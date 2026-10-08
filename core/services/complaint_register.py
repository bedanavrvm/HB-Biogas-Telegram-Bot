"""Organization-wide, read-only Complaint Cases register and XLSX export."""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, time, timedelta
from io import BytesIO
from typing import Any
from urllib.parse import urlparse

from django.db.models import Case, Count, IntegerField, OuterRef, Subquery, Q, Value, When
from django.db.models.functions import Coalesce, TruncDay, TruncMonth, TruncWeek, TruncYear
from django.utils import timezone
from django.utils.dateparse import parse_date

from core.models import CaseUpdate, ComplaintCategory, GroupSheetConfiguration, ParsedMessage
from core.services.complaint_cases import (
    ComplaintCaseError, format_datetime, resolution_history_entries,
    latest_resolution_text, resolution_comments_text, resolution_history_text, serialize_update, sla_payload,
)


EXPORT_FIELDS = (
    '#', 'Complaint ID', 'Date Reported', 'Status', 'Customer Name',
    'Customer National ID', 'Primary Phone Number', 'Secondary Phone No',
    'County', 'Constituency', 'Village', 'Branch', 'JBL Reported By',
    'Complaint Type', 'Complaint Description', 'GPS Link', 'Resolution Details',
    'Resolution Comments', 'Date Resolved', 'Days Open', 'Resolution History',
    'Resolution Time (hours)', 'HB Response Time (hours)',
)

SORT_FIELDS = {
    'reported_at': 'timestamp',
    'recorded_at': 'created_at',
    'resolved_at': 'date_resolved',
    'case_id': 'complaint_control__reference_number',
    'customer': 'customer_name',
    'branch': 'branch_region',
    'category': 'complaint_category',
    'status': 'complaint_status',
    'priority': 'complaint_control__priority',
    'sla_due': 'complaint_control__sla_due_at',
    'sync': 'complaint_control__sync_status',
    'group': 'group_id',
}

REPORT_SORT_FIELDS = {
    'date_reported': 'report_date',
    'status': 'complaint_status',
    'branch_region': 'branch_region',
    'days_open': 'report_date',
    'date_resolved': 'date_resolved',
}

REPORT_TIME_GROUPS = {
    'day': (TruncDay, '%Y-%m-%d'),
    'week': (TruncWeek, '%Y-%m-%d'),
    'month': (TruncMonth, '%Y-%m'),
    'year': (TruncYear, '%Y'),
}
REPORT_MAX_TIME_BUCKETS = 500


def _group_rows() -> dict[str, GroupSheetConfiguration]:
    rows = GroupSheetConfiguration.objects.all()
    return {
        str(row.group_id): row for row in rows
        if str((row.workflow or {}).get('type') or 'case') == 'case'
    }


def _group_label(group_id: str, groups: dict[str, GroupSheetConfiguration]) -> str:
    row = groups.get(str(group_id))
    return str(row.display_name or row.group_id) if row else str(group_id)


def _projection_enabled(group_id: str, groups: dict[str, GroupSheetConfiguration]) -> bool:
    row = groups.get(str(group_id))
    return bool(row.complaint_sheet_projection_enabled) if row else True


def _base_queryset():
    # ComplaintCaseControl is the durable marker that a ParsedMessage belongs
    # to the Complaint Cases workflow; reads never create controls implicitly.
    comment_counts = CaseUpdate.objects.filter(
        parsed_message_id=OuterRef('pk'), source='mini_app_comment',
    ).order_by().values('parsed_message_id').annotate(total=Count('pk')).values('total')
    return ParsedMessage.objects.filter(complaint_control__isnull=False).annotate(
        report_date=Coalesce('timestamp', 'created_at'),
        hb_comment_count=Coalesce(Subquery(comment_counts), Value(0)),
    ).select_related(
        'complaint_control__category', 'complaint_control__branch_ref',
        'complaint_control__customer', 'complaint_control__assigned_to',
    )


