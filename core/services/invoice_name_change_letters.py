"""Governed DOCX letters for confirmed invoice-name-change batches."""
from __future__ import annotations

import copy
import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from core.models import (
    InvoiceNameChangeBatch,
    InvoiceNameChangeLetterArtifact,
    InvoiceNameChangeLetterTemplate,
)
from core.services.document_sync import mark_drive_attempt, mark_drive_failure, mark_drive_success
from core.services.identifiers import normalize_kenyan_phone, normalize_national_id
from core.services.invoice_identity import normalize_person_name
from core.services.order_approval import GoogleDriveMediaStorage
from core.services.template_storage import GoogleDriveTemplateStorage, TemplateStorageError


DOCX_MIME_TYPE = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
WORD_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
W = f'{{{WORD_NS}}}'

# The first aliases are the literal sample placeholders in the supplied approved
# letter. Canonical aliases make later template revisions easier to understand.
PLACEHOLDERS = {
    'date': ('{17th August 2026}', '{DATE}'),
    'invoice_name': ('{JOHNSON NGANGA}', '{INVOICE NAME}'),
    'related_phone': ('{254723784369}', '{SPOUSE MOBILE NO}'),
    'applicant_name': ('{EUNICE MBEERE NGANGA}', '{APPLICANT NAME}'),
    'applicant_phone': ('{254721470557}', '{APPLICANT MOBILE NO}'),
    'applicant_id': ('{2336253}', '{APPLICANT ID NO}'),
    'sales_person': ('{ECOCONSERVE JAWABU [2026]}', '{SALES PERSON}'),
    'signatory': ('{Bedan Makumi}', '{SIGNATORY}'),
}
ROW_FIELDS = (
    'invoice_name', 'related_phone', 'applicant_name',
    'applicant_phone', 'applicant_id', 'sales_person',
)
GLOBAL_FIELDS = ('date', 'signatory')
ALIAS_TO_FIELD = {alias: field for field, aliases in PLACEHOLDERS.items() for alias in aliases}
TOKEN_RE = re.compile(r'\{[^{}]+\}')


class InvoiceNameChangeLetterError(ValueError):
    pass


@dataclass(frozen=True)
class TemplateInspection:
    row_index: int
    tokens: frozenset[str]


def _document_xml(data: bytes) -> tuple[zipfile.ZipFile, bytes]:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data), 'r')
        if len(archive.infolist()) > 500 or sum(info.file_size for info in archive.infolist()) > 50 * 1024 * 1024:
            archive.close()
            raise InvoiceNameChangeLetterError('The DOCX expands beyond the safe processing limit.')
        names = set(archive.namelist())
        if '[Content_Types].xml' not in names or 'word/document.xml' not in names:
            raise InvoiceNameChangeLetterError('Upload a valid Microsoft Word .docx file.')
        return archive, archive.read('word/document.xml')
    except (zipfile.BadZipFile, KeyError) as exc:
        raise InvoiceNameChangeLetterError('Upload a valid Microsoft Word .docx file.') from exc


def _text(element: ET.Element) -> str:
    return ''.join(node.text or '' for node in element.iter(f'{W}t'))


def inspect_template(data: bytes) -> TemplateInspection:
    archive, xml = _document_xml(data)
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as exc:
        archive.close()
        raise InvoiceNameChangeLetterError('The Word document body is invalid.') from exc
    finally:
        archive.close()

    all_text = _text(root)
    tokens = frozenset(TOKEN_RE.findall(all_text))
    unknown = sorted(token for token in tokens if token not in ALIAS_TO_FIELD)
    if unknown:
        raise InvoiceNameChangeLetterError(
            'Unknown template placeholder(s): ' + ', '.join(unknown)
        )
    fields = {ALIAS_TO_FIELD[token] for token in tokens}
    missing = [field for field in PLACEHOLDERS if field not in fields]
    if missing:
        raise InvoiceNameChangeLetterError(
            'Missing required placeholder(s): ' + ', '.join(missing)
        )

    row_index = -1
    for index, row in enumerate(root.iter(f'{W}tr')):
        row_fields = {
            ALIAS_TO_FIELD[token]
            for token in TOKEN_RE.findall(_text(row))
            if token in ALIAS_TO_FIELD
        }
        if set(ROW_FIELDS).issubset(row_fields):
            if row_index >= 0:
                raise InvoiceNameChangeLetterError('The template has more than one repeatable data row.')
            row_index = index
    if row_index < 0:
        raise InvoiceNameChangeLetterError(
            'Put all six row placeholders in one repeatable Word table row.'
        )
    return TemplateInspection(row_index=row_index, tokens=tokens)


