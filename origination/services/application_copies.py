"""Authorized, revision-bound application copies. No review or provider writes."""
import hashlib
import json

from django.core import signing
from django.db import transaction

from origination.models import LoanOriginationApplication
from origination.services.loan_origination import OriginationError, OriginationConflict

SALT = 'origination-application-copy-1'


def copy_fingerprint(application: LoanOriginationApplication, content: bytes, kind: str) -> str:
    # Unsigned rendering metadata can change between requests. Bind its saved
    # inputs instead; final signed copies must still match the exact bytes.
    if kind == 'SIGNED':
        return hashlib.sha256(content).hexdigest()
    captured = [application.schema_snapshot, application.form_payload,
                application.template_configuration_snapshot, application.product_quote_snapshot,
                list(application.packet_documents.filter(selected=True).order_by('document_key').values(
                    'document_key', 'template_snapshot', 'field_payload', 'schema_snapshot'))]
    return hashlib.sha256(json.dumps(captured, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


def copy_readiness(application: LoanOriginationApplication) -> dict[str, str]:
    """Form completeness, without preview/signing side effects or PDF rendering."""
    from origination.services.origination_value_contracts import application_input_schema, entered_payload
    from origination.services.loan_origination import validate_form_payload
    from origination.services.origination_documents import _document_fields, document_context
    schema = application_input_schema(application)
    result = validate_form_payload(schema, entered_payload(application.form_payload, schema=schema), require_complete=True)
    errors = dict(result.errors)
    for document in application.packet_documents.filter(selected=True).exclude(document_role='primary'):
        fields = _document_fields(document)
        context = document_context(application, document)
        local = validate_form_payload(
            {'fields':fields, 'input_rules_version':(document.schema_snapshot or {}).get('input_rules_version')},
            {field['key']:(context.get('_canonical_values') or {}).get(field['key'], context.get(field['key'])) for field in fields},
            require_complete=True,
        )
        errors.update({f'{document.document_key}.{key}':message for key, message in local.errors.items()})
    return errors


def copy_content(application: LoanOriginationApplication) -> tuple[bytes, str]:
    if application.status in {'declined', 'expired', 'cancelled'}:
        raise OriginationError('This application is closed. A new application copy cannot be downloaded.')
    if application.status == 'approved':
        package = application.signing_packages.filter(status='fully_signed').order_by('-finalized_at', '-created_at').first()
        if not package:
            raise OriginationError('The signed application is not available yet.')
        from origination.services.origination_esign import signed_package_content
        package, content = signed_package_content(package_id=package.pk)
        return content, 'SIGNED'
    errors = copy_readiness(application)
    if errors:
        raise OriginationError('Complete the required fields before downloading.', errors=errors)
    from origination.services.origination_documents import render_packet
    content, _manifest = render_packet(application)
    return content, 'UNSIGNED'


@transaction.atomic
def prepare_copy(*, application_id, actor, revision: int, request_id: str) -> tuple[str, str]:
    from origination.services.loan_origination import _require_request_id
    request_id = _require_request_id(request_id)
    application = LoanOriginationApplication.objects.select_for_update().get(pk=application_id)
    if int(revision) != application.revision:
        raise OriginationConflict('This application changed. Refresh before downloading.')
    from core.services.workflow_access import workflow_access_decision
    from core.services.telegram_identity import user_access
    from origination.services.origination_access import application_presentation_mode
    access = user_access(actor, 'loan_origination')
    if not workflow_access_decision(actor, 'loan_origination', 'origination.view',
            access=access, resource=application).allowed or application_presentation_mode(
                application, user=actor, access=access) != 'full':
        raise OriginationError('You do not have access to this application.')
    content, kind = copy_content(application)
    payload = {'actor': actor.pk, 'application': str(application.pk), 'revision': application.revision,
               'kind': kind, 'sha256': copy_fingerprint(application, content, kind)}
    from origination.services.loan_origination import _record_event
    replay = application.events.filter(action='application_copy_prepared', request_id=request_id).first()
    if replay and replay.after_values != payload:
        raise OriginationConflict('This download request was already used for a different copy.')
    if not replay:
        _record_event(application, 'application_copy_prepared', actor=actor, request_id=request_id, after=payload)
    return signing.dumps(payload, salt=SALT, compress=True), kind


def read_copy_token(token: str) -> dict:
    return signing.loads(token, salt=SALT, max_age=900)


@transaction.atomic
def retrieve_copy(payload: dict) -> tuple[bytes, str]:
    application = LoanOriginationApplication.objects.select_for_update().get(pk=payload['application'])
    if application.revision != payload['revision']:
        raise OriginationConflict('This copy has changed. Download the latest application.')
    content, kind = copy_content(application)
    if kind != payload['kind'] or copy_fingerprint(application, content, kind) != payload['sha256']:
        raise OriginationConflict('This copy has changed. Download the latest application.')
    return content, f'{application.reference_number}-{kind}.pdf'
