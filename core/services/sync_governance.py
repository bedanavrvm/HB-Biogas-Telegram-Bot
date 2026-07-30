"""Read-only governance checks for Django-published Sheets and Drive media.

Google Sheets is an operational register, never an inbound source of truth.
The functions in this module are therefore deliberately operator-triggered
reads: they identify schema drift and publication divergence without changing
Sheets, Drive, or canonical Django workflow data.
"""
from __future__ import annotations

import hashlib
import logging
import re
from collections import Counter, defaultdict
from typing import Any

from django.db import transaction

from core.models import (
    SheetRegisterContract,
    SheetSyncAuditSnapshot,
    SheetSyncDiscrepancy,
    TatTrackerCase,
)
from core.services.sheets import get_sheets_service

logger = logging.getLogger(__name__)


def normalize_header(value: Any) -> str:
    """Compare headers without making a presentation-only change look unsafe."""
    return ' '.join(str(value or '').strip().casefold().split())


def normalize_value(value: Any, comparison: str = '') -> str:
    value = ' '.join(str(value or '').strip().casefold().split())
    if comparison == 'digits':
        return re.sub(r'\D+', '', value)
    return value


def value_hash(value: Any) -> str:
    """Persist evidence of a difference without persisting customer values."""
    return hashlib.sha256(str(value or '').encode('utf-8')).hexdigest()


def _header_fingerprint(headers: list[Any]) -> str:
    normalized = '\x1f'.join(normalize_header(value) for value in headers)
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()


def _safe_sheet_error(exc: Exception) -> str:
    # Provider exception details can contain document identifiers or transport
    # context. The server log keeps the original exception for diagnosis.
    logger.exception('Sheet register audit could not read its configured register')
    return 'The configured Sheet could not be read. Check the audit log and Sheet configuration.'


def _snapshot_result(snapshot: SheetSyncAuditSnapshot, discrepancies: list[dict[str, str]]) -> dict[str, Any]:
    return {
        'contract_id': str(snapshot.contract_id),
        'register_key': snapshot.contract.register_key,
        'group_id': snapshot.contract.group_configuration.group_id,
        'sheet_name': snapshot.contract.sheet_name,
        'status': snapshot.status,
        'rows_checked': snapshot.rows_checked,
        'missing_headers': snapshot.missing_headers,
        'duplicate_headers': snapshot.duplicate_headers,
        'reordered_headers': snapshot.reordered_headers,
        'discrepancy_count': snapshot.discrepancy_count,
        'error_code': snapshot.error_code,
        'error': snapshot.error,
        'discrepancies': discrepancies,
        'snapshot_id': str(snapshot.pk),
    }


def _persist_snapshot(
    contract: SheetRegisterContract,
    *,
    status: str,
    expected_headers: list[Any],
    actual_headers: list[Any],
    missing_headers: list[str],
    duplicate_headers: list[str],
    reordered_headers: bool,
    rows_checked: int,
    discrepancies: list[dict[str, str]],
    checked_by: str,
    error_code: str = '',
    error: str = '',
) -> SheetSyncAuditSnapshot:
    with transaction.atomic():
        snapshot = SheetSyncAuditSnapshot.objects.create(
            contract=contract,
            status=status,
            expected_header_fingerprint=_header_fingerprint(expected_headers),
            actual_header_fingerprint=_header_fingerprint(actual_headers),
            missing_headers=missing_headers,
            duplicate_headers=duplicate_headers,
            reordered_headers=reordered_headers,
            rows_checked=rows_checked,
            discrepancy_count=len(discrepancies),
            checked_by=str(checked_by or '')[:255],
            error_code=error_code,
            error=error,
        )
        SheetSyncDiscrepancy.objects.bulk_create([
            SheetSyncDiscrepancy(
                snapshot=snapshot,
                record_key=item.get('record_key', '')[:255],
                field_name=item.get('field_name', '')[:255],
                kind=item['kind'],
                expected_value_hash=item.get('expected_value_hash', '')[:64],
                actual_value_hash=item.get('actual_value_hash', '')[:64],
                detail=item.get('detail', '')[:500],
            )
            for item in discrepancies
        ])
    return snapshot


