"""
Telegram bot command handlers backed by the local database.
"""
import re
from django.db import connection
from django.db.models import Count, Q
from django.utils import timezone

from core.models import ParsedMessage
from core.services.group_config import GroupRegistry


MAX_LAST_LIMIT = 20
DEFAULT_LAST_LIMIT = 5
MAX_SEARCH_LENGTH = 80


def handle_bot_command(
    content: str,
    group_id: str,
    sender: str = '',
    telegram_message_id: str = '',
) -> dict | None:
    """
    Return a command result dict when *content* is a supported command.

    Supported:
    - /last [n]
    - last [n]
    - /recent [n]
    - recent [n]
    - /case MSG_ID
    - /search text
    - /today
    - /week
    - /unsynced [n]
    - /phone value
    - /id value
    - /open [n]
    - /pending [n]
    - /closed [n]
    - /stale [days]
    - /errors [n]
    - /missing phone|id|name [n]
    - /lowconfidence [n]
    - /risk level [n]
    - /duplicates [days]
    - /top regions [days]
    - /top issues [days]
    - /summary today
    - /summary week
    - /sync
    - /group
    - /health
    - /help
    """
    if not content:
        return None

    text = content.strip()
    normalized = text.lower()

    if normalized in {'/help', 'help', '/commands', 'commands'}:
        return {
            'status': 'command',
            'reply_text': _help_text(),
        }

    if normalized in {'/sync', 'sync'}:
        return {
            'status': 'command',
            'reply_text': _format_sheet_sync(group_id=group_id),
        }

    if _should_refresh_from_sheet(normalized):
        _refresh_group_from_sheet(group_id)

    match = re.fullmatch(r'/?update\s+(\S+)\s+(.+)', text, flags=re.IGNORECASE | re.DOTALL)
    if match:
        from core.services.case_updates import handle_case_update_command
        return handle_case_update_command(
            group_id=group_id,
            message_id=match.group(1),
            content=match.group(2),
            sender=sender,
            update_telegram_message_id=telegram_message_id,
        )

    if normalized in {'/today', 'today'}:
        return {
            'status': 'command',
            'reply_text': _format_today_cases(group_id=group_id),
        }

    if normalized in {'/week', 'week'}:
        return {
            'status': 'command',
            'reply_text': _format_week_cases(group_id=group_id),
        }

    if normalized in {'/group', 'group'}:
        return {
            'status': 'command',
            'reply_text': _format_group_info(group_id=group_id),
        }

    if normalized in {'/health', 'health'}:
        return {
            'status': 'command',
            'reply_text': _format_health(group_id=group_id),
        }

    match = re.fullmatch(r'/?(?:last|recent)(?:\s+(\d+))?', normalized)
    if match:
        raw_limit = match.group(1)
        limit = int(raw_limit) if raw_limit else DEFAULT_LAST_LIMIT
        limit = max(1, min(limit, MAX_LAST_LIMIT))
        return {
            'status': 'command',
            'reply_text': _format_last_cases(group_id=group_id, limit=limit),
        }

    match = re.fullmatch(r'/?unsynced(?:\s+(\d+))?', normalized)
    if match:
        raw_limit = match.group(1)
        limit = int(raw_limit) if raw_limit else DEFAULT_LAST_LIMIT
        limit = max(1, min(limit, MAX_LAST_LIMIT))
        return {
            'status': 'command',
            'reply_text': _format_unsynced_cases(group_id=group_id, limit=limit),
        }

    match = re.fullmatch(r'/?(?:phone|tel)\s+(.+)', text, flags=re.IGNORECASE)
    if match:
        query = " ".join(match.group(1).split())[:MAX_SEARCH_LENGTH]
        return {
            'status': 'command',
            'reply_text': _format_field_lookup(
                group_id=group_id,
                field='customer_phone',
                label='phone',
                query=query,
            ),
        }

    match = re.fullmatch(r'/?(?:id|customerid|account)\s+(.+)', text, flags=re.IGNORECASE)
    if match:
        query = " ".join(match.group(1).split())[:MAX_SEARCH_LENGTH]
        return {
            'status': 'command',
            'reply_text': _format_field_lookup(
                group_id=group_id,
                field='customer_id',
                label='customer ID',
                query=query,
            ),
        }

    match = re.fullmatch(r'/?(?:open|pending|closed)(?:\s+(\d+))?', normalized)
    if match:
        command = normalized.lstrip('/').split()[0]
        raw_limit = match.group(1)
        limit = int(raw_limit) if raw_limit else DEFAULT_LAST_LIMIT
        limit = max(1, min(limit, MAX_LAST_LIMIT))
        return {
            'status': 'command',
            'reply_text': _format_status_cases(
                group_id=group_id,
                status=command,
                limit=limit,
            ),
        }

    match = re.fullmatch(r'/?missing\s+(phone|id|name)(?:\s+(\d+))?', normalized)
    if match:
        field_key = match.group(1)
        raw_limit = match.group(2)
        limit = int(raw_limit) if raw_limit else DEFAULT_LAST_LIMIT
        limit = max(1, min(limit, MAX_LAST_LIMIT))
        return {
            'status': 'command',
            'reply_text': _format_missing_cases(
                group_id=group_id,
                field_key=field_key,
                limit=limit,
            ),
        }

    match = re.fullmatch(r'/?lowconfidence(?:\s+(\d+))?', normalized)
    if match:
        raw_limit = match.group(1)
        limit = int(raw_limit) if raw_limit else DEFAULT_LAST_LIMIT
        limit = max(1, min(limit, MAX_LAST_LIMIT))
        return {
            'status': 'command',
            'reply_text': _format_low_confidence_cases(
                group_id=group_id,
                limit=limit,
            ),
        }

    match = re.fullmatch(r'/?risk\s+(\S+)(?:\s+(\d+))?', text, flags=re.IGNORECASE)
    if match:
        level = match.group(1).strip()[:40]
        raw_limit = match.group(2)
        limit = int(raw_limit) if raw_limit else DEFAULT_LAST_LIMIT
        limit = max(1, min(limit, MAX_LAST_LIMIT))
        return {
            'status': 'command',
            'reply_text': _format_risk_cases(
                group_id=group_id,
                level=level,
                limit=limit,
            ),
        }

    match = re.fullmatch(r'/?duplicates(?:\s+(\d+))?', normalized)
    if match:
        raw_days = match.group(1)
        days = int(raw_days) if raw_days else 30
        days = max(1, min(days, 365))
        return {
            'status': 'command',
            'reply_text': _format_duplicate_hints(group_id=group_id, days=days),
        }

    match = re.fullmatch(r'/?top\s+(regions|issues)(?:\s+(\d+))?', normalized)
    if match:
        target = match.group(1)
        raw_days = match.group(2)
        days = int(raw_days) if raw_days else 7
        days = max(1, min(days, 365))
        return {
            'status': 'command',
            'reply_text': _format_top_counts(
                group_id=group_id,
                target=target,
                days=days,
            ),
        }

    match = re.fullmatch(r'/?stale(?:\s+(\d+))?', normalized)
    if match:
        raw_days = match.group(1)
        days = int(raw_days) if raw_days else 7
        days = max(1, min(days, 365))
        return {
            'status': 'command',
            'reply_text': _format_stale_cases(group_id=group_id, days=days),
        }

    match = re.fullmatch(r'/?errors(?:\s+(\d+))?', normalized)
    if match:
        raw_limit = match.group(1)
        limit = int(raw_limit) if raw_limit else DEFAULT_LAST_LIMIT
        limit = max(1, min(limit, MAX_LAST_LIMIT))
        return {
            'status': 'command',
            'reply_text': _format_sync_error_cases(group_id=group_id, limit=limit),
        }

    match = re.fullmatch(r'/?summary(?:\s+(today|week))?', normalized)
    if match:
        period = match.group(1) or 'today'
        return {
            'status': 'command',
            'reply_text': _format_summary(group_id=group_id, period=period),
        }

    match = re.fullmatch(r'/?case\s+(\S+)', text, flags=re.IGNORECASE)
    if match:
        return {
            'status': 'command',
            'reply_text': _format_case_detail(
                group_id=group_id,
                message_id=match.group(1),
            ),
        }

    match = re.fullmatch(r'/?search\s+(.+)', text, flags=re.IGNORECASE)
    if match:
        query = " ".join(match.group(1).split())[:MAX_SEARCH_LENGTH]
        return {
            'status': 'command',
            'reply_text': _format_search_results(group_id=group_id, query=query),
        }

    if text.startswith('/'):
        return {
            'status': 'command',
            'reply_text': (
                "Unknown command. Try /last 5, /case MSG_ID, /search text, "
                "or /help."
            ),
        }

    return None


