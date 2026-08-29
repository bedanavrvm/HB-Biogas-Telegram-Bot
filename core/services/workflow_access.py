"""Scope-aware Mini App authorization shared by every controlled workflow.

Capability policy and grant scope are evaluated together.  A decision must be
satisfied by one complete grant tuple; roles, branches, products, and Telegram
groups from separate grants are never combined.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db.models import Q, QuerySet


@dataclass(frozen=True)
class WorkflowAccessDecision:
    allowed: bool
    workflow: str
    capability: str
    roles: tuple[str, ...] = ()
    grant_ids: tuple[str, ...] = ()
    technical_override: bool = False


def _normalized(value) -> str:
    return str(value or '').strip().casefold()


def _resource_branch(resource) -> str:
    value = getattr(resource, 'branch', '') or getattr(resource, 'branch_region', '')
    if not value and isinstance(getattr(resource, 'parsed_fields', None), dict):
        value = resource.parsed_fields.get('branch', '')
    return _normalized(value)


def _resource_product(resource) -> str:
    product = getattr(resource, 'product', None)
    if product is not None and not isinstance(product, str):
        return _normalized(getattr(product, 'code', '') or getattr(product, 'name', ''))
    product_definition = getattr(resource, 'product_definition', None)
    if product_definition is not None:
        definition_product = getattr(getattr(product_definition, 'product_version', None), 'product', None)
        return _normalized(
            getattr(definition_product, 'code', '')
            or getattr(product_definition, 'product_key', '')
        )
    product_version = getattr(resource, 'product_version', None)
    if product_version is not None:
        return _normalized(getattr(getattr(product_version, 'product', None), 'code', ''))
    return _normalized(
        getattr(resource, 'product_key', '')
        or getattr(resource, 'loan_product', '')
        or getattr(resource, 'payment_product', '')
        or product
    )


def _group_values(group_configuration=None, resource=None) -> set[str]:
    value = group_configuration
    if value is None and resource is not None:
        value = getattr(resource, 'group_configuration_id', None) or getattr(resource, 'group_id', None)
    values = {
        _normalized(getattr(value, 'pk', None)),
        _normalized(getattr(value, 'group_id', None)),
        _normalized(value if isinstance(value, (str, int)) else ''),
    }
    return {item for item in values if item}


def allowed_roles_for_capability(workflow: str, capability: str, roles) -> set[str]:
    from core.models import WorkflowRoleCapability

    normalized_roles = {str(role or '').strip().upper() for role in roles if _normalized(role)}
    if not normalized_roles:
        return set()
    return set(WorkflowRoleCapability.objects.filter(
        workflow=workflow,
        role__in=normalized_roles,
        capability_key=capability,
        effect=WorkflowRoleCapability.EFFECT_ALLOW,
    ).values_list('role', flat=True))


def matching_capability_grants(
    workflow: str,
    capability: str,
    *,
    access: dict | None,
    resource=None,
    branch: str = '',
    product: str = '',
    group_configuration=None,
) -> list:
    grants = list((access or {}).get('grants') or [])
    allowed_roles = allowed_roles_for_capability(
        workflow, capability, [getattr(grant, 'role', '') for grant in grants],
    )
    requested_branch = _normalized(branch) or (_resource_branch(resource) if resource is not None else '')
    requested_product = _normalized(product) or (_resource_product(resource) if resource is not None else '')
    requested_groups = _group_values(group_configuration, resource)
    branch_context = bool(_normalized(branch)) or resource is not None
    product_context = bool(_normalized(product)) or resource is not None
    group_context = group_configuration is not None or resource is not None
    matching = []
    for grant in grants:
        role = str(getattr(grant, 'role', '') or '').strip().upper()
        if role not in allowed_roles:
            continue
        grant_branch = _normalized(getattr(grant, 'branch', ''))
        grant_product = _normalized(getattr(grant, 'product', ''))
        grant_groups = {
            _normalized(getattr(grant, 'group_configuration_id', None)),
            _normalized(getattr(getattr(grant, 'group_configuration', None), 'group_id', None)),
        }
        grant_groups.discard('')
        if branch_context and grant_branch and grant_branch != requested_branch:
            continue
        if product_context and grant_product and grant_product != requested_product:
            continue
        if group_context and grant_groups and not grant_groups.intersection(requested_groups):
            continue
        matching.append(grant)
    return matching


def workflow_access_decision(
    user,
    workflow: str,
    capability: str,
    *,
    access: dict | None,
    resource=None,
    branch: str = '',
    product: str = '',
    group_configuration=None,
) -> WorkflowAccessDecision:
    from core.services.workflow_capabilities import capability_definition

    if not user or not getattr(user, 'is_active', False):
        return WorkflowAccessDecision(False, workflow, capability)
    if capability_definition(workflow, capability) is None:
        return WorkflowAccessDecision(False, workflow, capability)
    if getattr(user, 'is_superuser', False):
        return WorkflowAccessDecision(True, workflow, capability, technical_override=True)
    if access is None:
        # Explicit authentication-disabled local/test mode only. Deployment
        # checks reject this configuration outside DEBUG.
        return WorkflowAccessDecision(True, workflow, capability)
    matching = matching_capability_grants(
        workflow, capability, access=access, resource=resource, branch=branch,
        product=product, group_configuration=group_configuration,
    )
    return WorkflowAccessDecision(
        bool(matching), workflow, capability,
        roles=tuple(sorted({str(getattr(row, 'role', '') or '').strip().upper() for row in matching})),
        grant_ids=tuple(str(getattr(row, 'pk', '')) for row in matching),
    )


def workflow_capability_scope(user, workflow: str, capability: str, *, access: dict | None) -> dict:
    if not user or not getattr(user, 'is_active', False):
        return {'allowed': False, 'assignments': []}
    if getattr(user, 'is_superuser', False) or access is None:
        return {
            'allowed': True,
            'assignments': [{
                'role': 'TECHNICAL_OVERRIDE' if user else 'LOCAL_MODE', 'branch': '',
                'product': '', 'group_configuration_id': None,
            }],
        }
    grants = matching_capability_grants(workflow, capability, access=access)
    return {
        'allowed': bool(grants),
        'assignments': [
            {
                'role': str(getattr(grant, 'role', '') or '').strip().upper(),
                'branch': str(getattr(grant, 'branch', '') or '').strip(),
                'product': str(getattr(grant, 'product', '') or '').strip(),
                'group_configuration_id': getattr(grant, 'group_configuration_id', None),
            }
            for grant in grants
        ],
    }


def scope_workflow_queryset(
    queryset: QuerySet,
    user,
    workflow: str,
    capability: str,
    *,
    access: dict | None,
    branch_field: str = '',
    product_field: str = '',
    group_field: str = '',
) -> QuerySet:
    """OR complete grants into a queryset, failing closed for scoped fields."""
    if access is None or (user and getattr(user, 'is_superuser', False)):
        return queryset
    grants = matching_capability_grants(workflow, capability, access=access)
    scope = Q(pk__in=[])
    for grant in grants:
        item = Q()
        restricted = False
        if getattr(grant, 'branch', ''):
            if not branch_field:
                continue
            item &= Q(**{f'{branch_field}__iexact': grant.branch})
            restricted = True
        if getattr(grant, 'product', ''):
            if not product_field:
                continue
            item &= Q(**{f'{product_field}__iexact': grant.product})
            restricted = True
        if getattr(grant, 'group_configuration_id', None):
            if not group_field:
                continue
            group_value = getattr(grant.group_configuration, 'group_id', '')
            item &= Q(**{f'{group_field}__iexact': group_value})
            restricted = True
        if not restricted:
            # An allowed grant with no branch, product, or group restriction
            # is an intentional wildcard. ``Q(impossible) | Q()`` does not
            # reliably express that in Django, so return the already-bounded
            # workflow queryset explicitly.
            return queryset
        scope |= item
    return queryset.filter(scope).distinct()


# Executable inventory for route-guard coverage tests and security review.
# Keys are Django view function names, not user-facing navigation entries.
MINIAPP_ENDPOINT_CAPABILITIES = {
    'complaint_cases_bootstrap': ('complaint_cases', 'complaint.queue.view'),
    'complaint_cases_settings_personal': ('complaint_cases', 'complaint.queue.view'),
    'complaint_cases_list': ('complaint_cases', 'complaint.queue.view'),
    'complaint_cases_list_fragment': ('complaint_cases', 'complaint.queue.view'),
    'complaint_cases_create': ('complaint_cases', 'complaint.case.create'),
    'complaint_cases_detail': ('complaint_cases', 'complaint.queue.view'),
    'complaint_cases_update': ('complaint_cases', 'complaint.case.update'),
    'complaint_cases_evidence_access': ('complaint_cases', 'complaint.case.evidence.view'),
    'complaint_cases_sync_retry': ('complaint_cases', 'complaint.case.sync.retry'),
    'tat_tracker_bootstrap': ('tat_tracker', 'tat.home.view'),
    'tat_tracker_home': ('tat_tracker', 'tat.home.view'),
    'tat_tracker_home_fragment': ('tat_tracker', 'tat.home.view'),
    'tat_tracker_search': ('tat_tracker', 'tat.case.search'),
    'tat_tracker_search_fragment': ('tat_tracker', 'tat.case.search'),
    'tat_tracker_target_settings': ('tat_tracker', 'tat.settings.targets.propose'),
    'tat_tracker_settings': ('tat_tracker', 'tat.home.view'),
    'tat_tracker_settings_personal': ('tat_tracker', 'tat.home.view'),
    'tat_tracker_create': ('tat_tracker', 'tat.case.create'),
    'tat_tracker_identity_context': ('tat_tracker', 'tat.case.create'),
    'tat_tracker_detail': ('tat_tracker', 'tat.home.view'),
    'tat_tracker_update': ('tat_tracker', 'tat.home.view'),
    'spin_form_submit': ('spin_credit_analysis', 'spin.request.create'),
    'spin_form_requests': ('spin_credit_analysis', 'spin.request.view'),
    'spin_form_settings': ('spin_credit_analysis', 'spin.request.view'),
    'spin_form_settings_personal': ('spin_credit_analysis', 'spin.request.view'),
    'spin_form_complete': ('spin_credit_analysis', 'spin.request.complete'),
    'spin_form_review_update': ('spin_credit_analysis', 'spin.request.review'),
    'spin_batch_review_resolve': ('spin_credit_analysis', 'spin.batch.review'),
}

# These endpoints resolve a capability from the persisted setting key rather
# than owning one fixed capability. Their service layer still uses the same
# exact-tuple resolver and requires an unscoped branch/product grant.
MINIAPP_DYNAMIC_ENDPOINT_POLICIES = {
    'tat_tracker_settings_request': 'tat-setting-proposal-capability',
    'tat_tracker_settings_review': 'tat-setting-approval-capability',
}
