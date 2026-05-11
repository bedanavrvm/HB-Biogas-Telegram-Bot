"""Parse and apply chat-driven case status updates."""
import re
from dataclasses import dataclass

from django.db.models import Q
from django.utils import timezone

from core.models import CaseUpdate, ParsedMessage
from core.services.group_config import GroupRegistry
from core.services.sheets import get_sheets_service


STATUS_PATTERN = re.compile(r'^\s*(?:@\S+\s+)?status\s*:\s*(.+)$', re.IGNORECASE | re.DOTALL)
CASE_ID_PATTERN = re.compile(r'\b(MSG_[A-Z0-9_]+)\b', re.IGNORECASE)
NOTE_LABEL_PATTERN = re.compile(r'(?:^|[\s\r\n])note\s*:', re.IGNORECASE)

CLOSED_PATTERN = re.compile(
    r'\b(?:resolved?|closed|managed|done|fixed|repaired|sorted|completed?|'
    r'attended|working\s+now|solved)\b',
    re.IGNORECASE,
)
IN_PROGRESS_PATTERN = re.compile(
    r'\b(?:scheduled?|schedul|in\s+progress|ongoing|assigned|visited|'
    r'contacted|awaiting|will\s+visit|to\s+be\s+done)\b',
    re.IGNORECASE,
)
OPEN_PATTERN = re.compile(
    r'\b(?:open|pending|not\s+reachable|unreachable|no\s+answer|'
    r'not\s+solved|not\s+resolved|phone\s+off)\b',
    re.IGNORECASE,
)
HIGH_RISK_PATTERN = re.compile(
    r'\b(?:urgent|escalat(?:e|ed|ion)?|unattended|still\s+pending|'
    r'waiting\s+too\s+long|loan\s+at\s+risk)\b',
    re.IGNORECASE,
)


@dataclass
class ParsedCaseUpdate:
    is_update: bool
    new_status: str = ''
    resolution_text: str = ''
    risk_level: str = ''
    loan_at_risk: str = ''
    error: str = ''


def looks_like_status_update(content: str) -> bool:
    return bool(STATUS_PATTERN.match(content or ''))


def parse_case_update(content: str) -> ParsedCaseUpdate:
    """Parse a strict `Status: ...` staff update."""
    match = STATUS_PATTERN.match(content or '')
    if not match:
        return ParsedCaseUpdate(
            is_update=False,
            error='Status updates must start with "Status:".',
        )

    status_text, note_text = _split_status_and_note(match.group(1))
    body = " ".join(status_text.split()).strip()
    if not body:
        return ParsedCaseUpdate(
            is_update=False,
            error='Status update text cannot be empty.',
        )

    combined_text = " ".join(f"{body} {note_text}".split()).strip()

    if CLOSED_PATTERN.search(body):
        new_status = 'Closed'
    elif IN_PROGRESS_PATTERN.search(body):
        new_status = 'In Progress'
    elif OPEN_PATTERN.search(body) or HIGH_RISK_PATTERN.search(body):
        new_status = 'Open'
    else:
        return ParsedCaseUpdate(
            is_update=False,
            error='Could not recognise the status. Try resolved, scheduled, pending, or not reachable.',
        )

    risk_level = 'High' if HIGH_RISK_PATTERN.search(combined_text) else ''
    loan_at_risk = 'Yes' if re.search(r'\bloan\s+at\s+risk\b', combined_text, re.IGNORECASE) else ''

    return ParsedCaseUpdate(
        is_update=True,
        new_status=new_status,
        resolution_text=note_text or _clean_resolution_text(body, new_status),
        risk_level=risk_level,
        loan_at_risk=loan_at_risk,
    )


def handle_case_status_reply(
    group_id: str,
    reply_to_telegram_message_id: str,
    update_telegram_message_id: str,
    sender: str,
    content: str,
    reply_to_text: str = '',
) -> dict | None:
    """Apply a status update that replies to an original case or bot confirmation."""
    parsed_update = parse_case_update(content)
    if not parsed_update.is_update:
        return {
            'status': 'command',
            'reply_text': parsed_update.error,
        }

    cases = list(_cases_for_reply(group_id, reply_to_telegram_message_id))
    if not cases and reply_to_text:
        case = _case_from_quoted_confirmation(group_id, reply_to_text)
        cases = [case] if case else []
    if not cases and reply_to_text:
        cases = list(_cases_from_quoted_case_text(group_id, reply_to_text))
    if not cases:
        return {
            'status': 'command',
            'reply_text': (
                "I could not find the case linked to that message. "
                "Use /update MSG_ID Status: ... instead."
            ),
        }
    if len(cases) > 1:
        return {
            'status': 'command',
            'reply_text': _format_ambiguous_cases(cases),
        }

    return apply_case_update(
        parsed_message=cases[0],
        parsed_update=parsed_update,
        sender=sender,
        raw_update_text=content,
        update_telegram_message_id=update_telegram_message_id,
        reply_to_telegram_message_id=reply_to_telegram_message_id,
    )


