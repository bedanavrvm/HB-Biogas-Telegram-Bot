"""Order approval Telegram workflow.

This module is intentionally separate from the complaint parser. It handles a
structured BRO update format, finds an existing approval row by ID NUMBER, and
updates only the configured BRO headers plus Media URLs.
"""
import io
import hashlib
import hmac
import logging
import mimetypes
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from urllib.parse import parse_qsl, urlencode
from typing import Any

import requests
from django.conf import settings
from django.core import signing
from django.utils import timezone

from core.models import MediaAttachment, OrderApprovalUpdate
from core.services.sheets import get_sheets_service

logger = logging.getLogger(__name__)


DEFAULT_SEARCH_SHEETS = ['Pending', '178', '179', '180', '181']
DEFAULT_MATCH_FIELD = 'id_number'
DEFAULT_MEDIA_FIELD = 'media_urls'
ORDER_APPROVAL_WEBAPP_FIELDS = [
    'id_number',
    'date_visited',
    'customer_name',
    'branch',
    'primary_phone',
    'secondary_phone',
    'county',
    'landmark',
    'visited_by',
    'hb_staff',
    'deposit_hb',
    'deposit_jbl',
    'comment',
    'imab_created',
    'customer_no',
    'credit_analysis',
    'final_decision',
]

ORDER_APPROVAL_FIELD_HEADERS = {
    'date_visited': 'DATE VISITED',
    'customer_name': 'CUSTOMER NAME',
    'branch': 'BRANCH',
    'primary_phone': 'CONTACTS / PRIMARY',
    'secondary_phone': 'CONTACTS / SECONDARY',
    'id_number': 'ID NUMBER',
    'county': 'COUNTY',
    'landmark': 'LOCATION AND NEAREST LANDMARK',
    'visited_by': 'VISITED BY',
    'hb_staff': 'HB STAFF',
    'deposit_hb': 'DEPOSIT / HB',
    'deposit_jbl': 'DEPOSIT / JBL',
    'comment': 'COMMENT',
    'imab_created': 'IS CUSTOMER CREATED ON IMAB?',
    'customer_no': 'CUSTOMER NO',
    'credit_analysis': 'CREDIT ANALYSIS',
    'final_decision': 'FINAL DECISION',
    'media_urls': 'Media URLs',
}

LABEL_ALIASES = {
    'id': 'id_number',
    'id number': 'id_number',
    'date visited': 'date_visited',
    'customer name': 'customer_name',
    'branch': 'branch',
    'primary phone': 'primary_phone',
    'contacts primary': 'primary_phone',
    'secondary phone': 'secondary_phone',
    'contacts secondary': 'secondary_phone',
    'county': 'county',
    'location county': 'county',
    'landmark': 'landmark',
    'location and nearest landmark': 'landmark',
    'visited by': 'visited_by',
    'hb staff': 'hb_staff',
    'hb deposit': 'deposit_hb',
    'deposit hb': 'deposit_hb',
    'jbl deposit': 'deposit_jbl',
    'deposit jbl': 'deposit_jbl',
    'comment': 'comment',
    'imab created': 'imab_created',
    'is customer created on imab': 'imab_created',
    'customer no': 'customer_no',
    'customer number': 'customer_no',
    'credit analysis': 'credit_analysis',
    'final decision': 'final_decision',
    'decision': 'final_decision',
}

DATE_FIELDS = {'date_visited'}
FOLDER_MIME_TYPE = 'application/vnd.google-apps.folder'
FORM_TOKEN_SALT = 'order-approval-form'


@dataclass
class ParsedOrderApproval:
    fields: dict[str, str]
    warnings: list[str]

    @property
    def id_number(self) -> str:
        return normalize_business_key(self.fields.get('id_number', ''))


@dataclass
class SheetMatch:
    sheet_name: str
    row_number: int
    headers: list[str]
    row: list[str]
    service: Any


@dataclass
class TelegramMediaItem:
    telegram_file_id: str
    file_type: str
    original_filename: str
    mime_type: str
    size: int | None


@dataclass
class UploadedMedia:
    links: list[str]
    stored_count: int
    skipped_count: int
    warnings: list[str]


def is_order_approval_workflow(group_config) -> bool:
    workflow = getattr(group_config, 'workflow', {}) or {}
    return workflow.get('type') == 'order_approval'


