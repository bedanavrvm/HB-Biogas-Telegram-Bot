"""One resolution contract for workflow branch and product configuration.

The database catalogues remain authoritative.  Per-group JSON stores only an
explicit restriction or a deliberate request to follow the catalogue.  This
module also understands the legacy ``branches`` and ``products`` arrays so a
deployment cannot widen an existing group's scope merely by adopting the
guided Admin workspace.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from django.conf import settings


MODE_GROUP_CATALOG_SCOPE = 'group_catalog_scope'
MODE_AVAILABILITY_ACCESS_SCOPE = 'availability_access_scope'
MODE_CATALOG_WITH_LEGACY_ENVIRONMENT = 'catalog_with_legacy_environment'
MODE_CATALOG_PLUS_HISTORY = 'catalog_plus_history'
MODE_SOURCE_DATA_MAPPING = 'source_data_mapping'

SCOPE_CATALOG = 'catalog'
SCOPE_SELECTED = 'selected'
VALID_SCOPE_MODES = {SCOPE_CATALOG, SCOPE_SELECTED}

WORKFLOW_ALIASES = {
    'case': 'complaint_cases',
    'complaints': 'complaint_cases',
    'jawabu': 'jawabu_portal',
    'jawabu_homebiogas': 'jawabu_portal',
    'spin': 'spin_credit_analysis',
}

RESOLUTION_MODES = {
    'tat_tracker': MODE_GROUP_CATALOG_SCOPE,
    'spin_credit_analysis': MODE_GROUP_CATALOG_SCOPE,
    'loan_origination': MODE_AVAILABILITY_ACCESS_SCOPE,
    'jawabu_portal': MODE_AVAILABILITY_ACCESS_SCOPE,
    'order_approval': MODE_CATALOG_WITH_LEGACY_ENVIRONMENT,
    'complaint_cases': MODE_CATALOG_PLUS_HISTORY,
    'fca': MODE_SOURCE_DATA_MAPPING,
    'fca_review': MODE_SOURCE_DATA_MAPPING,
}

WARNING_MESSAGES = {
    'retired_branch': 'This configured branch is retired and cannot accept new records.',
    'historical_branch_only': 'This branch is retained only for filtering historical complaints.',
    'inactive_product': 'This configured product is inactive.',
    'missing_active_version': 'This product has no currently effective published version.',
    'missing_workflow_configuration': 'This product is missing configuration required by this workflow.',
    'unavailable_branch_product': 'This product is not available for one or more selected branches.',
    'legacy_environment_override': 'A deprecated environment setting overrides the governed branch catalogue.',
    'unknown_legacy_value': 'This saved value cannot be resolved to a governed catalogue record.',
}

_STALE_TAT_BRANCH_DEFAULTS = {
    'corporate', 'thika road', 'east nairobi', 'west nairobi',
    'nakuru', 'embu', 'limuru',
}


def canonical_workflow_key(value: object) -> str:
    key = str(value or '').strip()
    return WORKFLOW_ALIASES.get(key, key)


def workflow_key_for_config(group_config=None, workflow: dict | None = None) -> str:
    payload = workflow if workflow is not None else getattr(group_config, 'workflow', None)
    return canonical_workflow_key((payload or {}).get('type') or 'complaint_cases')


def _values(value: Any) -> list[str]:
    if not value:
        return []
    items = value.split(',') if isinstance(value, str) else value
    return list(dict.fromkeys(
        str(item or '').strip() for item in items if str(item or '').strip()
    ))


def scope_selection(workflow: dict | None, dimension: str) -> tuple[str, list[str], str]:
    """Return (mode, values, source) while preserving legacy restrictions."""
    workflow = workflow or {}
    scope = workflow.get('catalog_scope') or {}
    configured = scope.get(dimension) if isinstance(scope, dict) else None
    if isinstance(configured, dict):
        mode = str(configured.get('mode') or '').strip()
        if mode in VALID_SCOPE_MODES:
            return mode, _values(configured.get('values')), 'guided_configuration'
    legacy_key = 'branches' if dimension == 'branches' else 'products'
    if legacy_key in workflow and _values(workflow.get(legacy_key)):
        return SCOPE_SELECTED, _values(workflow.get(legacy_key)), 'legacy_restriction'
    return SCOPE_CATALOG, [], 'governed_catalogue'


def apply_catalog_scope(
    workflow: dict | None, *, branch_mode: str | None = None,
    branches=None, product_mode: str | None = None, products=None,
) -> dict:
    """Update only guided scope keys and preserve every unrelated JSON value."""
    result = deepcopy(workflow or {})
    scope = deepcopy(result.get('catalog_scope') or {})
    for dimension, mode, values, legacy_key in (
        ('branches', branch_mode, branches, 'branches'),
        ('products', product_mode, products, 'products'),
    ):
        if mode is None:
            continue
        if mode not in VALID_SCOPE_MODES:
            raise ValueError(f'Choose a valid {dimension} scope mode.')
        normalized = _values(values)
        if mode == SCOPE_SELECTED and not normalized:
            raise ValueError(f'Choose at least one {dimension[:-1]}.')
        scope[dimension] = {'mode': mode, 'values': normalized if mode == SCOPE_SELECTED else []}
        if mode == SCOPE_SELECTED:
            result[legacy_key] = normalized
        else:
            result.pop(legacy_key, None)
    result['catalog_scope'] = scope
    return result


def _warning(code: str, *, value: str = '', source: str = '') -> dict:
    return {
        'code': code,
        'message': WARNING_MESSAGES[code],
        'value': value,
        'source': source,
    }


def _branch_catalog():
    from core.models import OperationalLocation
    return list(OperationalLocation.objects.filter(
        location_type='branch', active=True,
    ).order_by('sort_order', 'name'))


def _all_branches_by_name():
    from core.models import OperationalLocation
    return {
        item.name.casefold(): item
        for item in OperationalLocation.objects.filter(location_type='branch')
    }


def _product_rows(workflow_key: str) -> tuple[list, list[dict]]:
    from core.models import Product
    from core.services.product_catalog import active_product_version, product_is_selectable

    rows = []
    warnings = []
    for product in Product.objects.filter(active=True).order_by('sort_order', 'name'):
        version = active_product_version(product)
        if version is None:
            warnings.append(_warning('missing_active_version', value=product.code, source='product_catalogue'))
            continue
        if workflow_key == 'tat_tracker' and not hasattr(version, 'tat_configuration'):
            warnings.append(_warning(
                'missing_workflow_configuration', value=product.code, source='product_catalogue',
            ))
            continue
        if not product_is_selectable(product=product, workflow=workflow_key, channel='portal'):
            continue
        rows.append(product)
    return rows, warnings


def _legacy_order_branches() -> list[str]:
    raw = getattr(settings, 'ORDER_APPROVAL_BRANCH_CHOICES', None)
    shared = getattr(settings, 'WORKFLOW_BRANCH_CHOICES', '')
    default = getattr(settings, 'DEFAULT_WORKFLOW_BRANCH_CHOICES', '')
    if raw is None or str(raw).strip() in {str(shared).strip(), str(default).strip()}:
        return []
    return _values(raw)


def _legacy_tat_branches() -> list[str]:
    raw = getattr(settings, 'TAT_TRACKER_BRANCH_CHOICES', '')
    shared = getattr(settings, 'WORKFLOW_BRANCH_CHOICES', '')
    default = getattr(settings, 'DEFAULT_WORKFLOW_BRANCH_CHOICES', '')
    if not str(raw or '').strip() or str(raw).strip() in {str(shared).strip(), str(default).strip()}:
        return []
    return _values(raw)


def _is_stale_tat_branch_default(values) -> bool:
    normalized = {str(value or '').strip().casefold() for value in values if str(value or '').strip()}
    return bool(normalized) and normalized.issubset(_STALE_TAT_BRANCH_DEFAULTS)


def _complaint_history(group_config) -> list[str]:
    if group_config is None or not getattr(group_config, 'group_id', ''):
        return []
    from core.models import ParsedMessage
    return list(ParsedMessage.objects.filter(
        group_id=str(group_config.group_id),
    ).exclude(branch_region='').order_by('branch_region').values_list(
        'branch_region', flat=True,
    ).distinct())


def resolve_workflow_catalog(
    workflow_key: str | None = None, group_config=None, actor=None,
    *, include_products: bool = True,
) -> dict:
    """Return the named source, effective values, exclusions, and warnings."""
    workflow = getattr(group_config, 'workflow', None) or {}
    key = canonical_workflow_key(workflow_key or workflow_key_for_config(group_config, workflow))
    resolution_mode = RESOLUTION_MODES.get(key, MODE_SOURCE_DATA_MAPPING)
    branch_mode, selected_branches, branch_source = scope_selection(workflow, 'branches')
    product_mode, selected_products, product_source = scope_selection(workflow, 'products')
    active_branches = _branch_catalog()
    branch_lookup = {item.name.casefold(): item for item in active_branches}
    all_branch_lookup = _all_branches_by_name()
    warnings = []
    excluded = {'branches': [], 'products': []}

    tat_environment_branches = _legacy_tat_branches() if key == 'tat_tracker' else []
    if _is_stale_tat_branch_default(tat_environment_branches):
        tat_environment_branches = []
    if tat_environment_branches:
        effective_branches = tat_environment_branches
        branch_source = 'legacy_environment'
        warnings.append(_warning('legacy_environment_override', source='TAT_TRACKER_BRANCH_CHOICES'))
    elif resolution_mode == MODE_SOURCE_DATA_MAPPING:
        effective_branches = []
        branch_source = 'source_data_mapping'
    elif resolution_mode == MODE_CATALOG_WITH_LEGACY_ENVIRONMENT and _legacy_order_branches():
        effective_branches = _legacy_order_branches()
        branch_source = 'legacy_environment'
        warnings.append(_warning('legacy_environment_override', source='ORDER_APPROVAL_BRANCH_CHOICES'))
    elif resolution_mode == MODE_CATALOG_PLUS_HISTORY:
        effective_branches = [item.name for item in active_branches]
        for value in _complaint_history(group_config):
            if value.casefold() not in branch_lookup:
                effective_branches.append(value)
                record = all_branch_lookup.get(value.casefold())
                code = 'retired_branch' if record else 'historical_branch_only'
                warnings.append(_warning(code, value=value, source='complaint_history'))
        branch_source = 'governed_catalogue_and_history'
    elif (
        branch_mode == SCOPE_SELECTED
        and resolution_mode == MODE_GROUP_CATALOG_SCOPE
        and not (key == 'tat_tracker' and _is_stale_tat_branch_default(selected_branches))
    ):
        effective_branches = []
        for value in selected_branches:
            record = all_branch_lookup.get(value.casefold())
            if record and record.active:
                effective_branches.append(record.name)
            else:
                code = 'retired_branch' if record else 'unknown_legacy_value'
                warnings.append(_warning(code, value=value, source=branch_source))
                excluded['branches'].append(value)
    else:
        effective_branches = [item.name for item in active_branches]

    product_applicable = include_products and resolution_mode not in {
        MODE_SOURCE_DATA_MAPPING, MODE_CATALOG_PLUS_HISTORY,
    }
    if not product_applicable:
        product_source = 'not_applicable'
        product_mode = SCOPE_CATALOG
        selected_products = []
    products, product_warnings = (
        _product_rows(key)
        if product_applicable
        else ([], [])
    )
    warnings.extend(product_warnings)
    product_lookup = {item.code.casefold(): item for item in products}
    if product_mode == SCOPE_SELECTED and resolution_mode == MODE_GROUP_CATALOG_SCOPE:
        effective_products = []
        from core.models import Product
        from core.services.product_catalog import active_product_version
        all_products = {
            item.code.casefold(): item for item in Product.objects.all()
        }
        for value in selected_products:
            product = product_lookup.get(value.casefold())
            if product:
                effective_products.append(product.code)
            else:
                existing = all_products.get(value.casefold())
                if existing and not existing.active:
                    code = 'inactive_product'
                elif existing and active_product_version(existing) is None:
                    code = 'missing_active_version'
                elif (
                    existing and key == 'tat_tracker'
                    and not hasattr(active_product_version(existing), 'tat_configuration')
                ):
                    code = 'missing_workflow_configuration'
                elif existing:
                    code = 'unavailable_branch_product'
                else:
                    code = 'unknown_legacy_value'
                warnings.append(_warning(code, value=value, source=product_source))
                excluded['products'].append(value)
    else:
        effective_products = [item.code for item in products]

    if (
        resolution_mode == MODE_GROUP_CATALOG_SCOPE
        and branch_mode == SCOPE_SELECTED
        and product_mode == SCOPE_SELECTED
    ):
        from core.services.product_catalog import product_is_available
        for product_code in effective_products:
            product = product_lookup.get(product_code.casefold())
            for branch_name in effective_branches:
                branch = branch_lookup.get(branch_name.casefold())
                if product and branch and not product_is_available(
                    product, branch=branch, workflow=key, channel='portal',
                ):
                    warnings.append(_warning(
                        'unavailable_branch_product',
                        value=f'{product.code} / {branch.name}', source='product_availability',
                    ))

    return {
        'workflow': key,
        'resolution_mode': resolution_mode,
        'branch_scope_mode': branch_mode,
        'product_scope_mode': product_mode,
        'branch_source': branch_source,
        'product_source': product_source,
        'available_branches': [item.name for item in active_branches],
        'available_products': [{'code': item.code, 'name': item.name} for item in products],
        'selected_branches': selected_branches,
        'selected_products': selected_products,
        'effective_branches': list(dict.fromkeys(effective_branches)),
        'effective_products': list(dict.fromkeys(effective_products)),
        'excluded': excluded,
        'warnings': warnings,
    }


def workflow_branch_names(workflow_key: str, workflow: dict | None = None) -> list[str]:
    config = type('WorkflowConfig', (), {'workflow': workflow or {}, 'group_id': ''})()
    return resolve_workflow_catalog(
        workflow_key, config, include_products=False,
    )['effective_branches']


def workflow_product_codes(workflow_key: str, workflow: dict | None = None) -> list[str]:
    config = type('WorkflowConfig', (), {'workflow': workflow or {}, 'group_id': ''})()
    return resolve_workflow_catalog(workflow_key, config)['effective_products']
