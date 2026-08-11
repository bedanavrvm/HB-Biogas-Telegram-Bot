"""Compatibility mapping from established portal actions to capability keys.

The persisted role matrix is the authorization source of truth.  Keeping the
older endpoint action names here lets the portal migrate one route at a time
without duplicating the policy in every view.
"""

from __future__ import annotations


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