def _parse_filter_date(value: Any, label: str, *, end: bool = False):
    text = str(value or '').strip()
    if not text:
        return None
    try:
        parsed = parse_date(text)
    except ValueError:
        parsed = None
    if not parsed:
        raise ComplaintCaseError(f'{label} must be a valid date.')
    boundary = datetime.combine(parsed, time.max if end else time.min)
    return timezone.make_aware(boundary, timezone.get_current_timezone())


def _apply_filters(queryset, filters: dict[str, Any], groups: dict[str, GroupSheetConfiguration]):
    status = str(filters.get('status') or '').strip().casefold()
    if status in {'pending', 'active'}:
        queryset = queryset.exclude(complaint_status='Closed')
    elif status in {'resolved', 'closed'}:
        queryset = queryset.filter(complaint_status='Closed')
    group_id = str(filters.get('group') or '').strip()
    if group_id:
        queryset = queryset.filter(group_id=group_id)
    branch = str(filters.get('branch') or '').strip()
    if branch:
        queryset = queryset.filter(branch_region__iexact=branch)
    category = str(filters.get('category') or '').strip()
    if category:
        queryset = queryset.filter(
            Q(complaint_control__category__label__iexact=category)
            | Q(complaint_category__iexact=category)
        )
    priority = str(filters.get('priority') or '').strip().casefold()
    if priority in {'high', 'normal', 'low'}:
        queryset = queryset.filter(complaint_control__priority=priority)
    sla = str(filters.get('sla') or '').strip().casefold()
    now = timezone.now()
    if sla == 'overdue':
        queryset = queryset.exclude(complaint_status='Closed').filter(complaint_control__sla_due_at__lt=now)
    elif sla == 'due_soon':
        queryset = queryset.exclude(complaint_status='Closed').filter(
            complaint_control__sla_due_at__gte=now,
            complaint_control__sla_due_at__lte=now + timedelta(hours=24),
        )
    elif sla == 'on_track':
        queryset = queryset.exclude(complaint_status='Closed').filter(complaint_control__sla_due_at__gt=now + timedelta(hours=24))
    elif sla == 'closed':
        queryset = queryset.filter(complaint_status='Closed')
    sync = str(filters.get('sync') or '').strip().casefold()
    disabled_groups = {
        group_id for group_id, row in groups.items()
        if not row.complaint_sheet_projection_enabled
    }
    if sync == 'suspended':
        queryset = queryset.filter(
            group_id__in=disabled_groups,
            complaint_control__sync_status__in={'pending', 'failed'},
        )
    elif sync in {'pending', 'failed'}:
        queryset = queryset.exclude(group_id__in=disabled_groups).filter(complaint_control__sync_status=sync)
    elif sync in {'success', 'not_required'}:
        queryset = queryset.filter(complaint_control__sync_status=sync)
    reported_from = _parse_filter_date(filters.get('reported_from'), 'Reported from')
    reported_to = _parse_filter_date(filters.get('reported_to'), 'Reported to', end=True)
    if reported_from:
        queryset = queryset.filter(timestamp__gte=reported_from)
    if reported_to:
        queryset = queryset.filter(timestamp__lte=reported_to)
    search = str(filters.get('query') or '').strip()
    if search:
        queryset = queryset.filter(
            Q(message_id__icontains=search)
            | Q(complaint_control__reference_number__icontains=search)
            | Q(customer_name__icontains=search)
            | Q(customer_phone__icontains=search)
            | Q(customer_id__icontains=search)
            | Q(branch_region__icontains=search)
            | Q(complaint_category__icontains=search)
            | Q(complaint_description__icontains=search)
        )
    return queryset


def _sync_state(case: ParsedMessage, groups: dict[str, GroupSheetConfiguration]) -> str:
    value = case.complaint_control.sync_status
    if not _projection_enabled(case.group_id, groups) and value in {'pending', 'failed'}:
        return 'suspended'
    return value


