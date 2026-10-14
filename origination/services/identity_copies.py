"""Optional, subject-bound identity evidence on captured Origination forms."""
import hashlib

ROLES = {'borrower': ('borrower_id_copy', 'Borrower ID copy'),
         'guarantor_1': ('guarantor_1_id_copy', 'Guarantor 1 ID copy'),
         'guarantor_2': ('guarantor_2_id_copy', 'Guarantor 2 ID copy')}
ID_KEYS = {value[0] for value in ROLES.values()}


def collection_enabled(application) -> bool:
    return (application.status == 'draft'
            or (application.schema_snapshot or {}).get('identity_copy_policy') == 1
            or application.events.filter(action='fields_saved', metadata__identity_copy_policy=1).exists())


def identity_fields(application) -> dict:
    from origination.services.loan_origination import _applicant_identity_field_keys
    from origination.services.origination_value_contracts import enabled, packet_contract, person_fields
    fields = {item['key'] for item in (application.schema_snapshot or {}).get('fields', [])}
    result = {}
    applicant = _applicant_identity_field_keys(application.schema_snapshot, application.signer_rules_snapshot)
    if applicant.get('national_id'):
        result['borrower'] = applicant['national_id'][0]
    if enabled(application.schema_snapshot):
        for role, mapping in person_fields(packet_contract(application)).items():
            target = 'borrower' if role == 'applicant' else role
            if target in ROLES and mapping.get('national_id'):
                result[target] = mapping['national_id']
    # Older captured schemas use reviewed role identity mappings, not field labels.
    for rule in application.signer_rules_snapshot or []:
        role = rule.get('role')
        key = (rule.get('identity_fields') or {}).get('national_id')
        if role in ROLES and key in fields:
            result[role] = key
    from origination.services.origination_value_contracts import form_projection_enabled, application_input_schema
    if hasattr(application, 'template_configuration_snapshot') and form_projection_enabled(application):
        active = {field['key'] for field in application_input_schema(application).get('fields', [])}
        result = {role: key for role, key in result.items() if key in active}
    return result


def copy_options(application) -> list[dict]:
    if not collection_enabled(application):
        return []
    fields = identity_fields(application)
    result = []
    from core.services.identifiers import validate_kenyan_national_id
    for role, (key, label) in ROLES.items():
        field = fields.get(role)
        value = str((application.form_payload or {}).get(field) or '').strip()
        if not field or not value.isascii() or not validate_kenyan_national_id(value):
            continue
        result.append({'key': key, 'label': label, 'type': 'document', 'workflow': 'loan_origination',
                       'required': False, 'identity_role': role, 'identity_field': field,
                       'subject_sha256': hashlib.sha256(f'{role}:{value}'.encode()).hexdigest()})
    return result


def subject_binding(application, key: str) -> dict:
    if key not in ID_KEYS or not collection_enabled(application):
        return {}
    from origination.services.loan_origination import OriginationError
    item = next((item for item in copy_options(application) if item['key'] == key), None)
    if not item:
        raise OriginationError('Save this person’s National ID before adding their ID copy.')
    return {key: item[key] for key in ('identity_role', 'identity_field', 'subject_sha256')}


def prepare_identity_copy(front, back):
    from core.services.jbl_visit_documents import prepare_visit_documents, VisitDocumentError
    from origination.services.loan_origination import OriginationError
    from django.conf import settings
    files = [item for item in (front, back) if item is not None]
    maximum = settings.ORIGINATION_EVIDENCE_MAX_FILE_SIZE_MB * 1024 * 1024
    if any(item.size > maximum for item in files):
        raise OriginationError('An ID photo is too large. Choose a smaller clear photo.')
    if sum(item.size for item in files) > settings.ORIGINATION_EVIDENCE_MAX_TOTAL_UPLOAD_MB * 1024 * 1024:
        raise OriginationError('These photos are too large to upload together.')
    try:
        return prepare_visit_documents({'CLIENT_ID_FRONT': [front] if front else [],
                                        'CLIENT_ID_BACK': [back] if back else []})['CLIENT_ID'][0]
    except (VisitDocumentError, KeyError) as exc:
        raise OriginationError(str(exc) if isinstance(exc, VisitDocumentError)
                               else 'Add the front and back of the ID.') from exc
