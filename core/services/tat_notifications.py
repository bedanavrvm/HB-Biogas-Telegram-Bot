"""Durable, private-first TAT action routing and Telegram delivery."""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta
from typing import Iterable

import requests
from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.utils import timezone

from core.models import (
    AccessGrant,
    GroupSheetConfiguration,
    TatActionTask,
    TatActionTaskLocator,
    TatActionTaskRecipient,
    TatGroupExceptionStatus,
    TatNotificationProcessorRun,
    TatPrivateAlertConnection,
    TatPrivateAlertConnectionEvent,
    TatResponsibilityAssignment,
    TatTaskRerouteEvent,
    TatTrackerCase,
    TatUpdateSideEffectDispatch,
)
from core.services.telegram_identity import database_group_configuration

logger = logging.getLogger(__name__)

MODE_GROUP = 'group'
MODE_SHADOW = 'shadow'
MODE_HYBRID = 'hybrid'
VALID_MODES = {MODE_GROUP, MODE_SHADOW, MODE_HYBRID}
LOCATOR_PREFIX = 'tt_'
LOCATOR_TTL = timedelta(hours=72)
TRANSIENT_DELIVERY_GRACE = timedelta(minutes=5)


def _record_connection_event(
    connection: TatPrivateAlertConnection,
    event_type: str,
    *,
    source: str,
    request_id: str = '',
    detail_code: str = '',
    actor=None,
) -> TatPrivateAlertConnectionEvent:
    """Append privacy-bounded connection evidence with retry idempotency."""
    key = str(request_id or '').strip()[:128]
    if key:
        existing = TatPrivateAlertConnectionEvent.objects.filter(request_id=key).first()
        if existing:
            return existing
    user = connection.user
    try:
        with transaction.atomic():
            return TatPrivateAlertConnectionEvent.objects.create(
                connection=connection,
                connection_id_snapshot=str(connection.pk or ''),
                user_id_snapshot=str(user.pk or ''),
                username_snapshot=user.get_username(),
                actor_id_snapshot=str(getattr(actor, 'pk', '') or ''),
                actor_username_snapshot=str(
                    actor.get_username() if actor and hasattr(actor, 'get_username') else ''
                )[:150],
                event_type=event_type,
                status=connection.status,
                source=str(source or '')[:32],
                request_id=key,
                detail_code=str(detail_code or '')[:80],
            )
    except IntegrityError:
        if key:
            return TatPrivateAlertConnectionEvent.objects.get(request_id=key)
        raise


def begin_notification_processor_run(
    *,
    trigger_source: str = TatNotificationProcessorRun.TRIGGER_SCHEDULED,
    actor=None,
    reason: str = '',
    request_id: str = '',
) -> tuple[TatNotificationProcessorRun, bool]:
    """Acquire the database-backed runner lock and retain one health row.

    The unique non-null lock key works across web and scheduler processes. A
    crashed process is failed closed after the configured lease and the next
    invocation can recover it without deleting its evidence.
    """
    now = timezone.now()
    request_key = str(request_id or '').strip()[:128]
    if request_key:
        existing = TatNotificationProcessorRun.objects.filter(request_id=request_key).first()
        if existing:
            return existing, False
    trigger_values = {
        'trigger_source': (
            TatNotificationProcessorRun.TRIGGER_ADMIN
            if trigger_source == TatNotificationProcessorRun.TRIGGER_ADMIN
            else TatNotificationProcessorRun.TRIGGER_SCHEDULED
        ),
        'triggered_by_id_snapshot': str(getattr(actor, 'pk', '') or ''),
        'triggered_by_username_snapshot': str(
            actor.get_username() if actor and hasattr(actor, 'get_username') else ''
        )[:150],
        'trigger_reason': str(reason or '').strip()[:500],
        'request_id': request_key,
    }
    lock_seconds = max(60, int(getattr(settings, 'TAT_NOTIFICATION_PROCESSOR_LOCK_SECONDS', 240)))
    stale_before = now - timedelta(seconds=lock_seconds)
    try:
        with transaction.atomic():
            active = TatNotificationProcessorRun.objects.select_for_update().filter(
                active_lock_key=TatNotificationProcessorRun.LOCK_KEY,
            ).first()
            if active and active.started_at >= stale_before:
                skipped = TatNotificationProcessorRun.objects.create(
                    status=TatNotificationProcessorRun.STATUS_SKIPPED_OVERLAP,
                    started_at=now,
                    completed_at=now,
                    error_code='active-run',
                    error_message='Another notification processor run still owns the lease.',
                    **trigger_values,
                )
                return skipped, False
            if active:
                active.status = TatNotificationProcessorRun.STATUS_FAILED
                active.active_lock_key = None
                active.completed_at = now
                active.error_code = 'stale-lock-recovered'
                active.error_message = 'The previous processor lease expired before completion.'
                active.save(update_fields=[
                    'status', 'active_lock_key', 'completed_at', 'error_code', 'error_message',
                ])
            run = TatNotificationProcessorRun.objects.create(
                status=TatNotificationProcessorRun.STATUS_RUNNING,
                active_lock_key=TatNotificationProcessorRun.LOCK_KEY,
                started_at=now,
                **trigger_values,
            )
            return run, True
    except IntegrityError:
        if request_key:
            existing = TatNotificationProcessorRun.objects.filter(request_id=request_key).first()
            if existing:
                return existing, False
        # Two workers can both observe no row before one wins the unique-key
        # insert. The loser records a harmless overlap rather than retrying.
        skipped = TatNotificationProcessorRun.objects.create(
            status=TatNotificationProcessorRun.STATUS_SKIPPED_OVERLAP,
            started_at=now,
            completed_at=now,
            error_code='lock-race',
            error_message='Another notification processor acquired the lease first.',
            **trigger_values,
        )
        return skipped, False


def _notification_delivery_counts() -> dict[str, int]:
    pending_tasks = TatActionTaskRecipient.objects.filter(task__status=TatActionTask.STATUS_PENDING)
    now = timezone.now()
    return {
        'retry_recipient_count': pending_tasks.filter(
            delivery_state=TatActionTaskRecipient.DELIVERY_RETRY,
        ).count(),
        'overdue_recipient_count': pending_tasks.filter(
            delivery_state__in=[
                TatActionTaskRecipient.DELIVERY_PENDING,
                TatActionTaskRecipient.DELIVERY_RETRY,
            ],
            deliver_after__isnull=False,
            deliver_after__lte=now,
        ).count(),
        'unreachable_recipient_count': pending_tasks.filter(
            delivery_state=TatActionTaskRecipient.DELIVERY_UNREACHABLE,
        ).count(),
    }


