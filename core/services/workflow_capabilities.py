"""Controlled Mini App capability catalogue and effective-access resolver.

The catalogue deliberately lives in code: endpoints and UI modules need stable,
reviewable capability keys.  Administrators may change which *existing role*
receives each capability through ``WorkflowRoleCapability``; they cannot invent
an unguarded capability or a role that the workflow does not understand.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable


@dataclass(frozen=True)
class CapabilityDefinition:
    key: str
    workflow: str
    label: str
    module: str
    default_roles: frozenset[str]
    requires: tuple[str, ...] = ()


def _roles(*roles: str) -> frozenset[str]:
    return frozenset(roles)


_STATIC_CAPABILITIES: tuple[CapabilityDefinition, ...] = (
    # Jawabu Portal: a view capability owns a screen; write capabilities own
    # consequential actions on that screen.
    CapabilityDefinition('portal.dashboard.view', 'jawabu_portal', 'View dashboard', 'Dashboard', _roles('JBL_OFFICER', 'CREDIT_ANALYST', 'HB_STAFF', 'ADMIN')),
    CapabilityDefinition('portal.case.read', 'jawabu_portal', 'View all cases and case history', 'Cases', _roles('JBL_OFFICER', 'CREDIT_ANALYST', 'HB_STAFF', 'ADMIN')),
    CapabilityDefinition('portal.deferred.view', 'jawabu_portal', 'View deferred cases', 'Cases', _roles('JBL_OFFICER', 'CREDIT_ANALYST', 'HB_STAFF', 'ADMIN'), ('portal.case.read',)),
    CapabilityDefinition('portal.jbl_queue.view', 'jawabu_portal', 'View JBL visit queue', 'JBL visit', _roles('JBL_OFFICER', 'ADMIN')),
    CapabilityDefinition('portal.jbl_visit.write', 'jawabu_portal', 'Log JBL visit', 'JBL visit', _roles('JBL_OFFICER', 'ADMIN'), ('portal.jbl_queue.view',)),
    CapabilityDefinition('portal.jbl_media.view', 'jawabu_portal', 'View JBL visit media', 'JBL visit', _roles('JBL_OFFICER', 'ADMIN'), ('portal.jbl_queue.view',)),
    CapabilityDefinition('portal.jbl_media.write', 'jawabu_portal', 'Upload JBL visit media', 'JBL visit', _roles('JBL_OFFICER', 'ADMIN'), ('portal.jbl_queue.view',)),
    CapabilityDefinition('portal.credit_queue.view', 'jawabu_portal', 'View credit queue', 'Credit', _roles('CREDIT_ANALYST', 'ADMIN')),
    CapabilityDefinition('portal.credit.write', 'jawabu_portal', 'Record credit analysis', 'Credit', _roles('CREDIT_ANALYST', 'ADMIN'), ('portal.credit_queue.view',)),
    CapabilityDefinition('portal.final_review.view', 'jawabu_portal', 'View Head of Rural review', 'Review', _roles('ADMIN')),
    CapabilityDefinition('portal.final_review.write', 'jawabu_portal', 'Record final and payment review', 'Review', _roles('ADMIN'), ('portal.final_review.view',)),
    CapabilityDefinition('portal.requisition.view', 'jawabu_portal', 'View requisition queue', 'Orders', _roles('HB_STAFF', 'ADMIN')),
    CapabilityDefinition('portal.requisition.write', 'jawabu_portal', 'Assign orders and generate requisitions', 'Orders', _roles('HB_STAFF', 'ADMIN'), ('portal.requisition.view',)),
    CapabilityDefinition('portal.batches.view', 'jawabu_portal', 'View requisition batches', 'Orders', _roles('HB_STAFF', 'ADMIN')),
    CapabilityDefinition('portal.invoice.view', 'jawabu_portal', 'View invoices', 'Invoices', _roles('HB_STAFF', 'ADMIN')),
    CapabilityDefinition('portal.invoice.write', 'jawabu_portal', 'Upload, match, and edit invoices', 'Invoices', _roles('HB_STAFF', 'CREDIT_ANALYST', 'ADMIN'), ('portal.invoice.view',)),
    CapabilityDefinition('portal.payment.view', 'jawabu_portal', 'View payment workspace', 'Payments', _roles('HB_STAFF', 'ADMIN')),
    CapabilityDefinition('portal.payment.prepare', 'jawabu_portal', 'Prepare payment batch', 'Payments', _roles('HB_STAFF', 'ADMIN'), ('portal.payment.view',)),
    CapabilityDefinition('portal.payment.review', 'jawabu_portal', 'Approve payment review', 'Payments', _roles('ADMIN'), ('portal.payment.view',)),
    CapabilityDefinition('portal.approval.delegation.authorize', 'jawabu_portal', 'Authorize temporary approval delegation', 'Review controls', _roles('ADMIN'), ('portal.case.read',)),
    CapabilityDefinition('portal.documents.view', 'jawabu_portal', 'View generated documents', 'Documents', _roles('HB_STAFF', 'ADMIN')),
    CapabilityDefinition('portal.documents.regenerate', 'jawabu_portal', 'Regenerate generated documents', 'Documents', _roles('HB_STAFF', 'ADMIN'), ('portal.documents.view',)),
    CapabilityDefinition('portal.documents.sign', 'jawabu_portal', 'Upload and attest physically signed documents', 'Documents', _roles('ADMIN'), ('portal.documents.view',)),
    CapabilityDefinition('portal.health.read', 'jawabu_portal', 'View workflow health', 'Operations', _roles('HB_STAFF', 'ADMIN')),
    # Complaint cases.
    CapabilityDefinition('complaint.queue.view', 'complaint_cases', 'View complaint queue', 'Cases', _roles('OFFICER', 'MANAGER')),
    CapabilityDefinition('complaint.case.create', 'complaint_cases', 'Create complaints', 'Cases', _roles('OFFICER', 'MANAGER'), ('complaint.queue.view',)),
    CapabilityDefinition('complaint.case.update', 'complaint_cases', 'Update complaints and upload evidence', 'Cases', _roles('OFFICER', 'MANAGER'), ('complaint.queue.view',)),
    CapabilityDefinition('complaint.case.manage', 'complaint_cases', 'View confidential source details and manage cases', 'Cases', _roles('MANAGER'), ('complaint.queue.view',)),
    # TAT tracker.  Individual stages are appended dynamically below.
    CapabilityDefinition('tat.home.view', 'tat_tracker', 'View TAT queue', 'Queue', _roles('BRO', 'ADMIN', 'CA', 'BM', 'SECRETARY', 'CHAIR', 'LOAN_APPROVER', 'FINANCE', 'IT', 'MANAGEMENT')),
    CapabilityDefinition('tat.case.create', 'tat_tracker', 'Create TAT cases', 'Cases', _roles('BRO', 'ADMIN', 'CA', 'BM', 'SECRETARY', 'CHAIR', 'LOAN_APPROVER', 'FINANCE', 'IT', 'MANAGEMENT'), ('tat.home.view',)),
    CapabilityDefinition('tat.case.search', 'tat_tracker', 'Search TAT cases', 'Cases', _roles('BRO', 'ADMIN', 'CA', 'BM', 'SECRETARY', 'CHAIR', 'LOAN_APPROVER', 'FINANCE', 'IT', 'MANAGEMENT'), ('tat.home.view',)),
    CapabilityDefinition('tat.case.correct', 'tat_tracker', 'Correct TAT case details', 'Cases', _roles('IT', 'ADMIN'), ('tat.home.view',)),
    CapabilityDefinition('tat.batch.upload', 'tat_tracker', 'Upload TAT case batches', 'Cases', _roles('BRO', 'IT')),
    CapabilityDefinition('tat.targets.manage', 'tat_tracker', 'Manage TAT targets', 'Settings', _roles('IT'), ('tat.home.view',)),
    # SPIN / Credit Analysis.
    CapabilityDefinition('spin.request.view', 'spin_credit_analysis', 'View SPIN requests', 'Requests', _roles('CREDIT_ANALYST', 'ADMIN')),
    CapabilityDefinition('spin.request.create', 'spin_credit_analysis', 'Create SPIN requests', 'Requests', _roles('CREDIT_ANALYST', 'ADMIN'), ('spin.request.view',)),
    CapabilityDefinition('spin.request.review', 'spin_credit_analysis', 'Review and correct SPIN requests', 'Requests', _roles('CREDIT_ANALYST', 'ADMIN'), ('spin.request.view',)),
    CapabilityDefinition('spin.request.complete', 'spin_credit_analysis', 'Complete SPIN analysis and upload reports', 'Requests', _roles('CREDIT_ANALYST', 'ADMIN'), ('spin.request.view',)),
    CapabilityDefinition('spin.batch.review', 'spin_credit_analysis', 'Resolve SPIN batch review items', 'Requests', _roles('CREDIT_ANALYST', 'ADMIN'), ('spin.request.view',)),
)


@lru_cache(maxsize=1)
def capability_definitions() -> tuple[CapabilityDefinition, ...]:
    """Return static capabilities plus the configured TAT stage catalogue."""
    definitions = list(_STATIC_CAPABILITIES)
    try:
        # Lazy import avoids a module cycle while the TAT service starts.
        from core.services.tat_tracker import PRODUCTS

        stages: dict[str, tuple[str, str]] = {}
        for product in PRODUCTS.values():
            for stage in product.stages:
                stages.setdefault(stage.key, (stage.label, stage.role))
        for stage_key, (label, role) in sorted(stages.items()):
            definitions.append(CapabilityDefinition(
                f'tat.stage.{stage_key}.update',
                'tat_tracker',
                f'Update TAT stage: {label}',
                'TAT stages',
                _roles(role, 'IT'),
                ('tat.home.view',),
            ))
    except Exception:
        # A broken optional TAT configuration must not make every other Mini
        # App permissive; known static capabilities remain available.
        pass
    return tuple(definitions)


def capability_definition(workflow: str, key: str) -> CapabilityDefinition | None:
    workflow = str(workflow or '').strip()
    key = str(key or '').strip()
    return next((item for item in capability_definitions() if item.workflow == workflow and item.key == key), None)


def capabilities_for_workflow(workflow: str) -> tuple[CapabilityDefinition, ...]:
    return tuple(item for item in capability_definitions() if item.workflow == workflow)


def default_enabled_capability_keys(workflow: str, role: str) -> set[str]:
    normalized_role = str(role or '').strip().upper()
    return {
        item.key for item in capabilities_for_workflow(workflow)
        if normalized_role in item.default_roles
    }


def dependency_closure(workflow: str, capability_keys: Iterable[str]) -> set[str]:
    """Add required screen capabilities and ignore invalid supplied keys."""
    available = {item.key: item for item in capabilities_for_workflow(workflow)}
    selected = {key for key in capability_keys if key in available}
    pending = list(selected)
    while pending:
        key = pending.pop()
        for required in available[key].requires:
            if required not in selected and required in available:
                selected.add(required)
                pending.append(required)
    return selected


def _policy_enabled_keys(workflow: str, roles: Iterable[str]) -> set[str]:
    from core.models import WorkflowRoleCapability

    normalized_roles = {str(role or '').strip().upper() for role in roles if str(role or '').strip()}
    if not normalized_roles:
        return set()
    return set(
        WorkflowRoleCapability.objects.filter(
            workflow=workflow,
            role__in=normalized_roles,
            effect=WorkflowRoleCapability.EFFECT_ALLOW,
        ).values_list('capability_key', flat=True)
    )


def effective_capability_keys(user, workflow: str, *, access: dict | None = None) -> set[str]:
    """Return policy-approved capabilities for an already scope-authorized user."""
    if not user or not user.is_active:
        return set()
    available = {item.key for item in capabilities_for_workflow(workflow)}
    if user.is_superuser:
        return available
    roles = (access or {}).get('roles') or []
    return _policy_enabled_keys(workflow, roles).intersection(available)


def has_capability(user, workflow: str, capability_key: str, *, access: dict | None = None) -> bool:
    if capability_definition(workflow, capability_key) is None:
        return False
    return capability_key in effective_capability_keys(user, workflow, access=access)


def capabilities_payload(user, workflow: str, *, access: dict | None = None) -> list[str]:
    return sorted(effective_capability_keys(user, workflow, access=access))
