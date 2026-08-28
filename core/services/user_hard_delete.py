"""Superuser-only physical user deletion with preserved audit evidence."""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

import requests
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Exists, F, OuterRef, Q
from django.utils import timezone

from core.models import (
    AccessControlChangeRequest,
    AccessControlCheckerAssignment,
    AccessControlNotification,
    AccessControlPolicyState,
    DeletedUserIdentity,
    JawabuApprovalDelegation,
    StaffLifecycleChangePlan,
    TatActionTask,
    TatActionTaskRecipient,
    TatResponsibilityAssignment,
    TatResponsibilityBackup,
    TatResponsibilityEvent,
    UserHardDeletionBatch,
    WorkflowConfigurationChangeRequest,
)
from core.services.access_grant_governance import governed_access_grant_mutation
from core.services.compliance_audit import record_event


TOMBSTONE_USERNAME_PREFIX = '__deleted_user_'
_hard_delete_authority = ContextVar('user_hard_delete_authority', default=False)

# These rows contain only live delivery/session/personal state and may disappear
# with the account. Everything else using CASCADE is rejected or explicitly
# redirected below so a new relation cannot silently expand deletion scope.
DISPOSABLE_CASCADE_MODELS = {
    'core.AccessGrant',
    'core.CapabilityUsageDaily',
    'core.EmergencyAccessGrant',
    'core.MiniAppDiagnosticSession',
    'core.MiniAppDraft',
    'core.PortalCaseWorkspace',
    'core.PortalSavedView',
    'core.TatActionTaskLocator',
    'core.TatActionTaskRecipient',
    'core.TatPrivateAlertConnection',
    'core.TelegramStaffActivation',
    'core.UserMiniAppPreference',
    'core.UserProfile',
}
PRESERVED_CASCADE_MODELS = {'admin.LogEntry'}
RETAINED_UNCONSTRAINED_FIELDS = {
    ('core.ComplianceAuditEvent', 'actor'),
    ('core.ComplianceAuditEvent', 'authority_user'),
    ('core.UserHardDeletionBatch', 'actor'),
}


@dataclass(frozen=True)
class HardDeletePreview:
    targets: tuple[dict, ...]
    relationships: tuple[dict, ...]
    totals: dict
    fingerprint: str


@contextmanager
def governed_user_hard_delete():
    token = _hard_delete_authority.set(True)
    try:
        yield
    finally:
        _hard_delete_authority.reset(token)


def require_governed_user_hard_delete() -> None:
    if not _hard_delete_authority.get():
        raise PermissionDenied(
            'Physical user deletion is available only through the governed Superuser hard-delete service.'
        )


def _label(user) -> str:
    return str(user.get_full_name() or user.get_username() or user.pk).strip()


def _require_root(actor) -> None:
    if not actor or not actor.is_authenticated or not actor.is_active or not actor.is_superuser:
        raise PermissionDenied('Only an active Django Superuser may hard-delete user accounts.')


def _targets(users) -> list:
    ids = sorted({int(user.pk if hasattr(user, 'pk') else user) for user in users})
    return list(get_user_model().objects.filter(pk__in=ids).order_by('pk'))


def _relation_action(relation) -> str:
    field = relation.field
    label = relation.related_model._meta.label
    on_delete = getattr(field.remote_field.on_delete, '__name__', '')
    key = (label, field.name)
    if key in RETAINED_UNCONSTRAINED_FIELDS:
        if on_delete != 'DO_NOTHING' or getattr(field, 'db_constraint', True):
            raise ValidationError(f'{label}.{field.name} is not configured as an unconstrained historical reference.')
        return 'retain_original_id'
    if on_delete == 'PROTECT':
        return 'preserve_via_tombstone'
    if on_delete == 'SET_NULL' and field.null:
        return 'detach_reference'
    if on_delete == 'CASCADE' and label in DISPOSABLE_CASCADE_MODELS:
        return 'delete_personal_state'
    if on_delete == 'CASCADE' and label in PRESERVED_CASCADE_MODELS:
        return 'preserve_via_tombstone'
    raise ValidationError(
        f'User deletion has no reviewed relationship policy for {label}.{field.name} ({on_delete or "unknown"}).'
    )