def finish_notification_processor_run(
    run: TatNotificationProcessorRun,
    *,
    processed_task_count: int = 0,
    processed_dispatch_count: int = 0,
    error: Exception | None = None,
) -> TatNotificationProcessorRun:
    """Release the runner lock and persist privacy-safe aggregate health."""
    counts = _notification_delivery_counts()
    now = timezone.now()
    with transaction.atomic():
        locked = TatNotificationProcessorRun.objects.select_for_update().get(pk=run.pk)
        locked.status = (
            TatNotificationProcessorRun.STATUS_FAILED
            if error else TatNotificationProcessorRun.STATUS_SUCCEEDED
        )
        locked.active_lock_key = None
        locked.completed_at = now
        locked.processed_task_count = max(0, int(processed_task_count))
        locked.processed_dispatch_count = max(0, int(processed_dispatch_count))
        locked.dispatch_attention_count = TatUpdateSideEffectDispatch.objects.filter(
            status=TatUpdateSideEffectDispatch.STATUS_NEEDS_ATTENTION,
        ).count()
        locked.retry_recipient_count = counts['retry_recipient_count']
        locked.overdue_recipient_count = counts['overdue_recipient_count']
        locked.unreachable_recipient_count = counts['unreachable_recipient_count']
        if error:
            locked.error_code = type(error).__name__[:80]
            locked.error_message = 'Notification processor failed; inspect server error monitoring.'
        locked.save(update_fields=[
            'status', 'active_lock_key', 'completed_at', 'processed_task_count',
            'processed_dispatch_count', 'dispatch_attention_count',
            'retry_recipient_count', 'overdue_recipient_count',
            'unreachable_recipient_count', 'error_code', 'error_message',
        ])
    retention_days = max(1, int(getattr(settings, 'TAT_NOTIFICATION_RUN_RETENTION_DAYS', 90)))
    try:
        TatNotificationProcessorRun.objects.filter(
            active_lock_key__isnull=True,
            completed_at__lt=now - timedelta(days=retention_days),
        ).exclude(pk=locked.pk).delete()
    except Exception:
        # Retention is maintenance, not delivery correctness. Preserve the
        # successful run and let monitoring surface the pruning fault.
        logger.exception('Pruning old TAT notification processor runs failed.')
    return locked


def notification_mode(group_config) -> str:
    workflow = getattr(group_config, 'workflow', None) or {}
    mode = str(workflow.get('tat_notification_mode') or MODE_GROUP).strip().lower()
    return mode if mode in VALID_MODES else MODE_GROUP


def _token_hash(token: str) -> str:
    return hashlib.sha256(str(token).encode('utf-8')).hexdigest()


def issue_locator(task: TatActionTask, recipient=None) -> str:
    """Issue a 192-bit, hash-only locator that fits Telegram's startapp budget."""
    token = secrets.token_urlsafe(24)
    TatActionTaskLocator.objects.create(
        task=task,
        recipient=recipient,
        token_hash=_token_hash(token),
        expires_at=timezone.now() + LOCATOR_TTL,
    )
    return token


def build_task_url(token: str) -> str:
    username = str(getattr(settings, 'TELEGRAM_BOT_USERNAME', '') or '').strip().lstrip('@')
    short_name = str(getattr(settings, 'TAT_TRACKER_MINI_APP_SHORT_NAME', '') or '').strip().strip('/')
    if username and short_name:
        return f'https://t.me/{username}/{short_name}?startapp={LOCATOR_PREFIX}{token}'
    base = str(getattr(settings, 'APP_BASE_URL', '') or '').rstrip('/')
    return f'{base}/api/tat-tracker/?startapp={LOCATOR_PREFIX}{token}'


def resolve_locator(token: str) -> TatActionTaskLocator | None:
    value = str(token or '').strip()
    if value.startswith(LOCATOR_PREFIX):
        value = value[len(LOCATOR_PREFIX):]
    if not value:
        return None
    return (
        TatActionTaskLocator.objects.select_related(
            'task__case', 'task__group_configuration', 'recipient',
        )
        .filter(token_hash=_token_hash(value))
        .first()
    )


def mark_private_alert_seen(user, *, allows_write: bool = False) -> TatPrivateAlertConnection | None:
    connection = TatPrivateAlertConnection.objects.filter(user=user).first()
    if not connection and not allows_write:
        return None
    if not connection:
        connection = TatPrivateAlertConnection.objects.create(user=user)
    if allows_write and connection.status != TatPrivateAlertConnection.STATUS_DISCONNECTED:
        now = timezone.now()
        status_changed = connection.status != TatPrivateAlertConnection.STATUS_CONNECTED
        connection.status = TatPrivateAlertConnection.STATUS_CONNECTED
        connection.connected_at = connection.connected_at or now
        connection.last_success_at = now
        connection.last_failure_code = ''
        connection.save(update_fields=[
            'status', 'connected_at', 'last_success_at', 'last_failure_code', 'updated_at',
        ])
        if status_changed:
            _record_connection_event(
                connection, TatPrivateAlertConnectionEvent.EVENT_CONNECTED,
                source='telegram_session', actor=user,
            )
    return connection


def connection_payload(user) -> dict:
    connection = TatPrivateAlertConnection.objects.filter(user=user).first()
    profile = getattr(user, 'staff_profile', None)
    status = connection.status if connection else TatPrivateAlertConnection.STATUS_UNKNOWN
    if not str(getattr(profile, 'telegram_id', '') or '').strip():
        status = TatPrivateAlertConnection.STATUS_UNCONNECTED
    return {
        'status': status,
        'connected': status == TatPrivateAlertConnection.STATUS_CONNECTED,
        'connected_at': connection.connected_at.isoformat() if connection and connection.connected_at else '',
        'disconnected_at': connection.disconnected_at.isoformat() if connection and connection.disconnected_at else '',
        'last_success_at': connection.last_success_at.isoformat() if connection and connection.last_success_at else '',
        'last_failure_at': connection.last_failure_at.isoformat() if connection and connection.last_failure_at else '',
        'last_failure_code': connection.last_failure_code if connection else '',
    }


def _group_row(group_config) -> GroupSheetConfiguration | None:
    return database_group_configuration(group_config)


def _grant_matches(grant: AccessGrant, *, group, branch: str, product_key: str, role: str) -> bool:
    if not grant.active or str(grant.role or '').upper() != role.upper():
        return False
    if grant.group_configuration_id and (not group or grant.group_configuration_id != group.pk):
        return False
    if grant.branch and str(grant.branch).casefold() != str(branch).casefold():
        return False
    if grant.product and str(grant.product).casefold() != str(product_key).casefold():
        return False
    return bool(grant.user.is_active)


def user_can_receive_task(user, *, group, case: TatTrackerCase, role: str) -> bool:
    return user_can_receive_scope(
        user, group=group, branch=case.branch,
        product_key=case.product_key, role=role,
    )


def user_can_receive_scope(user, *, group, branch: str, product_key: str, role: str) -> bool:
    """Require an explicit matching grant for routine notification routing.

    Django Superusers retain break-glass action authority elsewhere, but are
    not silently enrolled in operational task delivery.
    """
    if not user or not user.is_active:
        return False
    grants = AccessGrant.objects.filter(
        user=user, workflow='tat_tracker', active=True,
    ).select_related('user', 'group_configuration')
    return any(_grant_matches(
        grant, group=group, branch=branch,
        product_key=product_key, role=role,
    ) for grant in grants)


def eligible_role_users(*, group, case: TatTrackerCase, role: str) -> list:
    grants = AccessGrant.objects.filter(
        workflow='tat_tracker', active=True, user__is_active=True,
        role__iexact=role,
    ).filter(Q(group_configuration__isnull=True) | Q(group_configuration=group)).select_related(
        'user', 'user__staff_profile', 'group_configuration',
    )
    users = {}
    for grant in grants:
        if _grant_matches(grant, group=group, branch=case.branch, product_key=case.product_key, role=role):
            users[grant.user_id] = grant.user
    return list(users.values())


