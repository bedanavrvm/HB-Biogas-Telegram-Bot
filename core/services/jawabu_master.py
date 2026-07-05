"""CSV import and cleaning for Jawabu farmer master data."""
from __future__ import annotations

import base64
import binascii
import csv
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
import io
import logging
from typing import Iterable, TextIO
from urllib.parse import urlencode

from django.conf import settings
from django.core import signing
from django.db import transaction
from django.utils import timezone

from core.models import JawabuFarmerMaster, JawabuFarmerUploadBatch
logger = logging.getLogger(__name__)

from core.services.jawabu import (
    is_valid_phone,
    jawabu_duplicate_key,
    normalise_county,
    normalise_phone,
)


HEADER_ALIASES = {
    'external_id': {
        'external id', 'external_id', 'farmer id', 'farmer code', 'customer id',
        'customer code', 'record id', 'id code', 'code',
    },
    'customer_name': {
        'customer name', 'name', 'farmer name', 'client name', 'full name',
        'customer', 'farmer',
    },
    'national_id': {
        'national id', 'national id number', 'id number', 'id no', 'id no.',
        'id', 'customer id number', 'passport id', 'national id/passport',
    },
    'primary_phone': {
        'primary phone', 'phone', 'phone number', 'mobile', 'mobile number',
        'tel', 'telephone', 'contact', 'contacts', 'contact number',
    },
    'secondary_phone': {
        'secondary phone', 'alternative phone', 'alternate phone', 'alt phone',
        'phone 2', 'phone two', 'secondary contact', 'other phone',
    },
    'county': {'county', 'state', 'region', 'hbg hub'},
    'sub_county': {'sub county', 'sub-county', 'subcounty', 'district', 'constituency'},
    'ward': {'ward'},
    'village': {'village', 'estate', 'area'},
    'landmark': {'landmark', 'nearest landmark', 'location', 'address'},
    'branch': {'branch', 'office', 'hbg hub'},
    'gps_link': {'gps link', 'map link', 'maps link', 'google map', 'google maps'},
    'latitude': {'latitude', 'lat'},
    'longitude': {'longitude', 'long', 'lng', 'lon'},
    'status': {'status', 'active'},
    'hbg_contract_name': {'hbg contract name', 'contract name'},
    'lead_source': {'financial partners', 'financial partner', 'lead source'},
    'contract_type': {'contract type'},
    'installation_status': {'installation status'},
    'actual_receipts_currency': {'actual receipts currency', 'currency'},
    'actual_receipts': {'actual receipts', 'receipts', 'deposit', 'amount paid'},
    'hb_sales_person': {'sales person', 'hb sales person', 'sales rep'},
    'sign_date': {'sign date'},
    'created_date': {'created date'},
    'comments': {'comments', 'comment'},
}

CANONICAL_FIELDS = [
    'external_id', 'customer_name', 'national_id', 'primary_phone',
    'secondary_phone', 'county', 'sub_county', 'ward', 'village', 'landmark',
    'branch', 'gps_link', 'latitude', 'longitude', 'status',
    'hbg_contract_name', 'lead_source', 'contract_type', 'installation_status',
    'actual_receipts_currency', 'actual_receipts', 'hb_sales_person', 'sign_date',
    'created_date', 'comments',
]

FARMERS_TO_MASTER_MAPPING = [
    {
        'source_column': 'Full Name',
        'master_column': 'Customer Name',
        'field': 'customer_name',
        'confidence': 'high',
        'notes': 'Cleaned to uppercase. Bracketed National ID is removed from the name.',
    },
    {
        'source_column': 'ID NUMBER or bracketed ID in Full Name',
        'master_column': 'National ID',
        'field': 'national_id',
        'confidence': 'high',
        'notes': 'Uses ID NUMBER first. If blank, extracts digits from names like Jane Doe [12345678].',
    },
    {
        'source_column': 'Mobile',
        'master_column': 'Primary Phone',
        'field': 'primary_phone',
        'confidence': 'high',
        'notes': 'Normalized to consistent 254 format.',
    },
    {
        'source_column': 'Phone',
        'master_column': 'Secondary Phone',
        'field': 'secondary_phone',
        'confidence': 'high',
        'notes': 'Normalized to consistent 254 format.',
    },
    {
        'source_column': 'HBG Hub',
        'master_column': 'County',
        'field': 'county',
        'confidence': 'high',
        'notes': 'Confirmed mapping. Cleaned to uppercase county name.',
    },
    {
        'source_column': 'Sales Person',
        'master_column': 'HB Sales Person',
        'field': 'hb_sales_person',
        'confidence': 'high',
        'notes': 'Cleaned to uppercase and removes bracketed staff IDs.',
    },
    {
        'source_column': 'Financial Partners',
        'master_column': 'Lead Source',
        'field': 'lead_source',
        'confidence': 'medium',
        'notes': 'Jawabu values become JAWABU. Kept for review until all source types are known.',
    },
    {
        'source_column': 'Actual Receipts',
        'master_column': 'Deposit Paid to HB',
        'field': 'actual_receipts',
        'confidence': 'high',
        'notes': 'Confirmed mapping. Cleaned as a numeric KES amount.',
    },
    {
        'source_column': 'Installation Status',
        'master_column': 'Installation Status',
        'field': 'installation_status',
        'confidence': 'medium',
        'notes': 'Normalized lightly to the master dropdown wording.',
    },
    {
        'source_column': 'HBG Contract Name',
        'master_column': '<ignored>',
        'field': 'hbg_contract_name',
        'confidence': 'high',
        'notes': 'Ignored for master-data writes. Original value remains in raw_data only.',
    },
    {
        'source_column': 'Second Sign Date with value',
        'master_column': 'HBG Visit Date',
        'field': 'sign_date',
        'confidence': 'high',
        'notes': 'Uses Sign Date__2 when populated, otherwise falls back to Sign Date. Formatted as 24-June-2026.',
    },
    {
        'source_column': 'Created Date',
        'master_column': '<ignored>',
        'field': 'created_date',
        'confidence': 'high',
        'notes': 'Ignored for master-data writes. Original value remains in raw_data only.',
    },
    {
        'source_column': 'COMMENTS',
        'master_column': 'Additional Comments',
        'field': 'comments',
        'confidence': 'medium',
        'notes': 'Cleaned as free text.',
    },
]

