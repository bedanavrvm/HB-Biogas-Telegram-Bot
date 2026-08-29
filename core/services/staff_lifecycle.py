"""Atomic direct-Superuser and optionally checker-reviewed staff lifecycle."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from core.models import (
    AccessControlPolicySnapshot,
    AccessControlPolicyState,
    AccessGrant,
    JawabuApprovalDelegation,
    StaffLifecycleChangePlan,
    TatActionTask,
    TatResponsibilityAssignment,
    TatResponsibilityBackup,
    TelegramStaffActivation,
    UserProfile,
)
from core.services.access_control import (
    _policy_snapshot, approver_users, can_approve_access_change, notify_approvers,
)
from core.services.access_grant_governance import governed_access_grant_mutation
from core.services.access_policies import validate_access_scope


ACTIVATION_TTL_MINUTES = 15
ACTIVATION_MAX_ATTEMPTS = 5


def _grant_snapshot(grant) -> dict:
    return {
        'id': str(grant.pk),
        'workflow': grant.workflow,
        'role': grant.role,
        'branch': grant.branch,
        'product': grant.product,
        'group_configuration_id': grant.group_configuration_id,
        'active': grant.active,
        'updated_at': grant.updated_at.isoformat(),
    }


def _assignment_snapshot(assignment) -> dict:
    return {
        'id': str(assignment.pk),
        'primary_user_id': assignment.primary_user_id,
        'backups': [
            {
                'id': backup.pk,
                'user_id': backup.user_id,
                'rank': backup.rank,
                'threshold_percent': backup.threshold_percent,
                'active': backup.active,
            }
            for backup in assignment.backups.order_by('rank', 'pk')
        ],
        'updated_at': assignment.updated_at.isoformat(),
        'active': assignment.active,
    }


def lifecycle_snapshot(user) -> dict:
    profile = getattr(user, 'staff_profile', None)
    grants = AccessGrant.objects.filter(user=user).order_by('workflow', 'role', 'branch', 'product', 'pk')
    assignments = TatResponsibilityAssignment.objects.filter(
        Q(primary_user=user) | Q(backups__user=user), active=True,
    ).distinct().order_by('pk')
    return {
        'user': {
            'id': user.pk,
            'username': user.username,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'email': user.email,
            'is_active': user.is_active,
            'is_staff': user.is_staff,
            'is_superuser': user.is_superuser,
        },
        'telegram': {
            'username': getattr(profile, 'telegram_username', ''),
            'bound': bool(getattr(profile, 'telegram_id', '')),
        },
        'grants': [_grant_snapshot(row) for row in grants],
        'assignments': [_assignment_snapshot(row) for row in assignments],
    }


def _normalize_grants(rows) -> list[dict]:
    normalized = []
    seen = set()
    for raw in rows or []:
        workflow = str(raw.get('workflow') or '').strip()
        role = validate_access_scope(
            workflow=workflow,
            role=str(raw.get('role') or '').strip(),
            branch=str(raw.get('branch') or '').strip(),
            product=str(raw.get('product') or '').strip(),
            group_configuration=raw.get('group_configuration'),
        )
        group = raw.get('group_configuration')
        group_id = getattr(group, 'pk', None) or raw.get('group_configuration_id') or None
        key = (workflow, role, str(raw.get('branch') or '').strip(), str(raw.get('product') or '').strip(), group_id)
        if key in seen:
            continue
        seen.add(key)
        normalized.append({
            'workflow': key[0], 'role': key[1], 'branch': key[2], 'product': key[3],
            'group_configuration_id': group_id, 'active': True,
        })
    return normalized


def _request_fingerprint(*, action, target_user_id, reason, desired_grants,
                         replacement_user_id, leave_from, leave_until,
                         delegation_gates, identity, new_user_password='') -> str:
    password_proof = ''
    if new_user_password:
        password_proof = hmac.new(
            settings.SECRET_KEY.encode(), str(new_user_password).encode(), hashlib.sha256,
        ).hexdigest()
    payload = {
        'action': str(action or ''),
        'target_user_id': target_user_id,
        'reason': str(reason or '').strip(),
        'desired_grants': desired_grants,
        'replacement_user_id': replacement_user_id,
        'leave_from': leave_from.isoformat() if leave_from else '',
        'leave_until': leave_until.isoformat() if leave_until else '',
        'delegation_gates': sorted(str(value) for value in (delegation_gates or [])),
        'identity': identity or {},
        'new_user_password_proof': password_proof,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str).encode(),
    ).hexdigest()


def _existing_request(*, requester, request_key, fingerprint):
    if not request_key:
        return None
    existing = StaffLifecycleChangePlan.objects.filter(
        requested_by=requester, request_key=request_key,
    ).first()
    if existing and existing.request_fingerprint and existing.request_fingerprint != fingerprint:
        raise ValidationError(
            'This lifecycle request key was already used for different details. Reload and try again.'
        )
    return existing


def _create_onboarding_shell(*, identity, new_user_password):
    User = get_user_model()
    identity = dict(identity or {})
    login_method = str(identity.get('login_method') or '')
    telegram_username = str(identity.get('telegram_username') or '').strip().lstrip('@').lower()
    if login_method == 'telegram':
        safe_username = re.sub(r'[^a-z0-9_]', '_', telegram_username)[:100]
        username = f'tg_{safe_username}'
        if not safe_username:
            raise ValidationError('Enter the enrolled Telegram username.')
    elif login_method == 'django':
        username = str(identity.get('django_username') or '').strip()
        if not username:
            raise ValidationError('Enter a Django username.')
        if not new_user_password:
            raise ValidationError('Enter an initial password for the Django Admin account.')
    else:
        raise ValidationError('Choose how this staff member signs in.')
    if User.objects.filter(username__iexact=username).exists():
        raise ValidationError('That Django username already exists.')
    if telegram_username and UserProfile.objects.filter(
        telegram_username__iexact=telegram_username,
    ).exists():
        raise ValidationError('That Telegram username is already enrolled.')
    name_parts = str(identity.get('display_name') or '').strip().split(None, 1)
    if not name_parts:
        raise ValidationError('Enter the staff member\'s full name.')
    user = User(
        username=username,
        first_name=name_parts[0],
        last_name=name_parts[1] if len(name_parts) > 1 else '',
        email=str(identity.get('email') or '').strip(),
        is_active=False,
        is_staff=False,
    )
    if login_method == 'django':
        user.set_password(new_user_password)
    else:
        user.set_unusable_password()
    user.save()
    UserProfile.objects.create(user=user, telegram_username=telegram_username)
    return user


def lifecycle_submission_preview(*, action, reason, desired_grants=None,
                                 target_user=None, replacement_user=None,
                                 leave_from=None, leave_until=None,
                                 delegation_gates=None, identity=None,
                                 new_user_password='') -> dict:
    normalized_grants = _normalize_grants(desired_grants)
    normalized_identity = dict(identity or {})
    fingerprint = _request_fingerprint(
        action=action,
        target_user_id=getattr(target_user, 'pk', None),
        reason=reason,
        desired_grants=normalized_grants,
        replacement_user_id=getattr(replacement_user, 'pk', None),
        leave_from=leave_from,
        leave_until=leave_until,
        delegation_gates=delegation_gates,
        identity=normalized_identity,
        new_user_password=new_user_password,
    )
    return {
        'fingerprint': fingerprint,
        'action': dict(StaffLifecycleChangePlan.ACTION_CHOICES).get(action, action),
        'target': str(target_user) if target_user else normalized_identity.get('display_name', ''),
        'identity': normalized_identity,
        'grants': normalized_grants,
        'replacement': str(replacement_user) if replacement_user else '',
        'leave_from': leave_from,
        'leave_until': leave_until,
        'delegation_gates': list(delegation_gates or []),
        'reason': str(reason or '').strip(),
        'impact': lifecycle_impact(target_user) if target_user else {
            'active_grants': 0,
            'responsibilities': 0,
            'open_tasks': 0,
            'active_delegations': 0,
            'covering_for_others': 0,
        },
    }


def lifecycle_impact(user) -> dict:
    assignment_ids = TatResponsibilityAssignment.objects.filter(
        Q(primary_user=user) | Q(backups__user=user), active=True,
    ).values_list('pk', flat=True)
    return {
        'active_grants': AccessGrant.objects.filter(user=user, active=True).count(),
        'responsibilities': len(set(assignment_ids)),
        'open_tasks': TatActionTask.objects.filter(
            status=TatActionTask.STATUS_PENDING, recipients__user=user,
        ).distinct().count(),
        'active_delegations': JawabuApprovalDelegation.objects.filter(
            Q(delegate=user) | Q(authorized_by=user), revoked_at__isnull=True,
            expires_at__gt=timezone.now(),
        ).count(),
        'covering_for_others': StaffLifecycleChangePlan.objects.filter(
            action=StaffLifecycleChangePlan.ACTION_LEAVE,
            status=StaffLifecycleChangePlan.STATUS_APPLIED,
            proposed_snapshot__replacement_user_id=user.pk,
        ).count(),
    }


def create_lifecycle_plan(*, requester, target_user, action: str, reason: str,
                          desired_grants=None, replacement_user=None,
                          leave_from=None, leave_until=None, delegation_gates=None,
                          request_key='', identity=None,
                          decision_mode=StaffLifecycleChangePlan.DECISION_CHECKER,
                          request_fingerprint='') -> StaffLifecycleChangePlan:
    if not requester or not requester.is_active or not requester.is_superuser:
        raise PermissionDenied('Only an active Django Superuser may propose staff lifecycle changes.')
    if not target_user or not target_user.pk:
        raise ValidationError('Choose the staff account this plan changes.')
    if target_user.is_superuser:
        raise ValidationError('Django Superuser accounts use the separate god-mode lifecycle procedure.')
    if (
        decision_mode == StaffLifecycleChangePlan.DECISION_CHECKER
        and not approver_users().exclude(pk=requester.pk).exists()
    ):
        raise ValidationError('Appoint an independent Access Control Checker before submitting lifecycle changes.')
    if decision_mode not in dict(StaffLifecycleChangePlan.DECISION_MODE_CHOICES):
        raise ValidationError('Choose a supported lifecycle decision mode.')
    if action not in dict(StaffLifecycleChangePlan.ACTION_CHOICES):
        raise ValidationError('Choose a supported staff lifecycle action.')
    if action != StaffLifecycleChangePlan.ACTION_ONBOARD and not target_user.is_active:
        raise ValidationError('Choose an active staff account for this lifecycle action.')
    if action == StaffLifecycleChangePlan.ACTION_ONBOARD and target_user.is_active:
        raise ValidationError('An onboarding account shell must remain inactive until its lifecycle decision is applied.')
    reason = str(reason or '').strip()
    if len(reason) < 10:
        raise ValidationError('Explain the lifecycle change in at least 10 characters.')
    key = str(request_key or '').strip()[:128]
    if key:
        existing = _existing_request(
            requester=requester, request_key=key, fingerprint=request_fingerprint,
        )
        if existing:
            return existing
    open_plan = StaffLifecycleChangePlan.objects.filter(
        target_user=target_user, status__in=StaffLifecycleChangePlan.OPEN_STATUSES,
    ).first()
    if open_plan:
        raise ValidationError(f'This staff member already has an open lifecycle plan: {open_plan.pk}.')

    before = lifecycle_snapshot(target_user)
    proposed = {}
    if identity:
        proposed['identity'] = dict(identity)
    if action in {
        StaffLifecycleChangePlan.ACTION_ONBOARD,
        StaffLifecycleChangePlan.ACTION_ACCESS,
        StaffLifecycleChangePlan.ACTION_TRANSFER,
    }:
        proposed['grants'] = _normalize_grants(desired_grants)
        if not proposed['grants']:
            raise ValidationError('Choose at least one workflow role and scope.')
    if action in {
        StaffLifecycleChangePlan.ACTION_TRANSFER,
        StaffLifecycleChangePlan.ACTION_LEAVE,
        StaffLifecycleChangePlan.ACTION_OFFBOARD,
    }:
        affected = TatResponsibilityAssignment.objects.filter(
            Q(primary_user=target_user) | Q(backups__user=target_user), active=True,
        ).distinct()
        if affected.exists() and (not replacement_user or not replacement_user.is_active):
            raise ValidationError('Choose an active replacement for the affected TAT responsibilities.')
        if replacement_user and replacement_user == target_user:
            raise ValidationError('The replacement must be a different active staff member.')
        proposed['replacement_user_id'] = getattr(replacement_user, 'pk', None)
    if action == StaffLifecycleChangePlan.ACTION_LEAVE:
        now = timezone.now()
        start = leave_from or now
        if start < now:
            start = now
        if not leave_until or leave_until <= start:
            raise ValidationError('Temporary leave requires a future return time.')
        if leave_until > start + timedelta(days=14):
            raise ValidationError('One temporary leave plan may cover at most 14 days.')
        proposed['leave_from'] = start.isoformat()
        proposed['leave_until'] = leave_until.isoformat()
        proposed['delegation_gates'] = list(delegation_gates or [])
        if proposed['delegation_gates'] and replacement_user is None:
            raise ValidationError('Choose the staff member receiving temporary approval delegations.')
    if action == StaffLifecycleChangePlan.ACTION_RETURN and not StaffLifecycleChangePlan.objects.filter(
        target_user=target_user,
        action=StaffLifecycleChangePlan.ACTION_LEAVE,
        status=StaffLifecycleChangePlan.STATUS_APPLIED,
    ).exists():
        raise ValidationError('No applied leave arrangement is available to end early.')
    if action == StaffLifecycleChangePlan.ACTION_IDENTITY_RESET:
        profile = getattr(target_user, 'staff_profile', None)
        if profile is None or not profile.telegram_id:
            raise ValidationError('This staff account does not have a bound Telegram identity to reset.')
    if action in {StaffLifecycleChangePlan.ACTION_LEAVE, StaffLifecycleChangePlan.ACTION_OFFBOARD}:
        covering = StaffLifecycleChangePlan.objects.filter(
            action=StaffLifecycleChangePlan.ACTION_LEAVE,
            status=StaffLifecycleChangePlan.STATUS_APPLIED,
            proposed_snapshot__replacement_user_id=target_user.pk,
        ).exists()
        if covering:
            raise ValidationError(
                'This staff member currently covers another leave arrangement. Resolve that coverage first.'
            )

    state = AccessControlPolicyState.current()
    try:
        with transaction.atomic():
            plan = StaffLifecycleChangePlan.objects.create(
                action=action, target_user=target_user,
                status=StaffLifecycleChangePlan.STATUS_PENDING,
                before_snapshot=before, proposed_snapshot=proposed,
                impact=lifecycle_impact(target_user), expected_policy_version=state.version,
                reason=reason, request_key=key, requested_by=requester,
                request_fingerprint=request_fingerprint,
                decision_mode=decision_mode,
                effective_at=start if action == StaffLifecycleChangePlan.ACTION_LEAVE else None,
            )
    except IntegrityError:
        if key:
            return StaffLifecycleChangePlan.objects.get(requested_by=requester, request_key=key)
        raise
    _record_plan(plan, 'staff_lifecycle.plan.submitted')
    if decision_mode == StaffLifecycleChangePlan.DECISION_CHECKER:
        base_url = str(getattr(settings, 'APP_BASE_URL', '') or '').rstrip('/')
        review_url = f'{base_url}/admin/auth/user/staff-lifecycle/{plan.pk}/' if base_url else ''
        transaction.on_commit(lambda: notify_approvers(
            None, 'staff_lifecycle_pending',
            extra=(
                f'Staff lifecycle plan {plan.pk} awaits independent review: '
                f'{plan.get_action_display()} for {target_user}.'
                + (f' Review: {review_url}' if review_url else '')
            ),
        ))
    return plan


def _snapshot_matches(plan, user) -> bool:
    current = lifecycle_snapshot(user)
    before = plan.before_snapshot or {}
    return current.get('user') == before.get('user') and current.get('grants') == before.get('grants') and current.get('assignments') == before.get('assignments')


def _apply_desired_grants(plan, user) -> None:
    desired = plan.proposed_snapshot.get('grants') or []
    desired_keys = {
        (row['workflow'], row['role'], row.get('branch', ''), row.get('product', ''), row.get('group_configuration_id'))
        for row in desired
    }
    with governed_access_grant_mutation(f'staff lifecycle plan {plan.pk}'):
        current = list(AccessGrant.objects.select_for_update().filter(user=user))
        for grant in current:
            key = (grant.workflow, grant.role, grant.branch, grant.product, grant.group_configuration_id)
            should_be_active = key in desired_keys
            if grant.active != should_be_active:
                grant.active = should_be_active
                grant.source = 'staff_lifecycle_plan'
                grant.save(update_fields=['active', 'source', 'updated_at'])
        current_keys = {
            (row.workflow, row.role, row.branch, row.product, row.group_configuration_id)
            for row in current
        }
        for row in desired:
            key = (row['workflow'], row['role'], row.get('branch', ''), row.get('product', ''), row.get('group_configuration_id'))
            if key in current_keys:
                continue
            grant = AccessGrant(
                user=user, workflow=key[0], role=key[1], branch=key[2], product=key[3],
                group_configuration_id=key[4], active=True, source='staff_lifecycle_plan',
            )
            grant.full_clean()
            grant.save()


def _replace_responsibilities(plan, user, replacement) -> list[str]:
    from core.services.tat_notifications import reroute_pending_task, user_can_receive_scope

    changed = []
    assignments = list(TatResponsibilityAssignment.objects.select_for_update().filter(
        Q(primary_user=user) | Q(backups__user=user), active=True,
    ).distinct())
    for assignment in assignments:
        if not user_can_receive_scope(
            replacement, group=assignment.group_configuration, branch=assignment.branch,
            product_key=assignment.product_key, role=assignment.role,
        ):
            raise ValidationError(
                f'{replacement} lacks matching TAT access for {assignment.branch}/{assignment.role}.'
            )
        if assignment.primary_user_id == user.pk:
            assignment.primary_user = replacement
            assignment.save(update_fields=['primary_user', 'updated_at'])
        for backup in assignment.backups.select_for_update().filter(user=user):
            existing = assignment.backups.filter(user=replacement).exclude(pk=backup.pk).first()
            if existing or assignment.primary_user_id == replacement.pk:
                backup.delete()
            else:
                backup.user = replacement
                backup.save(update_fields=['user'])
        changed.append(str(assignment.pk))
        for task in assignment.tasks.select_for_update().filter(status=TatActionTask.STATUS_PENDING):
            reroute_pending_task(
                task=task, actor=plan.requested_by, reason=plan.reason,
                request_id=f'lifecycle-{plan.pk}-{task.pk}',
            )
    return changed


def _create_leave_delegations(plan, user, replacement) -> list[str]:
    from core.services.jawabu_approvals import create_delegation
    from core.services.telegram_identity import user_access

    expiry = timezone.datetime.fromisoformat(plan.proposed_snapshot['leave_until'])
    if timezone.is_naive(expiry):
        expiry = timezone.make_aware(expiry)
    access = user_access(user, 'jawabu_portal')
    created = []
    for gate in plan.proposed_snapshot.get('delegation_gates') or []:
        delegation = create_delegation(
            delegate=replacement, gate=gate, authorized_by=user,
            authorization_access=access, reason=plan.reason, expires_at=expiry,
        )
        created.append(str(delegation.pk))
    return created


def _apply_early_return(plan, user) -> tuple[list[str], list[str]]:
    leave = StaffLifecycleChangePlan.objects.select_for_update().filter(
        target_user=user, action=StaffLifecycleChangePlan.ACTION_LEAVE,
        status=StaffLifecycleChangePlan.STATUS_APPLIED,
    ).order_by('-applied_at').first()
    if leave is None:
        raise ValidationError('No applied leave arrangement is available to end early.')
    replacement_id = leave.proposed_snapshot.get('replacement_user_id')
    restored = []
    before_assignments = {
        str(row['id']): row for row in (leave.before_snapshot or {}).get('assignments', [])
        if row.get('primary_user_id') == user.pk
        or any(backup.get('user_id') == user.pk for backup in row.get('backups', []))
    }
    for assignment_id, before in before_assignments.items():
        assignment = TatResponsibilityAssignment.objects.select_for_update().filter(pk=assignment_id).first()
        if not assignment:
            raise ValidationError(
                'A leave responsibility no longer exists. Resolve it before return.'
            )
        if before.get('primary_user_id') == user.pk:
            if assignment.primary_user_id != replacement_id:
                raise ValidationError(
                    'A primary leave responsibility changed after the leave plan was applied. '
                    'Resolve it before return.'
                )
            assignment.primary_user = user
            assignment.save(update_fields=['primary_user', 'updated_at'])
        for backup_before in before.get('backups', []):
            if backup_before.get('user_id') != user.pk:
                continue
            backup = TatResponsibilityBackup.objects.select_for_update().filter(
                pk=backup_before.get('id'), assignment=assignment,
            ).first()
            if backup:
                if (
                    backup.user_id != replacement_id
                    or backup.rank != backup_before.get('rank')
                    or backup.threshold_percent != backup_before.get('threshold_percent')
                    or backup.active != backup_before.get('active')
                ):
                    raise ValidationError(
                        'A backup leave responsibility changed after the leave plan was applied. '
                        'Resolve it before return.'
                    )
                backup.user = user
                backup.save(update_fields=['user'])
                continue
            if assignment.backups.filter(
                Q(user=user) | Q(rank=backup_before.get('rank')),
            ).exists():
                raise ValidationError(
                    'A backup position was reused after the leave plan was applied. '
                    'Resolve it before return.'
                )
            TatResponsibilityBackup.objects.create(
                assignment=assignment,
                user=user,
                rank=backup_before.get('rank'),
                threshold_percent=backup_before.get('threshold_percent'),
                active=backup_before.get('active', True),
            )
        restored.append(assignment_id)
    now = timezone.now()
    delegation_ids = (leave.impact or {}).get('created_delegation_ids') or []
    revoked = []
    for delegation in JawabuApprovalDelegation.objects.select_for_update().filter(
        pk__in=delegation_ids, revoked_at__isnull=True,
    ):
        delegation.revoked_at = now
        delegation.revoked_by = plan.reviewed_by
        delegation.revocation_reason = plan.reason
        delegation.save(update_fields=['revoked_at', 'revoked_by', 'revocation_reason'])
        revoked.append(str(delegation.pk))
    return restored, revoked


def _apply_plan(plan, user) -> None:
    action = plan.action
    if action in {plan.ACTION_ONBOARD, plan.ACTION_ACCESS, plan.ACTION_TRANSFER}:
        _apply_desired_grants(plan, user)
    replacement_id = plan.proposed_snapshot.get('replacement_user_id')
    replacement = get_user_model().objects.select_for_update().filter(pk=replacement_id).first() if replacement_id else None
    changed_assignments = []
    if action in {plan.ACTION_TRANSFER, plan.ACTION_LEAVE, plan.ACTION_OFFBOARD} and replacement:
        changed_assignments = _replace_responsibilities(plan, user, replacement)
    created_delegations = []
    revoked_delegations = []
    if action == plan.ACTION_LEAVE and replacement:
        created_delegations = _create_leave_delegations(plan, user, replacement)
    elif action == plan.ACTION_RETURN:
        changed_assignments, revoked_delegations = _apply_early_return(plan, user)
    if action == plan.ACTION_ONBOARD:
        user.is_active = True
        identity = plan.proposed_snapshot.get('identity') or {}
        user.is_staff = bool(identity.get('django_admin_login'))
        user.save(update_fields=['is_active', 'is_staff'])
        if identity.get('login_method') == 'telegram':
            profile = user.staff_profile
            profile.telegram_metadata = {
                **(profile.telegram_metadata or {}),
                'activation_required': True,
                'onboarding_plan_id': str(plan.pk),
            }
            profile.save(update_fields=['telegram_metadata', 'updated_at'])
    elif action == plan.ACTION_OFFBOARD:
        user._access_retirement_actor = plan.reviewed_by
        user.is_active = False
        user.save(update_fields=['is_active'])
    elif action == plan.ACTION_IDENTITY_RESET:
        profile = user.staff_profile
        profile.telegram_id = ''
        profile.telegram_metadata = {
            **(profile.telegram_metadata or {}),
            'identity_reset_plan_id': str(plan.pk),
            'activation_required': True,
        }
        profile.save(update_fields=['telegram_id', 'telegram_metadata', 'updated_at'])
        TelegramStaffActivation.objects.filter(
            user=user, consumed_at__isnull=True, invalidated_at__isnull=True,
        ).update(invalidated_at=timezone.now())
    plan.impact = {
        **(plan.impact or {}),
        'changed_assignment_ids': changed_assignments,
        'created_delegation_ids': created_delegations,
        'revoked_delegation_ids': revoked_delegations,
    }


def _finalize_lifecycle_plan(*, plan, actor, state, review_comment=''):
    if state.version != plan.expected_policy_version or not _snapshot_matches(plan, plan.target_user):
        plan.status = plan.STATUS_STALE
        plan.reviewed_by = actor
        plan.reviewed_at = timezone.now()
        plan.review_comment = 'Effective access or routing changed after this plan was submitted.'
        plan.save(update_fields=[
            'status', 'reviewed_by', 'reviewed_at', 'review_comment', 'decision_mode',
        ])
        _record_plan(plan, 'staff_lifecycle.plan.stale')
        return plan
    plan.reviewed_by = actor
    plan.reviewed_at = timezone.now()
    plan.review_comment = str(review_comment or '').strip()
    if plan.effective_at and plan.effective_at > timezone.now():
        plan.status = plan.STATUS_SCHEDULED
        plan.save(update_fields=[
            'reviewed_by', 'reviewed_at', 'review_comment', 'status', 'decision_mode',
        ])
        _record_plan(plan, 'staff_lifecycle.plan.scheduled')
        return plan
    _apply_plan(plan, plan.target_user)
    state.version += 1
    state.save(update_fields=['version', 'updated_at'])
    snapshot = _policy_snapshot()
    snapshot['staff_lifecycle_plan'] = {
        'id': str(plan.pk),
        'target_user_id': plan.target_user_id,
        'action': plan.action,
        'decision_mode': plan.decision_mode,
        'decision_actor_id': actor.pk,
    }
    AccessControlPolicySnapshot.objects.create(version=state.version, state=snapshot)
    plan.status = plan.STATUS_APPLIED
    plan.applied_at = timezone.now()
    plan.save(update_fields=[
        'reviewed_by', 'reviewed_at', 'review_comment', 'status', 'applied_at',
        'impact', 'decision_mode',
    ])
    _record_plan(plan, 'staff_lifecycle.plan.applied')
    return plan


@transaction.atomic
def submit_lifecycle_change(*, requester, action: str, reason: str,
                            desired_grants=None, target_user=None,
                            replacement_user=None, leave_from=None, leave_until=None,
                            delegation_gates=None, request_key='', identity=None,
                            new_user_password='', current_password='',
                            decision_mode=StaffLifecycleChangePlan.DECISION_SUPERUSER):
    """Create and either apply or queue one idempotent lifecycle change."""
    if not requester or not requester.is_active or not requester.is_superuser:
        raise PermissionDenied('Only an active Django Superuser may submit staff lifecycle changes.')
    if decision_mode == StaffLifecycleChangePlan.DECISION_SUPERUSER:
        if not current_password or not requester.check_password(current_password):
            raise ValidationError('Your current Django Admin password is incorrect.')
    elif decision_mode != StaffLifecycleChangePlan.DECISION_CHECKER:
        raise ValidationError('Choose a supported lifecycle decision mode.')

    normalized_grants = _normalize_grants(desired_grants)
    normalized_identity = dict(identity or {})
    key = str(request_key or '').strip()[:128]
    if not key:
        raise ValidationError('Reload the lifecycle workspace before submitting this change.')
    fingerprint = _request_fingerprint(
        action=action,
        target_user_id=getattr(target_user, 'pk', None),
        reason=reason,
        desired_grants=normalized_grants,
        replacement_user_id=getattr(replacement_user, 'pk', None),
        leave_from=leave_from,
        leave_until=leave_until,
        delegation_gates=delegation_gates,
        identity=normalized_identity,
        new_user_password=new_user_password,
    )
    AccessControlPolicyState.current()
    state = AccessControlPolicyState.objects.select_for_update().get(singleton=1)
    existing = _existing_request(
        requester=requester, request_key=key, fingerprint=fingerprint,
    )
    if existing:
        return existing, False

    if action == StaffLifecycleChangePlan.ACTION_ONBOARD:
        if target_user is not None:
            raise ValidationError('Onboarding creates a new staff account; do not select an existing user.')
        target_user = _create_onboarding_shell(
            identity=normalized_identity,
            new_user_password=new_user_password,
        )
    plan = create_lifecycle_plan(
        requester=requester,
        target_user=target_user,
        action=action,
        reason=reason,
        desired_grants=normalized_grants,
        replacement_user=replacement_user,
        leave_from=leave_from,
        leave_until=leave_until,
        delegation_gates=delegation_gates,
        request_key=key,
        identity=normalized_identity,
        decision_mode=decision_mode,
        request_fingerprint=fingerprint,
    )
    if decision_mode == StaffLifecycleChangePlan.DECISION_CHECKER:
        return plan, True
    plan.decision_mode = StaffLifecycleChangePlan.DECISION_SUPERUSER
    plan = _finalize_lifecycle_plan(
        plan=plan,
        actor=requester,
        state=state,
        review_comment='Applied directly by an active Django Superuser.',
    )
    return plan, True


@transaction.atomic
def apply_pending_lifecycle_plan_as_superuser(*, plan_id, actor, current_password,
                                              review_comment=''):
    if not actor or not actor.is_active or not actor.is_superuser:
        raise PermissionDenied('Only an active Django Superuser may directly apply a pending plan.')
    if not current_password or not actor.check_password(current_password):
        raise ValidationError('Your current Django Admin password is incorrect.')
    plan = StaffLifecycleChangePlan.objects.select_for_update().select_related(
        'target_user', 'requested_by',
    ).get(pk=plan_id)
    if plan.status != plan.STATUS_PENDING:
        raise ValidationError('Only pending lifecycle plans can be applied directly.')
    state = AccessControlPolicyState.objects.select_for_update().get(singleton=1)
    plan.decision_mode = plan.DECISION_SUPERUSER
    return _finalize_lifecycle_plan(
        plan=plan, actor=actor, state=state,
        review_comment=review_comment or 'Applied directly by an active Django Superuser.',
    )


@transaction.atomic
def cancel_pending_lifecycle_plan_as_superuser(*, plan_id, actor, current_password,
                                               reason):
    if not actor or not actor.is_active or not actor.is_superuser:
        raise PermissionDenied('Only an active Django Superuser may cancel a pending plan.')
    if not current_password or not actor.check_password(current_password):
        raise ValidationError('Your current Django Admin password is incorrect.')
    reason = str(reason or '').strip()
    if len(reason) < 10:
        raise ValidationError('Explain the cancellation in at least 10 characters.')
    plan = StaffLifecycleChangePlan.objects.select_for_update().get(pk=plan_id)
    if plan.status != plan.STATUS_PENDING:
        raise ValidationError('Only pending lifecycle plans can be cancelled.')
    plan.status = plan.STATUS_CANCELLED
    plan.reviewed_by = actor
    plan.reviewed_at = timezone.now()
    plan.review_comment = reason
    plan.decision_mode = plan.DECISION_SUPERUSER
    plan.save(update_fields=[
        'status', 'reviewed_by', 'reviewed_at', 'review_comment', 'decision_mode',
    ])
    _record_plan(plan, 'staff_lifecycle.plan.cancelled')
    return plan


@transaction.atomic
def approve_lifecycle_plan(*, plan_id, approver, review_comment='') -> StaffLifecycleChangePlan:
    if not can_approve_access_change(approver):
        raise PermissionDenied('You are not an appointed access control checker.')
    plan = StaffLifecycleChangePlan.objects.select_for_update().select_related('target_user', 'requested_by').get(pk=plan_id)
    if plan.status != plan.STATUS_PENDING:
        raise ValidationError('Only pending lifecycle plans can be approved.')
    if plan.decision_mode != plan.DECISION_CHECKER:
        raise ValidationError('This plan is not awaiting independent checker review.')
    if plan.requested_by_id == approver.pk:
        raise PermissionDenied('The plan maker cannot approve their own lifecycle plan.')
    if plan.target_user_id == approver.pk:
        raise PermissionDenied('A checker cannot approve a lifecycle plan targeting themselves.')
    if (plan.proposed_snapshot or {}).get('replacement_user_id') == approver.pk:
        raise PermissionDenied('A checker cannot approve a plan that grants routing or delegation authority to themselves.')
    if plan.target_user.is_superuser:
        raise ValidationError('Django Superuser accounts are outside this workspace.')
    state = AccessControlPolicyState.objects.select_for_update().get(singleton=1)
    return _finalize_lifecycle_plan(
        plan=plan, actor=approver, state=state, review_comment=review_comment,
    )


@transaction.atomic
def apply_scheduled_lifecycle_plan(*, plan_id) -> StaffLifecycleChangePlan:
    """Apply one previously approved plan when its effective time arrives."""
    plan = StaffLifecycleChangePlan.objects.select_for_update().select_related(
        'target_user', 'requested_by', 'reviewed_by',
    ).get(pk=plan_id)
    if plan.status != plan.STATUS_SCHEDULED:
        return plan
    if not plan.effective_at or plan.effective_at > timezone.now():
        return plan
    state = AccessControlPolicyState.objects.select_for_update().get(singleton=1)
    if state.version != plan.expected_policy_version or not _snapshot_matches(plan, plan.target_user):
        plan.status = plan.STATUS_STALE
        plan.error = 'Effective access or routing changed before the scheduled leave started.'
        plan.save(update_fields=['status', 'error'])
        _record_plan(plan, 'staff_lifecycle.plan.stale')
        return plan
    _apply_plan(plan, plan.target_user)
    state.version += 1
    state.save(update_fields=['version', 'updated_at'])
    snapshot = _policy_snapshot()
    snapshot['staff_lifecycle_plan'] = {
        'id': str(plan.pk), 'target_user_id': plan.target_user_id, 'action': plan.action,
    }
    AccessControlPolicySnapshot.objects.create(version=state.version, state=snapshot)
    plan.status = plan.STATUS_APPLIED
    plan.applied_at = timezone.now()
    plan.save(update_fields=['status', 'applied_at', 'impact'])
    _record_plan(plan, 'staff_lifecycle.plan.applied')
    return plan


def process_due_lifecycle_plans(*, limit=100) -> dict:
    ids = list(StaffLifecycleChangePlan.objects.filter(
        status=StaffLifecycleChangePlan.STATUS_SCHEDULED,
        effective_at__lte=timezone.now(),
    ).order_by('effective_at').values_list('pk', flat=True)[:limit])
    applied = stale = 0
    for plan_id in ids:
        plan = apply_scheduled_lifecycle_plan(plan_id=plan_id)
        applied += plan.status == plan.STATUS_APPLIED
        stale += plan.status == plan.STATUS_STALE
    return {'due': len(ids), 'applied': applied, 'stale': stale}


@transaction.atomic
def reject_lifecycle_plan(*, plan_id, approver, review_comment) -> StaffLifecycleChangePlan:
    if not can_approve_access_change(approver):
        raise PermissionDenied('You are not an appointed access control checker.')
    reason = str(review_comment or '').strip()
    if not reason:
        raise ValidationError('A rejection reason is required.')
    plan = StaffLifecycleChangePlan.objects.select_for_update().get(pk=plan_id)
    if plan.requested_by_id == approver.pk or plan.target_user_id == approver.pk:
        raise PermissionDenied('You cannot review this lifecycle plan.')
    if plan.status != plan.STATUS_PENDING:
        raise ValidationError('Only pending lifecycle plans can be rejected.')
    plan.status = plan.STATUS_REJECTED
    plan.reviewed_by = approver
    plan.reviewed_at = timezone.now()
    plan.review_comment = reason
    plan.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'review_comment'])
    _record_plan(plan, 'staff_lifecycle.plan.rejected')
    return plan


def _activation_digest(user_id, code: str) -> str:
    payload = f'{user_id}:{code}'.encode()
    return hmac.new(settings.SECRET_KEY.encode(), payload, hashlib.sha256).hexdigest()


@transaction.atomic
def generate_telegram_activation(*, user, actor) -> tuple[TelegramStaffActivation, str]:
    if not actor or not actor.is_active or not actor.is_superuser:
        raise PermissionDenied('Only an active Superuser may issue a Telegram activation code.')
    if user.is_superuser or not hasattr(user, 'staff_profile'):
        raise ValidationError('Choose a non-Superuser staff account with an enrolled Telegram profile.')
    now = timezone.now()
    TelegramStaffActivation.objects.select_for_update().filter(
        user=user, consumed_at__isnull=True, invalidated_at__isnull=True,
    ).update(invalidated_at=now)
    code = f'{secrets.randbelow(100_000_000):08d}'
    challenge = TelegramStaffActivation.objects.create(
        user=user, code_digest=_activation_digest(user.pk, code),
        expires_at=now + timedelta(minutes=ACTIVATION_TTL_MINUTES), created_by=actor,
    )
    return challenge, code


@transaction.atomic
def consume_telegram_activation(*, user, code: str) -> bool:
    challenge = TelegramStaffActivation.objects.select_for_update().filter(
        user=user, consumed_at__isnull=True, invalidated_at__isnull=True,
    ).order_by('-created_at').first()
    if not challenge or not challenge.usable:
        return False
    if not hmac.compare_digest(challenge.code_digest, _activation_digest(user.pk, str(code or '').strip())):
        challenge.failed_attempts += 1
        if challenge.failed_attempts >= ACTIVATION_MAX_ATTEMPTS:
            challenge.invalidated_at = timezone.now()
        challenge.save(update_fields=['failed_attempts', 'invalidated_at'])
        return False
    challenge.consumed_at = timezone.now()
    challenge.save(update_fields=['consumed_at'])
    return True


def _record_plan(plan, action: str) -> None:
    from core.services.compliance_audit import record_event

    record_event(
        workflow='access_control', action=action, category='authorization',
        subject_type='staff_lifecycle_plan', subject_id=str(plan.pk),
        actor=plan.reviewed_by or plan.requested_by,
        authority_user=plan.reviewed_by or plan.requested_by,
        request_id=plan.request_key or str(plan.pk), source_model='StaffLifecycleChangePlan',
        source_event_id=f'{plan.pk}:{action}', deduplication_key=f'staff:{plan.pk}:{action}',
        before_values=plan.before_snapshot or {}, after_values=plan.proposed_snapshot or {},
        metadata={
            'reason': plan.reason,
            'status': plan.status,
            'decision_mode': plan.decision_mode,
            'impact': plan.impact or {},
        },
        sensitive=True, occurred_at=timezone.now(),
    )
