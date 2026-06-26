"""Jawabu HomeBiogas WhatsApp export workflow."""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.utils import timezone

from core.models import GroupSheetConfiguration, JawabuVisitRecord
from core.services.parser import MessageIntent, analyze_whatsapp_export, detect_message_intent
from core.services.sheets import get_sheets_service


logger = logging.getLogger(__name__)


JAWABU_WORKFLOW_TYPE = 'jawabu_homebiogas'

JAWABU_FIELD_HEADERS = {
    'record_id': 'Record ID',
    'visit_date': 'Visit Date',
    'whatsapp_message_at': 'WhatsApp Message Time',
    'staff_sender': 'Staff / Sender',
    'customer_name': 'Customer Name',
    'national_id': 'National ID',
    'primary_phone': 'Primary Phone',
    'secondary_phone': 'Secondary Phone',
    'county': 'County',
    'sub_county': 'Sub-County / City',
    'landmark': 'Landmark / Street',
    'gps_link': 'GPS Link',
    'latitude': 'Latitude',
    'longitude': 'Longitude',
    'media_filenames': 'Media Filenames',
    'decision': 'Decision',
    'decision_note': 'Decision Note',
    'duplicate_key': 'Duplicate Key',
    'duplicate_status': 'Duplicate Status',
    'review_notes': 'Review Notes',
    'raw_message': 'Raw Message',
}

REQUIRED_FIELDS = ('national_id', 'primary_phone')

PHONE_PATTERN = re.compile(r'(?<!\d)(?:\+?254\s*)?[017]\d(?:[\s/\-]?\d){7,9}(?!\d)')
MAP_URL_PATTERN = re.compile(
    r'https?://(?:www\.)?(?:google\.com/maps|maps\.google\.com|maps\.app\.goo\.gl|goo\.gl/maps)[^\s]+',
    re.IGNORECASE,
)
MAP_COORD_PATTERN = re.compile(
    r'(?:query=|q=)(-?\d+(?:\.\d+)?)[,+ ]+(-?\d+(?:\.\d+)?)',
    re.IGNORECASE,
)
IMG_PATTERN = re.compile(r'IMG-\d{8}-WA\d+\.(?:jpg|jpeg|png)', re.IGNORECASE)
COUNTY_PATTERN = re.compile(r'\bState:\s*-?\s*([A-Za-z \-]+?)(?:\s+County)?\s*$', re.IGNORECASE)
CITY_PATTERN = re.compile(r'\bCity:\s*-?\s*(.+)$', re.IGNORECASE)
STREET_PATTERN = re.compile(r'\b(?:Street|Address):\s*-?\s*(.+)$', re.IGNORECASE)
EXPLICIT_ID_PATTERN = re.compile(r'\b(?:ID|I\.D)\s*[-:]?\s*(\d{6,8})(?!\d)', re.IGNORECASE)
NUMBER_LINE_PATTERN = re.compile(r'^\D*(\d{6,8})(?:\D+\d{4,8})?\D*$')
DECISION_PATTERN = re.compile(
    r'\b(?:case\s+)?(?P<decision>approved|rejected|deferred|undecided|not decided|'
    r'cash|polepole|brookside|opted(?:\s+for)?\s+cash|opted(?:\s+for)?\s+brookside)\b',
    re.IGNORECASE,
)


@dataclass
class JawabuParsedRecord:
    index: int
    sender: str
    received_at: datetime | None
    raw_text: str
    fields: dict[str, str]
    missing_fields: list[str]
    duplicate_key: str

    @property
    def is_complete(self) -> bool:
        return not self.missing_fields

    @property
    def message_label(self) -> str:
        date_text = ''
        if self.received_at:
            date_text = timezone.localtime(self.received_at).strftime('%d-%b-%Y %H:%M')
        media = self.fields.get('media_filenames') or '<no media filename>'
        return f"{date_text or 'no date'} | {self.sender or 'unknown sender'} | {media}"


def is_jawabu_workflow(group_config) -> bool:
    workflow = getattr(group_config, 'workflow', None) or {}
    return str(workflow.get('type') or '') == JAWABU_WORKFLOW_TYPE