def _days_open(case: ParsedMessage) -> int | None:
    started = case.timestamp or case.created_at
    ended = case.date_resolved if case.complaint_status == 'Closed' else timezone.now()
    if not started or not ended or ended < started or ended > timezone.now():
        return None
    return int((ended - started).total_seconds() // 86400)


def _report_datetime(value) -> str:
    if not value:
        return ''
    return timezone.localtime(value).isoformat()


def _export_date(value):
    """Return a genuine local Excel date; cell formatting controls its display."""
    return timezone.localtime(value).date() if value else ''


def _export_upper(value: Any) -> Any:
    return value.upper() if isinstance(value, str) else value


def _report_status(case: ParsedMessage) -> tuple[str, bool]:
    if case.complaint_status == 'Closed':
        return 'CLOSED', False
    if case.complaint_status == 'Reopened':
        return 'REOPENED', False
    return 'OPEN', case.complaint_status == 'Review Needed'


def _safe_report_link(value: Any) -> str:
    text = str(value or '').strip()
    return text if urlparse(text).scheme.casefold() in {'http', 'https'} else ''


def serialize_report_case(case: ParsedMessage) -> dict[str, Any]:
    """Return only the explicitly approved management-report fields."""
    status, needs_details = _report_status(case)
    control = case.complaint_control
    if not hasattr(case, 'complaint_timing'):
        from core.services.complaint_timing import hydrate_timing
        hydrate_timing([case])
    return {
        'complaint_id': control.reference_number or '',
        'date_reported': _report_datetime(case.timestamp or case.created_at),
        'status': status,
        'needs_details': needs_details,
        'customer_name': case.customer_name,
        'customer_id': case.customer_id,
        'phone_number': case.customer_phone,
        'secondary_phone_number': case.secondary_phone,
        'county': case.county,
        'constituency': case.sub_county,
        'village': case.village,
        'reported_by': case.sender,
        'branch_region': (
            control.branch_ref.name if control.branch_ref_id else case.branch_region
        ),
        'complaint_category': (
            control.category.label if control.category_id else case.complaint_category
        ),
        'complaint_description': case.complaint_description,
        'source': case.source,
        'gps_link': _safe_report_link(case.gps_link),
        'attachments': int(getattr(case, 'successful_attachment_count', 0) or 0),
        'resolution_details': case.resolution_details,
        'resolution_comments': resolution_comments_text(case),
        'date_resolved': _report_datetime(case.date_resolved),
        'days_open': _days_open(case),
        'resolution_history_count': len(resolution_history_entries(case)),
        'resolution_hours': case.complaint_timing['resolution_hours'],
        'hb_response_hours': case.complaint_timing['hb_response_hours'],
    }


def _report_queryset():
    return _base_queryset().annotate(
        successful_attachment_count=Count(
            'complaint_evidence',
            filter=Q(complaint_evidence__upload_status='success'),
            distinct=True,
        ),
    )


def _apply_report_filters(queryset, filters: dict[str, Any], *, timing=True):
    status = str(filters.get('status') or '').strip().casefold()
    if status in {'open', 'pending'}:
        queryset = queryset.exclude(complaint_status__in=['Closed', 'Reopened'])
    elif status == 'reopened':
        queryset = queryset.filter(complaint_status='Reopened')
    elif status in {'closed', 'resolved'}:
        queryset = queryset.filter(complaint_status='Closed')
    elif status:
        raise ComplaintCaseError('Status must be Open, Reopened, or Closed.')
    branch = str(filters.get('branch') or '').strip()
    if branch.casefold() == 'not provided':
        queryset = queryset.filter(
            complaint_control__branch_ref__isnull=True,
        ).filter(Q(branch_region='') | Q(branch_region__isnull=True))
    elif branch:
        queryset = queryset.filter(
            Q(complaint_control__branch_ref__name__iexact=branch)
            | Q(complaint_control__branch_ref__isnull=True, branch_region__iexact=branch)
        )
    category = str(filters.get('category') or '').strip()
    if category.casefold() == 'not provided':
        queryset = queryset.filter(
            complaint_control__category__isnull=True,
        ).filter(Q(complaint_category='') | Q(complaint_category__isnull=True))
    elif category:
        queryset = queryset.filter(
            Q(complaint_control__category__label__iexact=category)
            | Q(complaint_control__category__isnull=True, complaint_category__iexact=category)
        )
    date_from = _parse_filter_date(filters.get('date_from'), 'Start date')
    date_to = _parse_filter_date(filters.get('date_to'), 'End date', end=True)
    if date_from and date_to and date_from > date_to:
        raise ComplaintCaseError('End date must not be before start date.')
    search = str(filters.get('search') or '').strip()
    if search:
        queryset = queryset.filter(
            Q(complaint_control__reference_number__icontains=search)
            | Q(customer_name__icontains=search)
            | Q(customer_id__icontains=search)
            | Q(customer_phone__icontains=search)
            | Q(complaint_description__icontains=search)
        )
    if not timing:
        return queryset
    basis = str(filters.get('date_basis') or 'reported')
    metric = str(filters.get('metric') or '')
    if basis not in {'reported', 'resolved', 'response', 'closures', 'reopened'}:
        raise ComplaintCaseError('Select Reported or Resolved dates.')
    if metric not in {'', 'received', 'reported_closed', 'reported_open', 'closures', 'open_age', 'resolution', 'on_time', 'late', 'hb_response', 'reopened'}:
        raise ComplaintCaseError('This chart selection is unavailable.')
    if metric == 'open_age' and filters.get('metric_value') not in {'under_3', '3_7', '8_14', 'over_14'}:
        raise ComplaintCaseError('This age selection is unavailable.')
    expected_basis = {'received': 'reported', 'closures': 'closures', 'open_age': 'reported',
                      'reported_closed': 'reported', 'reported_open': 'reported',
                      'resolution': 'resolved', 'on_time': 'resolved', 'late': 'resolved',
                      'hb_response': 'response', 'reopened': 'reopened'}
    if metric and expected_basis[metric] != basis:
        raise ComplaintCaseError('The chart and date selection do not match.')
    if not metric and basis in {'reported', 'resolved'}:
        field = 'report_date' if basis == 'reported' else 'date_resolved'
        if basis == 'resolved':
            queryset = queryset.filter(complaint_status='Closed')
        if date_from:
            queryset = queryset.filter(**{f'{field}__gte': date_from})
        if date_to:
            queryset = queryset.filter(**{f'{field}__lte': date_to})
        return queryset
    from core.services.complaint_timing import timed_cases, matches_timing
    ids = [case.pk for case in timed_cases(queryset) if matches_timing(case, filters, date_from, date_to)]
    return queryset.filter(pk__in=ids)


def validate_report_filters(filters):
    """Validate export selections before issuing a download URL."""
    _apply_report_filters(_base_queryset().none(), filters)


def encode_export_filters(filters):
    """Keep search values out of URL logs; the outer token still expires/re-authorizes."""
    import base64
    import hashlib
    import json
    from cryptography.fernet import Fernet
    from django.conf import settings
    key = base64.urlsafe_b64encode(hashlib.sha256(
        ('complaint-export-filters:' + settings.SECRET_KEY).encode()).digest())
    return Fernet(key).encrypt(json.dumps(filters).encode()).decode()


def decode_export_filters(value):
    import base64
    import hashlib
    import json
    from cryptography.fernet import Fernet, InvalidToken
    from django.conf import settings
    for secret in [settings.SECRET_KEY, *settings.SECRET_KEY_FALLBACKS]:
        key = base64.urlsafe_b64encode(hashlib.sha256(
            ('complaint-export-filters:' + secret).encode()).digest())
        try:
            return json.loads(Fernet(key).decrypt(value.encode()))
        except InvalidToken:
            continue
    raise ValueError('This download link has expired.')


def complaint_report_page(
    *, filters: dict[str, Any], page: Any = 1, page_size: Any = 50,
    sort: str = '-date_reported',
) -> dict[str, Any]:
    queryset = _apply_report_filters(_report_queryset(), filters)
    requested_sort = str(sort or '-date_reported').strip()
    descending = requested_sort.startswith('-')
    sort_key = requested_sort.lstrip('-')
    if sort_key not in REPORT_SORT_FIELDS:
        raise ComplaintCaseError('The selected report ordering is unavailable.')
    try:
        requested_page = max(1, int(page or 1))
        bounded_size = max(1, min(int(page_size or 50), 100))
    except (TypeError, ValueError):
        raise ComplaintCaseError('The requested report page is invalid.')
    if sort_key == 'days_open':
        # Days open is the inverse of the start timestamp for every open case.
        ordering = 'report_date' if descending else '-report_date'
    elif sort_key == 'status':
        queryset = queryset.annotate(report_status_order=Case(
            When(complaint_status='Closed', then=Value(1)),
            default=Value(0), output_field=IntegerField(),
        ))
        ordering = ('-' if descending else '') + 'report_status_order'
    else:
        ordering = ('-' if descending else '') + REPORT_SORT_FIELDS[sort_key]
    queryset = queryset.order_by(ordering, '-pk')
    count = queryset.count()
    pages = max(1, (count + bounded_size - 1) // bounded_size)
    current_page = min(requested_page, pages)
    offset = (current_page - 1) * bounded_size
    from core.services.complaint_timing import hydrate_timing
    cases = hydrate_timing(list(queryset[offset:offset + bounded_size]))
    return {
        'results': [serialize_report_case(case) for case in cases],
        'count': count,
        'page': current_page,
        'page_size': bounded_size,
    }


def _source_breakdown(queryset, *, canonical: str, legacy: str) -> list[dict[str, Any]]:
    counts = Counter()
    for canonical_value, legacy_value in queryset.values_list(canonical, legacy):
        counts[str(canonical_value or legacy_value or 'Not provided')] += 1
    return [
        {'label': label, 'count': count}
        for label, count in sorted(counts.items(), key=lambda item: (-item[1], item[0].casefold()))
    ]


def _timing_summary(queryset, filters, granularity):
    from core.services.complaint_timing import timed_cases, timing_summary
    now = timezone.now()
    result = timing_summary(
        timed_cases(_apply_report_filters(queryset, filters, timing=False), now=now),
        date_from=_parse_filter_date(filters.get('date_from'), 'Start date'),
        date_to=_parse_filter_date(filters.get('date_to'), 'End date', end=True),
        granularity=granularity, now=now,
    )
    for key in ('activity', 'reported_outcomes', 'resolution_trend', 'response_trend', 'reopenings'):
        if len(result[key]) > REPORT_MAX_TIME_BUCKETS:
            raise ComplaintCaseError('Narrow the date range or choose a broader time grouping.')
    return result


def complaint_report_summary(
    *, filters: dict[str, Any] | None = None, granularity: str = 'month',
    base_queryset=None,
) -> dict[str, Any]:
    granularity = str(granularity or 'month').strip().casefold()
    if granularity not in REPORT_TIME_GROUPS:
        raise ComplaintCaseError('Time grouping must be Day, Week, Month or Year.')
    base_queryset = _base_queryset() if base_queryset is None else base_queryset
    queryset = _apply_report_filters(base_queryset, filters or {})
    # Date type defines the cards/table cohort only. Category and reported
    # history graphs always use reporting dates; timing graphs own their bases.
    graph_queryset = queryset if (filters or {}).get('metric') else _apply_report_filters(base_queryset, {
        **(filters or {}), 'date_basis': 'reported', 'metric': '',
    })
    metrics = queryset.aggregate(
        total=Count('pk'),
        pending=Count('pk', filter=~Q(complaint_status='Closed')),
        resolved=Count('pk', filter=Q(complaint_status='Closed')),
        needs_details=Count('pk', filter=Q(complaint_status='Review Needed')),
    )
    truncation, label_format = REPORT_TIME_GROUPS[granularity]
    time_rows = list(graph_queryset.annotate(
        report_time_bucket=truncation('report_date', tzinfo=timezone.get_current_timezone()),
    ).values('report_time_bucket').annotate(count=Count('pk')).order_by(
        'report_time_bucket',
    )[:REPORT_MAX_TIME_BUCKETS + 1])
    if len(time_rows) > REPORT_MAX_TIME_BUCKETS:
        raise ComplaintCaseError(
            'This chart contains too many time periods. Narrow the reported date range '
            'or choose a broader time grouping.'
        )
    by_time = [
        {
            'label': timezone.localtime(row['report_time_bucket']).strftime(label_format),
            'count': row['count'],
        }
        for row in time_rows if row['report_time_bucket']
    ]
    from core.services.complaint_timing import timed_cases, timing_summary
    now = timezone.now()
    card_timing = timing_summary(timed_cases(queryset, now=now), now=now)['timing']
    return {
        **metrics,
        'card_timing': card_timing,
        **_timing_summary(base_queryset, filters or {}, granularity),
        'by_branch': _source_breakdown(
            graph_queryset, canonical='complaint_control__branch_ref__name', legacy='branch_region',
        ),
        'by_category': _source_breakdown(
            graph_queryset, canonical='complaint_control__category__label', legacy='complaint_category',
        ),
        'by_time': by_time,
        'time_granularity': granularity,
        'filter_options': {
            'branches': _source_breakdown(
                base_queryset,
                canonical='complaint_control__branch_ref__name', legacy='branch_region',
            ),
            'categories': _source_breakdown(
                base_queryset,
                canonical='complaint_control__category__label', legacy='complaint_category',
            ),
        },
    }


def serialize_register_case(case: ParsedMessage, groups: dict[str, GroupSheetConfiguration]) -> dict[str, Any]:
    control = case.complaint_control
    assigned = control.assigned_to
    assigned_label = assigned.get_full_name().strip() or assigned.get_username() if assigned else ''
    projection_enabled = _projection_enabled(case.group_id, groups)
    return {
        'id': str(case.pk), 'case_id': case.message_id,
        'reference_number': control.reference_number,
        'group_id': str(case.group_id), 'group_label': _group_label(case.group_id, groups),
        'customer_name': case.customer_name, 'customer_phone': case.customer_phone,
        'customer_id': case.customer_id, 'branch': case.branch_region,
        'category': control.category.label if control.category_id else case.complaint_category,
        'description': case.complaint_description,
        'status': 'Resolved' if case.complaint_status == 'Closed' else 'Pending',
        'stored_status': case.complaint_status or 'Open',
        'needs_details': case.complaint_status == 'Review Needed',
        'priority': control.priority,
        'assigned_to': assigned_label, 'reported_by': case.sender,
        'reported_at': format_datetime(case.timestamp), 'recorded_at': format_datetime(case.created_at),
        'resolved_at': format_datetime(case.date_resolved), 'days_open': _days_open(case),
        'resolution_details': case.resolution_details, 'customer_match_status': control.customer_match_status,
        'hb_comment_count': case.hb_comment_count,
        'sla': sla_payload(control, case), 'revision': control.revision,
        'sheet_projection_enabled': projection_enabled,
        'sync_status': _sync_state(case, groups),
    }


def _breakdown(queryset, field: str, *, groups=None) -> list[dict[str, Any]]:
    rows = queryset.values(field).annotate(count=Count('pk')).order_by('-count', field)
    values = []
    for row in rows:
        value = str(row[field] or 'Not set')
        if field == 'group_id' and groups is not None:
            value = _group_label(value, groups)
        values.append({'label': value, 'count': row['count']})
    return values


def register_overview() -> dict[str, Any]:
    groups = _group_rows()
    queryset = _base_queryset()
    now = timezone.now()
    disabled = {group_id for group_id, row in groups.items() if not row.complaint_sheet_projection_enabled}
    metrics = queryset.aggregate(
        total=Count('pk'),
        pending=Count('pk', filter=~Q(complaint_status='Closed')),
        resolved=Count('pk', filter=Q(complaint_status='Closed')),
        needs_details=Count('pk', filter=Q(complaint_status='Review Needed')),
        overdue=Count('pk', filter=~Q(complaint_status='Closed') & Q(complaint_control__sla_due_at__lt=now)),
        high_priority=Count('pk', filter=~Q(complaint_status='Closed') & Q(complaint_control__priority='high')),
        sync_attention=Count('pk', filter=~Q(group_id__in=disabled) & Q(complaint_control__sync_status__in={'pending', 'failed'})),
        suspended=Count('pk', filter=Q(group_id__in=disabled) & Q(complaint_control__sync_status__in={'pending', 'failed'})),
    )
    category_counts = Counter()
    for category_label, legacy_label in queryset.values_list(
        'complaint_control__category__label', 'complaint_category',
    ):
        category_counts[str(category_label or legacy_label or 'Not set')] += 1
    category_filters = set(category_counts)
    category_filters.update(ComplaintCategory.objects.filter(active=True).values_list('label', flat=True))
    return {
        'metrics': metrics,
        'breakdowns': {
            'groups': _breakdown(queryset, 'group_id', groups=groups),
            'branches': _breakdown(queryset, 'branch_region'),
            'categories': [
                {'label': label, 'count': count}
                for label, count in category_counts.most_common()
            ],
            'priorities': _breakdown(queryset, 'complaint_control__priority'),
        },
        'filters': {
            'categories': sorted(category_filters, key=str.casefold),
            'statuses': ['pending', 'resolved'],
        },
    }


def register_page(*, filters: dict[str, Any], page: Any = 1, page_size: Any = 50, sort: str = '-reported_at') -> dict[str, Any]:
    groups = _group_rows()
    queryset = _apply_filters(_base_queryset(), filters, groups)
    requested_sort = str(sort or '-reported_at').strip()
    descending = requested_sort.startswith('-')
    sort_key = requested_sort.lstrip('-')
    if sort_key not in SORT_FIELDS:
        raise ComplaintCaseError('The selected case ordering is unavailable.')
    ordering = ('-' if descending else '') + SORT_FIELDS[sort_key]
    queryset = queryset.order_by(ordering, '-pk')
    try:
        requested_page = max(1, int(page or 1))
        bounded_size = max(10, min(int(page_size or 50), 100))
    except (TypeError, ValueError):
        raise ComplaintCaseError('The requested register page is invalid.')
    total = queryset.count()
    pages = max(1, (total + bounded_size - 1) // bounded_size)
    current = min(requested_page, pages)
    offset = (current - 1) * bounded_size
    return {
        'items': [serialize_register_case(case, groups) for case in queryset[offset:offset + bounded_size]],
        'pagination': {'page': current, 'pages': pages, 'page_size': bounded_size, 'total': total},
        'start_index': offset + 1,
    }


def register_case(case_uuid: str) -> dict[str, Any]:
    from core.services.complaint_cases import complaint_history
    groups = _group_rows()
    case = _base_queryset().filter(pk=case_uuid).first()
    if not case:
        raise ComplaintCaseError('Complaint case was not found.')
    payload = serialize_register_case(case, groups)
    payload['updates'] = complaint_history(case)
    updates = list(case.case_updates.filter(new_status__in=['Closed', 'Reopened']).exclude(source='mini_app_comment'))
    payload['resolution_comments'] = [serialize_update(update) for update in case.case_updates.filter(source='mini_app_comment').order_by('-created_at', '-pk')]
    resolution = next((item for item in updates if item.new_status == 'Closed'), None)
    reopen = next((item for item in updates if item.new_status == 'Reopened'), None)
    payload['latest_resolution'] = serialize_update(resolution) if resolution else None
    payload['latest_reopen'] = serialize_update(reopen) if reopen else None
    return payload


def _excel_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) else value


def export_register_xlsx(*, actor, request_id: str, filters=None) -> tuple[bytes, int]:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    groups = _group_rows()
    queryset = (_apply_report_filters(_base_queryset(), filters) if filters is not None else _base_queryset()).order_by('-timestamp', '-pk')
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'Complaint Cases'
    sheet.append(EXPORT_FIELDS)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    count = 0
    from core.services.complaint_timing import timed_cases
    for count, case in enumerate(timed_cases(queryset), start=1):
        row = serialize_report_case(case)
        sheet.append(tuple(_excel_text(value) for value in (
            count, _export_upper(row['complaint_id']),
            _export_date(case.timestamp or case.created_at),
            _export_upper(row['status']), _export_upper(row['customer_name']),
            row['customer_id'], row['phone_number'], row['secondary_phone_number'],
            _export_upper(row['county']), _export_upper(row['constituency']),
            _export_upper(row['village']), _export_upper(row['branch_region']),
            _export_upper(row['reported_by']), _export_upper(row['complaint_category']),
            row['complaint_description'], row['gps_link'], latest_resolution_text(case),
            resolution_comments_text(case), _export_date(case.date_resolved), row['days_open'], resolution_history_text(case),
            row['resolution_hours'], row['hb_response_hours'],
        )))
        sheet.cell(row=count + 1, column=3).number_format = 'dd-mmm-yyyy'
        sheet.cell(row=count + 1, column=19).number_format = 'dd-mmm-yyyy'
        if row['gps_link']:
            gps_cell = sheet.cell(row=count + 1, column=16)
            gps_cell.hyperlink = row['gps_link']
            gps_cell.style = 'Hyperlink'
        status_styles = {
            'OPEN': ('FEF3C7', '92400E'),
            'REOPENED': ('FFEDD5', '9A3412'),
            'CLOSED': ('DCFCE7', '166534'),
        }
        fill_colour, font_colour = status_styles.get(row['status'], ('FFFFFF', '111827'))
        status_cell = sheet.cell(row=count + 1, column=4)
        status_cell.fill = PatternFill(fill_type='solid', fgColor=fill_colour)
        status_cell.font = Font(color=font_colour, bold=True)
    sheet.freeze_panes = 'A2'
    sheet.auto_filter.ref = sheet.dimensions
    output = BytesIO()
    workbook.save(output)

    from core.services.compliance_audit import record_event
    record_event(
        workflow='complaint_cases', action='register.exported', category='data_export', origin='human',
        subject_type='complaint_register', subject_id='global', actor=actor, authority_user=actor,
        request_id=request_id, source_model='ParsedMessage', source_event_id=request_id,
        deduplication_key=f'complaint-register-export:{actor.pk}:{request_id}',
        after_values={'scope': 'filtered' if filters is not None else 'all_groups', 'row_count': count, 'fields': list(EXPORT_FIELDS)},
        sensitive=True,
    )
    return output.getvalue(), count


def export_filename(*, filtered=False) -> str:
    stamp = timezone.localtime(timezone.now()).strftime('%Y-%m-%d')
    scope = 'Results' if filtered else 'All-Groups'
    return re.sub(r'[^A-Za-z0-9_.-]+', '-', f'Complaint-Cases-{scope}-{stamp}.xlsx')
