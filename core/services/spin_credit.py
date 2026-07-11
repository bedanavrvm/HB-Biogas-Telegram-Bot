"""SPIN / CRB / credit-analysis WhatsApp export workflow."""
from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import time
from urllib.parse import parse_qsl, urlencode
from typing import Any

from django.conf import settings
from django.core import signing
from django.db import IntegrityError
from django.utils import timezone

from core.models import GroupSheetConfiguration, SpinCreditRequest
from core.services.parser import analyze_whatsapp_export
from core.services.sheets import get_sheets_service

logger = logging.getLogger(__name__)

SPIN_WORKFLOW_TYPE = 'spin_credit_analysis'
SPIN_FORM_TOKEN_SALT = 'spin-crb-form'
SPIN_FORM_REQUEST_TYPES = {'spin', 'crb'}
SPIN_UPLOAD_FIELDS = [
    ('id_photos', 'id_photo'),
    ('supporting_docs', 'laf_doc'),
    ('other_files', 'other_file'),
]

DEFAULT_FIELD_HEADERS = {
    'request_id': 'Request ID',
    'request_datetime': 'Request Date/Time',
    'branch': 'Branch',
    'requested_by': 'Requested By',
    'request_type': 'Request Type',
    'customer_name': 'Customer Name',
    'national_id': 'National ID',
    'raw_id_text': 'Raw ID Text',
    'primary_phone': 'Primary Phone',
    'secondary_phone': 'Secondary Phone',
    'customer_type': 'Customer Type',
    'loan_product': 'Loan Product',
    'requested_amount': 'Requested Amount',
    'tenor': 'Tenor',
    'business_notes': 'Business / Employment Notes',
    'code': 'Code',
    'attachment_names': 'Attachments',
    'media_urls': 'Media URLs',
    'raw_message': 'Raw Message',
    'source_chat': 'Source Chat',
    'source_filename': 'Source Filename',
    'source_message_hash': 'Source Message Hash',
    'parse_status': 'Parse Status',
    'missing_fields': 'Missing Fields',
    'analysis_status': 'Analysis Status',
    'analyst_response': 'Analyst Response',
}

REQUEST_TYPE_LABELS = {
    'spin': 'SPIN',
    'crb': 'CRB Report',
}

REQUIRED_FIELDS = {
    'spin': ['customer_name', 'national_id', 'primary_phone', 'requested_amount', 'tenor'],
    'crb': ['customer_name', 'national_id', 'primary_phone', 'requested_amount', 'tenor'],
}

STOP_WORDS = {
    'a', 'an', 'the', 'new', 'existing', 'customer', 'client', 'running', 'operating',
    'does', 'has', 'is', 'at', 'in', 'requesting', 'for', 'loan', 'of', 'ksh', 'kshs',
    'kes', 'to', 'pay', 'repay', 'with', 'period', 'under', 'virtual', 'branch',
}

PRODUCT_ALIASES = [
    ('kilimo biashara', 'Kilimo Biashara'),
    ('asset finance', 'Asset Finance'),
    ('boda boda plus', 'Boda Boda Plus'),
    ('boda boda', 'Boda Boda'),
    ('log book', 'Logbook'),
    ('logbook', 'Logbook'),
    ('maendeleo', 'Maendeleo'),
    ('mjengo', 'Mjengo'),
    ('daranja', 'Daraja'),
    ('daraja', 'Daraja'),
    ('msingi', 'Msingi'),
    ('digital', 'Digital'),
    ('fedha chap chap', 'Fedha Chap Chap'),
    ('partnership', 'Partnership'),
    ('flex', 'Flex'),
    ('biashara', 'Biashara'),
]


@dataclass
class ParsedSpinRequest:
    request_type: str
    request_datetime: Any = None
    requested_by: str = ''
    customer_name: str = ''
    national_id: str = ''
    raw_id_text: str = ''
    primary_phone: str = ''
    secondary_phone: str = ''
    customer_type: str = ''
    loan_product: str = ''
    requested_amount: Decimal | None = None
    tenor: str = ''
    business_notes: str = ''
    code: str = ''
    attachment_names: list[str] = field(default_factory=list)
    raw_message: str = ''
    source_chat: str = ''
    source_filename: str = ''
    source_message_index: int | None = None
    source_message_hash: str = ''
    parsed_fields: dict[str, Any] = field(default_factory=dict)
    missing_fields: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return not self.missing_fields


def is_spin_workflow(group_config) -> bool:
    workflow = getattr(group_config, 'workflow', None) or {}
    return str(workflow.get('type') or '') == SPIN_WORKFLOW_TYPE