def process_jawabu_batch_export(
    group_config,
    export_text: str,
    telegram_message_id: str,
    sender: str = '',
) -> dict[str, Any]:
    """Import one Jawabu WhatsApp export into audit records and the configured sheet."""
    analysis = analyze_whatsapp_export(export_text)
    entries = analysis.get('entries') or []
    parsed_records = [
        parse_jawabu_entry(entry, index)
        for index, entry in enumerate(entries)
        if looks_like_jawabu_visit(entry.get('content', ''))
    ]

    if not entries:
        return {
            'status': 'command',
            'reply_text': (
                "No WhatsApp export messages were found. Send the Jawabu .txt "
                "export with @bot /batch."
            ),
        }

    if not parsed_records:
        return {
            'status': 'jawabu_batch_processed',
            'source': 'jawabu_homebiogas',
            'export_messages': len(entries),
            'processed': 0,
            'imported': 0,
            'duplicate_review': 0,
            'rejected': 0,
            'failed': 0,
            'duplicates': [],
            'rejections': [],
            'message': 'No Jawabu visit records with phone/location data were found.',
        }

    duplicate_keys = duplicate_keys_in_batch(parsed_records)
    results = []
    duplicate_reports = []
    rejection_reports = []

    for parsed in parsed_records:
        if not parsed.is_complete:
            record = save_jawabu_record(
                group_config=group_config,
                parsed=parsed,
                telegram_message_id=telegram_message_id,
                status='rejected',
                duplicate_status='unique',
                sync_error='Missing required field(s): ' + ', '.join(parsed.missing_fields),
            )
            results.append({'status': 'rejected', 'record': record, 'parsed': parsed})
            rejection_reports.append(rejection_summary(parsed, parsed.missing_fields))
            continue

        existing = existing_duplicate_records(group_config, parsed.duplicate_key)
        is_duplicate = parsed.duplicate_key in duplicate_keys or bool(existing)
        if is_duplicate:
            group_id = duplicate_group_id(parsed.duplicate_key)
            mark_existing_duplicates(existing, group_id)
            record = save_jawabu_record(
                group_config=group_config,
                parsed=parsed,
                telegram_message_id=telegram_message_id,
                status='duplicate_review',
                duplicate_status='possible_duplicate',
                duplicate_group_id=group_id,
                sync_error='Duplicate National ID + Primary Phone needs manual review.',
            )
            results.append({'status': 'duplicate_review', 'record': record, 'parsed': parsed})
            duplicate_reports.append(duplicate_summary(parsed, existing, group_id))
            continue

        record = save_jawabu_record(
            group_config=group_config,
            parsed=parsed,
            telegram_message_id=telegram_message_id,
            status='pending',
            duplicate_status='unique',
        )
        sync_result = append_jawabu_record_to_sheet(group_config, record)
        if sync_result.get('success'):
            record.import_status = 'imported'
            record.row_number = sync_result.get('row_number')
            record.sync_error = ''
            record.save(update_fields=['import_status', 'row_number', 'sync_error'])
            results.append({'status': 'imported', 'record': record, 'parsed': parsed})
        else:
            record.import_status = 'failed'
            record.sync_error = sync_result.get('error') or 'Google Sheets append failed'
            record.save(update_fields=['import_status', 'sync_error'])
            results.append({'status': 'failed', 'record': record, 'parsed': parsed})

    return {
        'status': 'jawabu_batch_processed',
        'source': 'jawabu_homebiogas',
        'export_messages': len(entries),
        'processed': len(parsed_records),
        'imported': sum(1 for result in results if result['status'] == 'imported'),
        'duplicate_review': sum(1 for result in results if result['status'] == 'duplicate_review'),
        'rejected': sum(1 for result in results if result['status'] == 'rejected'),
        'failed': sum(1 for result in results if result['status'] == 'failed'),
        'duplicates': duplicate_reports,
        'rejections': rejection_reports,
    }


def looks_like_jawabu_visit(content: str) -> bool:
    text = str(content or '')
    has_location_or_media = bool(
        MAP_URL_PATTERN.search(text)
        or IMG_PATTERN.search(text)
        or '<Media omitted>' in text
    )
    return has_location_or_media and bool(PHONE_PATTERN.search(text))