def _help_text() -> str:
    return (
        "Available commands:\n"
        "/last 5 - show the latest 5 cases from this group\n"
        "/recent 10 - show the latest 10 cases from this group\n"
        "/case MSG_ID - show one case in detail\n"
        "/update MSG_ID Status: resolved - update a case status\n"
        "/search text - search names, phone, ID, or complaint text\n"
        "/today - show today's cases from this group\n"
        "/week - show this week's cases from this group\n"
        "/unsynced 10 - show recent cases not synced to Sheets\n"
        "/phone 0712345678 - show cases for a phone number\n"
        "/id ACC123 - show cases for a customer/account ID\n"
        "/open 10 - show cases not marked closed\n"
        "/pending 10 - show cases with no status\n"
        "/closed 10 - show closed cases\n"
        "/stale 7 - show cases older than 7 days and not closed\n"
        "/errors 10 - show cases with sync errors\n"
        "/missing phone 10 - show cases missing phone, id, or name\n"
        "/lowconfidence 10 - show partial or incomplete cases\n"
        "/risk high 10 - show cases by risk level\n"
        "/duplicates 30 - show repeated phone/account IDs in 30 days\n"
        "/top regions 7 - show top regions in the last 7 days\n"
        "/top issues 7 - show top complaint categories in 7 days\n"
        "/summary today - show status/sync totals for today\n"
        "/summary week - show status/sync totals for this week\n"
        "/sync - refresh backend cases from Google Sheets\n"
        "/group - show this chat's sheet routing\n"
        "/health - show database and group config status\n"
        "/help - show this help"
    )


