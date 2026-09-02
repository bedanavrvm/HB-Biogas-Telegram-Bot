"""Organization-wide, read-only Complaint Cases register and XLSX export."""
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, time, timedelta
from io import BytesIO
from typing import Any
from urllib.parse import urlparse

from django.db.models import Case, Count, IntegerField, Q, Value, When
from django.db.models.functions import Coalesce, TruncDay, TruncMonth, TruncWeek, TruncYear
from django.utils import timezone
from django.utils.dateparse import parse_date

from core.models import ComplaintCategory, GroupSheetConfiguration, ParsedMessage
from core.services.complaint_cases import ComplaintCaseError, format_datetime, sla_payload


EXPORT_FIELDS = (
    'Complaint ID', 'Customer Name', 'Phone Number', 'Customer ID', 'Branch',
    'Category', 'Complaint', 'Status', 'Reported At', 'Resolved At',
    'Days Open', 'Resolution',
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
    return ParsedMessage.objects.filter(complaint_control__isnull=False).annotate(
        report_date=Coalesce('timestamp', 'created_at'),
    ).select_related(
        'complaint_control__category', 'complaint_control__branch_ref',
        'complaint_control__customer', 'complaint_control__assigned_to',
    )


def _parse_filter_date(value: Any, label: str, *, end: bool = False):
    text = str(value or '').strip()
    if not text:
        return None
    parsed = parse_date(text)
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


def _days_open(case: ParsedMessage) -> int:
    started = case.timestamp or case.created_at
    ended = case.date_resolved if case.complaint_status == 'Closed' and case.date_resolved else timezone.now()
    return max(0, int((ended - started).total_seconds() // 86400)) if started else 0


def _report_datetime(value) -> str:
    if not value:
        return ''
    return timezone.localtime(value).isoformat()


def _report_status(case: ParsedMessage) -> tuple[str, bool]:
    return ('Resolved', False) if case.complaint_status == 'Closed' else (
        'Pending', case.complaint_status == 'Review Needed'
    )


def _safe_report_link(value: Any) -> str:
    text = str(value or '').strip()
    return text if urlparse(text).scheme.casefold() in {'http', 'https'} else ''


def serialize_report_case(case: ParsedMessage) -> dict[str, Any]:
    """Return only the explicitly approved management-report fields."""
    status, needs_details = _report_status(case)
    control = case.complaint_control
    return {
        'complaint_id': control.reference_number or '',
        'date_reported': _report_datetime(case.timestamp or case.created_at),
        'status': status,
        'needs_details': needs_details,
        'customer_name': case.customer_name,
        'customer_id': case.customer_id,
        'phone_number': case.customer_phone,
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
        'date_resolved': _report_datetime(case.date_resolved),
        'days_open': _days_open(case),
    }


def _report_queryset():
    return _base_queryset().annotate(
        successful_attachment_count=Count(
            'complaint_evidence',
            filter=Q(complaint_evidence__upload_status='success'),
            distinct=True,
        ),
    )


def _apply_report_filters(queryset, filters: dict[str, Any]):
    status = str(filters.get('status') or '').strip().casefold()
    if status == 'pending':
        queryset = queryset.exclude(complaint_status='Closed')
    elif status == 'resolved':
        queryset = queryset.filter(complaint_status='Closed')
    elif status:
        raise ComplaintCaseError('Status must be Pending or Resolved.')
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
    if date_from:
        queryset = queryset.filter(report_date__gte=date_from)
    if date_to:
        queryset = queryset.filter(report_date__lte=date_to)
    search = str(filters.get('search') or '').strip()
    if search:
        queryset = queryset.filter(
            Q(complaint_control__reference_number__icontains=search)
            | Q(customer_name__icontains=search)
            | Q(customer_id__icontains=search)
            | Q(customer_phone__icontains=search)
            | Q(complaint_description__icontains=search)
        )
    return queryset


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
    return {
        'results': [serialize_report_case(case) for case in queryset[offset:offset + bounded_size]],
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


def complaint_report_summary(
    *, filters: dict[str, Any] | None = None, granularity: str = 'month',
) -> dict[str, Any]:
    granularity = str(granularity or 'month').strip().casefold()
    if granularity not in REPORT_TIME_GROUPS:
        raise ComplaintCaseError('Time grouping must be Day, Week, Month or Year.')
    base_queryset = _base_queryset()
    queryset = _apply_report_filters(base_queryset, filters or {})
    metrics = queryset.aggregate(
        total=Count('pk'),
        pending=Count('pk', filter=~Q(complaint_status='Closed')),
        resolved=Count('pk', filter=Q(complaint_status='Closed')),
        needs_details=Count('pk', filter=Q(complaint_status='Review Needed')),
    )
    truncation, label_format = REPORT_TIME_GROUPS[granularity]
    time_rows = list(queryset.annotate(
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
    return {
        **metrics,
        'by_branch': _source_breakdown(
            queryset, canonical='complaint_control__branch_ref__name', legacy='branch_region',
        ),
        'by_category': _source_breakdown(
            queryset, canonical='complaint_control__category__label', legacy='complaint_category',
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
    groups = _group_rows()
    case = _base_queryset().filter(pk=case_uuid).first()
    if not case:
        raise ComplaintCaseError('Complaint case was not found.')
    return serialize_register_case(case, groups)


def _excel_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) else value


def export_register_xlsx(*, actor, request_id: str) -> tuple[bytes, int]:
    from openpyxl import Workbook
    from openpyxl.styles import Font

    groups = _group_rows()
    queryset = _base_queryset().order_by('-timestamp', '-pk')
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = 'Complaint Cases'
    sheet.append(EXPORT_FIELDS)
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    count = 0
    for case in queryset.iterator(chunk_size=500):
        row = serialize_register_case(case, groups)
        sheet.append(tuple(_excel_text(value) for value in (
            row['reference_number'], row['customer_name'], row['customer_phone'],
            row['customer_id'], row['branch'], row['category'], row['description'],
            row['status'], row['reported_at'], row['resolved_at'],
            row['days_open'], row['resolution_details'],
        )))
        count += 1
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
        after_values={'scope': 'all_groups', 'row_count': count, 'fields': list(EXPORT_FIELDS)},
        sensitive=True,
    )
    return output.getvalue(), count


def export_filename() -> str:
    stamp = timezone.localtime(timezone.now()).strftime('%Y-%m-%d')
    return re.sub(r'[^A-Za-z0-9_.-]+', '-', f'Complaint-Cases-All-Groups-{stamp}.xlsx')
