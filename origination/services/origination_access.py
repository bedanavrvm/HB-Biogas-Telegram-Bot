"""Complete grant tuples and ownership rules for the independent Mini App."""
from django.db.models import Q
from core.services.workflow_access import (
    workflow_access_decision, workflow_capability_scope, scope_workflow_queryset,
)
from core.services.workflow_capabilities import effective_capability_keys

FULL, MASKED, DENIED = 'full', 'masked', 'denied'
WORKFLOW = 'loan_origination'


def _capabilities(user, access):
    return effective_capability_keys(user, WORKFLOW, access=access)


def authorized_branches(user, access, capability='origination.view'):
    from core.services.workflow_catalog import workflow_branch_names
    configured = workflow_branch_names(WORKFLOW)
    scope = workflow_capability_scope(user, WORKFLOW, capability, access=access)
    assignments = scope['assignments']
    if not scope['allowed']:
        return []
    if any(not item['branch'] for item in assignments):
        return configured
    names = {item['branch'].casefold() for item in assignments}
    return [item for item in configured if item.casefold() in names]


def _staff_signing_status(application):
    return application.status in {application.STATUS_SIGNING_PENDING, application.STATUS_PARTIALLY_SIGNED}


def application_presentation_mode(application, *, user, access):
    if not user or not user.is_active:
        return DENIED
    def decision(key):
        return workflow_access_decision(user, WORKFLOW, key, access=access, resource=application)
    if any(decision(key).allowed for key in ('origination.review', 'origination.signing.start')):
        return FULL
    if _staff_signing_status(application) and decision('origination.signing.staff').allowed:
        return FULL
    if decision('origination.create').allowed:
        return FULL if application.officer_id == user.pk else DENIED
    view = decision('origination.view')
    if view.allowed and not (view.roles and set(view.roles).issubset({'BM', 'MANAGEMENT', 'CA'})):
        return MASKED
    return DENIED


def scope_application_queryset(queryset, *, user, access):
    if not user or not user.is_active:
        return queryset.none()
    visible = Q(pk__in=[])
    for capability in _capabilities(user, access):
        if capability not in {'origination.view', 'origination.create', 'origination.review',
                              'origination.signing.start', 'origination.signing.staff'}:
            continue
        scoped = scope_workflow_queryset(
            queryset, user, WORKFLOW, capability, access=access, branch_field='branch',
            product_field='product_version__product__code', group_field='group_configuration__group_id',
        )
        if capability == 'origination.create':
            scoped = scoped.filter(officer=user)
        elif capability == 'origination.signing.staff':
            scoped = scoped.filter(status__in=[queryset.model.STATUS_SIGNING_PENDING,
                                               queryset.model.STATUS_PARTIALLY_SIGNED])
        elif capability == 'origination.view':
            # Presentation rules below decide whether this grant actually exposes a row.
            continue
        visible |= Q(pk__in=scoped.values('pk'))
    # An independent view-only policy may expose a masked record. Filter each
    # candidate through the same complete-tuple decision used by detail views.
    view_rows = scope_workflow_queryset(
        queryset, user, WORKFLOW, 'origination.view', access=access, branch_field='branch',
        product_field='product_version__product__code', group_field='group_configuration__group_id',
    )
    # Avoid materialising customer data or doing a per-row authorization query.
    from core.services.workflow_access import matching_capability_grants
    if access is None or user.is_superuser:
        return queryset
    safe_grants = [g for g in matching_capability_grants(WORKFLOW, 'origination.view', access=access)
                   if g.role not in {'JBL_OFFICER', 'BM', 'MANAGEMENT', 'CA'}]
    if safe_grants:
        view_rows = scope_workflow_queryset(
            view_rows, user, WORKFLOW, 'origination.view', access={'grants': safe_grants},
            branch_field='branch', product_field='product_version__product__code',
            group_field='group_configuration__group_id',
        )
        visible |= Q(pk__in=view_rows.values('pk'))
    return queryset.filter(visible).distinct()


def queue_capabilities(*, user, access: dict | None) -> dict:
    capabilities = _capabilities(user, access)
    from origination.services.origination_esign import STAFF_SIGNER_ACCESS_ROLES

    access_roles = {
        str(role or '').strip().upper() for role in (access or {}).get('roles', [])
    }
    if (
        access is None
        or getattr(user, 'is_superuser', False)
        or 'IT' in access_roles
    ):
        staff_signer_roles = sorted(STAFF_SIGNER_ACCESS_ROLES)
    else:
        staff_signer_roles = sorted(
            signer_role for signer_role, allowed_roles in STAFF_SIGNER_ACCESS_ROLES.items()
            if allowed_roles.intersection(access_roles)
        )
    from origination.services.origination_consent import conditional_approval_enabled
    return {
        'user_id': getattr(user, 'pk', None),
        'is_superuser': bool(getattr(user, 'is_superuser', False)),
        'can_create': 'origination.create' in capabilities,
        'can_review': 'origination.review' in capabilities,
        'can_start_signing': 'origination.signing.start' in capabilities,
        'can_staff_sign': 'origination.signing.staff' in capabilities,
        'conditional_approval_enabled': conditional_approval_enabled(),
        'can_confirm_signing': (
            conditional_approval_enabled() and 'origination.create' in capabilities
        ),
        'staff_signer_roles': staff_signer_roles,
    }