def handle_order_approval_message(
    group_config,
    message_data: dict,
    content: str,
    sender: str,
    received_at: datetime,
) -> dict:
    """Process a tagged order approval update or a media reply."""
    media_items = extract_media_items(message_data)
    telegram_message_id = str(message_data.get('message_id', ''))
    reply_to_id = str(
        message_data.get('reply_to_message', {}).get('message_id', '')
    )

    if media_items and reply_to_id and not str(content or '').strip():
        return handle_order_approval_media_reply(
            group_config=group_config,
            message_data=message_data,
            sender=sender,
            received_at=received_at,
            media_items=media_items,
        )

    command_result = handle_order_webapp_command(group_config, content or '')
    if command_result:
        return command_result
    if looks_like_non_order_command(content or ''):
        from core.services.commands import handle_bot_command

        return handle_bot_command(
            content=content,
            group_id=group_config.group_id,
            sender=sender,
            telegram_message_id=telegram_message_id,
        )

    parsed = parse_order_approval_message(content or '')
    if not parsed.id_number:
        return _order_reply(
            "Order approval update skipped. Add an ID: line and try again.",
            status='failed',
        )

    update_record = OrderApprovalUpdate.objects.create(
        group_id=group_config.group_id,
        sheet_id=group_config.sheet_id,
        id_number=parsed.id_number,
        sender=sender or '',
        telegram_message_id=telegram_message_id,
        reply_to_telegram_message_id=reply_to_id,
        raw_text=content or '',
        parsed_fields=parsed.fields,
        update_status='pending',
    )

    matches = find_order_approval_matches(group_config, parsed.id_number)
    if not matches:
        uploaded = store_media_for_order(
            group_config=group_config,
            message_data=message_data,
            sender=sender,
            received_at=received_at,
            media_items=media_items,
            business_key_value=parsed.id_number,
            order_update=update_record,
        )
        create_result = create_order_approval_row(
            group_config=group_config,
            parsed_fields=parsed.fields,
            media_links=uploaded.links,
        )
        if not create_result['success']:
            update_record.update_status = 'failed'
            update_record.sync_error = create_result['error']
            update_record.save(update_fields=['update_status', 'sync_error'])
            return _order_reply(
                (
                    f"Order approval row for ID {parsed.id_number} could not "
                    f"be created: {create_result['error']}"
                ),
                warnings=uploaded.warnings,
                status='failed',
            )

        update_record.sheet_tab = create_result['sheet_name']
        update_record.row_number = create_result['row_number']
        update_record.update_status = 'success'
        update_record.save(update_fields=[
            'sheet_tab', 'row_number', 'update_status',
        ])
        return _order_reply(
            (
                f"OK. Order approval row created.\n"
                f"ID: {parsed.id_number}\n"
                f"Sheet: {create_result['sheet_name']}, row {create_result['row_number']}\n"
                f"Fields updated: {len(create_result['fields_updated'])}\n"
                f"Files stored: {uploaded.stored_count}."
            ),
            warnings=uploaded.warnings,
            status='success',
        )

    if len(matches) > 1:
        uploaded = store_media_for_order(
            group_config=group_config,
            message_data=message_data,
            sender=sender,
            received_at=received_at,
            media_items=media_items,
            business_key_value=parsed.id_number,
            order_update=update_record,
        )
        locations = ", ".join(
            f"{match.sheet_name}!{match.row_number}" for match in matches[:10]
        )
        update_record.update_status = 'duplicate'
        update_record.sync_error = f"Duplicate ID matches: {locations}"
        update_record.save(update_fields=['update_status', 'sync_error'])
        return _order_reply(
            (
                f"Duplicate rows found for ID {parsed.id_number}: {locations}. "
                "Please resolve the duplicate in the sheet before updating. "
                f"Files stored: {uploaded.stored_count}."
            ),
            warnings=uploaded.warnings,
            status='duplicate',
        )

    match = matches[0]
    update_record.sheet_tab = match.sheet_name
    update_record.row_number = match.row_number
    update_record.save(update_fields=['sheet_tab', 'row_number'])

    uploaded = store_media_for_order(
        group_config=group_config,
        message_data=message_data,
        sender=sender,
        received_at=received_at,
        media_items=media_items,
        business_key_value=parsed.id_number,
        order_update=update_record,
    )
    sheet_result = update_order_approval_row(
        match=match,
        workflow=group_config.workflow or {},
        parsed_fields=parsed.fields,
        media_links=uploaded.links,
    )

    if not sheet_result['success']:
        update_record.update_status = 'failed'
        update_record.sync_error = sheet_result['error']
        update_record.save(update_fields=['update_status', 'sync_error'])
        return _order_reply(
            f"Order approval update for ID {parsed.id_number} was not synced: {sheet_result['error']}",
            warnings=uploaded.warnings,
            status='failed',
        )

    update_record.update_status = 'success'
    update_record.save(update_fields=['update_status'])
    customer_name = parsed.fields.get('customer_name') or value_for_header(
        match, header_for_field(group_config.workflow or {}, 'customer_name')
    )
    return _order_reply(
        format_order_success_reply(
            id_number=parsed.id_number,
            customer_name=customer_name,
            sheet_name=match.sheet_name,
            row_number=match.row_number,
            fields_updated=sheet_result['fields_updated'],
            files_stored=uploaded.stored_count,
            warnings=parsed.warnings + uploaded.warnings,
        ),
        status='success',
    )


def handle_order_approval_media_reply(
    group_config,
    message_data: dict,
    sender: str,
    received_at: datetime,
    media_items: list[TelegramMediaItem],
) -> dict:
    """Attach reply media to the original order approval update's row."""
    reply_to_id = str(
        message_data.get('reply_to_message', {}).get('message_id', '')
    )
    original_update = (
        OrderApprovalUpdate.objects
        .filter(group_id=group_config.group_id, telegram_message_id=reply_to_id)
        .exclude(id_number='')
        .order_by('-created_at')
        .first()
    )
    if not original_update:
        return _order_reply(
            "I could not link those files. Reply to the original order update message.",
            status='failed',
        )

    matches = find_order_approval_matches(group_config, original_update.id_number)
    if len(matches) != 1:
        return _order_reply(
            (
                f"I could not safely link files for ID {original_update.id_number}. "
                f"Matching rows found: {len(matches)}."
            ),
            status='failed',
        )

    followup_update = OrderApprovalUpdate.objects.create(
        group_id=group_config.group_id,
        sheet_id=group_config.sheet_id,
        sheet_tab=matches[0].sheet_name,
        row_number=matches[0].row_number,
        id_number=original_update.id_number,
        sender=sender or '',
        telegram_message_id=str(message_data.get('message_id', '')),
        reply_to_telegram_message_id=reply_to_id,
        raw_text='',
        parsed_fields={},
        update_status='pending',
    )

    uploaded = store_media_for_order(
        group_config=group_config,
        message_data=message_data,
        sender=sender,
        received_at=received_at,
        media_items=media_items,
        business_key_value=original_update.id_number,
        order_update=followup_update,
    )
    sheet_result = update_order_approval_row(
        match=matches[0],
        workflow=group_config.workflow or {},
        parsed_fields={},
        media_links=uploaded.links,
    )

    if not sheet_result['success']:
        followup_update.update_status = 'failed'
        followup_update.sync_error = sheet_result['error']
        followup_update.save(update_fields=['update_status', 'sync_error'])
        return _order_reply(
            f"Files were not linked for ID {original_update.id_number}: {sheet_result['error']}",
            warnings=uploaded.warnings,
            status='failed',
        )

    followup_update.update_status = 'success'
    followup_update.save(update_fields=['update_status'])
    return _order_reply(
        (
            f"OK. Files linked for ID {original_update.id_number}.\n"
            f"Sheet: {matches[0].sheet_name}, row {matches[0].row_number}\n"
            f"Files stored: {uploaded.stored_count}"
        ),
        warnings=uploaded.warnings,
        status='success',
    )


