"""Ownership, branch, and presentation scope for Loan Origination."""

from __future__ import annotations

from django.db.models import Q, QuerySet

from core.services.portal_permissions import portal_access_decision
from core.services.workflow_capabilities import effective_capability_keys


FULL = 'full'
MASKED = 'masked'
DENIED = 'denied'


def _staff_signing_status(application) -> bool:
    """Staff-signing access exists only while an approved packet needs signatures."""
    return str(getattr(application, 'status', '') or '') in {
        application.STATUS_SIGNING_PENDING,
        application.STATUS_PARTIALLY_SIGNED,
    }


def _capabilities(user, access: dict | None) -> set[str]:
    if access is None:
        # Authentication-disabled local/test environments historically expose
        # the complete Portal. Production requests always carry portal_access.
        return {
            'portal.origination.view', 'portal.origination.create',
            'portal.origination.review', 'portal.origination.signing.start',
            'portal.origination.signing.staff',
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
    ).allowed for capability in {
        'portal.origination.review', 'portal.origination.signing.start',
    }):
        return FULL
    if _staff_signing_status(application) and portal_access_decision(
        user, 'portal.origination.signing.staff', access=access, resource=application,
    ).allowed:
        return FULL
    if portal_access_decision(
        user, 'portal.origination.create', access=access, resource=application,
    ).allowed:
        return FULL if application.officer_id == user.pk else DENIED
    view_decision = portal_access_decision(
        user, 'portal.origination.view', access=access, resource=application,
    )
    if view_decision.allowed:
        # BM and Management receive view as the dependency of staff signing;
        # it must not become a branch-wide masked-data browsing permission.
        if view_decision.roles and set(view_decision.roles).issubset({'BM', 'MANAGEMENT'}):
            return DENIED
        return MASKED
    return DENIED


def scope_application_queryset(queryset: QuerySet, *, user, access: dict | None) -> QuerySet:
    """Apply branch scope and owner/reviewer visibility to an application list."""
    if not user:
        return queryset.none()
    if access is None or getattr(user, 'is_superuser', False):
        return queryset
    capabilities = _capabilities(user, access)
    candidate_capabilities = capabilities.intersection({
        'portal.origination.review', 'portal.origination.signing.start',
        'portal.origination.signing.staff', 'portal.origination.create',
    })
    if not candidate_capabilities and 'portal.origination.view' in capabilities:
        candidate_capabilities = {'portal.origination.view'}
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
            elif capability == 'portal.origination.signing.staff':
                item &= Q(status__in=[
                    queryset.model.STATUS_SIGNING_PENDING,
                    queryset.model.STATUS_PARTIALLY_SIGNED,
                ])
            combined |= item
    return queryset.filter(combined).distinct()


def queue_capabilities(*, user, access: dict | None) -> dict:
    capabilities = _capabilities(user, access)
    from core.services.origination_esign import STAFF_SIGNER_ACCESS_ROLES

    access_roles = {
        str(role or '').strip().upper() for role in (access or {}).get('roles', [])
    }
    if access is None or getattr(user, 'is_superuser', False):
        staff_signer_roles = sorted(STAFF_SIGNER_ACCESS_ROLES)
    else:
        staff_signer_roles = sorted(
            signer_role for signer_role, allowed_roles in STAFF_SIGNER_ACCESS_ROLES.items()
            if allowed_roles.intersection(access_roles)
        )
    return {
        'user_id': getattr(user, 'pk', None),
        'is_superuser': bool(getattr(user, 'is_superuser', False)),
        'can_create': 'portal.origination.create' in capabilities,
        'can_review': 'portal.origination.review' in capabilities,
        'can_start_signing': 'portal.origination.signing.start' in capabilities,
        'can_staff_sign': 'portal.origination.signing.staff' in capabilities,
        'staff_signer_roles': staff_signer_roles,
    }
