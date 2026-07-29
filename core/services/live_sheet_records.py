"""Safe live Google Sheet row operations for Django admin."""
import logging
from typing import Any

from core.services.sheet_schema import SheetSchema
from core.services.sheets import get_sheets_service

logger = logging.getLogger(__name__)


class LiveSheetRecordError(Exception):
    """Raised when a live sheet record operation cannot be completed safely."""


SHEET_IMPORT_DISABLED = 'SHEET_IMPORT_DISABLED'


def allowed_sheet_tabs(group_config) -> list[str]:
    """Return worksheet tabs that the configured workflow is allowed to manage."""
    workflow = group_config.workflow or {}
    workflow_type = str(workflow.get('type') or 'case')
    tabs = []
    if workflow_type == 'order_approval':
        tabs.extend(workflow.get('search_sheet_names') or [])
        tabs.append(workflow.get('create_sheet_name') or '')
    tabs.append(group_config.sheet_name or '')

    unique = []
    seen = set()
    for tab in tabs:
        value = str(tab or '').strip()
        if value and value not in seen:
            seen.add(value)
            unique.append(value)
    return unique


def load_live_sheet_table(group_config, sheet_tab: str = '') -> dict[str, Any]:
    """Read one live worksheet in its actual header and column order."""
    tab = _validated_tab(group_config, sheet_tab)
    service = _service_for_tab(group_config, tab)
    if not service.is_available():
        raise LiveSheetRecordError('Google Sheets service unavailable or sheet not accessible.')

    sheet = service._sheet
    header_row = _header_row(group_config)
    try:
        display_values = sheet.get_all_values()
        try:
            formula_values = sheet.get_all_values(value_render_option='FORMULA')
        except Exception:
            formula_values = display_values
    except Exception as exc:
        raise LiveSheetRecordError(f'Could not read the live worksheet: {exc}') from exc

    headers = _row_at(display_values, header_row)
    if not any(str(header or '').strip() for header in headers):
        raise LiveSheetRecordError(f'Header row {header_row} is empty.')

    duplicate_headers = _duplicate_headers(headers)
    if duplicate_headers:
        raise LiveSheetRecordError(
            'Duplicate headers must be fixed before editing: '
            + ', '.join(duplicate_headers)
        )

    formula_indexes = _configured_formula_indexes(group_config, headers)
    system_indexes = _system_identifier_indexes(group_config, headers)
    rows = []
    for row_number in range(header_row + 1, len(display_values) + 1):
        values = _pad_row(_row_at(display_values, row_number), len(headers))
        formulas = _pad_row(_row_at(formula_values, row_number), len(headers))
        if not any(str(value or '').strip() for value in values):
            continue
        row_formula_indexes = set(formula_indexes)
        row_formula_indexes.update(
            index
            for index, value in enumerate(formulas)
            if str(value or '').startswith('=')
        )
        protected_indexes = row_formula_indexes | system_indexes
        cells = [
            {
                'index': index,
                'header': str(header or ''),
                'value': str(values[index] or ''),
                'is_readonly': index in protected_indexes,
                'readonly_reason': (
                    'Formula cell'
                    if index in row_formula_indexes
                    else 'System tracking identifier'
                    if index in system_indexes
                    else ''
                ),
            }
            for index, header in enumerate(headers)
        ]
        rows.append({
            'row_number': row_number,
            'values': values,
            'cells': cells,
            'formula_indexes': sorted(row_formula_indexes),
            'protected_indexes': sorted(protected_indexes),
            'record_key': _record_key(group_config, headers, values),
        })

    return {
        'sheet_tab': tab,
        'header_row': header_row,
        'headers': headers,
        'rows': rows,
        'row_count': len(rows),
        'formula_indexes': sorted(formula_indexes),
        'workflow_type': str((group_config.workflow or {}).get('type') or 'case'),
    }


def update_live_sheet_row(
    group_config,
    sheet_tab: str,
    row_number: int,
    submitted_values: dict[int, str],
) -> dict[str, Any]:
    """Reject Sheet-originated edits; Django is the source of truth."""
    raise LiveSheetRecordError(
        f'{SHEET_IMPORT_DISABLED}: Sheets are view-only; update the record in Django.'
    )