MASTER_PREVIEW_HEADERS = [
    'Customer Name', 'National ID', 'Primary Phone', 'Secondary Phone', 'County',
    'Constituency', 'Village', 'Lead Source', 'HB Sales Person', 'HBG Visit Date',
    'HBG Visit Comment', 'Additional Comments', 'Deposit Paid to HB',
    'Installation Status', 'Order No.', 'Import Status', 'Cleaning Notes',
    'Source File', 'Source Row', 'Ignored HBG Contract Name', 'Raw Sign Date',
    'Raw Contract Type', 'Raw Financial Partners',
]

MASTER_SYSTEM_HEADERS = [
    'Master Record ID',
    'Import Batch ID',
    'Source Filename',
    'Source Row',
    'Duplicate Key',
    'Import Status',
    'Review Notes',
    'Reviewed By',
    'Reviewed At',
    'Last Updated At',
]

MASTER_FIELD_HEADERS = {
    'customer_name': ['Customer Name'],
    'national_id': ['National ID'],
    'primary_phone': ['Primary Phone'],
    'secondary_phone': ['Secondary Phone'],
    'county': ['County'],
    'sub_county': ['Constituency', 'Sub County', 'Sub-County'],
    'village': ['Village'],
    'lead_source': ['Lead Source'],
    'hb_sales_person': ['HB Sales Person'],
    'sign_date': ['HBG Visit Date'],
    'comments': ['Additional Comments'],
    'actual_receipts': ['Deposit Paid to HB', 'Deposit Paid to HBG', 'Deposit Paid to JBL'],
    'installation_status': ['Installation Status'],
}

MASTER_NORMAL_WRITE_FIELDS = [
    'customer_name', 'national_id', 'primary_phone', 'secondary_phone', 'county',
    'sub_county', 'village', 'lead_source', 'hb_sales_person', 'sign_date',
    'comments', 'actual_receipts', 'installation_status',
]


FARMUP_TOKEN_SALT = 'jawabu-farmer-upload'


def create_farmup_review_token(batch_id: str) -> str:
    return signing.dumps({'batch_id': str(batch_id)}, salt=FARMUP_TOKEN_SALT)


def validate_farmup_review_token(batch_id: str, token: str) -> tuple[bool, str]:
    try:
        payload = signing.loads(token or '', salt=FARMUP_TOKEN_SALT, max_age=7 * 24 * 3600)
    except signing.BadSignature:
        return False, 'This farm upload review link is invalid or expired.'
    if str(payload.get('batch_id', '')) != str(batch_id):
        return False, 'This farm upload review link does not match the batch.'
    return True, ''


def build_farmup_review_url(batch_id: str) -> str:
    base_url = getattr(settings, 'APP_BASE_URL', '').rstrip('/')
    if not base_url:
        return ''
    return (
        f"{base_url}/jawabu-farmers/review/?"
        + urlencode({'batch_id': str(batch_id), 'token': create_farmup_review_token(batch_id)})
    )

def build_farmup_mini_app_url(batch_id: str) -> str:
    bot_username = str(getattr(settings, 'TELEGRAM_BOT_USERNAME', '') or '').strip().lstrip('@')
    short_name = str(getattr(settings, 'FARMUP_MINI_APP_SHORT_NAME', '') or '').strip().strip('/')
    if not bot_username or not short_name:
        return ''
    return f"https://t.me/{bot_username}/{short_name}?startapp={create_farmup_start_param(batch_id)}"


def create_farmup_start_param(batch_id: str) -> str:
    payload = {
        'batch_id': str(batch_id),
        'token': create_farmup_review_token(batch_id),
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(',', ':')).encode('utf-8')
    ).decode('ascii')
    return encoded.rstrip('=')