def process_spin_batch_export(
    group_config,
    export_text: str,
    telegram_message_id: str,
    sender: str = '',
    source_filename: str = '',
) -> dict[str, Any]:
    analysis = analyze_whatsapp_export(export_text)
    entries = analysis.get('entries') or []
    if not entries:
        return {
            'status': 'command',
            'reply_text': (
                'No WhatsApp export messages were found. Send the SPIN/CRB chat .txt or .zip export with @bot /batch.'
            ),
        }

    parsed = []
    skipped = 0
    for index, entry in enumerate(entries):
        item = parse_spin_entry(entry, index=index, source_filename=source_filename)
        if item is None:
            skipped += 1
            continue
        parsed.append(item)

    if not parsed:
        return {
            'status': 'spin_batch_processed',
            'source': SPIN_WORKFLOW_TYPE,
            'export_messages': len(entries),
            'processed': 0,
            'imported': 0,
            'review_needed': 0,
            'duplicates': 0,
            'rejected': 0,
            'failed': 0,
            'skipped': skipped,
            'message': 'No SPIN, CRB, or credit-analysis request messages were found in the export.',
        }

    results = []
    records_for_sheet = []
    for item in parsed:
        item.missing_fields = missing_fields_for(item)
        status = 'review_needed' if item.missing_fields else 'imported'
        duplicate = SpinCreditRequest.objects.filter(
            group_id=group_config.group_id,
            source_message_hash=item.source_message_hash,
        ).first()
        if duplicate:
            results.append({'status': 'duplicate', 'parsed': item, 'record': duplicate})
            continue
        try:
            record = save_spin_request(
                group_config=group_config,
                parsed=item,
                telegram_message_id=telegram_message_id,
                import_status=status,
            )
        except IntegrityError:
            duplicate = SpinCreditRequest.objects.filter(
                group_id=group_config.group_id,
                source_message_hash=item.source_message_hash,
            ).first()
            results.append({'status': 'duplicate', 'parsed': item, 'record': duplicate})
            continue
        results.append({'status': status, 'parsed': item, 'record': record})
        records_for_sheet.append(record)

    sync_result = None
    if records_for_sheet:
        sync_result = append_spin_requests_to_sheet(group_config, records_for_sheet)
        if sync_result.get('success'):
            row_numbers = sync_result.get('row_numbers') or []
            for index, record in enumerate(records_for_sheet):
                record.row_number = row_numbers[index] if index < len(row_numbers) else None
                record.sheet_id = group_config.sheet_id or ''
                record.sheet_name = group_config.sheet_name or ''
                record.sync_error = ''
                record.save(update_fields=['row_number', 'sheet_id', 'sheet_name', 'sync_error', 'updated_at'])
        else:
            error = sync_result.get('error') or 'Google Sheets append failed'
            for record in records_for_sheet:
                record.import_status = 'failed'
                record.sync_error = error
                record.save(update_fields=['import_status', 'sync_error', 'updated_at'])
            for result in results:
                if result.get('record') in records_for_sheet:
                    result['status'] = 'failed'

    return {
        'status': 'spin_batch_processed',
        'source': SPIN_WORKFLOW_TYPE,
        'export_messages': len(entries),
        'processed': len(parsed),
        'imported': sum(1 for r in results if r['status'] == 'imported'),
        'review_needed': sum(1 for r in results if r['status'] == 'review_needed'),
        'duplicates': sum(1 for r in results if r['status'] == 'duplicate'),
        'rejected': sum(1 for r in results if r['status'] == 'rejected'),
        'failed': sum(1 for r in results if r['status'] == 'failed'),
        'skipped': skipped,
        'sheet_sync': sync_result,
        'review_items': [review_summary(r['parsed']) for r in results if r['status'] == 'review_needed'][:8],
        'duplicates_list': [request_summary(r.get('record'), r.get('parsed')) for r in results if r['status'] == 'duplicate'][:8],
    }


def parse_spin_entry(entry: dict[str, Any], index: int = 0, source_filename: str = '') -> ParsedSpinRequest | None:
    raw = str(entry.get('content') or '').strip()
    if not raw:
        return None
    normalized = normalize_text(raw)
    request_type = classify_request(normalized)
    if not request_type:
        return None

    attachment_names = extract_attachment_names(raw)
    text = strip_attachment_lines(raw)
    parsed = ParsedSpinRequest(
        request_type=request_type,
        request_datetime=entry.get('received_at'),
        requested_by=str(entry.get('sender') or '').strip(),
        raw_message=raw,
        source_filename=source_filename,
        source_message_index=index,
        attachment_names=attachment_names,
    )
    parsed.customer_name = extract_customer_name(text, request_type)
    parsed.raw_id_text, parsed.national_id = extract_id(text)
    phones = extract_phones(text)
    if phones:
        parsed.primary_phone = phones[0]
    if len(phones) > 1:
        parsed.secondary_phone = phones[1]
    parsed.customer_type = extract_customer_type(text)
    parsed.loan_product = extract_loan_product(text)
    parsed.requested_amount = extract_amount(text)
    parsed.tenor = extract_tenor(text)
    parsed.code = extract_code(text)
    parsed.business_notes = extract_business_notes(text, parsed)
    parsed.source_message_hash = source_hash(entry, raw)
    parsed.parsed_fields = parsed_fields(parsed)
    return parsed


