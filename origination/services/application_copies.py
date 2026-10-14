"""Authorized, revision-bound application copies. No review or provider writes."""
import hashlib
import json
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from django.core import signing
from django.db import transaction
from django.utils import timezone

from origination.models import LoanOriginationApplication
from origination.services.loan_origination import OriginationError, OriginationConflict

SALT = 'origination-application-copy-1'


class IncompleteCopyConfirmation(OriginationError):
    pass


def copy_filename(application, prepared_at):
    from origination.services.loan_origination import applicant_identity_snapshot
    identity = applicant_identity_snapshot(application.form_payload, schema=application.schema_snapshot,
                                           signer_rules=application.signer_rules_snapshot)
    name = identity.get('name') or application.reference_number
    product = (application.product_terms_snapshot or {}).get('product_name') or application.product_definition.name
    amount = application.form_payload.get('loan_amount')
    try:
        number = Decimal(str(amount))
        if not number.is_finite() or number < 0 or number.adjusted() > 15 or abs(number.as_tuple().exponent) > 6:
            raise InvalidOperation
        amount_label = 'KES ' + format(number, 'f')
    except (InvalidOperation, ValueError, TypeError):
        amount_label = 'Amount not set'
    def safe(value):
        text = ''.join(c for c in str(value) if not unicodedata.category(c).startswith('C'))
        return re.sub(r'\s+', ' ', re.sub(r'[<>:"/\\|?*]', ' ', text)).strip(' .')[:65]
    stamp = prepared_at.astimezone(ZoneInfo('Africa/Nairobi')).strftime('%d-%m-%Y %H-%M-%S')
    return f'{safe(name)} {safe(product)} {amount_label} {stamp}.pdf'


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


def copy_readiness(application: LoanOriginationApplication, *, require_complete=True) -> dict[str, str]:
    """Form completeness, without preview/signing side effects or PDF rendering."""
    from origination.services.origination_value_contracts import application_input_schema, entered_payload
    from origination.services.loan_origination import validate_form_payload
    from origination.services.origination_documents import _document_fields, document_context
    schema = application_input_schema(application)
    result = validate_form_payload(schema, entered_payload(application.form_payload, schema=schema), require_complete=require_complete)
    errors = dict(result.errors)
    for document in application.packet_documents.filter(selected=True).exclude(document_role='primary'):
        fields = _document_fields(document)
        context = document_context(application, document)
        local = validate_form_payload(
            {'fields':fields, 'input_rules_version':(document.schema_snapshot or {}).get('input_rules_version')},
            {field['key']:(context.get('_canonical_values') or {}).get(field['key'], context.get(field['key'])) for field in fields},
            require_complete=require_complete,
        )
        errors.update({f'{document.document_key}.{key}':message for key, message in local.errors.items()})
    return errors


def copy_content(application: LoanOriginationApplication, *, allow_incomplete=False) -> tuple[bytes, str]:
    if application.status in {'declined', 'expired', 'cancelled'}:
        raise OriginationError('This application is closed. A new application copy cannot be downloaded.')
    if application.status == 'approved':
        package = application.signing_packages.filter(status='fully_signed').order_by('-finalized_at', '-created_at').first()
        if not package:
            raise OriginationError('The signed application is not available yet.')
        from origination.services.origination_esign import signed_package_content
        package, content = signed_package_content(package_id=package.pk)
        return content, 'SIGNED'
    invalid = copy_readiness(application, require_complete=False)
    if invalid:
        raise OriginationError('Check the entered values before downloading.', errors=invalid)
    if not allow_incomplete and copy_readiness(application):
        raise IncompleteCopyConfirmation('Some required details are missing. Download this copy anyway?')
    from origination.services.origination_documents import render_packet
    content, _manifest = render_packet(application)
    return content, 'UNSIGNED'


@transaction.atomic
def prepare_copy(*, application_id, actor, revision: int, request_id: str, allow_incomplete=False) -> tuple[str, str]:
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
    if not isinstance(allow_incomplete, bool):
        raise OriginationError('Confirm whether to download the incomplete copy.')
    content, kind = copy_content(application, allow_incomplete=allow_incomplete)
    payload = {'actor': actor.pk, 'application': str(application.pk), 'revision': application.revision,
               'kind': kind, 'sha256': copy_fingerprint(application, content, kind),
               'allow_incomplete': allow_incomplete}
    from origination.services.loan_origination import _record_event
    replay = application.events.filter(action='application_copy_prepared', request_id=request_id).first()
    if replay:
        recorded = replay.after_values
        if any(recorded.get(key, False if key == 'allow_incomplete' else None) != value for key, value in payload.items()):
            raise OriginationConflict('This download request was already used for a different copy.')
        payload = dict(recorded)
    else:
        payload['filename'] = copy_filename(application, timezone.now())
        _record_event(application, 'application_copy_prepared', actor=actor, request_id=request_id, after=payload)
    return signing.dumps(payload, salt=SALT, compress=True), kind


def read_copy_token(token: str) -> dict:
    return signing.loads(token, salt=SALT, max_age=900)


@transaction.atomic
def retrieve_copy(payload: dict) -> tuple[bytes, str]:
    application = LoanOriginationApplication.objects.select_for_update().get(pk=payload['application'])
    if application.revision != payload['revision']:
        raise OriginationConflict('This copy has changed. Download the latest application.')
    content, kind = copy_content(application, allow_incomplete=payload.get('allow_incomplete', False))
    if kind != payload['kind'] or copy_fingerprint(application, content, kind) != payload['sha256']:
        raise OriginationConflict('This copy has changed. Download the latest application.')
    return content, payload.get('filename') or f'{application.reference_number}-{kind}.pdf'