def _should_refresh_from_sheet(normalized: str) -> bool:
    command = normalized.lstrip('/').split()[0] if normalized else ''
    return command in {
        'today',
        'week',
        'group',
        'health',
        'last',
        'recent',
        'unsynced',
        'phone',
        'tel',
        'id',
        'customerid',
        'account',
        'open',
        'pending',
        'closed',
        'missing',
        'lowconfidence',
        'risk',
        'duplicates',
        'top',
        'stale',
        'errors',
        'summary',
        'case',
        'search',
    }


def _refresh_group_from_sheet(group_id: str) -> None:
    try:
        from core.services.sheet_sync import sync_group_from_sheet
        result = sync_group_from_sheet(group_id=group_id, delete_missing=True)
        if result.get('status') != 'success':
            # Command reads should continue using the last local mirror if the
            # sheet is temporarily unavailable.
            return
    except Exception:
        return


def _format_sheet_sync(group_id: str) -> str:
    try:
        from core.services.sheet_sync import sync_group_from_sheet
        result = sync_group_from_sheet(group_id=group_id, delete_missing=True)
    except Exception:
        return "Sheet sync failed."

    if result.get('status') != 'success':
        error = _compact("; ".join(result.get('errors', [])), 200)
        return f"Sheet sync failed: {error or 'unknown error'}"

    return (
        "Sheet sync complete:\n"
        f"Rows in sheet: {result.get('row_count', 0)}\n"
        f"Created: {result.get('created_count', 0)}\n"
        f"Updated: {result.get('updated_count', 0)}\n"
        f"Deleted locally: {result.get('deleted_count', 0)}\n"
        f"Backend cases: {result.get('backend_count', 0)}"
    )


def _format_last_cases(group_id: str, limit: int) -> str:
    rows = list(_group_cases(group_id).order_by('-created_at')[:limit])

    if not rows:
        return "No cases found for this group yet."

    lines = [f"Latest {len(rows)} case(s):"]
    for index, msg in enumerate(rows, start=1):
        lines.append(_format_case_line(index, msg))

    return "\n".join(lines)


