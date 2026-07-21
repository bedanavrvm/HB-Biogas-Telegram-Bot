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
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.models import GroupSheetConfiguration, SpinBatchReviewItem, SpinCreditRequest, SpinRequestSequence
from core.services.branches import global_branch_choices, validate_workflow_branch, workflow_branches, workflow_default_branch
from core.services.parser import analyze_whatsapp_export
from core.services.sheets import get_sheets_service

logger = logging.getLogger(__name__)

SPIN_WORKFLOW_TYPE = 'spin_credit_analysis'
SPIN_FORM_TOKEN_SALT = 'spin-crb-form'
SPIN_FORM_REQUEST_TYPES = {'spin_crb', 'spin', 'crb'}
SPIN_UPLOAD_FIELDS = [
    ('id_photos', 'id_photo'),
    ('supporting_docs', 'laf_doc'),
    ('other_files', 'other_file'),
]

DEFAULT_FIELD_HEADERS = {
    'request_id': 'Request ID',
    'request_datetime': 'Request Date/Time',
    'request_month': 'Request Month',
    'branch': 'Branch',
    'requested_by': 'Requested By',
    'credit_analyst_name': 'Credit Analyst Name',
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
    'code': 'MPESA Statement Code',
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

OPTIONAL_SHEET_FIELDS = {'analysis_status', 'analyst_response', 'attachment_names', 'credit_analyst_name'}
SPIN_REVIEW_EDITABLE_FIELDS = {
    'request_type',
    'branch',
    'customer_name',
    'national_id',
    'primary_phone',
    'secondary_phone',
    'customer_type',
    'loan_product',
    'requested_amount',
    'tenor',
    'business_notes',
    'code',
}
SPIN_REVIEW_SHEET_FIELDS = [
    'branch',
    'request_type',
    'customer_name',
    'national_id',
    'raw_id_text',
    'primary_phone',
    'secondary_phone',
    'customer_type',
    'loan_product',
    'requested_amount',
    'tenor',
    'business_notes',
    'code',
    'parse_status',
    'missing_fields',
]
SPIN_ANALYSIS_STATUS_COLOURS = {
    'completed': '#d9ead3',
    'pending': '#fff2cc',
    'in progress': '#cfe2f3',
    'failed': '#f4cccc',
    'rejected': '#ead1dc',
}

REQUEST_TYPE_LABELS = {
    'spin_crb': 'SPIN/CRB',
    'spin': 'SPIN',
    'crb': 'CRB Report',
}

REQUIRED_FIELDS = {
    'spin_crb': ['customer_name', 'national_id', 'primary_phone', 'requested_amount', 'tenor'],
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
    ('micro-asset', 'Micro Asset'),
    ('micro asset', 'Micro Asset'),
    ('microasset', 'Micro Asset'),
    ('daranja', 'Daraja'),
    ('daraja', 'Daraja'),
    ('msingi', 'Msingi'),
    ('digital', 'Digital'),
    ('fedha chap chap', 'Fedha Chap Chap'),
    ('inua', 'Inua'),
    ('partnership', 'Partnership'),
    ('flex', 'Flex'),
    ('biashara', 'Biashara'),
]

FIELD_LABEL_PATTERN = r"(?:name|id(?:\s+number|\s+no)?|i'?d(?:\s+no)?|phone(?:\s+number|\s+no)?|phn(?:\s+no)?|phno(?:\s+no)?|p/no|p\s*no|tel|mobile|no|number|product|amount|duration|duaration|period|code)"

SPIN_KEYWORD_PATTERNS = {
    'spin': [r'\bspin\b'],
    'crb': [r'\bcrb\b', r'\bcredit\s+reference\s+bureau\b'],
    'credit_analysis': [
        r'\bcredit[\s\-/]*analysis\b',
        r'\bcredit[\s\-/]*assessment\b',
        r'\bcredit[\s\-/]*check\b',
        r'\bcredit[\s\-/]*review\b',
        r'\bcredit[\s\-/]*request\b',
    ],
    'loan_analysis': [
        r'\bloan[\s\-/]*analysis\b',
        r'\bloan[\s\-/]*assessment\b',
        r'\bloan[\s\-/]*check\b',
        r'\bloan[\s\-/]*request\b',
        r'\bcustomer[\s\-/]*analysis\b',
    ],
}

SPIN_EXCLUSION_PATTERNS = [
    r'\b(has been shared|analysis has been shared|crb has been shared|this analysis has been shared)\b',
    r'\bpost this payment|post this payments|reverse this transaction|create downpayment|zero rate|spin fee\b',
    r'\b(?:reply|respond)\s+to\s+(?:the\s+)?(?:credit\s+)?analysis\b',
    r'\bawaiting\s+(?:second\s+|2nd\s+)?opinion\s+analysis\s+reply\b',
    r'\bawaiting\s+analysis\s+reply\b',
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


@dataclass
class SpinProgressEvent:
    stage: str
    label: str
    received_at: Any = None
    sender: str = ''
    raw_message: str = ''


@dataclass
class SpinMessageClassification:
    category: str
    request_type: str | None = None
    keywords: list[str] = field(default_factory=list)
    identifier_fields: list[str] = field(default_factory=list)
    loan_detail_fields: list[str] = field(default_factory=list)
    reason: str = ''


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
    pending_progress_targets = []
    skipped = 0
    spin_candidates = 0
    incomplete_candidates = []
    ambiguous_messages = []
    batch_review_items = []
    progress_events = 0
    linked_progress_events = 0
    unlinked_progress_events = []
    for index, entry in enumerate(entries):
        item = parse_spin_entry(entry, index=index, source_filename=source_filename)
        if item is not None:
            parsed.append(item)
            pending_progress_targets.append(item)
            continue

        event = classify_spin_progress_event(entry)
        if event is not None:
            progress_events += 1
            if apply_spin_progress_event(pending_progress_targets, event):
                linked_progress_events += 1
            else:
                unlinked_progress_events.append(progress_event_summary(event))
            continue

        classification = classify_spin_message(str(entry.get('content') or ''))
        if classification.category == 'incomplete':
            spin_candidates += 1
            incomplete_candidates.append(classification_summary(entry, classification, index))
            review_item = persist_spin_batch_review_item(
                group_config, entry, classification, index, telegram_message_id, source_filename,
            )
            if review_item:
                batch_review_items.append(review_item)
            continue
        if classification.category == 'ambiguous':
            ambiguous_messages.append(classification_summary(entry, classification, index))
            review_item = persist_spin_batch_review_item(
                group_config, entry, classification, index, telegram_message_id, source_filename,
            )
            if review_item:
                batch_review_items.append(review_item)
            continue

        skipped += 1

    spin_candidates += len(parsed)

    if not parsed:
        return {
            'status': 'spin_batch_processed',
            'source': SPIN_WORKFLOW_TYPE,
            'export_messages': len(entries),
            'spin_candidates': spin_candidates,
            'processed': 0,
            'valid_requests': 0,
            'incomplete_requests': len(incomplete_candidates),
            'ambiguous_messages': len(ambiguous_messages),
            'imported': 0,
            'review_needed': 0,
            'batch_review_queued': len(batch_review_items),
            'duplicates': 0,
            'rejected': 0,
            'failed': 0,
            'skipped': skipped,
            'progress_events': progress_events,
            'linked_progress_events': linked_progress_events,
            'unlinked_progress_events': unlinked_progress_events[:8],
            'incomplete_items': incomplete_candidates[:8],
            'ambiguous_items': ambiguous_messages[:8],
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
        batch_sheet_name = configured_spin_batch_sheet_name(getattr(group_config, 'workflow', None) or {}, group_config.sheet_name)
        sync_result = append_spin_requests_to_sheet(group_config, records_for_sheet, sheet_name=batch_sheet_name)
        if sync_result.get('success'):
            row_numbers = sync_result.get('row_numbers') or []
            for index, record in enumerate(records_for_sheet):
                record.row_number = row_numbers[index] if index < len(row_numbers) else None
                record.sheet_id = group_config.sheet_id or ''
                record.sheet_name = sync_result.get('sheet_name') or batch_sheet_name or ''
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
        'spin_candidates': spin_candidates,
        'processed': len(parsed),
        'valid_requests': len(parsed),
        'incomplete_requests': len(incomplete_candidates),
        'ambiguous_messages': len(ambiguous_messages),
        'imported': sum(1 for r in results if r['status'] == 'imported'),
        'review_needed': sum(1 for r in results if r['status'] == 'review_needed'),
        'batch_review_queued': len(batch_review_items),
        'duplicates': sum(1 for r in results if r['status'] == 'duplicate'),
        'rejected': sum(1 for r in results if r['status'] == 'rejected'),
        'failed': sum(1 for r in results if r['status'] == 'failed'),
        'skipped': skipped,
        'progress_events': progress_events,
        'linked_progress_events': linked_progress_events,
        'unlinked_progress_events': unlinked_progress_events[:8],
        'incomplete_items': incomplete_candidates[:8],
        'ambiguous_items': ambiguous_messages[:8],
        'sheet_sync': sync_result,
        'review_items': [review_summary(r['parsed']) for r in results if r['status'] == 'review_needed'][:8],
        'duplicates_list': [request_summary(r.get('record'), r.get('parsed')) for r in results if r['status'] == 'duplicate'][:8],
    }


def classify_spin_progress_event(entry: dict[str, Any]) -> SpinProgressEvent | None:
    raw = str(entry.get('content') or '').strip()
    if not raw:
        return None
    text = normalize_text(strip_attachment_lines(raw))
    low = text.lower()
    if not low or 'message was deleted' in low:
        return None

    patterns = [
        ('analysis_shared', 'Credit Analysis Shared', r'\b(?:this|the)?\s*(?:credit\s+)?analysis\s+has\s+been\s+shared\b'),
        ('crb_shared', 'CRB Shared', r'\b(?:the\s+)?crb\s+has\s+been\s+shared\b'),
        ('statement_requested', 'Statement Requested', r'\bkindly\s+share\s+(?:a\s+|the\s+|his\s+|her\s+|client\'?s\s+)?(?:\d+\s*months?\s+)?(?:m-?pesa\s+|mpesa\s+)?statement\b|\bkindly\s+share\s+statement\b'),
        ('statement_shared', 'Statement Shared', r'\b(?:m-?pesa\s+|mpesa\s+)?statement\s+(?:has\s+been\s+)?shared\b|\bcode\s+[A-Za-z0-9/\-]{3,}\b'),
        ('spin_pending', 'SPIN Pending', r'\b(?:this\s+)?spin\s+(?:is\s+)?(?:still\s+)?pending\b'),
        ('analysis_reply_requested', 'Analysis Reply Requested', r'\b(?:reply|respond)\s+to\s+(?:the\s+)?(?:credit\s+)?analysis\b|\bawaiting\s+(?:second\s+|2nd\s+)?opinion\s+analysis\s+reply\b|\bawaiting\s+analysis\s+reply\b'),
        ('spin_generation_requested', 'SPIN Generation Requested', r'\b(?:shared\s+statement\s+)?kindly\s+generate\s+(?:the\s+)?spin\b'),
        ('missing_info_requested', 'Missing Information Requested', r'\bkindly\s+share\s+(?:the\s+)?(?:correct\s+)?(?:code|client\'?s\s+id|id)\b|\bkindly\s+share\s+the\s+correct\s+id\b'),
        ('pending', 'Pending', r'^pending\.?$'),
        ('loan_approved', 'Approved', r'\bapproved\b|\bkindly\s+proceed\b|\bplease\s+proceed\b'),
        ('loan_rejected', 'Rejected', r'\brejected\b|\bdeclined\b'),
    ]
    for stage, label, pattern in patterns:
        if re.search(pattern, low, re.I):
            return SpinProgressEvent(
                stage=stage,
                label=label,
                received_at=entry.get('received_at'),
                sender=str(entry.get('sender') or '').strip(),
                raw_message=text[:1000],
            )
    return None


def apply_spin_progress_event(pending_targets: list[ParsedSpinRequest], event: SpinProgressEvent) -> bool:
    if not pending_targets:
        return False
    target = pending_targets[0]
    target.parsed_fields = target.parsed_fields or parsed_fields(target)
    progress_items = target.parsed_fields.setdefault('progress_events', [])
    progress_items.append(progress_event_summary(event))
    target.parsed_fields['analysis_status'] = event.label
    line = progress_response_line(event)
    existing = str(target.parsed_fields.get('analyst_response') or '').strip()
    target.parsed_fields['analyst_response'] = f"{existing}\n{line}".strip() if existing else line
    if event.stage in {'analysis_shared', 'crb_shared', 'loan_approved', 'loan_rejected'}:
        pending_targets.pop(0)
    return True


def progress_event_summary(event: SpinProgressEvent) -> dict[str, str]:
    return {
        'stage': event.stage,
        'label': event.label,
        'received_at': format_sheet_datetime(event.received_at),
        'sender': event.sender,
        'message': event.raw_message,
    }


def progress_response_line(event: SpinProgressEvent) -> str:
    parts = [event.label]
    when = format_sheet_datetime(event.received_at)
    if when:
        parts.append(when)
    if event.sender:
        parts.append(event.sender)
    prefix = ' - '.join(parts)
    return f"{prefix}: {event.raw_message}" if event.raw_message else prefix

def parse_spin_entry(entry: dict[str, Any], index: int = 0, source_filename: str = '') -> ParsedSpinRequest | None:
    raw = str(entry.get('content') or '').strip()
    if not raw:
        return None
    text = strip_attachment_lines(raw)
    normalized = normalize_text(text)
    request_type = classify_request(normalized)
    if not request_type:
        return None

    attachment_names = extract_attachment_names(raw)
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
    classification = classify_spin_message(text)
    return classification.request_type if classification.category == 'valid' else None


def classify_spin_message(text: str) -> SpinMessageClassification:
    clean = normalize_text(strip_attachment_lines(text))
    low = clean.lower()
    if not low or 'message was deleted' in low:
        return SpinMessageClassification(category='non_spin', reason='Empty or deleted message.')
    if any(re.search(pattern, low, re.I) for pattern in SPIN_EXCLUSION_PATTERNS):
        return SpinMessageClassification(category='non_spin', reason='Matched a progress or exclusion phrase.')

    keywords = matched_spin_keywords(low)
    request_type = request_type_from_keywords(keywords, low)
    if not keywords:
        identifiers, loan_details = detect_spin_candidate_details(clean, request_type='spin_crb')
        if identifiers or loan_details:
            return SpinMessageClassification(
                category='ambiguous',
                identifier_fields=identifiers,
                loan_detail_fields=loan_details,
                reason='Customer or loan details found, but no SPIN/CRB/credit-analysis keyword was present.',
            )
        return SpinMessageClassification(category='non_spin', reason='No SPIN-related keyword found.')

    identifiers, loan_details = detect_spin_candidate_details(clean, request_type=request_type or 'spin_crb')
    if identifiers or loan_details:
        return SpinMessageClassification(
            category='valid',
            request_type=request_type or 'spin_crb',
            keywords=keywords,
            identifier_fields=identifiers,
            loan_detail_fields=loan_details,
            reason='SPIN-related keyword and customer/loan details found.',
        )
    return SpinMessageClassification(
        category='incomplete',
        request_type=request_type or 'spin_crb',
        keywords=keywords,
        reason='SPIN-related message detected, but no customer identifier or loan details were found.',
    )


def matched_spin_keywords(low: str) -> list[str]:
    matches = []
    for label, patterns in SPIN_KEYWORD_PATTERNS.items():
        if any(re.search(pattern, low, re.I) for pattern in patterns):
            matches.append(label)
    # Preserve compatibility with common request-only phrasing.
    if re.search(r'\bkindly\s+share\s+(?:the\s+)?analysis\b', low) and 'credit_analysis' not in matches:
        matches.append('credit_analysis')
    return matches


def request_type_from_keywords(keywords: list[str], low: str) -> str | None:
    keyword_set = set(keywords)
    if 'crb' in keyword_set and not ({'spin', 'credit_analysis', 'loan_analysis'} & keyword_set):
        return 'crb'
    if re.search(r'\bspin\s+analysis\b|\bspin\s+(?:and|&)\s+credit\s+analysis\b|\bcredit\s+analysis\b', low):
        return 'spin_crb'
    if 'spin' in keyword_set and not ({'crb', 'credit_analysis', 'loan_analysis'} & keyword_set):
        return 'spin'
    if keywords:
        return 'spin_crb'
    if re.search(r'\bcrb\b', low):
        return 'crb'
    return None


def detect_spin_candidate_details(text: str, request_type: str) -> tuple[list[str], list[str]]:
    identifiers = []
    loan_details = []
    raw_id, national_id = extract_id(text)
    if national_id:
        identifiers.append('national_id')
    if extract_phones(text):
        identifiers.append('phone_number')
    if re.search(r'\b(?:customer|client|account|acct|imab)\s*(?:id|no|number|#)?\s*[:#-]?\s*[A-Za-z0-9/-]{4,}\b', text, re.I):
        identifiers.append('customer_reference')
    if extract_customer_name(text, request_type):
        identifiers.append('customer_name')

    if extract_amount(text) is not None:
        loan_details.append('loan_amount')
    if extract_loan_product(text):
        loan_details.append('loan_product')
    if extract_tenor(text):
        loan_details.append('tenor')
    if extract_code(text):
        loan_details.append('mpesa_code')
    if re.search(r'\b(?:loan\s+balance|balance|deposit|monthly\s+repayment|repayment|purpose)\b', text, re.I):
        loan_details.append('loan_detail')
    return sorted(set(identifiers)), sorted(set(loan_details))


def classification_summary(entry: dict[str, Any], classification: SpinMessageClassification, index: int) -> dict[str, Any]:
    return {
        'index': index,
        'sender': str(entry.get('sender') or '').strip(),
        'received_at': format_sheet_datetime(entry.get('received_at')),
        'category': classification.category,
        'keywords': classification.keywords,
        'identifier_fields': classification.identifier_fields,
        'loan_detail_fields': classification.loan_detail_fields,
        'reason': classification.reason,
    }


def parse_spin_review_candidate(
    entry: dict[str, Any],
    classification: SpinMessageClassification,
    index: int,
    source_filename: str,
) -> ParsedSpinRequest:
    """Extract every usable field from an uncertain message without promoting it yet."""
    raw = str(entry.get('content') or '').strip()
    text = strip_attachment_lines(raw)
    request_type = classification.request_type or 'spin_crb'
    parsed = ParsedSpinRequest(
        request_type=request_type,
        request_datetime=entry.get('received_at'),
        requested_by=str(entry.get('sender') or '').strip(),
        raw_message=raw,
        source_filename=source_filename,
        source_message_index=index,
        attachment_names=extract_attachment_names(raw),
        source_message_hash=source_hash(entry, raw),
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
    parsed.parsed_fields = parsed_fields(parsed)
    parsed.missing_fields = missing_fields_for(parsed)
    return parsed


def persist_spin_batch_review_item(
    group_config,
    entry: dict[str, Any],
    classification: SpinMessageClassification,
    index: int,
    telegram_message_id: str,
    source_filename: str,
) -> SpinBatchReviewItem | None:
    """Persist uncertain messages so a batch import can never silently discard them."""
    candidate = parse_spin_review_candidate(entry, classification, index, source_filename)
    existing_request = SpinCreditRequest.objects.filter(
        group_id=str(group_config.group_id),
        source_message_hash=candidate.source_message_hash,
    ).first()
    defaults = {
        'telegram_message_id': str(telegram_message_id or ''),
        'source_filename': source_filename,
        'source_message_index': index,
        'source_sender': candidate.requested_by,
        'source_received_at': candidate.request_datetime,
        'raw_message': candidate.raw_message,
        'category': classification.category,
        'reason': classification.reason,
        'detected_fields': {
            'keywords': classification.keywords,
            'identifier_fields': classification.identifier_fields,
            'loan_detail_fields': classification.loan_detail_fields,
        },
        'candidate_fields': candidate.parsed_fields,
    }
    item, created = SpinBatchReviewItem.objects.get_or_create(
        group_id=str(group_config.group_id),
        source_message_hash=candidate.source_message_hash,
        defaults=defaults,
    )
    if existing_request and item.status == 'pending':
        item.status = 'resolved'
        item.resolved_request = existing_request
        item.resolution_fields = {'source': 'automatic_import'}
        item.reviewed_at = timezone.now()
        item.save(update_fields=['status', 'resolved_request', 'resolution_fields', 'reviewed_at', 'updated_at'])
        return None
    return item if created or item.status == 'pending' else None


def has_spin_request_details(low: str) -> bool:
    if re.search(r'\b(?:id|id\s+no|id\s+number|phone|phn|tel|mobile|code|kes|ksh|kshs|period|requesting|client|customer|product)\b', low):
        return True
    if re.search(r'(?<!\d)(?:\+?254|0)?[17]\d{8}(?!\d)', low):
        return True
    if re.search(r'\b\d{7,8}\b', low):
        return True
    return False


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
    if request_type == 'spin_crb':
        patterns.append(r'(?:crb\s+(?:and|&)\s+spin|spin\s+(?:and|&)\s+crb)\s+report\s+for\s+(?P<name>.+?)(?:\s+who\b|\s+a\s+(?:new|existing)\s+(?:customer|client)|\s+an\s+(?:new|existing)\s+(?:customer|client)|\s+requesting|\s+id\b|\s+phone\b|$)')
        patterns.append(r'spin\s+and\s+credit\s+analysis\s+for\s+(?P<name>.+?)(?:\s+a\s+(?:new|existing)\s+(?:customer|client)|\s+an\s+(?:new|existing)\s+(?:customer|client)|\s+requesting|\s+id\b|\s+phone\b|$)')
        patterns.append(r'(?:spin\s*/\s*crb|spin\s+(?:and|&)\s+crb|spin\s+crb)\s+(?:request\s+)?(?:for\s+)?(?P<name>.+?)(?:\s+a\s+(?:new|existing)\s+(?:customer|client)|\s+an\s+(?:new|existing)\s+(?:customer|client)|\s+requesting|\s+id\b|\s+phone\b|$)')
        patterns.append(r'share\s+(?:the\s+)?spin\s+analysis\s+(?:of|for)?\s*(?P<name>.+?)(?:\s+who\b|\s+applying\b|\s+seeking\b|\s+taking\b|\s+id\b|\s+i\'?d\b|\s+\d{7,8}\b|\s+phone\b|\s+phn\b|\s+p/no\b|\s+kes\b|\s+ksh\b|\s+new\b|\s+existing\b|$)')
        patterns.append(r'share\s+(?:the\s+)?analysis\s+for\s+(?P<name>.+?)(?:\s+who\b|\s+phone\b|\s+id\b|\s+ksh\b|\s+new\b|\s+existing\b|$)')
        patterns.append(r'(?:assist|help|do|run|check|process|send|share|need|request(?:ing)?)\s+(?:me\s+)?(?:with\s+|for\s+)?(?:a\s+|the\s+)?(?:client\s+)?(?:spin\s*(?:/|and|&)?\s*)?(?:credit\s+)?analysis\s+(?:for|of)?\s*(?P<name>.+?)(?:\s+who\b|\s+applying\b|\s+seeking\b|\s+taking\b|\s+a\s+(?:new|existing)\s+(?:customer|client)|\s+an\s+(?:new|existing)\s+(?:customer|client)|\s+id\b|\s+i\'?d\b|\s+\d{7,8}\b|\s+phone\b|\s+phn\b|\s+p/no\b|\s+kes\b|\s+ksh\b|\s+new\b|\s+existing\b|$)')
        patterns.append(r'(?:spin|credit\s+analysis|analysis)\s+(?:request\s+)?(?:for|of)\s+(?P<name>.+?)(?:\s+who\b|\s+applying\b|\s+seeking\b|\s+taking\b|\s+a\s+(?:new|existing)\s+(?:customer|client)|\s+an\s+(?:new|existing)\s+(?:customer|client)|\s+id\b|\s+i\'?d\b|\s+\d{7,8}\b|\s+phone\b|\s+phn\b|\s+p/no\b|\s+kes\b|\s+ksh\b|\s+new\b|\s+existing\b|$)')
    elif request_type == 'spin':
        patterns.append(r'share\s+spin\s+for\s*(?P<name>.+?)(?:\s+he\b|\s+she\b|\s+they\b|\s+id\b|\s+i\'?d\b|\s+phn\b|\s+p/no\b|\s+phone\b|\s+requesting\b|\s+new\b|\s+existing\b|$)')
        patterns.append(r'share\s+(?:the\s+)?spin\s+(?P<name>.+?)(?:\s+id\b|\s+i\'?d\b|\s+\d{7,8}\b|\s+phone\b|\s+phn\b|\s+p/no\b|\s+kes\b|\s+ksh\b|\s+new\b|\s+existing\b|$)')
        patterns.append(r'(?:assist|help|do|run|check|process|send|share|need|request(?:ing)?)\s+(?:with\s+|for\s+)?(?:a\s+|the\s+)?spin\s+(?:for|of)?\s*(?P<name>.+?)(?:\s+id\b|\s+i\'?d\b|\s+\d{7,8}\b|\s+phone\b|\s+phn\b|\s+p/no\b|\s+kes\b|\s+ksh\b|\s+new\b|\s+existing\b|$)')
        patterns.append(r'spin\s+(?:request\s+)?(?:for|of)\s+(?P<name>.+?)(?:\s+id\b|\s+i\'?d\b|\s+\d{7,8}\b|\s+phone\b|\s+phn\b|\s+p/no\b|\s+kes\b|\s+ksh\b|\s+new\b|\s+existing\b|$)')
    elif request_type == 'crb':
        patterns.append(r'share\s+crb\s+report\s+(?:of|for)?\s*(?P<name>.+?)(?:\s+he\s+is|\s+she\s+is|\s+they\s+are|\s+requesting|\s+id\b|\s+phone\b|$)')
        patterns.append(r'(?:assist|help|do|run|check|process|send|share|need|request(?:ing)?)\s+(?:with\s+|for\s+)?(?:a\s+|the\s+)?crb(?:\s+report)?\s+(?:for|of)?\s*(?P<name>.+?)(?:\s+he\s+is|\s+she\s+is|\s+they\s+are|\s+requesting|\s+id\b|\s+\d{7,8}\b|\s+phone\b|\s+phn\b|\s+kes\b|\s+ksh\b|$)')
    label_match = re.search(
        rf'(?is)(?:^|\b)name\s*[-:;]\s*(?P<name>.+?)(?=\s+\b{FIELD_LABEL_PATTERN}\s*[-:;]|\n|$)',
        text,
    )
    if label_match:
        return clean_name(label_match.group('name'))
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
    for match in re.finditer(r'(?i)\b(?:id|id\s+number|id\s+no|i\.?d|i?d|i\'d|i\'d\s+no)\s*(?:number|no)?\s*[-:.]?\s*([0-9][0-9\-\s]{5,20})', text):
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
    phone_contexts = re.finditer(
        rf'(?is)\b(?:phone(?: number| no)?|phn(?:\s+no)?|phno(?:\s+no)?|p/no|p\s*no|tel|mobile|no|number)\s*[-:.]?\s*([+\d][\d\s/\-]{{6,40}}?)(?=\s+\b{FIELD_LABEL_PATTERN}\s*[-:;]|\n|$)',
        text,
    )
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
    match = re.search(r'(?:requesting|seeking|applying|taking)\s+(?:for\s+)?(?:a\s+)?(?P<product>[A-Za-z ]{2,40}?)\s+loan\b', text, re.I)
    if match:
        return match.group('product').strip().title()
    return ''


def extract_amount(text: str) -> Decimal | None:
    patterns = [
        r'(?i)\bamount\s*[-:.]?\s*(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?k?)\b',
        r'(?i)(?:kshs?|kes)\s*\.?\s*(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)',
        r'(?i)requesting\s+(?:for\s+)?(?:a\s+)?(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?k?)\b',
        r'(?i)(?:loan\s+of|amount\s+of)\s+(?:kshs?|kes)?\s*\.?\s*(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?k?)\b',
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
    match = re.search(r'(?i)\b(?:to\s+pay\s+(?:with\s+)?|repay\s+in\s+|with\s+a\s+tenor\s+of\s+|tenor\s+of\s+|in\s+|for\s+|period\s*[-:.]?|du?aration\s*[-:.]?|duration\s*[-:.]?)?(\d+\s*(?:weeks?|wks?|months?|yrs?|years?))\b', text)
    if match:
        return re.sub(r'\s+', ' ', match.group(1)).strip()
    return ''


def extract_code(text: str) -> str:
    match = re.search(r'(?i)\bcode\s*[-:.]?\s*([A-Za-z0-9/\-]+)', text)
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
    request_dt = parsed.request_datetime or timezone.now()
    year = timezone.localtime(request_dt).year if timezone.is_aware(request_dt) else request_dt.year
    parsed_fields_value = dict(parsed.parsed_fields or {})
    parsed_fields_value['branch'] = parsed_fields_value.get('branch') or spin_default_branch(group_config)
    with transaction.atomic():
        sequence, _ = SpinRequestSequence.objects.select_for_update().get_or_create(
            group_id=str(group_config.group_id),
            year=year,
            defaults={'next_number': 1},
        )
        number = sequence.next_number
        sequence.next_number = number + 1
        sequence.save(update_fields=['next_number', 'updated_at'])
        return SpinCreditRequest.objects.create(
            group_id=group_config.group_id,
            sheet_id=getattr(group_config, 'sheet_id', '') or '',
            sheet_name=getattr(group_config, 'sheet_name', '') or '',
            public_sequence_year=year,
            public_sequence_number=number,
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
            parsed_fields=parsed_fields_value,
            missing_fields=parsed.missing_fields,
            import_status=import_status,
        )


def append_spin_requests_to_sheet(group_config, records: list[SpinCreditRequest], sheet_name: str | None = None) -> dict[str, Any]:
    if not records:
        return {'success': True, 'row_numbers': []}
    target_sheet_name = sheet_name or group_config.sheet_name
    service = get_sheets_service(
        sheet_id=group_config.sheet_id,
        sheet_name=target_sheet_name,
        sheet_schema=None,
    )
    if not service.is_available():
        return {'success': False, 'error': 'Google Sheets service unavailable.', 'sheet_name': target_sheet_name}
    workflow = getattr(group_config, 'workflow', None) or {}
    try:
        header_row_number = configured_header_row(workflow)
        headers = [str(value or '').strip() for value in service._sheet.row_values(header_row_number)]
    except Exception as exc:
        logger.error('Failed to read SPIN header row: %s', exc, exc_info=True)
        return {'success': False, 'error': str(exc), 'sheet_name': target_sheet_name}
    if not headers:
        return {'success': False, 'error': 'Header row is empty or unavailable.', 'sheet_name': target_sheet_name}
    field_headers = configured_field_headers(workflow)
    rows = []
    for record in records:
        row = ['' for _ in headers]
        values = sheet_values_for(record)
        missing_headers = [
            header for field, header in field_headers.items()
            if header and header not in headers and values.get(field, '') not in ('', None) and field not in OPTIONAL_SHEET_FIELDS
        ]
        if missing_headers:
            return {'success': False, 'error': 'Missing required column(s): ' + ', '.join(missing_headers[:8]), 'sheet_name': target_sheet_name}
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
        row_numbers = row_numbers_from_append_response(response, len(rows))
        apply_spin_sheet_formatting(service, headers, field_headers, records, row_numbers)
        return {'success': True, 'row_numbers': row_numbers, 'sheet_name': target_sheet_name}
    except Exception as exc:
        logger.error('Failed to append SPIN request rows: %s', exc, exc_info=True)
        return {'success': False, 'error': str(exc), 'sheet_name': target_sheet_name}


def sheet_values_for(record: SpinCreditRequest) -> dict[str, Any]:
    parsed = record.parsed_fields or {}
    return {
        'request_id': spin_request_id(record),
        'request_datetime': format_sheet_datetime(record.request_datetime),
        'request_month': format_sheet_month(record.request_datetime),
        'branch': parsed.get('branch') or record.source_chat,
        'requested_by': record.requested_by,
        'credit_analyst_name': (record.parsed_fields or {}).get('credit_analyst_name', ''),
        'request_type': REQUEST_TYPE_LABELS.get(record.request_type, record.request_type),
        'customer_name': record.customer_name,
        'national_id': record.national_id,
        'raw_id_text': record.raw_id_text,
        'primary_phone': record.primary_phone,
        'secondary_phone': record.secondary_phone,
        'customer_type': record.customer_type,
        'loan_product': record.loan_product,
        'requested_amount': float(record.requested_amount) if record.requested_amount is not None else '',
        'tenor': record.tenor,
        'business_notes': record.business_notes,
        'code': sheet_text(record.code),
        'attachment_names': '\n'.join(record.attachment_names or []),
        'media_urls': sheet_media_urls(parsed.get('media_urls', '')),
        'raw_message': record.raw_message,
        'source_chat': record.source_chat,
        'source_filename': record.source_filename,
        'source_message_hash': record.source_message_hash,
        'parse_status': record.import_status.replace('_', ' ').title(),
        'missing_fields': ', '.join(record.missing_fields or []),
        'analysis_status': parsed.get('analysis_status', ''),
        'analyst_response': parsed.get('analyst_response', ''),
    }


def spin_request_id(record: SpinCreditRequest) -> str:
    if record.public_sequence_year and record.public_sequence_number:
        return f"SPIN-{record.public_sequence_year}-{record.public_sequence_number:04d}"
    if record.pk:
        return f"SPIN-{str(record.pk).split('-')[0].upper()}"
    return 'SPIN'


def sheet_text(value: Any) -> str:
    text = str(value or '').strip()
    return f"'{text}" if text else ''


def sheet_media_urls(value: Any) -> str:
    return '\n'.join(media_url_list(value))


def apply_spin_sheet_formatting(
    service,
    headers: list[str],
    field_headers: dict[str, str],
    records: list[SpinCreditRequest] | None = None,
    row_numbers: list[int | None] | None = None,
) -> None:
    sheet = service._sheet
    try:
        code_header = field_headers.get('code')
        if code_header in headers:
            col = headers.index(code_header) + 1
            if hasattr(sheet, 'format'):
                sheet.format(f'{column_letter(col)}:{column_letter(col)}', {'numberFormat': {'type': 'TEXT'}})
        media_header = field_headers.get('media_urls')
        if media_header in headers and records and row_numbers:
            apply_media_url_rich_links(service, headers.index(media_header) + 1, records, row_numbers)
        analysis_header = field_headers.get('analysis_status')
        if analysis_header in headers:
            apply_analysis_status_conditional_formatting(service, headers.index(analysis_header) + 1, len(headers))
    except Exception as exc:
        logger.warning('Failed to apply SPIN sheet formatting: %s', exc, exc_info=True)


def apply_media_url_rich_links(
    service,
    media_col: int,
    records: list[SpinCreditRequest],
    row_numbers: list[int | None],
) -> None:
    sheet = service._sheet
    api = getattr(service, '_sheets_api_service', None)
    if not (api and getattr(service, '_api_initialized', False) is True and isinstance(getattr(sheet, 'id', None), int)):
        return
    requests = []
    for index, record in enumerate(records):
        row_number = row_numbers[index] if index < len(row_numbers) else None
        if not row_number:
            continue
        urls = media_url_list((record.parsed_fields or {}).get('media_urls', ''))
        if not urls:
            continue
        text = '\n'.join(urls)
        requests.append({
            'updateCells': {
                'range': {
                    'sheetId': sheet.id,
                    'startRowIndex': row_number - 1,
                    'endRowIndex': row_number,
                    'startColumnIndex': media_col - 1,
                    'endColumnIndex': media_col,
                },
                'rows': [{
                    'values': [{
                        'userEnteredValue': {'stringValue': text},
                        'textFormatRuns': media_url_text_format_runs(urls),
                    }],
                }],
                'fields': 'userEnteredValue,textFormatRuns',
            },
        })
    if requests:
        api.spreadsheets().batchUpdate(
            spreadsheetId=getattr(service, '_sheet_id', ''),
            body={'requests': requests},
        ).execute()


def apply_rich_links_to_cell(service, col_index: int, row_number: int, value: Any) -> None:
    sheet = service._sheet
    api = getattr(service, '_sheets_api_service', None)
    if not (api and getattr(service, '_api_initialized', False) is True and isinstance(getattr(sheet, 'id', None), int)):
        return
    text = str(value or '')
    runs = hyperlink_text_format_runs(text)
    if not runs:
        return
    api.spreadsheets().batchUpdate(
        spreadsheetId=getattr(service, '_sheet_id', ''),
        body={'requests': [{
            'updateCells': {
                'range': {
                    'sheetId': sheet.id,
                    'startRowIndex': row_number - 1,
                    'endRowIndex': row_number,
                    'startColumnIndex': col_index - 1,
                    'endColumnIndex': col_index,
                },
                'rows': [{
                    'values': [{
                        'userEnteredValue': {'stringValue': text},
                        'textFormatRuns': runs,
                    }],
                }],
                'fields': 'userEnteredValue,textFormatRuns',
            },
        }]},
    ).execute()


def media_url_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        candidates = [str(item or '').strip() for item in value]
    else:
        candidates = [str(item or '').strip() for item in str(value or '').replace(',', '\n').splitlines()]
    return [url for url in candidates if url]


def media_url_text_format_runs(urls: list[str]) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    offset = 0
    for index, url in enumerate(urls):
        runs.append({'startIndex': offset, 'format': {'link': {'uri': url}}})
        offset += len(url)
        if index < len(urls) - 1:
            runs.append({'startIndex': offset, 'format': {}})
            offset += 1
    return runs


def hyperlink_text_format_runs(text: str) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    for match in re.finditer(r'https?://[^\s,]+', text or ''):
        runs.append({'startIndex': match.start(), 'format': {'link': {'uri': match.group(0)}}})
        if match.end() < len(text or ''):
            runs.append({'startIndex': match.end(), 'format': {}})
    return runs


def apply_analysis_status_conditional_formatting(service, status_col: int, width: int) -> None:
    sheet = service._sheet
    api = getattr(service, '_sheets_api_service', None)
    if api and getattr(service, '_api_initialized', False) is True and isinstance(getattr(sheet, 'id', None), int):
        requests = []
        for status, colour in SPIN_ANALYSIS_STATUS_COLOURS.items():
            requests.append({
                'addConditionalFormatRule': {
                    'rule': {
                        'ranges': [{
                            'sheetId': sheet.id,
                            'startRowIndex': 1,
                            'startColumnIndex': 0,
                            'endColumnIndex': width,
                        }],
                        'booleanRule': {
                            'condition': {
                                'type': 'CUSTOM_FORMULA',
                                'values': [{'userEnteredValue': f'=LOWER(${column_letter(status_col)}2)="{status}"'}],
                            },
                            'format': {'backgroundColor': hex_to_rgb(status_colours_to_hex(status))},
                        },
                    },
                    'index': 0,
                },
            })
        api.spreadsheets().batchUpdate(
            spreadsheetId=getattr(service, '_sheet_id', ''),
            body={'requests': requests},
        ).execute()
        return
    if not hasattr(sheet, 'conditional_format'):
        return
    status_letter = column_letter(status_col)
    row_range = f'A2:{column_letter(width)}'
    for status, colour in SPIN_ANALYSIS_STATUS_COLOURS.items():
        sheet.conditional_format(
            row_range,
            {
                'type': 'CUSTOM_FORMULA',
                'formula': [f'=LOWER(${status_letter}2)="{status}"'],
                'format': {'backgroundColor': hex_to_rgb(colour)},
            },
        )


def status_colours_to_hex(status: str) -> str:
    return SPIN_ANALYSIS_STATUS_COLOURS.get(status, '#ffffff')


def hex_to_rgb(value: str) -> dict[str, float]:
    text = value.strip().lstrip('#')
    return {
        'red': int(text[0:2], 16) / 255,
        'green': int(text[2:4], 16) / 255,
        'blue': int(text[4:6], 16) / 255,
    }


def spin_branch_choices(group_config) -> list[str]:
    workflow = getattr(group_config, 'workflow', None) or {}
    return workflow_branches(workflow, default=global_branch_choices())


def spin_default_branch(group_config) -> str:
    workflow = getattr(group_config, 'workflow', None) or {}
    return workflow_default_branch(workflow, fallback=getattr(group_config, 'display_name', '') or '')


def validate_spin_branch(group_config, branch: str) -> str:
    workflow = getattr(group_config, 'workflow', None) or {}
    if not workflow_branches(workflow, default=[]):
        return str(branch or spin_default_branch(group_config)).strip()
    return validate_workflow_branch(branch, workflow)


def column_letter(index: int) -> str:
    result = ''
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result or 'A'


def configured_field_headers(workflow: dict) -> dict[str, str]:
    configured = dict(DEFAULT_FIELD_HEADERS)
    configured.update((workflow or {}).get('field_headers') or {})
    return configured


def configured_header_row(workflow: dict) -> int:
    try:
        return max(int((workflow or {}).get('header_row') or 1), 1)
    except (TypeError, ValueError):
        return 1


def configured_spin_batch_sheet_name(workflow: dict, fallback_sheet_name: str = '') -> str:
    value = str(
        (workflow or {}).get('legacy_batch_sheet_name')
        or (workflow or {}).get('batch_sheet_name')
        or ''
    ).strip()
    return value or 'SPIN Legacy Batch'

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


def format_sheet_month(value) -> str:
    if not value:
        return ''
    try:
        local_value = timezone.localtime(value)
        return local_value.strftime('%b-%Y')
    except Exception:
        return ''

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
            'credit_analyst_name': (record.parsed_fields or {}).get('credit_analyst_name', ''),
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
    if str(payload.get('launcher', '')).strip() == 'jbl_apps' and group_id:
        return {'group_id': group_id, 'token': ''}
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
    if not errors:
        try:
            cleaned['branch'] = validate_spin_branch(group_config, cleaned.get('branch', ''))
        except ValueError as exc:
            errors.append(str(exc))
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
    parsed.parsed_fields['branch'] = cleaned.get('branch', '')
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
        'credit_analyst_name': (record.parsed_fields or {}).get('credit_analyst_name', ''),
        'request_type': REQUEST_TYPE_LABELS.get(record.request_type, record.request_type),
        'customer_name': record.customer_name,
        'national_id': record.national_id,
        'primary_phone': record.primary_phone,
        'files_stored': len(media_links),
        'media_urls': media_links,
    }


def spin_review_fields_for(record: SpinCreditRequest) -> dict[str, Any]:
    parsed = record.parsed_fields or {}
    return {
        'request_type': record.request_type,
        'branch': parsed.get('branch') or '',
        'customer_name': record.customer_name,
        'national_id': record.national_id,
        'primary_phone': record.primary_phone,
        'secondary_phone': record.secondary_phone,
        'customer_type': record.customer_type,
        'loan_product': record.loan_product,
        'requested_amount': str(record.requested_amount or ''),
        'tenor': record.tenor,
        'business_notes': record.business_notes,
        'code': record.code,
    }


def normalize_spin_review_fields(group_config, record: SpinCreditRequest, fields: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    merged = spin_review_fields_for(record)
    incoming = fields or {}
    for key in SPIN_REVIEW_EDITABLE_FIELDS:
        if key in incoming:
            merged[key] = incoming.get(key)

    errors: list[str] = []
    request_type = normalize_spin_request_type(str(merged.get('request_type') or ''))
    if request_type not in SPIN_FORM_REQUEST_TYPES:
        errors.append('Request Type must be SPIN/CRB, SPIN, or CRB.')

    national_id = re.sub(r'\D', '', str(merged.get('national_id') or ''))
    if national_id and not re.fullmatch(r'\d{7,8}', national_id):
        errors.append('National ID must be 7 or 8 digits.')

    primary_phone_source = str(merged.get('primary_phone') or '').strip()
    primary_phone = normalize_phone(primary_phone_source) if primary_phone_source else ''
    if primary_phone_source and not primary_phone:
        errors.append('Primary Phone must be a valid Kenyan number, for example 254712345678.')

    secondary_phone_source = str(merged.get('secondary_phone') or '').strip()
    secondary_phone = normalize_phone(secondary_phone_source) if secondary_phone_source else ''
    if secondary_phone_source and not secondary_phone:
        errors.append('Secondary Phone must be a valid Kenyan number or left blank.')

    amount_source = str(merged.get('requested_amount') or '').strip()
    requested_amount = parse_amount(amount_source) if amount_source else None
    if amount_source and (requested_amount is None or requested_amount <= Decimal('0')):
        errors.append('Requested Amount must be a number greater than 0.')

    customer_type = str(merged.get('customer_type') or '').strip().title()
    if customer_type and customer_type not in {'New', 'Existing'}:
        errors.append('Customer Type must be New, Existing, or blank.')

    branch = str(merged.get('branch') or '').strip()
    try:
        branch = validate_spin_branch(group_config, branch) if branch else spin_default_branch(group_config)
    except ValueError as exc:
        errors.append(str(exc))

    return {
        'request_type': request_type,
        'branch': branch,
        'customer_name': clean_name(str(merged.get('customer_name') or '')),
        'national_id': national_id,
        'raw_id_text': national_id,
        'primary_phone': primary_phone,
        'secondary_phone': secondary_phone,
        'customer_type': customer_type,
        'loan_product': str(merged.get('loan_product') or '').strip().title(),
        'requested_amount': requested_amount,
        'tenor': re.sub(r'\s+', ' ', str(merged.get('tenor') or '')).strip(),
        'business_notes': str(merged.get('business_notes') or '')[:1000],
        'code': str(merged.get('code') or '')[:255],
    }, errors


def update_spin_review_request(group_config, record: SpinCreditRequest, fields: dict[str, Any]) -> dict[str, Any]:
    if str(record.group_id) != str(group_config.group_id):
        return {'success': False, 'status': 'not_found', 'message': 'Request not found.'}
    if record.import_status == 'completed':
        return {
            'success': False,
            'status': 'completed',
            'message': 'Completed requests cannot be edited from the review workflow.',
        }

    cleaned, errors = normalize_spin_review_fields(group_config, record, fields)
    if errors:
        return {
            'success': False,
            'status': 'validation_error',
            'message': 'Fix the highlighted fields and try again.',
            'errors': errors,
        }

    parsed = ParsedSpinRequest(
        request_type=cleaned['request_type'],
        customer_name=cleaned['customer_name'],
        national_id=cleaned['national_id'],
        raw_id_text=cleaned['raw_id_text'],
        primary_phone=cleaned['primary_phone'],
        secondary_phone=cleaned['secondary_phone'],
        customer_type=cleaned['customer_type'],
        loan_product=cleaned['loan_product'],
        requested_amount=cleaned['requested_amount'],
        tenor=cleaned['tenor'],
        business_notes=cleaned['business_notes'],
        code=cleaned['code'],
    )
    missing_fields = missing_fields_for(parsed)

    existing_parsed = dict(record.parsed_fields or {})
    existing_parsed.update({
        'request_type': cleaned['request_type'],
        'branch': cleaned['branch'],
        'customer_name': cleaned['customer_name'],
        'national_id': cleaned['national_id'],
        'raw_id_text': cleaned['raw_id_text'],
        'primary_phone': cleaned['primary_phone'],
        'secondary_phone': cleaned['secondary_phone'],
        'customer_type': cleaned['customer_type'],
        'loan_product': cleaned['loan_product'],
        'requested_amount': str(cleaned['requested_amount'] or ''),
        'tenor': cleaned['tenor'],
        'business_notes': cleaned['business_notes'],
        'code': cleaned['code'],
    })

    record.request_type = cleaned['request_type']
    record.customer_name = cleaned['customer_name']
    record.national_id = cleaned['national_id']
    record.raw_id_text = cleaned['raw_id_text']
    record.primary_phone = cleaned['primary_phone']
    record.secondary_phone = cleaned['secondary_phone']
    record.customer_type = cleaned['customer_type']
    record.loan_product = cleaned['loan_product']
    record.requested_amount = cleaned['requested_amount']
    record.tenor = cleaned['tenor']
    record.business_notes = cleaned['business_notes']
    record.code = cleaned['code']
    record.parsed_fields = existing_parsed
    record.missing_fields = missing_fields
    record.import_status = 'imported' if not missing_fields else 'review_needed'
    record.sync_error = ''
    record.save(update_fields=[
        'request_type',
        'customer_name',
        'national_id',
        'raw_id_text',
        'primary_phone',
        'secondary_phone',
        'customer_type',
        'loan_product',
        'requested_amount',
        'tenor',
        'business_notes',
        'code',
        'parsed_fields',
        'missing_fields',
        'import_status',
        'sync_error',
        'updated_at',
    ])

    sheet_synced = False
    if record.row_number:
        values = sheet_values_for(record)
        sheet_synced = update_spin_request_in_sheet(
            group_config,
            record,
            {field: values.get(field, '') for field in SPIN_REVIEW_SHEET_FIELDS},
        )
    else:
        sync_result = append_spin_requests_to_sheet(group_config, [record])
        sheet_synced = bool(sync_result.get('success'))
        if sheet_synced:
            row_numbers = sync_result.get('row_numbers') or []
            record.row_number = row_numbers[0] if row_numbers else None
            record.sheet_id = group_config.sheet_id or ''
            record.sheet_name = sync_result.get('sheet_name') or group_config.sheet_name or ''
            record.save(update_fields=['row_number', 'sheet_id', 'sheet_name', 'updated_at'])

    if not sheet_synced:
        record.sync_error = 'Review saved in Django, but Google Sheets could not be updated.'
        record.save(update_fields=['sync_error', 'updated_at'])

    return {
        'success': True,
        'status': record.import_status,
        'message': 'SPIN request review saved.',
        'request_id': spin_request_id(record),
        'record_id': str(record.id),
        'missing_fields': record.missing_fields,
        'sheet_synced': sheet_synced,
    }


def batch_review_item_summary(item: SpinBatchReviewItem) -> dict[str, Any]:
    fields = item.candidate_fields or {}
    return {
        'id': str(item.id),
        'category': item.category,
        'reason': item.reason,
        'source_sender': item.source_sender,
        'source_received_at': format_sheet_datetime(item.source_received_at),
        'raw_message': item.raw_message,
        'detected_fields': item.detected_fields or {},
        'fields': {
            'request_type': fields.get('request_type') or 'spin_crb',
            'branch': fields.get('branch') or '',
            'customer_name': fields.get('customer_name') or '',
            'national_id': fields.get('national_id') or '',
            'primary_phone': fields.get('primary_phone') or '',
            'secondary_phone': fields.get('secondary_phone') or '',
            'customer_type': fields.get('customer_type') or '',
            'loan_product': fields.get('loan_product') or '',
            'requested_amount': fields.get('requested_amount') or '',
            'tenor': fields.get('tenor') or '',
            'business_notes': fields.get('business_notes') or '',
            'code': fields.get('code') or '',
        },
    }


def resolve_spin_batch_review_item(
    group_config,
    item: SpinBatchReviewItem,
    fields: dict[str, Any],
    reviewed_by: str = '',
    action: str = 'resolve',
) -> dict[str, Any]:
    """Resolve a retained batch candidate into a normal SPIN request or reject it."""
    if str(item.group_id) != str(group_config.group_id):
        return {'success': False, 'status': 'not_found', 'message': 'Batch review item not found.'}
    if item.status != 'pending':
        return {'success': False, 'status': item.status, 'message': 'This batch review item has already been handled.'}

    if action == 'reject':
        item.status = 'rejected'
        item.reviewed_by = reviewed_by
        item.reviewed_at = timezone.now()
        item.resolution_fields = {'action': 'rejected'}
        item.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'resolution_fields', 'updated_at'])
        return {'success': True, 'status': 'rejected', 'message': 'Message marked as not a SPIN request.'}

    candidate = item.candidate_fields or {}
    draft = SpinCreditRequest(
        group_id=item.group_id,
        request_type=str(candidate.get('request_type') or 'spin_crb'),
        customer_name=str(candidate.get('customer_name') or ''),
        national_id=str(candidate.get('national_id') or ''),
        primary_phone=str(candidate.get('primary_phone') or ''),
        secondary_phone=str(candidate.get('secondary_phone') or ''),
        customer_type=str(candidate.get('customer_type') or ''),
        loan_product=str(candidate.get('loan_product') or ''),
        requested_amount=parse_amount(str(candidate.get('requested_amount') or '')),
        tenor=str(candidate.get('tenor') or ''),
        business_notes=str(candidate.get('business_notes') or ''),
        code=str(candidate.get('code') or ''),
        parsed_fields={'branch': str(candidate.get('branch') or '')},
    )
    cleaned, errors = normalize_spin_review_fields(group_config, draft, fields)
    if errors:
        return {'success': False, 'status': 'validation_error', 'message': 'Fix the highlighted fields and try again.', 'errors': errors}

    parsed = ParsedSpinRequest(
        request_type=cleaned['request_type'],
        request_datetime=item.source_received_at,
        requested_by=item.source_sender,
        customer_name=cleaned['customer_name'],
        national_id=cleaned['national_id'],
        raw_id_text=cleaned['raw_id_text'],
        primary_phone=cleaned['primary_phone'],
        secondary_phone=cleaned['secondary_phone'],
        customer_type=cleaned['customer_type'],
        loan_product=cleaned['loan_product'],
        requested_amount=cleaned['requested_amount'],
        tenor=cleaned['tenor'],
        business_notes=cleaned['business_notes'],
        code=cleaned['code'],
        raw_message=item.raw_message,
        source_filename=item.source_filename,
        source_message_index=item.source_message_index,
        source_message_hash=item.source_message_hash,
    )
    parsed.parsed_fields = parsed_fields(parsed)
    parsed.parsed_fields['branch'] = cleaned['branch']
    parsed.missing_fields = missing_fields_for(parsed)
    if parsed.missing_fields:
        return {
            'success': False,
            'status': 'validation_error',
            'message': 'Complete the required SPIN request fields before saving.',
            'missing_fields': parsed.missing_fields,
        }

    record = SpinCreditRequest.objects.filter(
        group_id=str(group_config.group_id), source_message_hash=item.source_message_hash,
    ).first()
    if not record:
        try:
            record = save_spin_request(group_config, parsed, item.telegram_message_id, import_status='imported')
        except IntegrityError:
            record = SpinCreditRequest.objects.filter(
                group_id=str(group_config.group_id), source_message_hash=item.source_message_hash,
            ).first()
    if not record:
        return {'success': False, 'status': 'failed', 'message': 'The request could not be created. Try again.'}

    sheet_synced = bool(record.row_number)
    if not sheet_synced:
        target_sheet_name = configured_spin_batch_sheet_name(
            getattr(group_config, 'workflow', None) or {}, group_config.sheet_name,
        )
        sync_result = append_spin_requests_to_sheet(group_config, [record], sheet_name=target_sheet_name)
        sheet_synced = bool(sync_result.get('success'))
        if sheet_synced:
            row_numbers = sync_result.get('row_numbers') or []
            record.row_number = row_numbers[0] if row_numbers else None
            record.sheet_id = group_config.sheet_id or ''
            record.sheet_name = sync_result.get('sheet_name') or target_sheet_name or ''
            record.import_status = 'imported'
            record.sync_error = ''
            record.save(update_fields=['row_number', 'sheet_id', 'sheet_name', 'import_status', 'sync_error', 'updated_at'])
        else:
            record.import_status = 'failed'
            record.sync_error = (sync_result.get('error') or 'Google Sheets append failed')
            record.save(update_fields=['import_status', 'sync_error', 'updated_at'])
    if not sheet_synced:
        return {'success': False, 'status': 'sheet_sync_failed', 'message': 'The request was retained, but the Sheet could not be updated. Try again.'}

    item.status = 'resolved'
    item.resolved_request = record
    item.resolution_fields = {
        **cleaned,
        'requested_amount': str(cleaned['requested_amount'] or ''),
    }
    item.reviewed_by = reviewed_by
    item.reviewed_at = timezone.now()
    item.save(update_fields=['status', 'resolved_request', 'resolution_fields', 'reviewed_by', 'reviewed_at', 'updated_at'])
    return {
        'success': True,
        'status': 'resolved',
        'message': 'Batch candidate saved as a SPIN request.',
        'request_id': spin_request_id(record),
        'record_id': str(record.id),
        'sheet_synced': True,
    }


def normalize_spin_request_type(value: str) -> str:
    val = str(value or '').strip().lower()
    if val in {'spin_crb', 'spin/crb', 'spin-crb', 'both'}:
        return 'spin_crb'
    if val in {'spin', 'only_spin'}:
        return 'spin'
    if val in {'crb', 'crb_report', 'crb report', 'only_crb'}:
        return 'crb'
    return val


def validate_spin_form_fields(fields: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    data = {key: str(value or '').strip() for key, value in (fields or {}).items()}
    request_type = normalize_spin_request_type(data.get('request_type', ''))
    errors = []
    if request_type not in SPIN_FORM_REQUEST_TYPES:
        errors.append('Request Type must be SPIN/CRB, SPIN, or CRB.')

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
        'branch': data.get('branch', ''),
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


def is_user_spin_analyst(user_payload: dict) -> bool:
    if not user_payload:
        return False
    spin_analysts = getattr(settings, 'SPIN_ANALYSTS', [])
    if not spin_analysts or '*' in spin_analysts:
        return True
    username = str(user_payload.get('username') or '').strip().lower()
    user_id = str(user_payload.get('id') or '').strip()
    if username and username in spin_analysts:
        return True
    if user_id and user_id in spin_analysts:
        return True
    return False


def upload_report(group_config, file_obj, file_type: str, sender_name: str, national_id: str) -> str | None:
    if not file_obj:
        return None
    from core.services.order_approval import UploadedFileItem, store_uploaded_files_for_order
    uploaded = store_uploaded_files_for_order(
        group_config=group_config,
        uploaded_files=[UploadedFileItem(file=file_obj, file_type=file_type)],
        sender=sender_name,
        received_at=timezone.now(),
        business_key_value=national_id,
    )
    if uploaded.links:
        return uploaded.links[0]
    return None


def update_spin_request_in_sheet(group_config, record: SpinCreditRequest, updates: dict[str, Any]) -> bool:
    if not record.row_number:
        logger.warning("SPIN request %s has no row_number saved, cannot update sheet.", record.pk)
        return False
    service = get_sheets_service(
        sheet_id=group_config.sheet_id,
        sheet_name=group_config.sheet_name,
        sheet_schema=None,
    )
    if not service.is_available():
        logger.warning("Google Sheets service unavailable for sheet update.")
        return False
    workflow = getattr(group_config, 'workflow', None) or {}
    try:
        header_row_number = configured_header_row(workflow)
        headers = [str(value or '').strip() for value in service._sheet.row_values(header_row_number)]
        field_headers = configured_field_headers(workflow)
        for field, value in updates.items():
            header = field_headers.get(field)
            if header in headers:
                col_index = headers.index(header) + 1
                if field == 'media_urls':
                    value = sheet_media_urls(value)
                service._sheet.update_cell(record.row_number, col_index, value)
                if field in {'media_urls', 'analyst_response'}:
                    apply_rich_links_to_cell(service, col_index, record.row_number, value)
        return True
    except Exception as exc:
        logger.error("Failed to update SPIN request in sheet: %s", exc, exc_info=True)
        return False


def build_spin_launcher_url(group_id: str) -> str:
    """Return a durable group launcher URL for a pinned Telegram message."""
    bot_username = str(getattr(settings, 'TELEGRAM_BOT_USERNAME', '') or '').strip().lstrip('@')
    short_name = str(getattr(settings, 'SPIN_MINI_APP_SHORT_NAME', '') or '').strip().strip('/')
    if not bot_username or not short_name:
        return ''
    payload = {'group_id': str(group_id), 'launcher': 'jbl_apps'}
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(',', ':')).encode('utf-8')
    ).decode('ascii').rstrip('=')
    return f"https://t.me/{bot_username}/{short_name}?startapp={encoded}"
