"""Parse and apply chat-driven case status updates."""
import hashlib
import re
from dataclasses import dataclass

from django.db import transaction
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
    telegram_user: dict | None = None,
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

    actor, authorization_error = _authorized_telegram_actor(group_id, telegram_user, cases[0], parsed_update)
    if authorization_error:
        return {'status': 'command', 'reply_text': authorization_error}

    return apply_case_update(
        parsed_message=cases[0],
        parsed_update=parsed_update,
        sender=sender,
        raw_update_text=content,
        update_telegram_message_id=update_telegram_message_id,
        reply_to_telegram_message_id=reply_to_telegram_message_id,
        actor=actor,
    )


def handle_case_update_command(
    group_id: str,
    message_id: str,
    content: str,
    sender: str = '',
    update_telegram_message_id: str = '',
    telegram_user: dict | None = None,
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

    actor, authorization_error = _authorized_telegram_actor(group_id, telegram_user, parsed_message, parsed_update)
    if authorization_error:
        return {'status': 'command', 'reply_text': authorization_error}

    return apply_case_update(
        parsed_message=parsed_message,
        parsed_update=parsed_update,
        sender=sender,
        raw_update_text=content,
        update_telegram_message_id=update_telegram_message_id,
        reply_to_telegram_message_id='',
        actor=actor,
    )


def _authorized_telegram_actor(group_id: str, user_payload: dict | None, case, parsed_update):
    """Resolve Telegram identity and enforce the same scoped policy as the Mini App."""
    if not user_payload:
        return None, 'Your Telegram account could not be verified for complaint updates.'
    group_config = GroupRegistry.get_instance().get_group(str(group_id))
    if not group_config:
        return None, 'Complaint Cases is not configured for this group.'
    try:
        from core.services.telegram_identity import identity_from_user_payload, resolve_or_bind_telegram_user, user_access
        user = resolve_or_bind_telegram_user(identity_from_user_payload(user_payload))
        access = user_access(user, 'complaint_cases', group_configuration=group_config)
        from core.services.workflow_access import workflow_access_decision
        capability = 'complaint.case.update'
        decision = workflow_access_decision(
            user, 'complaint_cases', capability, access=access, resource=case,
            group_configuration=group_config,
        )
        if not decision.allowed:
            return None, 'Your assigned complaint-case role does not permit updates to this case.'
        transition_capability = None
        if parsed_update.new_status == 'Closed' and case.complaint_status != 'Closed':
            transition_capability = 'complaint.case.close'
        elif case.complaint_status == 'Closed' and parsed_update.new_status != 'Closed':
            transition_capability = 'complaint.case.reopen'
        if transition_capability and not workflow_access_decision(
            user, 'complaint_cases', transition_capability, access=access, resource=case,
            group_configuration=group_config,
        ).allowed:
            return None, 'Only an authorized case manager can close or reopen this complaint.'
        return user, ''
    except Exception:
        return None, 'Your Telegram account is not configured for complaint updates.'


def apply_case_update(
    parsed_message: ParsedMessage,
    parsed_update: ParsedCaseUpdate,
    sender: str,
    raw_update_text: str,
    update_telegram_message_id: str,
    reply_to_telegram_message_id: str,
    actor=None,
) -> dict:
    """Commit canonical state first, then attempt the Sheet publication."""
    if update_telegram_message_id:
        existing = CaseUpdate.objects.filter(
            group_id=parsed_message.group_id, telegram_message_id=update_telegram_message_id,
        ).first()
        if existing:
            return {'status': 'command', 'reply_text': f'Update for {parsed_message.message_id} was already recorded.'}
    now = timezone.now()
    date_resolved = now if parsed_update.new_status == 'Closed' else None

    with transaction.atomic():
        parsed_message = ParsedMessage.objects.select_for_update().get(pk=parsed_message.pk)
        old_status = parsed_message.complaint_status or ''
        resolution_details = _append_resolution_details(
            existing=parsed_message.resolution_details,
            sender=(actor.get_full_name() or actor.get_username()) if actor else sender,
            update_text=parsed_update.resolution_text,
            created_at=now,
        )
        update_record = CaseUpdate.objects.create(
            parsed_message=parsed_message, group_id=parsed_message.group_id,
            updated_by=(actor.get_full_name() or actor.get_username()) if actor else (sender or ''),
            telegram_message_id=update_telegram_message_id or '',
            reply_to_telegram_message_id=reply_to_telegram_message_id or '',
            old_status=old_status, new_status=parsed_update.new_status,
            resolution_text=parsed_update.resolution_text, risk_level=parsed_update.risk_level,
            loan_at_risk=parsed_update.loan_at_risk, raw_update_text=raw_update_text,
            sync_status='pending', source='telegram',
        )
        parsed_message.complaint_status = parsed_update.new_status
        parsed_message.resolution_details = resolution_details
        parsed_message.date_resolved = date_resolved
        if parsed_update.risk_level:
            parsed_message.risk_level = parsed_update.risk_level
        if parsed_update.loan_at_risk:
            parsed_message.loan_at_risk = parsed_update.loan_at_risk
        parsed_message.save(update_fields=[
            'complaint_status', 'resolution_details', 'date_resolved', 'risk_level', 'loan_at_risk',
        ])
        from core.services.complaint_cases import control_snapshot, ensure_case_control
        from core.models import ComplaintCaseEvent
        control = ensure_case_control(parsed_message, GroupRegistry.get_instance().get_group(parsed_message.group_id))
        control.revision += 1
        control.sync_status = 'pending'
        control.save(update_fields=['revision', 'sync_status', 'updated_at'])
        ComplaintCaseEvent.objects.create(
            case=control, revision=control.revision, action='telegram_updated', actor=actor,
            actor_label=update_record.updated_by, request_id=f'telegram-{update_telegram_message_id}' if update_telegram_message_id else '',
            payload_hash=hashlib.sha256(raw_update_text.encode()).hexdigest(),
            before_values={'status': old_status}, after_values=control_snapshot(control, parsed_message),
            reason=parsed_update.resolution_text,
        )

    sheet_success = _update_sheet(parsed_message, parsed_update, resolution_details, date_resolved)
    if not sheet_success:
        update_record.sync_status = 'failed'
        update_record.sync_error = 'The local update is saved; Google Sheets publication is pending.'
        update_record.save(update_fields=['sync_status', 'sync_error'])
        control.sync_status = 'failed'
        control.sync_error = update_record.sync_error
        control.save(update_fields=['sync_status', 'sync_error', 'updated_at'])
        record_command_case_update(update_record, parsed_message, action='complaint.case.update_sync_failed')
        return {
            'status': 'command',
            'reply_text': f'Update saved for {parsed_message.message_id}. Register publication is pending.',
        }

    update_record.sync_status = 'success'
    update_record.save(update_fields=['sync_status'])
    control.sync_status = 'success'
    control.sync_error = ''
    control.last_sync_at = timezone.now()
    control.save(update_fields=['sync_status', 'sync_error', 'last_sync_at', 'updated_at'])
    record_command_case_update(update_record, parsed_message, action='complaint.case.updated')

    return {
        'status': 'command',
        'reply_text': _format_success_reply(
            parsed_message,
            parsed_update,
            date_resolved,
        ),
    }


def record_command_case_update(update_record: CaseUpdate, parsed_message: ParsedMessage, *, action: str) -> None:
    """Project a Telegram command update without retaining its raw content twice."""
    from core.services.compliance_audit import record_event

    record_event(
        workflow='complaint_cases',
        action=action,
        category='workflow_transition' if update_record.old_status != update_record.new_status else 'workflow',
        origin='human',
        subject_type='complaint_case',
        subject_id=str(parsed_message.pk),
        customer_reference=str(parsed_message.message_id),
        actor_label=update_record.updated_by,
        request_id=update_record.client_request_id or update_record.telegram_message_id,
        source_model='CaseUpdate',
        source_event_id=str(update_record.pk),
        deduplication_key=f'complaint:CaseUpdate:{update_record.pk}',
        before_values={'status': update_record.old_status} if update_record.old_status else {},
        after_values={
            'status': update_record.new_status,
            'risk_level': update_record.risk_level,
            'loan_at_risk': update_record.loan_at_risk,
            'sync_status': update_record.sync_status,
        },
        metadata={
            'source': update_record.source,
            'has_resolution_note': bool(update_record.resolution_text),
            'has_location': bool(update_record.gps_link),
            'has_sync_error': bool(update_record.sync_error),
        },
        sensitive=True,
        occurred_at=update_record.created_at,
    )


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
    entry = " ".join(str(update_text or '').strip().split())
    if not entry:
        return existing or ''
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
        f"Case ID: {parsed_message.message_id} (use this for /update)",
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
            f"- Case ID {case.message_id}: {case.customer_name or 'Unknown'} | "
            f"{case.customer_phone or 'no phone'}"
        )
    lines.append("/update MSG_ID Status: resolved - details")
    return "\n".join(lines)
