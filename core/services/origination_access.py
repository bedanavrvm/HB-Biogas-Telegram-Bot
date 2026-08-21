"""Ownership, branch, and presentation scope for Loan Origination."""

from __future__ import annotations

from django.db.models import Q, QuerySet

from core.services.portal_permissions import portal_access_decision
from core.services.workflow_capabilities import effective_capability_keys


FULL = 'full'
MASKED = 'masked'
DENIED = 'denied'


def _capabilities(user, access: dict | None) -> set[str]:
    if access is None:
        # Authentication-disabled local/test environments historically expose
        # the complete Portal. Production requests always carry portal_access.
        return {
            'portal.origination.view', 'portal.origination.create',
            'portal.origination.review', 'portal.origination.signing.start',
        }
    return effective_capability_keys(user, 'jawabu_portal', access=access)


def authorized_branches(user, access: dict | None, capability: str = 'portal.origination.view') -> list[str]:
    from core.services.branches import global_branch_choices

    configured = global_branch_choices()
    if access is None or getattr(user, 'is_superuser', False):
        return configured
    from core.services.portal_permissions import portal_capability_scope

    scope = portal_capability_scope(user, capability, access=access)
    if not scope['allowed']:
        return []
    granted = {str(value).strip().casefold() for value in scope['branches']}
    return configured if scope['global_branch'] else [
        branch for branch in configured if branch.casefold() in granted
    ]


def _branch_allowed(application, user, access: dict | None) -> bool:
    if access is None or getattr(user, 'is_superuser', False):
        return True
    branches = {
        str(value).strip().casefold()
        for value in (access or {}).get('branches', [])
        if str(value).strip()
    }
    return not branches or str(application.branch or '').strip().casefold() in branches


def application_presentation_mode(application, *, user, access: dict | None) -> str:
    """Return full, masked, or denied for one already-authenticated actor."""
    if not user:
        return DENIED
    if access is None or getattr(user, 'is_superuser', False):
        return FULL
    if any(portal_access_decision(
        user, capability, access=access, resource=application,
    ).allowed for capability in {'portal.origination.review', 'portal.origination.signing.start'}):
        return FULL
    if portal_access_decision(
        user, 'portal.origination.create', access=access, resource=application,
    ).allowed:
        return FULL if application.officer_id == user.pk else DENIED
    if portal_access_decision(
        user, 'portal.origination.view', access=access, resource=application,
    ).allowed:
        return MASKED
    return DENIED


def scope_application_queryset(queryset: QuerySet, *, user, access: dict | None) -> QuerySet:
    """Apply branch scope and owner/reviewer visibility to an application list."""
    if not user:
        return queryset.none()
    if access is None or getattr(user, 'is_superuser', False):
        return queryset
    capabilities = _capabilities(user, access)
    elevated = capabilities.intersection({
        'portal.origination.review', 'portal.origination.signing.start',
    })
    if elevated:
        candidate_capabilities = elevated
    elif 'portal.origination.create' in capabilities:
        # View is a dependency of create, not permission to browse another
        # officer's applications. Ownership stays part of the create scope.
        candidate_capabilities = {'portal.origination.create'}
    else:
        candidate_capabilities = capabilities.intersection({'portal.origination.view'})
    if not candidate_capabilities:
        return queryset.none()

    from core.models import WorkflowRoleCapability

    grants = list((access or {}).get('grants') or [])
    roles = [str(getattr(item, 'role', '') or '').strip().upper() for item in grants]
    policy_rows = WorkflowRoleCapability.objects.filter(
        workflow='jawabu_portal', capability_key__in=candidate_capabilities,
        effect=WorkflowRoleCapability.EFFECT_ALLOW, role__in=roles,
    ).values_list('role', 'capability_key')
    roles_by_capability: dict[str, set[str]] = {}
    for role, capability in policy_rows:
        roles_by_capability.setdefault(capability, set()).add(role)

    combined = Q(pk__in=[])
    for capability, allowed_roles in roles_by_capability.items():
        for grant in grants:
            if str(getattr(grant, 'role', '') or '').strip().upper() not in allowed_roles:
                continue
            item = Q()
            if getattr(grant, 'branch', ''):
                item &= Q(branch__iexact=grant.branch)
            if getattr(grant, 'product', ''):
                item &= Q(product_version__product__code__iexact=grant.product)
            if capability == 'portal.origination.create':
                item &= Q(officer=user)
            combined |= item
    return queryset.filter(combined).distinct()


def queue_capabilities(*, user, access: dict | None) -> dict:
    capabilities = _capabilities(user, access)
    return {
        'user_id': getattr(user, 'pk', None),
        'is_superuser': bool(getattr(user, 'is_superuser', False)),
        'can_create': 'portal.origination.create' in capabilities,
        'can_review': 'portal.origination.review' in capabilities,
        'can_start_signing': 'portal.origination.signing.start' in capabilities,
    }