def delete_live_sheet_row(group_config, sheet_tab: str, row_number: int) -> dict[str, Any]:
    """Reject Sheet-originated deletions; Django owns lifecycle state."""
    raise LiveSheetRecordError(
        f'{SHEET_IMPORT_DISABLED}: Sheets are view-only; archive or correct the record in Django.'
    )


def _service_for_tab(group_config, tab: str):
    return get_sheets_service(
        sheet_id=group_config.sheet_id,
        sheet_name=tab,
        sheet_schema=group_config.sheet_schema or {},
    )


def _validated_tab(group_config, requested_tab: str) -> str:
    tabs = allowed_sheet_tabs(group_config)
    tab = str(requested_tab or '').strip() or (tabs[0] if tabs else '')
    if not tab:
        raise LiveSheetRecordError('No worksheet tab is configured for this group.')
    if tab not in tabs:
        raise LiveSheetRecordError('The requested worksheet tab is not configured for this group.')
    return tab


def _header_row(group_config) -> int:
    workflow = group_config.workflow or {}
    schema_header_row = SheetSchema.from_config(
        group_config.sheet_schema or {}
    ).header_row
    value = workflow.get('header_row') or schema_header_row
    try:
        return max(int(value), 1)
    except (TypeError, ValueError):
        return schema_header_row


def _configured_formula_indexes(group_config, headers: list[str]) -> set[int]:
    if str((group_config.workflow or {}).get('type') or 'case') == 'order_approval':
        return set()
    schema = SheetSchema.from_config(group_config.sheet_schema or {})
    formula_headers = {schema.normalize(value) for value in schema.formula_headers}
    return {
        index
        for index, header in enumerate(headers)
        if schema.normalize(header) in formula_headers
    }


def _system_identifier_indexes(group_config, headers: list[str]) -> set[int]:
    workflow = group_config.workflow or {}
    workflow_type = str(workflow.get('type') or 'case')
    if workflow_type == 'order_approval':
        configured = workflow.get('field_headers') or {}
        identifier_headers = {
            str(configured.get('order_record_id') or 'ORDER RECORD ID'),
        }
    else:
        schema = SheetSchema.from_config(group_config.sheet_schema or {})
        identifier_headers = {schema.header('message_id')}
    normalized = {_normalize_header(value) for value in identifier_headers}
    return {
        index
        for index, header in enumerate(headers)
        if _normalize_header(header) in normalized
    }


def _record_key(group_config, headers: list[str], values: list[str]) -> str:
    workflow_type = str((group_config.workflow or {}).get('type') or 'case')
    candidates = (
        ['ORDER RECORD ID', 'ID NUMBER']
        if workflow_type == 'order_approval'
        else ['message_id', 'Complaint ID']
    )
    normalized = {_normalize_header(header): index for index, header in enumerate(headers)}
    for candidate in candidates:
        index = normalized.get(_normalize_header(candidate))
        if index is not None and index < len(values):
            value = str(values[index] or '').strip()
            if value:
                return value
    return ''


def _table_row(table: dict[str, Any], row_number: int) -> dict[str, Any]:
    try:
        row_number = int(row_number)
    except (TypeError, ValueError) as exc:
        raise LiveSheetRecordError('Invalid worksheet row number.') from exc
    for row in table['rows']:
        if row['row_number'] == row_number:
            return row
    raise LiveSheetRecordError('The worksheet row no longer exists. Refresh and try again.')


def _row_at(values: list[list[str]], row_number: int) -> list[str]:
    index = row_number - 1
    return list(values[index]) if 0 <= index < len(values) else []


def _pad_row(row: list[str], size: int) -> list[str]:
    return list(row[:size]) + [''] * max(size - len(row), 0)


def _duplicate_headers(headers: list[str]) -> list[str]:
    normalized = [_normalize_header(header) for header in headers]
    return sorted({
        str(header).strip()
        for header, key in zip(headers, normalized)
        if key and normalized.count(key) > 1
    })


def _normalize_header(value: str) -> str:
    return ' '.join(str(value or '').strip().lower().split())


def _column_letter(index: int) -> str:
    letters = ''
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters
