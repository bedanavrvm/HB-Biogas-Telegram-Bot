"""IT-only in-app configuration; no provider calls on the request path."""
import uuid
from datetime import time
from types import SimpleNamespace

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.utils import timezone

from core.models import GroupSheetConfiguration
from .models import ApprovedRecipient, ReportSchedule, ReportDelivery
from .services import allowed_configurations, require_manage, queue_schedule, next_occurrence
from .sources import PRESETS, validate_source


def configuration_payload(actor, workflow):
    require_manage(actor, workflow=workflow)
    groups = GroupSheetConfiguration.objects.filter(enabled=True)
    if not actor.is_superuser:
        grants = actor.access_grants.filter(active=True, workflow=workflow, role__iexact='IT')
        if not grants.filter(group_configuration__isnull=True).exists():
            groups = groups.filter(pk__in=grants.values('group_configuration_id'))
    schedules = allowed_configurations(actor, ReportSchedule, workflow=workflow).prefetch_related('recipients')[:100]
    from core.services.branches import global_branch_choices
    branch_scopes = {}
    grants = list(actor.access_grants.filter(active=True, workflow=workflow, role__iexact='IT'))
    for group in groups:
        eligible = [g for g in grants if not g.group_configuration_id or g.group_configuration_id == group.pk]
        broad = actor.is_superuser or any(not g.branch for g in eligible)
        names = global_branch_choices() if broad else sorted({g.branch for g in eligible if g.branch})
        branch_scopes[str(group.pk)] = ([{'value':'', 'label':'All branches'}] if broad else []) + [{'value':name, 'label':name} for name in names]
    pending_ids = list(ReportDelivery.objects.filter(schedule__in=allowed_configurations(actor, ReportSchedule, workflow=workflow),status__in=['queued','retry','processing']).order_by('created_at').values_list('pk',flat=True)[:100])
    from .dispatch import wake_deliveries
    wake_deliveries(pending_ids)
    return {'allowed': True, 'enabled': bool(settings.REPORT_EMAIL_DELIVERY_ENABLED and settings.RESEND_API_KEY and settings.REPORT_EMAIL_FROM),
            'pending_delivery_ids': [str(pk) for pk in pending_ids],
            'branches_by_group': branch_scopes,
            'presets': PRESETS[workflow], 'groups': [{'id': g.pk, 'label': str(g)} for g in groups],
            'schedules': [{'id': str(s.pk), 'revision': s.revision, 'title': s.title, 'preset': s.preset,
                           'group_configuration': s.group_configuration_id, 'branch': s.branch, 'product': s.product,
                           'county': s.county, 'frequency': s.frequency, 'send_time': s.send_time.strftime('%H:%M'),
                           'active': s.active, 'skip_empty': s.skip_empty,
                           'recipients': [r.email for r in s.recipients.all()]} for s in schedules]}