def classify_request(text: str) -> str | None:
    low = text.lower()
    if re.search(r'\b(has been shared|analysis has been shared|crb has been shared|this analysis has been shared)\b', low):
        return None
    if re.search(r'\bpost this payment|post this payments|reverse this transaction|create downpayment|zero rate\b', low):
        return None
    if re.search(r'\bkindly share\s+(a\s+)?spin\s+and\s+credit\s+analysis\s+for\b', low):
        return 'spin'
    if re.search(r'\bkindly share\s+spin\s+for\b', low):
        return 'spin'
    if re.search(r'\bkindly share\s+(the\s+)?analysis\s+for\b', low):
        return 'spin'
    if re.search(r'\bkindly share\s+crb\s+report\b|\bshare\s+crb\s+report\b|\bpls share crb\b', low):
        return 'crb'
    return None


def normalize_text(text: str) -> str:
    text = re.sub(r'@[\u2068]?[^\u2069\n]+[\u2069]?', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def strip_attachment_lines(text: str) -> str:
    lines = []
    for line in text.splitlines():
        value = line.strip()
        if not value:
            continue
        if value.lower() == '<media omitted>':
            continue
        if re.match(r'IMG-\S+\s+\(file attached\)', value, re.I):
            continue
        lines.append(value)
    return '\n'.join(lines)


def extract_attachment_names(text: str) -> list[str]:
    names = re.findall(r'\b([A-Z]{2,5}-\d{8}-WA\d{4}\.[A-Za-z0-9]+)\s+\(file attached\)', text)
    if '<Media omitted>' in text:
        names.append('<Media omitted>')
    return names


def extract_customer_name(text: str, request_type: str) -> str:
    single = normalize_text(strip_attachment_lines(text))
    patterns = []
    if request_type == 'spin':
        patterns.append(r'spin\s+and\s+credit\s+analysis\s+for\s+(?P<name>.+?)(?:\s+a\s+(?:new|existing)\s+(?:customer|client)|\s+an\s+(?:new|existing)\s+(?:customer|client)|\s+requesting|\s+id\b|\s+phone\b|$)')
        patterns.append(r'share\s+spin\s+for\s+(?P<name>.+?)(?:\s+id\b|\s+phn\b|\s+phone\b|\s+new\b|\s+existing\b|$)')
        patterns.append(r'share\s+(?:the\s+)?analysis\s+for\s+(?P<name>.+?)(?:\s+phone\b|\s+id\b|\s+ksh\b|\s+new\b|\s+existing\b|$)')
    elif request_type == 'crb':
        patterns.append(r'share\s+crb\s+report\s+(?:of|for)?\s*(?P<name>.+?)(?:\s+he\s+is|\s+she\s+is|\s+they\s+are|\s+requesting|\s+id\b|\s+phone\b|$)')
    for pattern in patterns:
        match = re.search(pattern, single, re.I)
        if match:
            return clean_name(match.group('name'))
    # Fallback for analysis-only multiline where the next line is the name.
    lines = [line.strip() for line in strip_attachment_lines(text).splitlines() if line.strip()]
    for i, line in enumerate(lines):
        if re.search(r'share\s+(?:the\s+)?analysis\s+for\s*$', line, re.I) and i + 1 < len(lines):
            return clean_name(lines[i + 1])
    return ''


def clean_name(value: str) -> str:
    value = re.sub(r'@\S+', ' ', value or '')
    value = re.sub(r'\b(?:id|id number|phone|phn|tel|mobile)\b.*$', '', value, flags=re.I)
    value = re.sub(r'[^A-Za-z\'\-\s]', ' ', value)
    words = [word for word in value.split() if word.lower() not in STOP_WORDS]
    return ' '.join(words).strip(' -.,;:/').upper()


def extract_id(text: str) -> tuple[str, str]:
    candidates = []
    for match in re.finditer(r'(?i)\b(?:id|id number|i\.?d|i?d|i\'d)\s*(?:number)?\s*[:.]?\s*([0-9][0-9\-\s]{5,20})', text):
        raw = re.sub(r'\s+', '', match.group(1)).strip('.,;:/')
        candidates.append(raw)
    if not candidates:
        for match in re.finditer(r'\b(\d{7,8})(?:-\d{3,8})?\b', text):
            raw = match.group(0)
            # Avoid common amounts like 150,000 after punctuation removal.
            if raw.replace('-', '').startswith('20') and len(raw.replace('-', '')) == 8:
                candidates.append(raw)
            elif len(raw.split('-')[0]) >= 7:
                candidates.append(raw)
    if not candidates:
        return '', ''
    raw = candidates[0]
    national = re.match(r'(\d{7,8})', raw)
    return raw, national.group(1) if national else re.sub(r'\D', '', raw)[:8]


def extract_phones(text: str) -> list[str]:
    found = []
    phone_contexts = re.finditer(r'(?i)\b(?:phone(?: number)?|phn|tel|mobile|phone no)\s*[:.]?\s*([+\d][\d\s/\-]{6,40})', text)
    for match in phone_contexts:
        found.extend(split_phone_blob(match.group(1)))
    for match in re.finditer(r'(?<!\d)(?:\+?254|0)?[17]\d{8}(?!\d)', text):
        phone = normalize_phone(match.group(0))
        if phone:
            found.append(phone)
    unique = []
    for phone in found:
        if phone and phone not in unique:
            unique.append(phone)
    return unique


def split_phone_blob(blob: str) -> list[str]:
    parts = re.split(r'[/,;]|\s+or\s+', blob)
    phones = []
    for part in parts:
        phone = normalize_phone(part)
        if phone:
            phones.append(phone)
    return phones


def normalize_phone(value: str) -> str:
    digits = re.sub(r'\D', '', str(value or ''))
    if digits.startswith('254') and len(digits) == 12 and digits[3] in {'1', '7'}:
        return digits
    if digits.startswith('0') and len(digits) == 10 and digits[1] in {'1', '7'}:
        return '254' + digits[1:]
    if len(digits) == 9 and digits[0] in {'1', '7'}:
        return '254' + digits
    return ''


def extract_customer_type(text: str) -> str:
    if re.search(r'\bnew\s+(?:customer|client)\b', text, re.I):
        return 'New'
    if re.search(r'\bexisting\s+(?:customer|client)\b|\bexisting\b', text, re.I):
        return 'Existing'
    return ''


def extract_loan_product(text: str) -> str:
    low = text.lower()
    for needle, label in PRODUCT_ALIASES:
        if needle in low:
            return label
    match = re.search(r'requesting\s+(?:for\s+)?(?:a\s+)?(?P<product>[A-Za-z ]{2,40}?)\s+loan\b', text, re.I)
    if match:
        return match.group('product').strip().title()
    return ''


def extract_amount(text: str) -> Decimal | None:
    patterns = [
        r'(?i)(?:kshs?|kes)\s*\.?\s*(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)',
        r'(?i)(?:loan|limit|of|for)\s+(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?k?)\b',
    ]
    candidates = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            value = parse_amount(match.group(1))
            if value is not None and value >= Decimal('1000'):
                candidates.append(value)
    return candidates[0] if candidates else None


def parse_amount(value: str) -> Decimal | None:
    value = str(value or '').strip().lower().replace(',', '')
    multiplier = Decimal('1000') if value.endswith('k') else Decimal('1')
    value = value.rstrip('k')
    try:
        return Decimal(value) * multiplier
    except (InvalidOperation, ValueError):
        return None


def extract_tenor(text: str) -> str:
    match = re.search(r'(?i)\b(?:to\s+pay\s+(?:with\s+)?|repay\s+in\s+|in\s+|for\s+|period\s*)?(\d+\s*(?:weeks?|wks?|months?|yrs?|years?))\b', text)
    if match:
        return re.sub(r'\s+', ' ', match.group(1)).strip()
    return ''


def extract_code(text: str) -> str:
    match = re.search(r'(?i)\bcode\s*[:.]?\s*([A-Za-z0-9/\-]+)', text)
    return match.group(1).strip('.,;') if match else ''


def extract_business_notes(text: str, parsed: ParsedSpinRequest) -> str:
    lines = [line.strip() for line in strip_attachment_lines(text).splitlines() if line.strip()]
    note_lines = []
    for line in lines:
        if re.search(r'(?i)^kindly share|^id\b|^phn\b|^phone\b|^code\b', line):
            continue
        if parsed.customer_name and parsed.customer_name.lower() in line.lower() and len(line.split()) <= 5:
            continue
        note_lines.append(line)
    note = ' '.join(note_lines)
    note = re.sub(r'(?i)\b(id|id number|phone|phn|code)\s*[:.]?\s*\S+', ' ', note)
    return re.sub(r'\s+', ' ', note).strip()[:1000]


def missing_fields_for(parsed: ParsedSpinRequest) -> list[str]:
    labels = {
        'customer_name': 'Customer Name',
        'national_id': 'National ID',
        'primary_phone': 'Primary Phone',
        'requested_amount': 'Requested Amount',
        'tenor': 'Tenor',
    }
    missing = []
    for field in REQUIRED_FIELDS.get(parsed.request_type, []):
        if not getattr(parsed, field):
            missing.append(labels[field])
    return missing


def source_hash(entry: dict[str, Any], raw: str) -> str:
    parts = [
        str(entry.get('received_at') or ''),
        str(entry.get('sender') or ''),
        raw,
    ]
    return hashlib.sha256('\n'.join(parts).encode('utf-8', errors='ignore')).hexdigest()


def parsed_fields(parsed: ParsedSpinRequest) -> dict[str, Any]:
    return {
        'request_type': parsed.request_type,
        'customer_name': parsed.customer_name,
        'national_id': parsed.national_id,
        'raw_id_text': parsed.raw_id_text,
        'primary_phone': parsed.primary_phone,
        'secondary_phone': parsed.secondary_phone,
        'customer_type': parsed.customer_type,
        'loan_product': parsed.loan_product,
        'requested_amount': str(parsed.requested_amount) if parsed.requested_amount is not None else '',
        'tenor': parsed.tenor,
        'business_notes': parsed.business_notes,
        'code': parsed.code,
        'attachment_names': parsed.attachment_names,
    }


def save_spin_request(group_config, parsed: ParsedSpinRequest, telegram_message_id: str, import_status: str) -> SpinCreditRequest:
    return SpinCreditRequest.objects.create(
        group_id=group_config.group_id,
        sheet_id=getattr(group_config, 'sheet_id', '') or '',
        sheet_name=getattr(group_config, 'sheet_name', '') or '',
        telegram_message_id=telegram_message_id,
        source_message_hash=parsed.source_message_hash,
        source_chat=getattr(group_config, 'display_name', '') or '',
        source_filename=parsed.source_filename,
        source_message_index=parsed.source_message_index,
        request_datetime=parsed.request_datetime,
        requested_by=parsed.requested_by,
        request_type=parsed.request_type,
        customer_name=parsed.customer_name,
        national_id=parsed.national_id,
        raw_id_text=parsed.raw_id_text,
        primary_phone=parsed.primary_phone,
        secondary_phone=parsed.secondary_phone,
        customer_type=parsed.customer_type,
        loan_product=parsed.loan_product,
        requested_amount=parsed.requested_amount,
        tenor=parsed.tenor,
        business_notes=parsed.business_notes,
        code=parsed.code,
        attachment_names=parsed.attachment_names,
        raw_message=parsed.raw_message,
        parsed_fields=parsed.parsed_fields,
        missing_fields=parsed.missing_fields,
        import_status=import_status,
    )


def append_spin_requests_to_sheet(group_config, records: list[SpinCreditRequest]) -> dict[str, Any]:
    if not records:
        return {'success': True, 'row_numbers': []}
    service = get_sheets_service(
        sheet_id=group_config.sheet_id,
        sheet_name=group_config.sheet_name,
        sheet_schema=None,
    )
    if not service.is_available():
        return {'success': False, 'error': 'Google Sheets service unavailable.'}
    workflow = getattr(group_config, 'workflow', None) or {}
    try:
        header_row_number = configured_header_row(workflow)
        headers = [str(value or '').strip() for value in service._sheet.row_values(header_row_number)]
    except Exception as exc:
        logger.error('Failed to read SPIN header row: %s', exc, exc_info=True)
        return {'success': False, 'error': str(exc)}
    if not headers:
        return {'success': False, 'error': 'Header row is empty or unavailable.'}
    field_headers = configured_field_headers(workflow)
    rows = []
    for record in records:
        row = ['' for _ in headers]
        values = sheet_values_for(record)
        missing_headers = [
            header for field, header in field_headers.items()
            if header and header not in headers and values.get(field, '') not in ('', None)
        ]
        if missing_headers:
            return {'success': False, 'error': 'Missing required column(s): ' + ', '.join(missing_headers[:8])}
        for field, header in field_headers.items():
            if header in headers:
                row[headers.index(header)] = values.get(field, '')
        rows.append(row)
    try:
        if hasattr(service._sheet, 'append_rows'):
            response = service._sheet.append_rows(rows, value_input_option='USER_ENTERED')
        else:
            responses = [service._sheet.append_row(row, value_input_option='USER_ENTERED') for row in rows]
            response = responses[0] if responses else {}
        return {'success': True, 'row_numbers': row_numbers_from_append_response(response, len(rows))}
    except Exception as exc:
        logger.error('Failed to append SPIN request rows: %s', exc, exc_info=True)
        return {'success': False, 'error': str(exc)}


def sheet_values_for(record: SpinCreditRequest) -> dict[str, Any]:
    return {
        'request_id': spin_request_id(record),
        'request_datetime': format_sheet_datetime(record.request_datetime),
        'branch': record.source_chat,
        'requested_by': record.requested_by,
        'request_type': REQUEST_TYPE_LABELS.get(record.request_type, record.request_type),
        'customer_name': record.customer_name,
        'national_id': record.national_id,
        'raw_id_text': record.raw_id_text,
        'primary_phone': record.primary_phone,
        'secondary_phone': record.secondary_phone,
        'customer_type': record.customer_type,
        'loan_product': record.loan_product,
        'requested_amount': record.requested_amount if record.requested_amount is not None else '',
        'tenor': record.tenor,
        'business_notes': record.business_notes,
        'code': record.code,
        'attachment_names': '\n'.join(record.attachment_names or []),
        'media_urls': (record.parsed_fields or {}).get('media_urls', ''),
        'raw_message': record.raw_message,
        'source_chat': record.source_chat,
        'source_filename': record.source_filename,
        'source_message_hash': record.source_message_hash,
        'parse_status': record.import_status.replace('_', ' ').title(),
        'missing_fields': ', '.join(record.missing_fields or []),
        'analysis_status': '',
        'analyst_response': '',
    }


def spin_request_id(record: SpinCreditRequest) -> str:
    if record.pk:
        return f"SPIN-{str(record.pk).split('-')[0].upper()}"
    return 'SPIN'


def configured_field_headers(workflow: dict) -> dict[str, str]:
    configured = dict(DEFAULT_FIELD_HEADERS)
    configured.update((workflow or {}).get('field_headers') or {})
    return configured


def configured_header_row(workflow: dict) -> int:
    try:
        return max(int((workflow or {}).get('header_row') or 1), 1)
    except (TypeError, ValueError):
        return 1


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


def format_sheet_datetime(value) -> str:
    if not value:
        return ''
    try:
        return timezone.localtime(value).strftime('%d-%b-%Y %H:%M')
    except Exception:
        return str(value)


def review_summary(parsed: ParsedSpinRequest) -> dict[str, Any]:
    return {
        'customer_name': parsed.customer_name,
        'national_id': parsed.national_id,
        'primary_phone': parsed.primary_phone,
        'request_type': REQUEST_TYPE_LABELS.get(parsed.request_type, parsed.request_type),
        'missing_fields': parsed.missing_fields,
    }


def request_summary(record: SpinCreditRequest | None, parsed: ParsedSpinRequest | None = None) -> dict[str, Any]:
    if record:
        return {
            'customer_name': record.customer_name,
            'national_id': record.national_id,
            'primary_phone': record.primary_phone,
            'request_type': REQUEST_TYPE_LABELS.get(record.request_type, record.request_type),
        }
    if parsed:
        return review_summary(parsed)
    return {}



def create_spin_form_token(group_id: str) -> str:
    return signing.dumps({'group_id': str(group_id)}, salt=SPIN_FORM_TOKEN_SALT)


def validate_spin_form_token(token: str, group_id: str) -> tuple[bool, str]:
    if not token:
        return False, 'Form token is missing. Open the form again from Telegram.'
    max_age = int(getattr(settings, 'SPIN_WEBAPP_AUTH_MAX_AGE_SECONDS', 86400))
    try:
        payload = signing.loads(
            token,
            salt=SPIN_FORM_TOKEN_SALT,
            max_age=max_age if max_age > 0 else None,
        )
    except signing.SignatureExpired:
        return False, 'Form token has expired. Open the form again from Telegram.'
    except signing.BadSignature:
        return False, 'Form token is invalid. Open the form again from Telegram.'
    if str(payload.get('group_id', '')) != str(group_id):
        return False, 'Form token does not match this group.'
    return True, ''


def build_spin_form_url(group_id: str) -> str:
    base_url = getattr(settings, 'APP_BASE_URL', '').rstrip('/')
    if not base_url:
        return ''
    return (
        f"{base_url}/spin/?"
        + urlencode({'group_id': str(group_id), 'token': create_spin_form_token(group_id)})
    )


def build_spin_mini_app_url(group_id: str) -> str:
    bot_username = str(getattr(settings, 'TELEGRAM_BOT_USERNAME', '') or '').strip().lstrip('@')
    short_name = str(getattr(settings, 'SPIN_MINI_APP_SHORT_NAME', '') or '').strip().strip('/')
    if not bot_username or not short_name:
        return ''
    return f"https://t.me/{bot_username}/{short_name}?startapp={create_spin_start_param(group_id)}"


def create_spin_start_param(group_id: str) -> str:
    payload = {'group_id': str(group_id), 'token': create_spin_form_token(group_id)}
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(',', ':')).encode('utf-8')
    ).decode('ascii')
    return encoded.rstrip('=')