def _format_today_cases(group_id: str) -> str:
    today = timezone.localdate()
    rows = list(
        _group_cases(group_id)
        .filter(created_at__date=today)
        .order_by('-created_at')[:MAX_LAST_LIMIT]
    )

    if not rows:
        return "No cases found for this group today."

    lines = [f"Today's cases ({len(rows)} shown):"]
    for index, msg in enumerate(rows, start=1):
        lines.append(_format_case_line(index, msg))
    return "\n".join(lines)


def _format_week_cases(group_id: str) -> str:
    today = timezone.localdate()
    start = today - timezone.timedelta(days=today.weekday())
    rows = list(
        _group_cases(group_id)
        .filter(created_at__date__gte=start)
        .order_by('-created_at')[:MAX_LAST_LIMIT]
    )

    if not rows:
        return "No cases found for this group this week."

    lines = [f"This week's cases ({len(rows)} shown):"]
    for index, msg in enumerate(rows, start=1):
        lines.append(_format_case_line(index, msg))
    return "\n".join(lines)


def _format_unsynced_cases(group_id: str, limit: int) -> str:
    rows = list(
        _group_cases(group_id)
        .filter(synced_to_sheets=False)
        .order_by('-created_at')[:limit]
    )

    if not rows:
        return "No unsynced cases found for this group."

    lines = [f"Latest {len(rows)} unsynced case(s):"]
    for index, msg in enumerate(rows, start=1):
        error = _compact(msg.last_sync_error, 60) or "no sync error recorded"
        lines.append(f"{_format_case_line(index, msg)}\n   Sync error: {error}")
    return "\n".join(lines)


def _format_field_lookup(group_id: str, field: str, label: str, query: str) -> str:
    if not query:
        return f"{label.title()} lookup value cannot be empty."

    rows = list(
        _group_cases(group_id)
        .filter(**{f"{field}__icontains": query})
        .order_by('-created_at')[:MAX_LAST_LIMIT]
    )

    if not rows:
        return f"No cases found for {label}: {query}"

    lines = [f"Cases for {label} '{query}' ({len(rows)} shown):"]
    for index, msg in enumerate(rows, start=1):
        lines.append(_format_case_line(index, msg))
    return "\n".join(lines)


def _format_status_cases(group_id: str, status: str, limit: int) -> str:
    queryset = _group_cases(group_id)
    if status == 'pending':
        queryset = queryset.filter(complaint_status='')
        title = 'pending case(s)'
    elif status == 'closed':
        queryset = queryset.filter(complaint_status__iexact='closed')
        title = 'closed case(s)'
    else:
        queryset = queryset.exclude(complaint_status__iexact='closed')
        title = 'open case(s)'

    rows = list(queryset.order_by('-created_at')[:limit])
    if not rows:
        return f"No {title} found for this group."

    lines = [f"Latest {len(rows)} {title}:"]
    for index, msg in enumerate(rows, start=1):
        lines.append(_format_case_line(index, msg))
    return "\n".join(lines)


def _format_missing_cases(group_id: str, field_key: str, limit: int) -> str:
    field_map = {
        'phone': ('customer_phone', 'phone number'),
        'id': ('customer_id', 'customer ID'),
        'name': ('customer_name', 'customer name'),
    }
    field_name, label = field_map[field_key]
    rows = list(
        _group_cases(group_id)
        .filter(**{field_name: ''})
        .order_by('-created_at')[:limit]
    )

    if not rows:
        return f"No cases missing {label} found for this group."

    lines = [f"Latest {len(rows)} case(s) missing {label}:"]
    for index, msg in enumerate(rows, start=1):
        lines.append(_format_case_line(index, msg))
    return "\n".join(lines)


def _format_low_confidence_cases(group_id: str, limit: int) -> str:
    rows = list(
        _group_cases(group_id)
        .filter(
            Q(processed_message__status='partial')
            | Q(customer_name='')
            | Q(customer_phone='')
            | Q(complaint_description='')
        )
        .order_by('-created_at')[:limit]
    )

    if not rows:
        return "No low-confidence or incomplete cases found for this group."

    lines = [f"Latest {len(rows)} low-confidence/incomplete case(s):"]
    for index, msg in enumerate(rows, start=1):
        reasons = []
        if msg.processed_message.status == 'partial':
            reasons.append('partial processing')
        if not msg.customer_name:
            reasons.append('missing name')
        if not msg.customer_phone:
            reasons.append('missing phone')
        if not msg.complaint_description:
            reasons.append('missing description')
        lines.append(
            f"{_format_case_line(index, msg)}\n"
            f"   Reason: {', '.join(reasons)}"
        )
    return "\n".join(lines)