def validate_template_file(uploaded_file) -> bytes:
    if not uploaded_file:
        raise InvoiceNameChangeLetterError('A DOCX template file is required.')
    filename = Path(str(getattr(uploaded_file, 'name', '') or '')).name
    if not filename.lower().endswith('.docx'):
        raise InvoiceNameChangeLetterError('The template must be a .docx file.')
    max_bytes = int(getattr(settings, 'INVOICE_NAME_CHANGE_TEMPLATE_MAX_FILE_SIZE_MB', 10)) * 1024 * 1024
    if int(getattr(uploaded_file, 'size', 0) or 0) > max_bytes:
        raise InvoiceNameChangeLetterError(
            f'The template exceeds the {max_bytes // (1024 * 1024)} MB limit.'
        )
    data = uploaded_file.read()
    try:
        uploaded_file.seek(0)
    except (AttributeError, OSError):
        pass
    inspect_template(data)
    return data


def _replace_text_group(element: ET.Element, values: dict[str, str]) -> None:
    nodes = list(element.iter(f'{W}t'))
    if not nodes:
        return
    combined = ''.join(node.text or '' for node in nodes)
    replaced = combined
    for alias, field in ALIAS_TO_FIELD.items():
        if field in values:
            replaced = replaced.replace(alias, values[field])
    if replaced != combined:
        nodes[0].text = replaced
        for node in nodes[1:]:
            node.text = ''


def _replace_tokens(element: ET.Element, values: dict[str, str]) -> None:
    """Replace split-run tokens without flattening separate paragraphs/cells."""
    paragraphs = list(element.iter(f'{W}p'))
    if paragraphs:
        for paragraph in paragraphs:
            _replace_text_group(paragraph, values)
    else:
        _replace_text_group(element, values)