def decode_spin_start_param(start_param: str) -> dict[str, str]:
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
    group_id = str(payload.get('group_id', '')).strip()
    token = str(payload.get('token', '')).strip()
    if not group_id or not token:
        return {}
    return {'group_id': group_id, 'token': token}


def validate_spin_telegram_webapp_init_data(init_data: str) -> tuple[bool, str, dict]:
    if not getattr(settings, 'SPIN_WEBAPP_REQUIRE_TELEGRAM_AUTH', True):
        return True, '', {}
    bot_token = getattr(settings, 'TELEGRAM_BOT_TOKEN', '')
    if not bot_token:
        return False, 'TELEGRAM_BOT_TOKEN is not configured.', {}
    if not init_data:
        return False, 'Telegram Mini App authentication data is missing.', {}

    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop('hash', '')
    if not received_hash:
        return False, 'Telegram Mini App hash is missing.', {}
    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(pairs.items()))
    secret_key = hmac.new(b'WebAppData', bot_token.encode('utf-8'), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode('utf-8'), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calculated_hash, received_hash):
        return False, 'Telegram Mini App authentication failed.', {}

    auth_date = pairs.get('auth_date')
    max_age = int(getattr(settings, 'SPIN_WEBAPP_AUTH_MAX_AGE_SECONDS', 86400))
    if auth_date and max_age > 0:
        try:
            if time.time() - int(auth_date) > max_age:
                return False, 'Telegram Mini App authentication expired.', {}
        except ValueError:
            return False, 'Telegram Mini App auth_date is invalid.', {}
    return True, '', pairs