def _relationship_rows(target_ids: list[int]) -> list[dict]:
    rows = []
    for relation in get_user_model()._meta.related_objects:
        action = _relation_action(relation)
        field = relation.field
        queryset = relation.related_model._base_manager.filter(**{f'{field.name}_id__in': target_ids})
        count = queryset.count()
        if count:
            rows.append({
                'model': relation.related_model._meta.label,
                'field': field.name,
                'action': action,
                'count': count,
            })
    return sorted(rows, key=lambda row: (row['action'], row['model'], row['field']))


def preview_user_hard_delete(*, actor, users) -> HardDeletePreview:
    _require_root(actor)
    targets = _targets(users)
    if not targets:
        raise ValidationError('Choose at least one existing user account.')
    if any(user.pk == actor.pk for user in targets):
        raise ValidationError('You cannot hard-delete the account currently authorising this request.')
    if any(user.username.startswith(TOMBSTONE_USERNAME_PREFIX) for user in targets):
        raise ValidationError('The deleted-user evidence tombstone cannot be deleted.')
    active_root_ids = set(get_user_model().objects.filter(is_active=True, is_superuser=True).values_list('pk', flat=True))
    remaining_roots = active_root_ids - {user.pk for user in targets}
    if not remaining_roots:
        raise ValidationError('This deletion would leave the system without an active Superuser.')

    target_rows = tuple({
        'id': user.pk,
        'username': user.get_username(),
        'display_name': _label(user),
        'is_active': user.is_active,
        'is_staff': user.is_staff,
        'is_superuser': user.is_superuser,
    } for user in targets)
    relationships = tuple(_relationship_rows([user.pk for user in targets]))
    totals = {
        'targets': len(targets),
        'active_superusers_remaining': len(remaining_roots),
        'references_retained': sum(row['count'] for row in relationships if row['action'].startswith('retain')),
        'historical_rows_preserved': sum(row['count'] for row in relationships if row['action'] == 'preserve_via_tombstone'),
        'references_detached': sum(row['count'] for row in relationships if row['action'] == 'detach_reference'),
        'personal_rows_deleted': sum(row['count'] for row in relationships if row['action'] == 'delete_personal_state'),
    }
    payload = {'targets': target_rows, 'relationships': relationships, 'totals': totals}
    fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return HardDeletePreview(target_rows, relationships, totals, fingerprint)


def _tombstone_user(*, original_user_id: int):
    User = get_user_model()
    username = f'{TOMBSTONE_USERNAME_PREFIX}{original_user_id}__'
    tombstone, created = User.objects.get_or_create(
        username=username,
        defaults={
            'first_name': 'Deleted', 'last_name': 'user evidence',
            'is_active': False, 'is_staff': False, 'is_superuser': False,
            'password': '!',
        },
    )
    if not created and (tombstone.is_active or tombstone.is_staff or tombstone.is_superuser):
        raise ValidationError('The deleted-user evidence tombstone is not safely disabled.')
    return tombstone