def parse_jawabu_entry(entry: dict, index: int) -> JawabuParsedRecord:
    raw_text = str(entry.get('content') or '').strip()
    sender = str(entry.get('sender') or '').strip()
    received_at = entry.get('received_at')
    fields = extract_jawabu_fields(raw_text, sender, received_at)
    missing_fields = [
        field for field in REQUIRED_FIELDS
        if not str(fields.get(field) or '').strip()
    ]
    duplicate_key = jawabu_duplicate_key(
        fields.get('national_id', ''),
        fields.get('primary_phone', ''),
    )
    return JawabuParsedRecord(
        index=index,
        sender=sender,
        received_at=received_at,
        raw_text=raw_text,
        fields=fields,
        missing_fields=missing_fields,
        duplicate_key=duplicate_key,
    )


def extract_jawabu_fields(content: str, sender: str, received_at: datetime | None) -> dict[str, str]:
    lines = [line.strip() for line in str(content or '').splitlines() if line.strip()]
    phones = [normalise_phone(match) for match in PHONE_PATTERN.findall(content)]
    phones = [phone for index, phone in enumerate(phones) if phone and phone not in phones[:index]]
    gps_link = first_match_text(MAP_URL_PATTERN, content)
    latitude, longitude = extract_coordinates(gps_link)
    media_filenames = IMG_PATTERN.findall(content)
    county = extract_county(lines)
    decision, decision_note = extract_decision(content)

    fields = {
        'record_id': '',
        'visit_date': format_sheet_date(received_at),
        'whatsapp_message_at': format_sheet_datetime(received_at),
        'staff_sender': sender,
        'customer_name': extract_customer_name(lines),
        'national_id': extract_national_id(lines, content),
        'primary_phone': phones[0] if phones else '',
        'secondary_phone': phones[1] if len(phones) > 1 else '',
        'county': county,
        'sub_county': extract_first_labeled_value(lines, CITY_PATTERN),
        'landmark': extract_landmark(lines),
        'gps_link': gps_link,
        'latitude': latitude,
        'longitude': longitude,
        'media_filenames': "\n".join(media_filenames),
        'decision': decision,
        'decision_note': decision_note,
        'duplicate_key': '',
        'duplicate_status': 'Unique',
        'review_notes': '',
        'raw_message': content,
    }
    fields['duplicate_key'] = jawabu_duplicate_key(
        fields['national_id'],
        fields['primary_phone'],
    )
    return fields


def extract_national_id(lines: list[str], content: str) -> str:
    explicit = EXPLICIT_ID_PATTERN.search(content)
    if explicit:
        return explicit.group(1)

    phone_line_index = next(
        (index for index, line in enumerate(lines) if PHONE_PATTERN.search(line)),
        None,
    )
    search_lines = lines[:phone_line_index] if phone_line_index is not None else lines
    for line in reversed(search_lines[-5:]):
        match = NUMBER_LINE_PATTERN.match(line)
        if match:
            return match.group(1)
    return ''


def extract_customer_name(lines: list[str]) -> str:
    phone_line_index = next(
        (index for index, line in enumerate(lines) if PHONE_PATTERN.search(line)),
        None,
    )
    if phone_line_index is None:
        return ''

    for line in reversed(lines[max(0, phone_line_index - 5):phone_line_index]):
        if is_probable_name(line):
            return clean_name(line)
    return ''


def is_probable_name(line: str) -> bool:
    value = clean_name(line)
    if not value or re.search(r'\d', value):
        return False
    lowered = value.lower()
    if lowered.startswith(('country', 'state', 'city', 'street', 'location', 'altitude')):
        return False
    if lowered in {'kenya', 'download app'}:
        return False
    return 1 <= len(value.split()) <= 5


def clean_name(value: str) -> str:
    value = re.sub(r'\s+', ' ', str(value or '')).strip(' :-')
    return value.upper()


def extract_county(lines: list[str]) -> str:
    for line in lines:
        match = COUNTY_PATTERN.search(line)
        if match:
            county = match.group(1).strip(' -')
            return normalise_county(county)
    for line in lines:
        if line.lower().startswith('country: -'):
            county = line.split(':', 1)[1].strip(' -')
            if county and county.lower() != 'kenya':
                return normalise_county(county)
    return ''


def normalise_county(value: str) -> str:
    value = re.sub(r'\s+', ' ', str(value or '')).strip()
    value = re.sub(r'\s+county$', '', value, flags=re.IGNORECASE)
    return value.upper()


def extract_landmark(lines: list[str]) -> str:
    street = extract_first_labeled_value(lines, STREET_PATTERN)
    if street:
        return street.upper()
    for line in reversed(lines[-5:]):
        if is_free_text_landmark(line):
            return line.upper()
    return ''