def handle_order_webapp_command(group_config, content: str) -> dict | None:
    normalized = str(content or '').strip().lower()
    if normalized not in {'/order', 'order', '/form', 'form'}:
        return None

    if not getattr(settings, 'ORDER_APPROVAL_WEBAPP_ENABLED', True):
        return _order_reply('Order approval form is not enabled.', status='failed')

    base_url = getattr(settings, 'APP_BASE_URL', '')
    if not base_url:
        return _order_reply(
            'Order approval form is not configured. Set APP_BASE_URL on Render.',
            status='failed',
        )

    form_url = (
        f"{base_url}/order-approval/?"
        + urlencode({
            'group_id': group_config.group_id,
            'token': create_order_approval_form_token(group_config.group_id),
        })
    )
    return {
        'status': 'command',
        'workflow': 'order_approval',
        'reply_text': 'Open the order approval form.',
        'reply_markup': {
            'inline_keyboard': [[
                {
                    'text': 'Open Order Approval Form',
                    'url': form_url,
                }
            ]]
        },
    }


def looks_like_non_order_command(content: str) -> bool:
    text = str(content or '').strip().lower()
    if not text.startswith('/'):
        return False
    command = text.split(None, 1)[0]
    return command not in {'/order', '/form'}


def process_order_approval_form_submission(
    group_config,
    fields: dict[str, str],
    uploaded_files: list,
    sender: str,
    received_at: datetime | None = None,
    include_blank_fields: bool = False,
) -> dict:
    received_at = received_at or timezone.now()
    parsed_fields = clean_form_fields(
        fields,
        include_blank_fields=include_blank_fields,
    )
    id_number = normalize_business_key(parsed_fields.get('id_number', ''))
    if not id_number:
        return {
            'success': False,
            'status': 'failed',
            'message': 'ID number is required.',
        }

    update_record = OrderApprovalUpdate.objects.create(
        group_id=group_config.group_id,
        sheet_id=group_config.sheet_id,
        id_number=id_number,
        sender=sender or '',
        raw_text='Telegram Web App submission',
        parsed_fields=parsed_fields,
        update_status='pending',
    )

    matches = find_order_approval_matches(group_config, id_number)
    if not matches:
        uploaded = store_uploaded_files_for_order(
            group_config=group_config,
            uploaded_files=uploaded_files,
            sender=sender,
            received_at=received_at,
            business_key_value=id_number,
            order_update=update_record,
        )
        create_result = create_order_approval_row(
            group_config=group_config,
            parsed_fields=parsed_fields,
            media_links=uploaded.links,
        )
        if not create_result['success']:
            update_record.update_status = 'failed'
            update_record.sync_error = create_result['error']
            update_record.save(update_fields=['update_status', 'sync_error'])
            return {
                'success': False,
                'status': 'failed',
                'message': create_result['error'],
                'files_stored': uploaded.stored_count,
                'warnings': uploaded.warnings,
            }

        update_record.sheet_tab = create_result['sheet_name']
        update_record.row_number = create_result['row_number']
        update_record.update_status = 'success'
        update_record.save(update_fields=[
            'sheet_tab', 'row_number', 'update_status',
        ])
        return {
            'success': True,
            'status': 'created',
            'message': 'Order approval row created.',
            'id_number': id_number,
            'customer_name': parsed_fields.get('customer_name', ''),
            'sheet': create_result['sheet_name'],
            'row': create_result['row_number'],
            'fields_updated': create_result['fields_updated'],
            'files_stored': uploaded.stored_count,
            'warnings': uploaded.warnings,
        }

    if len(matches) > 1:
        uploaded = store_uploaded_files_for_order(
            group_config=group_config,
            uploaded_files=uploaded_files,
            sender=sender,
            received_at=received_at,
            business_key_value=id_number,
            order_update=update_record,
        )
        locations = [
            {'sheet': match.sheet_name, 'row': match.row_number}
            for match in matches[:10]
        ]
        update_record.update_status = 'duplicate'
        update_record.sync_error = ", ".join(
            f"{item['sheet']}!{item['row']}" for item in locations
        )
        update_record.save(update_fields=['update_status', 'sync_error'])
        return {
            'success': False,
            'status': 'duplicate',
            'message': 'Duplicate rows found for this ID. Resolve them in the sheet first.',
            'matches': locations,
            'files_stored': uploaded.stored_count,
            'warnings': uploaded.warnings,
        }

    match = matches[0]
    update_record.sheet_tab = match.sheet_name
    update_record.row_number = match.row_number
    update_record.save(update_fields=['sheet_tab', 'row_number'])

    uploaded = store_uploaded_files_for_order(
        group_config=group_config,
        uploaded_files=uploaded_files,
        sender=sender,
        received_at=received_at,
        business_key_value=id_number,
        order_update=update_record,
    )
    sheet_result = update_order_approval_row(
        match=match,
        workflow=group_config.workflow or {},
        parsed_fields=parsed_fields,
        media_links=uploaded.links,
    )
    if not sheet_result['success']:
        update_record.update_status = 'failed'
        update_record.sync_error = sheet_result['error']
        update_record.save(update_fields=['update_status', 'sync_error'])
        return {
            'success': False,
            'status': 'failed',
            'message': sheet_result['error'],
            'files_stored': uploaded.stored_count,
            'warnings': uploaded.warnings,
        }

    update_record.update_status = 'success'
    update_record.save(update_fields=['update_status'])
    customer_name = parsed_fields.get('customer_name') or value_for_header(
        match, header_for_field(group_config.workflow or {}, 'customer_name')
    )
    return {
        'success': True,
        'status': 'success',
        'message': 'Order approval updated.',
        'id_number': id_number,
        'customer_name': customer_name,
        'sheet': match.sheet_name,
        'row': match.row_number,
        'fields_updated': sheet_result['fields_updated'],
        'files_stored': uploaded.stored_count,
        'warnings': uploaded.warnings,
    }


