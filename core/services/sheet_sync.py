"""
Mirror Google Sheets rows into the local database.

Google Sheets is the operational source of truth for cases. This service reads
the live sheet, upserts backend case rows from it, and optionally removes local
case rows that are no longer present in the sheet.
"""
import hashlib
import logging
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.models import ParsedMessage, ProcessedMessage, RawMessage
from core.services.deduplication import generate_message_hash
from core.services.group_config import GroupRegistry
from core.services.sheets import get_sheets_service


logger = logging.getLogger(__name__)


def sync_group_from_sheet(group_id: str, delete_missing: bool = True) -> dict:
    """Sync one Telegram group's configured Google Sheet into the backend."""
    registry = GroupRegistry.get_instance()
    config = registry.get_group(str(group_id))
    if not config:
        return _result(
            status='error',
            errors=['Group is not configured for Google Sheets sync'],
        )

    return sync_sheet_to_backend(
        group_id=str(group_id),
        sheet_id=config.sheet_id,
        sheet_name=config.sheet_name,
        delete_missing=delete_missing,
    )


def sync_sheet_to_backend(
    group_id: str,
    sheet_id: str,
    sheet_name: str = None,
    delete_missing: bool = True,
) -> dict:
    """
    Mirror one Google worksheet into ParsedMessage rows for *group_id*.

    Rows are matched by the sheet's message_id column when present. Human-added
    rows without message_id get a stable generated backend ID from Complaint ID,
    or row number as a last resort.
    """
    result = _result(status='success')
    service = get_sheets_service(sheet_id=sheet_id, sheet_name=sheet_name)

    if not service.is_available():
        return _result(
            status='error',
            errors=['Google Sheets service unavailable'],
        )

    valid, error = service.validate_sheet_structure()
    if not valid:
        return _result(status='error', errors=[error])

    rows = service.fetch_rows()
    seen_message_ids = set()

    with transaction.atomic():
        for row in rows:
            values = row.get('values', {})
            message_id = _sheet_message_id(
                values=values,
                row_number=row.get('row_number'),
                sheet_id=sheet_id,
                sheet_name=sheet_name,
            )

            if message_id in seen_message_ids:
                result['skipped_count'] += 1
                result['errors'].append(
                    f"Duplicate message_id in sheet skipped: {message_id}"
                )
                continue

            seen_message_ids.add(message_id)
            created = _upsert_parsed_message(
                group_id=str(group_id),
                message_id=message_id,
                row_values=values,
            )
            if created:
                result['created_count'] += 1
            else:
                result['updated_count'] += 1

        if delete_missing:
            missing = ParsedMessage.objects.filter(group_id=str(group_id)).exclude(
                message_id__in=seen_message_ids
            )
            result['deleted_count'] = missing.count()
            missing.delete()

    result['row_count'] = len(rows)
    result['backend_count'] = ParsedMessage.objects.filter(
        group_id=str(group_id)
    ).count()
    logger.info(f"Sheet-to-backend sync complete: {result}")
    return result


def sync_all_configured_groups(delete_missing: bool = True) -> dict:
    """Sync every explicitly configured group, or the default group in legacy mode."""
    registry = GroupRegistry.get_instance()
    groups = registry.list_groups()
    if not groups:
        default_group_id = getattr(settings, 'DEFAULT_GROUP_ID', 'default')
        groups = {str(default_group_id): registry.get_group(default_group_id)}

    results = {}
    for group_id, config in groups.items():
        if not config:
            continue
        results[str(group_id)] = sync_sheet_to_backend(
            group_id=str(group_id),
            sheet_id=config.sheet_id,
            sheet_name=config.sheet_name,
            delete_missing=delete_missing,
        )

    failed = sum(1 for item in results.values() if item.get('status') != 'success')
    return {
        'status': 'partial' if failed else 'success',
        'group_count': len(results),
        'failed_count': failed,
        'results': results,
    }