def is_free_text_landmark(line: str) -> bool:
    lowered = str(line or '').lower()
    if PHONE_PATTERN.search(line) or NUMBER_LINE_PATTERN.match(line):
        return False
    if lowered.startswith(('country:', 'state:', 'city:', 'street:', 'latitude:', 'longitude:', 'http')):
        return False
    if DECISION_PATTERN.search(line):
        return False
    return bool(line.strip())


def extract_first_labeled_value(lines: list[str], pattern) -> str:
    for line in lines:
        match = pattern.search(line)
        if match:
            value = match.group(1).strip(' -')
            if value and value != '-':
                return value.upper()
    return ''


def extract_decision(content: str) -> tuple[str, str]:
    match = DECISION_PATTERN.search(content)
    if not match:
        return '', ''
    raw = match.group('decision').lower()
    if 'reject' in raw:
        decision = 'REJECTED'
    elif 'defer' in raw:
        decision = 'DEFERRED'
    elif 'undecided' in raw or 'not decided' in raw:
        decision = 'UNDECIDED'
    elif 'brookside' in raw:
        decision = 'BROOKSIDE'
    elif 'cash' in raw:
        decision = 'CASH'
    elif 'approve' in raw:
        decision = 'APPROVED'
    else:
        decision = raw.upper()
    note = re.sub(r'\s+', ' ', content).strip()
    return decision, note[:500]


def first_match_text(pattern, content: str) -> str:
    match = pattern.search(str(content or ''))
    return match.group(0) if match else ''


def extract_coordinates(gps_link: str) -> tuple[str, str]:
    match = MAP_COORD_PATTERN.search(str(gps_link or ''))
    if not match:
        return '', ''
    return match.group(1), match.group(2)


def normalise_phone(value: str) -> str:
    digits = re.sub(r'\D', '', str(value or ''))
    if digits.startswith('254') and len(digits) >= 12:
        return digits[:12]
    if digits.startswith('0') and len(digits) >= 10:
        return '254' + digits[1:10]
    if len(digits) >= 9 and digits[0] in {'1', '7'}:
        return '254' + digits[:9]
    return digits


def jawabu_duplicate_key(national_id: str, primary_phone: str) -> str:
    national_id = re.sub(r'\D', '', str(national_id or ''))
    primary_phone = normalise_phone(primary_phone)
    if not national_id or not primary_phone:
        return ''
    return f"{national_id}|{primary_phone}"


def duplicate_group_id(duplicate_key: str) -> str:
    digest = hashlib.sha1(str(duplicate_key or '').encode('utf-8')).hexdigest()[:12]
    return f"JAWABU-DUP-{digest.upper()}"


def duplicate_keys_in_batch(records: list[JawabuParsedRecord]) -> set[str]:
    counts: dict[str, int] = {}
    for record in records:
        if record.duplicate_key:
            counts[record.duplicate_key] = counts.get(record.duplicate_key, 0) + 1
    return {key for key, count in counts.items() if count > 1}


def existing_duplicate_records(group_config, duplicate_key: str):
    if not duplicate_key:
        return JawabuVisitRecord.objects.none()
    return JawabuVisitRecord.objects.filter(
        group_id=str(group_config.group_id),
        duplicate_key=duplicate_key,
    ).exclude(import_status='rejected')


def mark_existing_duplicates(records, group_id: str) -> None:
    records.update(
        duplicate_status='possible_duplicate',
        duplicate_group_id=group_id,
    )


def save_jawabu_record(
    group_config,
    parsed: JawabuParsedRecord,
    telegram_message_id: str,
    status: str,
    duplicate_status: str,
    duplicate_group_id: str = '',
    sync_error: str = '',
) -> JawabuVisitRecord:
    fields = dict(parsed.fields)
    fields['duplicate_status'] = duplicate_status.replace('_', ' ').title()
    return JawabuVisitRecord.objects.create(
        group_id=str(group_config.group_id),
        sheet_id=str(group_config.sheet_id or ''),
        sheet_tab=str(group_config.sheet_name or ''),
        telegram_message_id=f"{telegram_message_id}_jawabu_{parsed.index}",
        source_telegram_message_id=str(telegram_message_id or ''),
        whatsapp_message_index=parsed.index,
        whatsapp_message_at=parsed.received_at,
        sender=parsed.sender,
        national_id=fields.get('national_id', ''),
        primary_phone=fields.get('primary_phone', ''),
        duplicate_key=parsed.duplicate_key,
        duplicate_group_id=duplicate_group_id,
        duplicate_status=duplicate_status,
        import_status=status,
        parsed_fields=fields,
        raw_text=parsed.raw_text,
        sync_error=sync_error,
    )