def _cancel_open_work(*, target_ids: list[int], actor, now) -> dict:
    counts = {}
    counts['cancelled_access_requests'] = AccessControlChangeRequest.objects.filter(
        Q(target_user_id__in=target_ids) | Q(requested_by_id__in=target_ids),
        status__in=[
            AccessControlChangeRequest.STATUS_DRAFT,
            AccessControlChangeRequest.STATUS_PENDING,
            AccessControlChangeRequest.STATUS_APPROVED,
        ],
    ).update(status=AccessControlChangeRequest.STATUS_CANCELLED, review_comment='Cancelled because a referenced user was hard-deleted.')
    counts['cancelled_configuration_requests'] = WorkflowConfigurationChangeRequest.objects.filter(
        Q(requested_by_id__in=target_ids) | Q(reviewed_by_id__in=target_ids),
        status=WorkflowConfigurationChangeRequest.STATUS_PENDING,
    ).update(status=WorkflowConfigurationChangeRequest.STATUS_CANCELLED, review_comment='Cancelled because a referenced user was hard-deleted.')
    counts['cancelled_lifecycle_plans'] = StaffLifecycleChangePlan.objects.filter(
        Q(target_user_id__in=target_ids) | Q(requested_by_id__in=target_ids) | Q(reviewed_by_id__in=target_ids),
        status__in=StaffLifecycleChangePlan.OPEN_STATUSES,
    ).update(status=StaffLifecycleChangePlan.STATUS_CANCELLED, error='Cancelled because a referenced user was hard-deleted.')

    assignments = list(TatResponsibilityAssignment.objects.select_for_update().filter(
        primary_user_id__in=target_ids, active=True,
    ).select_related('group_configuration'))
    for assignment in assignments:
        TatResponsibilityEvent.objects.create(
            assignment=assignment,
            assignment_id_snapshot=assignment.pk,
            action=TatResponsibilityEvent.ACTION_DELETED,
            actor=actor,
            reason='Primary owner hard-deleted by a Django Superuser; responsibility force-unassigned.',
            before_snapshot={
                'primary_user_id': assignment.primary_user_id,
                'active': True,
                'branch': assignment.branch,
                'product_key': assignment.product_key,
                'stage_key': assignment.stage_key,
                'role': assignment.role,
            },
            after_snapshot={'primary_user_id': None, 'active': False, 'effective_until': now.isoformat()},
        )
    assignment_ids = [assignment.pk for assignment in assignments]
    counts['responsibilities_unassigned'] = TatResponsibilityAssignment.objects.filter(pk__in=assignment_ids).update(
        active=False, effective_until=now,
    ) if assignment_ids else 0
    counts['backup_responsibilities_removed'] = TatResponsibilityBackup.objects.filter(
        user_id__in=target_ids, active=True,
    ).update(active=False)

    # PostgreSQL rejects SELECT FOR UPDATE when the outer query also uses
    # DISTINCT. Use a correlated recipient existence check so the task table is
    # locked directly without a duplicate-producing reverse join.
    target_recipient = TatActionTaskRecipient.objects.filter(
        task_id=OuterRef('pk'),
        user_id__in=target_ids,
    )
    pending_tasks = TatActionTask.objects.select_for_update().filter(
        status=TatActionTask.STATUS_PENDING,
    ).annotate(
        has_hard_deleted_recipient=Exists(target_recipient),
    )
    if assignment_ids:
        pending_tasks = pending_tasks.filter(
            Q(has_hard_deleted_recipient=True) | Q(assignment_id__in=assignment_ids),
        )
    else:
        pending_tasks = pending_tasks.filter(has_hard_deleted_recipient=True)
    task_rows = list(pending_tasks.order_by('pk'))
    for task in task_rows:
        snapshot = dict(task.recipient_snapshot or {})
        snapshot['hard_deleted_user_ids'] = sorted(
            {str(value) for value in snapshot.get('hard_deleted_user_ids', [])}
            | {str(value) for value in target_ids}
        )
        task.recipient_snapshot = snapshot
        if task.assignment_id in assignment_ids:
            task.assignment = None
        task.routing_generation = F('routing_generation') + 1
        task.save(update_fields=['recipient_snapshot', 'assignment', 'routing_generation', 'updated_at'])
    counts['open_tasks_unassigned'] = len(task_rows)

    counts['checker_assignments_revoked'] = AccessControlCheckerAssignment.objects.filter(
        user_id__in=target_ids, revoked_at__isnull=True,
    ).update(revoked_at=now, revoked_by=actor, revocation_reason='Checker account hard-deleted by a Django Superuser.')
    counts['delegations_revoked'] = JawabuApprovalDelegation.objects.filter(
        delegate_id__in=target_ids, revoked_at__isnull=True,
    ).update(revoked_at=now, revoked_by=actor, revocation_reason='Delegate account hard-deleted by a Django Superuser.')
    return counts