def _schema_outcome(contract: SheetRegisterContract, headers: list[Any]) -> tuple[list[str], list[str], bool]:
    expected = list(contract.expected_headers or [])
    expected_normalized = [normalize_header(value) for value in expected]
    actual_normalized = [normalize_header(value) for value in headers]
    actual_positions: dict[str, list[int]] = defaultdict(list)
    for index, value in enumerate(actual_normalized):
        if value:
            actual_positions[value].append(index)
    missing = [header for header, normalized in zip(expected, expected_normalized) if normalized not in actual_positions]
    duplicates = sorted({
        str(headers[indexes[0]] or '').strip()
        for indexes in actual_positions.values()
        if len(indexes) > 1
    })
    expected_positions = [actual_positions[value][0] for value in expected_normalized if value in actual_positions]
    reordered = expected_positions != sorted(expected_positions)
    return missing, duplicates, reordered


class SheetRegisterSchemaDriftError(ValueError):
    """Raised before publication when a registered Sheet layout has drifted."""


def assert_registered_schema_before_publish(group_configuration, sheet_name: str, headers: list[Any]) -> None:
    """Refuse writes to a contracted tab whose header contract no longer fits.

    Uncontracted legacy registers preserve current behaviour until an operator
    reviews and adds their contract. Once a contract is enabled, schema safety
    is enforced at the write boundary rather than being merely a report.
    """
    # Runtime sync receives GroupConfig, while Admin contracts hold a foreign
    # key to GroupSheetConfiguration. Match their shared immutable Telegram
    # group ID instead of passing the in-memory config to a model foreign key.
    group_id = str(getattr(group_configuration, 'group_id', '') or '').strip()
    if not group_id:
        return
    contracts = SheetRegisterContract.objects.filter(
        group_configuration__group_id=group_id,
        sheet_name=str(sheet_name or '').strip(),
        enabled=True,
    )
    for contract in contracts:
        missing, duplicates, reordered = _schema_outcome(contract, headers)
        if missing or duplicates or reordered:
            problems = []
            if missing:
                problems.append('missing required headers: ' + ', '.join(missing))
            if duplicates:
                problems.append('duplicate headers: ' + ', '.join(duplicates))
            if reordered:
                problems.append('expected headers are reordered')
            raise SheetRegisterSchemaDriftError(
                f'Register contract {contract.register_key} blocks publication because ' + '; '.join(problems) + '.'
            )


def _tat_cases_for_contract(contract: SheetRegisterContract):
    """Return only active TAT cases expected on this configured tab."""
    queryset = TatTrackerCase.objects.filter(
        group_id=str(contract.group_configuration.group_id),
        is_deleted=False,
    )
    # Case.sheet_name is the current output pointer. Older rows can be blank;
    # keep them in the audit when their configured product resolves to this tab.
    product_keys = []
    try:
        from core.services.tat_tracker import configured_products

        product_keys = [
            product.key for product in configured_products(contract.group_configuration.workflow)
            if product.sheet_name == contract.sheet_name
        ]
    except Exception:
        logger.exception('Could not resolve configured TAT products for register audit')
    if product_keys:
        return queryset.filter(product_key__in=product_keys)
    return queryset.filter(sheet_name=contract.sheet_name)


