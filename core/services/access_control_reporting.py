"""Auditor-facing exports and non-mutating access-control diagnostics."""
from __future__ import annotations

import csv
from io import StringIO
from datetime import timedelta

from django.template.loader import render_to_string
from django.utils import timezone

from core.models import (
    AccessControlChangeRequest, AccessControlPolicySnapshot, AccessGrant,
    CapabilityUsageDaily, EmergencyAccessGrant, WorkflowRoleCapability,
)
from core.services.access_policies import WORKFLOW_ROLES
from core.services.workflow_capabilities import capabilities_for_workflow


def evidence_rows(limit: int = 1000) -> list[list[str]]:
    rows = [['Section', 'Workflow', 'Role', 'Subject', 'State', 'At', 'Actor', 'Detail']]
    for item in WorkflowRoleCapability.objects.order_by('workflow', 'role', 'capability_key'):
        rows.append(['Capability matrix', item.workflow, item.role, item.capability_key, item.effect, item.updated_at.isoformat(), '', ''])
    for grant in AccessGrant.objects.select_related('user').order_by('workflow', 'role', 'user__username'):
        rows.append(['Approved staff grant', grant.workflow, grant.role, grant.user.get_username(), 'active' if grant.active else 'inactive', grant.updated_at.isoformat(), '', f'branch={grant.branch or "all"}; product={grant.product or "all"}'])
    for request in AccessControlChangeRequest.objects.select_related('requested_by', 'reviewed_by', 'target_user').order_by('-requested_at')[:limit]:
        rows.append(['Change request', request.workflow, request.role, request.target_user.get_username() if request.target_user else '', request.status, request.requested_at.isoformat(), request.requested_by.get_username(), request.reason])
    return rows


def evidence_csv(limit: int = 1000) -> str:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerows(evidence_rows(limit))
    return output.getvalue()


def evidence_pdf(limit: int = 1000) -> bytes:
    """Render a compact control report; imported lazily for non-PDF installs."""
    from weasyprint import HTML

    html = render_to_string('admin/core/access_control_evidence.html', {
        'generated_at': timezone.localtime(), 'rows': evidence_rows(limit)[1:],
    })
    return HTML(string=html).write_pdf()


def unused_capabilities(days: int = 90) -> list[dict]:
    threshold = timezone.now() - timedelta(days=days)
    used = set(CapabilityUsageDaily.objects.filter(last_used_at__gte=threshold).values_list('workflow', 'capability_key'))
    return [
        {'workflow': workflow, 'capability_key': definition.key, 'label': definition.label}
        for workflow in {item.workflow for item in WorkflowRoleCapability.objects.all()}
        for definition in capabilities_for_workflow(workflow)
        if (workflow, definition.key) not in used
    ]


