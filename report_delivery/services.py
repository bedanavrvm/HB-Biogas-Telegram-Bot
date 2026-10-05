"""Database reservations, authorization and bounded report delivery lifecycle."""
import hashlib
import json
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from core.models import AccessGrant
from .models import ApprovedRecipient, ReportDelivery, ReportSchedule, WebhookReceipt

NAIROBI = ZoneInfo('Africa/Nairobi')
LEASE_SECONDS = 300
MAX_ATTEMPTS = 6
PAYLOAD_DAYS = 30
METADATA_DAYS = 180


def can_manage(user, configuration=None, *, workflow='jawabu_portal'):
    if not user or not user.is_active:
        return False
    if user.is_superuser:
        return True
    workflow = getattr(configuration, 'workflow', workflow)
    grants = AccessGrant.objects.filter(user=user, active=True, workflow=workflow, role__iexact='IT')
    if configuration is None:
        return grants.exists()
    # A blank requested branch/product means the whole group. Narrow grants
    # cannot authorize it; independently matching scopes must never be unioned.
    return any(
        (not g.group_configuration_id or g.group_configuration_id == configuration.group_configuration_id)
        and (not g.branch or g.branch.strip().casefold() == configuration.branch.strip().casefold())
        and (not g.product or g.product.strip().casefold() == configuration.product.strip().casefold())
        for g in grants
    )


def require_manage(user, configuration=None, *, workflow='jawabu_portal'):
    if not can_manage(user, configuration, workflow=workflow):
        raise PermissionDenied('IT access is required for this app and report scope.')


def allowed_configurations(user, model, *, workflow=None):
    if not user or not user.is_active:
        return model.objects.none()
    if user.is_superuser:
        return model.objects.filter(workflow=workflow) if workflow else model.objects.all()
    scope = Q(pk__in=[])
    grants = AccessGrant.objects.filter(user=user, active=True, workflow__in=['jawabu_portal', 'tat_tracker', 'complaint_cases'], role__iexact='IT')
    if workflow:
        grants = grants.filter(workflow=workflow)
    for grant in grants:
        clause = Q(workflow=grant.workflow)
        if grant.group_configuration_id:
            clause &= Q(group_configuration_id=grant.group_configuration_id)
        if grant.branch:
            clause &= Q(branch__iexact=grant.branch)
        if grant.product:
            clause &= Q(product__iexact=grant.product)
        scope |= clause
    return model.objects.filter(scope)


def validate_recipient(schedule, recipient):
    from .sources import validate_source
    validate_source(schedule)
    if recipient.workflow != schedule.workflow:
        raise ValidationError('Recipients must be approved separately for this app.')
    if not recipient.active or recipient.suppressed:
        raise ValidationError('This recipient is paused or suppressed. IT must review it before sending.')
    if recipient.group_configuration_id != schedule.group_configuration_id:
        raise ValidationError('The recipient must be approved for this group.')
    for key in ('branch', 'product'):
        approved = getattr(recipient, key).strip().casefold()
        selected = getattr(schedule, key).strip().casefold()
        if approved and approved != selected:
            raise ValidationError('The report exceeds the recipient’s approved branch or product scope.')
    require_manage(recipient.authorized_by, recipient)