def resolve_assignment(*, group, case: TatTrackerCase, role: str, stage_key: str):
    if not group:
        return None
    now = timezone.now()
    assignments = TatResponsibilityAssignment.objects.filter(
        group_configuration=group, branch__iexact=case.branch, role__iexact=role,
        active=True, effective_from__lte=now,
    ).filter(Q(effective_until__isnull=True) | Q(effective_until__gt=now)).select_related(
        'primary_user', 'primary_user__staff_profile',
    ).prefetch_related('backups__user', 'backups__user__staff_profile')
    candidates = []
    for assignment in assignments:
        if assignment.product_key and assignment.product_key.casefold() != case.product_key.casefold():
            continue
        if assignment.stage_key and assignment.stage_key != stage_key:
            continue
        specificity = int(bool(assignment.product_key)) + (2 * int(bool(assignment.stage_key)))
        candidates.append((specificity, assignment))
    if not candidates:
        return None
    highest_specificity = max(item[0] for item in candidates)
    winners = [assignment for specificity, assignment in candidates if specificity == highest_specificity]
    if len(winners) != 1:
        logger.error(
            'Ambiguous TAT responsibility assignment; routing through safe role fallback.',
            extra={
                'group_configuration_id': getattr(group, 'pk', None),
                'case_id': case.case_id,
                'role': role,
                'stage_key': stage_key,
                'assignment_ids': [str(item.pk) for item in winners],
            },
        )
        return None
    return winners[0]


def _stage_started_at(case: TatTrackerCase, stage_key: str):
    snapshot = (case.stage_target_snapshots or {}).get(stage_key) or {}
    raw = snapshot.get('started_at')
    if raw:
        try:
            parsed = datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
            return parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed)
        except (TypeError, ValueError):
            pass
    return case.updated_at or case.created_at or timezone.now()


def _backup_due_at(case: TatTrackerCase, stage_key: str, threshold_percent: int):
    snapshot = (case.stage_target_snapshots or {}).get(stage_key) or {}
    try:
        target_minutes = float(snapshot.get('target_minutes'))
    except (TypeError, ValueError):
        return None
    return _stage_started_at(case, stage_key) + timedelta(
        minutes=target_minutes * (int(threshold_percent) / 100),
    )


def _connection_status(user) -> str:
    profile = getattr(user, 'staff_profile', None)
    if not str(getattr(profile, 'telegram_id', '') or '').strip():
        return TatPrivateAlertConnection.STATUS_UNCONNECTED
    connection = TatPrivateAlertConnection.objects.filter(user=user).first()
    return connection.status if connection else TatPrivateAlertConnection.STATUS_UNKNOWN


def _routing_recipients(*, group, case: TatTrackerCase, role: str, stage_key: str):
    """Resolve the current assignment to an explicit, access-checked roster."""
    assignment = resolve_assignment(group=group, case=case, role=role, stage_key=stage_key)
    recipients = []
    recipient_user_ids = set()
    invalid_assignment = False
    if assignment:
        if user_can_receive_task(assignment.primary_user, group=group, case=case, role=role):
            recipients.append((assignment.primary_user, TatActionTaskRecipient.KIND_PRIMARY, 0, None))
            recipient_user_ids.add(assignment.primary_user_id)
        else:
            invalid_assignment = True
        for backup in assignment.backups.filter(active=True).select_related('user').order_by('rank'):
            if (
                backup.user_id not in recipient_user_ids
                and user_can_receive_task(backup.user, group=group, case=case, role=role)
            ):
                recipients.append((
                    backup.user, TatActionTaskRecipient.KIND_BACKUP,
                    backup.rank, backup.threshold_percent,
                ))
                recipient_user_ids.add(backup.user_id)
            else:
                invalid_assignment = True
    if not recipients:
        recipients = [
            (user, TatActionTaskRecipient.KIND_ROLE, index + 1, None)
            for index, user in enumerate(eligible_role_users(group=group, case=case, role=role))
        ]
    return assignment, recipients, invalid_assignment


@transaction.atomic
def synchronize_case_task(
    group_config, case: TatTrackerCase, *, actor_user=None, dispatch_on_commit: bool = True,
) -> TatActionTask | None:
    """Supersede stale work and create exactly one task for the current revision."""
    mode = notification_mode(group_config)
    if mode == MODE_GROUP:
        return None
    from core.services.tat_tracker import next_action

    group = _group_row(group_config)
    stage = next_action(case)
    pending = list(TatActionTask.objects.select_for_update().filter(case=case, status=TatActionTask.STATUS_PENDING))
    if not stage:
        now = timezone.now()
        for old in pending:
            old.status = TatActionTask.STATUS_ACTED if actor_user else TatActionTask.STATUS_CANCELLED
            old.acted_by = actor_user
            old.acted_at = now if actor_user else None
            old.save(update_fields=['status', 'acted_by', 'acted_at', 'updated_at'])
            old.recipients.update(
                inbox_status=(TatActionTaskRecipient.INBOX_ACTED if actor_user else TatActionTaskRecipient.INBOX_SUPERSEDED),
                updated_at=now,
            )
            old.locators.filter(revoked_at__isnull=True).update(revoked_at=now)
        if group:
            transaction.on_commit(lambda: safe_refresh_group_exception(group.pk))
        return None

    existing = TatActionTask.objects.filter(
        case=case, stage_key=stage.key, case_revision=case.workflow_revision,
    ).first()
    if existing:
        return existing

    previous = pending[0] if pending else None
    now = timezone.now()
    for old in pending:
        completed_stage = old.stage_key != stage.key
        old.status = TatActionTask.STATUS_ACTED if completed_stage and actor_user else TatActionTask.STATUS_SUPERSEDED
        old.acted_by = actor_user if completed_stage else None
        old.acted_at = now if completed_stage and actor_user else None
        old.save(update_fields=['status', 'acted_by', 'acted_at', 'updated_at'])
        old.recipients.update(
            inbox_status=(TatActionTaskRecipient.INBOX_ACTED if completed_stage else TatActionTaskRecipient.INBOX_SUPERSEDED),
            updated_at=now,
        )
        old.locators.filter(revoked_at__isnull=True).update(revoked_at=now)

    assignment, recipients, invalid_assignment = _routing_recipients(
        group=group, case=case, role=stage.role, stage_key=stage.key,
    )

    task = TatActionTask.objects.create(
        case=case, group_configuration=group, assignment=assignment,
        stage_key=stage.key, stage_label=stage.label, responsible_role=stage.role,
        case_revision=case.workflow_revision,
        recipient_snapshot={
            'invalid_assignment': invalid_assignment,
            'assignment_id': str(assignment.pk) if assignment else '',
            'recipient_user_ids': [user.pk for user, _kind, _rank, _threshold in recipients],
            'delivery_exception': not bool(recipients),
        },
    )
    previous_delivered_user_ids = set()
    if previous and previous.stage_key == stage.key:
        previous_delivered_user_ids = set(previous.recipients.filter(
            delivery_state=TatActionTaskRecipient.DELIVERY_DELIVERED,
        ).values_list('user_id', flat=True))
    created_rows = []
    for user, kind, rank, threshold in recipients:
        deliver_after = now if kind in {TatActionTaskRecipient.KIND_PRIMARY, TatActionTaskRecipient.KIND_ROLE} else _backup_due_at(case, stage.key, threshold)
        delivery_state = TatActionTaskRecipient.DELIVERY_PENDING
        if user.pk in previous_delivered_user_ids:
            delivery_state = TatActionTaskRecipient.DELIVERY_SKIPPED
            deliver_after = None
        created_rows.append(TatActionTaskRecipient(
            task=task, user=user, kind=kind, rank=rank,
            threshold_percent=threshold, deliver_after=deliver_after,
            delivery_state=delivery_state,
        ))
    TatActionTaskRecipient.objects.bulk_create(created_rows)
    for old in pending:
        if old.status == TatActionTask.STATUS_SUPERSEDED:
            old.superseded_by = task
            old.save(update_fields=['superseded_by', 'updated_at'])
    if dispatch_on_commit:
        transaction.on_commit(lambda task_id=task.pk: safe_dispatch_task(task_id))
    if group:
        transaction.on_commit(lambda group_id=group.pk: safe_refresh_group_exception(group_id))
    return task


