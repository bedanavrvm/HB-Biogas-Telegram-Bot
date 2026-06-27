"""Jawabu HomeBiogas WhatsApp export workflow."""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from django.utils import timezone

from core.models import GroupSheetConfiguration, JawabuVisitRecord
from core.services.parser import MessageIntent, analyze_whatsapp_export, detect_message_intent
from core.services.sheets import get_sheets_service


logger = logging.getLogger(__name__)


JAWABU_WORKFLOW_TYPE = 'jawabu_homebiogas'
DEFAULT_IMPORT_START_DATE = '2026-05-01'

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
    'import_status': 'Import Status',
    'duplicate_key': 'Duplicate Key',
    'duplicate_status': 'Duplicate Status',
    'review_notes': 'Review Notes',
    'raw_message': 'Raw Message',
}

REQUIRED_FIELDS = ('customer_name', 'national_id_or_primary_phone')

PHONE_PATTERN = re.compile(
    r'(?<!\d)(?:\+?254[\s\-]?(?:7|1)\d{2}[\s\-]?\d{3}[\s\-]?\d{3}'
    r'|0(?:7|1)\d{2}[\s\-]?\d{3}[\s\-]?\d{3}'
    r'|(?:7|1)\d{2}[\s\-]?\d{3}[\s\-]?\d{3})(?!\d)'
)
MAP_URL_PATTERN = re.compile(
    r'https?://(?:www\.)?(?:google\.com/maps|maps\.google\.com|maps\.app\.goo\.gl|goo\.gl/maps)[^\s]+',
    re.IGNORECASE,
)
MAP_COORD_PATTERN = re.compile(
    r'(?:query=|q=)(-?\d+(?:\.\d+)?)(?:%2C|,|\+|\s)+(-?\d+(?:\.\d+)?)',
    re.IGNORECASE,
)
LABELED_LAT_PATTERN = re.compile(r'\bLatitude:\s*([NS])?\s*(-?\d+(?:\.\d+)?)', re.IGNORECASE)
LABELED_LON_PATTERN = re.compile(r'\bLongitude:\s*([EW])?\s*(-?\d+(?:\.\d+)?)', re.IGNORECASE)
IMG_PATTERN = re.compile(r'IMG-\d{8}-WA\d+\.(?:jpg|jpeg|png)', re.IGNORECASE)
COUNTY_PATTERN = re.compile(r'\bState:\s*-?\s*([A-Za-z \-]+?)\s+County\s*$', re.IGNORECASE)
EXPLICIT_COUNTY_PATTERN = re.compile(r'\bCounty:\s*-?\s*([A-Za-z \-]+?)(?:\s+County)?\s*$', re.IGNORECASE)
CITY_PATTERN = re.compile(r'\bCity:\s*-?\s*(.+)$', re.IGNORECASE)
STREET_PATTERN = re.compile(r'\b(?:Street|Address):\s*-?\s*(.+)$', re.IGNORECASE)
EXPLICIT_ID_PATTERN = re.compile(
    r'\b(?:NATIONAL\s+ID|ID\s*(?:NO\.?|NUMBER)?|I\.?D\.?)\s*[-:./]?\s*(\d{6,8})(?!\d)',
    re.IGNORECASE,
)
NUMBER_LINE_PATTERN = re.compile(r'^\D*(\d{6,8})(?:\D+\d{4,8})?\D*$')
DECISION_PATTERN = re.compile(
    r'\b(?:case\s+)?(?P<decision>approved|rejected|deferred|undecided|not decided|'
    r'cash|polepole|brookside|opted(?:\s+for)?\s+cash|opted(?:\s+for)?\s+brookside)\b',
    re.IGNORECASE,
)
LOCATION_DATE_PATTERNS = (
    re.compile(r'\bLocation read date:\s*(.+)$', re.IGNORECASE),
    re.compile(r'\bDate:\s*(.+)$', re.IGNORECASE),
)
LOCATION_DATE_FORMATS = (
    '%b %d, %Y %I:%M:%S %p',
    '%b %d, %Y %I:%M %p',
    '%B %d, %Y %I:%M:%S %p',
    '%B %d, %Y %I:%M %p',
    '%d/%m/%Y %H:%M:%S',
    '%d/%m/%Y %H:%M',
    '%d/%m/%y %H:%M:%S',
    '%d/%m/%y %H:%M',
    '%d/%m/%Y %I:%M:%S %p',
    '%d/%m/%Y %I:%M %p',
    '%d/%m/%y %I:%M:%S %p',
    '%d/%m/%y %I:%M %p',
    '%m/%d/%Y %H:%M:%S',
    '%m/%d/%Y %H:%M',
    '%m/%d/%y %H:%M:%S',
    '%m/%d/%y %H:%M',
    '%m/%d/%Y %I:%M:%S %p',
    '%m/%d/%Y %I:%M %p',
    '%m/%d/%y %I:%M:%S %p',
    '%m/%d/%y %I:%M %p',
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
    import_start_date = configured_import_start_date(group_config)
    sheet_state = sync_jawabu_state_from_sheet(group_config)
    latest_processed_at = latest_jawabu_processed_at(group_config)
    entries_after_start = [
        entry for entry in entries
        if not is_before_import_start(entry, import_start_date)
    ]
    eligible_entries = [
        entry for entry in entries_after_start
        if not is_at_or_before_latest_processed(entry, latest_processed_at)
    ]
    skipped_before_start = len(entries) - len(entries_after_start)
    skipped_already_processed = len(entries_after_start) - len(eligible_entries)
    parsed_records = [
        parse_jawabu_entry(entry, index)
        for index, entry in enumerate(eligible_entries)
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
            'skipped_before_start': skipped_before_start,
            'skipped_already_processed': skipped_already_processed,
            'latest_processed_at': format_sheet_datetime(latest_processed_at),
            'processed': 0,
            'imported': 0,
            'duplicate_review': 0,
            'rejected': 0,
            'failed': 0,
            'duplicates': [],
            'rejections': [],
            'message': 'No Jawabu visit records with phone/location data were found.',
        }

    parsed_records, consolidated_count, consolidation_conflict_keys = consolidate_jawabu_records(parsed_records)
    sheet_duplicate_keys = (sheet_state or {}).get('duplicate_keys')
    duplicate_keys = (
        duplicate_keys_in_batch([record for record in parsed_records if record.is_complete])
        | consolidation_conflict_keys
    )
    results = []
    duplicate_reports = []
    rejection_reports = []
    sheet_results = []

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
            item = {'status': 'rejected', 'record': record, 'parsed': parsed}
            results.append(item)
            sheet_results.append(item)
            rejection_reports.append(rejection_summary(parsed, parsed.missing_fields))
            continue

        existing = existing_duplicate_records(group_config, parsed.duplicate_key)
        exists_in_sheet = (
            sheet_duplicate_keys is not None
            and parsed.duplicate_key in sheet_duplicate_keys
        )
        is_duplicate = (
            parsed.duplicate_key in duplicate_keys
            or exists_in_sheet
            or bool(existing)
        )
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
                sync_error='Duplicate customer identifier needs manual review.',
            )
            item = {'status': 'duplicate_review', 'record': record, 'parsed': parsed}
            results.append(item)
            sheet_results.append(item)
            duplicate_reports.append(duplicate_summary(parsed, existing, group_id))
            continue

        record = save_jawabu_record(
            group_config=group_config,
            parsed=parsed,
            telegram_message_id=telegram_message_id,
            status='pending',
            duplicate_status='unique',
        )
        result_item = {'status': 'pending', 'record': record, 'parsed': parsed}
        results.append(result_item)
        sheet_results.append(result_item)

    if sheet_results:
        sync_result = append_jawabu_records_to_sheet(
            group_config,
            [item['record'] for item in sheet_results],
        )
        if sync_result.get('success'):
            row_numbers = sync_result.get('row_numbers') or []
            for index, item in enumerate(sheet_results):
                record = item['record']
                record.row_number = row_numbers[index] if index < len(row_numbers) else None
                update_fields = ['row_number']
                if item['status'] == 'pending':
                    record.import_status = 'imported'
                    record.sync_error = ''
                    item['status'] = 'imported'
                    update_fields.extend(['import_status', 'sync_error'])
                record.save(update_fields=update_fields)
        else:
            error = sync_result.get('error') or 'Google Sheets append failed'
            for item in sheet_results:
                record = item['record']
                record.import_status = 'failed'
                record.sync_error = error
                record.save(update_fields=['import_status', 'sync_error'])
                item['status'] = 'failed'

    return {
        'status': 'jawabu_batch_processed',
        'source': 'jawabu_homebiogas',
        'export_messages': len(entries),
        'skipped_before_start': skipped_before_start,
        'skipped_already_processed': skipped_already_processed,
        'latest_processed_at': format_sheet_datetime(latest_processed_at),
        'processed': len(parsed_records),
        'consolidated': consolidated_count,
        'imported': sum(1 for result in results if result['status'] == 'imported'),
        'duplicate_review': sum(1 for result in results if result['status'] == 'duplicate_review'),
        'rejected': sum(1 for result in results if result['status'] == 'rejected'),
        'failed': sum(1 for result in results if result['status'] == 'failed'),
        'duplicates': duplicate_reports,
        'rejections': rejection_reports,
    }



