"""Durable post-commit work for fast, authoritative TAT updates."""

from __future__ import annotations

from datetime import timedelta
import logging
import uuid

from django.conf import settings
from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from core.models import (
    GroupSheetConfiguration,
    TatTrackerApprovalCertificate,
    TatTrackerCase,
    TatUpdateSideEffectDispatch,
)


logger = logging.getLogger(__name__)
MAX_ATTEMPTS = 5
RETRY_DELAYS_SECONDS = (30, 120, 600, 1800)
LEASE_SECONDS = 300


def reserve_update_dispatches(group_config, case: TatTrackerCase, *, request_id: str = '') -> list[str]:
    """Reserve applicable effects inside the case-update transaction."""
    effects: list[str] = []
    if bool(getattr(group_config, 'tat_sheet_projection_enabled', True)):
        effects.append(TatUpdateSideEffectDispatch.EFFECT_SHEET)
    if (
        bool(getattr(settings, 'TAT_TRACKER_SIGNATURES_ENABLED', False))
        and case.approval_certificates.filter(status='awaiting_signature').exists()
    ):
        effects.append(TatUpdateSideEffectDispatch.EFFECT_SIGNATURE)
    effects.append(TatUpdateSideEffectDispatch.EFFECT_NOTIFICATION)

    ids: list[str] = []
    for effect in effects:
        dispatch, _created = TatUpdateSideEffectDispatch.objects.get_or_create(
            case=case,
            workflow_revision=case.workflow_revision,
            effect_type=effect,
            defaults={'request_id': str(request_id or '')[:128]},
        )
        ids.append(str(dispatch.pk))
    return ids


def dispatch_ids_for_case_revision(case: TatTrackerCase) -> list[str]:
    return [
        str(value)
        for value in case.update_dispatches.filter(
            workflow_revision=case.workflow_revision,
        ).values_list('pk', flat=True)
    ]


def attention_count(*, group_id: str | None = None) -> int:
    rows = TatUpdateSideEffectDispatch.objects.filter(
        status=TatUpdateSideEffectDispatch.STATUS_NEEDS_ATTENTION,
    )
    if group_id:
        rows = rows.filter(case__group_id=str(group_id))
    return rows.count()


def _claim_one(*, dispatch_ids: list[str] | None = None):
    now = timezone.now()
    stale_before = now - timedelta(seconds=LEASE_SECONDS)
    due = Q(status=TatUpdateSideEffectDispatch.STATUS_PENDING) | Q(
        status=TatUpdateSideEffectDispatch.STATUS_RETRYABLE,
        next_retry_at__lte=now,
    ) | Q(
        status=TatUpdateSideEffectDispatch.STATUS_RUNNING,
        lease_started_at__lt=stale_before,
    )
    with transaction.atomic():
        signature_blockers = TatUpdateSideEffectDispatch.objects.filter(
            case_id=OuterRef('case_id'),
            workflow_revision=OuterRef('workflow_revision'),
            effect_type=TatUpdateSideEffectDispatch.EFFECT_SIGNATURE,
        ).exclude(status__in=[
            TatUpdateSideEffectDispatch.STATUS_SUCCEEDED,
            TatUpdateSideEffectDispatch.STATUS_SUPERSEDED,
        ])
        queryset = TatUpdateSideEffectDispatch.objects.filter(due).annotate(
            signature_blocked=Exists(signature_blockers),
        ).exclude(
            effect_type=TatUpdateSideEffectDispatch.EFFECT_NOTIFICATION,
            signature_blocked=True,
        ).order_by('created_at', 'effect_type')
        if dispatch_ids is not None:
            queryset = queryset.filter(pk__in=dispatch_ids)
        try:
            dispatch = queryset.select_for_update(skip_locked=True).first()
        except NotImplementedError:
            dispatch = queryset.select_for_update().first()
        if dispatch is None:
            return None, None
        token = uuid.uuid4()
        dispatch.status = TatUpdateSideEffectDispatch.STATUS_RUNNING
        dispatch.lease_token = token
        dispatch.lease_started_at = now
        dispatch.cycle_attempts += 1
        dispatch.total_attempts += 1
        dispatch.next_retry_at = None
        dispatch.last_error_code = ''
        dispatch.last_error_message = ''
        dispatch.save(update_fields=[
            'status', 'lease_token', 'lease_started_at', 'cycle_attempts',
            'total_attempts', 'next_retry_at', 'last_error_code',
            'last_error_message', 'updated_at',
        ])
        return dispatch, token


def _group_config(case: TatTrackerCase) -> GroupSheetConfiguration:
    return GroupSheetConfiguration.objects.get(group_id=case.group_id)