@transaction.atomic
def save_configuration(actor, workflow, payload):
    require_manage(actor, workflow=workflow)
    try:
        pk = uuid.UUID(str(payload['id']))
        group = GroupSheetConfiguration.objects.get(pk=payload['group_configuration'], enabled=True)
        send_time = time.fromisoformat(payload.get('send_time') or '08:00')
    except (KeyError, ValueError, TypeError, GroupSheetConfiguration.DoesNotExist):
        raise ValidationError('Choose a group and a valid sending time.')
    scope = SimpleNamespace(workflow=workflow, group_configuration_id=group.pk,
                            branch=str(payload.get('branch') or '').strip(), product=str(payload.get('product') or '').strip())
    require_manage(actor, scope)
    if connection.vendor == 'postgresql':
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(%s)', [int.from_bytes(pk.bytes[:8], 'big', signed=True)])
    existing = ReportSchedule.objects.select_for_update().filter(pk=pk).first()
    if existing:
        if existing.workflow != workflow:
            raise ValidationError('This schedule belongs to a different app.')
        require_manage(actor, existing)
    values = {'workflow': workflow, 'group_configuration': group, 'branch': scope.branch, 'product': scope.product,
              'county': str(payload.get('county') or '').strip(), 'title': str(payload.get('title') or '').strip(),
              'preset': payload.get('preset'), 'frequency': payload.get('frequency'), 'send_time': send_time,
              'active': payload.get('active') is True, 'skip_empty': payload.get('skip_empty') is True}
    emails = payload.get('recipients')
    if not isinstance(emails, list) or not 1 <= len(emails) <= 50:
        raise ValidationError('Add between 1 and 50 approved recipient addresses.')
    emails = sorted(set(str(v).strip().lower() for v in emails))
    unchanged = existing and existing.authorized_by_id == actor.pk and all(getattr(existing, k) == v for k, v in values.items()) and sorted(existing.recipients.values_list('email', flat=True)) == emails
    if existing and not unchanged and payload.get('revision') != existing.revision:
        raise ValidationError('This schedule changed. Reload Settings before saving.')
    schedule = existing or ReportSchedule(pk=pk, authorized_by=actor)
    for key, value in values.items():
        setattr(schedule, key, value)
    validate_source(schedule)
    schedule.full_clean(exclude=['recipients'])
    recipients = []
    for email in emails:
        recipient, _ = ApprovedRecipient.objects.get_or_create(workflow=workflow, group_configuration=group,
            branch=scope.branch, product=scope.product, email=email, defaults={'authorized_by': actor})
        if recipient.suppressed:
            raise ValidationError('An address is suppressed after a bounce or complaint. IT must review it in Admin.')
        recipient.full_clean()
        recipient.authorized_by = actor
        recipient.active = True
        recipient.save()
        recipients.append(recipient)
    if not unchanged:
        schedule.authorized_by = actor
        if existing:
            schedule.revision += 1
        schedule.next_run_at = next_occurrence(schedule, timezone.now()) if schedule.active else None
        schedule.save()
        schedule.recipients.set(recipients)
        from django.contrib.admin.models import LogEntry, CHANGE, ADDITION
        from django.contrib.contenttypes.models import ContentType
        LogEntry.objects.create(user=actor, content_type=ContentType.objects.get_for_model(schedule),
            object_id=str(schedule.pk), object_repr=schedule.title, action_flag=CHANGE if existing else ADDITION,
            change_message=f'Report settings approved: {workflow}, revision {schedule.revision}, {len(recipients)} recipients.')
    return schedule


def settings_action(actor, workflow, payload):
    require_manage(actor, workflow=workflow)
    action = payload.get('action', 'list')
    if action == 'save':
        save_configuration(actor, workflow, payload)
    elif action == 'send':
        if not settings.REPORT_EMAIL_DELIVERY_ENABLED or not settings.RESEND_API_KEY or not settings.REPORT_EMAIL_FROM:
            raise ValidationError('Email delivery is not configured yet.')
        schedule = allowed_configurations(actor, ReportSchedule, workflow=workflow).filter(pk=payload.get('id')).first()
        if schedule is None:
            raise ValidationError('Choose a report schedule in this app.')
        deliveries = queue_schedule(schedule.pk, actor=actor, request_key=payload.get('client_request_id'))
        from .dispatch import wake_deliveries
        ids = [str(d.pk) for d in deliveries]
        wake_deliveries(ids)
        return {'queued': len(deliveries), 'delivery_ids': ids, 'message': 'Sending report. You can keep using the app.'}
    elif action == 'status':
        ids = payload.get('delivery_ids')
        if not isinstance(ids, list) or not 1 <= len(ids) <= 2500:
            raise ValidationError('Choose the report deliveries to check.')
        ids = {uuid.UUID(str(pk)) for pk in ids}
        deliveries = list(ReportDelivery.objects.filter(pk__in=ids, schedule__in=allowed_configurations(actor, ReportSchedule, workflow=workflow)))
        if len(deliveries) != len(ids):
            raise ValidationError('These deliveries are not available in this app or access scope.')
        from .dispatch import wake_deliveries
        wake_deliveries(d.pk for d in deliveries if d.status in {'queued', 'retry', 'processing'})
        return {'deliveries': [{'id':str(d.pk), 'status':d.status, 'issue':d.issue,
                               'next_attempt_at':d.next_attempt_at.isoformat()} for d in deliveries]}
    elif action != 'list':
        raise ValidationError('Choose a valid report action.')
    return configuration_payload(actor, workflow)