def decode_farmup_start_param(start_param: str) -> dict[str, str]:
    value = str(start_param or '').strip()
    if not value:
        return {}
    padding = '=' * (-len(value) % 4)
    try:
        payload = json.loads(
            base64.urlsafe_b64decode((value + padding).encode('ascii')).decode('utf-8')
        )
    except (binascii.Error, ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    batch_id = str(payload.get('batch_id', '')).strip()
    token = str(payload.get('token', '')).strip()
    if not batch_id or not token:
        return {}
    return {'batch_id': batch_id, 'token': token}




def create_farmup_review_batch(
    *,
    group_id: str,
    telegram_message_id: str,
    sender: str,
    source_filename: str,
    csv_text: str,
) -> tuple[JawabuFarmerUploadBatch, dict]:
    rows, stats = build_cleaned_master_preview(
        io.StringIO(csv_text),
        source_name=source_filename,
    )
    review_rows = []
    for index, row in enumerate(rows, start=1):
        editable = dict(row)
        editable['row_id'] = index
        editable['approved'] = row.get('Import Status') != 'review_needed'
        review_rows.append(editable)
    batch = JawabuFarmerUploadBatch.objects.create(
        group_id=str(group_id),
        telegram_message_id=str(telegram_message_id or ''),
        sender=str(sender or ''),
        source_filename=str(source_filename or 'farmers.csv'),
        total_rows=stats.get('total_rows', 0),
        review_needed=stats.get('review_needed', 0),
        parsed_rows=review_rows,
        mapping=mapping_review_rows(),
    )
    return batch, stats


@transaction.atomic
def commit_farmup_review_batch(batch: JawabuFarmerUploadBatch, rows: list[dict], group_config=None) -> dict:
    if batch.status == 'committed':
        return {
            'success': False,
            'message': 'This batch has already been committed.',
            'committed': batch.committed_count,
            'skipped': batch.skipped_count,
        }

    previous_committed = batch.committed_count or 0
    committed = 0
    skipped = 0
    errors = []
    remaining_rows = []
    committed_display_rows = []
    committed_cleaned_rows = []
    now = timezone.now()
    for index, row in enumerate(rows, start=1):
        row = dict(row or {})
        row['row_id'] = row.get('row_id') or index
        if not row.get('approved'):
            skipped += 1
            remaining_rows.append(row)
            continue
        cleaned = cleaned_master_row_from_review(row, batch, index, now)
        if not cleaned['customer_name']:
            errors.append(f"Row {index}: Customer Name is required.")
            row['Import Status'] = 'review_needed'
            row['Cleaning Notes'] = append_note(row.get('Cleaning Notes', ''), 'Customer Name is required')
            remaining_rows.append(row)
            continue
        if not cleaned['national_id'] and not cleaned['primary_phone']:
            errors.append(f"Row {index}: National ID or Primary Phone is required.")
            row['Import Status'] = 'review_needed'
            row['Cleaning Notes'] = append_note(row.get('Cleaning Notes', ''), 'National ID or Primary Phone is required')
            remaining_rows.append(row)
            continue
        if cleaned['primary_phone'] and not is_valid_phone(cleaned['primary_phone']):
            errors.append(f"Row {index}: Primary Phone must be in 254 format.")
            row['Import Status'] = 'review_needed'
            row['Cleaning Notes'] = append_note(row.get('Cleaning Notes', ''), 'Primary Phone must be in 254 format')
            remaining_rows.append(row)
            continue
        if cleaned['secondary_phone'] and not is_valid_phone(cleaned['secondary_phone']):
            errors.append(f"Row {index}: Secondary Phone must be in 254 format.")
            row['Import Status'] = 'review_needed'
            row['Cleaning Notes'] = append_note(row.get('Cleaning Notes', ''), 'Secondary Phone must be in 254 format')
            remaining_rows.append(row)
            continue
        farmer_created, farmer_status = upsert_farmer(cleaned)
        cleaned['_farmer_created'] = farmer_created
        cleaned['_farmer_status'] = farmer_status
        committed_cleaned_rows.append(cleaned)
        committed += 1
        row['Import Status'] = 'active'
        committed_display_rows.append(row)

    sheet_sync = sync_committed_farmup_rows_to_master_sheet(
        batch=batch,
        cleaned_rows=committed_cleaned_rows,
        group_config=group_config,
    )
    sync_errors = sheet_sync.get('errors') or []
    success = not errors and sheet_sync.get('success', True)
    if success:
        saved_rows = remaining_rows
    else:
        saved_rows = committed_display_rows + remaining_rows
        for row in committed_display_rows:
            row['Import Status'] = 'review_needed'
            row['Cleaning Notes'] = append_note(
                row.get('Cleaning Notes', ''),
                'Committed locally but Master Data sheet sync needs retry'
            )
    batch.parsed_rows = saved_rows
    batch.committed_count = previous_committed + committed
    batch.skipped_count = skipped
    batch.review_needed = sum(1 for row in saved_rows if row.get('Import Status') == 'review_needed')
    batch.status = 'committed' if success and not saved_rows else 'pending_review'
    batch.error = '\n'.join((errors + sync_errors)[:20])
    if batch.status == 'committed':
        batch.committed_at = now
    batch.save()
    return {
        'success': success,
        'message': (
            'Batch committed.'
            if success
            else 'Some rows still need correction or sheet sync failed.'
        ),
        'committed': committed,
        'skipped': skipped,
        'errors': (errors + sync_errors)[:20],
        'review_needed': batch.review_needed,
        'sheet_sync': sheet_sync,
    }


def sync_committed_farmup_rows_to_master_sheet(
    *,
    batch: JawabuFarmerUploadBatch,
    cleaned_rows: list[dict],
    group_config=None,
) -> dict:
    if not cleaned_rows:
        return {'success': True, 'enabled': False, 'created': 0, 'updated': 0, 'conflicts': 0, 'errors': []}
    workflow = getattr(group_config, 'workflow', None) or {}
    if not workflow.get('master_sync_enabled'):
        return {'success': True, 'enabled': False, 'created': 0, 'updated': 0, 'conflicts': 0, 'errors': []}

    sheet_id = str(workflow.get('master_sheet_id') or getattr(group_config, 'sheet_id', '') or '').strip()
    sheet_name = str(workflow.get('master_sheet_name') or 'Master Data').strip()
    header_row = positive_int(workflow.get('master_header_row'), 3)
    data_start_row = positive_int(workflow.get('master_data_start_row'), header_row + 2)
    log_sheet_name = str(workflow.get('master_import_log_sheet_name') or '').strip()
    if not sheet_id or not sheet_name:
        return {
            'success': False, 'enabled': True, 'created': 0, 'updated': 0, 'conflicts': 0,
            'errors': ['Master sheet sync is enabled but master_sheet_id/master_sheet_name is incomplete.'],
        }

    try:
        from core.services.sheets import GoogleSheetsService

        service = GoogleSheetsService.get_instance(sheet_id=sheet_id, sheet_name=sheet_name)
        if not service.is_available():
            raise RuntimeError('Google Sheets service unavailable for Master Data sheet.')
        sheet = service._sheet
        headers = ensure_master_system_headers(sheet, header_row)
        result = write_rows_to_master_sheet(
            sheet=sheet,
            headers=headers,
            data_start_row=data_start_row,
            batch=batch,
            cleaned_rows=cleaned_rows,
        )
        if log_sheet_name:
            append_master_import_log(
                service=service,
                log_sheet_name=log_sheet_name,
                batch=batch,
                result=result,
            )
        return {'success': result['errors'] == [], 'enabled': True, **result}
    except Exception as exc:  # pragma: no cover - defensive external API handling
        logger.error('Farmup Master Data sheet sync failed: %s', exc, exc_info=True)
        return {
            'success': False, 'enabled': True, 'created': 0, 'updated': 0, 'conflicts': 0,
            'errors': [f'Master Data sheet sync failed: {exc}'],
        }


def ensure_master_system_headers(sheet, header_row: int) -> list[str]:
    headers = list(sheet.row_values(header_row))
    start_col = 45  # AS. Keep system metadata at the far-right fixed block.
    end_col = start_col + len(MASTER_SYSTEM_HEADERS) - 1
    if end_col > getattr(sheet, 'col_count', end_col):
        sheet.add_cols(end_col - sheet.col_count)
    if len(headers) < end_col:
        headers.extend([''] * (end_col - len(headers)))

    canonical_names = {normalize_header(header) for header in MASTER_SYSTEM_HEADERS}
    cleanup_cells = []
    for index, header in enumerate(headers, start=1):
        if start_col <= index <= end_col:
            continue
        if normalize_header(header) in canonical_names:
            cleanup_cells.append((header_row, index, ''))
            cleanup_cells.append((header_row + 1, index, ''))
            headers[index - 1] = ''

    for offset, header in enumerate(MASTER_SYSTEM_HEADERS):
        col = start_col + offset
        headers[col - 1] = header
        cleanup_cells.append((header_row, col, header))
        cleanup_cells.append((
            header_row + 1,
            col,
            'SYSTEM: hidden metadata used by Django import/sync. Do not edit.',
        ))

    update_sheet_cells(sheet, cleanup_cells)
    hide_master_system_columns(sheet, start_col, end_col)
    return headers


def update_sheet_cells(sheet, cells: list[tuple[int, int, str]]) -> None:
    if not cells:
        return
    try:
        from gspread import Cell
        sheet.update_cells([Cell(row, col, value) for row, col, value in cells], value_input_option='RAW')
    except Exception:
        for row, col, value in cells:
            sheet.update_cell(row, col, value)


def hide_master_system_columns(sheet, start_col: int, end_col: int) -> None:
    try:
        sheet_id = sheet.id
        sheet.spreadsheet.batch_update({
            'requests': [{
                'updateDimensionProperties': {
                    'range': {
                        'sheetId': sheet_id,
                        'dimension': 'COLUMNS',
                        'startIndex': start_col - 1,
                        'endIndex': end_col,
                    },
                    'properties': {'hiddenByUser': True},
                    'fields': 'hiddenByUser',
                }
            }]
        })
    except Exception as exc:  # pragma: no cover - optional presentation step
        logger.warning('Could not hide Master Data system columns: %s', exc)


def write_rows_to_master_sheet(
    *,
    sheet,
    headers: list[str],
    data_start_row: int,
    batch: JawabuFarmerUploadBatch,
    cleaned_rows: list[dict],
) -> dict:
    values = sheet.get_all_values()
    header_lookup = header_lookup_from_headers(headers)
    existing = build_master_existing_index(values, header_lookup, data_start_row)
    created = updated = conflicts = 0
    errors = []
    pending_updates = []
    now_text = timezone.now().strftime('%d-%B-%Y %H:%M')
    for cleaned in cleaned_rows:
        try:
            row_number = find_master_row_number(cleaned, existing)
            if row_number:
                row_values = row_values_for_number(values, row_number, len(headers))
                change_count, conflict_notes = merge_master_row_values(
                    row_values=row_values,
                    headers=headers,
                    header_lookup=header_lookup,
                    cleaned=cleaned,
                    batch=batch,
                    now_text=now_text,
                    created=False,
                )
                if conflict_notes:
                    conflicts += 1
                if change_count:
                    pending_updates.append((row_number, row_values))
                    values = pad_values_to_row(values, row_number, len(headers))
                    values[row_number - 1] = row_values
                    updated += 1
                continue

            row_number = next_master_append_row(values, header_lookup, data_start_row)
            row_values = [''] * len(headers)
            set_header_value(row_values, header_lookup, 'No.', row_number - data_start_row + 1)
            merge_master_row_values(
                row_values=row_values,
                headers=headers,
                header_lookup=header_lookup,
                cleaned=cleaned,
                batch=batch,
                now_text=now_text,
                created=True,
            )
            pending_updates.append((row_number, row_values))
            values = pad_values_to_row(values, row_number, len(headers))
            values[row_number - 1] = row_values
            add_master_index_row(existing, row_number, row_values, header_lookup)
            created += 1
        except Exception as exc:  # pragma: no cover - defensive per-row handling
            errors.append(f"{cleaned.get('customer_name') or cleaned.get('national_id') or 'row'}: {exc}")
    if pending_updates:
        try:
            batch_update_master_sheet_rows(sheet, pending_updates, len(headers))
        except Exception as exc:  # pragma: no cover - defensive external API handling
            errors.append(f'Master Data batch write failed: {exc}')
    return {'created': created, 'updated': updated, 'conflicts': conflicts, 'errors': errors[:20]}


def batch_update_master_sheet_rows(sheet, updates: list[tuple[int, list]], width: int) -> None:
    if not updates:
        return
    payload = []
    for start_row, block_rows in compact_master_sheet_updates(updates):
        end_row = start_row + len(block_rows) - 1
        payload.append({
            'range': f'A{start_row}:{col_letter(width)}{end_row}',
            'values': block_rows,
        })
    sheet.batch_update(payload, value_input_option='RAW')


def compact_master_sheet_updates(updates: list[tuple[int, list]]) -> list[tuple[int, list[list]]]:
    ordered = sorted(updates, key=lambda item: item[0])
    blocks = []
    current_start = None
    current_rows = []
    previous_row = None
    for row_number, row_values in ordered:
        if current_start is None:
            current_start = row_number
            current_rows = [row_values]
        elif previous_row is not None and row_number == previous_row + 1:
            current_rows.append(row_values)
        else:
            blocks.append((current_start, current_rows))
            current_start = row_number
            current_rows = [row_values]
        previous_row = row_number
    if current_start is not None:
        blocks.append((current_start, current_rows))
    return blocks


def merge_master_row_values(
    *,
    row_values: list,
    headers: list[str],
    header_lookup: dict[str, int],
    cleaned: dict,
    batch: JawabuFarmerUploadBatch,
    now_text: str,
    created: bool,
) -> tuple[int, list[str]]:
    before = list(row_values)
    conflict_notes = []
    for field in MASTER_NORMAL_WRITE_FIELDS:
        target_header = first_existing_header(header_lookup, MASTER_FIELD_HEADERS[field])
        if not target_header:
            continue
        new_value = cleaned.get(field, '')
        if new_value in (None, ''):
            continue
        idx = header_lookup[normalize_header(target_header)] - 1
        current = row_values[idx] if idx < len(row_values) else ''
        if values_equivalent(current, new_value):
            row_values[idx] = new_value
        elif not str(current or '').strip():
            row_values[idx] = new_value
        else:
            conflict_notes.append(f"{target_header}: sheet '{current}' vs upload '{new_value}'")

    status = 'created' if created else ('updated_with_conflict' if conflict_notes else 'updated')
    set_header_value(row_values, header_lookup, 'Master Record ID', str(cleaned.get('id') or cleaned.get('duplicate_key') or ''))
    set_header_value(row_values, header_lookup, 'Import Batch ID', str(batch.id))
    set_header_value(row_values, header_lookup, 'Source Filename', batch.source_filename)
    set_header_value(row_values, header_lookup, 'Source Row', cleaned.get('source_row_number') or '')
    set_header_value(row_values, header_lookup, 'Duplicate Key', cleaned.get('duplicate_key') or '')
    set_header_value(row_values, header_lookup, 'Import Status', status)
    set_header_value(row_values, header_lookup, 'Review Notes', '; '.join(conflict_notes) or cleaned.get('cleaning_notes') or '')
    set_header_value(row_values, header_lookup, 'Reviewed By', batch.sender)
    set_header_value(row_values, header_lookup, 'Reviewed At', now_text)
    set_header_value(row_values, header_lookup, 'Last Updated At', now_text)
    return sum(1 for old, new in zip(before, row_values) if str(old or '') != str(new or '')), conflict_notes


def append_master_import_log(*, service, log_sheet_name: str, batch: JawabuFarmerUploadBatch, result: dict) -> None:
    try:
        spreadsheet = service._client.open_by_key(service._sheet_id)
        try:
            sheet = spreadsheet.worksheet(log_sheet_name)
        except Exception:
            sheet = spreadsheet.add_worksheet(title=log_sheet_name, rows=100, cols=10)
            sheet.update('A1:J1', [[
                'Batch ID', 'Source Filename', 'Group ID', 'Uploaded By', 'Committed At',
                'Total Rows', 'Created', 'Updated', 'Conflicts', 'Errors',
            ]])
        sheet.append_row([
            str(batch.id), batch.source_filename, batch.group_id, batch.sender,
            timezone.now().strftime('%d-%B-%Y %H:%M'), batch.total_rows,
            result.get('created', 0), result.get('updated', 0), result.get('conflicts', 0),
            '; '.join(result.get('errors') or []),
        ], value_input_option='USER_ENTERED')
    except Exception as exc:  # pragma: no cover - optional audit log
        logger.warning('Could not append Farmers Upload Log row: %s', exc, exc_info=True)


def header_lookup_from_headers(headers: list[str]) -> dict[str, int]:
    return {normalize_header(header): index + 1 for index, header in enumerate(headers) if str(header or '').strip()}


def first_existing_header(header_lookup: dict[str, int], candidates: list[str]) -> str:
    for candidate in candidates:
        if normalize_header(candidate) in header_lookup:
            return candidate
    return ''


def row_values_for_number(values: list[list[str]], row_number: int, width: int) -> list[str]:
    if row_number - 1 < len(values):
        row_values = list(values[row_number - 1])
    else:
        row_values = []
    return row_values + [''] * (width - len(row_values))


def pad_values_to_row(values: list[list[str]], row_number: int, width: int) -> list[list[str]]:
    while len(values) < row_number:
        values.append([''] * width)
    return values


def next_master_append_row(values: list[list[str]], header_lookup: dict[str, int], data_start_row: int) -> int:
    name_idx = header_lookup.get(normalize_header('Customer Name'), 2) - 1
    last = data_start_row - 1
    for row_number, row in enumerate(values[data_start_row - 1:], start=data_start_row):
        if name_idx < len(row) and str(row[name_idx] or '').strip():
            last = row_number
    return last + 1


def build_master_existing_index(values: list[list[str]], header_lookup: dict[str, int], data_start_row: int) -> dict[str, int]:
    existing = {}
    for row_number, row_values in enumerate(values[data_start_row - 1:], start=data_start_row):
        add_master_index_row(existing, row_number, row_values, header_lookup)
    return existing


def add_master_index_row(existing: dict[str, int], row_number: int, row_values: list, header_lookup: dict[str, int]) -> None:
    duplicate_key = header_row_value(row_values, header_lookup, 'Duplicate Key')
    if duplicate_key:
        existing[f'duplicate_key:{duplicate_key}'] = row_number
    national_id = header_row_value(row_values, header_lookup, 'National ID')
    primary_phone = header_row_value(row_values, header_lookup, 'Primary Phone')
    if national_id and primary_phone:
        existing[f'id_phone:{national_id}|{primary_phone}'] = row_number
    if national_id:
        existing.setdefault(f'id:{national_id}', row_number)
    if primary_phone:
        existing.setdefault(f'phone:{primary_phone}', row_number)


def find_master_row_number(cleaned: dict, existing: dict[str, int]) -> int:
    duplicate_key = cleaned.get('duplicate_key') or ''
    national_id = cleaned.get('national_id') or ''
    primary_phone = cleaned.get('primary_phone') or ''
    for key in (
        f'duplicate_key:{duplicate_key}' if duplicate_key else '',
        f'id_phone:{national_id}|{primary_phone}' if national_id and primary_phone else '',
        f'id:{national_id}' if national_id else '',
        f'phone:{primary_phone}' if primary_phone else '',
    ):
        if key and key in existing:
            return existing[key]
    return 0


def header_row_value(row_values: list, header_lookup: dict[str, int], header: str) -> str:
    index = header_lookup.get(normalize_header(header), 0) - 1
    if index < 0 or index >= len(row_values):
        return ''
    return str(row_values[index] or '').strip()


def set_header_value(row_values: list, header_lookup: dict[str, int], header: str, value) -> None:
    index = header_lookup.get(normalize_header(header), 0) - 1
    if index < 0:
        return
    if index >= len(row_values):
        row_values.extend([''] * (index - len(row_values) + 1))
    row_values[index] = '' if value is None else value


def update_master_sheet_row(sheet, row_number: int, row_values: list) -> None:
    end_cell = f"{col_letter(len(row_values))}{row_number}"
    # Preserve reviewed text exactly as staff see it in the form. USER_ENTERED
    # lets Google Sheets reinterpret values such as 24-March-2026 as locale
    # dates, which can display as mm/dd/yy in the Master Data sheet.
    sheet.update(f"A{row_number}:{end_cell}", [row_values], value_input_option='RAW')


def values_equivalent(left, right) -> bool:
    return clean_text(left).casefold() == clean_text(right).casefold()


def positive_int(value, default: int) -> int:
    try:
        return max(int(value), 1)
    except (TypeError, ValueError):
        return default


def col_letter(col_index: int) -> str:
    letters = ''
    while col_index > 0:
        col_index, rem = divmod(col_index - 1, 26)
        letters = chr(65 + rem) + letters
    return letters


def cleaned_master_row_from_review(
    row: dict,
    batch: JawabuFarmerUploadBatch,
    index: int,
    imported_at,
) -> dict:
    customer_name = clean_name(row.get('Customer Name', ''))
    national_id = clean_national_id(row.get('National ID', ''))
    primary_phone = normalise_phone(row.get('Primary Phone', ''))
    secondary_phone = normalise_phone(row.get('Secondary Phone', ''))
    county = normalise_county(row.get('County', '')).upper()
    duplicate_key = jawabu_duplicate_key(national_id, primary_phone, customer_name)
    raw_data = {
        'review_row': row,
        'upload_batch_id': str(batch.id),
        'source_filename': batch.source_filename,
    }
    return {
        'source': 'jawabu_farmup_review',
        'source_name': batch.source_filename,
        'source_row_number': int(row.get('Source Row') or index),
        'source_fingerprint': row_fingerprint(raw_data),
        'external_id': '',
        'customer_name': customer_name,
        'national_id': national_id,
        'primary_phone': primary_phone,
        'secondary_phone': secondary_phone,
        'county': county,
        'sub_county': clean_text(row.get('Constituency', '')).upper(),
        'ward': '',
        'village': clean_text(row.get('Village', '')).upper(),
        'landmark': '',
        'branch': county,
        'gps_link': '',
        'latitude': '',
        'longitude': '',
        'hbg_contract_name': '',
        'lead_source': clean_lead_source(row.get('Lead Source', '')),
        'contract_type': clean_text(row.get('Raw Contract Type', '')),
        'installation_status': clean_installation_status(row.get('Installation Status', '')),
        'actual_receipts_currency': 'KES' if row.get('Deposit Paid to HB') else '',
        'actual_receipts': clean_decimal(row.get('Deposit Paid to HB', '')),
        'hb_sales_person': clean_sales_person(row.get('HB Sales Person', '')),
        'sign_date': clean_date(row.get('HBG Visit Date', '')),
        'created_date': '',
        'comments': clean_text(row.get('Additional Comments', '')),
        'duplicate_key': duplicate_key,
        'status': 'active',
        'cleaning_notes': clean_text(row.get('Cleaning Notes', '')),
        'raw_data': raw_data,
        'last_imported_at': imported_at,
    }


def append_note(existing: str, note: str) -> str:
    existing = clean_text(existing)
    if not existing:
        return note
    if note in existing:
        return existing
    return f"{existing}; {note}"

@dataclass
class JawabuMasterImportResult:
    total_rows: int = 0
    created: int = 0
    updated: int = 0
    review_needed: int = 0
    skipped_blank: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def imported(self) -> int:
        return self.created + self.updated

    def as_dict(self) -> dict:
        return {
            'total_rows': self.total_rows,
            'created': self.created,
            'updated': self.updated,
            'imported': self.imported,
            'review_needed': self.review_needed,
            'skipped_blank': self.skipped_blank,
            'errors': self.errors,
        }


def import_jawabu_farmers_csv(
    csv_file: TextIO,
    *,
    source_name: str = '',
    dry_run: bool = False,
) -> JawabuMasterImportResult:
    """Import a Jawabu farmers CSV into the internal master table.

    Rows are cleaned and upserted by the same duplicate key used by the
    Jawabu WhatsApp visit workflow. Rows with incomplete identifiers are kept
    as review_needed instead of being silently lost.
    """
    rows, headers = read_csv_rows(csv_file)
    result = JawabuMasterImportResult()
    if not headers:
        result.errors.append('CSV has no header row.')
        return result

    header_map = build_header_map(headers)
    now = timezone.now()
    for source_row_number, raw_row in rows:
        result.total_rows += 1
        try:
            if is_blank_row(raw_row):
                result.skipped_blank += 1
                continue
            cleaned = clean_farmer_row(raw_row, header_map)
            cleaned['source_name'] = source_name
            cleaned['source_row_number'] = source_row_number
            cleaned['last_imported_at'] = now
            cleaned['source_fingerprint'] = row_fingerprint(raw_row)
            if dry_run:
                if cleaned['status'] == 'review_needed':
                    result.review_needed += 1
                result.created += 1
                continue
            was_created, status = upsert_farmer(cleaned)
            if was_created:
                result.created += 1
            else:
                result.updated += 1
            if status == 'review_needed':
                result.review_needed += 1
        except Exception as exc:  # pragma: no cover - defensive per-row import safety
            result.errors.append(f'Row {source_row_number}: {exc}')
    return result


def build_cleaned_master_preview(
    csv_file: TextIO,
    *,
    source_name: str = '',
) -> tuple[list[dict], dict]:
    rows, headers = read_csv_rows(csv_file)
    header_map = build_header_map(headers)
    preview_rows = []
    stats = {
        'total_rows': 0,
        'review_needed': 0,
        'skipped_blank': 0,
        'headers': headers,
        'header_map': header_map,
    }
    for source_row_number, raw_row in rows:
        stats['total_rows'] += 1
        if is_blank_row(raw_row):
            stats['skipped_blank'] += 1
            continue
        cleaned = clean_farmer_row(raw_row, header_map)
        if cleaned['status'] == 'review_needed':
            stats['review_needed'] += 1
        preview_rows.append(master_preview_row(cleaned, source_name, source_row_number))
    return preview_rows, stats


def mapping_review_rows() -> list[dict]:
    return [dict(row) for row in FARMERS_TO_MASTER_MAPPING]


def read_csv_rows(csv_file: TextIO) -> tuple[list[tuple[int, dict]], list[str]]:
    reader = csv.reader(csv_file)
    try:
        raw_headers = next(reader)
    except StopIteration:
        return [], []
    headers = unique_headers(raw_headers)
    rows = []
    for source_row_number, values in enumerate(reader, start=2):
        if len(values) < len(headers):
            values = values + [''] * (len(headers) - len(values))
        row = {header: values[index] if index < len(values) else '' for index, header in enumerate(headers)}
        rows.append((source_row_number, row))
    return rows, headers


def unique_headers(headers: Iterable[str]) -> list[str]:
    seen: dict[str, int] = {}
    result = []
    for index, header in enumerate(headers, start=1):
        base = str(header or '').strip() or f'Column_{index}'
        seen[base] = seen.get(base, 0) + 1
        result.append(base if seen[base] == 1 else f'{base}__{seen[base]}')
    return result


def build_header_map(headers: list[str]) -> dict[str, str]:
    normalized_lookup = {}
    for header in headers:
        normalized_lookup.setdefault(normalize_header(header), header)
    base_lookup = {}
    for header in headers:
        base = re.sub(r'__\d+$', '', header)
        base_lookup.setdefault(normalize_header(base), header)
    header_map: dict[str, str] = {}
    for field, aliases in HEADER_ALIASES.items():
        for alias in aliases | {field}:
            normalized = normalize_header(alias)
            header = base_lookup.get(normalized) or normalized_lookup.get(normalized)
            if header:
                header_map[field] = header
                break
    if 'Mobile' in headers:
        header_map['primary_phone'] = 'Mobile'
        if 'Phone' in headers:
            header_map['secondary_phone'] = 'Phone'
    if 'Sign Date__2' in headers:
        header_map['sign_date'] = 'Sign Date__2'
    elif 'Sign Date' in headers:
        header_map['sign_date'] = 'Sign Date'
    return header_map

def normalize_header(value: str) -> str:
    value = re.sub(r'__\d+$', '', str(value or ''))
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9]+', ' ', value.lower())).strip()