def handle_case_update_command(
    group_id: str,
    message_id: str,
    content: str,
    sender: str = '',
    update_telegram_message_id: str = '',
) -> dict:
    """Apply an explicit `/update MSG_ID Status: ...` command."""
    parsed_update = parse_case_update(content)
    if not parsed_update.is_update:
        return {'status': 'command', 'reply_text': parsed_update.error}

    parsed_message = (
        ParsedMessage.objects
        .filter(group_id=str(group_id), message_id__iexact=message_id)
        .first()
    )
    if not parsed_message:
        return {
            'status': 'command',
            'reply_text': f"Case {message_id} was not found in this group.",
        }

    return apply_case_update(
        parsed_message=parsed_message,
        parsed_update=parsed_update,
        sender=sender,
        raw_update_text=content,
        update_telegram_message_id=update_telegram_message_id,
        reply_to_telegram_message_id='',
    )


def apply_case_update(
    parsed_message: ParsedMessage,
    parsed_update: ParsedCaseUpdate,
    sender: str,
    raw_update_text: str,
    update_telegram_message_id: str,
    reply_to_telegram_message_id: str,
) -> dict:
    """Write a case update to Sheets, then mirror it into Django."""
    now = timezone.now()
    old_status = parsed_message.complaint_status or ''
    date_resolved = now if parsed_update.new_status == 'Closed' else None
    resolution_details = _append_resolution_details(
        existing=parsed_message.resolution_details,
        sender=sender,
        update_text=parsed_update.resolution_text,
        created_at=now,
    )

    update_record = CaseUpdate.objects.create(
        parsed_message=parsed_message,
        group_id=parsed_message.group_id,
        updated_by=sender or '',
        telegram_message_id=update_telegram_message_id or '',
        reply_to_telegram_message_id=reply_to_telegram_message_id or '',
        old_status=old_status,
        new_status=parsed_update.new_status,
        resolution_text=parsed_update.resolution_text,
        risk_level=parsed_update.risk_level,
        loan_at_risk=parsed_update.loan_at_risk,
        raw_update_text=raw_update_text,
        sync_status='pending',
    )

    sheet_success = _update_sheet(parsed_message, parsed_update, resolution_details, date_resolved)
    if not sheet_success:
        update_record.sync_status = 'failed'
        update_record.sync_error = 'Google Sheets update failed'
        update_record.save(update_fields=['sync_status', 'sync_error'])
        return {
            'status': 'command',
            'reply_text': (
                f"Update received for {parsed_message.message_id}, but I could "
                "not update the register. It was not applied."
            ),
        }

    parsed_message.complaint_status = parsed_update.new_status
    parsed_message.resolution_details = resolution_details
    if date_resolved:
        parsed_message.date_resolved = date_resolved
    if parsed_update.risk_level:
        parsed_message.risk_level = parsed_update.risk_level
    if parsed_update.loan_at_risk:
        parsed_message.loan_at_risk = parsed_update.loan_at_risk
    parsed_message.save(update_fields=[
        'complaint_status',
        'resolution_details',
        'date_resolved',
        'risk_level',
        'loan_at_risk',
    ])

    update_record.sync_status = 'success'
    update_record.save(update_fields=['sync_status'])

    return {
        'status': 'command',
        'reply_text': _format_success_reply(
            parsed_message,
            parsed_update,
            date_resolved,
        ),
    }


def _update_sheet(
    parsed_message: ParsedMessage,
    parsed_update: ParsedCaseUpdate,
    resolution_details: str,
    date_resolved,
) -> bool:
    registry = GroupRegistry.get_instance()
    group_config = registry.get_group(str(parsed_message.group_id))
    if not group_config and not parsed_message.sheet_id:
        return False

    updates = {
        'status': parsed_update.new_status,
        'resolution_details': resolution_details,
    }
    if date_resolved:
        updates['date_resolved'] = timezone.localtime(date_resolved).strftime('%d/%m/%Y')
    if parsed_update.risk_level:
        updates['risk_level'] = parsed_update.risk_level
    if parsed_update.loan_at_risk:
        updates['loan_at_risk'] = parsed_update.loan_at_risk

    service = get_sheets_service(
        sheet_id=(group_config.sheet_id if group_config else parsed_message.sheet_id),
        sheet_name=(group_config.sheet_name if group_config else parsed_message.sheet_name),
        sheet_schema=(group_config.sheet_schema_config if group_config else None),
    )
    return service.update_case_row(parsed_message.message_id, updates)


def _cases_for_reply(group_id: str, reply_to_telegram_message_id: str):
    return (
        ParsedMessage.objects
        .filter(group_id=str(group_id))
        .filter(
            Q(processed_message__raw_message__telegram_message_id=reply_to_telegram_message_id)
            | Q(processed_message__raw_message__source_telegram_message_id=reply_to_telegram_message_id)
        )
        .distinct()
        .order_by('processed_message__raw_message__batch_index', 'created_at')
    )