@transaction.atomic
def reroute_pending_task(*, task: TatActionTask, actor, reason: str, request_id: str) -> TatActionTask:
    """Atomically replace a pending task roster using the latest approved responsibility."""
    if not getattr(actor, 'is_superuser', False):
        raise ValueError('Only a Django Superuser may reroute open TAT tasks.')
    reason = str(reason or '').strip()
    request_id = str(request_id or '').strip()
    if len(reason) < 10:
        raise ValueError('Explain why this reroute is required (at least 10 characters).')
    if not request_id:
        raise ValueError('A request ID is required.')
    task = TatActionTask.objects.select_related('case', 'group_configuration').get(pk=task.pk)
    # The case lock is shared with stage completion. Whichever operation wins
    # commits first; the loser then revalidates the terminal/pending state.
    case = TatTrackerCase.objects.select_for_update().get(pk=task.case_id)
    task = TatActionTask.objects.select_for_update().select_related(
        'case', 'group_configuration',
    ).get(pk=task.pk)
    existing_event = TatTaskRerouteEvent.objects.filter(task=task, request_id=request_id).first()
    if existing_event:
        return task
    if task.status != TatActionTask.STATUS_PENDING:
        raise ValueError('This task was already completed or superseded; it was not rerouted.')
    from core.services.tat_tracker import next_action
    current_stage = next_action(case)
    if not current_stage or current_stage.key != task.stage_key or case.workflow_revision != task.case_revision:
        raise ValueError('The case changed before rerouting. Refresh and review its current task.')
    assignment, recipients, invalid_assignment = _routing_recipients(
        group=task.group_configuration, case=case,
        role=task.responsible_role, stage_key=task.stage_key,
    )
    now = timezone.now()
    before_rows = list(task.recipients.select_for_update().order_by('rank', 'created_at'))
    before_snapshot = {
        'assignment_id': str(task.assignment_id or ''),
        'routing_generation': task.routing_generation,
        'recipients': [
            {'user_id': row.user_id, 'kind': row.kind, 'rank': row.rank}
            for row in before_rows
        ],
    }
    generation = task.routing_generation + 1
    intended = {user.pk: (user, kind, rank, threshold) for user, kind, rank, threshold in recipients}
    existing_by_user = {row.user_id: row for row in before_rows}
    removed_user_ids = set(existing_by_user) - set(intended)
    if removed_user_ids:
        task.locators.filter(recipient_id__in=removed_user_ids, revoked_at__isnull=True).update(revoked_at=now)
    for user_id, row in existing_by_user.items():
        if user_id not in intended:
            row.inbox_status = TatActionTaskRecipient.INBOX_SUPERSEDED
            row.delivery_state = TatActionTaskRecipient.DELIVERY_SKIPPED
            row.delivery_error = 'Superseded by an explicit task reroute.'
            row.deliver_after = None
            row.save(update_fields=[
                'inbox_status', 'delivery_state', 'delivery_error', 'deliver_after', 'updated_at',
            ])
            continue
        _user, kind, rank, threshold = intended[user_id]
        row.kind = kind
        row.rank = rank
        row.threshold_percent = threshold
        row.routing_generation = generation
        if row.inbox_status == TatActionTaskRecipient.INBOX_SUPERSEDED:
            row.inbox_status = TatActionTaskRecipient.INBOX_UNREAD
        row.save(update_fields=[
            'kind', 'rank', 'threshold_percent', 'routing_generation', 'inbox_status', 'updated_at',
        ])
    for user_id, (user, kind, rank, threshold) in intended.items():
        if user_id in existing_by_user:
            continue
        immediate = kind in {TatActionTaskRecipient.KIND_PRIMARY, TatActionTaskRecipient.KIND_ROLE}
        TatActionTaskRecipient.objects.create(
            task=task, user=user, kind=kind, rank=rank, threshold_percent=threshold,
            routing_generation=generation,
            deliver_after=now if immediate else _backup_due_at(case, task.stage_key, threshold),
        )
    task.assignment = assignment
    task.routing_generation = generation
    task.recipient_snapshot = {
        'invalid_assignment': invalid_assignment,
        'assignment_id': str(assignment.pk) if assignment else '',
        'recipient_user_ids': sorted(intended),
        'delivery_exception': not bool(intended),
        'rerouted_at': now.isoformat(),
    }
    task.save(update_fields=['assignment', 'routing_generation', 'recipient_snapshot', 'updated_at'])
    after_snapshot = {
        'assignment_id': str(task.assignment_id or ''),
        'routing_generation': generation,
        'recipients': [
            {'user_id': user.pk, 'kind': kind, 'rank': rank}
            for user, kind, rank, _threshold in recipients
        ],
    }
    TatTaskRerouteEvent.objects.create(
        task=task, actor=actor, request_id=request_id, reason=reason,
        generation_before=before_snapshot['routing_generation'], generation_after=generation,
        before_snapshot=before_snapshot, after_snapshot=after_snapshot,
    )
    transaction.on_commit(lambda task_id=task.pk: safe_dispatch_task(task_id))
    if task.group_configuration_id:
        transaction.on_commit(lambda group_id=task.group_configuration_id: safe_refresh_group_exception(group_id))
    return task


def _telegram_request(method: str, payload: dict):
    token = str(getattr(settings, 'TELEGRAM_BOT_TOKEN', '') or '')
    if not token:
        raise RuntimeError('Telegram bot delivery is not configured.')
    response = requests.post(
        f'https://api.telegram.org/bot{token}/{method}', json=payload,
        timeout=getattr(settings, 'API_REQUEST_TIMEOUT', 10),
    )
    data = response.json() if response.content else {}
    if not response.ok or not data.get('ok'):
        error = requests.HTTPError(f'Telegram delivery failed ({response.status_code}).')
        error.response = response
        raise error
    return data.get('result') or {}