def is_blank_row(row: dict) -> bool:
    return not any(str(value or '').strip() for value in row.values())


def clean_farmer_row(raw_row: dict, header_map: dict[str, str]) -> dict:
    raw_data = {
        str(key or '').strip(): str(value or '').strip()
        for key, value in raw_row.items()
        if str(key or '').strip()
    }
    values = {field: raw_value(raw_row, header_map, field) for field in CANONICAL_FIELDS}
    values['sign_date'] = first_non_blank(raw_row, ['Sign Date__2', 'Sign Date'])
    raw_name = clean_text(values['customer_name'])
    bracketed_id = extract_bracketed_id(raw_name)
    customer_name = clean_name(remove_bracketed_id(raw_name))
    national_id = clean_national_id(values['national_id']) or bracketed_id
    primary_phone = normalise_phone(values['primary_phone'])
    secondary_phone = normalise_phone(values['secondary_phone'])
    county = normalise_county(values['county']).upper()
    duplicate_key = jawabu_duplicate_key(national_id, primary_phone, customer_name)
    info_notes = []
    review_notes = []
    if bracketed_id and not clean_national_id(values['national_id']):
        info_notes.append('National ID extracted from Full Name brackets')
    if not customer_name:
        review_notes.append('Missing customer name')
    if not national_id and not primary_phone:
        review_notes.append('Missing National ID and primary phone')
    if values['primary_phone'] and not primary_phone:
        review_notes.append('Primary phone could not be normalized')
    if primary_phone and not is_valid_phone(primary_phone):
        review_notes.append('Primary phone is not a valid 254 phone number')
    if secondary_phone and not is_valid_phone(secondary_phone):
        review_notes.append('Secondary phone is not a valid 254 phone number')
    status = clean_status(values['status'])
    if review_notes and status == 'active':
        status = 'review_needed'
    notes = info_notes + review_notes

    return {
        'source': 'jawabu_farmers_csv',
        'external_id': '',
        'customer_name': customer_name,
        'national_id': national_id,
        'primary_phone': primary_phone,
        'secondary_phone': secondary_phone,
        'county': county,
        'sub_county': clean_text(values['sub_county']).upper(),
        'ward': clean_text(values['ward']).upper(),
        'village': clean_text(values['village']).upper(),
        'landmark': clean_text(values['landmark']).upper(),
        'branch': clean_text(values['branch']).upper(),
        'gps_link': clean_text(values['gps_link']),
        'latitude': clean_coordinate(values['latitude']),
        'longitude': clean_coordinate(values['longitude']),
        'hbg_contract_name': '',
        # Farmers CSV exports come from HomeBiogas' system. Installation status
        # is filled later in the workflow after HB invoices/install evidence.
        'lead_source': 'HOMEBIOGAS',
        'contract_type': clean_text(values['contract_type']),
        'installation_status': '',
        'actual_receipts_currency': clean_text(values['actual_receipts_currency']).upper(),
        'actual_receipts': clean_decimal(values['actual_receipts']),
        'hb_sales_person': clean_sales_person(values['hb_sales_person']),
        'sign_date': clean_date(values['sign_date']),
        'created_date': '',
        'comments': clean_text(values['comments']),
        'duplicate_key': duplicate_key,
        'status': status,
        'cleaning_notes': '; '.join(notes),
        'raw_data': raw_data,
    }

