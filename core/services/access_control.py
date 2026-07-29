"""Approval-controlled administration for Mini App role and staff access.

The module is deliberately the only writer for permanent access policy.  It
keeps the maker/checker state separate from effective ``AccessGrant`` rows so
an unapproved request can never accidentally authorize a staff member.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Iterable

import requests
from django.conf import settings
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from core.models import (
    AccessControlChangeRequest, AccessControlNotification,
    AccessControlPolicySnapshot, AccessControlPolicyState, AccessGrant,
    CapabilityUsageDaily, EmergencyAccessGrant, UserProfile,
    WorkflowRoleCapability, WorkflowRoleCapabilityAuditEvent,
)
from core.services.access_policies import canonical_access_role, validate_access_scope
from core.services.workflow_capabilities import capabilities_for_workflow, dependency_closure


APPROVER_GROUP_NAME = 'Access Policy Approvers'
EMERGENCY_ACCESS_HOURS = 4


def approver_group() -> Group:
    return Group.objects.get_or_create(name=APPROVER_GROUP_NAME)[0]


def can_approve_access_change(user) -> bool:
    return bool(user and user.is_active and user.groups.filter(name=APPROVER_GROUP_NAME).exists())


def policy_version() -> int:
    return AccessControlPolicyState.current().version


def _capability_state(workflow: str, role: str) -> dict[str, str]:
    return {
        key: effect
        for key, effect in WorkflowRoleCapability.objects.filter(workflow=workflow, role=role).values_list('capability_key', 'effect')
    }


def _policy_snapshot() -> dict:
    grants = []
    for row in AccessGrant.objects.order_by('user_id', 'workflow', 'role', 'branch', 'product').values('id', 'user_id', 'workflow', 'role', 'branch', 'product', 'group_configuration_id', 'active', 'source'):
        row['id'] = str(row['id'])
        grants.append(row)
    return {
        'capabilities': list(WorkflowRoleCapability.objects.order_by('workflow', 'role', 'capability_key').values('workflow', 'role', 'capability_key', 'effect')),
        'grants': grants,
    }


def capability_impact(workflow: str, role: str) -> dict:
    grants = AccessGrant.objects.filter(workflow=workflow, role=role, active=True)
    return {
        'staff_count': grants.values('user_id').distinct().count(),
        'branch_count': grants.exclude(branch='').values('branch').distinct().count(),
        'branches': sorted(grants.exclude(branch='').values_list('branch', flat=True).distinct()),
    }


def create_capability_request(*, requester, workflow: str, role: str, capability_keys: Iterable[str], reason: str, source_request=None):
    """Create a reviewable policy diff; it has no live effect until approved."""
    if not reason.strip():
        raise ValidationError('A business reason is required for an access-policy change.')
    role = canonical_access_role(workflow, role)
    allowed = {definition.key for definition in capabilities_for_workflow(workflow)}
    selected = dependency_closure(workflow, set(capability_keys).intersection(allowed))
    before = _capability_state(workflow, role)
    proposed = {key: ('allow' if key in selected else 'deny') for key in allowed}
    state = AccessControlPolicyState.current()
    request = AccessControlChangeRequest.objects.create(
        change_type=AccessControlChangeRequest.TYPE_CAPABILITY,
        workflow=workflow, role=role,
        before_snapshot={'capabilities': before},
        proposed_snapshot={'capabilities': proposed},
        impact=capability_impact(workflow, role),
        reason=reason.strip(), status=AccessControlChangeRequest.STATUS_PENDING,
        policy_version=state.version, requested_by=requester, source_request=source_request,
    )
    transaction.on_commit(lambda: notify_approvers(request, 'pending'))
    return request


def _grant_payload(*, user, workflow, role, branch='', product='', group_configuration=None, active=True, grant_id='') -> dict:
    role = validate_access_scope(workflow=workflow, role=role, branch=branch, product=product, group_configuration=group_configuration)
    return {
        'id': str(grant_id or ''), 'user_id': user.pk, 'workflow': workflow, 'role': role,
        'branch': branch or '', 'product': product or '',
        'group_configuration_id': getattr(group_configuration, 'pk', None), 'active': bool(active),
    }


def create_grant_request(*, requester, user, workflow, role, reason, branch='', product='', group_configuration=None, active=True, grant=None, source_request=None):
    if not reason.strip():
        raise ValidationError('A business reason is required for a staff access change.')
    proposed = _grant_payload(user=user, workflow=workflow, role=role, branch=branch, product=product, group_configuration=group_configuration, active=active, grant_id=getattr(grant, 'pk', ''))
    before = _grant_payload(user=grant.user, workflow=grant.workflow, role=grant.role, branch=grant.branch, product=grant.product, group_configuration=grant.group_configuration, active=grant.active, grant_id=grant.pk) if grant else {}
    request = AccessControlChangeRequest.objects.create(
        change_type=AccessControlChangeRequest.TYPE_GRANT,
        workflow=workflow, role=proposed['role'], target_user=user,
        before_snapshot={'grant': before}, proposed_snapshot={'grant': proposed},
        impact={'staff_count': 1, 'branch_count': 1 if proposed['branch'] else 0, 'branches': [proposed['branch']] if proposed['branch'] else []},
        reason=reason.strip(), status=AccessControlChangeRequest.STATUS_PENDING,
        policy_version=AccessControlPolicyState.current().version, requested_by=requester, source_request=source_request,
    )
    transaction.on_commit(lambda: notify_approvers(request, 'pending'))
    return request


def request_diff(request: AccessControlChangeRequest) -> dict:
    if request.change_type == request.TYPE_CAPABILITY:
        before = (request.before_snapshot or {}).get('capabilities') or {}
        after = (request.proposed_snapshot or {}).get('capabilities') or {}
        return {
            'allowed': sorted(key for key, value in after.items() if value == 'allow' and before.get(key) != 'allow'),
            'denied': sorted(key for key, value in after.items() if value == 'deny' and before.get(key) != 'deny'),
        }
    return {'before': (request.before_snapshot or {}).get('grant') or {}, 'after': (request.proposed_snapshot or {}).get('grant') or {}}


def _apply_capability_request(request: AccessControlChangeRequest) -> None:
    proposed = (request.proposed_snapshot or {}).get('capabilities') or {}
    definitions = {definition.key for definition in capabilities_for_workflow(request.workflow)}
    for key in definitions:
        effect = proposed.get(key, WorkflowRoleCapability.EFFECT_DENY)
        WorkflowRoleCapability.objects.update_or_create(
            workflow=request.workflow, role=request.role, capability_key=key,
            defaults={'effect': effect, 'enabled': effect == WorkflowRoleCapability.EFFECT_ALLOW},
        )
    diff = request_diff(request)
    WorkflowRoleCapabilityAuditEvent.objects.create(
        workflow=request.workflow, role=request.role, actor=request.reviewed_by,
        source='approved_change_request', changes={**diff, 'request_id': str(request.pk)},
    )


def _apply_grant_request(request: AccessControlChangeRequest) -> None:
    data = (request.proposed_snapshot or {}).get('grant') or {}
    grant_id = data.get('id')
    if grant_id:
        grant = AccessGrant.objects.select_for_update().filter(pk=grant_id).first()
    else:
        grant = None
    if grant is None:
        grant = AccessGrant(user_id=data['user_id'])
    grant.workflow = data['workflow']
    grant.role = data['role']
    grant.branch = data.get('branch', '')
    grant.product = data.get('product', '')
    grant.group_configuration_id = data.get('group_configuration_id') or None
    grant.active = bool(data.get('active'))
    grant.source = 'approved_access_request'
    grant.full_clean()
    grant.save()


def approve_request(*, request_id, approver, review_comment='') -> AccessControlChangeRequest:
    """Approve and apply one unchanged request in a single database transaction."""
    if not can_approve_access_change(approver):
        raise PermissionDenied('You are not a designated access-policy approver.')
    with transaction.atomic():
        request = AccessControlChangeRequest.objects.select_for_update().select_related('requested_by').get(pk=request_id)
        if request.requested_by_id == approver.pk:
            raise PermissionDenied('The request maker cannot approve their own access change.')
        if request.status != request.STATUS_PENDING:
            raise ValidationError('Only pending access-control requests can be approved.')
        state, _created = AccessControlPolicyState.objects.select_for_update().get_or_create(singleton=1)
        if request.policy_version != state.version:
            request.status = request.STATUS_STALE
            request.reviewed_by = approver
            request.reviewed_at = timezone.now()
            request.review_comment = 'Policy changed after this request was proposed; create a new request from the current state.'
            request.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'review_comment'])
            return request
        request.reviewed_by = approver
        request.reviewed_at = timezone.now()
        request.review_comment = review_comment.strip()
        request.status = request.STATUS_APPROVED
        if request.change_type == request.TYPE_CAPABILITY:
            _apply_capability_request(request)
        else:
            _apply_grant_request(request)
        state.version += 1
        state.save(update_fields=['version', 'updated_at'])
        AccessControlPolicySnapshot.objects.create(version=state.version, request=request, state=_policy_snapshot())
        request.status = request.STATUS_APPLIED
        request.applied_at = timezone.now()
        request.save(update_fields=['reviewed_by', 'reviewed_at', 'review_comment', 'status', 'applied_at'])
    notify_approvers(request, 'applied')
    return request


def reject_request(*, request_id, approver, review_comment) -> AccessControlChangeRequest:
    if not can_approve_access_change(approver):
        raise PermissionDenied('You are not a designated access-policy approver.')
    if not review_comment.strip():
        raise ValidationError('A rejection reason is required.')
    with transaction.atomic():
        request = AccessControlChangeRequest.objects.select_for_update().get(pk=request_id)
        if request.requested_by_id == approver.pk:
            raise PermissionDenied('The request maker cannot reject their own access change.')
        if request.status != request.STATUS_PENDING:
            raise ValidationError('Only pending requests can be rejected.')
        request.status = request.STATUS_REJECTED
        request.reviewed_by = approver
        request.reviewed_at = timezone.now()
        request.review_comment = review_comment.strip()
        request.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'review_comment'])
    notify_approvers(request, 'rejected')
    return request


def create_emergency_grant(*, actor, user, workflow, role, reason, branch='', product='', group_configuration=None):
    if not actor or not actor.is_active or not actor.is_superuser:
        raise PermissionDenied('Only an active superuser can activate emergency access.')
    if not reason.strip():
        raise ValidationError('Emergency access requires a reason.')
    role = validate_access_scope(workflow=workflow, role=role, branch=branch, product=product, group_configuration=group_configuration)
    grant = EmergencyAccessGrant.objects.create(
        user=user, workflow=workflow, role=role, branch=branch or '', product=product or '',
        group_configuration=group_configuration, reason=reason.strip(), activated_by=actor,
        expires_at=timezone.now() + timedelta(hours=EMERGENCY_ACCESS_HOURS),
    )
    notify_approvers(None, 'emergency_activated', extra=f'Emergency access for {user.get_username()} in {workflow}/{role} expires at {grant.expires_at:%d-%b-%Y %H:%M}.')
    return grant


def create_rollback_request(*, snapshot, requester, reason: str):
    """Propose reversal of one applied snapshot; approval is still required."""
    original = snapshot.request
    if original is None:
        raise ValidationError('The baseline snapshot is evidence only and cannot be reverted as one change.')
    if not reason.strip():
        raise ValidationError('A reason is required to propose a rollback.')
    if original.change_type == original.TYPE_CAPABILITY:
        prior = (original.before_snapshot or {}).get('capabilities') or {}
        return create_capability_request(
            requester=requester, workflow=original.workflow, role=original.role,
            capability_keys={key for key, effect in prior.items() if effect == 'allow'},
            reason=reason, source_request=original,
        )
    before = (original.before_snapshot or {}).get('grant') or {}
    proposed = (original.proposed_snapshot or {}).get('grant') or {}
    from django.contrib.auth import get_user_model
    user_id = before.get('user_id') or proposed.get('user_id')
    user = get_user_model().objects.get(pk=user_id)
    if before:
        grant = AccessGrant.objects.filter(pk=before.get('id')).first()
        from core.models import GroupSheetConfiguration
        group = GroupSheetConfiguration.objects.filter(pk=before.get('group_configuration_id')).first()
        return create_grant_request(
            requester=requester, user=user, workflow=before['workflow'], role=before['role'],
            branch=before.get('branch', ''), product=before.get('product', ''),
            group_configuration=group, active=before.get('active', True), grant=grant,
            reason=reason, source_request=original,
        )
    grant = AccessGrant.objects.filter(
        user=user, workflow=proposed['workflow'], role=proposed['role'], branch=proposed.get('branch', ''), product=proposed.get('product', ''),
    ).first()
    if grant is None:
        raise ValidationError('The grant created by this snapshot no longer exists; no rollback is needed.')
    return create_grant_request(
        requester=requester, user=user, workflow=grant.workflow, role=grant.role,
        branch=grant.branch, product=grant.product, group_configuration=grant.group_configuration,
        active=False, grant=grant, reason=reason, source_request=original,
    )


def notify_approvers(request, event: str, extra='') -> None:
    """Best-effort Telegram delivery with a durable Admin delivery ledger."""
    recipients = approver_group().user_set.filter(is_active=True).select_related('staff_profile')
    token = str(getattr(settings, 'TELEGRAM_BOT_TOKEN', '') or '')
    for recipient in recipients:
        note = AccessControlNotification.objects.create(request=request, recipient=recipient, channel=AccessControlNotification.CHANNEL_ADMIN, event=event, status='delivered', delivered_at=timezone.now())
        profile = getattr(recipient, 'staff_profile', None)
        telegram_id = str(getattr(profile, 'telegram_id', '') or '')
        if not token or not telegram_id:
            continue
        telegram = AccessControlNotification.objects.create(request=request, recipient=recipient, channel=AccessControlNotification.CHANNEL_TELEGRAM, event=event)
        text = extra or f'Access-control request {request.pk} is {event}: {request.workflow}/{request.role}.'
        try:
            response = requests.post(f'https://api.telegram.org/bot{token}/sendMessage', json={'chat_id': telegram_id, 'text': text}, timeout=10)
            response.raise_for_status()
            telegram.status, telegram.delivered_at = 'delivered', timezone.now()
        except requests.RequestException as exc:
            telegram.status, telegram.error = 'failed', str(exc)[:500]
        telegram.save(update_fields=['status', 'error', 'delivered_at'])


def record_capability_usage(user, workflow: str, capability_key: str) -> None:
    if not user or not user.is_authenticated:
        return
    now = timezone.now()
    lookup = {'day': now.date(), 'user': user, 'workflow': workflow, 'capability_key': capability_key}
    updated = CapabilityUsageDaily.objects.filter(**lookup).update(use_count=F('use_count') + 1, last_used_at=now)
    if not updated:
        try:
            CapabilityUsageDaily.objects.create(**lookup, use_count=1, last_used_at=now)
        except IntegrityError:
            CapabilityUsageDaily.objects.filter(**lookup).update(use_count=F('use_count') + 1, last_used_at=now)