def _format_risk_cases(group_id: str, level: str, limit: int) -> str:
    rows = list(
        _group_cases(group_id)
        .filter(risk_level__iexact=level)
        .order_by('-created_at')[:limit]
    )

    if not rows:
        return f"No {level} risk cases found for this group."

    lines = [f"Latest {len(rows)} {level} risk case(s):"]
    for index, msg in enumerate(rows, start=1):
        lines.append(_format_case_line(index, msg))
    return "\n".join(lines)


def _format_stale_cases(group_id: str, days: int) -> str:
    cutoff = timezone.now() - timezone.timedelta(days=days)
    rows = list(
        _group_cases(group_id)
        .exclude(complaint_status__iexact='closed')
        .filter(created_at__lt=cutoff)
        .order_by('created_at')[:MAX_LAST_LIMIT]
    )

    if not rows:
        return f"No stale cases older than {days} day(s) found for this group."

    lines = [f"Stale cases older than {days} day(s) ({len(rows)} shown):"]
    for index, msg in enumerate(rows, start=1):
        age_days = max((timezone.now() - msg.created_at).days, 0)
        lines.append(f"{_format_case_line(index, msg)}\n   Age: {age_days} day(s)")
    return "\n".join(lines)


def _format_duplicate_hints(group_id: str, days: int) -> str:
    cutoff = timezone.now() - timezone.timedelta(days=days)
    queryset = _group_cases(group_id).filter(created_at__gte=cutoff)
    duplicate_lines = []

    for field_name, label in [
        ('customer_phone', 'phone'),
        ('customer_id', 'customer ID'),
    ]:
        duplicates = (
            queryset.exclude(**{field_name: ''})
            .values(field_name)
            .annotate(total=Count('id'))
            .filter(total__gt=1)
            .order_by('-total')[:10]
        )
        for item in duplicates:
            duplicate_lines.append(
                f"{label} {item[field_name]}: {item['total']} case(s)"
            )

    if not duplicate_lines:
        return f"No duplicate phone or customer ID hints found in {days} day(s)."

    return (
        f"Duplicate hints in the last {days} day(s):\n"
        + "\n".join(duplicate_lines[:MAX_LAST_LIMIT])
    )


def _format_sync_error_cases(group_id: str, limit: int) -> str:
    rows = list(
        _group_cases(group_id)
        .exclude(last_sync_error='')
        .order_by('-created_at')[:limit]
    )

    if not rows:
        return "No sync errors found for this group."

    lines = [f"Latest {len(rows)} sync error case(s):"]
    for index, msg in enumerate(rows, start=1):
        error = _compact(msg.last_sync_error, 90)
        lines.append(f"{_format_case_line(index, msg)}\n   Error: {error}")
    return "\n".join(lines)


def _format_top_counts(group_id: str, target: str, days: int) -> str:
    cutoff = timezone.now() - timezone.timedelta(days=days)
    field = 'branch_region' if target == 'regions' else 'complaint_category'
    label = 'regions' if target == 'regions' else 'issues'

    rows = (
        _group_cases(group_id)
        .filter(created_at__gte=cutoff)
        .exclude(**{field: ''})
        .values(field)
        .annotate(total=Count('id'))
        .order_by('-total', field)[:10]
    )

    rows = list(rows)
    if not rows:
        return f"No {label} found in the last {days} day(s)."

    lines = [f"Top {label} in the last {days} day(s):"]
    for index, row in enumerate(rows, start=1):
        lines.append(f"{index}. {row[field]}: {row['total']}")
    return "\n".join(lines)


