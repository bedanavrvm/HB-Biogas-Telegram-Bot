"""Portal-owned FarmUp intake plus review-only SysUp staging and archival.

FarmUp reuses the established parser and commit service behind a scoped,
revision-bound Portal contract. SysUp remains source review only.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import mimetypes
import re
from datetime import date
from pathlib import PurePath
from typing import Any

from django.conf import settings
from django.core import signing
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.models import GroupSheetConfiguration, IntegrationOperation, JawabuFarmerUploadBatch
from core.services.compliance_audit import record_event
from core.services.document_sync import mark_drive_attempt, mark_drive_failure, mark_drive_success
from core.services.external_resilience import ExternalOperationError, execute_operation, reserve_operation


IMPORT_KIND_FARMUP = 'farmup'
IMPORT_KIND_SYSUP = 'sysup'
IMPORT_KINDS = frozenset({IMPORT_KIND_FARMUP, IMPORT_KIND_SYSUP})
SOURCE_MODEL = 'core.JawabuFarmerUploadBatch'
ARCHIVE_OPERATION = 'portal_import_drive_archive'
_JAWABU_IMPORT_WORKFLOW_TYPE = 'jawabu_homebiogas'
_SAFE_FILENAME = re.compile(r'[^A-Za-z0-9._ -]+')


class PortalImportError(ValueError):
    """A stable validation failure suitable for a staff-facing API response."""


class PortalImportConflict(PortalImportError):
    """The batch revision or idempotency payload no longer matches."""


FARMUP_EDITABLE_FIELDS = (
    'Customer Name', 'National ID', 'Primary Phone', 'Secondary Phone',
    'Application Action', 'Additional Unit Reason', 'County',
    'HBG Visit Date', 'Deposit Paid to HB', 'HB Sales Person',
)
FARMUP_REQUIRED_FIELDS = (
    'customer_name', 'national_id', 'primary_phone', 'secondary_phone',
    'county', 'sign_date', 'actual_receipts', 'hb_sales_person',
)
FARMUP_FIELD_LABELS = {
    'customer_name': 'Customer Name',
    'national_id': 'National ID',
    'primary_phone': 'Primary Phone',
    'secondary_phone': 'Secondary Phone',
    'county': 'County',
    'sub_county': 'Constituency',
    'village': 'Village',
    'lead_source': 'Lead Source',
    'sign_date': 'HBG Visit Date',
    'comments': 'HBG Visit Comment',
    'actual_receipts': 'Deposit Paid to HB',
    'hb_sales_person': 'HB Sales Person',
}
_FARMUP_REVISION_SALT = 'portal-farmup-batch-revision-v1'
FARMUP_DISPOSITION_COMMIT = 'commit_now'
FARMUP_DISPOSITION_HOLD = 'hold'
FARMUP_DISPOSITION_EXCLUDE = 'exclude'
FARMUP_TERMINAL_DISPOSITIONS = frozenset({'committed', 'already_committed', 'excluded'})


def parse_farmup_period(value: Any, *, required: bool = False) -> date | None:
    text = str(value or '').strip()
    if not text:
        if required:
            raise PortalImportError('Choose the month represented by this FarmUp worklist.')
        return None
    try:
        year_text, month_text = text.split('-', 1)
        return date(int(year_text), int(month_text), 1)
    except (TypeError, ValueError):
        raise PortalImportError('FarmUp month must use YYYY-MM, for example 2026-08.')


def _review_source_fingerprint(row: dict) -> str:
    source = {
        str(key): value for key, value in dict(row or {}).items()
        if not str(key).startswith('_') and key not in {
            'approved', 'warning_acknowledged', 'update_acknowledged',
            'disposition', 'row_id',
        }
    }
    return hashlib.sha256(json.dumps(
        source, sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=str,
    ).encode('utf-8')).hexdigest()


def _review_identity_key(row: dict) -> str:
    from core.services.identifiers import normalize_kenyan_phone, normalize_national_id

    national_id = normalize_national_id(row.get('National ID'))
    phone = normalize_kenyan_phone(row.get('Primary Phone'))
    if national_id:
        material = f'national-id:{national_id}'
        return hashlib.sha256(material.encode('utf-8')).hexdigest()
    if phone:
        material = f'phone:{phone}'
        return hashlib.sha256(material.encode('utf-8')).hexdigest()
    return _review_source_fingerprint(row)


def _initialize_review_rows(rows: list[dict]) -> list[dict]:
    prepared = []
    seen: set[str] = set()
    for index, original in enumerate(rows, start=1):
        row = dict(original or {})
        row['row_id'] = row.get('row_id') or index
        row['_source_fingerprint'] = _review_source_fingerprint(row)
        row['_identity_key'] = _review_identity_key(row)
        row['_source_state'] = row.get('_source_state') or 'current'
        row['disposition'] = row.get('disposition') or (
            FARMUP_DISPOSITION_COMMIT if row.get('approved') else FARMUP_DISPOSITION_HOLD
        )
        row['approved'] = row['disposition'] == FARMUP_DISPOSITION_COMMIT
        if row['_identity_key'] in seen:
            row['_duplicate_in_upload'] = True
            row['approved'] = False
            row['disposition'] = FARMUP_DISPOSITION_HOLD
        seen.add(row['_identity_key'])
        prepared.append(row)
    return prepared


def resolve_import_group(*, allowed_group_ids: set[str] | None = None) -> GroupSheetConfiguration:
    """Resolve the one configured Jawabu HomeBiogas import destination.

    FarmUp and SysUp are Portal-owned intake routes, not a multi-group import
    tool. Letting the browser choose a Telegram group made the upload route
    ambiguous and could block an authorised IT user before sending the file.
    Ordinary AccessGrant group scope is still enforced here.
    """
    configurations = [
        config
        for config in GroupSheetConfiguration.objects.filter(enabled=True).order_by('group_id')
        if str((config.workflow or {}).get('type') or '').strip() == _JAWABU_IMPORT_WORKFLOW_TYPE
    ]
    if not configurations:
        raise PortalImportError('The Jawabu HomeBiogas import workflow is not configured. Ask IT to configure it before staging files.')
    if len(configurations) > 1:
        raise PortalImportError('More than one Jawabu HomeBiogas import workflow is configured. Ask IT to correct the configuration before staging files.')
    configuration = configurations[0]
    if allowed_group_ids is not None and str(configuration.group_id) not in allowed_group_ids:
        raise PortalImportError('Your Portal import access does not cover the configured Jawabu HomeBiogas workflow.')
    return configuration


def _source_limit_bytes(kind: str) -> int:
    if kind == IMPORT_KIND_FARMUP:
        max_mb = max(1, int(getattr(settings, 'FARMUP_MAX_FILE_SIZE_MB', 5) or 5))
    else:
        max_mb = max(1, int(getattr(settings, 'SYSUP_MAX_FILE_SIZE_MB', 5) or 5))
    return max_mb * 1024 * 1024


def _validated_source(kind: str, *, filename: str, content: bytes) -> tuple[str, str, bytes]:
    normalized_kind = str(kind or '').strip().lower()
    if normalized_kind not in IMPORT_KINDS:
        raise PortalImportError('Select either FarmUp or SysUp.')
    safe_name = PurePath(str(filename or '')).name.strip()
    lower_name = safe_name.lower()
    if normalized_kind == IMPORT_KIND_FARMUP and not lower_name.endswith('.csv'):
        raise PortalImportError('FarmUp accepts a Jawabu Farmers CSV file only.')
    if normalized_kind == IMPORT_KIND_SYSUP and not lower_name.endswith(('.csv', '.xlsx')):
        raise PortalImportError('SysUp accepts a Customers Without Loans CSV or XLSX export.')
    payload = bytes(content or b'')
    if not payload:
        raise PortalImportError('Choose an import file before staging it.')
    if len(payload) > _source_limit_bytes(normalized_kind):
        raise PortalImportError('This import exceeds the configured safe upload size. Split it into smaller files and retry.')
    mime_type = mimetypes.guess_type(safe_name)[0] or 'application/octet-stream'
    return normalized_kind, safe_name, payload


def _decode_farmup_csv(content: bytes) -> str:
    for encoding in ('utf-8-sig', 'utf-8'):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise PortalImportError('FarmUp CSV must be UTF-8 encoded.')


def _farmup_mapping_digest(decisions: list[dict]) -> str:
    normalized = [
        {
            'source_id': str(item.get('source_id') or ''),
            'target_field': str(item.get('target_field') or ''),
        }
        for item in decisions
    ]
    return hashlib.sha256(json.dumps(
        normalized, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
    ).encode('utf-8')).hexdigest()


def farmup_mapping_analysis(csv_text: str, decisions: list[dict] | None = None) -> dict[str, Any]:
    """Describe a positional, explicit source-to-canonical FarmUp mapping."""
    from core.services.jawabu_master import (
        CANONICAL_FIELDS, build_header_map, read_csv_rows,
    )

    raw_table = list(csv.reader(io.StringIO(csv_text)))
    if not raw_table or not any(str(value or '').strip() for value in raw_table[0]):
        raise PortalImportError('FarmUp CSV has no usable header row.')
    overflow_rows = [
        index for index, values in enumerate(raw_table[1:], start=2)
        if len(values) > len(raw_table[0]) and any(str(value or '').strip() for value in values)
    ]
    if overflow_rows:
        sample = ', '.join(str(value) for value in overflow_rows[:5])
        raise PortalImportError(f'FarmUp CSV rows {sample} contain more values than the header row.')
    rows, headers = read_csv_rows(io.StringIO(csv_text))
    if decisions is not None:
        submitted_ids = [str(item.get('source_id') or '') for item in decisions if isinstance(item, dict)]
        if len(submitted_ids) != len(set(submitted_ids)) or set(submitted_ids) != set(headers):
            raise PortalImportError('Every CSV column must be mapped or explicitly ignored exactly once.')
    inferred = build_header_map(headers)
    inferred_by_source = {source: field for field, source in inferred.items()}
    supplied = {
        str(item.get('source_id') or ''): str(item.get('target_field') or '')
        for item in (decisions or []) if isinstance(item, dict)
    }
    columns = []
    used_targets: set[str] = set()
    for index, source_id in enumerate(headers):
        target = supplied.get(source_id) if decisions is not None else inferred_by_source.get(source_id, '')
        if target and target not in CANONICAL_FIELDS:
            raise PortalImportError(f'Column {source_id} was mapped to an unsupported FarmUp field.')
        if target and target in used_targets:
            raise PortalImportError(f'More than one CSV column was mapped to {FARMUP_FIELD_LABELS.get(target, target)}.')
        if target:
            used_targets.add(target)
        # The established export intentionally uses the second Sign Date.
        known_ignored = source_id == 'Sign Date' and inferred.get('sign_date') == 'Sign Date__2'
        resolution = 'manual' if decisions is not None else ('auto' if target else ('ignored' if known_ignored else 'unresolved'))
        samples = []
        for _row_number, row in rows:
            value = str(row.get(source_id) or '').strip()
            if value and value not in samples:
                samples.append(value)
            if len(samples) == 3:
                break
        display_header = re.sub(r'__\d+$', '', source_id)
        columns.append({
            'source_id': source_id,
            'source_header': display_header,
            'column_number': index + 1,
            'target_field': target,
            'suggested_field': inferred_by_source.get(source_id, ''),
            'resolution': resolution,
            'sample_values': samples,
        })
    unresolved = [item['source_id'] for item in columns if item['resolution'] == 'unresolved']
    missing_required = [field for field in FARMUP_REQUIRED_FIELDS if field not in used_targets]
    normalized_decisions = [
        {'source_id': item['source_id'], 'target_field': item['target_field']}
        for item in columns
    ]
    return {
        'version': 1,
        'state': 'needs_mapping' if unresolved else ('confirmed' if decisions is not None else 'auto_ready'),
        'columns': columns,
        'canonical_fields': [
            {'key': field, 'label': FARMUP_FIELD_LABELS.get(field, field.replace('_', ' ').title()), 'required': field in FARMUP_REQUIRED_FIELDS}
            for field in CANONICAL_FIELDS
        ],
        'unresolved_columns': unresolved,
        'missing_required_fields': missing_required,
        'source_row_count': sum(1 for _number, row in rows if any(str(value or '').strip() for value in row.values())),
        'digest': _farmup_mapping_digest(normalized_decisions),
    }


def _mapping_without_samples(mapping: dict[str, Any]) -> dict[str, Any]:
    payload = dict(mapping)
    payload['columns'] = []
    for item in mapping.get('columns', []):
        column = dict(item)
        column.pop('sample_values', None)
        payload['columns'].append(column)
    return payload


def _batch_mapping_payload(batch: JawabuFarmerUploadBatch, *, include_samples: bool = False) -> dict[str, Any]:
    mapping = batch.mapping if isinstance(batch.mapping, dict) else {}
    if mapping.get('version') == 1:
        payload = dict(mapping)
        payload['columns'] = [dict(item) for item in mapping.get('columns', [])]
    elif batch.source_content:
        payload = farmup_mapping_analysis(_decode_farmup_csv(bytes(batch.source_content)))
        # Existing standalone and pre-Portal batches were already parsed with
        # the established alias rules. Preserve that usable review surface;
        # guided mapping applies only to new Portal staging or an explicit
        # remap request.
        if batch.parsed_rows:
            payload['state'] = 'legacy_ready'
    else:
        payload = {'version': 1, 'state': 'legacy', 'columns': [], 'canonical_fields': [], 'unresolved_columns': [], 'missing_required_fields': [], 'digest': ''}
    if include_samples and batch.source_content and payload.get('columns'):
        decisions = [
            {'source_id': item.get('source_id'), 'target_field': item.get('target_field', '')}
            for item in payload['columns']
        ]
        sampled = farmup_mapping_analysis(_decode_farmup_csv(bytes(batch.source_content)), decisions)
        samples = {item['source_id']: item.get('sample_values', []) for item in sampled['columns']}
        for column in payload['columns']:
            column['sample_values'] = samples.get(column.get('source_id'), [])
    elif not include_samples:
        for column in payload.get('columns', []):
            column.pop('sample_values', None)
    return payload


def _decode_sysup_csv(content: bytes) -> str:
    """Decode the CSV encodings accepted by the existing SysUp parser."""
    for encoding in ('utf-8-sig', 'utf-8', 'cp1252'):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise PortalImportError('SysUp CSV could not be read. Export it as UTF-8 CSV and retry.')


def _source_csv_table_page(
    content: bytes,
    *,
    decoder,
    page: int,
    page_size: int,
) -> dict[str, list[list[str]] | list[str]]:
    """Return one raw CSV page without exposing parser or review-only fields.

    ``parsed_rows`` deliberately contains normalized and matching metadata used
    by the command workflows.  The Portal's review-only screen instead needs
    to show the retained source exactly in its own column order, so it reads
    the original CSV values as a table of lists rather than dictionaries.
    Lists also preserve duplicate or blank source headers without inventing
    replacement column names.
    """
    reader = csv.reader(io.StringIO(decoder(content)))
    try:
        headers = next(reader)
    except StopIteration:
        return {'headers': [], 'rows': []}

    start = max(0, (max(1, page) - 1) * max(1, page_size))
    end = start + max(1, page_size)
    rows: list[list[str]] = []
    visible_position = 0
    for values in reader:
        if not any(str(value or '').strip() for value in values):
            continue
        if start <= visible_position < end:
            rows.append(list(values[:len(headers)]) + [''] * max(0, len(headers) - len(values)))
        visible_position += 1
        if visible_position >= end:
            break
    return {'headers': list(headers), 'rows': rows}


def _source_xlsx_table_page(
    content: bytes,
    *,
    page: int,
    page_size: int,
) -> dict[str, list[list[str]] | list[str]]:
    """Return a raw SysUp workbook page using the same header detection rule.

    This intentionally stops after the requested page.  It avoids loading an
    entire workbook into the Portal response merely to render the source data
    that an IT reviewer asked to inspect.
    """
    try:
        from openpyxl import load_workbook
        from core.services.system_export import REQUIRED_HEADER_KEYS, _cell_text, _header_key

        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:
        raise PortalImportError('The retained SysUp workbook could not be read for review.') from exc

    try:
        sheet = workbook.active
        header_row_number = None
        headers: list[str] = []
        for row_number, row in enumerate(sheet.iter_rows(min_row=1, max_row=25, values_only=True), start=1):
            candidate = [_cell_text(value) for value in row]
            keys = {_header_key(value) for value in candidate if value}
            if set(REQUIRED_HEADER_KEYS).issubset(keys):
                header_row_number = row_number
                headers = candidate
                break
        if header_row_number is None:
            raise PortalImportError('The retained SysUp workbook has no recognizable header row.')

        start = max(0, (max(1, page) - 1) * max(1, page_size))
        end = start + max(1, page_size)
        rows: list[list[str]] = []
        visible_position = 0
        for row in sheet.iter_rows(min_row=header_row_number + 1, values_only=True):
            values = [_cell_text(value) for value in row]
            if not any(values):
                continue
            if start <= visible_position < end:
                rows.append(values[:len(headers)] + [''] * max(0, len(headers) - len(values)))
            visible_position += 1
            if visible_position >= end:
                break
        return {'headers': headers, 'rows': rows}
    finally:
        workbook.close()


def source_table_page(
    batch: JawabuFarmerUploadBatch,
    *,
    page: int,
    page_size: int,
) -> dict[str, list[list[str]] | list[str]]:
    """Return the original staged import columns and values for Portal review.

    This is intentionally presentation-only.  It never re-runs matching,
    normalization, or a customer-data commit and does not expose derived
    parser fields such as Import Status, matched customer, or cleaning notes.
    """
    content = bytes(batch.source_content or b'')
    if not content:
        raise PortalImportError('The original source file is unavailable for this staged import.')
    if batch.import_kind == 'farmers':
        return _source_csv_table_page(
            content,
            decoder=_decode_farmup_csv,
            page=page,
            page_size=page_size,
        )
    if str(batch.source_filename or '').lower().endswith('.xlsx'):
        return _source_xlsx_table_page(content, page=page, page_size=page_size)
    return _source_csv_table_page(
        content,
        decoder=_decode_sysup_csv,
        page=page,
        page_size=page_size,
    )


def _existing_replay(request_id: str, *, kind: str, source_hash: str) -> JawabuFarmerUploadBatch | None:
    if not request_id:
        return None
    batch = JawabuFarmerUploadBatch.objects.filter(upload_request_id=request_id).first()
    if batch is None:
        return None
    if batch.source_content_hash != source_hash or batch.import_kind != ('farmers' if kind == IMPORT_KIND_FARMUP else 'system_export'):
        raise PortalImportError('This retry key belongs to a different import. Reload the screen and submit again.')
    return batch


def _assert_replay_is_in_scope(
    batch: JawabuFarmerUploadBatch,
    *,
    allowed_group_ids: set[str] | None,
) -> None:
    """Keep an idempotent replay inside the caller's original import scope.

    A retry key must replay exactly one source upload, not become a way to
    retrieve a staged file from a different configured Telegram group.
    """
    if allowed_group_ids is not None and str(batch.group_id) not in allowed_group_ids:
        raise PortalImportError('This staged import is unavailable in your scope.')


def _assert_farmup_batch(batch: JawabuFarmerUploadBatch) -> None:
    if batch.import_kind != 'farmers':
        raise PortalImportError('SysUp batches are available under Imports and cannot be changed through FarmUp.')


def farmup_revision_token(batch: JawabuFarmerUploadBatch) -> str:
    """Return an opaque, batch-bound token for optimistic concurrency."""
    return signing.dumps(
        {'batch': str(batch.pk), 'revision': int(batch.portal_revision or 1)},
        salt=_FARMUP_REVISION_SALT,
        compress=True,
    )


def _revision_from_token(batch: JawabuFarmerUploadBatch, token: str) -> int:
    try:
        payload = signing.loads(str(token or ''), salt=_FARMUP_REVISION_SALT)
        if str(payload.get('batch') or '') != str(batch.pk):
            raise signing.BadSignature
        return int(payload.get('revision'))
    except (signing.BadSignature, TypeError, ValueError, AttributeError):
        raise PortalImportConflict('This FarmUp preview is stale. Reload the batch before committing.')


def _farmup_commit_rows(batch: JawabuFarmerUploadBatch, submitted_rows: Any) -> list[dict]:
    """Merge the editable surface onto server rows without trusting metadata."""
    if not isinstance(submitted_rows, list):
        raise PortalImportError('FarmUp rows must be submitted as a list.')
    current_rows = list(batch.parsed_rows or [])
    by_id = {str(row.get('row_id')): dict(row) for row in current_rows}
    submitted_ids: set[str] = set()
    merged_rows: list[dict] = []
    for submitted in submitted_rows:
        if not isinstance(submitted, dict):
            raise PortalImportError('Each FarmUp row must be an object.')
        row_id = str(submitted.get('row_id') or '')
        if not row_id or row_id not in by_id or row_id in submitted_ids:
            raise PortalImportConflict('The FarmUp row selection changed. Reload the batch before committing.')
        submitted_ids.add(row_id)
        merged = by_id[row_id]
        for field in FARMUP_EDITABLE_FIELDS:
            if field in submitted:
                merged[field] = str(submitted.get(field) or '')
        merged['approved'] = bool(submitted.get('approved'))
        merged['warning_acknowledged'] = bool(submitted.get('warning_acknowledged'))
        disposition = str(submitted.get('disposition') or (
            FARMUP_DISPOSITION_COMMIT if merged['approved'] else FARMUP_DISPOSITION_HOLD
        ))
        if not merged['approved'] and disposition == FARMUP_DISPOSITION_COMMIT:
            disposition = FARMUP_DISPOSITION_HOLD
        elif merged['approved'] and disposition == FARMUP_DISPOSITION_HOLD:
            disposition = FARMUP_DISPOSITION_COMMIT
        if disposition not in {
            FARMUP_DISPOSITION_COMMIT, FARMUP_DISPOSITION_HOLD,
            FARMUP_DISPOSITION_EXCLUDE, *FARMUP_TERMINAL_DISPOSITIONS,
        }:
            raise PortalImportError('Choose Commit now, Hold for later, or Exclude for every FarmUp row.')
        merged['disposition'] = disposition
        merged['approved'] = disposition == FARMUP_DISPOSITION_COMMIT
        merged['update_acknowledged'] = bool(submitted.get('update_acknowledged'))
        merged_rows.append(merged)
    if submitted_ids != set(by_id):
        raise PortalImportConflict('The FarmUp row selection changed. Reload the batch before committing.')
    return merged_rows


def _farmup_payload_digest(rows: list[dict]) -> str:
    editable = [
        {
            'row_id': str(row.get('row_id') or ''),
            'approved': bool(row.get('approved')),
            'warning_acknowledged': bool(row.get('warning_acknowledged')),
            'update_acknowledged': bool(row.get('update_acknowledged')),
            'disposition': str(row.get('disposition') or ''),
            **{field: str(row.get(field) or '') for field in FARMUP_EDITABLE_FIELDS},
        }
        for row in rows
    ]
    encoded = json.dumps(editable, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


_FARMUP_COMPARE_FIELDS = {
    'customer_name': 'Customer Name', 'national_id': 'National ID',
    'primary_phone': 'Primary Phone', 'secondary_phone': 'Secondary Phone',
    'county': 'County', 'sub_county': 'Constituency', 'village': 'Village',
    'lead_source': 'Lead Source', 'sign_date': 'HBG Visit Date',
    'actual_receipts': 'Deposit Paid to HB', 'hb_sales_person': 'HB Sales Person',
    'comments': 'HBG Visit Comment',
}


def _comparable_farmup_value(value: Any) -> str:
    if value is None:
        return ''
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    return str(value).strip().casefold()


def _farmup_database_match(batch: JawabuFarmerUploadBatch, row: dict, index: int, *, lock: bool = False) -> dict:
    """Classify create/update/no-op using the same canonical identity sources as commit."""
    from django.db.models import Exists, OuterRef, Q
    from core.models import JawabuCustomer, JawabuCustomerPhoneHistory, JawabuFarmerMaster
    from core.services.identifiers import normalize_kenyan_phone, normalize_national_id
    from core.services.jawabu_master import cleaned_master_row_from_review

    cleaned = cleaned_master_row_from_review(row, batch, index, timezone.now())
    national_id = normalize_national_id(cleaned.get('national_id'))
    primary_phone = normalize_kenyan_phone(cleaned.get('primary_phone'))
    query = Q()
    if national_id:
        query |= Q(national_id=national_id)
    if primary_phone:
        query |= Q(primary_phone=primary_phone)
    customers = JawabuCustomer.objects.all()
    if lock:
        customers = customers.select_for_update()
    if primary_phone:
        history = JawabuCustomerPhoneHistory.objects.filter(customer_id=OuterRef('pk'), phone=primary_phone)
        customers = customers.annotate(_farmup_phone_history_match=Exists(history))
        query |= Q(_farmup_phone_history_match=True)
    matches = list(customers.filter(query).order_by('pk')) if query.children else []
    if len(matches) > 1:
        return {'kind': 'identity_conflict', 'farmer_id': '', 'changed_fields': []}
    if str(cleaned.get('application_action') or 'update_existing') == 'create_additional_unit':
        return {'kind': 'additional_unit', 'farmer_id': '', 'changed_fields': []}
    if not matches:
        return {'kind': 'new', 'farmer_id': '', 'changed_fields': []}
    applications = JawabuFarmerMaster.objects.filter(customer=matches[0]).order_by('-updated_at', 'pk')
    if lock:
        applications = applications.select_for_update()
    existing = applications.first()
    if existing is None:
        return {'kind': 'new', 'farmer_id': '', 'changed_fields': []}
    changed = []
    for field, label in _FARMUP_COMPARE_FIELDS.items():
        incoming = cleaned.get(field)
        # A blank monthly export must never erase an established value.
        if incoming in (None, ''):
            continue
        if _comparable_farmup_value(getattr(existing, field, '')) != _comparable_farmup_value(incoming):
            changed.append(label)
    return {
        'kind': 'update' if changed else 'unchanged',
        'farmer_id': str(existing.pk), 'changed_fields': changed,
    }


def _farmup_row_issues(batch: JawabuFarmerUploadBatch, row: dict, index: int) -> list[dict[str, str]]:
    from core.services.jawabu import is_valid_phone
    from core.services.jawabu_master import (
        clean_national_id, cleaned_master_row_from_review,
        farmup_review_validation_notes, is_valid_national_id,
    )

    cleaned = cleaned_master_row_from_review(row, batch, index, timezone.now())
    blockers = []
    if not cleaned.get('customer_name'):
        blockers.append('Customer Name is required')
    blockers.extend(farmup_review_validation_notes(row, cleaned))
    if cleaned.get('primary_phone') and not is_valid_phone(cleaned['primary_phone']):
        blockers.append('Primary Phone must be in 254 format')
    if cleaned.get('secondary_phone') and not is_valid_phone(cleaned['secondary_phone']):
        blockers.append('Secondary Phone must be in 254 format')
    issues = [{'severity': 'blocker', 'message': message} for message in dict.fromkeys(blockers)]
    if row.get('_duplicate_in_upload'):
        issues.append({'severity': 'blocker', 'message': 'This upload contains another row with the same customer identity'})
    if row.get('_source_state') == 'changed':
        issues.append({'severity': 'warning', 'message': 'This row changed in the latest monthly upload; review it before selecting'})
    if row.get('_source_state') == 'removed':
        issues.append({'severity': 'warning', 'message': 'This held row is absent from the latest monthly upload'})
    raw_id = str(row.get('National ID') or '').strip()
    numeric_id = clean_national_id(raw_id)
    if numeric_id and not is_valid_national_id(numeric_id):
        issues.append({
            'severity': 'warning',
            'message': 'National ID is outside the usual 7-9 digit range',
        })
    notes = str(row.get('Cleaning Notes') or '').strip()
    if row.get('Import Status') == 'review_needed' and not issues and notes.startswith('Master Data conflict before commit:'):
        issues.append({'severity': 'warning', 'message': notes})
    return issues


def validate_portal_farmup(
    *,
    batch_id: str,
    rows: list[dict],
    revision_token: str,
    allowed_group_ids: set[str] | None = None,
) -> tuple[JawabuFarmerUploadBatch, list[dict], dict[str, int]]:
    """Validate an exact client review without changing workflow state."""
    batch = JawabuFarmerUploadBatch.objects.filter(pk=batch_id).first()
    if batch is None:
        raise PortalImportError('This FarmUp batch is unavailable.')
    _assert_replay_is_in_scope(batch, allowed_group_ids=allowed_group_ids)
    _assert_farmup_batch(batch)
    if _revision_from_token(batch, revision_token) != int(batch.portal_revision or 1):
        raise PortalImportConflict('Another reviewer changed this FarmUp batch. Reload it before continuing.')
    merged = _farmup_commit_rows(batch, rows)
    results = []
    counts = {
        'total': len(merged), 'selected': 0, 'warning_overrides': 0,
        'new': 0, 'updates': 0, 'unchanged': 0, 'held': 0,
        'excluded': 0, 'removed': 0, 'unresolved': 0,
    }
    for index, row in enumerate(merged, start=1):
        issues = _farmup_row_issues(batch, row, index)
        match = _farmup_database_match(batch, row, index)
        if match['kind'] == 'identity_conflict':
            issues.append({'severity': 'blocker', 'message': 'These identifiers match multiple historical customers'})
        blockers = [item for item in issues if item['severity'] == 'blocker']
        warnings = [item for item in issues if item['severity'] == 'warning']
        disposition = str(row.get('disposition') or (
            FARMUP_DISPOSITION_COMMIT if row.get('approved') else FARMUP_DISPOSITION_HOLD
        ))
        selected = disposition == FARMUP_DISPOSITION_COMMIT
        if match['kind'] == 'unchanged':
            selected = False
            disposition = 'already_committed'
            counts['unchanged'] += 1
        acknowledged = bool(row.get('warning_acknowledged'))
        update_acknowledged = bool(row.get('update_acknowledged'))
        if disposition == FARMUP_DISPOSITION_EXCLUDE:
            counts['excluded'] += 1
        elif disposition == FARMUP_DISPOSITION_HOLD:
            counts['held'] += 1
        if row.get('_source_state') == 'removed':
            counts['removed'] += 1
        if selected and match['kind'] == 'update' and not update_acknowledged:
            issues.append({'severity': 'warning', 'message': 'Acknowledge the existing-record update before commit'})
            warnings = [item for item in issues if item['severity'] == 'warning']
        if selected and blockers:
            state = 'needs_correction'
            counts['unresolved'] += 1
        elif selected and warnings and (
            not acknowledged or (match['kind'] == 'update' and not update_acknowledged)
        ):
            state = 'warning'
            counts['unresolved'] += 1
        elif selected:
            state = 'warning' if warnings else 'ready'
            counts['selected'] += 1
            if match['kind'] in ('new', 'additional_unit'):
                counts['new'] += 1
            elif match['kind'] == 'update':
                counts['updates'] += 1
            if warnings:
                counts['warning_overrides'] += 1
        elif blockers or warnings:
            state = 'needs_correction' if blockers else 'warning'
            counts['unresolved'] += 1
        else:
            state = 'ready'
        results.append({
            'row_id': str(row.get('row_id') or ''),
            'state': state,
            'selected': selected,
            'warning_acknowledged': acknowledged,
            'update_acknowledged': update_acknowledged,
            'disposition': disposition,
            'match': match,
            'issues': issues,
        })
    return batch, results, counts


def _farmup_repair_operation_ids(batch: JawabuFarmerUploadBatch) -> set[str]:
    ledgers = JawabuFarmerUploadBatch.objects.filter(
        worklist_id=batch.worklist_id, import_kind='farmers',
    ).values_list('portal_commit_replays', flat=True)
    operation_ids = {
        str(operation.get('id'))
        for ledger in ledgers
        for replay in list(ledger or [])
        if replay.get('operation') in (None, 'commit', 'repair')
        for publication in list((replay.get('result') or {}).get('publications') or [])
        for operation in list(publication.get('operations') or [])
        if operation.get('id')
    }
    operation_ids.update(str(value) for value in IntegrationOperation.objects.filter(
        source_model='JawabuFarmerMaster',
        metadata__farmup_worklist_id=str(batch.worklist_id),
    ).values_list('pk', flat=True))
    return operation_ids


def _farmup_repair_farmer_ids(batch: JawabuFarmerUploadBatch) -> set[str]:
    """Collect opaque canonical farmer IDs associated with this worklist."""
    farmer_ids = set(IntegrationOperation.objects.filter(
        pk__in=_farmup_repair_operation_ids(batch), source_model='JawabuFarmerMaster',
    ).values_list('source_id', flat=True))

    current = JawabuFarmerUploadBatch.objects.filter(
        worklist_id=batch.worklist_id, import_kind='farmers', is_current_version=True,
    ).first() or batch
    for index, row in enumerate(list(current.parsed_rows or []), start=1):
        if str(row.get('disposition') or '') in {'exclude', 'excluded'}:
            continue
        match = _farmup_database_match(current, row, index)
        if match.get('kind') == 'unchanged' and match.get('farmer_id'):
            farmer_ids.add(str(match['farmer_id']))
    return farmer_ids


def _farmup_invalid_deposit(farmer) -> bool:
    from core.services.jawabu_validation import parse_money

    if farmer.deposit_paid_hbg is not None or farmer.actual_receipts in (None, ''):
        return False
    return parse_money(farmer.actual_receipts) is None


def farmup_repair_preview(
    *, batch_id: str, revision_token: str,
    allowed_group_ids: set[str] | None = None,
) -> tuple[JawabuFarmerUploadBatch, dict[str, Any], list]:
    """Build a customer-safe monthly Sheet projection repair preview."""
    from core.models import JawabuFarmerMaster

    batch = JawabuFarmerUploadBatch.objects.filter(pk=batch_id).first()
    if batch is None:
        raise PortalImportError('This FarmUp batch is unavailable.')
    _assert_replay_is_in_scope(batch, allowed_group_ids=allowed_group_ids)
    _assert_farmup_batch(batch)
    if _revision_from_token(batch, revision_token) != int(batch.portal_revision or 1):
        raise PortalImportConflict('Another reviewer changed this FarmUp batch. Reload it before repairing Sheets.')
    group_configuration = resolve_import_group(allowed_group_ids=allowed_group_ids)
    if str(group_configuration.group_id) != str(batch.group_id):
        raise PortalImportError('This FarmUp batch no longer matches the configured Jawabu workflow.')

    sheet_enabled = bool((group_configuration.workflow or {}).get('master_sync_enabled'))
    farmer_ids = _farmup_repair_farmer_ids(batch)
    farmers = list(JawabuFarmerMaster.objects.filter(pk__in=farmer_ids).order_by('pk'))
    invalid_ids = {str(farmer.pk) for farmer in farmers if _farmup_invalid_deposit(farmer)}
    eligible = [farmer for farmer in farmers if str(farmer.pk) not in invalid_ids] if sheet_enabled else []
    operation_ids = _farmup_repair_operation_ids(batch)
    operations = list(IntegrationOperation.objects.filter(
        pk__in=operation_ids, source_model='JawabuFarmerMaster', source_id__in=farmer_ids,
        operation_type__in=['jawabu_master_publish', 'jawabu_internal_order_publish'],
    ).order_by('created_at'))
    failures: dict[str, int] = {}
    last_failure_at = None
    failure_categories: dict[str, int] = {}
    farmer_statuses: dict[str, set[str]] = {}
    for operation in operations:
        farmer_statuses.setdefault(operation.source_id, set()).add(operation.status)
        if operation.status == IntegrationOperation.STATUS_DEAD_LETTER:
            failures[operation.source_id] = failures.get(operation.source_id, 0) + 1
            category = str(operation.last_error_code or 'external_error')
            failure_categories[category] = failure_categories.get(category, 0) + 1
            if operation.last_attempt_at and (last_failure_at is None or operation.last_attempt_at > last_failure_at):
                last_failure_at = operation.last_attempt_at
    pending_statuses = {
        IntegrationOperation.STATUS_PENDING, IntegrationOperation.STATUS_RUNNING,
        IntegrationOperation.STATUS_RETRYABLE,
    }
    current = JawabuFarmerUploadBatch.objects.filter(
        worklist_id=batch.worklist_id, import_kind='farmers', is_current_version=True,
    ).first() or batch
    current_rows = list(current.parsed_rows or [])
    unchanged_count = 0
    for index, row in enumerate(current_rows, start=1):
        if str(row.get('disposition') or '') not in {'exclude', 'excluded'} and _farmup_database_match(current, row, index).get('kind') == 'unchanged':
            unchanged_count += 1
    counts = {
        'repairable': len(eligible),
        'committed': int(current.committed_count or 0),
        'unchanged': unchanged_count,
        'held': sum(1 for row in current_rows if str(row.get('disposition') or '') == 'hold'),
        'excluded': int(current.skipped_count or 0),
        'unresolved': int(current.review_needed or 0),
        'pending': sum(1 for farmer_id in farmer_ids if farmer_statuses.get(farmer_id, set()) & pending_statuses),
        'failed_once': sum(1 for count in failures.values() if count == 1),
        'repeatedly_failing': sum(1 for count in failures.values() if count >= 2),
        'invalid_deposits': len(invalid_ids),
    }
    preview = {
        'worklist_id': str(batch.worklist_id),
        'period': batch.period_month.strftime('%Y-%m') if batch.period_month else '',
        'period_label': batch.period_month.strftime('%B %Y') if batch.period_month else 'Legacy import',
        'counts': counts,
        'failure_categories': failure_categories,
        'last_failure_at': last_failure_at.isoformat() if last_failure_at else None,
        'sheet_enabled': sheet_enabled,
    }
    return batch, preview, eligible


@transaction.atomic
def repair_portal_farmup(
    *, batch_id: str, revision_token: str, request_id: str, actor,
    allowed_group_ids: set[str] | None = None,
) -> tuple[JawabuFarmerUploadBatch, dict[str, Any], bool]:
    """Reserve an idempotent, resumable Sheet-only repair for one worklist."""
    request_id = str(request_id or '').strip()
    if not request_id:
        raise PortalImportError('This Sheet repair needs a retry key.')
    batch = JawabuFarmerUploadBatch.objects.select_for_update().filter(pk=batch_id).first()
    if batch is None:
        raise PortalImportError('This FarmUp batch is unavailable.')
    _assert_replay_is_in_scope(batch, allowed_group_ids=allowed_group_ids)
    _assert_farmup_batch(batch)
    payload_hash = hashlib.sha256(
        f'{batch.worklist_id}:{revision_token}'.encode('utf-8')
    ).hexdigest()
    for replay in list(batch.portal_commit_replays or []):
        if replay.get('operation') != 'repair' or replay.get('request_id') != request_id:
            continue
        if replay.get('payload_hash') != payload_hash:
            raise PortalImportConflict('This retry key was already used for a different FarmUp repair.')
        return batch, dict(replay.get('result') or {}), True

    _preview_batch, preview, farmers = farmup_repair_preview(
        batch_id=str(batch.pk), revision_token=revision_token,
        allowed_group_ids=allowed_group_ids,
    )
    from core.services.portal_publication import MASTER_OPERATION, publication_payload, reserve_farmer_publication

    publications = []
    namespace = f'farmup-repair:{batch.worklist_id}:{request_id}'
    for farmer in farmers:
        reserve_farmer_publication(
            farmer, request_id=request_id, requested_by=actor,
            requested_by_label=batch.sender,
            required_capability='portal.publication.retry',
            deduplication_namespace=namespace,
            extra_metadata={
                'farmup_worklist_id': str(batch.worklist_id),
                'farmup_period': preview['period'], 'farmup_repair': True,
            },
            operation_types=[MASTER_OPERATION],
        )
        publications.append(publication_payload(farmer))
    result = {
        'success': True, 'repairable': len(farmers),
        'skipped_invalid_deposits': int(preview['counts']['invalid_deposits']),
        'publications': publications,
        'pending_operation_ids': [
            operation_id for publication in publications
            for operation_id in list(publication.get('pending_operation_ids') or [])
        ],
    }
    replays = list(batch.portal_commit_replays or [])
    replays.append({
        'operation': 'repair', 'request_id': request_id[:128],
        'payload_hash': payload_hash, 'result': result,
    })
    commit_replays = [item for item in replays if item.get('operation') in (None, 'commit')]
    other_replays = [item for item in replays if item.get('operation') not in (None, 'commit')][-50:]
    batch.portal_commit_replays = commit_replays + other_replays
    batch.save(update_fields=['portal_commit_replays', 'updated_at'])
    record_event(
        workflow='portal', action='portal.farmup.sheet_repair_reserved', category='integration',
        subject_type='JawabuFarmerUploadBatch', subject_id=str(batch.pk),
        deduplication_key=f'portal-farmup-repair:{batch.pk}:{request_id}', actor=actor,
        request_id=request_id, source_model='JawabuFarmerUploadBatch',
        source_event_id=f'{batch.pk}:repair:{request_id}', before_values={},
        after_values={'repairable': len(farmers), 'invalid_deposits': result['skipped_invalid_deposits']},
        metadata={'group_id': batch.group_id, 'worklist_id': str(batch.worklist_id), 'period': preview['period']},
        sensitive=False,
    )
    return batch, result, False


@transaction.atomic
def apply_portal_farmup_mapping(
    *, batch_id: str, decisions: list[dict], revision_token: str,
    request_id: str, actor, allowed_group_ids: set[str] | None = None,
) -> tuple[JawabuFarmerUploadBatch, bool]:
    """Apply one explicit, idempotent mapping and reparse retained source."""
    request_id = str(request_id or '').strip()
    if not request_id:
        raise PortalImportError('This mapping change needs a retry key.')
    if not isinstance(decisions, list) or any(not isinstance(item, dict) for item in decisions):
        raise PortalImportError('FarmUp column mappings must be submitted as a list.')
    batch = JawabuFarmerUploadBatch.objects.select_for_update().filter(pk=batch_id).first()
    if batch is None:
        raise PortalImportError('This FarmUp batch is unavailable.')
    _assert_replay_is_in_scope(batch, allowed_group_ids=allowed_group_ids)
    _assert_farmup_batch(batch)
    payload_hash = _farmup_mapping_digest(decisions)
    for replay in list(batch.portal_commit_replays or []):
        if replay.get('operation') != 'mapping' or replay.get('request_id') != request_id:
            continue
        if replay.get('payload_hash') != payload_hash:
            raise PortalImportConflict('This retry key was already used with a different column mapping.')
        return batch, True
    if _revision_from_token(batch, revision_token) != int(batch.portal_revision or 1):
        raise PortalImportConflict('Another reviewer changed this FarmUp batch. Reload it before changing the mapping.')
    version_has_commit = any(
        replay.get('operation') in (None, 'commit')
        for replay in list(batch.portal_commit_replays or [])
    )
    if batch.committed_count and (int(batch.version_number or 1) == 1 or version_has_commit):
        raise PortalImportConflict('Column mapping is locked after the first FarmUp commit.')
    if not batch.source_content:
        raise PortalImportError('The original FarmUp CSV is unavailable for remapping.')
    csv_text = _decode_farmup_csv(bytes(batch.source_content))
    analysis = farmup_mapping_analysis(csv_text, decisions)
    from core.services.jawabu_master import build_cleaned_master_preview

    canonical_map = {
        item['target_field']: item['source_id']
        for item in analysis['columns'] if item.get('target_field')
    }
    rows, stats = build_cleaned_master_preview(
        io.StringIO(csv_text), source_name=batch.source_filename,
        header_mapping=canonical_map,
    )
    parsed = _initialize_review_rows([
        {**row, 'row_id': index, 'approved': row.get('Import Status') != 'review_needed'}
        for index, row in enumerate(rows, start=1)
    ])
    if int(batch.version_number or 1) > 1:
        previous = JawabuFarmerUploadBatch.objects.filter(
            worklist_id=batch.worklist_id,
            version_number=int(batch.version_number or 1) - 1,
        ).first()
        if previous is not None:
            parsed, batch.reconciliation = _reconcile_farmup_version(previous, parsed)
    batch.parsed_rows = parsed
    batch.total_rows = len(parsed)
    batch.review_needed = sum(1 for row in parsed if row.get('Import Status') == 'review_needed')
    batch.mapping = _mapping_without_samples(analysis)
    previous_revision = int(batch.portal_revision or 1)
    batch.portal_revision = previous_revision + 1
    replays = list(batch.portal_commit_replays or [])
    replays.append({'operation': 'mapping', 'request_id': request_id[:128], 'payload_hash': payload_hash})
    batch.portal_commit_replays = replays[-100:]
    batch.save(update_fields=[
        'parsed_rows', 'total_rows', 'review_needed', 'mapping', 'reconciliation',
        'portal_revision', 'portal_commit_replays', 'updated_at',
    ])
    record_event(
        workflow='portal', action='portal.farmup.mapping_changed', category='workflow',
        subject_type='JawabuFarmerUploadBatch', subject_id=str(batch.pk),
        deduplication_key=f'portal-farmup-mapping:{batch.pk}:{request_id}',
        actor=actor, request_id=request_id, source_model='JawabuFarmerUploadBatch',
        source_event_id=f'{batch.pk}:mapping:{request_id}',
        before_values={'revision': previous_revision},
        after_values={'revision': batch.portal_revision, 'mapping_digest': analysis['digest']},
        metadata={
            'group_id': batch.group_id,
            'mapped_columns': sum(1 for item in analysis['columns'] if item.get('target_field')),
            'ignored_columns': sum(1 for item in analysis['columns'] if not item.get('target_field')),
            'missing_required_count': len(analysis['missing_required_fields']),
        }, sensitive=False,
    )
    return batch, False


@transaction.atomic
def commit_portal_farmup(
    *,
    batch_id: str,
    rows: list[dict],
    revision_token: str,
    request_id: str,
    actor,
    allowed_group_ids: set[str] | None = None,
) -> tuple[JawabuFarmerUploadBatch, dict, bool]:
    """Commit a revision-bound FarmUp review with customer-free replay state."""
    request_id = str(request_id or '').strip()
    if not request_id:
        raise PortalImportError('This commit needs a retry key. Reload FarmUp and try again.')
    batch = JawabuFarmerUploadBatch.objects.select_for_update().filter(pk=batch_id).first()
    if batch is None:
        raise PortalImportError('This FarmUp batch is unavailable.')
    _assert_replay_is_in_scope(batch, allowed_group_ids=allowed_group_ids)
    _assert_farmup_batch(batch)
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise PortalImportError('FarmUp rows must be submitted as a list.')
    # Check the retry ledger before comparing against the now-mutated working
    # rows. A successful full/partial commit removes processed rows, but an
    # exact network retry must still replay its original aggregate result.
    payload_hash = _farmup_payload_digest(rows)

    for replay in list(batch.portal_commit_replays or []):
        if replay.get('operation') not in (None, 'commit'):
            continue
        if str(replay.get('request_id') or '') != request_id:
            continue
        if replay.get('payload_hash') != payload_hash:
            raise PortalImportConflict('This retry key was already used with different FarmUp rows.')
        return batch, dict(replay.get('result') or {}), True

    merged_rows = _farmup_commit_rows(batch, rows)
    expected_revision = _revision_from_token(batch, revision_token)
    if expected_revision != int(batch.portal_revision or 1):
        raise PortalImportConflict('Another reviewer changed this FarmUp batch. Reload it before committing.')
    warning_overrides = 0
    for index, row in enumerate(merged_rows, start=1):
        if not row.get('approved'):
            continue
        match = _farmup_database_match(batch, row, index, lock=True)
        row['_match_kind'] = match['kind']
        row['_changed_fields'] = match.get('changed_fields') or []
        if match['kind'] == 'identity_conflict':
            raise PortalImportError(
                f'Row {row.get("row_id") or index} matches multiple historical customers and cannot be committed.'
            )
        if match['kind'] == 'update' and not row.get('update_acknowledged'):
            raise PortalImportError(
                f'Row {row.get("row_id") or index} will update an existing unit. Review and acknowledge its changes first.'
            )
        if match['kind'] == 'unchanged':
            row['approved'] = False
            row['disposition'] = 'already_committed'
            continue
        issues = _farmup_row_issues(batch, row, index)
        if any(item['severity'] == 'blocker' for item in issues):
            raise PortalImportError(f'Row {row.get("row_id") or index} still needs correction before it can be selected.')
        if any(item['severity'] == 'warning' for item in issues):
            if not row.get('warning_acknowledged'):
                raise PortalImportError(f'Row {row.get("row_id") or index} has a warning that must be acknowledged before commit.')
            warning_overrides += 1

    from core.services.jawabu_master import commit_farmup_review_batch

    group_configuration = resolve_import_group(allowed_group_ids=allowed_group_ids)
    if str(group_configuration.group_id) != str(batch.group_id):
        raise PortalImportError('This FarmUp batch no longer matches the configured Jawabu workflow.')
    result = commit_farmup_review_batch(
        batch, merged_rows, group_config=group_configuration,
        defer_sheet_sync=True, request_id=request_id, actor=actor,
    )
    safe_result = {
        'success': bool(result.get('success')),
        'message': str(result.get('message') or ''),
        'committed': int(result.get('committed') or 0),
        'skipped': int(result.get('skipped') or 0),
        'review_needed': int(result.get('review_needed') or 0),
        'held': int(result.get('held') or 0),
        'excluded': int(result.get('excluded') or 0),
        'created': int(result.get('created') or 0),
        'updated': int(result.get('updated') or 0),
        'unchanged': int(result.get('unchanged') or 0),
        'publications': list(result.get('publications') or []),
        'errors': [str(value) for value in list(result.get('errors') or [])[:20]],
        'sheet_sync': {
            key: result.get('sheet_sync', {}).get(key)
            for key in ('success', 'enabled', 'status', 'created', 'updated', 'conflicts')
        },
    }
    batch.portal_revision = int(batch.portal_revision or 1) + 1
    replays = list(batch.portal_commit_replays or [])
    replays.append({
        'operation': 'commit',
        'request_id': request_id[:128],
        'payload_hash': payload_hash,
        'result': safe_result,
    })
    batch.portal_commit_replays = replays[-100:]
    batch.save(update_fields=['portal_revision', 'portal_commit_replays', 'updated_at'])
    record_event(
        workflow='portal',
        action='portal.farmup.committed',
        category='workflow',
        subject_type='JawabuFarmerUploadBatch',
        subject_id=str(batch.pk),
        deduplication_key=f'portal-farmup-commit:{batch.pk}:{request_id}',
        actor=actor,
        request_id=request_id,
        source_model='JawabuFarmerUploadBatch',
        source_event_id=f'{batch.pk}:portal-commit:{request_id}',
        before_values={'revision': expected_revision},
        after_values={
            'revision': batch.portal_revision,
            'status': batch.status,
            'committed_count': batch.committed_count,
            'skipped_count': batch.skipped_count,
            'review_needed': batch.review_needed,
        },
        metadata={
            'group_id': batch.group_id,
            'approved_rows': sum(1 for row in merged_rows if row.get('approved')),
            'skipped_rows': sum(1 for row in merged_rows if not row.get('approved')),
            'unresolved_rows': safe_result['review_needed'],
            'warning_overrides': warning_overrides,
        },
        sensitive=False,
    )
    return batch, safe_result, False


def archive_portal_import_working_list(
    *,
    batch_id: str,
    actor,
    request_id: str,
    allowed_group_ids: set[str] | None = None,
) -> tuple[JawabuFarmerUploadBatch, bool]:
    """Hide one retained staged import from the active Portal working list.

    This deliberately does not call Google Drive or alter the underlying
    FarmUp/SysUp workflow status.  It is safe for Mini App retries: once a
    batch is archived, all later retries return the retained batch without
    producing a second audit event.
    """
    request_id = str(request_id or '').strip()
    if not request_id:
        raise PortalImportError('This archive action needs a retry key. Reload Imports and try again.')
    with transaction.atomic():
        batch = JawabuFarmerUploadBatch.objects.select_for_update().filter(pk=batch_id).first()
        if batch is None:
            raise PortalImportError('This staged import is unavailable.')
        _assert_replay_is_in_scope(batch, allowed_group_ids=allowed_group_ids)
        if batch.is_portal_archived:
            return batch, True

        before = {
            'working_list_active': True,
            'status': batch.status,
            'drive_archive_state': import_archive_state(batch),
        }
        archived_at = timezone.now()
        JawabuFarmerUploadBatch.objects.filter(worklist_id=batch.worklist_id).update(
            is_portal_archived=True, portal_archived_at=archived_at,
            portal_archived_by=actor, updated_at=archived_at,
        )
        batch.is_portal_archived = True
        batch.portal_archived_at = archived_at
        batch.portal_archived_by = actor
        record_event(
            workflow='portal',
            action='portal.import.working_list_archived',
            category='workflow',
            subject_type='JawabuFarmerUploadBatch',
            subject_id=str(batch.pk),
            deduplication_key=f'portal-import-working-list-archive:{batch.pk}',
            actor=actor,
            request_id=request_id,
            source_model='JawabuFarmerUploadBatch',
            source_event_id=f'{batch.pk}:working-list-archive',
            before_values=before,
            after_values={
                'working_list_active': False,
                'status': batch.status,
                'drive_archive_state': import_archive_state(batch),
                'archived_at': archived_at,
            },
            metadata={'import_kind': batch.import_kind, 'group_id': batch.group_id},
            sensitive=True,
        )
    return batch, False


def reserve_import_archive(batch: JawabuFarmerUploadBatch, *, request_id: str, user=None) -> IntegrationOperation:
    """Reserve an idempotent Drive archive attempt without performing I/O."""
    operation, _ = reserve_operation(
        integration=IntegrationOperation.INTEGRATION_GOOGLE_DRIVE,
        operation_type=ARCHIVE_OPERATION,
        deduplication_key=f'portal-import-archive:{batch.pk}:{batch.source_content_hash}',
        source_model=SOURCE_MODEL,
        source_id=str(batch.pk),
        request_id=str(request_id or '')[:128],
        requested_by=user,
        requested_by_label=str(getattr(user, 'get_full_name', lambda: '')() or getattr(user, 'username', '') or '')[:255],
        operation_payload=(str(batch.pk), batch.source_content_hash),
        metadata={'import_kind': batch.import_kind, 'source_size': int(batch.source_size or 0)},
    )
    return operation


def stage_portal_import(
    *,
    kind: str,
    filename: str,
    content: bytes,
    request_id: str,
    actor,
    allowed_group_ids: set[str] | None = None,
    period: str | date | None = None,
) -> tuple[JawabuFarmerUploadBatch, IntegrationOperation, bool]:
    """Create one parsed review batch and reserve archival work.

    The request key is mandatory because an Android WebView retry must return
    the original parsed batch rather than create a second import to review.
    """
    request_id = str(request_id or '').strip()
    if not request_id:
        raise PortalImportError('This upload needs a retry key. Reload the Imports screen and try again.')
    normalized_kind, safe_name, payload = _validated_source(kind, filename=filename, content=content)
    source_hash = hashlib.sha256(payload).hexdigest()
    period_month = (
        period if isinstance(period, date)
        else parse_farmup_period(period, required=False)
    ) if normalized_kind == IMPORT_KIND_FARMUP else None
    existing = _existing_replay(request_id, kind=normalized_kind, source_hash=source_hash)
    if existing is not None:
        _assert_replay_is_in_scope(
            existing,
            allowed_group_ids=allowed_group_ids,
        )
        return existing, reserve_import_archive(existing, request_id=request_id, user=actor), True
    group_configuration = resolve_import_group(allowed_group_ids=allowed_group_ids)
    if normalized_kind == IMPORT_KIND_FARMUP:
        duplicate = JawabuFarmerUploadBatch.objects.filter(
            import_kind='farmers', group_id=str(group_configuration.group_id),
            source_content_hash=source_hash,
        ).order_by('-created_at').first()
        if duplicate is not None:
            if period_month and duplicate.period_month and duplicate.period_month != period_month:
                raise PortalImportConflict(
                    f'This exact CSV is already retained in the {duplicate.period_month:%B %Y} FarmUp worklist.'
                )
            current = JawabuFarmerUploadBatch.objects.filter(
                worklist_id=duplicate.worklist_id, is_current_version=True,
            ).first() or duplicate
            _assert_replay_is_in_scope(current, allowed_group_ids=allowed_group_ids)
            return current, reserve_import_archive(duplicate, request_id=request_id, user=actor), True
        if period_month and JawabuFarmerUploadBatch.objects.filter(
            import_kind='farmers', group_id=str(group_configuration.group_id),
            period_month=period_month, is_current_version=True,
        ).exists():
            raise PortalImportConflict(
                f'A {period_month:%B %Y} FarmUp worklist already exists. Open it and use Upload updated version.'
            )
    try:
        with transaction.atomic():
            # Check again inside the transaction.  The unique request key is
            # the final concurrent-retry guard.
            existing = _existing_replay(request_id, kind=normalized_kind, source_hash=source_hash)
            if existing is not None:
                _assert_replay_is_in_scope(
                    existing,
                    allowed_group_ids=allowed_group_ids,
                )
                return existing, reserve_import_archive(existing, request_id=request_id, user=actor), True
            if normalized_kind == IMPORT_KIND_FARMUP:
                from core.services.jawabu_master import create_farmup_review_batch

                csv_text = _decode_farmup_csv(payload)
                mapping = farmup_mapping_analysis(csv_text)
                batch, _stats = create_farmup_review_batch(
                    group_id=group_configuration.group_id,
                    telegram_message_id='',
                    sender=str(getattr(actor, 'get_full_name', lambda: '')() or getattr(actor, 'username', '') or ''),
                    source_filename=safe_name,
                    csv_text=csv_text,
                    group_config=group_configuration,
                )
                batch.parsed_rows = _initialize_review_rows(list(batch.parsed_rows or []))
                batch.mapping = _mapping_without_samples(mapping)
                if mapping['state'] == 'needs_mapping':
                    batch.parsed_rows = []
                    batch.total_rows = mapping['source_row_count']
                    batch.review_needed = mapping['source_row_count']
            else:
                from core.services.system_export import create_system_export_review_batch

                batch, _stats = create_system_export_review_batch(
                    group_id=group_configuration.group_id,
                    telegram_message_id='',
                    sender=str(getattr(actor, 'get_full_name', lambda: '')() or getattr(actor, 'username', '') or ''),
                    source_filename=safe_name,
                    content=payload,
                )
            batch.created_by = actor
            batch.upload_request_id = request_id
            batch.source_mime_type = mimetypes.guess_type(safe_name)[0] or 'application/octet-stream'
            batch.source_size = len(payload)
            batch.source_content_hash = source_hash
            batch.source_content = payload
            if normalized_kind == IMPORT_KIND_FARMUP:
                batch.period_month = period_month
            batch.save(update_fields=[
                'created_by', 'upload_request_id', 'source_mime_type', 'source_size',
                'source_content_hash', 'source_content', 'mapping', 'parsed_rows',
                'total_rows', 'review_needed', 'period_month', 'updated_at',
            ])
            operation = reserve_import_archive(batch, request_id=request_id, user=actor)
            return batch, operation, False
    except IntegrityError:
        # A concurrent retry may have won after parser work completed.  Do not
        # surface a duplicate-batch error or leave callers guessing its state.
        existing = _existing_replay(request_id, kind=normalized_kind, source_hash=source_hash)
        if existing is not None:
            _assert_replay_is_in_scope(
                existing,
                allowed_group_ids=allowed_group_ids,
            )
            return existing, reserve_import_archive(existing, request_id=request_id, user=actor), True
        raise


def _reconcile_farmup_version(previous: JawabuFarmerUploadBatch, incoming: list[dict]) -> tuple[list[dict], dict]:
    """Carry reviewer work forward without treating a cumulative CSV as new work."""
    previous_rows = {
        str(row.get('_identity_key') or _review_identity_key(row)): dict(row)
        for row in list(previous.parsed_rows or [])
    }
    rows = _initialize_review_rows(incoming)
    seen: set[str] = set()
    counts = {'added': 0, 'source_unchanged': 0, 'source_changed': 0, 'removed_from_latest': 0}
    next_row_id = 1
    for row in rows:
        key = str(row.get('_identity_key'))
        seen.add(key)
        prior = previous_rows.get(key)
        row['row_id'] = next_row_id
        next_row_id += 1
        if prior is None:
            counts['added'] += 1
            continue
        if str(prior.get('_source_fingerprint') or _review_source_fingerprint(prior)) == row['_source_fingerprint']:
            for field in FARMUP_EDITABLE_FIELDS:
                if field in prior:
                    row[field] = prior[field]
            prior_disposition = str(prior.get('disposition') or FARMUP_DISPOSITION_HOLD)
            row['disposition'] = (
                prior_disposition if prior_disposition not in FARMUP_TERMINAL_DISPOSITIONS
                else FARMUP_DISPOSITION_HOLD
            )
            row['approved'] = row['disposition'] == FARMUP_DISPOSITION_COMMIT
            row['warning_acknowledged'] = bool(prior.get('warning_acknowledged'))
            row['update_acknowledged'] = bool(prior.get('update_acknowledged'))
            counts['source_unchanged'] += 1
        else:
            row['_source_state'] = 'changed'
            row['disposition'] = FARMUP_DISPOSITION_HOLD
            row['approved'] = False
            counts['source_changed'] += 1
    for key, prior in previous_rows.items():
        if key in seen or str(prior.get('disposition') or '') in FARMUP_TERMINAL_DISPOSITIONS:
            continue
        retained = dict(prior)
        retained['row_id'] = next_row_id
        next_row_id += 1
        retained['_source_state'] = 'removed'
        retained['disposition'] = FARMUP_DISPOSITION_HOLD
        retained['approved'] = False
        rows.append(retained)
        counts['removed_from_latest'] += 1
    return rows, counts


@transaction.atomic
def stage_portal_farmup_version(
    *, batch_id: str, filename: str, content: bytes, request_id: str, actor,
    allowed_group_ids: set[str] | None = None,
) -> tuple[JawabuFarmerUploadBatch, IntegrationOperation, bool]:
    """Add one immutable source version to an existing monthly worklist."""
    request_id = str(request_id or '').strip()
    if not request_id:
        raise PortalImportError('This upload needs a retry key.')
    _kind, safe_name, payload = _validated_source(IMPORT_KIND_FARMUP, filename=filename, content=content)
    source_hash = hashlib.sha256(payload).hexdigest()
    requested = JawabuFarmerUploadBatch.objects.filter(pk=batch_id, import_kind='farmers').first()
    if requested is None:
        raise PortalImportError('This FarmUp worklist is unavailable.')
    _assert_replay_is_in_scope(requested, allowed_group_ids=allowed_group_ids)
    replay = _existing_replay(request_id, kind=IMPORT_KIND_FARMUP, source_hash=source_hash)
    if replay is not None:
        _assert_replay_is_in_scope(replay, allowed_group_ids=allowed_group_ids)
        if replay.worklist_id != requested.worklist_id:
            raise PortalImportConflict('This retry key belongs to a different FarmUp worklist.')
        current = JawabuFarmerUploadBatch.objects.filter(
            worklist_id=requested.worklist_id, is_current_version=True,
        ).first() or replay
        return current, reserve_import_archive(replay, request_id=request_id, user=actor), True
    previous = JawabuFarmerUploadBatch.objects.select_for_update().filter(
        worklist_id=requested.worklist_id, import_kind='farmers', is_current_version=True,
    ).first()
    if previous is None:
        raise PortalImportConflict('This FarmUp worklist changed. Reload it before uploading a new version.')
    _assert_replay_is_in_scope(previous, allowed_group_ids=allowed_group_ids)
    duplicate = JawabuFarmerUploadBatch.objects.filter(
        worklist_id=previous.worklist_id, source_content_hash=source_hash,
    ).first()
    if duplicate is not None:
        return previous, reserve_import_archive(duplicate, request_id=request_id, user=actor), True

    group_configuration = resolve_import_group(allowed_group_ids=allowed_group_ids)
    csv_text = _decode_farmup_csv(payload)
    mapping = farmup_mapping_analysis(csv_text)
    from core.services.jawabu_master import create_farmup_review_batch

    batch, stats = create_farmup_review_batch(
        group_id=group_configuration.group_id, telegram_message_id='',
        sender=str(getattr(actor, 'get_full_name', lambda: '')() or getattr(actor, 'username', '') or ''),
        source_filename=safe_name, csv_text=csv_text, group_config=group_configuration,
    )
    rows, reconciliation = _reconcile_farmup_version(previous, list(batch.parsed_rows or []))
    if mapping['state'] == 'needs_mapping':
        rows = []
        reconciliation = {'added': 0, 'source_unchanged': 0, 'source_changed': 0, 'removed_from_latest': 0}
    previous.is_current_version = False
    previous.save(update_fields=['is_current_version', 'updated_at'])
    batch.worklist_id = previous.worklist_id
    batch.period_month = previous.period_month
    batch.version_number = int(previous.version_number or 1) + 1
    batch.is_current_version = True
    batch.created_by = actor
    batch.upload_request_id = request_id
    batch.source_mime_type = mimetypes.guess_type(safe_name)[0] or 'text/csv'
    batch.source_size = len(payload)
    batch.source_content_hash = source_hash
    batch.source_content = payload
    batch.mapping = _mapping_without_samples(mapping)
    batch.parsed_rows = rows
    batch.total_rows = len(rows) if rows else int(stats.get('total_rows') or mapping['source_row_count'])
    batch.review_needed = sum(1 for row in rows if row.get('Import Status') == 'review_needed')
    batch.committed_count = int(previous.committed_count or 0)
    batch.skipped_count = int(previous.skipped_count or 0)
    batch.reconciliation = reconciliation
    batch.save()
    operation = reserve_import_archive(batch, request_id=request_id, user=actor)
    record_event(
        workflow='portal', action='portal.farmup.version_uploaded', category='workflow',
        subject_type='JawabuFarmerUploadBatch', subject_id=str(batch.pk), actor=actor,
        request_id=request_id, deduplication_key=f'portal-farmup-version:{request_id}',
        source_model='JawabuFarmerUploadBatch', source_event_id=f'{batch.pk}:version:{request_id}',
        after_values={'version': batch.version_number},
        metadata={'group_id': batch.group_id, **reconciliation}, sensitive=False,
    )
    return batch, operation, False


def _archive_filename(batch: JawabuFarmerUploadBatch) -> str:
    original = _SAFE_FILENAME.sub('_', PurePath(str(batch.source_filename or '')).name).strip(' ._')
    original = original[:160] or ('farmup.csv' if batch.import_kind == 'farmers' else 'system-export.csv')
    prefix = 'FarmUp' if batch.import_kind == 'farmers' else 'SysUp'
    return f'{prefix}_{str(batch.pk)[:8]}_{original}'


def attempt_import_archive(operation_id: str) -> dict[str, Any]:
    """Perform at most one bounded archive attempt for a previously staged file."""
    operation = IntegrationOperation.objects.filter(pk=operation_id).first()
    if operation is None or operation.source_model != SOURCE_MODEL or operation.operation_type != ARCHIVE_OPERATION:
        raise PortalImportError('This import archive operation is unavailable.')
    batch = JawabuFarmerUploadBatch.objects.filter(pk=operation.source_id).first()
    if batch is None:
        raise PortalImportError('The staged import is no longer available.')
    if batch.archive_file_id and batch.archive_url:
        return {'ok': True, 'batch': batch, 'operation': operation, 'replayed': True}
    folder_id = str(getattr(settings, 'GOOGLE_DRIVE_MEDIA_FOLDER_ID', '') or '').strip()
    if not folder_id:
        batch.archive_error = 'The shared Drive archive is not configured.'
        batch.save(update_fields=['archive_error', 'updated_at'])
        return {'ok': False, 'batch': batch, 'operation': operation, 'error': batch.archive_error}
    if not batch.source_content:
        batch.archive_error = 'The original source file is unavailable for Drive archival.'
        batch.save(update_fields=['archive_error', 'updated_at'])
        return {'ok': False, 'batch': batch, 'operation': operation, 'error': batch.archive_error}
    mark_drive_attempt(batch, prefix='archive')

    def archive_once() -> dict[str, str]:
        from core.services.order_approval import GoogleDriveMediaStorage

        # Imports share the approved media Drive root, but the storage gateway
        # creates their own Imports/YYYY/MM-Month/Batch_<id> path beneath it.
        file_id, url = GoogleDriveMediaStorage().upload(
            batch.source_content,
            filename=_archive_filename(batch),
            mime_type=batch.source_mime_type or 'application/octet-stream',
            id_number='portal_imports',
            received_at=batch.created_at or timezone.now(),
            workflow_key='Imports',
            record_type='Batch',
            record_key=str(batch.pk),
            attempt_budget=1,
        )
        return {'id': file_id, 'url': url}

    try:
        result = execute_operation(operation, archive_once, attempt_budget=1)
    except ExternalOperationError:
        mark_drive_failure(batch, 'Drive archive needs attention. Retry from Imports.', prefix='archive', error_field='archive_error')
        operation.refresh_from_db()
        return {'ok': False, 'batch': batch, 'operation': operation, 'error': batch.archive_error}
    if not result:
        operation.refresh_from_db()
        return {'ok': False, 'batch': batch, 'operation': operation, 'error': 'Drive archive is already being processed.'}
    file_id = str(result.get('id') or '')
    url = str(result.get('url') or result.get('webViewLink') or '')
    if not file_id or not url:
        batch.archive_error = 'Drive archive completed without a usable file reference.'
        batch.save(update_fields=['archive_error', 'updated_at'])
        return {'ok': False, 'batch': batch, 'operation': operation, 'error': batch.archive_error}
    mark_drive_success(batch, file_id=file_id, url=url, prefix='archive', error_field='archive_error')
    return {'ok': True, 'batch': batch, 'operation': operation, 'replayed': False}


def import_archive_state(batch: JawabuFarmerUploadBatch) -> str:
    if batch.archive_file_id and batch.archive_url:
        return 'archived'
    if batch.archive_error:
        return 'needs_attention'
    return 'pending'


def archive_operation_ids(batches: list[JawabuFarmerUploadBatch]) -> dict[str, str]:
    """Fetch archive-operation IDs in one query for an already scoped batch list."""
    batch_ids = [str(batch.pk) for batch in batches]
    if not batch_ids:
        return {}
    return {
        str(operation['source_id']): str(operation['id'])
        for operation in IntegrationOperation.objects.filter(
            source_model=SOURCE_MODEL,
            operation_type=ARCHIVE_OPERATION,
            source_id__in=batch_ids,
        ).values('id', 'source_id')
    }


def serialize_import_batch(
    batch: JawabuFarmerUploadBatch, *, include_rows: bool = False, archive_operation_id: str = '',
) -> dict[str, Any]:
    """Return staff-safe metadata; raw bytes and Drive URLs stay private."""
    review_rows = list(batch.parsed_rows or [])
    disposition_counts = {
        key: sum(1 for row in review_rows if str(row.get('disposition') or '') == key)
        for key in ('commit_now', 'hold', 'exclude', 'excluded', 'committed', 'already_committed')
    }
    payload: dict[str, Any] = {
        'id': str(batch.pk),
        'kind': 'farmup' if batch.import_kind == 'farmers' else 'sysup',
        'source_filename': batch.source_filename,
        'source_size': int(batch.source_size or 0),
        'group_id': batch.group_id,
        'status': batch.status,
        'total_rows': batch.total_rows,
        'review_needed': batch.review_needed,
        'committed_count': batch.committed_count,
        'skipped_count': batch.skipped_count,
        'remaining_count': sum(
            value for key, value in disposition_counts.items()
            if key in {'commit_now', 'hold', 'exclude'}
        ),
        'disposition_counts': disposition_counts,
        'worklist_id': str(batch.worklist_id),
        'period': batch.period_month.strftime('%Y-%m') if batch.period_month else '',
        'period_label': batch.period_month.strftime('%B %Y') if batch.period_month else 'Legacy import',
        'version_number': int(batch.version_number or 1),
        'is_current_version': bool(batch.is_current_version),
        'reconciliation': dict(batch.reconciliation or {}),
        'publication': _farmup_publication_summary(batch) if batch.import_kind == 'farmers' else {'status': 'not_required'},
        'error': batch.error,
        'created_at': batch.created_at.isoformat() if batch.created_at else None,
        'updated_at': batch.updated_at.isoformat() if batch.updated_at else None,
        'created_by': str(getattr(batch.created_by, 'get_full_name', lambda: '')() or getattr(batch.created_by, 'username', '') or batch.sender or ''),
        'archive_state': import_archive_state(batch),
        'archive_error': batch.archive_error or '',
        'archive_attempts': int(batch.archive_sync_attempts or 0),
        'archive_last_attempt_at': batch.archive_last_sync_at.isoformat() if batch.archive_last_sync_at else None,
        'archive_next_retry_at': batch.archive_next_retry_at.isoformat() if batch.archive_next_retry_at else None,
        'archive_operation_id': str(archive_operation_id or ''),
        'is_portal_archived': bool(batch.is_portal_archived),
        'portal_archived_at': batch.portal_archived_at.isoformat() if batch.portal_archived_at else None,
        'portal_archived_by': str(
            getattr(batch.portal_archived_by, 'get_full_name', lambda: '')()
            or getattr(batch.portal_archived_by, 'username', '')
            or ''
        ),
    }
    if batch.import_kind == 'farmers' and include_rows:
        payload['versions'] = [
            {
                'id': str(item['pk']), 'version_number': int(item['version_number'] or 1),
                'source_filename': item['source_filename'],
                'source_size': int(item['source_size'] or 0),
                'created_at': item['created_at'].isoformat() if item['created_at'] else None,
                'is_current_version': bool(item['is_current_version']),
            }
            for item in JawabuFarmerUploadBatch.objects.filter(
                worklist_id=batch.worklist_id, import_kind='farmers',
            ).order_by('-version_number').values(
                'pk', 'version_number', 'source_filename', 'source_size',
                'created_at', 'is_current_version',
            )
        ]
    if include_rows:
        payload['mapping'] = _batch_mapping_payload(batch, include_samples=True)
        payload['rows'] = review_rows
    else:
        payload['mapping_state'] = _batch_mapping_payload(batch).get('state', 'legacy')
    return payload


def _farmup_publication_summary(batch: JawabuFarmerUploadBatch) -> dict[str, Any]:
    replay_ledgers = JawabuFarmerUploadBatch.objects.filter(
        worklist_id=batch.worklist_id, import_kind='farmers',
    ).values_list('portal_commit_replays', flat=True)
    operation_ids = {
        str(operation.get('id'))
        for ledger in replay_ledgers
        for replay in list(ledger or [])
        if replay.get('operation') in (None, 'commit')
        for publication in list((replay.get('result') or {}).get('publications') or [])
        for operation in list(publication.get('operations') or [])
        if operation.get('id')
    }
    if not operation_ids:
        return {'status': 'not_required', 'total': 0, 'synced': 0, 'pending_operation_ids': []}
    operations = list(IntegrationOperation.objects.filter(pk__in=operation_ids))
    pending_statuses = {
        IntegrationOperation.STATUS_PENDING, IntegrationOperation.STATUS_RUNNING,
        IntegrationOperation.STATUS_RETRYABLE,
    }
    pending = [str(item.pk) for item in operations if item.status in pending_statuses]
    failed = sum(1 for item in operations if item.status == IntegrationOperation.STATUS_DEAD_LETTER)
    synced = sum(1 for item in operations if item.status == IntegrationOperation.STATUS_SUCCEEDED)
    status = 'needs_attention' if failed else ('pending' if pending else 'synced')
    return {
        'status': status, 'total': len(operations), 'synced': synced,
        'needs_attention': failed, 'pending_operation_ids': pending,
    }