def _upsert_parsed_message(group_id: str, message_id: str, row_values: dict) -> bool:
    defaults = {
        'timestamp': _parse_sheet_datetime(_value(row_values, 'Date Reported')),
        'sender': _value(row_values, 'JBL Reported By'),
        'raw_message': _raw_message(row_values),
        'item': '',
        'quantity': None,
        'price': None,
        'gps_link': _value(row_values, 'gps_link'),
        'image_flag': _parse_bool(_value(row_values, 'image_flag')),
        'source': _value(row_values, 'source') or 'google sheets',
        'customer_name': _value(row_values, 'Customer Name'),
        'customer_phone': _value(row_values, 'Phone Number'),
        'customer_id': _value(row_values, 'Customer ID / Account'),
        'branch_region': _value(row_values, 'Branch / Region'),
        'complaint_category': _value(row_values, 'Complaint Category'),
        'complaint_description': _value(row_values, 'Complaint Description'),
        'complaint_status': _value(row_values, 'Status'),
        'resolution_details': _value(row_values, 'Resolution Details'),
        'date_resolved': _parse_sheet_datetime(_value(row_values, 'Date Resolved')),
        'days_open': _parse_int(_value(row_values, 'Days Open')),
        'risk_level': _value(row_values, 'Risk Level'),
        'loan_status': _value(row_values, 'Loan Status'),
        'loan_at_risk': _value(row_values, 'Loan at Risk'),
        'group_id': group_id,
        'synced_to_sheets': True,
        'synced_at': timezone.now(),
        'last_sync_error': '',
    }

    parsed_message = ParsedMessage.objects.filter(message_id=message_id).first()
    if parsed_message:
        for field, value in defaults.items():
            setattr(parsed_message, field, value)
        parsed_message.save(update_fields=list(defaults.keys()))
        return False

    raw_message = _get_or_create_raw_message(message_id, row_values)
    processed_message = _get_or_create_processed_message(
        raw_message=raw_message,
        message_id=message_id,
    )
    ParsedMessage.objects.create(
        message_id=message_id,
        processed_message=processed_message,
        **defaults,
    )
    return True


def _get_or_create_raw_message(message_id: str, row_values: dict) -> RawMessage:
    raw_message = RawMessage.objects.filter(
        telegram_message_id=message_id
    ).order_by('created_at').first()
    if raw_message:
        return raw_message

    return RawMessage.objects.create(
        telegram_message_id=message_id,
        sender=_value(row_values, 'JBL Reported By') or 'Google Sheets',
        content=_raw_message(row_values),
        received_at=_parse_sheet_datetime(_value(row_values, 'Date Reported'))
        or timezone.now(),
        has_image=_parse_bool(_value(row_values, 'image_flag')),
    )


def _get_or_create_processed_message(
    raw_message: RawMessage,
    message_id: str,
) -> ProcessedMessage:
    message_hash = generate_message_hash(
        sender='google sheets',
        content=f'{message_id}:{raw_message.content}',
    )
    processed, _ = ProcessedMessage.objects.get_or_create(
        message_hash=message_hash,
        defaults={
            'raw_message': raw_message,
            'status': 'success',
        },
    )
    return processed


def _sheet_message_id(
    values: dict,
    row_number: int,
    sheet_id: str,
    sheet_name: str = None,
) -> str:
    message_id = _value(values, 'message_id')
    if message_id:
        return message_id[:128]

    complaint_id = _value(values, 'Complaint ID')
    stable_source = complaint_id or f'row:{row_number}'
    digest = hashlib.sha256(
        f'{sheet_id}:{sheet_name or ""}:{stable_source}'.encode('utf-8')
    ).hexdigest()[:16].upper()
    return f'SHEET_{digest}'


def _raw_message(values: dict) -> str:
    return (
        _value(values, 'raw_message')
        or _value(values, 'Complaint Description')
        or _value(values, 'Complaint ID')
        or 'Imported from Google Sheets'
    )


def _value(values: dict, header_name: str) -> str:
    key = " ".join(str(header_name or "").strip().lower().split())
    return str(values.get(key, '') or '').strip()


def _parse_sheet_datetime(value: str):
    value = str(value or '').strip()
    if not value:
        return None

    try:
        from dateutil import parser as date_parser
        parsed = date_parser.parse(value, dayfirst=True)
    except Exception:
        return None

    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _parse_bool(value: str) -> bool:
    return str(value or '').strip().lower() in {'true', 'yes', 'y', '1'}


def _parse_int(value: str):
    value = str(value or '').strip()
    if not value:
        return None
    try:
        return int(Decimal(value.replace(',', '')))
    except (InvalidOperation, ValueError):
        return None


def _result(status: str, errors: list = None) -> dict:
    return {
        'status': status,
        'row_count': 0,
        'created_count': 0,
        'updated_count': 0,
        'deleted_count': 0,
        'skipped_count': 0,
        'backend_count': 0,
        'errors': errors or [],
    }
