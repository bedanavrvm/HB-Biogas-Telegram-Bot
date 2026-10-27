"""Authorized, revision-bound application copies. No review or provider writes."""
import hashlib
import json
import re
import unicodedata
from decimal import Decimal, InvalidOperation
from io import BytesIO
from zoneinfo import ZoneInfo

from django.core import signing
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from origination.models import LoanOriginationApplication
from origination.services.loan_origination import OriginationError, OriginationConflict

SALT = 'origination-application-copy-1'
SEPARATE_COPY_UNAVAILABLE = 'Separate copies are unavailable for this application. Download all documents instead.'
NOTICE_KEY = 'conditional_approval_notice'


class IncompleteCopyConfirmation(OriginationError):
    pass


def copy_filename(application, prepared_at, *, document_name=''):
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
    document_label = f' {safe(document_name)}' if document_name else ''
    return f'{safe(name)} {safe(product)} {amount_label}{document_label} {stamp}.pdf'


def _document_key(value):
    if value is None or value == '':
        return ''
    if not isinstance(value, str) or not re.fullmatch(r'[-a-zA-Z0-9_]{1,80}', value):
        raise OriginationError('Choose a document from this application.')
    return value


def _approved_package(application):
    if application.status == 'invalidated':
        return application.signing_packages.filter(
            Q(signed_document_hash__gt='') | Q(pending_signed_document__gt=b'')
        ).order_by('-created_at').first()
    return application.signing_packages.filter(status='fully_signed').order_by('-finalized_at', '-created_at').first()


def _manifest_ranges(package, *, page_count=None):
    """Only captured, complete page boundaries can identify a signed document."""
    manifest = package.document_manifest_snapshot
    if not isinstance(manifest, list) or not manifest:
        raise OriginationError(SEPARATE_COPY_UNAVAILABLE)
    ranges, offset = {}, 0
    for item in manifest:
        if not isinstance(item, dict):
            raise OriginationError(SEPARATE_COPY_UNAVAILABLE)
        key, count = item.get('key'), item.get('page_count')
        if (not isinstance(key, str) or not re.fullmatch(r'[-a-zA-Z0-9_]{1,80}', key)
                or key in ranges or type(count) is not int or count < 1):
            raise OriginationError(SEPARATE_COPY_UNAVAILABLE)
        ranges[key] = {'start': offset, 'count': count,
                       'name': 'Main LAF' if key == 'primary' else str(item.get('name') or 'Supporting document')}
        offset += count
    if 'primary' not in ranges or (page_count is not None and offset != page_count):
        raise OriginationError(SEPARATE_COPY_UNAVAILABLE)
    return ranges


def signed_document_content(package, content: bytes, document_key: str) -> tuple[bytes, dict]:
    """Extract only manifest-bound pages from already hash-verified bundle bytes."""
    from pypdf import PdfReader, PdfWriter
    from pypdf.errors import PdfReadError
    try:
        reader = PdfReader(BytesIO(content))
        ranges = _manifest_ranges(package, page_count=len(reader.pages))
        selected = ranges.get(_document_key(document_key)) if document_key != NOTICE_KEY else None
        if not selected:
            raise OriginationError('This document is not included in the signed application.')
        writer = PdfWriter()
        for page in range(selected['start'], selected['start'] + selected['count']):
            writer.add_page(reader.pages[page])
        output = BytesIO()
        writer.write(output)
    except (PdfReadError, ValueError, KeyError, TypeError) as exc:
        raise OriginationError(SEPARATE_COPY_UNAVAILABLE) from exc
    return output.getvalue(), selected


