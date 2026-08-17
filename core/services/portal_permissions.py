"""Compatibility mapping from established portal actions to capability keys.

The persisted role matrix is the authorization source of truth.  Keeping the
older endpoint action names here lets the portal migrate one route at a time
without duplicating the policy in every view.
"""

from __future__ import annotations

from dataclasses import dataclass

PORTAL_ACTION_CAPABILITIES: dict[str, str] = {
    'read': 'portal.case.read',
    'dashboard.view': 'portal.dashboard.view',
    'health.read': 'portal.health.read',
    'jbl_visit.write': 'portal.jbl_visit.write',
    'credit.write': 'portal.credit.write',
    'final_review.write': 'portal.final_review.write',
    'requisition.write': 'portal.requisition.write',
    'invoice.write': 'portal.invoice.write',
    'invoice_identity.manage': 'portal.invoice_identity.manage',
    'payment.review': 'portal.payment.review',
}


@dataclass(frozen=True)
class PortalAccessDecision:
    """One capability decision derived from complete, non-composed grants.

    A role and its branch/product scope must come from the same grant.  This
    prevents a branch-specific role from borrowing a different grant's wider
    scope (the classic roles x scopes privilege-expansion bug).
    """

    allowed: bool
    capability: str
    roles: tuple[str, ...] = ()
    grant_ids: tuple[str, ...] = ()
    technical_override: bool = False


def portal_access_decision(
    user,
    capability: str,
    *,
    access: dict | None,
    resource=None,
    branch: str = '',
    product: str = '',
    group_configuration=None,
    enforce_group_scope: bool = False,
) -> PortalAccessDecision:
    """Resolve a Portal capability without flattening independent grants."""
    from core.services.workflow_access import workflow_access_decision
    decision = workflow_access_decision(
        user, 'jawabu_portal', capability, access=access, resource=resource,
        branch=branch, product=product,
        group_configuration=group_configuration if enforce_group_scope else None,
    )
    return PortalAccessDecision(
        decision.allowed, capability, roles=decision.roles,
        grant_ids=decision.grant_ids, technical_override=decision.technical_override,
    )


def portal_capability_scope(user, capability: str, *, access: dict | None) -> dict:
    """Return effective scopes for UI/filtering; never use cross-product lists."""
    from core.services.workflow_access import workflow_capability_scope
    base = workflow_capability_scope(user, 'jawabu_portal', capability, access=access)
    assignments = base['assignments']
    return {
        'allowed': base['allowed'],
        'global_branch': any(not item['branch'] for item in assignments),
        'branches': sorted({item['branch'] for item in assignments if item['branch']}),
        'global_product': any(not item['product'] for item in assignments),
        'products': sorted({item['product'] for item in assignments if item['product']}),
        'assignments': assignments,
    }


def scope_portal_case_queryset(queryset, user, capability: str, *, access: dict | None):
    """OR complete grant tuples when scoping canonical Portal case rows."""
    from core.services.workflow_access import scope_workflow_queryset
    return scope_workflow_queryset(
        queryset, user, 'jawabu_portal', capability, access=access,
        branch_field='branch', product_field='product__code',
    )


def portal_action_capability(action: str) -> str:
    """Return the reviewed capability for an old action key, failing closed."""
    return PORTAL_ACTION_CAPABILITIES.get(str(action or '').strip(), '')


def portal_action_roles(action: str) -> frozenset[str]:
    """Legacy inspection helper; authorization must use capabilities instead."""
    from core.services.workflow_capabilities import capability_definition

    capability = portal_action_capability(action)
    definition = capability_definition('jawabu_portal', capability)
    return definition.default_roles if definition else frozenset()


# Kept as a read-only compatibility export for integrations/tests that used
# this constant before the matrix was introduced.
PORTAL_ACTION_ROLES = {
    action: portal_action_roles(action)
    for action in PORTAL_ACTION_CAPABILITIES
}
