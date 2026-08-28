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
from django.db.models import F, Q
from django.utils import timezone

from core.models import (
    AccessControlChangeRequest, AccessControlCheckerAssignment, AccessControlNotification,
    AccessControlPolicySnapshot, AccessControlPolicyState, AccessGrant,
    CapabilityUsageDaily, EmergencyAccessGrant, UserProfile,
    DocumentSignoffPolicy, WorkflowRoleCapability, WorkflowRoleCapabilityAuditEvent,
)
from core.services.access_policies import canonical_access_role, validate_access_scope
from core.services.access_grant_governance import governed_access_grant_mutation
from core.services.workflow_capabilities import capabilities_for_workflow, dependency_closure


APPROVER_GROUP_NAME = 'Access Policy Approvers'
EMERGENCY_ACCESS_HOURS = 4


def approver_group() -> Group:
    """Return the retired legacy group for data-migration compatibility only.

    Effective checker authority is stored in ``AccessControlCheckerAssignment``.
    Keeping this helper avoids breaking historical administration references
    while ensuring a direct Group edit can never grant approval authority.
    """
    return Group.objects.get_or_create(name=APPROVER_GROUP_NAME)[0]


def approver_users():
    """Return active root Superusers and independently appointed checkers."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.filter(
        Q(is_superuser=True)
        | Q(
            access_control_checker_assignments__isnull=False,
            access_control_checker_assignments__revoked_at__isnull=True,
        ),
        is_active=True,
    ).distinct()


def active_checker_assignment_for_user(user):
    if not user or not getattr(user, 'pk', None):
        return None
    return AccessControlCheckerAssignment.objects.filter(
        user=user,
        revoked_at__isnull=True,
        user__is_active=True,
    ).select_related('user', 'appointed_by', 'revoked_by').first()


def can_approve_access_change(user) -> bool:
    return bool(user and user.is_active and (
        user.is_superuser or active_checker_assignment_for_user(user) is not None
    ))


def bootstrap_override_available(request, approver) -> bool:
    """Permanent access changes never receive a maker/checker bypass.

    Bootstrap is confined to appointing the first independent checker in
    ``appoint_access_control_checker`` and cannot approve operational access.
    """
    return False


def _record_checker_assignment(assignment, *, action: str, actor, before: dict, after: dict, decision_mode: str) -> None:
    from core.services.compliance_audit import record_event

    record_event(
        workflow='access_control',
        action=action,
        category='authorization',
        subject_type='access_control_checker',
        subject_id=str(assignment.pk),
        actor=actor,
        authority_user=actor,
        request_id=str(assignment.pk),
        source_model='AccessControlCheckerAssignment',
        source_event_id=str(assignment.pk),
        deduplication_key=f'access:AccessControlCheckerAssignment:{assignment.pk}:{action}',
        before_values=before,
        after_values=after,
        metadata={
            'target_user_id': assignment.user_id,
            'reason': assignment.appointment_reason if action.endswith('appointed') else assignment.revocation_reason,
            'decision_mode': decision_mode,
        },
        sensitive=True,
        occurred_at=timezone.now(),
    )


def appoint_access_control_checker(*, actor, user, reason: str, confirmation_phrase: str = ''):
    """Directly appoint a checker from the technical Superuser boundary.

    This is intentionally not a Mini App access grant.  It is the bootstrap
    path which lets the first root administrator create independent reviewers
    without an impossible self-approval loop.  Repeated submissions are
    idempotent while the appointment remains active.
    """
    if not actor or not actor.is_active or not actor.is_superuser:
        raise PermissionDenied('Only an active Django Superuser can appoint an access control checker.')
    if not user or not user.is_active:
        raise ValidationError('Only an active user can be appointed as an access control checker.')
    if not user.is_staff:
        raise ValidationError(
            'An access control checker must have deliberate Django Admin access '
            '(is_staff=True) so they can review requests independently.'
        )
    if user.pk == actor.pk:
        raise ValidationError('A Django Superuser is already a root approver and does not need a checker appointment.')
    if not reason.strip():
        raise ValidationError('A reason is required to appoint an access control checker.')

    with transaction.atomic():
        existing = AccessControlCheckerAssignment.objects.select_for_update().filter(
            user=user,
            revoked_at__isnull=True,
        ).first()
        if existing:
            return existing, False
        decision_mode = (
            AccessControlCheckerAssignment.SOURCE_BOOTSTRAP
            if not approver_users().exclude(pk=actor.pk).exists()
            else AccessControlCheckerAssignment.SOURCE_SUPERUSER
        )
        if (
            decision_mode == AccessControlCheckerAssignment.SOURCE_BOOTSTRAP
            and str(confirmation_phrase or '').strip() != 'APPOINT FIRST CHECKER'
        ):
            raise ValidationError('Type APPOINT FIRST CHECKER to confirm the bootstrap appointment.')
        assignment = AccessControlCheckerAssignment.objects.create(
            user=user,
            appointed_by=actor,
            appointment_reason=reason.strip(),
            source=decision_mode,
        )
        _record_checker_assignment(
            assignment,
            action='access_control.checker.appointed',
            actor=actor,
            before={},
            after={
                'user_id': assignment.user_id,
                'source': assignment.source,
                'appointed_at': assignment.appointed_at,
            },
            decision_mode=decision_mode,
        )
    transaction.on_commit(lambda: notify_approvers(
        None,
        'checker_appointed',
        extra=f'{user.get_username()} was appointed as an access control checker.',
    ))
    return assignment, True


def revoke_access_control_checker(*, actor, assignment, reason: str):
    """Revoke checker authority while preserving the appointment evidence."""
    if not actor or not actor.is_active or not actor.is_superuser:
        raise PermissionDenied('Only an active Django Superuser can revoke an access control checker.')
    if not reason.strip():
        raise ValidationError('A reason is required to revoke an access control checker.')
    with transaction.atomic():
        assignment = AccessControlCheckerAssignment.objects.select_for_update().select_related('user').get(pk=assignment.pk)
        if assignment.revoked_at is not None:
            return assignment, False
        before = {
            'user_id': assignment.user_id,
            'source': assignment.source,
            'appointed_at': assignment.appointed_at,
        }
        assignment.revoked_at = timezone.now()
        assignment.revoked_by = actor
        assignment.revocation_reason = reason.strip()
        assignment.save(update_fields=['revoked_at', 'revoked_by', 'revocation_reason'])
        _record_checker_assignment(
            assignment,
            action='access_control.checker.revoked',
            actor=actor,
            before=before,
            after={**before, 'revoked_at': assignment.revoked_at},
            decision_mode='superuser_revocation',
        )
    transaction.on_commit(lambda: notify_approvers(
        None,
        'checker_revoked',
        extra=f'{assignment.user.get_username()} is no longer an access control checker.',
    ))
    return assignment, True


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
        'document_signoff_policies': list(
            DocumentSignoffPolicy.objects.order_by('document_type').values(
                'document_type', 'workflow', 'approval_role', 'approval_roles', 'is_active',
            )
        ),
    }


def _record_access_control_request(request: AccessControlChangeRequest) -> None:
    """Capture proposal evidence before it can affect effective access."""
    from core.services.compliance_audit import record_event

    record_event(
        workflow='access_control',
        action='access_control.change.requested',
        category='authorization',
        subject_type=request.change_type,
        subject_id=str(request.pk),
        actor=request.requested_by,
        authority_user=request.requested_by,
        request_id=str(request.pk),
        source_model='AccessControlChangeRequest',
        source_event_id=str(request.pk),
        deduplication_key=f'access:AccessControlChangeRequest:{request.pk}:requested',
        before_values=request.before_snapshot or {},
        after_values=request.proposed_snapshot or {},
        metadata={'workflow': request.workflow, 'role': request.role, 'impact': request.impact or {}, 'reason': request.reason},
        sensitive=True,
        occurred_at=request.requested_at,
    )


def _record_access_control_decision(
    request: AccessControlChangeRequest,
    *,
    action: str,
    decision_mode: str = 'independent_checker',
) -> None:
    from core.services.compliance_audit import record_event

    record_event(
        workflow='access_control',
        action=action,
        category='authorization',
        subject_type=request.change_type,
        subject_id=str(request.pk),
        actor=request.reviewed_by,
        authority_user=request.reviewed_by,
        request_id=str(request.pk),
        source_model='AccessControlChangeRequest',
        source_event_id=f'{request.pk}:{request.status}',
        deduplication_key=f'access:AccessControlChangeRequest:{request.pk}:{request.status}',
        before_values=request.before_snapshot or {},
        after_values=request.proposed_snapshot or {},
        metadata={
            'status': request.status,
            'workflow': request.workflow,
            'role': request.role,
            'impact': request.impact or {},
            'review_comment': request.review_comment,
            'decision_mode': decision_mode,
        },
        sensitive=True,
        occurred_at=request.reviewed_at or timezone.now(),
    )


def capability_impact(workflow: str, role: str) -> dict:
    grants = AccessGrant.objects.filter(workflow=workflow, role=role, active=True)
    return {
        'staff_count': grants.values('user_id').distinct().count(),
        'branch_count': grants.exclude(branch='').values('branch').distinct().count(),
        'branches': sorted(grants.exclude(branch='').values_list('branch', flat=True).distinct()),
    }


def create_capability_request(
    *, requester, workflow: str, role: str = '', roles: Iterable[str] | None = None,
    capability_keys: Iterable[str], reason: str, source_request=None,
    request_key: str = '',
):
    """Create a reviewable policy diff; it has no live effect until approved."""
    if not requester or not requester.is_active:
        raise ValidationError('An active requester is required for an access-policy change.')
    if not reason.strip():
        raise ValidationError('A business reason is required for an access-policy change.')
    requested_roles = list(roles or [role])
    normalized_roles = []
    for requested_role in requested_roles:
        normalized = validate_access_scope(workflow=workflow, role=requested_role)
        if normalized not in normalized_roles:
            normalized_roles.append(normalized)
    if not normalized_roles:
        raise ValidationError('Choose at least one valid workflow role.')
    allowed = {definition.key for definition in capabilities_for_workflow(workflow)}
    selected = dependency_closure(workflow, set(capability_keys).intersection(allowed))
    before_by_role = {
        target_role: _capability_state(workflow, target_role)
        for target_role in normalized_roles
    }
    proposed = {key: ('allow' if key in selected else 'deny') for key in allowed}
    key = str(request_key or '').strip()[:128]
    if key:
        existing = AccessControlChangeRequest.objects.filter(
            requested_by=requester, request_key=key,
        ).first()
        if existing:
            return existing
    state = AccessControlPolicyState.current()
    try:
        with transaction.atomic():
            request = AccessControlChangeRequest.objects.create(
                change_type=AccessControlChangeRequest.TYPE_CAPABILITY,
                workflow=workflow, role=normalized_roles[0], target_roles=normalized_roles,
                before_snapshot={
                    'capabilities': before_by_role[normalized_roles[0]],
                    'role_capabilities': before_by_role,
                },
                proposed_snapshot={
                    'capabilities': proposed,
                    'role_capabilities': {target_role: proposed for target_role in normalized_roles},
                },
                impact={
                    'roles': normalized_roles,
                    'staff_count': AccessGrant.objects.filter(
                        workflow=workflow, role__in=normalized_roles, active=True,
                    ).values('user_id').distinct().count(),
                },
                reason=reason.strip(), status=AccessControlChangeRequest.STATUS_PENDING,
                policy_version=state.version, requested_by=requester,
                source_request=source_request, request_key=key,
            )
    except IntegrityError:
        if key:
            return AccessControlChangeRequest.objects.get(requested_by=requester, request_key=key)
        raise
    _record_access_control_request(request)
    transaction.on_commit(lambda: notify_approvers(request, 'pending'))
    return request


def _grant_payload(*, user, workflow, role, branch='', product='', group_configuration=None, active=True, grant_id='') -> dict:
    role = validate_access_scope(workflow=workflow, role=role, branch=branch, product=product, group_configuration=group_configuration)
    return {
        'id': str(grant_id or ''), 'user_id': user.pk, 'workflow': workflow, 'role': role,
        'branch': branch or '', 'product': product or '',
        'group_configuration_id': getattr(group_configuration, 'pk', None), 'active': bool(active),
    }


def create_grant_request(*, requester, user, workflow, role, reason, branch='', product='', group_configuration=None, active=True, grant=None, source_request=None, request_key=''):
    if not requester or not requester.is_active:
        raise ValidationError('An active requester is required for a staff access change.')
    if not user or not user.pk:
        raise ValidationError('Choose the staff user receiving the Access Grant.')
    if active and not user.is_active:
        raise ValidationError('Activate the staff account before requesting active Mini App access.')
    if not reason.strip():
        raise ValidationError('A business reason is required for a staff access change.')
    key = str(request_key or '').strip()[:128]
    if key:
        existing = AccessControlChangeRequest.objects.filter(
            requested_by=requester, request_key=key,
        ).first()
        if existing:
            return existing
    proposed = _grant_payload(user=user, workflow=workflow, role=role, branch=branch, product=product, group_configuration=group_configuration, active=active, grant_id=getattr(grant, 'pk', ''))
    before = _grant_payload(user=grant.user, workflow=grant.workflow, role=grant.role, branch=grant.branch, product=grant.product, group_configuration=grant.group_configuration, active=grant.active, grant_id=grant.pk) if grant else {}
    try:
        with transaction.atomic():
            request = AccessControlChangeRequest.objects.create(
                change_type=AccessControlChangeRequest.TYPE_GRANT,
                workflow=workflow, role=proposed['role'], target_user=user,
                before_snapshot={'grant': before}, proposed_snapshot={'grant': proposed},
                impact={'staff_count': 1, 'branch_count': 1 if proposed['branch'] else 0, 'branches': [proposed['branch']] if proposed['branch'] else []},
                reason=reason.strip(), status=AccessControlChangeRequest.STATUS_PENDING,
                policy_version=AccessControlPolicyState.current().version, requested_by=requester,
                source_request=source_request, target_roles=[proposed['role']], request_key=key,
            )
    except IntegrityError:
        if key:
            return AccessControlChangeRequest.objects.get(requested_by=requester, request_key=key)
        raise
    _record_access_control_request(request)
    transaction.on_commit(lambda: notify_approvers(request, 'pending'))
    return request


def create_document_signoff_policy_request(*, requester, document_type: str, reason: str, approval_role: str = '', approval_roles=None, source_request=None):
    """Propose one or more responsible roles for physical document sign-off.

    A role selection changes who may attest a signed/stamped scan, so it uses
    the same maker-checker ledger and policy-version guard as capabilities and
    staff grants.  The request itself never changes effective access.
    """
    if not reason.strip():
        raise ValidationError('A business reason is required for a document sign-off policy change.')
    valid_types = {value for value, _label in DocumentSignoffPolicy.DOCUMENT_TYPE_CHOICES}
    if document_type not in valid_types:
        raise ValidationError({'document_type': 'Select a supported document type.'})
    raw_roles = approval_roles if approval_roles is not None else [approval_role]
    if isinstance(raw_roles, str):
        raw_roles = [raw_roles]
    roles = []
    for raw_role in raw_roles or []:
        role = validate_access_scope(workflow='jawabu_portal', role=str(raw_role or ''))
        if role not in roles:
            roles.append(role)
    if not roles:
        raise ValidationError({'approval_roles': 'Select at least one authorised Portal role.'})
    unsupported = [role for role in roles if not WorkflowRoleCapability.objects.filter(
        workflow='jawabu_portal', role=role,
        capability_key='portal.documents.sign',
        effect=WorkflowRoleCapability.EFFECT_ALLOW,
    ).exists()]
    if unsupported:
        raise ValidationError(
            'Give each selected role the approved portal.documents.sign capability before making it a document sign-off approver.'
        )
    current = DocumentSignoffPolicy.objects.filter(document_type=document_type).first()
    before = {
        'document_type': current.document_type,
        'workflow': current.workflow,
        'approval_role': current.approval_role,
        'approval_roles': list(current.effective_approval_roles),
        'is_active': current.is_active,
    } if current else {}
    proposed = {
        'document_type': document_type,
        'workflow': 'jawabu_portal',
        'approval_role': roles[0],
        'approval_roles': roles,
        'is_active': True,
    }
    request = AccessControlChangeRequest.objects.create(
        change_type=AccessControlChangeRequest.TYPE_DOCUMENT_SIGNOFF,
        workflow='jawabu_portal', role=roles[0],
        before_snapshot={'document_signoff_policy': before},
        proposed_snapshot={'document_signoff_policy': proposed},
        impact={
            'roles': roles,
            'staff_count': AccessGrant.objects.filter(
                workflow='jawabu_portal', role__in=roles, active=True,
            ).values('user_id').distinct().count(),
        },
        reason=reason.strip(), status=AccessControlChangeRequest.STATUS_PENDING,
        policy_version=AccessControlPolicyState.current().version,
        requested_by=requester, source_request=source_request,
    )
    _record_access_control_request(request)
    transaction.on_commit(lambda: notify_approvers(request, 'pending'))
    return request


def request_diff(request: AccessControlChangeRequest) -> dict:
    if request.change_type == request.TYPE_CAPABILITY:
        before_by_role = (request.before_snapshot or {}).get('role_capabilities') or {}
        after_by_role = (request.proposed_snapshot or {}).get('role_capabilities') or {}
        if before_by_role or after_by_role:
            roles = request.target_roles or [request.role]
            role_diffs = {}
            for role in roles:
                before = before_by_role.get(role, {})
                after = after_by_role.get(role, {})
                role_diffs[role] = {
                    'allowed': sorted(key for key, value in after.items() if value == 'allow' and before.get(key) != 'allow'),
                    'denied': sorted(key for key, value in after.items() if value == 'deny' and before.get(key) != 'deny'),
                }
            if len(role_diffs) > 1:
                return {'roles': role_diffs}
        before = (request.before_snapshot or {}).get('capabilities') or {}
        after = (request.proposed_snapshot or {}).get('capabilities') or {}
        return {
            'allowed': sorted(key for key, value in after.items() if value == 'allow' and before.get(key) != 'allow'),
            'denied': sorted(key for key, value in after.items() if value == 'deny' and before.get(key) != 'deny'),
        }
    if request.change_type == request.TYPE_DOCUMENT_SIGNOFF:
        return {
            'before': (request.before_snapshot or {}).get('document_signoff_policy') or {},
            'after': (request.proposed_snapshot or {}).get('document_signoff_policy') or {},
        }
    return {'before': (request.before_snapshot or {}).get('grant') or {}, 'after': (request.proposed_snapshot or {}).get('grant') or {}}


def _apply_capability_request(request: AccessControlChangeRequest) -> None:
    proposed_by_role = (request.proposed_snapshot or {}).get('role_capabilities') or {}
    roles = request.target_roles or [request.role]
    definitions = {definition.key for definition in capabilities_for_workflow(request.workflow)}
    for role in roles:
        proposed = proposed_by_role.get(role) or (request.proposed_snapshot or {}).get('capabilities') or {}
        for key in definitions:
            effect = proposed.get(key, WorkflowRoleCapability.EFFECT_DENY)
            WorkflowRoleCapability.objects.update_or_create(
                workflow=request.workflow, role=role, capability_key=key,
                defaults={'effect': effect, 'enabled': effect == WorkflowRoleCapability.EFFECT_ALLOW},
            )
        before = ((request.before_snapshot or {}).get('role_capabilities') or {}).get(role) or (
            (request.before_snapshot or {}).get('capabilities') or {}
        )
        diff = {
            'allowed': sorted(key for key, value in proposed.items() if value == 'allow' and before.get(key) != 'allow'),
            'denied': sorted(key for key, value in proposed.items() if value == 'deny' and before.get(key) != 'deny'),
        }
        audit_event = WorkflowRoleCapabilityAuditEvent.objects.create(
            workflow=request.workflow, role=role, actor=request.reviewed_by,
            source='approved_change_request', changes={**diff, 'request_id': str(request.pk)},
        )
        from core.services.compliance_audit import record_event

        record_event(
            workflow='access_control', action='access_control.capability.applied',
            category='authorization', subject_type='workflow_role_capability',
            subject_id=f'{request.workflow}:{role}', actor=request.reviewed_by,
            authority_user=request.reviewed_by, request_id=str(request.pk),
            source_model='WorkflowRoleCapabilityAuditEvent', source_event_id=str(audit_event.pk),
            deduplication_key=f'access:WorkflowRoleCapabilityAuditEvent:{audit_event.pk}',
            before_values=before, after_values=proposed,
            metadata={'impact': request.impact or {}, 'reason': request.reason},
            sensitive=True, occurred_at=audit_event.created_at,
        )


def _apply_grant_request(request: AccessControlChangeRequest) -> None:
    with governed_access_grant_mutation('approved access-control request'):
        snapshot = request.proposed_snapshot or {}
        data = snapshot.get('grant') or {}
        if snapshot.get('operation') == 'delete':
            before = (request.before_snapshot or {}).get('grant') or {}
            grant_id = before.get('id')
            grant = AccessGrant.objects.select_for_update().filter(pk=grant_id).first()
            if grant is None:
                raise ValidationError('The Access Grant no longer exists and cannot be deleted.')
            grant.active = False
            grant.source = 'retired_access_request'
            grant.save(update_fields=['active', 'source', 'updated_at'])
            return
        grant_id = data.get('id')
        if grant_id:
            grant = AccessGrant.objects.select_for_update().filter(pk=grant_id).first()
        else:
            grant = AccessGrant.objects.select_for_update().filter(
                user_id=data['user_id'], workflow=data['workflow'], role=data['role'],
                branch=data.get('branch', ''), product=data.get('product', ''),
                group_configuration_id=data.get('group_configuration_id') or None,
                active=False,
            ).first()
        if grant is None:
            grant = AccessGrant(user_id=data['user_id'])
        grant.workflow = data['workflow']
        grant.role = data['role']
        grant.branch = data.get('branch', '')
        grant.product = data.get('product', '')
        grant.group_configuration_id = data.get('group_configuration_id') or None
        grant.active = bool(data.get('active'))
        grant.source = (
            'django_superuser_override'
            if snapshot.get('execution_mode') == 'django_superuser_override'
            else 'approved_access_request'
        )
        grant.full_clean()
        grant.save()


def apply_superuser_grant_override(
    *,
    actor,
    user,
    workflow: str | None = None,
    role: str | None = None,
    branch: str = '',
    product: str = '',
    group_configuration=None,
    active: bool = True,
    grant: AccessGrant | None = None,
    operation: str = 'upsert',
) -> AccessControlChangeRequest:
    """Retired compatibility entry point for the former immediate override.

    Permanent authority now requires an independent checker through a grant
    request or atomic staff lifecycle plan.  Keeping this explicit failure is
    safer than leaving old scripts able to silently bypass the new control.
    """
    raise PermissionDenied(
        'Immediate permanent AccessGrant overrides are retired. Submit a '
        'checker-approved staff lifecycle or access-control request.'
    )


def _apply_document_signoff_policy_request(request: AccessControlChangeRequest) -> None:
    data = (request.proposed_snapshot or {}).get('document_signoff_policy') or {}
    policy, _created = DocumentSignoffPolicy.objects.update_or_create(
        document_type=data['document_type'],
        defaults={
            'workflow': data.get('workflow') or 'jawabu_portal',
            'approval_role': data['approval_role'],
            'approval_roles': data.get('approval_roles') or [data['approval_role']],
            'is_active': bool(data.get('is_active', True)),
        },
    )
    policy.full_clean()
    policy.save()


def _request_target_is_unchanged(request: AccessControlChangeRequest) -> bool:
    """Compare only the requested target, allowing unrelated approvals to proceed."""
    if request.change_type == request.TYPE_CAPABILITY:
        roles = request.target_roles or [request.role]
        before_by_role = (request.before_snapshot or {}).get('role_capabilities') or {}
        for role in roles:
            expected = before_by_role.get(role)
            if expected is None:
                expected = (request.before_snapshot or {}).get('capabilities') or {}
            if _capability_state(request.workflow, role) != expected:
                return False
        return True
    if request.change_type == request.TYPE_GRANT:
        before = (request.before_snapshot or {}).get('grant') or {}
        proposed = (request.proposed_snapshot or {}).get('grant') or {}
        if before:
            grant = AccessGrant.objects.filter(pk=before.get('id')).select_related('group_configuration').first()
            if grant is None:
                return False
            current = _grant_payload(
                user=grant.user, workflow=grant.workflow, role=grant.role,
                branch=grant.branch, product=grant.product,
                group_configuration=grant.group_configuration, active=grant.active,
                grant_id=grant.pk,
            )
            return current == before
        return not AccessGrant.objects.filter(
            user_id=proposed.get('user_id'), workflow=proposed.get('workflow'),
            role=proposed.get('role'), branch=proposed.get('branch', ''),
            product=proposed.get('product', ''),
            group_configuration_id=proposed.get('group_configuration_id') or None,
        ).exists()
    if request.change_type == request.TYPE_DOCUMENT_SIGNOFF:
        current = DocumentSignoffPolicy.objects.filter(
            document_type=((request.proposed_snapshot or {}).get('document_signoff_policy') or {}).get('document_type'),
        ).first()
        current_payload = {
            'document_type': current.document_type,
            'workflow': current.workflow,
            'approval_role': current.approval_role,
            'approval_roles': list(current.effective_approval_roles),
            'is_active': current.is_active,
        } if current else {}
        return current_payload == ((request.before_snapshot or {}).get('document_signoff_policy') or {})
    return False


def _approval_conflict_error(request: AccessControlChangeRequest, approver) -> str:
    if request.change_type == request.TYPE_GRANT and request.target_user_id == approver.pk:
        return 'An access-policy checker cannot approve a grant targeting their own account.'
    if request.change_type == request.TYPE_CAPABILITY and not approver.is_superuser:
        target_roles = request.target_roles or [request.role]
        if AccessGrant.objects.filter(
            user=approver, workflow=request.workflow, role__in=target_roles, active=True,
        ).exists():
            return 'An access-policy checker cannot approve a capability change for a role they currently hold.'
    return ''


def approve_request(*, request_id, approver, review_comment='') -> AccessControlChangeRequest:
    """Approve and apply one unchanged request in a single database transaction."""
    if not can_approve_access_change(approver):
        raise PermissionDenied('You are not a designated access-policy approver.')
    with transaction.atomic():
        request = AccessControlChangeRequest.objects.select_for_update().select_related('requested_by').get(pk=request_id)
        bootstrap_override = bootstrap_override_available(request, approver)
        if request.requested_by_id == approver.pk and not bootstrap_override:
            raise PermissionDenied('The request maker cannot approve their own access change.')
        conflict_error = _approval_conflict_error(request, approver)
        if conflict_error and not bootstrap_override:
            raise PermissionDenied(conflict_error)
        if bootstrap_override and not review_comment.strip():
            raise ValidationError('A bootstrap override requires an explicit approval reason.')
        if request.status != request.STATUS_PENDING:
            raise ValidationError('Only pending access-control requests can be approved.')
        proposed_grant = (request.proposed_snapshot or {}).get('grant') or {}
        if (
            request.change_type == request.TYPE_GRANT
            and proposed_grant.get('active')
            and (not request.target_user or not request.target_user.is_active)
        ):
            raise ValidationError('The target staff account is inactive; submit a new request after reactivation.')
        state, _created = AccessControlPolicyState.objects.select_for_update().get_or_create(singleton=1)
        if request.policy_version != state.version and not _request_target_is_unchanged(request):
            request.status = request.STATUS_STALE
            request.reviewed_by = approver
            request.reviewed_at = timezone.now()
            request.review_comment = 'Policy changed after this request was proposed; create a new request from the current state.'
            request.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'review_comment'])
            _record_access_control_decision(
                request,
                action='access_control.change.stale',
                decision_mode='bootstrap_override' if bootstrap_override else 'independent_checker',
            )
            return request
        request.reviewed_by = approver
        request.reviewed_at = timezone.now()
        request.review_comment = review_comment.strip()
        request.status = request.STATUS_APPROVED
        if request.change_type == request.TYPE_CAPABILITY:
            _apply_capability_request(request)
        elif request.change_type == request.TYPE_GRANT:
            _apply_grant_request(request)
        elif request.change_type == request.TYPE_DOCUMENT_SIGNOFF:
            _apply_document_signoff_policy_request(request)
        else:
            raise ValidationError('Unsupported access-control change type.')
        state.version += 1
        state.save(update_fields=['version', 'updated_at'])
        AccessControlPolicySnapshot.objects.create(version=state.version, request=request, state=_policy_snapshot())
        request.status = request.STATUS_APPLIED
        request.applied_at = timezone.now()
        request.save(update_fields=['reviewed_by', 'reviewed_at', 'review_comment', 'status', 'applied_at'])
        _record_access_control_decision(
            request,
            action='access_control.change.bootstrap_override_applied' if bootstrap_override else 'access_control.change.applied',
            decision_mode='bootstrap_override' if bootstrap_override else 'independent_checker',
        )
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
        _record_access_control_decision(request, action='access_control.change.rejected')
    notify_approvers(request, 'rejected')
    return request


def _record_emergency_access(grant, *, action: str, actor, reason: str) -> None:
    from core.services.compliance_audit import record_event

    record_event(
        workflow='access_control', action=action, category='authorization',
        subject_type='emergency_access_grant', subject_id=str(grant.pk),
        actor=actor, authority_user=actor, request_id=grant.request_id or str(grant.pk),
        source_model='EmergencyAccessGrant', source_event_id=f'{grant.pk}:{action}',
        deduplication_key=f'access:EmergencyAccessGrant:{grant.pk}:{action}',
        before_values={},
        after_values={
            'user_id': grant.user_id, 'workflow': grant.workflow, 'role': grant.role,
            'branch': grant.branch, 'product': grant.product,
            'expires_at': grant.expires_at, 'revoked_at': grant.revoked_at,
        },
        metadata={'reason': reason}, sensitive=True, occurred_at=timezone.now(),
    )


def create_emergency_grant(*, actor, user, workflow, role, reason, branch='', product='', group_configuration=None, request_id=''):
    if not actor or not actor.is_active or not actor.is_superuser:
        raise PermissionDenied('Only an active superuser can activate emergency access.')
    if not user or not user.is_active:
        raise ValidationError('Emergency access can only be activated for an active staff account.')
    if not reason.strip():
        raise ValidationError('Emergency access requires a reason.')
    key = str(request_id or '').strip()[:128]
    if key:
        existing = EmergencyAccessGrant.objects.filter(activated_by=actor, request_id=key).first()
        if existing:
            return existing
    role = validate_access_scope(workflow=workflow, role=role, branch=branch, product=product, group_configuration=group_configuration)
    try:
        with transaction.atomic():
            grant = EmergencyAccessGrant.objects.create(
                user=user, workflow=workflow, role=role, branch=branch or '', product=product or '',
                group_configuration=group_configuration, reason=reason.strip(), activated_by=actor,
                expires_at=timezone.now() + timedelta(hours=EMERGENCY_ACCESS_HOURS), request_id=key,
            )
    except IntegrityError:
        if key:
            return EmergencyAccessGrant.objects.get(activated_by=actor, request_id=key)
        raise
    _record_emergency_access(
        grant, action='access_control.emergency.activated', actor=actor, reason=reason.strip(),
    )
    notify_approvers(None, 'emergency_activated', extra=f'Emergency access for {user.get_username()} in {workflow}/{role} expires at {grant.expires_at:%d-%b-%Y %H:%M}.')
    return grant


@transaction.atomic
def revoke_emergency_grant(*, actor, grant, reason: str):
    if not actor or not actor.is_active or not actor.is_superuser:
        raise PermissionDenied('Only an active superuser can revoke emergency access.')
    if not str(reason or '').strip():
        raise ValidationError('A reason is required to revoke emergency access.')
    grant = EmergencyAccessGrant.objects.select_for_update().get(pk=grant.pk)
    if grant.revoked_at is not None:
        return grant, False
    grant.revoked_at = timezone.now()
    grant.revoked_by = actor
    grant.revocation_reason = str(reason).strip()
    grant.save(update_fields=['revoked_at', 'revoked_by', 'revocation_reason'])
    _record_emergency_access(
        grant, action='access_control.emergency.revoked', actor=actor,
        reason=grant.revocation_reason,
    )
    return grant, True


@transaction.atomic
def retire_user_access(*, user, actor=None, reason: str = 'Staff account deactivated.') -> dict:
    """Fail closed on deactivation; reactivation never restores old authority."""
    now = timezone.now()
    grant_rows = list(AccessGrant.objects.select_for_update().filter(user=user, active=True))
    from core.services.compliance_audit import record_event

    with governed_access_grant_mutation('staff account deactivation'):
        for grant in grant_rows:
            previous_source = grant.source
            grant.active = False
            grant.source = 'account_deactivated'
            grant.save(update_fields=['active', 'source', 'updated_at'])
            record_event(
                workflow='access_control', action='access_control.grant.retired',
                category='authorization', subject_type='access_grant',
                subject_id=str(grant.pk), actor=actor, authority_user=actor,
                request_id=str(grant.pk), source_model='AccessGrant',
                source_event_id=f'{grant.pk}:account_deactivated',
                deduplication_key=f'access:AccessGrant:{grant.pk}:account_deactivated',
                before_values={'active': True, 'source': previous_source},
                after_values={'active': False, 'source': grant.source},
                metadata={'target_user_id': user.pk, 'reason': reason},
                sensitive=True, occurred_at=now,
            )
    emergency_rows = list(EmergencyAccessGrant.objects.select_for_update().filter(
        user=user, revoked_at__isnull=True,
    ))
    for grant in emergency_rows:
        grant.revoked_at = now
        grant.revoked_by = actor if getattr(actor, 'pk', None) else None
        grant.revocation_reason = reason
        grant.save(update_fields=['revoked_at', 'revoked_by', 'revocation_reason'])
        _record_emergency_access(
            grant, action='access_control.emergency.revoked', actor=actor, reason=reason,
        )
    from core.models import JawabuApprovalDelegation

    delegations = JawabuApprovalDelegation.objects.filter(
        Q(delegate=user) | Q(authorized_by=user),
        revoked_at__isnull=True, expires_at__gt=now,
    ).update(
        revoked_at=now,
        revoked_by=actor if getattr(actor, 'pk', None) else None,
        revocation_reason=reason,
    )
    checker = AccessControlCheckerAssignment.objects.select_for_update().filter(
        user=user, revoked_at__isnull=True,
    ).first()
    if checker:
        checker.revoked_at = now
        checker.revoked_by = actor if getattr(actor, 'pk', None) else None
        checker.revocation_reason = reason
        checker.save(update_fields=['revoked_at', 'revoked_by', 'revocation_reason'])
        _record_checker_assignment(
            checker, action='access_control.checker.revoked', actor=actor,
            before={'user_id': user.pk}, after={'user_id': user.pk, 'revoked_at': now},
            decision_mode='account_deactivation',
        )
    pending_rows = list(AccessControlChangeRequest.objects.select_for_update().filter(
        Q(requested_by=user)
        | Q(
            change_type=AccessControlChangeRequest.TYPE_GRANT,
            target_user=user,
        ),
        status=AccessControlChangeRequest.STATUS_PENDING,
    ))
    for request in pending_rows:
        request.status = AccessControlChangeRequest.STATUS_CANCELLED
        request.reviewed_by = actor if getattr(actor, 'pk', None) else None
        request.reviewed_at = now
        request.review_comment = reason
        request.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'review_comment'])
        _record_access_control_decision(
            request, action='access_control.change.cancelled_on_deactivation',
            decision_mode='account_deactivation',
        )
    return {
        'grants': len(grant_rows), 'emergency_grants': len(emergency_rows),
        'delegations': delegations, 'checker_assignments': 1 if checker else 0,
        'pending_requests': len(pending_rows),
    }


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
    if original.change_type == original.TYPE_DOCUMENT_SIGNOFF:
        before = (original.before_snapshot or {}).get('document_signoff_policy') or {}
        if not before:
            raise ValidationError('This policy did not have an earlier value to restore.')
        return create_document_signoff_policy_request(
            requester=requester,
            document_type=before['document_type'],
            approval_role=before['approval_role'],
            approval_roles=before.get('approval_roles') or [before['approval_role']],
            reason=reason,
            source_request=original,
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
    recipients = approver_users().select_related('staff_profile')
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