def _coverage_gaps() -> list[dict]:
    from core.models import GroupSheetConfiguration
    from core.services.tat_production import _group_scope_issues
    from core.services.tat_tracker import is_tat_tracker_workflow

    rows = []
    for group in GroupSheetConfiguration.objects.filter(enabled=True):
        if not is_tat_tracker_workflow(group):
            continue
        for issue in _group_scope_issues(group):
            if issue.code in {'tat-access-coverage', 'tat-responsibility-missing', 'tat-primary-access'}:
                rows.append({'severity': issue.severity, 'code': issue.code, 'message': issue.message})
    return rows


def _delete_authenticated_sessions(*, target_ids: list[int], now) -> int:
    from django.contrib.sessions.models import Session

    wanted = {str(value) for value in target_ids}
    session_keys = []
    for session in Session.objects.filter(expire_date__gt=now).iterator():
        try:
            payload = session.get_decoded()
        except Exception:
            continue
        if str(payload.get('_auth_user_id') or '') in wanted:
            session_keys.append(session.session_key)
    if not session_keys:
        return 0
    deleted, _details = Session.objects.filter(session_key__in=session_keys).delete()
    return deleted


def _notify_actor_telegram(*, actor_id: int, batch_id) -> None:
    User = get_user_model()
    actor = User.objects.filter(pk=actor_id, is_active=True).select_related('staff_profile').first()
    if not actor:
        return
    profile = getattr(actor, 'staff_profile', None)
    telegram_id = str(getattr(profile, 'telegram_id', '') or '')
    token = str(getattr(settings, 'TELEGRAM_BOT_TOKEN', '') or '')
    if not telegram_id or not token:
        return
    notification = AccessControlNotification.objects.create(
        request=None, recipient=actor, channel=AccessControlNotification.CHANNEL_TELEGRAM,
        event=f'user_hard_delete:{batch_id}', status='queued',
    )
    try:
        response = requests.post(
            f'https://api.telegram.org/bot{token}/sendMessage',
            json={'chat_id': telegram_id, 'text': f'JBL Admin: user hard-deletion batch {batch_id} completed.'},
            timeout=10,
        )
        response.raise_for_status()
        notification.status = 'delivered'
        notification.delivered_at = timezone.now()
    except requests.RequestException as exc:
        notification.status = 'failed'
        notification.error = str(exc)[:500]
    notification.save(update_fields=['status', 'error', 'delivered_at'])


