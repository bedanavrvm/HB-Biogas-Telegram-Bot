"""Controlled, read-only reporting for the Jawabu Portal.

This module deliberately exposes a small catalogue over the canonical Portal
case model.  It is not a generic ORM/SQL query builder: a browser can only
choose approved field keys and approved operations.  In particular, records
from TAT, SPIN and Complaint Cases are not joined by mutable identifiers.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Any, Iterable

from django.db import IntegrityError, transaction
from django.db.models import Avg, Count, DecimalField, IntegerField, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce, TruncDay, TruncMonth
from django.utils import timezone
from django.utils.dateparse import parse_date
from openpyxl import Workbook
from openpyxl.styles import Font

from core.models import (
    ComplianceAuditEvent,
    JawabuFarmerMaster,
    MediaAttachment,
    ParsedInvoice,
    PortalReportChart,
    PortalReportDefinition,
)
from core.services.compliance_audit import record_event


SOURCE_PORTAL_CASES = PortalReportDefinition.SOURCE_PORTAL_CASES
MAX_SELECTED_FIELDS = 18
MAX_FILTERS = 10
MAX_CHARTS = 6
MAX_TABLE_ROWS = 2_000
PAGE_SIZE = 50
MAX_CHART_BUCKETS = 100
DATETIME_FILTER_FIELDS = frozenset({'created_at', 'updated_at'})

logger = logging.getLogger(__name__)


class PortalReportingError(ValueError):
    """A safe validation or stale-version error for Portal report actions."""


@dataclass(frozen=True)
class ReportField:
    key: str
    label: str
    expression: str
    value_type: str
    category: str
    filter_operators: tuple[str, ...] = ()
    aggregations: tuple[str, ...] = ()
    sortable: bool = True
    derived: bool = False

    @property
    def filterable(self) -> bool:
        return bool(self.filter_operators)

    @property
    def groupable(self) -> bool:
        return self.value_type in {'choice', 'text', 'date'}


_TEXT = ('equals', 'contains', 'in')
_CHOICE = ('equals', 'in')
_DATE = ('equals', 'before', 'after', 'between')
_NUMBER = ('equals', 'greater_than', 'less_than', 'between')

# This is the reporting contract.  Do not add raw JSON, comments, GPS, Drive
# references, media, or audit/event payloads here: they are deliberately not
# reportable even to IT through the Mini App.
PORTAL_REPORT_FIELDS: tuple[ReportField, ...] = (
    ReportField('case_id', 'Case ID', 'id', 'text', 'Case', ('equals', 'in')),
    ReportField('customer_name', 'Customer name', 'customer_name', 'text', 'Customer', _TEXT),
    ReportField('national_id', 'National ID', 'national_id', 'text', 'Customer', _TEXT),
    ReportField('primary_phone', 'Primary phone', 'primary_phone', 'text', 'Customer', _TEXT),
    ReportField('customer_no', 'Customer number', 'customer_no', 'text', 'Customer', _TEXT),
    ReportField('branch', 'Branch', 'branch', 'choice', 'Location', _CHOICE),
    ReportField('county', 'County', 'county', 'choice', 'Location', _CHOICE),
    ReportField('sub_county', 'Constituency / sub-county', 'sub_county', 'text', 'Location', _TEXT),
    ReportField('village', 'Village', 'village', 'text', 'Location', _TEXT),
    ReportField('hbg_visit_date', 'HBG visit date', 'hbg_visit_date', 'date', 'Workflow', _DATE),
    ReportField('jbl_visit_date', 'JBL visit date', 'jbl_visit_date', 'date', 'Workflow', _DATE),
    ReportField('jbl_visit_status', 'JBL visit status', 'jbl_visit_status', 'choice', 'Workflow', _CHOICE),
    ReportField('credit_decision', 'Credit decision', 'credit_decision', 'choice', 'Workflow', _CHOICE),
    ReportField('final_decision', 'Final decision', 'final_decision', 'choice', 'Workflow', _CHOICE),
    ReportField('workflow_state', 'Current pipeline state', 'workflow_state', 'choice', 'Workflow', _CHOICE),
    ReportField('requisition_date', 'Requisition date', 'requisition_date', 'date', 'Operations', _DATE),
    ReportField('order_number', 'Order number', 'order_number', 'text', 'Operations', _TEXT),
    ReportField('invoice_number', 'Invoice number', 'invoice_number', 'text', 'Operations', _TEXT),
    ReportField('invoice_date', 'Invoice date', 'invoice_date', 'date', 'Operations', _DATE),
    ReportField('status', 'Record status', 'status', 'choice', 'Operations', _CHOICE),
    ReportField('created_at', 'Created at', 'created_at', 'date', 'Operations', _DATE),
    ReportField('updated_at', 'Last updated', 'updated_at', 'date', 'Operations', _DATE),
    ReportField('deposit_paid_hbg', 'HBG deposit', 'deposit_paid_hbg', 'number', 'Finance', _NUMBER, ('sum', 'average')),
    ReportField('system_deposit_paid_jbl', 'JBL deposit', 'system_deposit_paid_jbl', 'number', 'Finance', _NUMBER, ('sum', 'average')),
    ReportField('invoice_amount', 'Invoice amount', 'invoice_amount', 'number', 'Finance', _NUMBER, ('sum', 'average')),
    ReportField('discount', 'Discount', 'discount', 'number', 'Finance', _NUMBER, ('sum', 'average')),
    ReportField('payment', 'HBG payment / deposit', 'payment', 'number', 'Finance', _NUMBER, ('sum', 'average')),
    ReportField('balance_due', 'Balance due', 'balance_due', 'number', 'Finance', _NUMBER, ('sum', 'average')),
    ReportField('matched_invoice_count', 'Matched invoice count', 'matched_invoice_count', 'number', 'Derived', _NUMBER, ('sum', 'average'), derived=True),
    ReportField('jbl_media_count', 'JBL media count', 'jbl_media_count', 'number', 'Derived', _NUMBER, ('sum', 'average'), derived=True),
)
_FIELD_BY_KEY = {field.key: field for field in PORTAL_REPORT_FIELDS}


def catalogue_payload() -> dict[str, Any]:
    """Return the UI catalogue without Django field names or relation paths."""
    categories: dict[str, list[dict[str, Any]]] = {}
    for field in PORTAL_REPORT_FIELDS:
        categories.setdefault(field.category, []).append({
            'key': field.key,
            'label': field.label,
            'type': field.value_type,
            'filterable': field.filterable,
            'groupable': field.groupable,
            'sortable': field.sortable,
            'operators': list(field.filter_operators),
            'aggregations': ['count', *field.aggregations] if field.value_type == 'number' else ['count'],
            'derived': field.derived,
        })
    return {
        'source': {'key': SOURCE_PORTAL_CASES, 'label': 'Portal customer cases'},
        'categories': [{'label': key, 'fields': values} for key, values in categories.items()],
        'limits': {
            'fields': MAX_SELECTED_FIELDS,
            'filters': MAX_FILTERS,
            'charts': MAX_CHARTS,
            'table_rows': MAX_TABLE_ROWS,
            'chart_buckets': MAX_CHART_BUCKETS,
        },
    }


def _field(key: Any) -> ReportField:
    value = str(key or '').strip()
    field = _FIELD_BY_KEY.get(value)
    if not field:
        raise PortalReportingError('Choose a field from the approved Portal reporting catalogue.')
    return field


def _list_of_strings(value: Any, *, label: str, maximum: int) -> list[str]:
    if not isinstance(value, list):
        raise PortalReportingError(f'{label} must be a list.')
    values = [str(item or '').strip() for item in value]
    if not values or any(not item for item in values) or len(values) > maximum:
        raise PortalReportingError(f'Choose between 1 and {maximum} {label.lower()}.')
    if len(set(values)) != len(values):
        raise PortalReportingError(f'{label} cannot contain duplicates.')
    return values


def validate_configuration(value: Any) -> dict[str, Any]:
    """Normalize one report configuration and reject arbitrary query inputs."""
    if not isinstance(value, dict):
        raise PortalReportingError('Report configuration must be an object.')
    fields = _list_of_strings(value.get('fields'), label='Fields', maximum=MAX_SELECTED_FIELDS)
    for key in fields:
        _field(key)
    filters: list[dict[str, Any]] = []
    supplied_filters = value.get('filters') or []
    if not isinstance(supplied_filters, list) or len(supplied_filters) > MAX_FILTERS:
        raise PortalReportingError(f'Choose at most {MAX_FILTERS} filters.')
    for item in supplied_filters:
        if not isinstance(item, dict):
            raise PortalReportingError('Each filter must be an object.')
        field = _field(item.get('field'))
        operator = str(item.get('operator') or '').strip()
        if operator not in field.filter_operators:
            raise PortalReportingError(f'{field.label} does not support that filter.')
        filter_value = item.get('value')
        if operator == 'between':
            if not isinstance(filter_value, list) or len(filter_value) != 2:
                raise PortalReportingError(f'{field.label} needs a start and end value.')
            normalized = [_normalize_filter_scalar(field, part) for part in filter_value]
        elif operator == 'in':
            if not isinstance(filter_value, list) or not filter_value or len(filter_value) > 25:
                raise PortalReportingError(f'{field.label} needs between 1 and 25 values.')
            normalized = [_normalize_filter_scalar(field, part) for part in filter_value]
        else:
            normalized = _normalize_filter_scalar(field, filter_value)
        filters.append({'field': field.key, 'operator': operator, 'value': normalized})
    ordering = value.get('ordering') or {}
    if not isinstance(ordering, dict):
        raise PortalReportingError('Report ordering must be an object.')
    ordering_field = str(ordering.get('field') or 'customer_name').strip()
    direction = str(ordering.get('direction') or 'asc').strip().lower()
    field = _field(ordering_field)
    if not field.sortable or field.derived:
        raise PortalReportingError('Choose a direct Portal field for ordering.')
    if direction not in {'asc', 'desc'}:
        raise PortalReportingError('Ordering must be ascending or descending.')
    return {'fields': fields, 'filters': filters, 'ordering': {'field': field.key, 'direction': direction}}


def _normalize_filter_scalar(field: ReportField, value: Any) -> str:
    raw = str(value or '').strip()
    if not raw:
        raise PortalReportingError(f'{field.label} needs a value.')
    if field.value_type == 'date':
        if not parse_date(raw):
            raise PortalReportingError(f'{field.label} must use a valid date.')
    elif field.value_type == 'number':
        try:
            Decimal(raw)
        except (InvalidOperation, ValueError):
            raise PortalReportingError(f'{field.label} must use a valid number.')
    return raw


def validate_charts(value: Any, *, selected_fields: Iterable[str]) -> list[dict[str, Any]]:
    if value in (None, ''):
        return []
    if not isinstance(value, list) or len(value) > MAX_CHARTS:
        raise PortalReportingError(f'Choose at most {MAX_CHARTS} charts.')
    selected = set(selected_fields)
    normalized: list[dict[str, Any]] = []
    for position, item in enumerate(value):
        if not isinstance(item, dict):
            raise PortalReportingError('Each chart must be an object.')
        chart_type = str(item.get('chart_type') or '').strip()
        if chart_type not in {PortalReportChart.TYPE_BAR, PortalReportChart.TYPE_DOUGHNUT, PortalReportChart.TYPE_LINE}:
            raise PortalReportingError('Choose a supported chart type.')
        dimension = _field(item.get('dimension_field'))
        aggregation = str(item.get('aggregation') or PortalReportChart.AGGREGATE_COUNT).strip()
        metric_key = str(item.get('metric_field') or '').strip()
        date_bucket = str(item.get('date_bucket') or '').strip()
        if dimension.key not in selected or not dimension.groupable:
            raise PortalReportingError('Choose a selected category or date field for each chart.')
        if chart_type == PortalReportChart.TYPE_LINE:
            if dimension.value_type != 'date':
                raise PortalReportingError('A line chart needs a date field.')
            if date_bucket not in {PortalReportChart.BUCKET_DAY, PortalReportChart.BUCKET_MONTH}:
                raise PortalReportingError('Choose day or month grouping for a line chart.')
        elif date_bucket:
            raise PortalReportingError('Date grouping is available only for line charts.')
        if aggregation == PortalReportChart.AGGREGATE_COUNT:
            if metric_key:
                raise PortalReportingError('Count charts do not need a numeric metric field.')
        else:
            metric = _field(metric_key)
            if metric.key not in selected or aggregation not in metric.aggregations:
                raise PortalReportingError('Choose a selected numeric metric supported by that aggregation.')
        title = str(item.get('title') or '').strip()[:100]
        normalized.append({
            'title': title,
            'chart_type': chart_type,
            'dimension_field': dimension.key,
            'metric_field': metric_key,
            'aggregation': aggregation,
            'date_bucket': date_bucket,
            'position': position,
        })
    return normalized


def _annotated_queryset(queryset):
    matched_invoices = ParsedInvoice.objects.filter(
        # ParsedInvoice keeps statuses as explicit model choices rather than
        # public constants.  Use the canonical persisted value here.
        matched_farmer_id=OuterRef('pk'), status='matched',
    ).order_by().values('matched_farmer_id').annotate(total=Count('pk')).values('total')[:1]
    jbl_media = MediaAttachment.objects.filter(
        jawabu_farmer_id=OuterRef('pk'), upload_status='success',
    ).order_by().values('jawabu_farmer_id').annotate(total=Count('pk')).values('total')[:1]
    return queryset.annotate(
        matched_invoice_count=Coalesce(Subquery(matched_invoices, output_field=IntegerField()), Value(0)),
        jbl_media_count=Coalesce(Subquery(jbl_media, output_field=IntegerField()), Value(0)),
    )


def scoped_case_queryset(*, user, access: dict | None):
    """Match the established Portal case read scope; no cross-workflow joins."""
    queryset = JawabuFarmerMaster.objects.filter(status='active')
    if not getattr(user, 'is_superuser', False):
        branches = [str(value).strip() for value in (access or {}).get('branches', []) if str(value).strip()]
        if branches:
            branch_scope = Q()
            for branch in branches:
                branch_scope |= Q(branch__iexact=branch)
            queryset = queryset.filter(branch_scope)
    return _annotated_queryset(queryset)


def _apply_filters(queryset, filters: Iterable[dict[str, Any]]):
    for item in filters:
        field = _field(item['field'])
        # The reporting editor intentionally accepts calendar dates.  Django
        # would otherwise compare a date such as 04-August against midnight of
        # a DateTimeField, which makes an "equals" filter appear to return no
        # records created later that day.
        expression = f'{field.expression}__date' if field.key in DATETIME_FILTER_FIELDS else field.expression
        operator = item['operator']
        value = item['value']
        if field.value_type == 'date':
            value = [parse_date(part) for part in value] if isinstance(value, list) else parse_date(value)
        elif field.value_type == 'number':
            value = [Decimal(part) for part in value] if isinstance(value, list) else Decimal(value)
        if operator == 'equals':
            queryset = queryset.filter(**{expression: value})
        elif operator == 'contains':
            queryset = queryset.filter(**{f'{expression}__icontains': value})
        elif operator == 'in':
            queryset = queryset.filter(**{f'{expression}__in': value})
        elif operator == 'before':
            queryset = queryset.filter(**{f'{expression}__lt': value})
        elif operator == 'after':
            queryset = queryset.filter(**{f'{expression}__gt': value})
        elif operator == 'greater_than':
            queryset = queryset.filter(**{f'{expression}__gt': value})
        elif operator == 'less_than':
            queryset = queryset.filter(**{f'{expression}__lt': value})
        elif operator == 'between':
            queryset = queryset.filter(**{f'{expression}__range': value})
    return queryset


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def definition_payload(definition: PortalReportDefinition) -> dict[str, Any]:
    config = validate_configuration(definition.configuration or {})
    return {
        'id': str(definition.pk),
        'title': definition.title,
        'source_key': definition.source_key,
        'configuration': config,
        'version': definition.version,
        'is_active': definition.is_active,
        'archived_at': definition.archived_at.isoformat() if definition.archived_at else None,
        'created_at': definition.created_at.isoformat() if definition.created_at else None,
        'updated_at': definition.updated_at.isoformat() if definition.updated_at else None,
        'charts': [
            {
                'id': str(chart.pk), 'title': chart.title, 'chart_type': chart.chart_type,
                'dimension_field': chart.dimension_field, 'metric_field': chart.metric_field,
                'aggregation': chart.aggregation, 'date_bucket': chart.date_bucket,
                'position': chart.position,
            }
            for chart in definition.charts.order_by('position', 'created_at')
        ],
    }


def _audit_key(action: str, actor, request_id: str, definition_id: str) -> str:
    return f'portal-report:{action}:{getattr(actor, "pk", "")}:{request_id or definition_id}:{definition_id}'


def _record_definition_event(*, action: str, definition, actor, request_id: str, before: dict | None, after: dict | None, metadata: dict | None = None):
    return record_event(
        workflow='portal', action=f'portal.report.{action}', category='configuration',
        subject_type='PortalReportDefinition', subject_id=str(definition.pk),
        deduplication_key=_audit_key(action, actor, request_id, str(definition.pk)),
        actor=actor, request_id=request_id, source_model='PortalReportDefinition',
        source_event_id=f'{definition.pk}:{action}:{definition.version}',
        before_values=before or {}, after_values=after or {}, metadata=metadata or {},
        sensitive=True,
    )


def _definition_summary(definition: PortalReportDefinition) -> dict[str, Any]:
    config = validate_configuration(definition.configuration or {})
    return {
        'title': definition.title,
        'version': definition.version,
        'fields': config['fields'],
        'filter_count': len(config['filters']),
        'chart_count': definition.charts.count(),
        'active': definition.is_active,
    }


def create_definition(*, payload: dict[str, Any], actor, request_id: str) -> tuple[PortalReportDefinition, bool]:
    title = str(payload.get('title') or '').strip()
    if not title or len(title) > 100:
        raise PortalReportingError('Enter a report title of up to 100 characters.')
    config = validate_configuration(payload.get('configuration') or {})
    charts = validate_charts(payload.get('charts') or [], selected_fields=config['fields'])
    request_id = str(request_id or '').strip()
    if request_id:
        existing = PortalReportDefinition.objects.filter(create_request_id=request_id).first()
        if existing:
            return existing, True
    try:
        with transaction.atomic():
            definition = PortalReportDefinition.objects.create(
                title=title, source_key=SOURCE_PORTAL_CASES, configuration=config,
                created_by=actor, create_request_id=request_id,
            )
            PortalReportChart.objects.bulk_create([
                PortalReportChart(definition=definition, **chart) for chart in charts
            ])
            _record_definition_event(
                action='created', definition=definition, actor=actor, request_id=request_id,
                before={}, after={'title': title, 'fields': config['fields'], 'chart_count': len(charts)},
            )
    except IntegrityError:
        if request_id:
            existing = PortalReportDefinition.objects.filter(create_request_id=request_id).first()
            if existing:
                return existing, True
        raise
    return definition, False


def update_definition(*, definition_id: str, payload: dict[str, Any], actor, request_id: str) -> tuple[PortalReportDefinition, bool]:
    expected_version = payload.get('version')
    try:
        expected_version = int(expected_version)
    except (TypeError, ValueError):
        raise PortalReportingError('Refresh the report before saving it.')
    title = str(payload.get('title') or '').strip()
    if not title or len(title) > 100:
        raise PortalReportingError('Enter a report title of up to 100 characters.')
    config = validate_configuration(payload.get('configuration') or {})
    charts = validate_charts(payload.get('charts') or [], selected_fields=config['fields'])
    with transaction.atomic():
        definition = PortalReportDefinition.objects.select_for_update().prefetch_related('charts').filter(
            pk=definition_id, source_key=SOURCE_PORTAL_CASES,
        ).first()
        if not definition:
            raise PortalReportingError('This report definition is unavailable.')
        audit_key = _audit_key('updated', actor, request_id, str(definition.pk))
        if request_id and ComplianceAuditEvent.objects.filter(deduplication_key=audit_key).exists():
            return definition, True
        if not definition.is_active:
            raise PortalReportingError('Archived reports cannot be edited.')
        if definition.version != expected_version:
            raise PortalReportingError('This report changed while you were working. Refresh and review it before saving.')
        before = _definition_summary(definition)
        definition.title = title
        definition.configuration = config
        definition.version += 1
        definition.save(update_fields=['title', 'configuration', 'version', 'updated_at'])
        definition.charts.all().delete()
        PortalReportChart.objects.bulk_create([
            PortalReportChart(definition=definition, **chart) for chart in charts
        ])
        _record_definition_event(
            action='updated', definition=definition, actor=actor, request_id=request_id,
            before=before, after={'title': title, 'fields': config['fields'], 'chart_count': len(charts), 'version': definition.version},
        )
    return definition, False


def archive_definition(*, definition_id: str, version: Any, actor, request_id: str) -> tuple[PortalReportDefinition, bool]:
    try:
        expected_version = int(version)
    except (TypeError, ValueError):
        raise PortalReportingError('Refresh the report before archiving it.')
    with transaction.atomic():
        definition = PortalReportDefinition.objects.select_for_update().prefetch_related('charts').filter(pk=definition_id).first()
        if not definition:
            raise PortalReportingError('This report definition is unavailable.')
        audit_key = _audit_key('archived', actor, request_id, str(definition.pk))
        if request_id and ComplianceAuditEvent.objects.filter(deduplication_key=audit_key).exists():
            return definition, True
        if definition.version != expected_version:
            raise PortalReportingError('This report changed while you were working. Refresh and review it before archiving.')
        before = _definition_summary(definition)
        definition.is_active = False
        definition.archived_at = timezone.now()
        definition.archived_by = actor
        definition.version += 1
        definition.save(update_fields=['is_active', 'archived_at', 'archived_by', 'version', 'updated_at'])
        _record_definition_event(
            action='archived', definition=definition, actor=actor, request_id=request_id,
            before=before, after={'active': False, 'version': definition.version},
        )
    return definition, False


def _query_for_definition(definition: PortalReportDefinition, *, user, access: dict | None):
    if definition.source_key != SOURCE_PORTAL_CASES:
        raise PortalReportingError('This report source is no longer supported.')
    config = validate_configuration(definition.configuration or {})
    queryset = _apply_filters(scoped_case_queryset(user=user, access=access), config['filters'])
    ordering = config['ordering']
    expression = _field(ordering['field']).expression
    queryset = queryset.order_by(f'{"-" if ordering["direction"] == "desc" else ""}{expression}', 'id')
    return queryset, config


def run_definition(*, definition: PortalReportDefinition, user, access: dict | None, page: int = 1) -> dict[str, Any]:
    if not definition.is_active:
        raise PortalReportingError('This report is archived.')
    page = max(1, int(page or 1))
    queryset, config = _query_for_definition(definition, user=user, access=access)
    total = queryset.count()
    max_pages = max(1, min((min(total, MAX_TABLE_ROWS) + PAGE_SIZE - 1) // PAGE_SIZE, (MAX_TABLE_ROWS + PAGE_SIZE - 1) // PAGE_SIZE))
    page = min(page, max_pages)
    selected = [_field(key) for key in config['fields']]
    expressions = [field.expression for field in selected]
    rows = [
        {field.key: _json_value(raw.get(field.expression)) for field in selected}
        for raw in queryset[(page - 1) * PAGE_SIZE:page * PAGE_SIZE].values(*expressions)
    ]
    charts = []
    for chart in definition.charts.order_by('position', 'created_at'):
        try:
            charts.append(chart_payload(chart, queryset))
        except PortalReportingError:
            logger.warning(
                'Portal report chart requires review chart=%s definition=%s',
                chart.pk, definition.pk,
            )
            charts.append({
                'id': str(chart.pk),
                'title': chart.title or 'Unavailable chart',
                'type': chart.chart_type,
                'labels': [],
                'values': [],
                'dimension_label': '',
                'metric_label': '',
                'truncated': False,
                'error': 'This chart configuration needs review. The report rows are still available.',
            })
        except Exception:
            # A historical chart configuration must not make otherwise valid
            # filtered rows unavailable.  The client displays a stable
            # per-chart fallback while IT corrects the saved definition.
            logger.exception('Could not run Portal report chart=%s definition=%s', chart.pk, definition.pk)
            charts.append({
                'id': str(chart.pk),
                'title': chart.title or 'Unavailable chart',
                'type': chart.chart_type,
                'labels': [],
                'values': [],
                'dimension_label': '',
                'metric_label': '',
                'truncated': False,
                'error': 'This chart configuration needs review. The report rows are still available.',
            })
    return {
        'definition': definition_payload(definition),
        'columns': [{'key': field.key, 'label': field.label, 'type': field.value_type} for field in selected],
        'rows': rows,
        'total_rows': total,
        'shown_rows_limit': min(total, MAX_TABLE_ROWS),
        'pagination': {'page': page, 'page_size': PAGE_SIZE, 'pages': max_pages},
        'charts': charts,
        'run_at': timezone.now().isoformat(),
    }


def chart_payload(chart: PortalReportChart, queryset) -> dict[str, Any]:
    dimension = _field(chart.dimension_field)
    metric = _field(chart.metric_field) if chart.metric_field else None
    if chart.chart_type == PortalReportChart.TYPE_LINE:
        bucket = TruncDay(dimension.expression) if chart.date_bucket == PortalReportChart.BUCKET_DAY else TruncMonth(dimension.expression)
        grouped = queryset.exclude(**{f'{dimension.expression}__isnull': True}).annotate(_dimension=bucket).values('_dimension')
    else:
        grouped = queryset.exclude(**{f'{dimension.expression}': ''}).exclude(**{f'{dimension.expression}__isnull': True}).values(dimension.expression)
    if chart.aggregation == PortalReportChart.AGGREGATE_COUNT:
        grouped = grouped.annotate(value=Count('id'))
    elif chart.aggregation == PortalReportChart.AGGREGATE_SUM:
        decimal_output = DecimalField(max_digits=18, decimal_places=2)
        grouped = grouped.annotate(value=Coalesce(
            Sum(metric.expression),
            Value(Decimal('0'), output_field=decimal_output),
            output_field=decimal_output,
        ))
    else:
        grouped = grouped.annotate(value=Avg(metric.expression))
    grouped = grouped.order_by('-value')[:MAX_CHART_BUCKETS]
    labels, values = [], []
    for row in grouped:
        raw = row.get('_dimension') if chart.chart_type == PortalReportChart.TYPE_LINE else row.get(dimension.expression)
        labels.append(_json_value(raw) or 'Not recorded')
        value = row.get('value')
        values.append(float(value or 0))
    if chart.chart_type == PortalReportChart.TYPE_LINE:
        pairs = sorted(zip(labels, values), key=lambda item: item[0])
        labels, values = map(list, zip(*pairs)) if pairs else ([], [])
    return {
        'id': str(chart.pk),
        'title': chart.title or f'{dimension.label} by {chart.get_aggregation_display()}',
        'type': chart.chart_type,
        'labels': labels,
        'values': values,
        'dimension_label': dimension.label,
        'metric_label': 'Case count' if chart.aggregation == PortalReportChart.AGGREGATE_COUNT else metric.label,
        'truncated': len(labels) >= MAX_CHART_BUCKETS,
    }


def export_xlsx(*, definition: PortalReportDefinition, user, access: dict | None) -> bytes:
    if not definition.is_active:
        raise PortalReportingError('This report is archived.')
    queryset, config = _query_for_definition(definition, user=user, access=access)
    selected = [_field(key) for key in config['fields']]
    rows = list(queryset[:MAX_TABLE_ROWS].values(*[field.expression for field in selected]))
    workbook = Workbook()
    details = workbook.active
    details.title = 'Report details'
    details.append(['Report', definition.title])
    details.append(['Source', 'Portal customer cases'])
    details.append(['Definition version', definition.version])
    details.append(['Generated at', timezone.localtime().strftime('%d-%B-%Y %H:%M')])
    details.append(['Filters', _filter_description(config['filters']) or 'None'])
    details.append(['Rows exported', len(rows)])
    for cell in details[1]:
        cell.font = Font(bold=True)
    data_sheet = workbook.create_sheet('Data')
    data_sheet.append([field.label for field in selected])
    for cell in data_sheet[1]:
        cell.font = Font(bold=True)
    for row in rows:
        data_sheet.append([row.get(field.expression) for field in selected])
    for column in data_sheet.columns:
        letter = column[0].column_letter
        data_sheet.column_dimensions[letter].width = min(36, max(12, max(len(str(cell.value or '')) for cell in column) + 2))
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def _filter_description(filters: Iterable[dict[str, Any]]) -> str:
    values = []
    for item in filters:
        field = _field(item['field'])
        value = item['value']
        rendered = ', '.join(value) if isinstance(value, list) else value
        values.append(f'{field.label} {item["operator"].replace("_", " ")} {rendered}')
    return '; '.join(values)


def record_run(*, definition: PortalReportDefinition, actor, request_id: str, exported: bool = False, result_count: int = 0) -> None:
    action = 'exported' if exported else 'run'
    record_event(
        workflow='portal', action=f'portal.report.{action}', category='access',
        subject_type='PortalReportDefinition', subject_id=str(definition.pk),
        deduplication_key=_audit_key(action, actor, request_id, str(definition.pk)),
        actor=actor, request_id=request_id, source_model='PortalReportDefinition',
        source_event_id=f'{definition.pk}:{action}:{definition.version}',
        metadata={'definition_version': definition.version, 'result_count': result_count}, sensitive=True,
    )