def _format_summary(group_id: str, period: str) -> str:
    queryset = _group_cases(group_id)
    today = timezone.localdate()
    if period == 'week':
        start = today - timezone.timedelta(days=today.weekday())
        queryset = queryset.filter(created_at__date__gte=start)
        title = f"Summary for this week (from {start.strftime('%d/%m/%Y')})"
    else:
        queryset = queryset.filter(created_at__date=today)
        title = "Summary for today"

    total = queryset.count()
    closed = queryset.filter(complaint_status__iexact='closed').count()
    pending = queryset.filter(complaint_status='').count()
    open_count = queryset.exclude(complaint_status__iexact='closed').count()
    unsynced = queryset.filter(synced_to_sheets=False).count()
    sync_errors = queryset.exclude(last_sync_error='').count()

    return (
        f"{title}:\n"
        f"Total: {total}\n"
        f"Open/not closed: {open_count}\n"
        f"Pending status: {pending}\n"
        f"Closed: {closed}\n"
        f"Unsynced: {unsynced}\n"
        f"Sync errors: {sync_errors}"
    )


def _format_case_detail(group_id: str, message_id: str) -> str:
    msg = _group_cases(group_id).filter(message_id__iexact=message_id).first()
    if not msg:
        return f"Case {message_id} was not found in this group."

    return (
        f"Case {msg.message_id}\n"
        f"Date: {_format_date(msg.timestamp or msg.created_at)}\n"
        f"Customer: {(msg.customer_name or msg.sender or 'Unknown').upper()}\n"
        f"Phone: {msg.customer_phone or 'not set'}\n"
        f"Customer ID: {msg.customer_id or 'not set'}\n"
        f"Region: {msg.branch_region or 'not set'}\n"
        f"Status: {msg.complaint_status or 'status not set'}\n"
        f"Synced: {'yes' if msg.synced_to_sheets else 'no'}\n"
        f"Description: {_compact(msg.complaint_description or msg.raw_message, 500)}"
    )


def _format_search_results(group_id: str, query: str) -> str:
    if not query:
        return "Search query cannot be empty."

    rows = list(
        _group_cases(group_id)
        .filter(
            Q(message_id__icontains=query)
            | Q(customer_name__icontains=query)
            | Q(customer_phone__icontains=query)
            | Q(customer_id__icontains=query)
            | Q(complaint_description__icontains=query)
            | Q(raw_message__icontains=query)
        )
        .order_by('-created_at')[:MAX_LAST_LIMIT]
    )

    if not rows:
        return f"No cases found for search: {query}"

    lines = [f"Search results for '{query}' ({len(rows)} shown):"]
    for index, msg in enumerate(rows, start=1):
        lines.append(_format_case_line(index, msg))
    return "\n".join(lines)


def _format_group_info(group_id: str) -> str:
    registry = GroupRegistry.get_instance()
    config = registry.get_group(str(group_id))

    if not config:
        return f"Group {group_id} is not configured."

    return (
        f"Group: {group_id}\n"
        f"Enabled: {'yes' if config.enabled else 'no'}\n"
        f"Sheet ID: {config.sheet_id or 'not set'}\n"
        f"Sheet tab: {config.sheet_name or 'not set'}"
    )


def _format_health(group_id: str) -> str:
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        db_status = "ok"
    except Exception:
        db_status = "error"

    registry = GroupRegistry.get_instance()
    group_status = "configured" if registry.get_group(str(group_id)) else "not configured"
    case_count = _group_cases(group_id).count()
    unsynced_count = _group_cases(group_id).filter(synced_to_sheets=False).count()

    return (
        "Health:\n"
        f"Database: {db_status}\n"
        f"Group: {group_status}\n"
        f"Cases in group: {case_count}\n"
        f"Unsynced cases: {unsynced_count}"
    )


def _group_cases(group_id: str):
    return ParsedMessage.objects.filter(group_id=str(group_id))


def _format_case_line(index: int, msg: ParsedMessage) -> str:
    reported_at = _format_date(msg.timestamp or msg.created_at)
    name = (msg.customer_name or msg.sender or "Unknown").upper()
    phone = msg.customer_phone or "no phone"
    status = msg.complaint_status or "status not set"
    description = _compact(msg.complaint_description or msg.raw_message, 80)

    return (
        f"{index}. {reported_at} | {name} | {phone} | {status}\n"
        f"   {description}\n"
        f"   ID: {msg.message_id}"
    )


def _format_date(value) -> str:
    if not value:
        return "no date"
    if timezone.is_aware(value):
        value = timezone.localtime(value)
    return value.strftime('%d/%m/%Y')


def _compact(value: str, max_length: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_length:
        return text
    return text[: max_length - 3].rstrip() + "..."