def download_choices(application):
    """Authorized-detail metadata only; never render PDFs or contact storage."""
    if application.status in {'declined', 'expired', 'cancelled'}:
        return []
    choices = [{'document_key': '', 'label': 'All documents', 'description': 'Combined PDF', 'available': True}]
    if application.status in {'approved', 'invalidated'}:
        package = _approved_package(application)
        if not package or (not package.signed_document_hash and not package.pending_signed_document):
            choices[0].update(available=False, reason='The signed application is not available yet.')
            return choices
        try:
            ranges = _manifest_ranges(package)
        except OriginationError:
            return choices + [{'document_key': 'primary', 'label': 'Individual documents',
                               'available': False, 'reason': SEPARATE_COPY_UNAVAILABLE}]
        return choices + [{'document_key': key, 'label': value['name'], 'description': 'Signed PDF', 'available': True}
                          for key, value in ranges.items() if key != NOTICE_KEY]
    documents = list(application.packet_documents.filter(selected=True).order_by('display_order', 'document_key'))
    primary = next((item for item in documents if item.document_key == 'primary'), None)
    if not documents or primary:
        choices.append({'document_key': 'primary', 'label': 'Main LAF',
                        'description': primary.name if primary and primary.name != 'Main LAF' else 'PDF', 'available': True})
    choices.extend({'document_key': item.document_key, 'label': item.name or 'Supporting document',
                    'description': 'PDF', 'available': True} for item in documents if item.document_key != 'primary')
    return choices