def _reset_private_chat_menu(telegram_id: str) -> None:
    """Remove a stale default Mini App button from a TAT alert chat.

    Telegram can retain a bot-level Web App menu button (for example, an old
    Order Approval launcher) in a user's private chat.  TAT task buttons are
    issued separately as scoped inline links, so this chat-specific override
    safely restores the ordinary commands menu without changing task access.
    A menu reset is cosmetic and must never prevent durable alert connection.
    """
    try:
        _telegram_request('setChatMenuButton', {
            'chat_id': telegram_id,
            'menu_button': {'type': 'commands'},
        })
    except Exception as exc:
        logger.warning(
            'Could not reset the private Telegram menu during TAT alert connection: %s',
            type(exc).__name__,
        )


def _send_recipient(recipient: TatActionTaskRecipient) -> bool:
    # Claim the row before crossing the Telegram boundary. A concurrent web
    # request or scheduler run will see the future retry time and cannot send
    # the same prompt. If this process dies mid-request, the claim naturally
    # becomes retryable after one minute.
    now = timezone.now()
    with transaction.atomic():
        # Lock only the recipient row. Joining nullable relations such as the
        # reverse staff profile or optional group configuration makes
        # PostgreSQL reject FOR UPDATE with "nullable side of an outer join".
        # Related objects are loaded lazily after this short claim transaction.
        recipient = TatActionTaskRecipient.objects.select_for_update().get(pk=recipient.pk)
        task_generation = TatActionTask.objects.select_for_update().values_list(
            'routing_generation', flat=True,
        ).get(pk=recipient.task_id)
        if recipient.routing_generation != task_generation:
            return False
        if recipient.delivery_state == TatActionTaskRecipient.DELIVERY_DELIVERED:
            return True
        if recipient.delivery_state not in {
            TatActionTaskRecipient.DELIVERY_PENDING,
            TatActionTaskRecipient.DELIVERY_RETRY,
        }:
            return False
        if recipient.deliver_after and recipient.deliver_after > now:
            return False
        recipient.delivery_attempts += 1
        recipient.delivery_state = TatActionTaskRecipient.DELIVERY_RETRY
        recipient.deliver_after = now + timedelta(minutes=1)
        recipient.save(update_fields=[
            'delivery_attempts', 'delivery_state', 'deliver_after', 'updated_at',
        ])
        claimed_generation = recipient.routing_generation
    user = recipient.user
    profile = getattr(user, 'staff_profile', None)
    chat_id = str(getattr(profile, 'telegram_id', '') or '').strip()
    connection, _ = TatPrivateAlertConnection.objects.get_or_create(user=user)
    if not user_can_receive_task(
        user,
        group=recipient.task.group_configuration,
        case=recipient.task.case,
        role=recipient.task.responsible_role,
    ):
        recipient.delivery_state = TatActionTaskRecipient.DELIVERY_UNREACHABLE
        recipient.delivery_error = 'The recipient no longer has the required TAT access scope.'
        recipient.save(update_fields=['delivery_state', 'delivery_error', 'updated_at'])
        return False
    known_status = _connection_status(user)
    if known_status in {
        TatPrivateAlertConnection.STATUS_UNCONNECTED,
        TatPrivateAlertConnection.STATUS_DISCONNECTED,
        TatPrivateAlertConnection.STATUS_BLOCKED,
    } or not chat_id:
        recipient.delivery_state = TatActionTaskRecipient.DELIVERY_UNREACHABLE
        recipient.delivery_error = 'Private alerts are not connected.'
        recipient.save(update_fields=['delivery_state', 'delivery_error', 'delivery_attempts', 'updated_at'])
        return False
    token = issue_locator(recipient.task, user)
    locator = resolve_locator(token)
    url = build_task_url(token)
    text = (
        '⏰ Action Required\n\n'
        'A TAT task requires your attention.\n\n'
        f'Stage: {recipient.task.stage_label}\n'
        f'Branch: {recipient.task.case.branch or "Not provided"}\n'
        f'Product: {recipient.task.case.product_label or recipient.task.case.product_key or "Not provided"}\n'
        f'Reference: {recipient.task.case.case_id}\n\n'
        'Open the task to review the details and confirm the required action.'
    )
    try:
        result = _telegram_request('sendMessage', {
            'chat_id': chat_id,
            'text': text,
            'reply_markup': {'inline_keyboard': [[{'text': 'Open TAT Task', 'url': url}]]},
        })
    except requests.HTTPError as exc:
        if locator:
            locator.revoked_at = timezone.now()
            locator.save(update_fields=['revoked_at'])
        code = getattr(getattr(exc, 'response', None), 'status_code', 0)
        permanent = code in {400, 403}
        recipient.delivery_state = (
            TatActionTaskRecipient.DELIVERY_UNREACHABLE if permanent
            else TatActionTaskRecipient.DELIVERY_RETRY
        )
        recipient.delivery_error = f'Telegram HTTP {code or "error"}'
        if not permanent and now - recipient.created_at < TRANSIENT_DELIVERY_GRACE:
            recipient.deliver_after = now + timedelta(minutes=1)
        else:
            recipient.delivery_state = TatActionTaskRecipient.DELIVERY_UNREACHABLE
        failure_status = (
            TatPrivateAlertConnection.STATUS_BLOCKED if permanent
            else TatPrivateAlertConnection.STATUS_TEMPORARY_FAILURE
        )
        TatPrivateAlertConnection.objects.filter(pk=connection.pk).exclude(
            status=TatPrivateAlertConnection.STATUS_DISCONNECTED,
        ).update(
            status=failure_status, last_failure_at=now,
            last_failure_code=str(code or 'network'), updated_at=now,
        )
        connection.refresh_from_db()
        _record_connection_event(
            connection, TatPrivateAlertConnectionEvent.EVENT_DELIVERY_FAILED,
            source='task_delivery',
            request_id=f'task-delivery:{recipient.pk}:{recipient.delivery_attempts}',
            detail_code=str(code or 'network'),
        )
        recipient.save(update_fields=[
            'delivery_state', 'delivery_error', 'delivery_attempts', 'deliver_after', 'updated_at',
        ])
        return False
    except (requests.RequestException, RuntimeError):
        if locator:
            locator.revoked_at = timezone.now()
            locator.save(update_fields=['revoked_at'])
        recipient.delivery_state = TatActionTaskRecipient.DELIVERY_RETRY
        recipient.delivery_error = 'Temporary Telegram delivery failure.'
        recipient.deliver_after = now + timedelta(minutes=1)
        if now - recipient.created_at >= TRANSIENT_DELIVERY_GRACE:
            recipient.delivery_state = TatActionTaskRecipient.DELIVERY_UNREACHABLE
        TatPrivateAlertConnection.objects.filter(pk=connection.pk).exclude(
            status=TatPrivateAlertConnection.STATUS_DISCONNECTED,
        ).update(
            status=TatPrivateAlertConnection.STATUS_TEMPORARY_FAILURE,
            last_failure_at=now, last_failure_code='network', updated_at=now,
        )
        connection.refresh_from_db()
        _record_connection_event(
            connection, TatPrivateAlertConnectionEvent.EVENT_DELIVERY_FAILED,
            source='task_delivery',
            request_id=f'task-delivery:{recipient.pk}:{recipient.delivery_attempts}',
            detail_code='network',
        )
        recipient.save(update_fields=[
            'delivery_state', 'delivery_error', 'delivery_attempts', 'deliver_after', 'updated_at',
        ])
        return False
    with transaction.atomic():
        current = TatActionTaskRecipient.objects.select_for_update().select_related('task').get(pk=recipient.pk)
        if (
            current.routing_generation != claimed_generation
            or current.task.routing_generation != claimed_generation
            or current.task.status != TatActionTask.STATUS_PENDING
        ):
            if locator:
                locator.revoked_at = timezone.now()
                locator.save(update_fields=['revoked_at'])
            current.delivery_state = TatActionTaskRecipient.DELIVERY_SKIPPED
            current.delivery_error = 'Delivery became stale during rerouting.'
            current.deliver_after = None
            current.save(update_fields=['delivery_state', 'delivery_error', 'deliver_after', 'updated_at'])
            return False
        current.delivery_state = TatActionTaskRecipient.DELIVERY_DELIVERED
        current.delivery_error = ''
        current.telegram_message_id = str(result.get('message_id') or '')
        current.delivered_at = now
        current.save(update_fields=[
            'delivery_state', 'delivery_error', 'telegram_message_id', 'delivered_at',
            'delivery_attempts', 'updated_at',
        ])
    TatPrivateAlertConnection.objects.filter(pk=connection.pk).exclude(
        status=TatPrivateAlertConnection.STATUS_DISCONNECTED,
    ).update(
        status=TatPrivateAlertConnection.STATUS_CONNECTED,
        connected_at=connection.connected_at or now,
        last_success_at=now, last_failure_code='', updated_at=now,
    )
    connection.refresh_from_db()
    _record_connection_event(
        connection, TatPrivateAlertConnectionEvent.EVENT_DELIVERY_SUCCEEDED,
        source='task_delivery',
        request_id=f'task-delivery:{recipient.pk}:{recipient.delivery_attempts}',
    )
    return True