def master_preview_row(cleaned: dict, source_name: str, source_row_number: int) -> dict:
    return {
        'Customer Name': cleaned.get('customer_name', ''),
        'National ID': cleaned.get('national_id', ''),
        'Primary Phone': cleaned.get('primary_phone', ''),
        'Secondary Phone': cleaned.get('secondary_phone', ''),
        'County': cleaned.get('county', ''),
        'Constituency': cleaned.get('sub_county', ''),
        'Village': cleaned.get('village') or cleaned.get('landmark', ''),
        'Lead Source': cleaned.get('lead_source', ''),
        'HB Sales Person': cleaned.get('hb_sales_person', ''),
        'HBG Visit Date': cleaned.get('sign_date', ''),
        'HBG Visit Comment': '',
        'Additional Comments': cleaned.get('comments', ''),
        'Deposit Paid to HB': cleaned.get('actual_receipts', ''),
        'Installation Status': cleaned.get('installation_status', ''),
        'Order No.': '',
        'Import Status': cleaned.get('status', ''),
        'Cleaning Notes': cleaned.get('cleaning_notes', ''),
        'Source File': source_name,
        'Source Row': source_row_number,
        'Ignored HBG Contract Name': (cleaned.get('raw_data') or {}).get('HBG Contract Name', ''),
        'Raw Sign Date': cleaned.get('sign_date', ''),
        'Raw Contract Type': cleaned.get('contract_type', ''),
        'Raw Financial Partners': (cleaned.get('raw_data') or {}).get('Financial Partners', ''),
    }