def _run_effect(dispatch: TatUpdateSideEffectDispatch) -> str:
    case = TatTrackerCase.objects.prefetch_related('approval_certificates').get(pk=dispatch.case_id)
    # A newer authoritative update owns all projections and outbound messages.
    # Processing an older revision could otherwise publish stale state or send
    # an obsolete signature/next-role prompt.
    if case.workflow_revision != dispatch.workflow_revision:
        return TatUpdateSideEffectDispatch.STATUS_SUPERSEDED
    group_config = _group_config(case)
    if dispatch.effect_type == TatUpdateSideEffectDispatch.EFFECT_SHEET:
        from core.services.tat_tracker import sync_case_to_sheet
        sync_case_to_sheet(group_config, case)
        return TatUpdateSideEffectDispatch.STATUS_SUCCEEDED

    if dispatch.effect_type == TatUpdateSideEffectDispatch.EFFECT_SIGNATURE:
        from core.services.tat_signature import dispatch_certificate
        certificates = case.approval_certificates.filter(status__in=['awaiting_signature', 'delivery_failed'])
        for certificate in certificates:
            result = dispatch_certificate(certificate)
            certificate.status = 'signed'
            certificate.signed_document_hash = str(result.get('signed_doc_hash') or '')
            certificate.signed_at = timezone.now()
            certificate.error = ''
            certificate.save(update_fields=[
                'status', 'signed_document_hash', 'signed_at', 'error', 'updated_at',
            ])
        return TatUpdateSideEffectDispatch.STATUS_SUCCEEDED

    if dispatch.effect_type == TatUpdateSideEffectDispatch.EFFECT_NOTIFICATION:
        from core.services.tat_notifications import MODE_GROUP, dispatch_task, notification_mode
        if notification_mode(group_config) != MODE_GROUP:
            task = case.action_tasks.filter(
                case_revision=dispatch.workflow_revision,
                status='pending',
            ).order_by('-created_at').first()
            if task:
                dispatch_task(task.pk)
            return TatUpdateSideEffectDispatch.STATUS_SUCCEEDED
        from core.api.views import _post_telegram_reply
        from core.services.tat_tracker import next_role_alert, serialize_case_summary
        alert = next_role_alert(group_config, {'summary': serialize_case_summary(
            case, workflow=getattr(group_config, 'workflow', None) or {},
        )})
        if alert:
            if not _post_telegram_reply(group_config.group_id, {}, alert['text']):
                raise RuntimeError('Telegram next-role alert delivery did not complete.')
        return TatUpdateSideEffectDispatch.STATUS_SUCCEEDED

    raise ValueError('Unsupported TAT update dispatch effect.')


def _finish(dispatch_id, token, *, status: str, error: Exception | None = None) -> None:
    now = timezone.now()
    with transaction.atomic():
        dispatch = TatUpdateSideEffectDispatch.objects.select_for_update().get(pk=dispatch_id)
        if dispatch.lease_token != token or dispatch.status != TatUpdateSideEffectDispatch.STATUS_RUNNING:
            return
        dispatch.lease_token = None
        dispatch.lease_started_at = None
        if error is None:
            dispatch.status = status
            dispatch.completed_at = now
            dispatch.next_retry_at = None
        else:
            dispatch.last_error_code = type(error).__name__[:80]
            dispatch.last_error_message = 'External processing did not complete. Review monitoring before retrying.'
            if dispatch.cycle_attempts >= MAX_ATTEMPTS:
                dispatch.status = TatUpdateSideEffectDispatch.STATUS_NEEDS_ATTENTION
                dispatch.next_retry_at = None
                logger.error(
                    'TAT update dispatch needs attention: dispatch=%s effect=%s case=%s',
                    dispatch.pk, dispatch.effect_type, dispatch.case_id,
                )
            else:
                dispatch.status = TatUpdateSideEffectDispatch.STATUS_RETRYABLE
                delay_index = min(dispatch.cycle_attempts - 1, len(RETRY_DELAYS_SECONDS) - 1)
                dispatch.next_retry_at = now + timedelta(seconds=RETRY_DELAYS_SECONDS[delay_index])
        dispatch.save(update_fields=[
            'status', 'lease_token', 'lease_started_at', 'completed_at',
            'next_retry_at', 'last_error_code', 'last_error_message', 'updated_at',
        ])


def process_dispatches(*, limit: int = 50, dispatch_ids: list[str] | None = None) -> int:
    bounded = max(1, min(int(limit or 50), 500))
    processed = 0
    normalized_ids = [str(value) for value in (dispatch_ids or [])] if dispatch_ids is not None else None
    while processed < bounded:
        dispatch, token = _claim_one(dispatch_ids=normalized_ids)
        if dispatch is None:
            break
        try:
            status = _run_effect(dispatch)
        except Exception as exc:
            logger.exception('TAT update dispatch failed: dispatch=%s effect=%s', dispatch.pk, dispatch.effect_type)
            if dispatch.effect_type == TatUpdateSideEffectDispatch.EFFECT_SIGNATURE:
                TatTrackerApprovalCertificate.objects.filter(
                    case_id=dispatch.case_id, status='awaiting_signature',
                ).update(status='delivery_failed', error='Signature delivery did not complete.')
            _finish(dispatch.pk, token, status='', error=exc)
        else:
            _finish(dispatch.pk, token, status=status)
        processed += 1
    return processed


def retry_dispatch(dispatch: TatUpdateSideEffectDispatch, *, actor, reason: str) -> TatUpdateSideEffectDispatch:
    if not getattr(actor, 'is_active', False) or not getattr(actor, 'is_superuser', False):
        raise PermissionError('Only an active Django Superuser may retry this dispatch.')
    reason = str(reason or '').strip()
    if len(reason) < 10:
        raise ValueError('Explain why this dispatch is being retried (at least 10 characters).')
    with transaction.atomic():
        locked = TatUpdateSideEffectDispatch.objects.select_for_update().get(pk=dispatch.pk)
        if locked.status != TatUpdateSideEffectDispatch.STATUS_NEEDS_ATTENTION:
            raise ValueError('Only a dispatch needing attention can be retried manually.')
        locked.status = TatUpdateSideEffectDispatch.STATUS_PENDING
        locked.cycle_attempts = 0
        locked.next_retry_at = None
        locked.completed_at = None
        locked.manual_retry_reason = reason[:500]
        locked.manual_retry_by = actor
        locked.last_error_code = ''
        locked.last_error_message = ''
        locked.save(update_fields=[
            'status', 'cycle_attempts', 'next_retry_at', 'completed_at',
            'manual_retry_reason', 'manual_retry_by', 'last_error_code',
            'last_error_message', 'updated_at',
        ])
        return locked