def sync_jawabu_state_from_sheet(group_config) -> dict[str, Any] | None:
    """Return sheet duplicate keys/latest time and remove stale local rows.

    The Jawabu sheet is the staff-facing database. If staff delete rows there,
    stale local duplicate records must not keep future imports marked as
    duplicates. When the sheet cannot be read, return None and keep the local DB
    as the conservative fallback.
    """
    workflow = getattr(group_config, 'workflow', None) or {}
    service = get_sheets_service(
        sheet_id=group_config.sheet_id,
        sheet_name=group_config.sheet_name,
        sheet_schema=None,
    )
    if not service.is_available():
        return None

    try:
        values = service._sheet.get_all_values()
    except Exception as exc:
        logger.warning(
            "Failed to sync Jawabu state from sheet: %s",
            exc,
            exc_info=True,
        )
        return None

    headers = header_row_values(values, workflow)
    if not headers:
        return None

    field_headers = configured_field_headers(workflow)
    duplicate_index = find_header_index(headers, field_headers.get('duplicate_key'))
    message_at_index = find_header_index(headers, field_headers.get('whatsapp_message_at'))
    if duplicate_index is None:
        return None

    header_row = configured_header_row(workflow)
    sheet_keys = set()
    latest_message_at = None
    for row in values[header_row:]:
        duplicate_key = str(row[duplicate_index] if duplicate_index < len(row) else '').strip()
        if duplicate_key:
            sheet_keys.add(duplicate_key)
        if message_at_index is not None:
            parsed_at = parse_sheet_datetime(
                row[message_at_index] if message_at_index < len(row) else ''
            )
            if parsed_at and (latest_message_at is None or parsed_at > latest_message_at):
                latest_message_at = parsed_at

    local_records = JawabuVisitRecord.objects.filter(group_id=str(group_config.group_id))
    if sheet_keys:
        local_records.exclude(duplicate_key__in=sheet_keys).delete()
    else:
        local_records.delete()
    return {
        'duplicate_keys': sheet_keys,
        'latest_message_at': latest_message_at,
    }


