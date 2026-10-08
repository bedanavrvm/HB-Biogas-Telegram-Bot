"""One-off disclosure uses the existing workflow export, never a schedule."""
import base64
import hashlib
import json
import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone

from core.models import AccessGrant
from core.services.telegram_identity import user_access
from core.services.workflow_capabilities import has_capability
from .models import ApprovedRecipient, ReportDelivery

CAPABILITIES = {
    'jawabu_portal': ('portal.reports.view',),
    'tat_tracker': ('tat.reports.view',),
    'complaint_cases': ('complaint.reports.view', 'complaint.case.export'),
}


def require_export(actor, workflow):
    if not actor or not actor.is_active or workflow not in CAPABILITIES:
        raise PermissionDenied('Report export access is required.')
    access = user_access(actor, workflow)
    if not all(has_capability(actor, workflow, key, access=access) for key in CAPABILITIES[workflow]):
        raise PermissionDenied('Report export access is required.')
    return access


def access_stamp(actor, workflow):
    # A narrowed/revoked grant cannot disclose a previously captured broad export.
    from core.models import AccessControlPolicyState
    grants = list(AccessGrant.objects.filter(user=actor, workflow=workflow, active=True)
                  .order_by('pk').values('pk', 'role', 'group_configuration_id', 'branch', 'product'))
    policy = list(AccessControlPolicyState.objects.values().order_by('pk'))
    emergency = user_access(actor, workflow).get('emergency_grants', [])
    return hashlib.sha256(json.dumps([actor.is_superuser, grants, emergency, policy], sort_keys=True,
                                    cls=DjangoJSONEncoder).encode()).hexdigest()


def suppressed(email):
    return (ApprovedRecipient.objects.filter(email__iexact=email, suppressed=True).exists()
            or ReportDelivery.objects.filter(destination__iexact=email, status__in=['bounced', 'complained']).exists()
            or ReportDelivery.objects.filter(recipient__email__iexact=email, status__in=['bounced', 'complained']).exists())


@transaction.atomic
def queue_export(actor, workflow, payload):
    require_export(actor, workflow)
    try:
        key = str(uuid.UUID(str(payload.get('client_request_id'))))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError('Reopen Email report and try again.')
    email = str(payload.get('email') or '').strip()
    validate_email(email)
    if len(email) > 254:
        raise ValidationError('Enter an email address of 254 characters or fewer.')
    filters = payload.get('filters', {})
    if not isinstance(filters, dict) or len(json.dumps(filters)) > 16000:
        raise ValidationError('Review the report filters.')
    # Only report inputs survive; never retain Telegram tokens/initData.
    allowed = {'branch', 'county', 'product', 'stage', 'status', 'category', 'search',
               'date_mode', 'month', 'quarter', 'year', 'from', 'to', 'date_from', 'date_to', 'date_basis',
               'metric', 'metric_value', 'view', 'group', 'role', 'granularity', 'sort',
               'comparison_dimension', 'comparison_metric', 'heatmap_row', 'heatmap_column',
               'heatmap_metric', 'heatmap_pair', 'chart_dimension', 'chart_metric', 'sla_state',
               'drill_chart', 'drill_series', 'drill_bucket', 'heat_row', 'heat_column', 'chart', 'series', 'bucket',
               'chart_key', 'series_key', 'bucket_key'}
    filters = {k: v for k, v in filters.items() if k in allowed}
    configuration = {'workflow': workflow, 'preset': payload.get('preset') or
                     {'jawabu_portal': 'pipeline', 'tat_tracker': 'tat', 'complaint_cases': 'complaints'}[workflow],
                     'filters': filters, 'access_stamp': access_stamp(actor, workflow)}
    from .sources import PRESETS
    if configuration['preset'] not in PRESETS[workflow]:
        raise ValidationError('Choose a report belonging to this app.')
    delivery, created = ReportDelivery.objects.get_or_create(requested_by=actor, schedule=None,
        occurrence='export:' + key, defaults={'destination': email, 'configuration': configuration})
    if not created and (delivery.destination.casefold() != email.casefold()
                        or delivery.configuration != configuration):
        raise ValidationError('This send request changed. Reopen Email report to send a different report.')
    if suppressed(email):
        raise ValidationError('This address cannot receive reports after a bounce or complaint. Ask IT to review it.')
    if created:
        from core.services.compliance_audit import record_event
        record_event(workflow=workflow, action='report.email.requested', category='data_export', origin='human',
                     subject_type='report_delivery', subject_id=str(delivery.pk), actor=actor, authority_user=actor,
                     deduplication_key=f'report-email:{delivery.pk}',
                     metadata={'preset': configuration['preset'], 'destination_hash': hashlib.sha256(email.casefold().encode()).hexdigest()},
                     sensitive=True)
    return delivery