def parity_report() -> dict:
    missing = []
    for workflow in {choice[0] for choice in AccessGrant.WORKFLOW_CHOICES}:
        rows = set(WorkflowRoleCapability.objects.filter(workflow=workflow).values_list('role', 'capability_key'))
        roles = {role for role, _label in WORKFLOW_ROLES.get(workflow, ())}
        for role in roles:
            for definition in capabilities_for_workflow(workflow):
                if (role, definition.key) not in rows:
                    missing.append({'workflow': workflow, 'role': role, 'capability_key': definition.key})
    baseline = AccessControlPolicySnapshot.objects.order_by('version').first()
    baseline_rows = {
        (row['workflow'], row['role'], row['capability_key']): row['effect']
        for row in ((baseline.state if baseline else {}).get('capabilities') or [])
    }
    current_rows = {
        (row['workflow'], row['role'], row['capability_key']): row['effect']
        for row in WorkflowRoleCapability.objects.values('workflow', 'role', 'capability_key', 'effect')
    }
    baseline_drift = [
        {'workflow': key[0], 'role': key[1], 'capability_key': key[2], 'baseline': effect, 'current': current_rows.get(key, 'missing')}
        for key, effect in baseline_rows.items() if current_rows.get(key) != effect
    ]
    known_roles = {
        workflow: {role for role, _label in roles}
        for workflow, roles in WORKFLOW_ROLES.items()
    }
    invalid_grants = []
    inactive_user_grants = []
    active_grants = list(AccessGrant.objects.select_related('user').filter(active=True))
    for grant in active_grants:
        if grant.role not in known_roles.get(grant.workflow, set()):
            invalid_grants.append({'grant_id': str(grant.pk), 'workflow': grant.workflow, 'role': grant.role})
        if not grant.user.is_active:
            inactive_user_grants.append({'grant_id': str(grant.pk), 'user_id': grant.user_id})

    invalid_policy_rows = []
    effect_mismatches = []
    dependency_violations = []
    rows_by_role: dict[tuple[str, str], dict[str, str]] = {}
    definitions_by_workflow = {
        workflow: {item.key: item for item in capabilities_for_workflow(workflow)}
        for workflow in WORKFLOW_ROLES
    }
    for row in WorkflowRoleCapability.objects.all():
        definition = definitions_by_workflow.get(row.workflow, {}).get(row.capability_key)
        if row.role not in known_roles.get(row.workflow, set()) or definition is None:
            invalid_policy_rows.append({
                'workflow': row.workflow, 'role': row.role,
                'capability_key': row.capability_key,
            })
            continue
        if row.enabled != (row.effect == WorkflowRoleCapability.EFFECT_ALLOW):
            effect_mismatches.append({
                'workflow': row.workflow, 'role': row.role,
                'capability_key': row.capability_key,
            })
        rows_by_role.setdefault((row.workflow, row.role), {})[row.capability_key] = row.effect
    for (workflow, role), effects in rows_by_role.items():
        for capability_key, effect in effects.items():
            if effect != WorkflowRoleCapability.EFFECT_ALLOW:
                continue
            definition = definitions_by_workflow[workflow][capability_key]
            missing_dependencies = [
                required for required in definition.requires
                if effects.get(required) != WorkflowRoleCapability.EFFECT_ALLOW
            ]
            if missing_dependencies:
                dependency_violations.append({
                    'workflow': workflow, 'role': role,
                    'capability_key': capability_key,
                    'missing': missing_dependencies,
                })

    redundant_grants = []
    by_subject: dict[tuple, list] = {}
    for grant in active_grants:
        by_subject.setdefault((grant.user_id, grant.workflow, grant.role), []).append(grant)
    for (user_id, workflow, role), grants in by_subject.items():
        for grant in grants:
            broader = next((candidate for candidate in grants if candidate.pk != grant.pk
                and (not candidate.branch or candidate.branch.casefold() == grant.branch.casefold())
                and (not candidate.product or candidate.product.casefold() == grant.product.casefold())
                and (not candidate.group_configuration_id or candidate.group_configuration_id == grant.group_configuration_id)
            ), None)
            if broader:
                redundant_grants.append({
                    'grant_id': str(grant.pk), 'covered_by': str(broader.pk),
                    'user_id': user_id, 'workflow': workflow, 'role': role,
                })

    now = timezone.now()
    emergency_on_inactive_users = [
        {'grant_id': str(item.pk), 'user_id': item.user_id}
        for item in EmergencyAccessGrant.objects.select_related('user').filter(
            revoked_at__isnull=True, expires_at__gt=now, user__is_active=False,
        )
    ]
    pending_self_conflicts = []
    for request in AccessControlChangeRequest.objects.filter(
        status=AccessControlChangeRequest.STATUS_PENDING,
    ).select_related('requested_by', 'target_user'):
        if request.change_type == request.TYPE_GRANT and request.target_user_id == request.requested_by_id:
            pending_self_conflicts.append({'request_id': str(request.pk), 'type': 'own_grant'})
        elif request.change_type == request.TYPE_CAPABILITY:
            roles = request.target_roles or [request.role]
            if AccessGrant.objects.filter(
                user=request.requested_by, workflow=request.workflow,
                role__in=roles, active=True,
            ).exists():
                pending_self_conflicts.append({'request_id': str(request.pk), 'type': 'own_role_policy'})

    problem_keys = (
        'missing_policy_rows', 'invalid_grants', 'inactive_user_grants',
        'invalid_policy_rows', 'effect_mismatches', 'dependency_violations',
        'emergency_on_inactive_users', 'pending_self_conflicts',
    )
    report = {
        'missing_policy_rows': missing,
        'baseline_drift': baseline_drift,
        'invalid_grants': invalid_grants,
        'inactive_user_grants': inactive_user_grants,
        'invalid_policy_rows': invalid_policy_rows,
        'effect_mismatches': effect_mismatches,
        'dependency_violations': dependency_violations,
        'redundant_grants': redundant_grants,
        'emergency_on_inactive_users': emergency_on_inactive_users,
        'pending_self_conflicts': pending_self_conflicts,
    }
    report['ok'] = not any(report[key] for key in problem_keys)
    return report