def configured_import_start_date(group_config) -> date | None:
    workflow = getattr(group_config, 'workflow', None) or {}
    if 'import_start_date' in workflow:
        raw_value = str(workflow.get('import_start_date') or '').strip()
        if not raw_value:
            return None
    else:
        raw_value = DEFAULT_IMPORT_START_DATE
    try:
        return datetime.strptime(raw_value, '%Y-%m-%d').date()
    except ValueError:
        logger.warning(
            "Invalid Jawabu import_start_date %r for group %s; no date filter applied",
            raw_value,
            getattr(group_config, 'group_id', ''),
        )
        return None


def is_before_import_start(entry: dict, import_start_date: date | None) -> bool:
    if not import_start_date:
        return False
    received_at = entry.get('received_at')
    if not received_at:
        return False
    return timezone.localtime(received_at).date() < import_start_date


def is_at_or_before_latest_processed(
    entry: dict,
    latest_processed_at: datetime | None,
) -> bool:
    if not latest_processed_at:
        return False
    received_at = entry.get('received_at')
    if not received_at:
        return False
    return aware_datetime(received_at) <= aware_datetime(latest_processed_at)


def latest_jawabu_processed_at(group_config) -> datetime | None:
    """Return the moving cutoff from local import history only.

    After a group DB reset there is intentionally no moving cutoff, so the next
    batch starts from the configured import_start_date. Once that batch creates
    local Jawabu records, later uploads use the latest stored WhatsApp time.
    """
    db_latest = (
        JawabuVisitRecord.objects
        .filter(group_id=str(group_config.group_id))
        .exclude(whatsapp_message_at=None)
        .order_by('-whatsapp_message_at')
        .values_list('whatsapp_message_at', flat=True)
        .first()
    )
    return aware_datetime(db_latest) if db_latest else None


