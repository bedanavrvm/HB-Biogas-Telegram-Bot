"""Workflow-owned read adapters; delivery never joins customer identities."""
from django.core.exceptions import ValidationError
from django.utils import timezone

PRESETS = {'jawabu_portal': ['pipeline', 'outcomes', 'finance'], 'tat_tracker': ['tat'], 'complaint_cases': ['complaints']}


def validate_source(schedule):
    if schedule.preset not in PRESETS.get(schedule.workflow, []):
        raise ValidationError('Choose a report belonging to this app.')
    if schedule.workflow != 'jawabu_portal' and schedule.county:
        raise ValidationError('County filtering is currently available for Portal email reports only.')
    if schedule.workflow == 'complaint_cases' and schedule.product:
        raise ValidationError('Complaints are not grouped by loan product.')


def capture_workflow_report(schedule, configuration):
    validate_source(schedule)
    period = configuration.get('period')
    if not period:
        raise ValidationError('A completed reporting period is required.')
    filters = {'date_from': period['from'], 'date_to': period['to'], 'branch': schedule.branch}
    if schedule.workflow == 'tat_tracker':
        from core.services.tat_reporting import report_summary, report_cases
        filters.update(group=str(schedule.group_configuration.group_id), product=schedule.product,
                       view='performance', granularity='day', response_mode='focused_v1', insight='trend', include_options=False)
        overview = report_summary(schedule.authorized_by, filters)
        metrics = overview.get('metrics', {})
        labels = {'created': 'Cases received', 'finished': 'Completed cases', 'disbursed': 'Disbursed',
                  'declined': 'Declined', 'sla_met_percent': 'Within or near target (%)',
                  'median_tat_minutes': 'Median TAT (minutes)', 'p90_tat_minutes': '90th percentile TAT (minutes)',
                  'target_unavailable': 'No target available'}
        summary = {label: metrics.get(key) for key, label in labels.items()}
        chart = overview.get('charts', {}).get('trend', {})
        charts = [{'title': chart.get('title', 'TAT outcomes'), 'labels': chart.get('labels', []),
                   'datasets': [{'label': s.get('label', ''), 'values': s.get('values', s.get('data', []))} for s in chart.get('series', [])],
                   'type': 'line', 'context': chart.get('subtitle', '')}]
        rows, total = [], 0
        for page in range(1, 21):
            result = report_cases(schedule.authorized_by, {**filters, 'page': page, 'page_size': 100})
            rows.extend(result['results']); total = result['count']
            if len(rows) >= total:
                break
        columns = [('case_id', 'Reference'), ('client_name', 'Customer'), ('branch', 'Branch'),
                   ('product_label', 'Product'), ('status', 'Status'), ('current_stage', 'Stage'),
                   ('created_at', 'Created'), ('finished_at', 'Completed'), ('elapsed_minutes', 'TAT (minutes)'), ('sla_state', 'Target result')]
    else:
        from core.services.complaint_register import _report_queryset, _apply_report_filters, serialize_report_case, complaint_report_summary
        base = _report_queryset().filter(group_id=str(schedule.group_configuration.group_id))
        # Narrow the base before all aggregate, option, timing and row queries.
        if schedule.branch:
            base = _apply_report_filters(base, {'branch': schedule.branch}, timing=False)
        overview = complaint_report_summary(filters=filters, granularity='day', base_queryset=base)
        summary = {label: overview.get(key, 0) for key, label in [('total', 'Complaints received'), ('pending', 'Open'), ('resolved', 'Resolved'), ('needs_details', 'Needs details')]}
        charts = [{'title': title, 'type': kind, 'labels': [r['label'] for r in overview.get(key, [])],
                   'datasets': [{'label': 'Complaints', 'values': [r['count'] for r in overview.get(key, [])]}], 'context': ''}
                  for key, title, kind in [('by_time', 'Complaints received', 'line'), ('by_category', 'Complaint categories', 'bar')]]
        queryset = _apply_report_filters(base, filters).order_by('-timestamp', '-pk')
        total = queryset.count()
        rows = [serialize_report_case(case) for case in queryset[:2000]]
        columns = [('complaint_id', 'Reference'), ('date_reported', 'Reported'), ('customer_name', 'Customer'),
                   ('customer_id', 'National ID'), ('phone_number', 'Phone'), ('branch_region', 'Branch'),
                   ('complaint_category', 'Category'), ('status', 'Status'), ('resolution_details', 'Resolution'),
                   ('resolution_comments', 'HB comments'), ('date_resolved', 'Resolved')]
    return {'preset': schedule.preset, 'period': period, 'summary': summary, 'charts': charts,
            'rows': rows, 'total_rows': total, 'export_limit': 2000,
            'columns': [{'key': key, 'label': label, 'type': 'text'} for key, label in columns],
            'applied_filters': filters, 'run_at': timezone.now().isoformat()}
