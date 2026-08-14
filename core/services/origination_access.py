"""Ownership, branch, and presentation scope for Loan Origination."""

from __future__ import annotations

from django.db.models import Q, QuerySet

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


def authorized_branches(user, access: dict | None) -> list[str]:
    from core.services.branches import global_branch_choices

    configured = global_branch_choices()
    if access is None or getattr(user, 'is_superuser', False):
        return configured
    granted = {
        str(value).strip().casefold()
        for value in (access or {}).get('branches', [])
        if str(value).strip()
    }
    return [branch for branch in configured if not granted or branch.casefold() in granted]


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
    if not user or not _branch_allowed(application, user, access):
        return DENIED
    if access is None or getattr(user, 'is_superuser', False):
        return FULL
    capabilities = _capabilities(user, access)
    if capabilities & {'portal.origination.review', 'portal.origination.signing.start'}:
        return FULL
    if 'portal.origination.create' in capabilities:
        return FULL if application.officer_id == user.pk else DENIED
    if 'portal.origination.view' in capabilities:
        return MASKED
    return DENIED


def scope_application_queryset(queryset: QuerySet, *, user, access: dict | None) -> QuerySet:
    """Apply branch scope and owner/reviewer visibility to an application list."""
    if not user:
        return queryset.none()
    if access is None or getattr(user, 'is_superuser', False):
        return queryset
    branches = [
        str(value).strip() for value in (access or {}).get('branches', [])
        if str(value).strip()
    ]
    if branches:
        branch_scope = Q()
        for branch in branches:
            branch_scope |= Q(branch__iexact=branch)
        queryset = queryset.filter(branch_scope)
    capabilities = _capabilities(user, access)
    if capabilities & {'portal.origination.review', 'portal.origination.signing.start'}:
        return queryset
    if 'portal.origination.create' in capabilities:
        return queryset.filter(officer=user)
    if 'portal.origination.view' in capabilities:
        return queryset
    return queryset.none()


def queue_capabilities(*, user, access: dict | None) -> dict[str, bool]:
    capabilities = _capabilities(user, access)
    return {
        'can_create': 'portal.origination.create' in capabilities,
        'can_review': 'portal.origination.review' in capabilities,
        'can_start_signing': 'portal.origination.signing.start' in capabilities,
    }