def append_jawabu_record_to_sheet(group_config, record: JawabuVisitRecord) -> dict:
    workflow = getattr(group_config, 'workflow', None) or {}
    service = get_sheets_service(
        sheet_id=group_config.sheet_id,
        sheet_name=group_config.sheet_name,
        sheet_schema=None,
    )
    if not service.is_available():
        return {'success': False, 'error': 'Google Sheets service unavailable.'}

    values = service._sheet.get_all_values()
    headers = header_row_values(values, workflow)
    if not headers:
        return {'success': False, 'error': 'Header row is empty or unavailable.'}

    field_headers = configured_field_headers(workflow)
    missing_headers = [
        header for header in field_headers.values()
        if header and header not in headers
    ]
    if missing_headers:
        return {
            'success': False,
            'error': 'Missing required column(s): ' + ', '.join(missing_headers[:8]),
        }

    row_values = ['' for _ in headers]
    fields = dict(record.parsed_fields or {})
    fields['record_id'] = jawabu_record_id(record)
    fields['duplicate_status'] = 'Unique'
    fields['review_notes'] = ''
    for field, header in field_headers.items():
        if header in headers:
            row_values[headers.index(header)] = fields.get(field, '')

    try:
        service._sheet.append_row(row_values, value_input_option='USER_ENTERED')
        row_number = len(values) + 1
        return {'success': True, 'row_number': row_number}
    except Exception as exc:
        logger.error("Failed to append Jawabu row: %s", exc, exc_info=True)
        return {'success': False, 'error': str(exc)}


def configured_field_headers(workflow: dict) -> dict[str, str]:
    overrides = (workflow or {}).get('field_headers') or {}
    headers = dict(JAWABU_FIELD_HEADERS)
    headers.update({
        str(field): str(header)
        for field, header in overrides.items()
        if str(field).strip() and str(header).strip()
    })
    return headers


def configured_header_row(workflow: dict) -> int:
    try:
        return max(int((workflow or {}).get('header_row') or 1), 1)
    except (TypeError, ValueError):
        return 1


def header_row_values(values: list[list[str]], workflow: dict) -> list[str]:
    index = configured_header_row(workflow) - 1
    if index < 0 or index >= len(values):
        return []
    return [str(value or '').strip() for value in values[index]]


def jawabu_record_id(record: JawabuVisitRecord) -> str:
    return f"JAW-{record.created_at.strftime('%Y%m%d')}-{str(record.id)[:8].upper()}"


def format_sheet_date(value) -> str:
    if not value:
        return ''
    return timezone.localtime(value).strftime('%d-%b-%Y')


def format_sheet_datetime(value) -> str:
    if not value:
        return ''
    return timezone.localtime(value).strftime('%d-%b-%Y %H:%M')


def duplicate_summary(parsed: JawabuParsedRecord, existing, group_id: str) -> dict:
    existing_messages = []
    for record in list(existing[:5]) if hasattr(existing, '__getitem__') else list(existing)[:5]:
        when = ''
        if record.whatsapp_message_at:
            when = timezone.localtime(record.whatsapp_message_at).strftime('%d-%b-%Y %H:%M')
        media = (record.parsed_fields or {}).get('media_filenames') or '<no media filename>'
        existing_messages.append(
            f"{when or 'no date'} | {record.sender or 'unknown sender'} | {media}"
        )
    return {
        'duplicate_group_id': group_id,
        'national_id': parsed.fields.get('national_id', ''),
        'primary_phone': parsed.fields.get('primary_phone', ''),
        'message': parsed.message_label,
        'existing_messages': existing_messages,
        'existing_count': existing.count() if hasattr(existing, 'count') else len(existing),
    }


def rejection_summary(parsed: JawabuParsedRecord, missing_fields: list[str]) -> dict:
    return {
        'message': parsed.message_label,
        'missing_fields': list(missing_fields),
        'captured': {
            'national_id': parsed.fields.get('national_id', ''),
            'primary_phone': parsed.fields.get('primary_phone', ''),
            'customer_name': parsed.fields.get('customer_name', ''),
        },
    }