def execute_user_hard_delete(
    *, actor, users, reason_category: str, reason_note: str = '',
    request_id: str, expected_fingerprint: str,
) -> UserHardDeletionBatch:
    """Physically delete accounts after revalidating an unchanged impact preview."""
    _require_root(actor)
    request_id = str(request_id or '').strip()
    if not request_id:
        raise ValidationError('A stable hard-deletion request ID is required.')
    if reason_category not in dict(UserHardDeletionBatch.REASON_CHOICES):
        raise ValidationError('Choose a valid hard-deletion reason category.')
    existing = UserHardDeletionBatch.objects.filter(request_id=request_id).first()
    if existing:
        if existing.preview_fingerprint != expected_fingerprint:
            raise ValidationError('This request ID was already used for a different deletion preview.')
        return existing

    target_ids = sorted({int(user.pk if hasattr(user, 'pk') else user) for user in users})
    with (
        transaction.atomic(),
        governed_access_grant_mutation('Superuser hard-delete account revocation'),
        governed_user_hard_delete(),
    ):
        User = get_user_model()
        locked_roots = list(User.objects.select_for_update().filter(
            is_active=True, is_superuser=True,
        ).order_by('pk'))
        locked_actor = next((user for user in locked_roots if user.pk == actor.pk), None)
        if locked_actor is None:
            raise PermissionDenied('The authorising Superuser account is no longer active.')
        locked_targets = list(User.objects.select_for_update().filter(pk__in=target_ids).order_by('pk'))
        preview = preview_user_hard_delete(actor=locked_actor, users=locked_targets)
        if preview.fingerprint != expected_fingerprint:
            raise ValidationError('The account impact changed. Review the refreshed deletion preview before continuing.')

        now = timezone.now()
        manifests = {
            user.pk: _relationship_rows([user.pk])
            for user in locked_targets
        }
        identity_snapshots = [{
            'original_user_id': user.pk,
            'username': user.get_username(),
            'display_name': _label(user),
            'was_active': user.is_active,
            'was_staff': user.is_staff,
            'was_superuser': user.is_superuser,
            'relationship_manifest': manifests[user.pk],
        } for user in locked_targets]
        result_counts = _cancel_open_work(target_ids=target_ids, actor=locked_actor, now=now)
        result_counts['authenticated_sessions_deleted'] = _delete_authenticated_sessions(
            target_ids=target_ids, now=now,
        )
        for target in locked_targets:
            tombstone = _tombstone_user(original_user_id=target.pk)
            for relation in User._meta.related_objects:
                action = _relation_action(relation)
                if action != 'preserve_via_tombstone':
                    continue
                field = relation.field
                key = f'preserved:{relation.related_model._meta.label}.{field.name}'
                changed = (
                    relation.related_model._base_manager.filter(**{f'{field.name}_id': target.pk})
                    .update(**{f'{field.name}_id': tombstone.pk})
                )
                result_counts[key] = result_counts.get(key, 0) + changed

        deleted_total = 0
        for target in locked_targets:
            deleted_count, _details = target.delete()
            deleted_total += deleted_count
        result_counts['database_rows_deleted'] = deleted_total

        AccessControlPolicyState.objects.select_for_update().filter(singleton=1).update(
            version=F('version') + 1,
            updated_at=now,
        )
        coverage_gaps = _coverage_gaps()
        batch = UserHardDeletionBatch.objects.create(
            request_id=request_id,
            actor=locked_actor,
            actor_label=_label(locked_actor),
            reason_category=reason_category,
            reason_note=str(reason_note or '').strip(),
            target_count=len(locked_targets),
            preview_fingerprint=preview.fingerprint,
            result_counts=result_counts,
            coverage_gaps=coverage_gaps,
        )
        DeletedUserIdentity.objects.bulk_create([
            DeletedUserIdentity(
                batch=batch,
                **snapshot,
            )
            for snapshot in identity_snapshots
        ])
        record_event(
            workflow='access_control',
            action='user.hard_deleted',
            category='identity',
            subject_type='user_hard_deletion_batch',
            subject_id=str(batch.pk),
            actor=locked_actor,
            request_id=request_id,
            source_model='UserHardDeletionBatch',
            source_event_id=str(batch.pk),
            deduplication_key=f'user-hard-delete:{request_id}',
            before_values={'users': list(preview.targets)},
            after_values={'deleted': True, 'result_counts': result_counts, 'coverage_gap_count': len(coverage_gaps)},
            metadata={'reason_category': reason_category, 'reason_note': str(reason_note or '').strip()},
            sensitive=True,
        )
        AccessControlNotification.objects.create(
            request=None, recipient=locked_actor, channel=AccessControlNotification.CHANNEL_ADMIN,
            event=f'user_hard_delete:{batch.pk}', status='delivered', delivered_at=now,
        )
        transaction.on_commit(lambda: _notify_actor_telegram(actor_id=locked_actor.pk, batch_id=batch.pk))
        return batch