def looks_like_jawabu_visit(content: str) -> bool:
    text = str(content or '')
    has_location_or_media = bool(
        MAP_URL_PATTERN.search(text)
        or IMG_PATTERN.search(text)
        or '<Media omitted>' in text
    )
    has_customer_identifier = bool(
        extract_phone_numbers(text)
        or EXPLICIT_ID_PATTERN.search(text)
        or any(is_customer_identifier_line(line.strip()) for line in text.splitlines())
    )
    return has_location_or_media and has_customer_identifier


def parse_jawabu_entry(entry: dict, index: int) -> JawabuParsedRecord:
    raw_text = str(entry.get('content') or '').strip()
    sender = str(entry.get('sender') or '').strip()
    received_at = entry.get('received_at')
    fields = extract_jawabu_fields(raw_text, sender, received_at)
    missing_fields = missing_required_jawabu_fields(fields)
    duplicate_key = jawabu_duplicate_key(
        fields.get('national_id', ''),
        fields.get('primary_phone', ''),
        fields.get('customer_name', ''),
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


CONSOLIDATE_STRICT_FIELDS = (
    'visit_date',
    'customer_name',
    'national_id',
    'primary_phone',
    'secondary_phone',
    'county',
    'sub_county',
    'landmark',
    'gps_link',
    'latitude',
    'longitude',
    'decision',
)
CONSOLIDATE_COMBINE_FIELDS = (
    'media_filenames',
    'decision_note',
    'raw_message',
)


def consolidate_jawabu_records(
    records: list[JawabuParsedRecord],
) -> tuple[list[JawabuParsedRecord], int, set[str]]:
    grouped: dict[str, list[JawabuParsedRecord]] = {}
    passthrough: list[JawabuParsedRecord] = []
    for record in records:
        key = jawabu_consolidation_key(record)
        if not key:
            passthrough.append(record)
            continue
        grouped.setdefault(key, []).append(record)

    consolidated_records: list[JawabuParsedRecord] = []
    consolidated_count = 0
    conflict_duplicate_keys: set[str] = set()
    for group in grouped.values():
        if len(group) == 1:
            consolidated_records.append(group[0])
            continue

        merged = merge_jawabu_record_group(group)
        if merged is None:
            consolidated_records.extend(group)
            conflict_duplicate_keys.update(
                record.duplicate_key for record in group if record.duplicate_key
            )
            continue

        consolidated_records.append(merged)
        consolidated_count += len(group) - 1

    return sorted(
        consolidated_records + passthrough,
        key=lambda record: record.index,
    ), consolidated_count, conflict_duplicate_keys


def jawabu_consolidation_key(record: JawabuParsedRecord) -> str:
    national_id = re.sub(r'\D', '', str(record.fields.get('national_id') or ''))
    if national_id:
        return f'ID:{national_id}'
    primary_phone = normalise_phone(record.fields.get('primary_phone', ''))
    if primary_phone:
        return f'PHONE:{primary_phone}'
    return str(record.duplicate_key or '').strip()


def merge_jawabu_record_group(records: list[JawabuParsedRecord]) -> JawabuParsedRecord | None:
    ordered = sorted(records, key=lambda record: record.index)
    merged_fields = dict(ordered[0].fields)

    for record in ordered[1:]:
        if not merge_jawabu_fields(merged_fields, record.fields):
            return None

    sender = combine_text_values(record.sender for record in ordered)
    raw_text = combine_text_values(record.raw_text for record in ordered)
    received_at = min(
        (record.received_at for record in ordered if record.received_at),
        default=None,
    )
    merged_fields['raw_message'] = raw_text
    merged_fields['staff_sender'] = sender
    merged_fields['duplicate_key'] = jawabu_duplicate_key(
        merged_fields.get('national_id', ''),
        merged_fields.get('primary_phone', ''),
        merged_fields.get('customer_name', ''),
    )
    missing_fields = missing_required_jawabu_fields(merged_fields)
    return JawabuParsedRecord(
        index=ordered[0].index,
        sender=sender,
        received_at=received_at,
        raw_text=raw_text,
        fields=merged_fields,
        missing_fields=missing_fields,
        duplicate_key=merged_fields['duplicate_key'],
    )


def merge_jawabu_fields(target: dict[str, str], source: dict[str, str]) -> bool:
    for field in CONSOLIDATE_STRICT_FIELDS:
        left = normalized_compare_value(target.get(field, ''))
        right = normalized_compare_value(source.get(field, ''))
        if left and right and left != right:
            return False
        if not left and right:
            target[field] = source.get(field, '')

    for field in CONSOLIDATE_COMBINE_FIELDS:
        target[field] = combine_text_values([target.get(field, ''), source.get(field, '')])

    for field, value in source.items():
        if field in CONSOLIDATE_STRICT_FIELDS or field in CONSOLIDATE_COMBINE_FIELDS:
            continue
        if not str(target.get(field, '') or '').strip() and str(value or '').strip():
            target[field] = value
    return True


def normalized_compare_value(value: str) -> str:
    return re.sub(r'\s+', ' ', str(value or '').strip()).upper()


def combine_text_values(values) -> str:
    seen = set()
    combined = []
    for value in values:
        parts = str(value or '').splitlines() or [value]
        for part in parts:
            item = str(part or '').strip()
            if not item:
                continue
            key = re.sub(r'\s+', ' ', item).upper()
            if key in seen:
                continue
            seen.add(key)
            combined.append(item)
    return "\n".join(combined)


def extract_jawabu_fields(content: str, sender: str, received_at: datetime | None) -> dict[str, str]:
    lines = [line.strip() for line in str(content or '').splitlines() if line.strip()]
    phones = extract_phone_numbers(content)
    gps_link = first_match_text(MAP_URL_PATTERN, content)
    latitude, longitude = extract_coordinates(gps_link, content)
    media_filenames = IMG_PATTERN.findall(content)
    county = extract_county(lines)
    decision, decision_note = extract_decision(content)
    location_taken_at = extract_location_datetime(lines, received_at)
    visit_at = location_taken_at or received_at
    message_at = received_at or location_taken_at

    fields = {
        'record_id': '',
        'visit_date': format_sheet_date(visit_at),
        'whatsapp_message_at': format_sheet_datetime(message_at),
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
        fields['customer_name'],
    )
    return fields


def missing_required_jawabu_fields(fields: dict[str, str]) -> list[str]:
    missing = []
    if not str(fields.get('customer_name') or '').strip():
        missing.append('customer_name')
    if not (
        str(fields.get('national_id') or '').strip()
        or str(fields.get('primary_phone') or '').strip()
    ):
        missing.append('national_id or primary_phone')
    return missing


def extract_national_id(lines: list[str], content: str) -> str:
    explicit = EXPLICIT_ID_PATTERN.search(content)
    if explicit:
        return explicit.group(1)

    phone_line_index = next(
        (index for index, line in enumerate(lines) if extract_phone_numbers(line)),
        None,
    )
    search_lines = lines[:phone_line_index] if phone_line_index is not None else lines
    for line in reversed(search_lines[-6:]):
        if not is_possible_id_line(line):
            continue
        match = NUMBER_LINE_PATTERN.match(line.strip())
        if match:
            return match.group(1)
    return ''


def extract_customer_name(lines: list[str]) -> str:
    identifier_line_index = next(
        (
            index for index, line in enumerate(lines)
            if is_customer_identifier_line(line)
        ),
        None,
    )
    if identifier_line_index is None:
        return ''

    for line in reversed(lines[max(0, identifier_line_index - 5):identifier_line_index]):
        if is_probable_name(line):
            return clean_name(line)
    return ''


def is_customer_identifier_line(line: str) -> bool:
    value = str(line or '').strip()
    if not value:
        return False
    if extract_phone_numbers(value) or EXPLICIT_ID_PATTERN.search(value):
        return True
    return is_possible_id_line(value)


def is_possible_id_line(line: str) -> bool:
    value = str(line or '').strip()
    lowered = value.lower()
    if not value:
        return False
    if (
        IMG_PATTERN.search(value)
        or MAP_URL_PATTERN.search(value)
        or extract_phone_numbers(value)
        or any(pattern.search(value) for pattern in LOCATION_DATE_PATTERNS)
        or lowered.startswith((
            'latitude:', 'longitude:', 'altitude:', 'country:', 'state:',
            'county:', 'city:', 'street:', 'address:', 'location:',
            'google maps:', 'waze:', 'download app:',
        ))
    ):
        return False
    return bool(NUMBER_LINE_PATTERN.match(value))


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
        match = EXPLICIT_COUNTY_PATTERN.search(line)
        if match:
            county = match.group(1).strip(' -')
            return normalise_county(county)
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
    if extract_phone_numbers(line) or is_possible_id_line(line):
        return False
    if lowered.startswith(('country:', 'state:', 'county:', 'city:', 'street:', 'latitude:', 'longitude:', 'http')):
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


def extract_coordinates(gps_link: str, content: str = '') -> tuple[str, str]:
    match = MAP_COORD_PATTERN.search(str(gps_link or ''))
    if match:
        return match.group(1), match.group(2)
    lat_match = LABELED_LAT_PATTERN.search(str(content or ''))
    lon_match = LABELED_LON_PATTERN.search(str(content or ''))
    if not lat_match or not lon_match:
        return '', ''
    latitude = signed_coordinate(lat_match.group(2), lat_match.group(1))
    longitude = signed_coordinate(lon_match.group(2), lon_match.group(1))
    return latitude, longitude


def signed_coordinate(value: str, direction: str | None) -> str:
    number = str(value or '').strip()
    if not number:
        return ''
    if str(direction or '').upper() in {'S', 'W'} and not number.startswith('-'):
        return '-' + number
    return number


def extract_phone_numbers(content: str) -> list[str]:
    phones = []
    for match in PHONE_PATTERN.finditer(str(content or '')):
        phone = normalise_phone(match.group(0))
        if is_valid_phone(phone) and phone not in phones:
            phones.append(phone)
    return phones


def normalise_phone(value: str) -> str:
    digits = re.sub(r'\D', '', str(value or ''))
    if digits.startswith('254') and len(digits) >= 12:
        return digits[:12]
    if digits.startswith('0') and len(digits) >= 10:
        return '254' + digits[1:10]
    if len(digits) >= 9 and digits[0] in {'1', '7'}:
        return '254' + digits[:9]
    return digits


def is_valid_phone(value: str) -> bool:
    return bool(re.fullmatch(r'254(?:7|1)\d{8}', str(value or '')))


def extract_location_datetime(
    lines: list[str],
    reference_at: datetime | None = None,
) -> datetime | None:
    for line in lines:
        for pattern in LOCATION_DATE_PATTERNS:
            match = pattern.search(line)
            if not match:
                continue
            parsed = parse_location_datetime(match.group(1).strip(), reference_at)
            if parsed:
                return parsed
    return None


def parse_location_datetime(
    value: str,
    reference_at: datetime | None = None,
) -> datetime | None:
    candidates = parse_location_datetime_candidates(value)
    if not candidates:
        return None
    if not reference_at:
        return candidates[0]

    reference = aware_datetime(reference_at)
    not_future = [candidate for candidate in candidates if candidate <= reference]
    if not not_future:
        return None
    return max(not_future)


def parse_location_datetime_candidates(value: str) -> list[datetime]:
    cleaned = re.sub(r'\s+', ' ', str(value or '').strip())
    cleaned = re.sub(r'(?i)\s*(?:Google Maps|Waze|Download App):.*$', '', cleaned).strip()
    candidates: list[datetime] = []
    seen = set()
    for fmt in LOCATION_DATE_FORMATS:
        try:
            parsed = datetime.strptime(cleaned, fmt)
        except ValueError:
            continue
        aware = timezone.make_aware(parsed, timezone.get_current_timezone())
        key = aware.isoformat()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(aware)
    return candidates


def aware_datetime(value: datetime) -> datetime:
    if timezone.is_naive(value):
        return timezone.make_aware(value, timezone.get_current_timezone())
    return timezone.localtime(value)


def jawabu_duplicate_key(
    national_id: str,
    primary_phone: str,
    customer_name: str = '',
) -> str:
    national_id = re.sub(r'\D', '', str(national_id or ''))
    primary_phone = normalise_phone(primary_phone)
    name_key = re.sub(r'\s+', ' ', str(customer_name or '').strip().upper())
    if national_id and primary_phone:
        return f"ID:{national_id}|PHONE:{primary_phone}"
    if national_id and name_key:
        return f"ID:{national_id}|NAME:{name_key}"
    if primary_phone and name_key:
        return f"PHONE:{primary_phone}|NAME:{name_key}"
    return ''


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
    result = append_jawabu_records_to_sheet(group_config, [record])
    if not result.get('success'):
        return result
    row_numbers = result.get('row_numbers') or []
    return {
        'success': True,
        'row_number': row_numbers[0] if row_numbers else None,
    }


def append_jawabu_records_to_sheet(group_config, records: list[JawabuVisitRecord]) -> dict:
    if not records:
        return {'success': True, 'row_numbers': []}

    workflow = getattr(group_config, 'workflow', None) or {}
    service = get_sheets_service(
        sheet_id=group_config.sheet_id,
        sheet_name=group_config.sheet_name,
        sheet_schema=None,
    )
    if not service.is_available():
        return {'success': False, 'error': 'Google Sheets service unavailable.'}

    try:
        header_row_number = configured_header_row(workflow)
        headers = [
            str(value or '').strip()
            for value in service._sheet.row_values(header_row_number)
        ]
    except Exception as exc:
        logger.error("Failed to read Jawabu header row: %s", exc, exc_info=True)
        return {'success': False, 'error': str(exc)}

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

    rows = []
    for record in records:
        row_values = ['' for _ in headers]
        fields = dict(record.parsed_fields or {})
        fields['record_id'] = jawabu_record_id(record)
        fields['import_status'] = sheet_import_status(record)
        fields['duplicate_status'] = sheet_duplicate_status(record)
        fields['review_notes'] = jawabu_review_notes(record)
        for field, header in field_headers.items():
            if header in headers:
                row_values[headers.index(header)] = fields.get(field, '')
        rows.append(row_values)

    try:
        if hasattr(service._sheet, 'append_rows'):
            response = service._sheet.append_rows(rows, value_input_option='USER_ENTERED')
        else:
            responses = [
                service._sheet.append_row(row_values, value_input_option='USER_ENTERED')
                for row_values in rows
            ]
            response = responses[0] if responses else {}
        return {
            'success': True,
            'row_numbers': row_numbers_from_append_response(response, len(rows)),
        }
    except Exception as exc:
        logger.error("Failed to append Jawabu rows: %s", exc, exc_info=True)
        return {'success': False, 'error': str(exc)}


def row_numbers_from_append_response(response: Any, count: int) -> list[int | None]:
    if count <= 0:
        return []
    updated_range = ''
    if isinstance(response, dict):
        updated_range = str((response.get('updates') or {}).get('updatedRange') or '')
    match = re.search(r'![A-Z]+(\d+)(?::|$)', updated_range)
    if not match:
        match = re.search(r'(?:^|:|\s)(?:[A-Z]+)(\d+)(?::|$)', updated_range.split('!')[-1])
    if not match:
        return [None for _ in range(count)]
    first_row = int(match.group(1))
    return [first_row + index for index in range(count)]


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


def find_header_index(headers: list[str], header: str | None) -> int | None:
    target = str(header or '').strip().lower()
    if not target:
        return None
    for index, value in enumerate(headers):
        if str(value or '').strip().lower() == target:
            return index
    return None


def header_row_values(values: list[list[str]], workflow: dict) -> list[str]:
    index = configured_header_row(workflow) - 1
    if index < 0 or index >= len(values):
        return []
    return [str(value or '').strip() for value in values[index]]


def jawabu_record_id(record: JawabuVisitRecord) -> str:
    return f"JAW-{record.created_at.strftime('%Y%m%d')}-{str(record.id)[:8].upper()}"


def sheet_import_status(record: JawabuVisitRecord) -> str:
    status = str(record.import_status or '').strip()
    if status == 'pending':
        status = 'imported'
    labels = {
        'imported': 'Imported',
        'duplicate_review': 'Duplicate Review',
        'rejected': 'Rejected',
        'failed': 'Failed',
        'pending': 'Pending',
    }
    return labels.get(status, status.replace('_', ' ').title())


def sheet_duplicate_status(record: JawabuVisitRecord) -> str:
    status = str(record.duplicate_status or 'unique').strip()
    labels = {
        'unique': 'Unique',
        'possible_duplicate': 'Possible Duplicate',
        'confirmed_duplicate': 'Confirmed Duplicate',
        'not_duplicate': 'Not Duplicate',
        'merged': 'Merged',
    }
    return labels.get(status, status.replace('_', ' ').title())


def jawabu_review_notes(record: JawabuVisitRecord) -> str:
    notes = []
    if record.duplicate_group_id:
        notes.append(f'Duplicate group: {record.duplicate_group_id}')
    if record.sync_error:
        notes.append(str(record.sync_error))
    existing = (record.parsed_fields or {}).get('review_notes')
    if existing:
        notes.append(str(existing))
    return "\n".join(note for note in notes if str(note).strip())


def parse_sheet_datetime(value) -> datetime | None:
    text = str(value or '').strip()
    if not text:
        return None
    for fmt in (
        '%d-%b-%Y %H:%M',
        '%d-%b-%Y %H:%M:%S',
        '%d/%m/%Y %H:%M',
        '%d/%m/%Y %H:%M:%S',
        '%d/%m/%y %H:%M',
        '%d/%m/%y %H:%M:%S',
        '%m/%d/%Y %H:%M',
        '%m/%d/%Y %H:%M:%S',
        '%m/%d/%y %H:%M',
        '%m/%d/%y %H:%M:%S',
        '%Y-%m-%d %H:%M:%S',
        '%Y-%m-%d %H:%M',
    ):
        try:
            parsed = datetime.strptime(text, fmt)
            return timezone.make_aware(parsed, timezone.get_current_timezone())
        except ValueError:
            continue
    return None


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
        'missing_fields': [friendly_jawabu_field_name(field) for field in missing_fields],
        'captured': {
            'national_id': parsed.fields.get('national_id', ''),
            'primary_phone': parsed.fields.get('primary_phone', ''),
            'customer_name': parsed.fields.get('customer_name', ''),
        },
    }


def friendly_jawabu_field_name(field: str) -> str:
    labels = {
        'customer_name': 'Customer Name',
        'national_id or primary_phone': 'National ID or Primary Phone',
        'national_id_or_primary_phone': 'National ID or Primary Phone',
    }
    return labels.get(str(field or ''), str(field or '').replace('_', ' ').title())
