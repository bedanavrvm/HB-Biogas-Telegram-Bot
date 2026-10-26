"""Read-only delivery issues. Never create another report to repair a send."""
from django.conf import settings
from django.db.models import OuterRef, Subquery, F
from core.services.miniapp_recovery import issue, request_action
from report_delivery.models import ReportDelivery, ReportSchedule
from report_delivery.services import allowed_configurations, can_manage


def recovery_rows(actor, workflow, *, group=None):
    if not can_manage(actor, workflow=workflow):
        return []
    schedules = allowed_configurations(actor, ReportSchedule, workflow=workflow)
    if group is not None:
        schedules = schedules.filter(group_configuration_id=group.pk)
    rows = []
    if not (settings.REPORT_EMAIL_DELIVERY_ENABLED and settings.RESEND_API_KEY and settings.REPORT_EMAIL_FROM):
        rows.append(issue('report-configuration', 'Email delivery', status='Configuration required',
            detail='Report schedules can be saved, but email sending is not configured.',
            steps=['Ask IT to enable REPORT_EMAIL_DELIVERY_ENABLED and configure RESEND_API_KEY and REPORT_EMAIL_FROM in the deployment settings.',
                   'The sender domain must be verified in Resend. Keep credentials out of the Mini App.',
                   'Once repaired, check the existing delivery. Do not send another copy while its outcome is uncertain.']))
    latest = ReportDelivery.objects.filter(schedule_id=OuterRef('schedule_id'), recipient_id=OuterRef('recipient_id')).order_by('-created_at', '-pk').values('pk')[:1]
    endpoint = {'jawabu_portal': '/api/portal/settings/reports/', 'tat_tracker': '/api/tat-tracker/settings/reports/',
                'complaint_cases': '/api/complaints/settings/reports/'}[workflow]
    deliveries = ReportDelivery.objects.filter(schedule__in=schedules).annotate(latest=Subquery(latest)).filter(pk=F('latest')).exclude(status__in=['delivered', 'accepted']).select_related('schedule').order_by('-created_at')
    for delivery in deliveries:
        waiting = delivery.status in {'queued', 'retry', 'processing'}
        rows.append(issue(delivery.pk, f'{delivery.schedule.title or "Report"} · Email delivery',
            detail='Delivery is being checked.' if waiting else 'This delivery needs review before sending again.',
            status='Processing' if delivery.status == 'processing' else 'Waiting' if waiting else 'Needs review',
            action=request_action('Check status', endpoint, {'action': 'status', 'delivery_ids': [str(delivery.pk)]},
                                  'Check this existing delivery? This does not create or send a new report.'),
            steps=['Check this delivery’s status first. Accepted is not confirmation that it reached the inbox.',
                   'For a failed or uncertain result, ask IT to inspect the delivery and Resend history using this reference.',
                   'Do not use Send now to retry an uncertain delivery.']))
    return rows