def lookup_order_approval_form_record(group_config, id_number: str) -> dict:
    id_number = normalize_business_key(id_number)
    if not id_number:
        return {
            'success': False,
            'status': 'failed',
            'message': 'ID number is required.',
        }

    matches = find_order_approval_matches(group_config, id_number)
    if not matches:
        return {
            'success': True,
            'status': 'not_found',
            'message': 'No existing order row found. Submitting will create a new row.',
            'id_number': id_number,
            'fields': {'id_number': id_number},
        }

    if len(matches) > 1:
        return {
            'success': False,
            'status': 'duplicate',
            'message': 'Duplicate rows found for this ID. Resolve them in the sheet first.',
            'id_number': id_number,
            'matches': [
                {'sheet': match.sheet_name, 'row': match.row_number}
                for match in matches[:10]
            ],
        }

    match = matches[0]
    return {
        'success': True,
        'status': 'found',
        'message': 'Existing order row loaded.',
        'id_number': id_number,
        'sheet': match.sheet_name,
        'row': match.row_number,
        'fields': fields_for_order_approval_match(
            match=match,
            workflow=group_config.workflow or {},
        ),
    }


def parse_order_approval_message(content: str) -> ParsedOrderApproval:
    """Parse strict label/value lines into canonical BRO fields."""
    fields: dict[str, str] = {}
    warnings: list[str] = []
    current_field = ''

    for line in str(content or '').splitlines():
        if not line.strip():
            continue

        match = re.match(r'^\s*([^:]{1,100})\s*:\s*(.*)$', line)
        if match:
            label = normalize_label(match.group(1))
            field = LABEL_ALIASES.get(label)
            if field:
                fields[field] = match.group(2).strip()
                current_field = field
                continue
            warnings.append(f"Ignored unknown label: {match.group(1).strip()}")
            current_field = ''
            continue

        if current_field:
            fields[current_field] = (
                f"{fields[current_field]}\n{line.strip()}".strip()
            )

    if fields.get('id_number'):
        fields['id_number'] = normalize_business_key(fields['id_number'])

    return ParsedOrderApproval(fields=fields, warnings=warnings)


def clean_form_fields(
    fields: dict[str, str],
    include_blank_fields: bool = False,
) -> dict[str, str]:
    cleaned = {}
    allowed = set(ORDER_APPROVAL_FIELD_HEADERS)
    for field, value in (fields or {}).items():
        if field not in allowed or field == DEFAULT_MEDIA_FIELD:
            continue
        value = str(value or '').strip()
        if value or field == 'id_number' or include_blank_fields:
            cleaned[field] = value
    if cleaned.get('id_number'):
        cleaned['id_number'] = normalize_business_key(cleaned['id_number'])
    return cleaned


def fields_for_order_approval_match(match: SheetMatch, workflow: dict) -> dict[str, str]:
    fields: dict[str, str] = {}
    for field in ORDER_APPROVAL_WEBAPP_FIELDS:
        value = value_for_header(match, header_for_field(workflow, field))
        if field in DATE_FIELDS:
            value = html_date_value(value)
        fields[field] = value
    return fields


