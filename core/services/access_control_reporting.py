"""Auditor-facing exports and non-mutating access-control diagnostics."""
from __future__ import annotations

import csv
from io import StringIO
from datetime import timedelta

from django.template.loader import render_to_string
from django.utils import timezone

from core.models import AccessControlChangeRequest, AccessControlPolicySnapshot, AccessGrant, CapabilityUsageDaily, WorkflowRoleCapability
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
        roles = set(AccessGrant.objects.filter(workflow=workflow).values_list('role', flat=True))
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
    return {'missing_policy_rows': missing, 'baseline_drift': baseline_drift, 'ok': not missing}