def process_spin_form_submission(
    group_config,
    fields: dict[str, Any],
    sender: str = '',
    received_at=None,
    uploaded_files: list | None = None,
) -> dict[str, Any]:
    cleaned, errors = validate_spin_form_fields(fields)
    if errors:
        return {
            'success': False,
            'status': 'validation_error',
            'message': 'Fix the highlighted fields and submit again.',
            'errors': errors,
        }

    received_at = received_at or timezone.now()
    uploaded_files = uploaded_files or []
    media_links: list[str] = []
    media_warnings: list[str] = []
    attachment_names = uploaded_file_names(uploaded_files)
    if uploaded_files:
        from core.services.order_approval import store_uploaded_files_for_order

        uploaded_media = store_uploaded_files_for_order(
            group_config=group_config,
            uploaded_files=uploaded_files,
            sender=sender or 'Telegram Mini App',
            received_at=received_at,
            business_key_value=cleaned['national_id'],
            order_update=None,
        )
        media_links = uploaded_media.links
        media_warnings = uploaded_media.warnings
        if media_warnings or uploaded_media.skipped_count:
            return {
                'success': False,
                'status': 'media_upload_failed',
                'message': 'Request was not submitted because one or more files could not be stored.',
                'errors': media_warnings or ['One or more files could not be stored.'],
                'files_stored': uploaded_media.stored_count,
            }
    if media_links:
        cleaned['media_urls'] = '\n'.join(media_links)
    if attachment_names:
        cleaned['attachment_names'] = attachment_names
    raw_message = json.dumps({**cleaned, 'requested_amount': str(cleaned.get('requested_amount') or '')}, ensure_ascii=True, sort_keys=True)
    parsed = ParsedSpinRequest(
        request_type=cleaned['request_type'],
        request_datetime=received_at,
        requested_by=sender or 'Telegram Mini App',
        customer_name=cleaned['customer_name'],
        national_id=cleaned['national_id'],
        raw_id_text=cleaned['national_id'],
        primary_phone=cleaned['primary_phone'],
        secondary_phone=cleaned.get('secondary_phone', ''),
        customer_type=cleaned.get('customer_type', ''),
        loan_product=cleaned.get('loan_product', ''),
        requested_amount=cleaned['requested_amount'],
        tenor=cleaned['tenor'],
        business_notes=cleaned.get('business_notes', ''),
        code=cleaned.get('code', ''),
        attachment_names=attachment_names,
        raw_message=raw_message,
        source_filename='Telegram Mini App',
        source_message_hash=hashlib.sha256(
            f"{group_config.group_id}\n{received_at.isoformat()}\n{sender}\n{raw_message}".encode('utf-8')
        ).hexdigest(),
    )
    parsed.missing_fields = missing_fields_for(parsed)
    parsed.parsed_fields = parsed_fields(parsed)
    if media_links:
        parsed.parsed_fields['media_urls'] = '\n'.join(media_links)

    try:
        record = save_spin_request(
            group_config=group_config,
            parsed=parsed,
            telegram_message_id='miniapp',
            import_status='imported' if parsed.is_complete else 'review_needed',
        )
    except IntegrityError:
        return {
            'success': False,
            'status': 'duplicate',
            'message': 'This request was already submitted. Check the sheet before sending it again.',
            'errors': ['Duplicate request detected.'],
        }

    sync_result = append_spin_requests_to_sheet(group_config, [record])
    if not sync_result.get('success'):
        error = sync_result.get('error') or 'Google Sheets append failed.'
        record.import_status = 'failed'
        record.sync_error = error
        record.save(update_fields=['import_status', 'sync_error', 'updated_at'])
        return {
            'success': False,
            'status': 'sheet_sync_failed',
            'message': 'Request was not submitted because the sheet could not be updated.',
            'errors': [error],
            'request_id': spin_request_id(record),
        }

    row_numbers = sync_result.get('row_numbers') or []
    record.row_number = row_numbers[0] if row_numbers else None
    record.sheet_id = group_config.sheet_id or ''
    record.sheet_name = group_config.sheet_name or ''
    record.sync_error = ''
    record.save(update_fields=['row_number', 'sheet_id', 'sheet_name', 'sync_error', 'updated_at'])
    return {
        'success': True,
        'status': 'submitted',
        'message': 'SPIN/CRB request submitted.',
        'request_id': spin_request_id(record),
        'request_type': REQUEST_TYPE_LABELS.get(record.request_type, record.request_type),
        'customer_name': record.customer_name,
        'national_id': record.national_id,
        'primary_phone': record.primary_phone,
        'files_stored': len(media_links),
        'media_urls': media_links,
    }


