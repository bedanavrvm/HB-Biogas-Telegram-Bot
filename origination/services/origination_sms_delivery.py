"""Redacted SMS evidence on existing operations; lookup never replays a send."""
from __future__ import annotations

from datetime import timedelta
import time
import uuid

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from core.models import IntegrationOperation
from core.services.external_resilience import external_call_budget
from origination.services.origination_sms import ADVANTA, account_fingerprint, lookup_delivery

SMS_TYPES = ('origination_signing_invitation', 'origination_signing_otp', 'origination_withdrawal_sms')
LOOKUP_MINUTES = (1, 3, 10, 30, 120, 480, 1500)
RUNNER_KEY = 'origination_deliveries'


def initial_metadata(provider: str) -> dict:
    return {'sms': {'provider': provider, 'account': account_fingerprint(provider),
                    'submission': 'pending', 'delivery': 'pending', 'lookup_done': True}}


def confirmed_submission(operation) -> dict | None:
    """Recover a remote acknowledgement committed before a worker stopped."""
    sms = (operation.metadata or {}).get('sms') or {}
    if sms.get('submission') == 'accepted' and sms.get('message_id'):
        return {'id': sms['message_id'], 'status': 'Accepted'}
    return None


def _date(value):
    return parse_datetime(value) if isinstance(value, str) else None


def _apply_delivery(operation, *, state: str, status: str, now):
    metadata = dict(operation.metadata or {})
    sms = dict(metadata.get('sms') or {})
    previous = sms.get('delivery', 'pending')
    if previous != 'delivered' and not (previous == 'failed' and state in {'accepted', 'unknown'}):
        if not (previous == 'accepted' and state == 'unknown'):
            sms.update(delivery=state, provider_status=status)
    sms['observed_at'] = now.isoformat()
    metadata['sms'] = sms
    operation.metadata = metadata
    if operation.operation_type == 'origination_signing_otp':
        from origination.models import OriginationOtpChallenge
        challenge = OriginationOtpChallenge.objects.select_for_update().filter(
            pk=operation.source_id, session__sms_provider=operation.integration,
        ).first()
        if challenge:
            previous = challenge.delivery_status
            if previous != 'delivered' and not (previous == 'failed' and state in {'accepted', 'unknown'}):
                if not (previous == 'accepted' and state == 'unknown'):
                    challenge.delivery_status = state
                    challenge.provider_status = status
                    challenge.save(update_fields=['delivery_status', 'provider_status'])


def submit_once(operation, send):
    """Called inside execute_operation's send lease, before its success checkpoint."""
    from origination.services.origination_sms import OriginationSmsSubmissionError
    try:
        original = (operation.metadata or {}).get('sms') or {}
        if original.get('account') and original['account'] != account_fingerprint(operation.integration):
            raise OriginationSmsSubmissionError('account_changed', rejected=True)
        result = send()
        if not result or not result.get('id'):
            raise OriginationSmsSubmissionError('send_unconfirmed')
    except Exception as exc:
        with transaction.atomic():
            saved = IntegrationOperation.objects.select_for_update().get(pk=operation.pk)
            if saved.metadata.get('attempt_token') == operation.metadata.get('attempt_token'):
                metadata = dict(saved.metadata)
                sms = dict(metadata.get('sms') or {})
                rejected = isinstance(exc, OriginationSmsSubmissionError) and exc.rejected
                sms.update(submission='rejected' if rejected else 'unknown',
                           delivery='failed' if rejected else 'unknown',
                           error_code=exc.provider_status if isinstance(exc, OriginationSmsSubmissionError) else 'send_unconfirmed')
                metadata['sms'] = sms
                saved.metadata = metadata
                saved.save(update_fields=['metadata', 'updated_at'])
        raise
    now = timezone.now()
    with transaction.atomic():
        saved = IntegrationOperation.objects.select_for_update().get(pk=operation.pk)
        if saved.metadata.get('attempt_token') != operation.metadata.get('attempt_token'):
            return None
        metadata = dict(saved.metadata)
        sms = dict(metadata.get('sms') or initial_metadata(saved.integration)['sms'])
        sms.update(submission='accepted', message_id=str(result['id']), sent_at=now.isoformat(),
                   lookup_index=0, lookup_done=saved.integration != ADVANTA)
        if saved.integration == ADVANTA:
            sms['lookup_due_at'] = (now + timedelta(minutes=LOOKUP_MINUTES[0])).isoformat()
        metadata['sms'] = sms
        saved.metadata = metadata
        if saved.operation_type == 'origination_signing_otp':
            from origination.models import OriginationOtpChallenge
            OriginationOtpChallenge.objects.filter(
                pk=saved.source_id, session__sms_provider=saved.integration,
            ).update(provider_message_id=str(result['id']))
        _apply_delivery(saved, state='accepted', status='Accepted', now=now)
        saved.save(update_fields=['metadata', 'updated_at'])
    return result