def raw_value(row: dict, header_map: dict[str, str], field: str) -> str:
    header = header_map.get(field)
    return str(row.get(header, '') if header else '').strip()


def first_non_blank(row: dict, headers: list[str]) -> str:
    for header in headers:
        value = str(row.get(header, '')).strip()
        if value:
            return value
    return ''


def clean_text(value: str) -> str:
    return re.sub(r'\s+', ' ', str(value or '').strip())


def clean_name(value: str) -> str:
    return clean_text(value).upper()


def clean_national_id(value: str) -> str:
    return re.sub(r'\D', '', str(value or ''))


def extract_bracketed_id(value: str) -> str:
    match = re.search(r'\[(\d{5,12})\]', str(value or ''))
    return match.group(1) if match else ''


def remove_bracketed_id(value: str) -> str:
    return clean_text(re.sub(r'\[\d{5,12}\]', '', str(value or '')))


def clean_coordinate(value: str) -> str:
    text = clean_text(value)
    match = re.search(r'-?\d+(?:\.\d+)?', text)
    return match.group(0) if match else ''


def clean_status(value: str) -> str:
    text = clean_text(value).lower()
    if text in {'no', 'inactive', 'disabled', 'false'}:
        return 'inactive'
    if text in {'review', 'review needed', 'needs review', 'pending'}:
        return 'review_needed'
    return 'active'


