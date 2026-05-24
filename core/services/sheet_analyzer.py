"""Analyze a live Google Sheet and propose a group schema configuration."""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.conf import settings

from core.services.sheet_schema import (
    DEFAULT_BOT_WRITABLE_FIELDS,
    DEFAULT_CASE_UPDATE_FIELDS,
    DEFAULT_DATE_FIELDS,
    DEFAULT_FIELD_HEADERS,
    DEFAULT_FORMULA_FIELDS,
    SheetSchema,
)
from core.services.sheets import get_sheets_service


FIELD_SYNONYMS = {
    'complaint_id': [
        'complaint id', 'case id', 'ticket id', 'ticket no', 'case no',
    ],
    'message_id': [
        'message_id', 'message id', 'backend id', 'bot id', 'msg id',
    ],
    'date_reported': [
        'date reported', 'reported date', 'date', 'created date',
        'created on', 'reported on',
    ],
    'customer_name': [
        'customer name', 'client name', 'client', 'name', 'customer',
    ],
    'customer_id': [
        'customer id', 'customer id / account', 'account', 'account no',
        'id no', 'id number', 'national id',
    ],
    'customer_phone': [
        'phone number', 'phone', 'tel', 'telephone', 'mobile', 'contact',
        'customer phone',
    ],
    'reported_by': [
        'jbl reported by', 'reported by', 'sender', 'staff', 'agent',
    ],
    'branch_region': [
        'branch / region', 'branch', 'region', 'area', 'location',
    ],
    'complaint_category': [
        'complaint category', 'category', 'issue type', 'problem category',
    ],
    'complaint_description': [
        'complaint description', 'nature of the problem',
        'nature of complaint', 'description', 'problem', 'issue',
    ],
    'raw_message': [
        'raw_message', 'raw message', 'original message',
    ],
    'gps_link': [
        'gps_link', 'gps link', 'location link', 'maps link',
    ],
    'image_flag': [
        'image_flag', 'image flag', 'has image', 'photo',
    ],
    'source': [
        'source', 'channel', 'origin',
    ],
    'loan_status': [
        'loan status',
    ],
    'loan_at_risk': [
        'loan at risk',
    ],
    'risk_level': [
        'risk level', 'risk',
    ],
    'status': [
        'status', 'case status', 'complaint status', 'state',
    ],
    'resolution_details': [
        'resolution details', 'resolution', 'fix notes', 'notes',
        'action taken',
    ],
    'date_resolved': [
        'date resolved', 'resolved date', 'closed date', 'date closed',
    ],
    'days_open': [
        'days open', 'age', 'case age',
    ],
}


def analyze_google_sheet(
    sheet_id: str,
    sheet_name: str = '',
    sample_size: int = 25,
) -> dict:
    """Read a live Google Sheet and return detected schema/workflow metadata."""
    worksheet_titles, worksheet_error = list_google_sheet_worksheets(sheet_id)
    service = get_sheets_service(sheet_id=sheet_id, sheet_name=sheet_name)
    if not service.is_available():
        return {
            'status': 'error',
            'error': 'Google Sheets service unavailable or sheet not accessible.',
            'worksheet_titles': worksheet_titles,
            'worksheet_error': worksheet_error,
        }

    values = service._sheet.get_all_values()
    if not values:
        return {
            'status': 'error',
            'error': 'The selected worksheet is empty.',
            'worksheet_titles': worksheet_titles,
            'worksheet_error': worksheet_error,
        }

    headers = [str(header or '').strip() for header in values[0]]
    rows = values[1:sample_size + 1]
    formula_columns = _detect_formula_columns(service, headers, sample_size)
    dropdowns = _extract_dropdown_values(service, headers)
    columns = []

    for idx, header in enumerate(headers):
        samples = _column_samples(rows, idx)
        canonical_field, confidence = _suggest_field(header, samples)
        data_type = _infer_data_type(samples, dropdowns.get(idx, []))
        role = _suggest_role(canonical_field, idx in formula_columns)
        columns.append({
            'index': idx + 1,
            'letter': _column_letter(idx + 1),
            'header': header,
            'canonical_field': canonical_field,
            'mapping_confidence': confidence,
            'data_type': data_type,
            'sample_values': samples[:5],
            'dropdown_values': dropdowns.get(idx, []),
            'formula_detected': idx in formula_columns,
            'role': role,
        })

    suggested_schema = _build_suggested_schema(headers, columns)
    workflow = _build_workflow(columns)
    warnings = _warnings(headers, columns)

    return {
        'status': 'success',
        'sheet_id': sheet_id,
        'sheet_name': sheet_name or getattr(service, '_sheet_name', ''),
        'worksheet_titles': worksheet_titles,
        'worksheet_error': worksheet_error,
        'row_count': max(len(values) - 1, 0),
        'sample_size': len(rows),
        'headers': headers,
        'columns': columns,
        'suggested_schema': suggested_schema,
        'workflow': workflow,
        'warnings': warnings,
    }