def eligible_lookups():
    return IntegrationOperation.objects.filter(
        integration=ADVANTA, operation_type__in=SMS_TYPES,
        metadata__sms__submission='accepted', metadata__sms__lookup_done=False,
        metadata__sms__lookup_due_at__lte=timezone.now().isoformat(),
    )


def record_provider_receipt(*, provider: str, message_id: str, status: str) -> bool | None:
    """None means legacy evidence only; False means ambiguous/unsafe evidence."""
    from origination.services.origination_sms import delivery_state
    with transaction.atomic():
        matches = list(IntegrationOperation.objects.select_for_update().filter(
            integration=provider, operation_type__in=SMS_TYPES,
            metadata__sms__message_id=message_id,
        )[:2])
        if not matches:
            return None
        if len(matches) != 1:
            return False
        operation = matches[0]
        _apply_delivery(operation, state=delivery_state(provider, status), status=status, now=timezone.now())
        operation.save(update_fields=['metadata', 'updated_at'])
    return True


def _claim_lookup(operation_id):
    with transaction.atomic():
        operation = eligible_lookups().select_for_update().filter(pk=operation_id).first()
        if not operation:
            return None
        metadata = dict(operation.metadata)
        sms = dict(metadata['sms'])
        now = timezone.now()
        lease_until = _date(sms.get('lookup_lease_until'))
        if lease_until and lease_until > now:
            return None
        sms['lookup_token'] = uuid.uuid4().hex
        sms['lookup_lease_until'] = (now + timedelta(seconds=120)).isoformat()
        metadata['sms'] = sms
        operation.metadata = metadata
        operation.save(update_fields=['metadata', 'updated_at'])
        return operation


def reconcile_delivery(operation_id) -> bool:
    operation = _claim_lookup(operation_id)
    if not operation:
        return False
    claimed = operation.metadata['sms']
    result = None
    error = ''
    if claimed.get('account') != account_fingerprint(operation.integration):
        error = 'account_changed'
    else:
        try:
            result = lookup_delivery(claimed['message_id'], provider=operation.integration)
        except Exception as exc:
            from origination.services.origination_sms import OriginationSmsSubmissionError
            error = exc.provider_status if isinstance(exc, OriginationSmsSubmissionError) else 'lookup_unavailable'
    with transaction.atomic():
        saved = IntegrationOperation.objects.select_for_update().get(pk=operation_id)
        metadata = dict(saved.metadata)
        sms = dict(metadata['sms'])
        if sms.get('lookup_token') != claimed.get('lookup_token'):
            return False
        now = timezone.now()
        if result:
            _apply_delivery(saved, state=result['state'], status=result['status'], now=now)
            metadata = dict(saved.metadata)
            sms = dict(metadata['sms'])
        sms.pop('lookup_token', None)
        sms.pop('lookup_lease_until', None)
        index = int(sms.get('lookup_index', 0)) + 1
        sms.update(lookup_index=index, lookup_error=error, lookup_checked_at=now.isoformat())
        sms['lookup_done'] = (sms.get('delivery') in {'delivered', 'failed'}
                              or index >= len(LOOKUP_MINUTES) or error == 'account_changed')
        if not sms['lookup_done']:
            sent_at = _date(sms.get('sent_at')) or now
            sms['lookup_due_at'] = max(now + timedelta(minutes=1),
                                      sent_at + timedelta(minutes=LOOKUP_MINUTES[index])).isoformat()
        metadata['sms'] = sms
        saved.metadata = metadata
        saved.save(update_fields=['metadata', 'updated_at'])
    return True


def runner_health() -> dict:
    from core.models import DurableJobRunnerHeartbeat
    heartbeat = DurableJobRunnerHeartbeat.objects.filter(runner_key=RUNNER_KEY).first()
    cutoff = timezone.now() - timedelta(seconds=max(60, int(getattr(settings, 'DURABLE_JOB_RUNNER_MAX_SILENCE_SECONDS', 900))))
    return {'fresh': bool(heartbeat and heartbeat.heartbeat_at >= cutoff),
            'status': heartbeat.status if heartbeat else 'never_run',
            'due_lookups': eligible_lookups().count(),
            'account_changed': IntegrationOperation.objects.filter(
                integration=ADVANTA, operation_type__in=SMS_TYPES,
                metadata__sms__lookup_error='account_changed').count()}


def process_due_lookups(*, limit=5, max_seconds=50) -> int:
    deadline = time.monotonic() + max_seconds
    processed = 0
    ids = list(eligible_lookups().order_by('created_at').values_list('pk', flat=True)[:max(0, min(5, limit))])
    for operation_id in ids:
        if time.monotonic() >= deadline:
            break
        with external_call_budget(max(0.1, deadline - time.monotonic())):
            processed += int(reconcile_delivery(operation_id))
    return processed