def clean_lead_source(value: str) -> str:
    text = clean_text(value).upper()
    if 'JAWABU' in text:
        return 'JAWABU'
    if 'HOMEBIOGAS' in text or 'HOME BIOGAS' in text or text == 'HBG':
        return 'HOMEBIOGAS'
    return text


def clean_sales_person(value: str) -> str:
    text = re.sub(r'\[[^\]]+\]', '', str(value or ''))
    return clean_text(text).upper()


def clean_installation_status(value: str) -> str:
    text = clean_text(value).lower()
    if text == 'pending':
        return 'Pending Installation'
    if text == 'installed':
        return 'Installed'
    if text == 'scheduled':
        return 'Scheduled'
    if text == 'rejected':
        return 'Rejected'
    return clean_text(value)


def clean_decimal(value: str) -> str:
    text = re.sub(r'[^0-9.\-]', '', str(value or ''))
    if not text:
        return ''
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return clean_text(value)
    if amount == amount.to_integral():
        return str(amount.quantize(Decimal('1')))
    return str(amount.normalize())


def clean_date(value: str) -> str:
    text = clean_text(value)
    if not text:
        return ''
    for fmt in ('%d/%m/%Y', '%m/%d/%Y', '%d/%m/%y', '%m/%d/%y', '%Y-%m-%d'):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.strftime('%d-%B-%Y')
        except ValueError:
            continue
    return text