def _advance_unreachable_backup(task: TatActionTask) -> bool:
    now = timezone.now()
    rows = list(task.recipients.select_related('user', 'user__staff_profile').order_by('rank', 'created_at'))
    immediate = [row for row in rows if row.kind in {
        TatActionTaskRecipient.KIND_PRIMARY, TatActionTaskRecipient.KIND_ROLE,
    }]
    if any(row.delivery_state == TatActionTaskRecipient.DELIVERY_DELIVERED for row in immediate):
        return True
    if immediate and not all(row.delivery_state == TatActionTaskRecipient.DELIVERY_UNREACHABLE for row in immediate):
        return True
    for backup in [row for row in rows if row.kind == TatActionTaskRecipient.KIND_BACKUP]:
        if backup.delivery_state in {
            TatActionTaskRecipient.DELIVERY_DELIVERED,
            TatActionTaskRecipient.DELIVERY_PENDING,
            TatActionTaskRecipient.DELIVERY_RETRY,
        }:
            if backup.delivery_state == TatActionTaskRecipient.DELIVERY_DELIVERED:
                return True
            backup.deliver_after = now
            backup.save(update_fields=['deliver_after', 'updated_at'])
            return _send_recipient(backup) or _advance_unreachable_backup(task)
    return False


def _advance_after_failed_backup(task: TatActionTask, failed_rank: int) -> bool:
    """Do not wait for a later threshold when the alerted backup is unreachable."""
    now = timezone.now()
    for backup in task.recipients.select_related('user', 'user__staff_profile').filter(
        kind=TatActionTaskRecipient.KIND_BACKUP,
        rank__gt=failed_rank,
        delivery_state__in=[
            TatActionTaskRecipient.DELIVERY_PENDING,
            TatActionTaskRecipient.DELIVERY_RETRY,
        ],
    ).order_by('rank'):
        backup.deliver_after = now
        backup.save(update_fields=['deliver_after', 'updated_at'])
        if _send_recipient(backup):
            return True
        if backup.delivery_state == TatActionTaskRecipient.DELIVERY_UNREACHABLE:
            continue
        return True
    return False


def dispatch_task(task_id) -> None:
    task = TatActionTask.objects.select_related(
        'case', 'group_configuration',
    ).filter(pk=task_id, status=TatActionTask.STATUS_PENDING).first()
    if not task:
        return
    group_config = task.group_configuration
    mode = notification_mode(group_config) if group_config else MODE_SHADOW
    now = timezone.now()
    due = list(task.recipients.select_related('user', 'user__staff_profile').filter(
        routing_generation=task.routing_generation,
        delivery_state__in=[TatActionTaskRecipient.DELIVERY_PENDING, TatActionTaskRecipient.DELIVERY_RETRY],
        deliver_after__isnull=False, deliver_after__lte=now,
    ).order_by('rank', 'created_at'))
    if mode == MODE_SHADOW:
        TatActionTaskRecipient.objects.filter(pk__in=[row.pk for row in due]).update(
            delivery_state=TatActionTaskRecipient.DELIVERY_SHADOW,
            delivery_error='Would send private TAT alert.', updated_at=now,
        )
        snapshot = dict(task.recipient_snapshot or {})
        snapshot['shadow_evaluated_at'] = now.isoformat()
        snapshot['would_group_fallback'] = not task.recipients.exists()
        task.recipient_snapshot = snapshot
        task.save(update_fields=['recipient_snapshot', 'updated_at'])
        return
    if mode != MODE_HYBRID:
        return
    for recipient in due:
        _send_recipient(recipient)
        recipient.refresh_from_db(fields=['delivery_state'])
    failed_backup_ranks = [
        row.rank for row in due
        if row.kind == TatActionTaskRecipient.KIND_BACKUP
        and row.delivery_state == TatActionTaskRecipient.DELIVERY_UNREACHABLE
    ]
    if failed_backup_ranks:
        reachable = _advance_after_failed_backup(task, max(failed_backup_ranks))
    else:
        reachable = _advance_unreachable_backup(task)
    snapshot = dict(task.recipient_snapshot or {})
    snapshot['delivery_exception'] = not reachable
    task.recipient_snapshot = snapshot
    task.save(update_fields=['recipient_snapshot', 'updated_at'])
    if group_config:
        refresh_group_exception(group_config.pk, role=task.responsible_role)


def safe_dispatch_task(task_id) -> None:
    try:
        dispatch_task(task_id)
    except Exception:
        logger.exception('TAT private task delivery failed for task=%s.', task_id)


def safe_refresh_group_exception(group_id) -> None:
    try:
        refresh_group_exception(group_id)
    except Exception:
        logger.exception('TAT private-delivery exception status refresh failed for group=%s.', group_id)


def retire_group_exception_messages(*, limit: int = 100) -> int:
    """Delete legacy public exception posts without creating replacements.

    Private inbox and Telegram delivery are now the only alert channels.  The
    status rows remain useful as privacy-safe Admin diagnostics, while this
    bounded cleanup makes the scheduled/manual processor retire posts created
    by older deployments even when no task for that group is currently due.
    """
    statuses = list(TatGroupExceptionStatus.objects.select_related(
        'group_configuration',
    ).exclude(telegram_message_id='').order_by('last_attempt_at', 'pk')[:limit])
    retired = 0
    for status in statuses:
        status.last_attempt_at = timezone.now()
        try:
            _telegram_request('deleteMessage', {
                'chat_id': status.group_configuration.group_id,
                'message_id': status.telegram_message_id,
            })
        except Exception:
            status.last_error = 'The legacy public TAT exception message could not be removed.'
            logger.warning(
                'Legacy public TAT exception removal failed for group=%s role=%s',
                status.group_configuration_id, status.responsible_role,
            )
        else:
            status.telegram_message_id = ''
            status.last_error = ''
            retired += 1
        status.save(update_fields=[
            'telegram_message_id', 'last_error', 'last_attempt_at', 'updated_at',
        ])
    return retired