def _tat_discrepancies(
    contract: SheetRegisterContract,
    headers: list[Any],
    values: list[list[Any]],
) -> tuple[int, list[dict[str, str]]]:
    header_index = {
        normalize_header(header): index
        for index, header in enumerate(headers)
        if normalize_header(header)
    }
    key_index = header_index.get(normalize_header(contract.row_key_header))
    if key_index is None:
        return 0, []

    rows_by_key: dict[str, list[tuple[int, list[Any]]]] = defaultdict(list)
    rows_checked = 0
    for row_number, row in enumerate(values[contract.data_start_row - 1:], start=contract.data_start_row):
        padded = list(row or [])
        if not any(str(value or '').strip() for value in padded):
            continue
        rows_checked += 1
        row_key = str(padded[key_index] if key_index < len(padded) else '').strip()
        if row_key:
            rows_by_key[row_key].append((row_number, padded))

    cases = {case.case_id: case for case in _tat_cases_for_contract(contract)}
    discrepancies: list[dict[str, str]] = []
    for case_id, case in cases.items():
        rows = rows_by_key.get(case_id, [])
        if not rows:
            discrepancies.append({
                'kind': SheetSyncDiscrepancy.KIND_MISSING_ROW,
                'record_key': case_id,
                'detail': 'No matching immutable case ID was found in the configured Sheet.',
            })
            continue
        if len(rows) > 1:
            discrepancies.append({
                'kind': SheetSyncDiscrepancy.KIND_DUPLICATE_ROW_KEY,
                'record_key': case_id,
                'detail': f'{len(rows)} Sheet rows share the immutable case ID.',
            })
            continue
        row_number, row = rows[0]
        if int(case.row_number or 0) != row_number:
            discrepancies.append({
                'kind': SheetSyncDiscrepancy.KIND_ROW_POINTER,
                'record_key': case_id,
                'detail': f'Django points to row {case.row_number or "none"}; the immutable ID is at row {row_number}.',
            })
        for header, specification in (contract.field_ownership or {}).items():
            if not isinstance(specification, dict):
                continue
            if specification.get('owner') not in {
                SheetRegisterContract.OWNER_BACKEND,
                SheetRegisterContract.OWNER_IMMUTABLE,
            }:
                continue
            model_field = str(specification.get('model_field') or '').strip()
            column_index = header_index.get(normalize_header(header))
            if not model_field or column_index is None or not hasattr(case, model_field):
                continue
            expected = getattr(case, model_field)
            actual = row[column_index] if column_index < len(row) else ''
            comparison = str(specification.get('comparison') or '')
            if normalize_value(expected, comparison) != normalize_value(actual, comparison):
                discrepancies.append({
                    'kind': SheetSyncDiscrepancy.KIND_FIELD_VALUE,
                    'record_key': case_id,
                    'field_name': str(header),
                    'expected_value_hash': value_hash(expected),
                    'actual_value_hash': value_hash(actual),
                    'detail': f'Backend-owned field differs at Sheet row {row_number}; raw values are intentionally not retained.',
                })

    for row_key, rows in rows_by_key.items():
        if row_key not in cases:
            discrepancies.append({
                'kind': SheetSyncDiscrepancy.KIND_ORPHAN_ROW,
                'record_key': row_key,
                'detail': f'Sheet row {rows[0][0]} has no active canonical TAT case for this configured register.',
            })
    return rows_checked, discrepancies