def row_fingerprint(row: dict) -> str:
    normalized = {
        str(key or '').strip(): str(value or '').strip()
        for key, value in row.items()
        if str(key or '').strip()
    }
    payload = json.dumps(normalized, sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


@transaction.atomic
def upsert_farmer(cleaned: dict) -> tuple[bool, str]:
    lookup = farmer_lookup(cleaned)
    existing = JawabuFarmerMaster.objects.filter(**lookup).order_by('-updated_at').first()
    defaults = model_fields(cleaned)
    if existing:
        for field, value in defaults.items():
            setattr(existing, field, value)
        existing.save()
        return False, existing.status
    JawabuFarmerMaster.objects.create(**defaults)
    return True, defaults['status']


def model_fields(cleaned: dict) -> dict:
    allowed = {field.name for field in JawabuFarmerMaster._meta.fields if field.name != 'id'}
    return {key: value for key, value in cleaned.items() if key in allowed}


def farmer_lookup(cleaned: dict) -> dict[str, str]:
    if cleaned.get('duplicate_key'):
        return {'duplicate_key': cleaned['duplicate_key']}
    if cleaned.get('external_id'):
        return {'source': cleaned['source'], 'external_id': cleaned['external_id']}
    return {'source': cleaned['source'], 'source_fingerprint': cleaned['source_fingerprint']}