def validate_spin_form_fields(fields: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    data = {key: str(value or '').strip() for key, value in (fields or {}).items()}
    request_type = data.get('request_type', '').lower().replace(' report', '')
    if request_type == 'crb report':
        request_type = 'crb'
    errors = []
    if request_type not in SPIN_FORM_REQUEST_TYPES:
        errors.append('Request Type must be SPIN or CRB.')

    name = clean_name(data.get('customer_name', ''))
    if not name:
        errors.append('Customer Name is required.')

    national_id = re.sub(r'\D', '', data.get('national_id', ''))
    if not re.fullmatch(r'\d{7,8}', national_id or ''):
        errors.append('National ID must be 7 or 8 digits.')

    primary_phone = normalize_phone(data.get('primary_phone', ''))
    if not primary_phone:
        errors.append('Primary Phone must be a valid Kenyan number, for example 254712345678.')
    secondary_phone = ''
    if data.get('secondary_phone'):
        secondary_phone = normalize_phone(data.get('secondary_phone', ''))
        if not secondary_phone:
            errors.append('Secondary Phone must be a valid Kenyan number or left blank.')

    amount = parse_amount(data.get('requested_amount', ''))
    if amount is None or amount <= Decimal('0'):
        errors.append('Requested Amount is required and must be a number greater than 0.')

    tenor = re.sub(r'\s+', ' ', data.get('tenor', '')).strip()
    if not tenor:
        errors.append('Tenor is required, for example 6 weeks or 12 months.')

    customer_type = data.get('customer_type', '').title()
    if customer_type and customer_type not in {'New', 'Existing'}:
        errors.append('Customer Type must be New, Existing, or blank.')

    return {
        'request_type': request_type,
        'customer_name': name,
        'national_id': national_id,
        'primary_phone': primary_phone,
        'secondary_phone': secondary_phone,
        'customer_type': customer_type,
        'loan_product': data.get('loan_product', '').strip().title(),
        'requested_amount': amount,
        'tenor': tenor,
        'business_notes': data.get('business_notes', '')[:1000],
        'code': data.get('code', '')[:255],
    }, errors




def collect_spin_uploaded_files(files_map) -> list:
    from core.services.order_approval import UploadedFileItem

    uploads = []
    getlist = getattr(files_map, 'getlist', None)
    if not getlist:
        return uploads
    for field_name, file_type in SPIN_UPLOAD_FIELDS:
        for file_obj in getlist(field_name) or []:
            uploads.append(UploadedFileItem(file=file_obj, file_type=file_type))
    return uploads


def validate_spin_uploaded_files(files_map) -> list[str]:
    errors: list[str] = []
    getlist = getattr(files_map, 'getlist', None)
    if not getlist:
        return errors

    max_files_per_slot = int(getattr(settings, 'SPIN_MAX_FILES_PER_SLOT', 2))
    max_total_bytes = int(getattr(settings, 'SPIN_MAX_TOTAL_UPLOAD_MB', 20)) * 1024 * 1024
    labels = {
        'id_photos': 'ID photos',
        'supporting_docs': 'Supporting documents',
        'other_files': 'Other files',
    }
    total_size = 0
    for field_name, _file_type in SPIN_UPLOAD_FIELDS:
        files = list(getlist(field_name) or [])
        if len(files) > max_files_per_slot:
            errors.append(f"{labels.get(field_name, field_name)} supports at most {max_files_per_slot} file(s).")
        for file_obj in files:
            try:
                total_size += int(getattr(file_obj, 'size', 0) or 0)
            except (TypeError, ValueError):
                continue
    if total_size > max_total_bytes:
        errors.append(
            "Total upload size is too large. Upload at most "
            f"{getattr(settings, 'SPIN_MAX_TOTAL_UPLOAD_MB', 20)} MB per submission."
        )
    return errors


def uploaded_file_names(uploaded_files: list) -> list[str]:
    names = []
    for item in uploaded_files or []:
        file_obj = getattr(item, 'file', item)
        name = str(getattr(file_obj, 'name', '') or '').strip()
        if name:
            names.append(name)
    return names