def audit_sheet_register(
    contract: SheetRegisterContract,
    *,
    checked_by: str = '',
    persist: bool = True,
) -> dict[str, Any]:
    """Audit one register by read-only API calls, optionally preserving evidence."""
    expected_headers = list(contract.expected_headers or [])
    actual_headers: list[Any] = []
    missing_headers: list[str] = []
    duplicate_headers: list[str] = []
    reordered_headers = False
    rows_checked = 0
    discrepancies: list[dict[str, str]] = []
    error_code = ''
    error = ''

    try:
        service = get_sheets_service(
            sheet_id=contract.group_configuration.sheet_id,
            sheet_name=contract.sheet_name,
            sheet_schema=contract.group_configuration.sheet_schema or {},
        )
        if not service.is_available() or not getattr(service, '_sheet', None):
            raise RuntimeError('Google Sheets service unavailable')
        sheet = service._sheet
        actual_headers = list(sheet.row_values(contract.header_row) or [])
        missing_headers, duplicate_headers, reordered_headers = _schema_outcome(contract, actual_headers)
        if not (missing_headers or duplicate_headers or reordered_headers):
            if contract.subject_type == SheetRegisterContract.SUBJECT_TAT_CASE:
                values = sheet.get_all_values()
                rows_checked, discrepancies = _tat_discrepancies(contract, actual_headers, values)
    except Exception as exc:
        error_code = 'sheet_unavailable'
        error = _safe_sheet_error(exc)

    if error_code:
        status = SheetSyncAuditSnapshot.STATUS_UNAVAILABLE
    elif missing_headers or duplicate_headers or reordered_headers:
        status = SheetSyncAuditSnapshot.STATUS_SCHEMA_DRIFT
    elif discrepancies:
        status = SheetSyncAuditSnapshot.STATUS_DIVERGENCE
    else:
        status = SheetSyncAuditSnapshot.STATUS_HEALTHY

    if persist:
        snapshot = _persist_snapshot(
            contract,
            status=status,
            expected_headers=expected_headers,
            actual_headers=actual_headers,
            missing_headers=missing_headers,
            duplicate_headers=duplicate_headers,
            reordered_headers=reordered_headers,
            rows_checked=rows_checked,
            discrepancies=discrepancies,
            checked_by=checked_by,
            error_code=error_code,
            error=error,
        )
        return _snapshot_result(snapshot, discrepancies)

    return {
        'contract_id': str(contract.pk),
        'register_key': contract.register_key,
        'group_id': contract.group_configuration.group_id,
        'sheet_name': contract.sheet_name,
        'status': status,
        'rows_checked': rows_checked,
        'missing_headers': missing_headers,
        'duplicate_headers': duplicate_headers,
        'reordered_headers': reordered_headers,
        'discrepancy_count': len(discrepancies),
        'error_code': error_code,
        'error': error,
        'discrepancies': discrepancies,
        'snapshot_id': '',
    }


def audit_configured_sheet_registers(
    *,
    group_id: str = '',
    register_key: str = '',
    checked_by: str = '',
    persist: bool = True,
) -> list[dict[str, Any]]:
    """Run deliberate audits for enabled configured contracts only."""
    contracts = SheetRegisterContract.objects.select_related('group_configuration').filter(enabled=True)
    if group_id:
        contracts = contracts.filter(group_configuration__group_id=str(group_id).strip())
    if register_key:
        contracts = contracts.filter(register_key=str(register_key).strip())
    return [audit_sheet_register(contract, checked_by=checked_by, persist=persist) for contract in contracts]


def audit_drive_media_root() -> dict[str, Any]:
    """Inspect the configured Drive root sharing policy without modifying it."""
    try:
        from core.services.order_approval import GoogleDriveMediaStorage

        storage = GoogleDriveMediaStorage()
        root = storage.service.files().get(
            fileId=storage.parent_folder_id,
            fields='id,name,mimeType,trashed,permissions(id,type,role,domain,allowFileDiscovery)',
            supportsAllDrives=True,
        ).execute()
        permissions = root.get('permissions') or []
        broadly_shared = [
            permission for permission in permissions
            if permission.get('type') in {'anyone', 'domain'}
        ]
        return {
            'status': 'exposed' if broadly_shared else 'restricted',
            'root_id': storage.parent_folder_id,
            'root_name': str(root.get('name') or ''),
            'trashed': bool(root.get('trashed')),
            'broad_permission_count': len(broadly_shared),
            'permission_types': dict(Counter(str(item.get('type') or 'unknown') for item in permissions)),
            'message': (
                'Review broadly shared permissions before storing customer media.'
                if broadly_shared else 'No domain-wide or anyone-with-link root permission was returned.'
            ),
        }
    except Exception:
        logger.exception('Drive media-root audit failed')
        return {
            'status': 'unavailable',
            'root_id': '',
            'root_name': '',
            'trashed': False,
            'broad_permission_count': 0,
            'permission_types': {},
            'message': 'The configured Drive root could not be inspected. Check server logs and credentials.',
        }