def process_due_tasks(*, limit: int = 100) -> int:
    # Remove posts produced by the retired public fallback, including on runs
    # where no task is due. Failures remain visible on the diagnostic row and
    # are retried by the next scheduled/manual run.
    retire_group_exception_messages(limit=limit)
    task_ids = list(TatActionTaskRecipient.objects.filter(
        task__status=TatActionTask.STATUS_PENDING,
        routing_generation=F('task__routing_generation'),
        delivery_state__in=[TatActionTaskRecipient.DELIVERY_PENDING, TatActionTaskRecipient.DELIVERY_RETRY],
        deliver_after__isnull=False, deliver_after__lte=timezone.now(),
    ).values_list('task_id', flat=True).distinct()[:limit])
    for task_id in task_ids:
        dispatch_task(task_id)
    return len(task_ids)


@transaction.atomic
def refresh_group_exception(group_id, *, role: str = '') -> None:
    # Keep a privacy-safe Admin diagnostic count. Public group fallbacks are
    # retired: task alerts and escalations are delivered privately only.
    group = GroupSheetConfiguration.objects.select_for_update().filter(pk=group_id).first()
    if not group or notification_mode(group) != MODE_HYBRID:
        return
    roles: Iterable[str]
    if role:
        roles = [role]
    else:
        roles = TatActionTask.objects.filter(
            group_configuration=group, status=TatActionTask.STATUS_PENDING,
        ).values_list('responsible_role', flat=True).distinct()
    for responsible_role in roles:
        stuck = TatActionTask.objects.filter(
            group_configuration=group, responsible_role=responsible_role,
            status=TatActionTask.STATUS_PENDING,
            recipient_snapshot__delivery_exception=True,
        ).order_by('created_at')
        count = stuck.count()
        status, _ = TatGroupExceptionStatus.objects.get_or_create(
            group_configuration=group, responsible_role=responsible_role,
        )
        status.unresolved_count = count
        status.oldest_task_at = stuck.values_list('created_at', flat=True).first() if count else None
        status.active = bool(count)
        status.last_attempt_at = timezone.now()
        if status.telegram_message_id:
            try:
                _telegram_request('deleteMessage', {
                    'chat_id': group.group_id,
                    'message_id': status.telegram_message_id,
                })
                status.telegram_message_id = ''
                status.last_error = ''
            except Exception:
                status.last_error = 'The legacy public TAT exception message could not be removed.'
                logger.warning(
                    'Legacy public TAT exception removal failed for group=%s role=%s',
                    group.pk, responsible_role,
                )
        else:
            status.last_error = ''
        status.save()


def inbox_payload(
    user,
    *,
    group=None,
    group_id: str = '',
    limit: int = 50,
    offset: int = 0,
    product_key: str = '',
    branch: str = '',
    product_keys=None,
    branches=None,
    statuses=None,
) -> dict:
    if not user or not user.is_active:
        return {'items': [], 'unread_count': 0, 'total': 0, 'pagination': {
            'offset': 0, 'page_size': max(1, min(limit, 100)), 'total': 0, 'has_more': False,
        }}
    recipients = TatActionTaskRecipient.objects.select_related(
        'task__case', 'task__group_configuration',
    ).filter(
        user=user, task__status=TatActionTask.STATUS_PENDING,
        routing_generation=F('task__routing_generation'),
        inbox_status__in=[TatActionTaskRecipient.INBOX_UNREAD, TatActionTaskRecipient.INBOX_READ],
    )
    if group:
        recipients = recipients.filter(task__group_configuration=group)
    elif str(group_id or '').strip():
        recipients = recipients.filter(task__case__group_id=str(group_id).strip())
    def selected_values(values, legacy=''):
        source = values if values not in (None, '') else legacy
        if isinstance(source, str):
            source = source.split(',')
        if not isinstance(source, (list, tuple, set)):
            source = [source]
        return list(dict.fromkeys(str(value or '').strip() for value in source if str(value or '').strip()))

    selected_products = selected_values(product_keys, product_key)
    selected_branches = selected_values(branches, branch)
    from core.services.tat_tracker import canonical_tat_status, tat_reporting_status
    selected_statuses = list(dict.fromkeys(
        canonical_tat_status(value) for value in selected_values(statuses)
    ))
    if selected_products:
        recipients = recipients.filter(task__case__product_key__in=selected_products)
    if selected_branches:
        recipients = recipients.filter(task__case__branch__in=selected_branches)
    grants = [] if user.is_superuser else list(AccessGrant.objects.filter(
        user=user, workflow='tat_tracker', active=True,
    ).select_related('user', 'group_configuration'))
    eligible = []
    total = 0
    unread_count = 0
    bounded_limit = max(1, min(limit, 100))
    bounded_offset = max(0, int(offset or 0))
    seen_case_ids = set()
    for recipient in recipients.order_by('task__created_at'):
        task = recipient.task
        workflow = getattr(task.group_configuration, 'workflow', None) or {}
        status = tat_reporting_status(task.case, workflow=workflow)
        if selected_statuses and status not in selected_statuses:
            continue
        if not user.is_superuser and not any(_grant_matches(
            grant,
            group=task.group_configuration,
            branch=task.case.branch,
            product_key=task.case.product_key,
            role=task.responsible_role,
        ) for grant in grants):
            continue
        if task.case_id in seen_case_ids:
            continue
        seen_case_ids.add(task.case_id)
        total += 1
        unread_count += int(recipient.inbox_status == TatActionTaskRecipient.INBOX_UNREAD)
        eligible.append((recipient, task))
    rows = []
    for recipient, task in eligible[bounded_offset:bounded_offset + bounded_limit]:
        case = task.case
        rows.append({
            'task_id': str(task.pk), 'case_id': task.case.case_id,
            'stage_key': task.stage_key, 'stage_label': task.stage_label,
            'role': task.responsible_role, 'kind': recipient.kind,
            'branch': case.branch,
            'product': case.product_label or case.product_key,
            'product_key': case.product_key,
            'client_name': case.client_name,
            'national_id': case.national_id,
            'primary_phone': case.primary_phone,
            'amount': str(case.amount or ''),
            'status': tat_reporting_status(
                case, workflow=getattr(task.group_configuration, 'workflow', None) or {},
            ),
            'current_stage': case.current_stage,
            'next_stage': task.stage_label,
            'workflow_revision': task.case_revision,
            'unread': recipient.inbox_status == TatActionTaskRecipient.INBOX_UNREAD,
            'delivery_state': recipient.delivery_state,
            'created_at': task.created_at.isoformat(),
            'updated_at': case.updated_at.isoformat(),
        })
    return {
        'items': rows,
        'unread_count': unread_count,
        'total': total,
        'pagination': {
            'offset': bounded_offset,
            'page_size': bounded_limit,
            'total': total,
            'has_more': bounded_offset + len(rows) < total,
        },
    }