def html_date_value(value: str) -> str:
    value = str(value or '').strip()
    if not value:
        return ''
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y'):
        try:
            return datetime.strptime(value, fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue
    return value


def find_order_approval_matches(group_config, id_number: str) -> list[SheetMatch]:
    workflow = group_config.workflow or {}
    match_field = workflow.get('match_field') or DEFAULT_MATCH_FIELD
    match_header = header_for_field(workflow, match_field)
    sheet_names = workflow.get('search_sheet_names') or DEFAULT_SEARCH_SHEETS
    target = normalize_business_key(id_number)
    matches: list[SheetMatch] = []

    for sheet_name in sheet_names:
        service = get_sheets_service(
            sheet_id=group_config.sheet_id,
            sheet_name=sheet_name,
            sheet_schema=None,
        )
        if not service.is_available():
            logger.warning("Google Sheets unavailable for %s", sheet_name)
            continue

        values = service._sheet.get_all_values()
        headers = header_row_values(values, workflow)
        if not headers:
            continue

        id_index = header_index(headers, match_header)
        if id_index is None:
            logger.warning("Header %r not found in %s", match_header, sheet_name)
            continue

        header_row = configured_header_row(workflow)
        for row_number, row in enumerate(
            values[header_row:],
            start=header_row + 1,
        ):
            cell = row[id_index] if id_index < len(row) else ''
            if normalize_business_key(cell) == target:
                matches.append(
                    SheetMatch(
                        sheet_name=sheet_name,
                        row_number=row_number,
                        headers=headers,
                        row=row,
                        service=service,
                    )
                )

    return matches


def update_order_approval_row(
    match: SheetMatch,
    workflow: dict,
    parsed_fields: dict[str, str],
    media_links: list[str],
) -> dict[str, Any]:
    """Update a single matched sheet row, header-driven."""
    fields_to_write = {
        field: value
        for field, value in (parsed_fields or {}).items()
        if field in field_headers(workflow) and value is not None
    }

    media_field = workflow.get('media_field') or DEFAULT_MEDIA_FIELD
    media_header = header_for_field(workflow, media_field)
    media_index = header_index(match.headers, media_header)
    if media_index is None:
        return {
            'success': False,
            'error': f"Required column {media_header!r} was not found.",
            'fields_updated': [],
        }

    if media_links:
        existing_media = match.row[media_index] if media_index < len(match.row) else ''
        fields_to_write[media_field] = append_cell_lines(existing_media, media_links)

    missing_headers = []
    for field in fields_to_write:
        header = header_for_field(workflow, field)
        if header_index(match.headers, header) is None:
            missing_headers.append(header)
    if missing_headers:
        return {
            'success': False,
            'error': "Missing required column(s): " + ", ".join(missing_headers),
            'fields_updated': [],
        }

    columns = []
    for field, value in fields_to_write.items():
        header = header_for_field(workflow, field)
        column_index = header_index(match.headers, header)
        input_option = 'USER_ENTERED' if field in DATE_FIELDS else 'RAW'
        columns.append((column_index + 1, value, input_option, field))

    if not columns:
        return {'success': True, 'error': '', 'fields_updated': []}

    try:
        for group in group_consecutive_columns(columns):
            start_col = group[0][0]
            end_col = group[-1][0]
            range_name = (
                f"{column_letter(start_col)}{match.row_number}:"
                f"{column_letter(end_col)}{match.row_number}"
            )
            values = [[value for _, value, _, _ in group]]
            match.service._update_range(
                range_name,
                values,
                value_input_option=group[0][2],
            )
    except Exception as exc:
        logger.error("Failed to update order approval row: %s", exc, exc_info=True)
        return {'success': False, 'error': str(exc), 'fields_updated': []}

    return {
        'success': True,
        'error': '',
        'fields_updated': [field for _, _, _, field in columns],
    }


def create_order_approval_row(
    group_config,
    parsed_fields: dict[str, str],
    media_links: list[str],
) -> dict[str, Any]:
    """Append a new order approval row to the configured creation tab."""
    workflow = group_config.workflow or {}
    sheet_name = workflow.get('create_sheet_name') or (
        workflow.get('search_sheet_names') or DEFAULT_SEARCH_SHEETS
    )[0]
    service = get_sheets_service(
        sheet_id=group_config.sheet_id,
        sheet_name=sheet_name,
        sheet_schema=None,
    )
    if not service.is_available():
        return {
            'success': False,
            'error': f"Google Sheets unavailable for {sheet_name}.",
            'fields_updated': [],
        }

    values = service._sheet.get_all_values()
    headers = header_row_values(values, workflow)
    if not headers:
        return {
            'success': False,
            'error': (
                f"Sheet {sheet_name} has no header row at row "
                f"{configured_header_row(workflow)}."
            ),
            'fields_updated': [],
        }

    media_field = workflow.get('media_field') or DEFAULT_MEDIA_FIELD
    media_header = header_for_field(workflow, media_field)
    if header_index(headers, media_header) is None:
        return {
            'success': False,
            'error': f"Required column {media_header!r} was not found.",
            'fields_updated': [],
        }

    fields_to_write = {
        field: value
        for field, value in (parsed_fields or {}).items()
        if field in field_headers(workflow) and value is not None
    }
    if media_links:
        fields_to_write[media_field] = "\n".join(
            link for link in media_links if str(link or '').strip()
        )

    missing_headers = []
    for field in fields_to_write:
        header = header_for_field(workflow, field)
        if header_index(headers, header) is None:
            missing_headers.append(header)
    if missing_headers:
        return {
            'success': False,
            'error': "Missing required column(s): " + ", ".join(missing_headers),
            'fields_updated': [],
        }

    row_number = next_order_approval_row_number(headers, values, workflow)
    match = SheetMatch(
        sheet_name=sheet_name,
        row_number=row_number,
        headers=headers,
        row=[],
        service=service,
    )
    result = update_order_approval_row(
        match=match,
        workflow=workflow,
        parsed_fields=fields_to_write,
        media_links=[],
    )
    result['sheet_name'] = sheet_name
    result['row_number'] = row_number
    return result


def next_order_approval_row_number(
    headers: list[str],
    values: list[list[str]],
    workflow: dict,
) -> int:
    """Return next row after real order data, ignoring blank/formula-only rows."""
    field_header_values = set(field_headers(workflow).values())
    data_indices = [
        index
        for index, header in enumerate(headers)
        if any(
            normalize_header(header) == normalize_header(field_header)
            for field_header in field_header_values
        )
    ]
    if not data_indices:
        data_indices = list(range(len(headers)))

    header_row = configured_header_row(workflow)
    last_data_row = header_row
    for row_number, row in enumerate(
        values[header_row:],
        start=header_row + 1,
    ):
        if any(
            index < len(row) and str(row[index] or '').strip()
            for index in data_indices
        ):
            last_data_row = row_number
    return last_data_row + 1


def configured_header_row(workflow: dict) -> int:
    try:
        header_row = int((workflow or {}).get('header_row') or 1)
    except (TypeError, ValueError):
        header_row = 1
    return max(header_row, 1)


def header_row_values(values: list[list[str]], workflow: dict) -> list[str]:
    header_index_zero_based = configured_header_row(workflow) - 1
    if header_index_zero_based < 0 or header_index_zero_based >= len(values):
        return []
    return values[header_index_zero_based]


def store_media_for_order(
    group_config,
    message_data: dict,
    sender: str,
    received_at: datetime,
    media_items: list[TelegramMediaItem],
    business_key_value: str,
    order_update: OrderApprovalUpdate | None = None,
) -> UploadedMedia:
    links: list[str] = []
    warnings: list[str] = []
    stored_count = 0
    skipped_count = 0

    for index, item in enumerate(media_items, start=1):
        attachment = MediaAttachment.objects.create(
            order_update=order_update,
            group_id=group_config.group_id,
            telegram_message_id=str(message_data.get('message_id', '')),
            reply_to_telegram_message_id=str(
                message_data.get('reply_to_message', {}).get('message_id', '')
            ),
            telegram_file_id=item.telegram_file_id,
            sender=sender or '',
            file_type=item.file_type,
            original_filename=item.original_filename,
            mime_type=item.mime_type,
            size=item.size,
            storage_provider=getattr(settings, 'MEDIA_STORAGE_PROVIDER', 'google_drive'),
            business_key_type='id_number',
            business_key_value=business_key_value,
        )

        max_bytes = int(getattr(settings, 'MEDIA_MAX_FILE_SIZE_MB', 20)) * 1024 * 1024
        if item.size and item.size > max_bytes:
            attachment.upload_status = 'skipped'
            attachment.upload_error = (
                f"File is larger than {settings.MEDIA_MAX_FILE_SIZE_MB} MB"
            )
            attachment.save(update_fields=['upload_status', 'upload_error'])
            skipped_count += 1
            warnings.append(
                f"Skipped {display_filename(item, index)}: over {settings.MEDIA_MAX_FILE_SIZE_MB} MB."
            )
            continue

        try:
            downloaded = download_telegram_file(item.telegram_file_id)
            if len(downloaded) > max_bytes:
                attachment.upload_status = 'skipped'
                attachment.upload_error = (
                    f"Downloaded file is larger than {settings.MEDIA_MAX_FILE_SIZE_MB} MB"
                )
                attachment.size = len(downloaded)
                attachment.save(update_fields=['upload_status', 'upload_error', 'size'])
                skipped_count += 1
                warnings.append(
                    f"Skipped {display_filename(item, index)}: over {settings.MEDIA_MAX_FILE_SIZE_MB} MB."
                )
                continue

            provider = getattr(settings, 'MEDIA_STORAGE_PROVIDER', 'google_drive')
            if provider != 'google_drive':
                raise ValueError(f"Unsupported media storage provider: {provider}")

            storage = GoogleDriveMediaStorage()
            drive_file_id, drive_url = storage.upload(
                data=downloaded,
                filename=build_storage_filename(item, business_key_value, index),
                mime_type=item.mime_type or 'application/octet-stream',
                id_number=business_key_value,
                received_at=received_at,
            )
            attachment.upload_status = 'success'
            attachment.drive_file_id = drive_file_id
            attachment.drive_url = drive_url
            attachment.size = len(downloaded)
            attachment.save(update_fields=[
                'upload_status', 'drive_file_id', 'drive_url', 'size',
            ])
            links.append(drive_url)
            stored_count += 1
        except Exception as exc:
            attachment.upload_status = 'failed'
            attachment.upload_error = str(exc)
            attachment.save(update_fields=['upload_status', 'upload_error'])
            warnings.append(f"Could not store {display_filename(item, index)}.")
            logger.error("Media upload failed: %s", exc, exc_info=True)

    return UploadedMedia(
        links=links,
        stored_count=stored_count,
        skipped_count=skipped_count,
        warnings=warnings,
    )


def store_uploaded_files_for_order(
    group_config,
    uploaded_files: list,
    sender: str,
    received_at: datetime,
    business_key_value: str,
    order_update: OrderApprovalUpdate | None = None,
) -> UploadedMedia:
    links: list[str] = []
    warnings: list[str] = []
    stored_count = 0
    skipped_count = 0

    for index, uploaded_file in enumerate(uploaded_files or [], start=1):
        original_filename = getattr(uploaded_file, 'name', '') or ''
        mime_type = getattr(uploaded_file, 'content_type', '') or ''
        size = getattr(uploaded_file, 'size', None)
        attachment = MediaAttachment.objects.create(
            order_update=order_update,
            group_id=group_config.group_id,
            sender=sender or '',
            file_type='document' if not str(mime_type).startswith('image/') else 'photo',
            original_filename=original_filename,
            mime_type=mime_type,
            size=size,
            storage_provider=getattr(settings, 'MEDIA_STORAGE_PROVIDER', 'google_drive'),
            business_key_type='id_number',
            business_key_value=business_key_value,
        )

        max_bytes = int(getattr(settings, 'MEDIA_MAX_FILE_SIZE_MB', 20)) * 1024 * 1024
        if size and size > max_bytes:
            attachment.upload_status = 'skipped'
            attachment.upload_error = (
                f"File is larger than {settings.MEDIA_MAX_FILE_SIZE_MB} MB"
            )
            attachment.save(update_fields=['upload_status', 'upload_error'])
            skipped_count += 1
            warnings.append(
                f"Skipped {original_filename or f'file {index}'}: over {settings.MEDIA_MAX_FILE_SIZE_MB} MB."
            )
            continue

        try:
            data = uploaded_file.read()
            if len(data) > max_bytes:
                attachment.upload_status = 'skipped'
                attachment.upload_error = (
                    f"File is larger than {settings.MEDIA_MAX_FILE_SIZE_MB} MB"
                )
                attachment.size = len(data)
                attachment.save(update_fields=['upload_status', 'upload_error', 'size'])
                skipped_count += 1
                warnings.append(
                    f"Skipped {original_filename or f'file {index}'}: over {settings.MEDIA_MAX_FILE_SIZE_MB} MB."
                )
                continue

            if getattr(settings, 'MEDIA_STORAGE_PROVIDER', 'google_drive') != 'google_drive':
                raise ValueError(
                    f"Unsupported media storage provider: {settings.MEDIA_STORAGE_PROVIDER}"
                )

            item = TelegramMediaItem(
                telegram_file_id='',
                file_type=attachment.file_type,
                original_filename=original_filename,
                mime_type=mime_type,
                size=len(data),
            )
            storage = GoogleDriveMediaStorage()
            drive_file_id, drive_url = storage.upload(
                data=data,
                filename=build_storage_filename(item, business_key_value, index),
                mime_type=mime_type or 'application/octet-stream',
                id_number=business_key_value,
                received_at=received_at,
            )
            attachment.upload_status = 'success'
            attachment.drive_file_id = drive_file_id
            attachment.drive_url = drive_url
            attachment.size = len(data)
            attachment.save(update_fields=[
                'upload_status', 'drive_file_id', 'drive_url', 'size',
            ])
            links.append(drive_url)
            stored_count += 1
        except Exception as exc:
            attachment.upload_status = 'failed'
            attachment.upload_error = str(exc)
            attachment.save(update_fields=['upload_status', 'upload_error'])
            warnings.append(f"Could not store {original_filename or f'file {index}'}.")
            logger.error("Uploaded media storage failed: %s", exc, exc_info=True)

    return UploadedMedia(
        links=links,
        stored_count=stored_count,
        skipped_count=skipped_count,
        warnings=warnings,
    )


class GoogleDriveMediaStorage:
    """Small Google Drive uploader for order approval media."""

    SCOPES = ['https://www.googleapis.com/auth/drive']

    def __init__(self):
        parent_folder_id = getattr(settings, 'GOOGLE_DRIVE_MEDIA_FOLDER_ID', '')
        if not parent_folder_id:
            raise ValueError('GOOGLE_DRIVE_MEDIA_FOLDER_ID is not configured')
        self.parent_folder_id = parent_folder_id
        self._service = None

    @property
    def service(self):
        if self._service is None:
            from google.oauth2.service_account import Credentials
            from googleapiclient.discovery import build

            creds = Credentials.from_service_account_file(
                getattr(settings, 'GOOGLE_SERVICE_ACCOUNT_FILE', 'credentials.json'),
                scopes=self.SCOPES,
            )
            self._service = build('drive', 'v3', credentials=creds)
        return self._service

    def upload(
        self,
        data: bytes,
        filename: str,
        mime_type: str,
        id_number: str,
        received_at: datetime,
    ) -> tuple[str, str]:
        from googleapiclient.http import MediaIoBaseUpload

        folder_id = self.ensure_folder_path(id_number, received_at)
        media = MediaIoBaseUpload(
            io.BytesIO(data),
            mimetype=mime_type,
            resumable=False,
        )
        metadata = {'name': filename, 'parents': [folder_id]}
        created = (
            self.service.files()
            .create(
                body=metadata,
                media_body=media,
                fields='id, webViewLink',
                supportsAllDrives=True,
            )
            .execute()
        )
        file_id = created['id']
        return file_id, created.get('webViewLink') or drive_file_url(file_id)

    def ensure_folder_path(self, id_number: str, received_at: datetime) -> str:
        local_time = timezone.localtime(received_at) if timezone.is_aware(received_at) else received_at
        parts = [
            str(local_time.year),
            local_time.strftime('%B'),
            f"ID_{sanitize_folder_name(id_number)}",
        ]
        parent = self.parent_folder_id
        for part in parts:
            parent = self.ensure_child_folder(parent, part)
        return parent

    def ensure_child_folder(self, parent_id: str, name: str) -> str:
        escaped_name = name.replace("\\", "\\\\").replace("'", "\\'")
        escaped_parent = parent_id.replace("\\", "\\\\").replace("'", "\\'")
        query = (
            f"name = '{escaped_name}' and "
            f"mimeType = '{FOLDER_MIME_TYPE}' and "
            f"'{escaped_parent}' in parents and trashed = false"
        )
        existing = (
            self.service.files()
            .list(
                q=query,
                spaces='drive',
                fields='files(id, name)',
                pageSize=1,
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
            )
            .execute()
            .get('files', [])
        )
        if existing:
            return existing[0]['id']

        created = (
            self.service.files()
            .create(
                body={
                    'name': name,
                    'mimeType': FOLDER_MIME_TYPE,
                    'parents': [parent_id],
                },
                fields='id',
                supportsAllDrives=True,
            )
            .execute()
        )
        return created['id']


def extract_media_items(message_data: dict) -> list[TelegramMediaItem]:
    items: list[TelegramMediaItem] = []

    photos = message_data.get('photo') or []
    if photos:
        photo = max(photos, key=lambda item: item.get('file_size') or 0)
        items.append(
            TelegramMediaItem(
                telegram_file_id=photo.get('file_id', ''),
                file_type='photo',
                original_filename='',
                mime_type='image/jpeg',
                size=photo.get('file_size'),
            )
        )

    document = message_data.get('document') or {}
    if document:
        items.append(
            TelegramMediaItem(
                telegram_file_id=document.get('file_id', ''),
                file_type='document',
                original_filename=document.get('file_name', ''),
                mime_type=document.get('mime_type', ''),
                size=document.get('file_size'),
            )
        )

    return [item for item in items if item.telegram_file_id]


def download_telegram_file(file_id: str) -> bytes:
    bot_token = getattr(settings, 'TELEGRAM_BOT_TOKEN', '')
    if not bot_token:
        raise ValueError('TELEGRAM_BOT_TOKEN is not configured')

    api_base = f"https://api.telegram.org/bot{bot_token}"
    file_response = requests.get(
        f"{api_base}/getFile",
        params={'file_id': file_id},
        timeout=settings.API_REQUEST_TIMEOUT,
    )
    file_response.raise_for_status()
    payload = file_response.json()
    if not payload.get('ok'):
        raise ValueError(payload.get('description') or 'Telegram getFile failed')

    file_path = payload.get('result', {}).get('file_path')
    if not file_path:
        raise ValueError('Telegram file path was missing')

    download_response = requests.get(
        f"https://api.telegram.org/file/bot{bot_token}/{file_path}",
        timeout=settings.API_REQUEST_TIMEOUT,
    )
    download_response.raise_for_status()
    return download_response.content


def format_order_success_reply(
    id_number: str,
    customer_name: str,
    sheet_name: str,
    row_number: int,
    fields_updated: list[str],
    files_stored: int,
    warnings: list[str],
) -> str:
    labels = [
        header_for_field({}, field)
        for field in fields_updated
        if field != DEFAULT_MEDIA_FIELD
    ]
    lines = [
        "OK. Order approval updated.",
        f"ID: {id_number}",
    ]
    if customer_name:
        lines.append(f"Customer: {customer_name}")
    lines.extend([
        f"Sheet: {sheet_name}, row {row_number}",
        f"Fields updated: {len(labels)}",
        f"Files stored: {files_stored}",
    ])
    if warnings:
        lines.append("Warnings: " + "; ".join(warnings[:3]))
    return "\n".join(lines)


def header_for_field(workflow: dict, field: str) -> str:
    return field_headers(workflow).get(field, field)


def field_headers(workflow: dict) -> dict[str, str]:
    configured = (workflow or {}).get('field_headers') or {}
    headers = dict(ORDER_APPROVAL_FIELD_HEADERS)
    headers.update(configured)
    return headers


def value_for_header(match: SheetMatch, header: str) -> str:
    index = header_index(match.headers, header)
    if index is None or index >= len(match.row):
        return ''
    return str(match.row[index] or '').strip()


def header_index(headers: list[str], header: str) -> int | None:
    target = normalize_header(header)
    for index, candidate in enumerate(headers):
        if normalize_header(candidate) == target:
            return index
    return None


def append_cell_lines(existing: str, new_lines: list[str]) -> str:
    lines = [
        line.strip()
        for line in str(existing or '').splitlines()
        if line.strip()
    ]
    for line in new_lines:
        if line and line not in lines:
            lines.append(line)
    return "\n".join(lines)


def build_storage_filename(
    item: TelegramMediaItem,
    business_key_value: str,
    sequence: int,
) -> str:
    suffix = PurePosixPath(item.original_filename or '').suffix
    if not suffix:
        suffix = mimetypes.guess_extension(item.mime_type or '') or ''
    if item.file_type == 'photo' and not suffix:
        suffix = '.jpg'
    stem = 'photo' if item.file_type == 'photo' else 'document'
    return f"{stem}_{sequence:02d}{suffix.lower()}"


def display_filename(item: TelegramMediaItem, sequence: int) -> str:
    return item.original_filename or build_storage_filename(item, '', sequence)


def sanitize_folder_name(value: str) -> str:
    safe = re.sub(r'[^A-Za-z0-9_.-]+', '_', str(value or '').strip())
    return safe.strip('_') or 'unknown'


def drive_file_url(file_id: str) -> str:
    return f"https://drive.google.com/file/d/{file_id}/view"


def normalize_label(label: str) -> str:
    cleaned = re.sub(r'[^A-Za-z0-9]+', ' ', str(label or '').lower())
    return " ".join(cleaned.split())


def normalize_header(header: str) -> str:
    return " ".join(str(header or '').strip().lower().split())


def normalize_business_key(value: str) -> str:
    return " ".join(str(value or '').strip().split())


def validate_telegram_webapp_init_data(init_data: str) -> tuple[bool, str, dict]:
    """Validate Telegram Web App initData using the bot token."""
    if not getattr(settings, 'ORDER_APPROVAL_WEBAPP_REQUIRE_TELEGRAM_AUTH', True):
        return True, '', {}

    bot_token = getattr(settings, 'TELEGRAM_BOT_TOKEN', '')
    if not bot_token:
        return False, 'TELEGRAM_BOT_TOKEN is not configured.', {}
    if not init_data:
        return False, 'Telegram Web App authentication data is missing.', {}

    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop('hash', '')
    if not received_hash:
        return False, 'Telegram Web App hash is missing.', {}

    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(pairs.items())
    )
    secret_key = hmac.new(
        b'WebAppData',
        bot_token.encode('utf-8'),
        hashlib.sha256,
    ).digest()
    calculated_hash = hmac.new(
        secret_key,
        data_check_string.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(calculated_hash, received_hash):
        return False, 'Telegram Web App authentication failed.', {}

    auth_date = pairs.get('auth_date')
    max_age = int(getattr(settings, 'ORDER_APPROVAL_WEBAPP_AUTH_MAX_AGE_SECONDS', 86400))
    if auth_date and max_age > 0:
        try:
            if time.time() - int(auth_date) > max_age:
                return False, 'Telegram Web App authentication expired.', {}
        except ValueError:
            return False, 'Telegram Web App auth_date is invalid.', {}

    return True, '', pairs


def create_order_approval_form_token(group_id: str) -> str:
    return signing.dumps(
        {'group_id': str(group_id)},
        salt=FORM_TOKEN_SALT,
    )


def validate_order_approval_form_token(
    token: str,
    group_id: str,
) -> tuple[bool, str]:
    if not token:
        return False, 'Form token is missing.'

    max_age = int(getattr(settings, 'ORDER_APPROVAL_WEBAPP_AUTH_MAX_AGE_SECONDS', 86400))
    try:
        payload = signing.loads(
            token,
            salt=FORM_TOKEN_SALT,
            max_age=max_age if max_age > 0 else None,
        )
    except signing.SignatureExpired:
        return False, 'Form token has expired. Open the form again from Telegram.'
    except signing.BadSignature:
        return False, 'Form token is invalid. Open the form again from Telegram.'

    if str(payload.get('group_id', '')) != str(group_id):
        return False, 'Form token does not match this group.'
    return True, ''


def group_consecutive_columns(columns: list[tuple]) -> list[list[tuple]]:
    if not columns:
        return []

    ordered = sorted(columns, key=lambda column: column[0])
    groups = [[ordered[0]]]
    for column in ordered[1:]:
        if column[0] == groups[-1][-1][0] + 1 and column[2] == groups[-1][-1][2]:
            groups[-1].append(column)
        else:
            groups.append([column])
    return groups


def column_letter(column_index: int) -> str:
    letters = ''
    while column_index:
        column_index, remainder = divmod(column_index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _order_reply(text: str, warnings: list[str] | None = None, status: str = 'success') -> dict:
    if warnings:
        text = f"{text}\nWarnings: " + "; ".join(warnings[:3])
    return {
        'status': 'command',
        'workflow': 'order_approval',
        'order_status': status,
        'reply_text': text,
    }