def recipient_stamp(recipient):
    values = {
        'email': recipient.email, 'group': recipient.group_configuration_id,
        'branch': recipient.branch, 'product': recipient.product,
        'actor': recipient.authorized_by_id,
    }
    # Keep unchanged queued Portal reports valid across the ownership migration.
    if recipient.workflow != 'jawabu_portal':
        values['workflow'] = recipient.workflow
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def _month_shift(day, count):
    index = day.year * 12 + day.month - 1 + count
    return day.replace(year=index // 12, month=index % 12 + 1, day=1)


def adjacent_occurrence(schedule, at, direction):
    local = timezone.localtime(at, NAIROBI)
    if schedule.frequency == 'daily':
        day = local.date() + timedelta(days=direction)
    elif schedule.frequency == 'weekly':
        day = local.date() + timedelta(days=7 * direction)
    else:
        day = _month_shift(local.date(), direction * (3 if schedule.frequency == 'quarterly' else 1))
    return datetime.combine(day, schedule.send_time, NAIROBI)


def period_boundary(schedule, now):
    local = timezone.localtime(now, NAIROBI)
    day = local.date()
    if schedule.frequency == 'weekly':
        day -= timedelta(days=day.weekday())
    elif schedule.frequency in {'monthly', 'quarterly'}:
        day = day.replace(day=1)
        if schedule.frequency == 'quarterly':
            day = day.replace(month=((day.month - 1) // 3) * 3 + 1)
    return datetime.combine(day, schedule.send_time, NAIROBI)


def latest_occurrence(schedule, now):
    occurrence = period_boundary(schedule, now)
    return occurrence if occurrence <= now else adjacent_occurrence(schedule, occurrence, -1)


def next_occurrence(schedule, now):
    return adjacent_occurrence(schedule, latest_occurrence(schedule, now), 1)


def completed_period(schedule, occurrence):
    day = timezone.localtime(occurrence, NAIROBI).date()
    end = day - timedelta(days=1)
    if schedule.frequency == 'daily':
        start = end
    elif schedule.frequency == 'weekly':
        start = day - timedelta(days=7)
    else:
        start = _month_shift(day, -3 if schedule.frequency == 'quarterly' else -1)
    return {'from': start.isoformat(), 'to': end.isoformat()}


def _configuration(schedule, recipient, occurrence):
    period = completed_period(schedule, occurrence)
    filters = {key: getattr(schedule, key) for key in ('branch', 'product', 'county') if getattr(schedule, key)}
    # Pipeline is a current backlog snapshot, not a historical pipeline.
    filters.update({'date_mode': 'all'} if schedule.preset == 'pipeline' else {'date_mode': 'custom', **period})
    return {
        'revision': schedule.revision, 'group': schedule.group_configuration_id, 'workflow': schedule.workflow,
        'approved_by': schedule.authorized_by_id, 'recipient_approved_by': recipient.authorized_by_id,
        'preset': schedule.preset, 'filters': filters, 'period': period,
        'due_at': occurrence.isoformat(), 'recipient_stamp': recipient_stamp(recipient),
    }


@transaction.atomic
def queue_schedule(schedule_id, *, actor, request_key, recipient_id=None, now=None):
    """Manual/test controls reserve work only; double POST reuses the UUID."""
    try:
        key = str(uuid.UUID(str(request_key)))
    except (ValueError, TypeError, AttributeError):
        raise ValidationError('Reopen this action and try again.')
    schedule = ReportSchedule.objects.select_for_update().select_related('authorized_by').get(pk=schedule_id)
    require_manage(actor, schedule)
    require_manage(schedule.authorized_by, schedule)
    recipients = schedule.recipients.select_related('authorized_by')
    if recipient_id:
        recipients = recipients.filter(pk=recipient_id)
    if not recipients.exists():
        raise ValidationError('Choose an approved recipient assigned to this schedule.')
    now = now or timezone.now()
    due = period_boundary(schedule, now)
    deliveries = []
    for recipient in recipients:
        validate_recipient(schedule, recipient)
        configuration = _configuration(schedule, recipient, due)
        configuration['due_at'] = now.isoformat()
        delivery, _ = ReportDelivery.objects.get_or_create(
            schedule=schedule, recipient=recipient, occurrence='manual:' + key,
            defaults={'configuration': configuration, 'next_attempt_at': now},
        )
        if not delivery.configuration.get('requested_by'):
            delivery.configuration['requested_by'] = actor.pk
            delivery.save(update_fields=['configuration', 'updated_at'])
        deliveries.append(delivery)
    return deliveries


def reserve_due(*, now=None, limit=20):
    now = now or timezone.now()
    ids = ReportSchedule.objects.filter(active=True, next_run_at__lte=now).order_by('next_run_at').values_list('pk', flat=True)[:limit]
    reserved = 0
    for pk in list(ids):
        with transaction.atomic():
            schedule = ReportSchedule.objects.select_for_update().select_related('authorized_by').get(pk=pk)
            if not schedule.active or not schedule.next_run_at or schedule.next_run_at > now:
                continue
            due = latest_occurrence(schedule, now)
            old = timezone.localtime(schedule.next_run_at, NAIROBI)
            if schedule.frequency in {'daily', 'weekly'}:
                skipped = (due.date() - old.date()).days // (7 if schedule.frequency == 'weekly' else 1)
            else:
                skipped = ((due.year - old.year) * 12 + due.month - old.month) // (3 if schedule.frequency == 'quarterly' else 1)
            schedule.skipped_occurrences += max(0, skipped)
            schedule.next_run_at = adjacent_occurrence(schedule, due, 1)
            schedule.save(update_fields=['next_run_at', 'skipped_occurrences', 'updated_at'])
            for recipient in schedule.recipients.select_related('authorized_by'):
                error = ''
                try:
                    require_manage(schedule.authorized_by, schedule)
                    validate_recipient(schedule, recipient)
                except (PermissionDenied, ValidationError):
                    error = 'scope_or_recipient_changed'
                _, created = ReportDelivery.objects.get_or_create(
                    schedule=schedule, recipient=recipient, occurrence='scheduled:' + due.isoformat(),
                    defaults={'configuration': _configuration(schedule, recipient, due), 'next_attempt_at': now,
                              'status': 'blocked' if error else 'queued', 'error_code': error},
                )
                reserved += int(created)
    return reserved


def claim_delivery(*, now=None):
    now = now or timezone.now()
    eligible = Q(status__in=['queued', 'retry'], next_attempt_at__lte=now) | Q(status='processing', lease_until__lte=now)
    # Compare-and-swap also protects local SQLite runs; PostgreSQL supports the
    # runner's concurrent invocations without holding locks during HTTP/PDF work.
    for pk in ReportDelivery.objects.filter(eligible).order_by('next_attempt_at', 'created_at').values_list('pk', flat=True)[:20]:
        token = uuid.uuid4()
        if ReportDelivery.objects.filter(pk=pk).filter(eligible).update(status='processing', lease_token=token, lease_until=now + timedelta(seconds=LEASE_SECONDS)):
            return ReportDelivery.objects.select_related('schedule__authorized_by', 'recipient__authorized_by').get(pk=pk)
    return None


def validate_delivery(delivery):
    schedule, recipient = delivery.schedule, delivery.recipient
    require_manage(schedule.authorized_by, schedule)
    validate_recipient(schedule, recipient)
    if delivery.configuration.get('workflow', 'jawabu_portal') != schedule.workflow:
        raise ValidationError('The report app changed; queue a fresh report.')
    if not schedule.recipients.filter(pk=recipient.pk).exists():
        raise ValidationError('This recipient is no longer assigned to the schedule.')
    if not schedule.group_configuration.enabled:
        raise ValidationError('This group is paused.')
    if delivery.configuration['revision'] != schedule.revision or delivery.configuration['recipient_stamp'] != recipient_stamp(recipient):
        raise ValidationError('Configuration changed; queue a fresh report after reviewing its scope.')
    if delivery.configuration['group'] != schedule.group_configuration_id or delivery.configuration['preset'] != schedule.preset:
        raise ValidationError('The report scope changed.')
    for key in ('branch', 'product', 'county'):
        if delivery.configuration['filters'].get(key, '') != getattr(schedule, key):
            raise ValidationError('The report filters changed.')
    if not schedule.active and not delivery.occurrence.startswith('manual:'):
        raise ValidationError('This schedule is paused.')


def capture_report(schedule, configuration):
    from core.services.portal_reporting import capture_curated_report
    from core.services.telegram_identity import user_access
    # PostgreSQL sees one committed database snapshot across aggregate and row
    # queries. This transaction is separate from lease acquisition and HTTP.
    with transaction.atomic():
        if connection.vendor == 'postgresql':
            with connection.cursor() as cursor:
                cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        if schedule.workflow != 'jawabu_portal':
            from .sources import capture_workflow_report
            snapshot = capture_workflow_report(schedule, configuration)
            return json.loads(json.dumps(snapshot, cls=DjangoJSONEncoder))
        snapshot = capture_curated_report(
            preset=configuration['preset'], filters=configuration['filters'],
            user=schedule.authorized_by, access=user_access(schedule.authorized_by, 'jawabu_portal'),
            group_configuration=schedule.group_configuration,
        )
        return json.loads(json.dumps(snapshot, cls=DjangoJSONEncoder))


def preview_report(schedule, actor):
    require_manage(actor, schedule)
    require_manage(schedule.authorized_by, schedule)
    due = period_boundary(schedule, timezone.now())
    return capture_report(schedule, {'preset': schedule.preset, 'filters': {
        **{key: getattr(schedule, key) for key in ('branch', 'product', 'county') if getattr(schedule, key)},
        **({'date_mode': 'all'} if schedule.preset == 'pipeline' else {'date_mode': 'custom', **completed_period(schedule, due)}),
    }, 'period': completed_period(schedule, due)})


def _finish(delivery, **changes):
    changes.update(lease_token=None, lease_until=None, updated_at=timezone.now())
    return ReportDelivery.objects.filter(pk=delivery.pk, lease_token=delivery.lease_token).update(**changes)


def process_delivery(delivery, *, now=None):
    from .rendering import build_payload, ReportTooLarge
    from .resend import send_email, SubmissionError
    now = now or timezone.now()
    try:
        validate_delivery(delivery)
    except (PermissionDenied, ValidationError):
        _finish(delivery, status='blocked', error_code='scope_or_recipient_changed')
        return
    if delivery.first_attempt_at and now >= delivery.first_attempt_at + timedelta(hours=23, minutes=55):
        _finish(delivery, status='uncertain', error_code='idempotency_window_expired')
        return
    if not delivery.payload:
        try:
            snapshot = capture_report(delivery.schedule, delivery.configuration)
            if delivery.schedule.skip_empty and snapshot['total_rows'] == 0:
                _finish(delivery, status='skipped', error_code='empty_report')
                return
            payload = build_payload(snapshot, delivery.recipient.email, delivery.configuration)
        except ReportTooLarge:
            _finish(delivery, status='failed', error_code='attachments_too_large')
            return
        except Exception:
            # Rendering or data errors are not "empty". No customer values or
            # raw provider bodies belong in diagnostic metadata.
            _finish(delivery, status='failed', error_code='report_generation_failed')
            return
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        if not ReportDelivery.objects.filter(pk=delivery.pk, lease_token=delivery.lease_token).update(payload=payload, payload_hash=digest, snapshot=snapshot):
            return
        delivery.payload = payload
    # Recheck live grants after potentially expensive rendering and immediately
    # before disclosure. Future retry attempts use the exact persisted payload.
    delivery = ReportDelivery.objects.select_related('schedule__authorized_by', 'recipient__authorized_by').filter(pk=delivery.pk, lease_token=delivery.lease_token).first()
    if delivery is None:
        return
    try:
        validate_delivery(delivery)
    except (PermissionDenied, ValidationError):
        _finish(delivery, status='blocked', error_code='scope_or_recipient_changed')
        return
    if delivery.lease_until <= timezone.now():
        return
    attempts = delivery.attempts + 1
    first = delivery.first_attempt_at or now
    if not ReportDelivery.objects.filter(pk=delivery.pk, lease_token=delivery.lease_token).update(attempts=attempts, first_attempt_at=first):
        return
    try:
        provider_id = send_email(delivery.payload, key='portal-report/' + str(delivery.pk))
    except SubmissionError as exc:
        status = 'retry' if exc.retryable and attempts < MAX_ATTEMPTS else 'uncertain' if exc.ambiguous else 'failed'
        _finish(delivery, status=status, error_code=exc.code, next_attempt_at=now + timedelta(seconds=min(3600, max(exc.retry_after, 60 * 2 ** (attempts - 1)))))
    else:
        _finish(delivery, status='accepted', provider_id=provider_id, error_code='')
        reconcile_webhooks(provider_id)


@transaction.atomic
def retry_delivery(delivery_id, actor):
    delivery = ReportDelivery.objects.select_for_update().select_related('schedule__authorized_by', 'recipient__authorized_by').get(pk=delivery_id)
    require_manage(actor, delivery.schedule)
    validate_delivery(delivery)
    if delivery.status not in {'failed', 'blocked'}:
        raise ValidationError('Only a failed or blocked, unaccepted delivery can be retried. Reconcile uncertain submissions with Resend first.')
    if delivery.provider_id or (delivery.first_attempt_at and timezone.now() >= delivery.first_attempt_at + timedelta(hours=23, minutes=55)):
        raise ValidationError('This submission requires provider reconciliation; automatic retry could duplicate the email.')
    if not delivery.payload and delivery.first_attempt_at:
        raise ValidationError('The retained payload expired. Review and queue a new report instead.')
    delivery.status = 'queued'
    delivery.next_attempt_at = timezone.now()
    delivery.error_code = ''
    delivery.save(update_fields=['status', 'next_attempt_at', 'error_code', 'updated_at'])


@transaction.atomic
def reconcile_webhooks(provider_id):
    delivery = ReportDelivery.objects.select_for_update().filter(provider_id=provider_id).first()
    if not delivery:
        return
    events = list(WebhookReceipt.objects.filter(provider_id=provider_id).order_by('occurred_at', 'created_at'))
    statuses = {'email.sent': 'accepted', 'email.delivered': 'delivered', 'email.delivery_delayed': 'delayed',
                'email.bounced': 'bounced', 'email.complained': 'complained', 'email.failed': 'failed'}
    for event in events:
        status = statuses.get(event.event_type)
        if not status:
            continue
        # Delivery and suppression evidence dominate a later delayed/sent event.
        if delivery.status in {'bounced', 'complained'} or (delivery.status == 'delivered' and status in {'accepted', 'delayed'}):
            continue
        delivery.status = status
        delivery.last_event_at = event.occurred_at
        if status in {'bounced', 'complained'}:
            ApprovedRecipient.objects.filter(email__iexact=delivery.recipient.email).update(suppressed=True, suppression_reason=status)
    delivery.save(update_fields=['status', 'last_event_at', 'updated_at'])


def purge_history(*, now=None, limit=100):
    now = now or timezone.now()
    payload_ids = list(ReportDelivery.objects.filter(created_at__lt=now - timedelta(days=PAYLOAD_DAYS)).exclude(payload={}).values_list('pk', flat=True)[:limit])
    ReportDelivery.objects.filter(pk__in=payload_ids).update(payload={}, snapshot={})
    ids = list(ReportDelivery.objects.filter(created_at__lt=now - timedelta(days=METADATA_DAYS)).values_list('pk', flat=True)[:limit])
    ReportDelivery.objects.filter(pk__in=ids).delete()
    events = list(WebhookReceipt.objects.filter(created_at__lt=now - timedelta(days=METADATA_DAYS)).values_list('pk', flat=True)[:limit])
    WebhookReceipt.objects.filter(pk__in=events).delete()
    return len(payload_ids), len(ids), len(events)