def list_google_sheet_worksheets(sheet_id: str) -> tuple[list[str], str]:
    """Return worksheet titles even when the configured tab is invalid."""
    if not sheet_id:
        return [], ''

    try:
        import gspread
        from google.oauth2.service_account import Credentials

        creds = Credentials.from_service_account_file(
            getattr(settings, 'GOOGLE_SERVICE_ACCOUNT_FILE', 'credentials.json'),
            scopes=['https://www.googleapis.com/auth/spreadsheets.readonly'],
        )
        spreadsheet = gspread.authorize(creds).open_by_key(sheet_id)
        return [worksheet.title for worksheet in spreadsheet.worksheets()], ''
    except Exception as exc:
        return [], str(exc)


def apply_analysis_to_config(config, analysis: dict) -> None:
    """Persist an accepted analysis onto a GroupSheetConfiguration instance."""
    config.sheet_schema = analysis.get('suggested_schema') or {}
    workflow = dict(config.workflow or {})
    workflow.update(analysis.get('workflow') or {})
    config.workflow = workflow

    metadata = dict(config.metadata or {})
    metadata['sheet_analysis'] = {
        'row_count': analysis.get('row_count', 0),
        'sample_size': analysis.get('sample_size', 0),
        'columns': analysis.get('columns', []),
        'warnings': analysis.get('warnings', []),
        'analyzed_at': datetime.utcnow().isoformat(timespec='seconds') + 'Z',
    }
    config.metadata = metadata
    config.save(update_fields=['sheet_schema', 'workflow', 'metadata', 'updated_at'])


def _build_suggested_schema(headers: list[str], columns: list[dict]) -> dict:
    field_headers = {}
    formula_fields = []
    bot_writable_fields = []
    case_update_fields = []
    date_fields = []

    for column in columns:
        field = column.get('canonical_field')
        if not field:
            continue

        field_headers[field] = column['header']
        if column.get('formula_detected') or field in DEFAULT_FORMULA_FIELDS:
            formula_fields.append(field)
        if field in DEFAULT_BOT_WRITABLE_FIELDS and not column.get('formula_detected'):
            bot_writable_fields.append(field)
        if field in DEFAULT_CASE_UPDATE_FIELDS and not column.get('formula_detected'):
            case_update_fields.append(field)
        if field in DEFAULT_DATE_FIELDS:
            date_fields.append(field)

    return {
        'columns': headers,
        'field_headers': field_headers,
        'formula_fields': formula_fields,
        'bot_writable_fields': bot_writable_fields,
        'case_update_fields': case_update_fields,
        'date_fields': date_fields,
    }


def _build_workflow(columns: list[dict]) -> dict:
    dropdown_values = {
        column['canonical_field']: column['dropdown_values']
        for column in columns
        if column.get('canonical_field') and column.get('dropdown_values')
    }
    return {'dropdown_values': dropdown_values} if dropdown_values else {}


def _suggest_field(header: str, samples: list[str]) -> tuple[str, str]:
    normalized = SheetSchema.normalize(header)
    if not normalized:
        return '', 'none'

    for field, default_header in DEFAULT_FIELD_HEADERS.items():
        if normalized == SheetSchema.normalize(default_header):
            return field, 'high'

    for field, aliases in FIELD_SYNONYMS.items():
        if normalized in {SheetSchema.normalize(alias) for alias in aliases}:
            return field, 'high'

    for field, aliases in FIELD_SYNONYMS.items():
        for alias in aliases:
            alias_norm = SheetSchema.normalize(alias)
            if alias_norm and (alias_norm in normalized or normalized in alias_norm):
                return field, 'medium'

    sample_guess = _suggest_field_from_samples(samples)
    if sample_guess:
        return sample_guess, 'low'
    return '', 'none'


def _suggest_field_from_samples(samples: list[str]) -> str:
    joined = " ".join(samples)
    if re.search(r'\b(?:07|01)\d{8}\b|\b254\d{9}\b', joined):
        return 'customer_phone'
    if samples and all(_looks_bool(value) for value in samples):
        return 'image_flag'
    return ''


