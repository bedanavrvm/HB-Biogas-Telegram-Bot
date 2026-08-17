"""Compatibility mapping from established portal actions to capability keys.

The persisted role matrix is the authorization source of truth.  Keeping the
older endpoint action names here lets the portal migrate one route at a time
without duplicating the policy in every view.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Q


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


def _normalized(value) -> str:
    return str(value or '').strip().casefold()


def _resource_product(resource) -> str:
    product = getattr(resource, 'product', None)
    if product is not None and not isinstance(product, str):
        return _normalized(getattr(product, 'code', '') or getattr(product, 'name', ''))
    return _normalized(
        getattr(resource, 'product_key', '')
        or getattr(resource, 'payment_product', '')
        or product
    )


def _allowed_roles_for_capability(workflow: str, capability: str, roles) -> set[str]:
    from core.models import WorkflowRoleCapability

    normalized_roles = {_normalized(role).upper() for role in roles if _normalized(role)}
    if not normalized_roles:
        return set()
    return set(WorkflowRoleCapability.objects.filter(
        workflow=workflow,
        role__in=normalized_roles,
        capability_key=capability,
        effect=WorkflowRoleCapability.EFFECT_ALLOW,
    ).values_list('role', flat=True))


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
    from core.services.workflow_capabilities import capability_definition

    if not user or not getattr(user, 'is_active', False):
        return PortalAccessDecision(False, capability)
    if capability_definition('jawabu_portal', capability) is None:
        return PortalAccessDecision(False, capability)
    if getattr(user, 'is_superuser', False):
        return PortalAccessDecision(True, capability, technical_override=True)
    if access is None:
        # Authentication-disabled mode is retained for isolated local tests.
        return PortalAccessDecision(True, capability)

    grants = list((access or {}).get('grants') or [])
    allowed_roles = _allowed_roles_for_capability(
        'jawabu_portal', capability, [getattr(grant, 'role', '') for grant in grants],
    )
    resource_branch = _normalized(branch or getattr(resource, 'branch', ''))
    resource_product = _normalized(product) or (_resource_product(resource) if resource is not None else '')
    resource_group_id = getattr(group_configuration, 'pk', group_configuration)
    matching = []
    for grant in grants:
        role = str(getattr(grant, 'role', '') or '').strip().upper()
        if role not in allowed_roles:
            continue
        grant_branch = _normalized(getattr(grant, 'branch', ''))
        if resource_branch and grant_branch and grant_branch != resource_branch:
            continue
        if grant_branch and not resource_branch and resource is not None:
            # A branch-scoped grant cannot authorize an unclassified case.
            # The record must first be assigned a canonical/legacy branch or
            # handled by a genuinely all-branch grant.
            continue
        grant_product = _normalized(getattr(grant, 'product', ''))
        if resource_product and grant_product and grant_product != resource_product:
            # Canonical product grants store codes. A legacy resource may only
            # expose a display name; fail closed rather than guessing aliases.
            continue
        if grant_product and not resource_product and resource is not None:
            continue
        if enforce_group_scope:
            grant_group_id = getattr(grant, 'group_configuration_id', None)
            if grant_group_id and str(grant_group_id) != str(resource_group_id or ''):
                continue
        matching.append(grant)
    return PortalAccessDecision(
        bool(matching), capability,
        roles=tuple(sorted({str(getattr(item, 'role', '') or '').strip().upper() for item in matching})),
        grant_ids=tuple(str(getattr(item, 'pk', '')) for item in matching),
    )


def portal_capability_scope(user, capability: str, *, access: dict | None) -> dict:
    """Return effective scopes for UI/filtering; never use cross-product lists."""
    if not user or not getattr(user, 'is_active', False):
        return {'allowed': False, 'global_branch': False, 'branches': [], 'global_product': False, 'products': [], 'assignments': []}
    if getattr(user, 'is_superuser', False) or access is None:
        return {
            'allowed': True, 'global_branch': True, 'branches': [],
            'global_product': True, 'products': [],
            'assignments': [{'role': 'TECHNICAL_OVERRIDE' if user else 'LOCAL_MODE', 'branch': '', 'product': '', 'group_configuration_id': None}],
        }
    grants = list((access or {}).get('grants') or [])
    allowed_roles = _allowed_roles_for_capability(
        'jawabu_portal', capability, [getattr(grant, 'role', '') for grant in grants],
    )
    matching = [
        grant for grant in grants
        if str(getattr(grant, 'role', '') or '').strip().upper() in allowed_roles
    ]
    return {
        'allowed': bool(matching),
        'global_branch': any(not _normalized(getattr(grant, 'branch', '')) for grant in matching),
        'branches': sorted({str(getattr(grant, 'branch', '') or '').strip() for grant in matching if _normalized(getattr(grant, 'branch', ''))}),
        'global_product': any(not _normalized(getattr(grant, 'product', '')) for grant in matching),
        'products': sorted({str(getattr(grant, 'product', '') or '').strip() for grant in matching if _normalized(getattr(grant, 'product', ''))}),
        'assignments': [
            {
                'role': str(getattr(grant, 'role', '') or '').strip().upper(),
                'branch': str(getattr(grant, 'branch', '') or '').strip(),
                'product': str(getattr(grant, 'product', '') or '').strip(),
                'group_configuration_id': getattr(grant, 'group_configuration_id', None),
            }
            for grant in matching
        ],
    }


def scope_portal_case_queryset(queryset, user, capability: str, *, access: dict | None):
    """OR complete grant tuples when scoping canonical Portal case rows."""
    if access is None or (user and getattr(user, 'is_superuser', False)):
        return queryset
    grants = list((access or {}).get('grants') or [])
    allowed_roles = _allowed_roles_for_capability(
        'jawabu_portal', capability, [getattr(grant, 'role', '') for grant in grants],
    )
    scope = Q(pk__in=[])
    for grant in grants:
        if str(getattr(grant, 'role', '') or '').strip().upper() not in allowed_roles:
            continue
        if not getattr(grant, 'branch', '') and not getattr(grant, 'product', ''):
            return queryset
        item = Q()
        if getattr(grant, 'branch', ''):
            item &= Q(branch__iexact=grant.branch)
        if getattr(grant, 'product', ''):
            item &= Q(product__code__iexact=grant.product)
        scope |= item
    return queryset.filter(scope).distinct()


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