def validate_export(delivery):
    actor = delivery.requested_by
    workflow = delivery.configuration['workflow']
    require_export(actor, workflow)
    if access_stamp(actor, workflow) != delivery.configuration['access_stamp'] or suppressed(delivery.destination):
        raise PermissionDenied('Report access or destination changed.')


def capture_export(delivery):
    """Called inside the shared repeatable-read capture transaction."""
    actor, config = delivery.requested_by, delivery.configuration
    workflow, filters = config['workflow'], config['filters']
    request_id = str(delivery.pk)
    if workflow == 'jawabu_portal':
        from core.services.portal_reporting import capture_curated_report, curated_snapshot_xlsx, record_curated_run
        snapshot = capture_curated_report(preset=config['preset'], filters=filters, user=actor,
                                          access=require_export(actor, workflow))
        workbook = curated_snapshot_xlsx(snapshot)
        record_curated_run(preset=config['preset'], actor=actor, request_id=request_id, exported=True,
                           result_count=snapshot['total_rows'])
    else:
        if workflow == 'tat_tracker':
            from core.services.tat_reporting import export_report_xlsx, report_summary
            people = has_capability(actor, workflow, 'tat.reports.people.view', access=user_access(actor, workflow))
            workbook, count = export_report_xlsx(actor, filters, include_people=people, request_id=request_id)
            overview = report_summary(actor, {**filters, 'response_mode': 'focused_v1', 'insight': 'trend',
                                             'include_options': False}, include_people=people)
            metrics = overview.get('metrics', {})
            fields = ([('active', 'Active cases'), ('stalled', 'Stalled cases'),
                       ('within_target', 'Within target'), ('overdue', 'Over target'),
                       ('near_target', 'Near target'), ('target_unavailable', 'No target available')]
                      if filters.get('view', 'current') == 'current' else
                      [('created', 'Cases received'), ('finished', 'Completed cases'),
                        ('disbursed', 'Disbursed'), ('declined', 'Declined'),
                        ('sla_met_percent', 'Within or near target (%)'),
                        ('median_tat_minutes', 'Median TAT (minutes)'), ('target_unavailable', 'No target available')])
            if overview.get('metric_basis') == 'completed_stage_actions':
                fields = [(key, 'Completed actions' if key == 'finished' else 'Cases with completed actions' if key == 'created' else label)
                          for key, label in fields]
            summary = {label: metrics.get(key) for key, label in fields}
            trend = overview.get('charts', {}).get('trend', {})
            charts = [{'title': trend.get('title', 'TAT outcomes'), 'labels': trend.get('labels', []),
                       'datasets': [{'label': s.get('label', ''), 'values': s.get('values', s.get('data', []))}
                                    for s in trend.get('series', [])]}] if has_capability(
                                        actor, workflow, 'tat.reports.insight.trend', access=user_access(actor, workflow)) else []
        else:
            from core.services.complaint_register import export_register_xlsx, complaint_report_summary
            workbook, count = export_register_xlsx(actor=actor, request_id=request_id, filters=filters)
            overview = complaint_report_summary(filters=filters, granularity=filters.get('granularity') or 'month')
            summary = {label: overview.get(key, 0) for key, label in
                       [('total', 'Complaints received'), ('pending', 'Open'), ('resolved', 'Resolved'),
                        ('needs_details', 'Needs details')]}
            timing = overview.get('timing', {})
            summary.update({label: timing.get(key) for key, label in
                            [('median_resolution_hours', 'Median resolution (hours)'),
                             ('median_response_hours', 'Median HB response (hours)'),
                             ('on_time_percent', 'Resolved on time (%)')]})
            charts = [{'title': title, 'labels': [r['label'] for r in overview.get(key, [])],
                       'datasets': [{'label':'Complaints', 'values':[r['count'] for r in overview.get(key, [])]}]}
                      for key, title in [('by_category', 'Complaint categories'), ('by_branch', 'Complaints by branch')]]
        snapshot = {'preset': config['preset'], 'summary': summary, 'charts': charts, 'rows': [],
                    'exported_rows': count, 'total_rows': count, 'export_limit': 10000 if workflow == 'tat_tracker' else None,
                    'applied_filters': filters, 'period': None, 'run_at': timezone.now().isoformat()}
        if filters.get('date_from') and filters.get('date_to'):
            snapshot['period'] = {'from': filters['date_from'], 'to': filters['date_to']}
    snapshot['xlsx_content'] = base64.b64encode(workbook).decode()
    return json.loads(json.dumps(snapshot, cls=DjangoJSONEncoder))