def render_docx(template_data: bytes, *, globals_: dict[str, str], rows: list[dict[str, str]]) -> bytes:
    if not rows:
        raise InvoiceNameChangeLetterError('Add at least one invoice-name-change case to the letter.')
    inspection = inspect_template(template_data)
    archive, xml = _document_xml(template_data)
    root = ET.fromstring(xml)
    for prefix, uri in (
        ('w', WORD_NS),
        ('r', 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'),
        ('wp', 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing'),
        ('a', 'http://schemas.openxmlformats.org/drawingml/2006/main'),
        ('pic', 'http://schemas.openxmlformats.org/drawingml/2006/picture'),
    ):
        ET.register_namespace(prefix, uri)

    repeatable = list(root.iter(f'{W}tr'))[inspection.row_index]
    parent = next(parent for parent in root.iter() if repeatable in list(parent))
    insert_at = list(parent).index(repeatable)
    for offset, row_values in enumerate(rows):
        clone = copy.deepcopy(repeatable)
        _replace_tokens(clone, row_values)
        parent.insert(insert_at + offset, clone)
    parent.remove(repeatable)
    _replace_tokens(root, globals_)

    rendered_xml = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as target:
        for info in archive.infolist():
            payload = rendered_xml if info.filename == 'word/document.xml' else archive.read(info.filename)
            target.writestr(info, payload)
    archive.close()
    result = output.getvalue()
    remaining = TOKEN_RE.findall(_text(ET.fromstring(rendered_xml)))
    if remaining:
        raise InvoiceNameChangeLetterError('The generated letter still contains unresolved placeholders.')
    return result


def _ordinal(value: int) -> str:
    suffix = 'th' if 10 < value % 100 < 14 else {1: 'st', 2: 'nd', 3: 'rd'}.get(value % 10, 'th')
    return f'{value}{suffix}'


def formatted_nairobi_date(day=None) -> str:
    value = day or timezone.localdate()
    return f'{_ordinal(value.day)} {value:%B %Y}'


def _canonical_rows(batch: InvoiceNameChangeBatch) -> tuple[list[dict], list[str]]:
    items = list(
        batch.items.select_related(
            'farmer', 'relationship__related_person', 'original_invoice',
        ).order_by('created_at', 'id')
    )
    blockers: list[str] = []
    rows: list[dict] = []
    if not items:
        blockers.append('Add at least one case to this draft letter.')
    for position, item in enumerate(items, start=1):
        farmer = item.farmer
        person = item.relationship.related_person
        values = {
            'item_id': str(item.id),
            'invoice_name': normalize_person_name(person.full_name),
            'related_phone': normalize_kenyan_phone(person.primary_phone),
            'applicant_name': normalize_person_name(farmer.imab_customer_name or farmer.customer_name),
            'applicant_phone': normalize_kenyan_phone(farmer.primary_phone),
            'applicant_id': normalize_national_id(farmer.national_id),
            'sales_person': normalize_person_name(farmer.hb_sales_person),
        }
        labels = {
            'invoice_name': 'invoice name', 'related_phone': 'spouse/related-person mobile number',
            'applicant_name': 'applicant name', 'applicant_phone': 'applicant mobile number',
            'applicant_id': 'applicant ID number', 'sales_person': 'sales person',
        }
        for field in ROW_FIELDS:
            if not values[field]:
                blockers.append(f'Row {position}: {labels[field]} is missing.')
        if item.status != 'draft':
            blockers.append(f'Row {position}: the case is no longer a draft.')
        if item.relationship.status != item.relationship.STATUS_CONFIRMED:
            blockers.append(f'Row {position}: the household relationship is no longer confirmed.')
        original = item.original_identity or {}
        if original.get('normalized_name') and normalize_person_name(person.full_name) != original.get('normalized_name'):
            blockers.append(f'Row {position}: the verified invoice name changed after the case was created.')
        if original.get('normalized_phone') and normalize_kenyan_phone(person.primary_phone) != original.get('normalized_phone'):
            blockers.append(f'Row {position}: the verified related-person phone changed after the case was created.')
        rows.append(values)
    return rows, blockers


def source_fingerprint(rows: list[dict]) -> str:
    return hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('utf-8')
    ).hexdigest()


def letter_batch_readiness(batch: InvoiceNameChangeBatch) -> dict:
    rows, blockers = _canonical_rows(batch)
    if batch.status != 'draft':
        blockers.insert(0, 'Only a draft letter can be generated.')
    template = InvoiceNameChangeLetterTemplate.objects.filter(
        template_key=InvoiceNameChangeLetterTemplate.TEMPLATE_KEY, is_active=True,
    ).first()
    if not template:
        blockers.append('An active invoice-name-change DOCX template has not been uploaded in Django Admin.')
    return {
        'ready': not blockers,
        'blockers': blockers,
        'row_count': len(rows),
        'source_fingerprint': source_fingerprint(rows),
        'rows': rows,
        'template': template,
    }


def _template_bytes(template: InvoiceNameChangeLetterTemplate) -> bytes:
    if template.file:
        try:
            template.file.open('rb')
            data = template.file.read()
            template.file.close()
            if data:
                return data
        except (OSError, ValueError):
            pass
    if template.drive_file_id:
        return GoogleDriveTemplateStorage().download_template(template.drive_file_id)
    raise TemplateStorageError('The active DOCX template is not available locally or in Drive.')


def retry_letter_artifact_upload(artifact: InvoiceNameChangeLetterArtifact, *, actor: str = '') -> dict:
    if not artifact.file_content:
        return {'ok': False, 'error': 'The generated DOCX is not available for retry.'}
    mark_drive_attempt(artifact)
    try:
        file_id, url = GoogleDriveMediaStorage().upload(
            bytes(artifact.file_content), filename=artifact.filename, mime_type=artifact.content_type,
            id_number='invoice_name_changes', received_at=artifact.generated_at,
            workflow_key='Jawabu/Invoice Name Changes', record_type='Batch',
            record_key=str(artifact.batch.reference or artifact.batch_id),
        )
    except Exception as exc:
        artifact.status = artifact.STATUS_UPLOAD_FAILED
        mark_drive_failure(
            artifact, 'Drive upload failed; retry required.', error_field='drive_upload_error',
            update_fields=['status'],
        )
        return {'ok': False, 'error': str(exc)}
    artifact.status = artifact.STATUS_GENERATED
    mark_drive_success(
        artifact, file_id=file_id, url=url, error_field='drive_upload_error',
        update_fields=['status'],
    )
    return {'ok': True, 'file_id': file_id, 'url': url, 'actor': actor}


def generate_letter_artifact(
    batch: InvoiceNameChangeBatch, *, actor: str, client_request_id: str,
) -> tuple[InvoiceNameChangeLetterArtifact, bool]:
    actor = str(actor or '').strip()
    request_id = str(client_request_id or '').strip()
    if not actor:
        raise InvoiceNameChangeLetterError('The generating staff member could not be identified.')
    if not request_id:
        raise InvoiceNameChangeLetterError('A retry key is required to generate the letter safely.')

    existing = InvoiceNameChangeLetterArtifact.objects.filter(
        batch=batch, client_request_id=request_id,
    ).first()
    if existing:
        if not existing.drive_url:
            retry_letter_artifact_upload(existing, actor=actor)
        return existing, False

    with transaction.atomic():
        locked = InvoiceNameChangeBatch.objects.select_for_update().get(pk=batch.pk)
        existing = InvoiceNameChangeLetterArtifact.objects.filter(
            batch=locked, client_request_id=request_id,
        ).first()
        if existing:
            artifact, created = existing, False
        else:
            readiness = letter_batch_readiness(locked)
            if not readiness['ready']:
                raise InvoiceNameChangeLetterError(' '.join(readiness['blockers']))
            template = readiness['template']
            template_data = _template_bytes(template)
            inspection = inspect_template(template_data)
            del inspection
            template_checksum = hashlib.sha256(template_data).hexdigest()
            today = timezone.localdate()
            globals_ = {'date': formatted_nairobi_date(today), 'signatory': actor}
            rendered = render_docx(template_data, globals_=globals_, rows=readiness['rows'])
            version = (locked.letter_artifacts.aggregate(value=Max('version'))['value'] or 0) + 1
            safe_ref = re.sub(r'[^A-Za-z0-9_-]+', '_', locked.reference or str(locked.id)[:8]).strip('_')
            filename = f'Request_for_Change_of_Invoice_Names_{safe_ref}_v{version}.docx'
            artifact = InvoiceNameChangeLetterArtifact.objects.create(
                batch=locked, template=template, version=version, filename=filename,
                file_content=rendered, checksum=hashlib.sha256(rendered).hexdigest(),
                template_checksum=template_checksum,
                source_fingerprint=readiness['source_fingerprint'],
                payload_snapshot={
                    'date': globals_['date'], 'signatory': actor,
                    'rows': readiness['rows'], 'template_checksum': template_checksum,
                },
                generated_by=actor, client_request_id=request_id,
            )
            from core.services.invoice_identity import _record_case_event
            for item in locked.items.select_related('farmer').all():
                _record_case_event(
                    item.farmer,
                    action='invoice_name_change_letter_generated',
                    actor=actor,
                    request_id=f'invoice-name-change-letter:{artifact.id}:{item.id}',
                    metadata={
                        'batch_id': str(locked.id), 'artifact_id': str(artifact.id),
                        'version': version, 'item_id': str(item.id),
                    },
                )
            created = True
    if not artifact.drive_url:
        retry_letter_artifact_upload(artifact, actor=actor)
        artifact.refresh_from_db()
    return artifact, created


def artifact_is_current(artifact: InvoiceNameChangeLetterArtifact) -> bool:
    rows, blockers = _canonical_rows(artifact.batch)
    return not blockers and artifact.source_fingerprint == source_fingerprint(rows)


def serialize_artifact(artifact: InvoiceNameChangeLetterArtifact | None) -> dict | None:
    if not artifact:
        return None
    return {
        'id': str(artifact.id), 'version': artifact.version, 'status': artifact.status,
        'filename': artifact.filename, 'checksum': artifact.checksum,
        'drive_url': artifact.drive_url, 'drive_error': artifact.drive_upload_error,
        'is_current': artifact_is_current(artifact),
        'generated_by': artifact.generated_by,
        'generated_at': artifact.generated_at.isoformat(),
    }