def copy_fingerprint(application: LoanOriginationApplication, content: bytes, kind: str, *, document_key='', source=None) -> str:
    # Unsigned rendering metadata can change between requests. Bind its saved
    # inputs instead; final signed copies must still match the exact bytes.
    if kind == 'SIGNED':
        if document_key:
            # PDF extraction metadata is not signing evidence. Bind the verified
            # original bundle, captured manifest and selected range instead.
            return hashlib.sha256(json.dumps([document_key, source], sort_keys=True).encode()).hexdigest()
        return hashlib.sha256(content).hexdigest()
    captured = [application.schema_snapshot, application.form_payload,
                application.template_configuration_snapshot, application.product_quote_snapshot,
                list(application.packet_documents.filter(selected=True).order_by('document_key').values(
                    'document_key', 'template_snapshot', 'field_payload', 'schema_snapshot'))]
    if document_key:
        captured.append(document_key)
    return hashlib.sha256(json.dumps(captured, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


def copy_readiness(application: LoanOriginationApplication, *, require_complete=True, document_key='') -> dict[str, str]:
    """Form completeness, without preview/signing side effects or PDF rendering."""
    from origination.services.origination_value_contracts import application_input_schema, application_document_schema, entered_payload
    from origination.services.loan_origination import validate_form_payload
    from origination.services.origination_documents import _document_fields, document_context
    if document_key:
        document = _selected_document(application, document_key)
        schema = application_document_schema(application, document if document_key != 'primary' else None)
        schema['fields'] = [field for field in schema.get('fields', [])
                            if field.get('source_type') != 'system'
                            and (field.get('value_contract') or {}).get('source', 'entered') == 'entered']
        values = {**application.form_payload, **(document.field_payload if document else {})}
        result = validate_form_payload(schema, entered_payload(values, schema=schema), require_complete=require_complete)
        return {(key if document_key == 'primary' else f'{document_key}.{key}'): message
                for key, message in result.errors.items()}
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


def _selected_document(application, document_key):
    document = application.packet_documents.filter(document_key=document_key).first()
    if document is None and document_key == 'primary' and not application.packet_documents.exists():
        return None  # Historical single-LAF application.
    if not document or not document.selected:
        raise OriginationError('This document is not selected for the application.')
    return document


def _copy_result(application, *, allow_incomplete=False, document_key=''):
    if application.status in {'declined', 'expired', 'cancelled'}:
        raise OriginationError('This application is closed. A new application copy cannot be downloaded.')
    if application.status in {'approved', 'invalidated'}:
        package = _approved_package(application)
        if not package:
            raise OriginationError('The signed application is not available yet.')
        from origination.services.origination_esign import signed_package_content
        if application.status == 'invalidated' and not package.signed_document_hash:
            event = application.events.filter(action='application_invalidated').order_by('-occurred_at').first()
            content = bytes(package.pending_signed_document or b'')
            expected = (event.metadata.get('historical_copies') or {}).get(str(package.pk)) if event else ''
            if not expected or hashlib.sha256(content).hexdigest() != expected:
                raise OriginationError('The historical signed copy failed its integrity check.')
        else:
            package, content = signed_package_content(package_id=package.pk)
        if not document_key:
            return content, 'SIGNED', '', None
        content, selected = signed_document_content(package, content, document_key)
        source = {'package_id': str(package.pk), 'sha256': package.signed_document_hash,
                  'manifest_sha256': hashlib.sha256(json.dumps(package.document_manifest_snapshot, sort_keys=True).encode()).hexdigest(),
                  'start': selected['start'], 'count': selected['count']}
        return content, 'SIGNED', selected['name'], source
    document = _selected_document(application, document_key) if document_key else None
    invalid = copy_readiness(application, require_complete=False, document_key=document_key)
    if invalid:
        raise OriginationError('Check the entered values before downloading.', errors=invalid)
    if not allow_incomplete and copy_readiness(application, document_key=document_key):
        raise IncompleteCopyConfirmation('Some required details are missing. Download this copy anyway?')
    from origination.services.origination_documents import render_packet, render_document
    if document_key:
        content = render_document(application, document_key)
    else:
        content, _manifest = render_packet(application)
    name = 'Main LAF' if document_key == 'primary' else document.name if document else ''
    return content, 'UNSIGNED', name, None


def copy_content(application: LoanOriginationApplication, *, allow_incomplete=False, document_key='') -> tuple[bytes, str]:
    content, kind, _name, _source = _copy_result(application,
        allow_incomplete=allow_incomplete, document_key=_document_key(document_key))
    return content, kind


@transaction.atomic
def prepare_copy(*, application_id, actor, revision: int, request_id: str, allow_incomplete=False, document_key='') -> tuple[str, str]:
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
    document_key = _document_key(document_key)
    content, kind, document_name, source = _copy_result(application,
        allow_incomplete=allow_incomplete, document_key=document_key)
    payload = {'actor': actor.pk, 'application': str(application.pk), 'revision': application.revision,
               'kind': kind, 'sha256': copy_fingerprint(application, content, kind, document_key=document_key, source=source),
               'allow_incomplete': allow_incomplete, 'document_key': document_key}
    if source:
        payload['document_source'] = source
    from origination.services.loan_origination import _record_event
    replay = application.events.filter(action='application_copy_prepared', request_id=request_id).first()
    if replay:
        recorded = replay.after_values
        defaults = {'allow_incomplete': False, 'document_key': ''}
        if any(recorded.get(key, defaults.get(key)) != value for key, value in payload.items()):
            raise OriginationConflict('This download request was already used for a different copy.')
        payload = dict(recorded)
    else:
        payload['filename'] = copy_filename(application, timezone.now(), document_name=document_name)
        _record_event(application, 'application_copy_prepared', actor=actor, request_id=request_id, after=payload)
    return signing.dumps(payload, salt=SALT, compress=True), kind


def read_copy_token(token: str) -> dict:
    return signing.loads(token, salt=SALT, max_age=900)


@transaction.atomic
def retrieve_copy(payload: dict) -> tuple[bytes, str]:
    application = LoanOriginationApplication.objects.select_for_update().get(pk=payload['application'])
    if application.revision != payload['revision']:
        raise OriginationConflict('This copy has changed. Download the latest application.')
    document_key = _document_key(payload.get('document_key'))
    content, kind, _name, source = _copy_result(application,
        allow_incomplete=payload.get('allow_incomplete', False), document_key=document_key)
    if (kind != payload['kind'] or copy_fingerprint(application, content, kind,
            document_key=document_key, source=source) != payload['sha256']
            or (source and source != payload.get('document_source'))):
        raise OriginationConflict('This copy has changed. Download the latest application.')
    return content, payload.get('filename') or f'{application.reference_number}-{kind}.pdf'