def _case_from_quoted_confirmation(group_id: str, reply_to_text: str):
    match = CASE_ID_PATTERN.search(reply_to_text or '')
    if not match:
        return None
    return (
        ParsedMessage.objects
        .filter(group_id=str(group_id), message_id__iexact=match.group(1))
        .first()
    )


def _cases_from_quoted_case_text(group_id: str, reply_to_text: str):
    """
    Recover a reply-to-original-case update when the stored Telegram link is missing.

    This can happen for older rows that were synced from Sheets after submission.
    The quoted original message usually still contains the customer identifiers, so
    use the same complaint parser and match by the strongest available fields.
    """
    from core.services.parser import parse_message

    parsed = parse_message(reply_to_text or '', sender='')
    if not (parsed.customer_phone or parsed.customer_id or parsed.customer_name):
        return ParsedMessage.objects.none()

    base = ParsedMessage.objects.filter(group_id=str(group_id))
    phone = _digits(parsed.customer_phone)
    customer_id = (parsed.customer_id or '').strip()
    customer_name = (parsed.customer_name or '').strip()

    if phone and customer_id:
        matches = _filter_by_phone(base.filter(customer_id__iexact=customer_id), phone)
        if matches.exists():
            return matches

    if customer_id:
        matches = base.filter(customer_id__iexact=customer_id)
        if matches.exists():
            return matches.order_by('-created_at')

    if phone:
        matches = _filter_by_phone(base, phone)
        if matches.exists():
            return matches

    if customer_name:
        return base.filter(customer_name__iexact=customer_name).order_by('-created_at')

    return ParsedMessage.objects.none()


def _filter_by_phone(queryset, phone: str):
    """Match phone fields with or without punctuation and +254/0 variants."""
    variants = {phone}
    if phone.startswith('0') and len(phone) == 10:
        variants.add('254' + phone[1:])
        variants.add('+254' + phone[1:])
    elif phone.startswith('254') and len(phone) == 12:
        variants.add('0' + phone[3:])
        variants.add('+' + phone)

    query = Q()
    for variant in variants:
        query |= Q(customer_phone__icontains=variant)
    return queryset.filter(query).order_by('-created_at')


def _digits(value: str) -> str:
    return re.sub(r'\D', '', value or '')


def _split_status_and_note(value: str) -> tuple[str, str]:
    """Split `Status: resolved` from an optional following `NOTE: details`."""
    value = str(value or '').strip()
    match = NOTE_LABEL_PATTERN.search(value)
    if not match:
        return value, ''

    status_text = value[:match.start()].strip(' \t\r\n-:;')
    note_text = value[match.end():].strip(' \t\r\n-:;')
    note_text = " ".join(note_text.split())
    return status_text, note_text


def _clean_resolution_text(body: str, new_status: str) -> str:
    text = body.strip()
    if new_status == 'Closed':
        text = re.sub(
            r'^(?:resolved?|closed|managed|done|fixed|repaired|sorted|completed?|'
            r'attended|solved)\b\s*[:;\-,]?\s*',
            '',
            text,
            flags=re.IGNORECASE,
        ).strip()
    return text or body.strip()


def _append_resolution_details(
    existing: str,
    sender: str,
    update_text: str,
    created_at,
) -> str:
    local_time = timezone.localtime(created_at).strftime('%d/%m/%Y %H:%M')
    actor = sender or 'Unknown'
    entry = f"[{local_time} - {actor}] {update_text}".strip()
    if existing and existing.strip():
        return f"{existing.strip()}\n{entry}"
    return entry


def _format_success_reply(
    parsed_message: ParsedMessage,
    parsed_update: ParsedCaseUpdate,
    date_resolved,
) -> str:
    lines = [
        "OK. Case updated.",
        f"Case: {parsed_message.message_id}",
        (
            f"Customer: {parsed_message.customer_name or 'Unknown'}"
            f" | {parsed_message.customer_phone or 'no phone'}"
        ),
        f"Status: {parsed_update.new_status}",
    ]
    if parsed_update.resolution_text:
        lines.append(f"Resolution: {parsed_update.resolution_text}")
    if date_resolved:
        lines.append(
            f"Date resolved: {timezone.localtime(date_resolved).strftime('%d/%m/%Y')}"
        )
    return "\n".join(lines)


def _format_ambiguous_cases(cases: list[ParsedMessage]) -> str:
    lines = [
        "That message created more than one case. Use /update with the case ID:",
    ]
    for case in cases[:10]:
        lines.append(
            f"- {case.message_id}: {case.customer_name or 'Unknown'} | "
            f"{case.customer_phone or 'no phone'}"
        )
    lines.append("/update MSG_ID Status: resolved - details")
    return "\n".join(lines)