@transaction.atomic
def mark_task_read(task: TatActionTask, user) -> None:
    recipient = TatActionTaskRecipient.objects.select_for_update().filter(
        task=task, user=user, routing_generation=task.routing_generation,
    ).first()
    if not recipient:
        return
    if recipient.inbox_status == TatActionTaskRecipient.INBOX_UNREAD:
        recipient.inbox_status = TatActionTaskRecipient.INBOX_READ
        recipient.read_at = timezone.now()
        recipient.save(update_fields=['inbox_status', 'read_at', 'updated_at'])


def task_access_allowed(task: TatActionTask, user) -> bool:
    if not user or not user.is_active:
        return False
    if user.is_superuser:
        return True
    if task.recipients.filter(
        user=user, routing_generation=task.routing_generation,
        inbox_status__in=[TatActionTaskRecipient.INBOX_UNREAD, TatActionTaskRecipient.INBOX_READ],
    ).exists():
        return user_can_receive_task(
            user, group=task.group_configuration, case=task.case,
            role=task.responsible_role,
        )
    return False


def connect_private_alerts(user, *, request_id: str = '') -> dict:
    request_id = str(request_id or '').strip()
    profile = getattr(user, 'staff_profile', None)
    telegram_id = str(getattr(profile, 'telegram_id', '') or '').strip()
    if not telegram_id:
        raise ValueError('Your staff profile is not linked to a Telegram account.')
    with transaction.atomic():
        connection, _ = TatPrivateAlertConnection.objects.select_for_update().get_or_create(user=user)
        if request_id and connection.last_connect_request_id == request_id:
            return connection_payload(user)
        connection.last_connect_request_id = request_id
        connection.save(update_fields=['last_connect_request_id', 'updated_at'])
    now = timezone.now()
    try:
        _telegram_request('sendMessage', {
            'chat_id': telegram_id,
            'text': (
                '✅ Task Alerts Connected\n\n'
                'You will receive your assigned TAT tasks and alerts in this chat.'
            ),
        })
    except Exception as exc:
        failure_code = type(exc).__name__[:80]
        with transaction.atomic():
            connection = TatPrivateAlertConnection.objects.select_for_update().get(user=user)
            if connection.status != TatPrivateAlertConnection.STATUS_DISCONNECTED:
                connection.status = TatPrivateAlertConnection.STATUS_TEMPORARY_FAILURE
                connection.last_failure_at = now
                connection.last_failure_code = failure_code
                connection.save(update_fields=[
                    'status', 'last_failure_at', 'last_failure_code', 'updated_at',
                ])
            _record_connection_event(
                connection, TatPrivateAlertConnectionEvent.EVENT_CONNECT_FAILED,
                source='miniapp', request_id=request_id,
                detail_code=failure_code, actor=user,
            )
        raise
    _reset_private_chat_menu(telegram_id)
    with transaction.atomic():
        connection = TatPrivateAlertConnection.objects.select_for_update().get(user=user)
        if (
            connection.status == TatPrivateAlertConnection.STATUS_DISCONNECTED
            and connection.disconnected_at
            and connection.disconnected_at >= now
        ):
            return connection_payload(user)
        connection.status = TatPrivateAlertConnection.STATUS_CONNECTED
        connection.connected_at = connection.connected_at or now
        connection.disconnected_at = None
        connection.last_success_at = now
        connection.last_failure_code = ''
        connection.save(update_fields=[
            'status', 'connected_at', 'disconnected_at', 'last_success_at',
            'last_failure_code', 'updated_at',
        ])
        _record_connection_event(
            connection, TatPrivateAlertConnectionEvent.EVENT_CONNECTED,
            source='miniapp', request_id=request_id, actor=user,
        )
    return connection_payload(user)


@transaction.atomic
def disconnect_private_alerts(user, *, request_id: str = '') -> dict:
    """Disable private delivery without affecting the durable in-app inbox."""
    connection, _ = TatPrivateAlertConnection.objects.select_for_update().get_or_create(user=user)
    request_id = str(request_id or '').strip()
    if request_id and connection.last_disconnect_request_id == request_id:
        return connection_payload(user)
    now = timezone.now()
    connection.status = TatPrivateAlertConnection.STATUS_DISCONNECTED
    connection.disconnected_at = now
    connection.last_disconnect_request_id = request_id
    connection.save(update_fields=[
        'status', 'disconnected_at', 'last_disconnect_request_id', 'updated_at',
    ])
    _record_connection_event(
        connection, TatPrivateAlertConnectionEvent.EVENT_DISCONNECTED,
        source='miniapp', request_id=request_id, actor=user,
    )
    return connection_payload(user)


def send_private_alert_test(user, *, request_id: str = '', actor=None) -> dict:
    """Send one explicit Admin test without creating or advancing a TAT task."""
    request_id = str(request_id or '').strip()
    with transaction.atomic():
        connection, _ = TatPrivateAlertConnection.objects.select_for_update().get_or_create(user=user)
        if request_id and connection.last_test_request_id == request_id:
            return connection_payload(user)
        if connection.status == TatPrivateAlertConnection.STATUS_DISCONNECTED:
            raise ValueError('This user disconnected private alerts and must reconnect from the Mini App.')
        connection.last_test_request_id = request_id
        connection.save(update_fields=['last_test_request_id', 'updated_at'])
    profile = getattr(user, 'staff_profile', None)
    telegram_id = str(getattr(profile, 'telegram_id', '') or '').strip()
    if not telegram_id:
        raise ValueError('This staff profile is not linked to a Telegram account.')
    now = timezone.now()
    try:
        _telegram_request('sendMessage', {
            'chat_id': telegram_id,
            'text': (
                '✅ Alert Test Successful\n\n'
                'Your private task alerts are working correctly.\n\n'
                'No real task or escalation was created.'
            ),
        })
    except Exception as exc:
        failure_code = type(exc).__name__[:80]
        with transaction.atomic():
            connection = TatPrivateAlertConnection.objects.select_for_update().get(user=user)
            if connection.status != TatPrivateAlertConnection.STATUS_DISCONNECTED:
                connection.status = TatPrivateAlertConnection.STATUS_TEMPORARY_FAILURE
                connection.last_failure_at = now
                connection.last_failure_code = failure_code
                connection.save(update_fields=[
                    'status', 'last_failure_at', 'last_failure_code', 'updated_at',
                ])
            _record_connection_event(
                connection, TatPrivateAlertConnectionEvent.EVENT_TEST_FAILED,
                source='admin_test', request_id=request_id,
                detail_code=failure_code, actor=actor,
            )
        raise
    with transaction.atomic():
        connection = TatPrivateAlertConnection.objects.select_for_update().get(user=user)
        if connection.status != TatPrivateAlertConnection.STATUS_DISCONNECTED:
            connection.status = TatPrivateAlertConnection.STATUS_CONNECTED
            connection.connected_at = connection.connected_at or now
            connection.last_success_at = now
            connection.last_failure_code = ''
            connection.save(update_fields=[
                'status', 'connected_at', 'last_success_at', 'last_failure_code', 'updated_at',
            ])
        _record_connection_event(
            connection, TatPrivateAlertConnectionEvent.EVENT_TEST_SUCCEEDED,
            source='admin_test', request_id=request_id, actor=actor,
        )
    return connection_payload(user)