def _infer_data_type(samples: list[str], dropdown_values: list[str]) -> str:
    if dropdown_values:
        return 'dropdown'
    if not samples:
        return 'empty'
    votes = Counter(_type_for_value(value) for value in samples)
    return votes.most_common(1)[0][0]


def _type_for_value(value: str) -> str:
    value = str(value or '').strip()
    if not value:
        return 'empty'
    if _looks_bool(value):
        return 'boolean'
    if re.fullmatch(r'\+?\d[\d\s/\-()]{7,}', value):
        return 'phone'
    if _looks_number(value):
        return 'number'
    if _looks_date(value):
        return 'date'
    if value.startswith('http://') or value.startswith('https://'):
        return 'url'
    return 'text'


def _looks_bool(value: str) -> bool:
    return str(value or '').strip().lower() in {'true', 'false', 'yes', 'no', 'y', 'n'}


def _looks_number(value: str) -> bool:
    try:
        Decimal(str(value or '').replace(',', '').strip())
        return True
    except (InvalidOperation, ValueError):
        return False


def _looks_date(value: str) -> bool:
    value = str(value or '').strip()
    if not re.search(r'\d{1,4}[-/]\d{1,2}[-/]\d{1,4}', value):
        return False
    try:
        from dateutil import parser as date_parser
        date_parser.parse(value, dayfirst=True)
        return True
    except Exception:
        return False


def _suggest_role(canonical_field: str, formula_detected: bool) -> str:
    if formula_detected or canonical_field in DEFAULT_FORMULA_FIELDS:
        return 'formula'
    if canonical_field in DEFAULT_CASE_UPDATE_FIELDS:
        return 'case_update'
    if canonical_field in DEFAULT_BOT_WRITABLE_FIELDS:
        return 'bot_writable'
    return 'unmapped'


def _column_samples(rows: list[list[str]], idx: int) -> list[str]:
    samples = []
    for row in rows:
        if idx >= len(row):
            continue
        value = str(row[idx] or '').strip()
        if value:
            samples.append(value)
    return samples


def _detect_formula_columns(service, headers: list[str], sample_size: int) -> set[int]:
    try:
        rows = service._sheet.get(
            f'1:{sample_size + 1}',
            value_render_option='FORMULA',
        )
    except Exception:
        rows = []

    formula_columns = set()
    for row in rows[1:]:
        for idx, value in enumerate(row[:len(headers)]):
            if str(value or '').strip().startswith('='):
                formula_columns.add(idx)
    return formula_columns


def _extract_dropdown_values(service, headers: list[str]) -> dict[int, list[str]]:
    api_service = getattr(service, '_sheets_api_service', None)
    if not getattr(service, '_api_initialized', False) or not api_service:
        return {}

    try:
        metadata = (
            api_service.spreadsheets()
            .get(
                spreadsheetId=service._sheet_id,
                fields='sheets(properties(title),data(rowData(values(dataValidation))))',
            )
            .execute()
        )
    except Exception:
        return {}

    dropdowns = {}
    for sheet in metadata.get('sheets', []):
        title = sheet.get('properties', {}).get('title', '')
        if service._sheet_name and title != service._sheet_name:
            continue
        for row in sheet.get('data', [{}])[0].get('rowData', []):
            for idx, cell in enumerate(row.get('values', [])[:len(headers)]):
                values = _dropdown_values_from_cell(cell)
                if values and idx not in dropdowns:
                    dropdowns[idx] = values
    return dropdowns


def _dropdown_values_from_cell(cell: dict) -> list[str]:
    validation = cell.get('dataValidation') or {}
    condition = validation.get('condition') or {}
    condition_type = condition.get('type', '')
    if condition_type not in {'ONE_OF_LIST', 'LIST'}:
        return []

    values = []
    for item in condition.get('values', []):
        value = item.get('userEnteredValue') or item.get('relativeDate')
        if value:
            values.append(str(value))
    return values


def _warnings(headers: list[str], columns: list[dict]) -> list[str]:
    warnings = []
    normalized = [SheetSchema.normalize(header) for header in headers if header]
    duplicates = sorted({header for header in normalized if normalized.count(header) > 1})
    if duplicates:
        warnings.append(
            'Duplicate headers detected: ' + ', '.join(duplicates)
        )

    mapped = {column['canonical_field'] for column in columns if column['canonical_field']}
    for required in ('message_id', 'customer_name', 'customer_phone', 'complaint_description'):
        if required not in mapped:
            warnings.append(f'No confident mapping found for {required}.')
    return warnings


def _column_letter(column_index: int) -> str:
    letters = ''
    while column_index:
        column_index, remainder = divmod(column_index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters
