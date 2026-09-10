"""Auditable reconciliation for the reference data required by a fresh database."""
from __future__ import annotations

import importlib
from dataclasses import asdict, dataclass

from django.apps import apps
from django.db import transaction


DEFAULT_PRODUCT_SPECS = (
    ('business', 'Business'),
    ('logbook', 'Logbook'),
    ('mjengo', 'Mjengo'),
    ('micro_asset', 'Micro-Asset'),
)


@dataclass(frozen=True)
class BaselineItem:
    area: str
    key: str
    state: str
    detail: str = ''


def _migration(name: str):
    return importlib.import_module(f'core.migrations.{name}')


def _expected():
    locations = _migration('0112_branchservicearea_locationconfigurationevent_and_more')
    branches = _migration('0059_seed_default_branches')
    products = _migration('0108_product_productalias_productavailability_and_more')
    descriptions = _migration('0166_compact_complaint_category_descriptions')
    return branches.DEFAULT_BRANCHES, locations.KENYA_COUNTY_SUB_COUNTIES, products, descriptions.CATEGORY_DESCRIPTIONS


def operational_row_counts() -> dict[str, int]:
    names = (
        'GroupSheetConfiguration', 'AccessGrant', 'ParsedMessage', 'TatTrackerCase',
        'SpinCreditRequest', 'LoanOriginationApplication', 'JawabuFarmerMaster',
    )
    return {
        name: apps.get_model('core', name).objects.count()
        for name in names
        if apps.get_model('core', name) is not None
    }


def audit_baseline() -> dict:
    from core.models import (
        AccessControlPolicyState, ComplaintCategory, LocationPolicyState,
        OperationalLocation, Product, TatPresentationSettings, WorkflowRoleCapability,
    )
    from core.services.workflow_capabilities import capability_definitions

    branch_names, counties, _products_seed, descriptions = _expected()
    items: list[BaselineItem] = []
    for name in branch_names:
        row = OperationalLocation.objects.filter(location_type='branch', name__iexact=name).first()
        state = 'correct' if row and row.active else ('conflicting' if row else 'missing')
        items.append(BaselineItem('branches', name, state, 'active governed branch'))
    for number, county_name, sub_counties in counties:
        county = OperationalLocation.objects.filter(location_type='county', code=f'KE-{number:02d}').first()
        state = 'correct' if county and county.active else ('conflicting' if county else 'missing')
        items.append(BaselineItem('counties', f'KE-{number:02d}', state, county_name))
        if county:
            actual = county.children.filter(location_type='sub_county', active=True).count()
            if actual != len(sub_counties):
                items.append(BaselineItem(
                    'sub_counties', f'KE-{number:02d}', 'conflicting',
                    f'expected {len(sub_counties)}, found {actual}',
                ))
    expected_products = dict(DEFAULT_PRODUCT_SPECS)
    for code, expected_name in DEFAULT_PRODUCT_SPECS:
        product = Product.objects.filter(code__iexact=code).first()
        published = bool(product and product.versions.filter(status='published').exists())
        state = (
            'correct'
            if product and product.name == expected_name and product.active and published
            else ('conflicting' if product else 'missing')
        )
        items.append(BaselineItem(
            'products', code, state,
            f'{expected_name}: active product with a published version',
        ))
    for product in Product.objects.exclude(code__in=expected_products).order_by('code'):
        items.append(BaselineItem(
            'products', product.code or str(product.pk), 'conflicting',
            'not part of the approved fresh-database default catalogue',
        ))
    for key, description in descriptions.items():
        category = ComplaintCategory.objects.filter(key=key).first()
        state = (
            'correct' if category and category.active and category.description == description
            else ('conflicting' if category else 'missing')
        )
        items.append(BaselineItem('complaint_categories', key, state, description))
    for definition in capability_definitions():
        for role in definition.default_roles:
            exists = WorkflowRoleCapability.objects.filter(
                workflow=definition.workflow, role=role,
                capability_key=definition.key,
            ).exists()
            items.append(BaselineItem(
                'role_capabilities', f'{definition.workflow}:{role}:{definition.key}',
                'correct' if exists else 'missing',
            ))
    for key, exists in (
        ('access_control', AccessControlPolicyState.objects.filter(singleton=1).exists()),
        ('locations', LocationPolicyState.objects.filter(pk=1).exists()),
        ('tat_presentation', TatPresentationSettings.objects.filter(singleton=1).exists()),
    ):
        items.append(BaselineItem('singleton_policies', key, 'correct' if exists else 'missing'))
    states = {state: sum(item.state == state for item in items) for state in ('correct', 'missing', 'conflicting')}
    return {
        'ok': not states['missing'] and not states['conflicting'],
        'summary': states,
        'location_counts': {
            'branches': OperationalLocation.objects.filter(location_type='branch', active=True).count(),
            'counties': OperationalLocation.objects.filter(location_type='county', active=True).count(),
            'sub_counties': OperationalLocation.objects.filter(location_type='sub_county', active=True).count(),
        },
        'operational_rows': operational_row_counts(),
        'items': [asdict(item) for item in items],
        'next_step': 'Dry-run seed_origination_main_lafs separately; Main LAF files remain unpublished.',
    }


@transaction.atomic
def apply_baseline(*, actor=None) -> dict:
    populated = {name: count for name, count in operational_row_counts().items() if count}
    if populated:
        labels = ', '.join(f'{name}={count}' for name, count in populated.items())
        raise ValueError(f'Baseline apply is restricted to a fresh database; found {labels}.')

    from core.models import OperationalLocation
    branch_names, _counties, _products, _descriptions = _expected()
    for sort_order, name in enumerate(branch_names):
        code = 'JBL-BR-' + ''.join(
            character if character.isalnum() else '-'
            for character in name.upper()
        ).strip('-')
        OperationalLocation.objects.get_or_create(
            location_type='branch', name=name,
            defaults={'code': code, 'active': True, 'sort_order': sort_order},
        )
    _migration('0112_branchservicearea_locationconfigurationevent_and_more').seed_and_backfill_locations(apps, None)
    _reconcile_default_products()
    _migration('0070_seed_workflow_role_capabilities').seed_capabilities(apps, None)
    from core.models import WorkflowRoleCapability
    WorkflowRoleCapability.objects.filter(
        workflow='tat_tracker', capability_key='tat.stage.bm_tat_request.update',
    ).delete()
    _migration('0154_complaint_category_catalogue').seed_complaint_categories(apps, None)
    _migration('0163_it_override_tat_roles_complaint_categories').apply_policy_and_catalogue(apps, None)
    _migration('0166_compact_complaint_category_descriptions').update_descriptions(apps, None)

    from core.models import AccessControlPolicyState, LocationPolicyState, TatPresentationSettings
    AccessControlPolicyState.current()
    LocationPolicyState.objects.get_or_create(pk=1)
    TatPresentationSettings.objects.get_or_create(singleton=1)
    report = audit_baseline()
    if actor is not None:
        from core.services.compliance_audit import record_event
        record_event(
            workflow='system', action='fresh_database.baseline_applied',
            category='configuration', subject_type='database_baseline', subject_id='v1',
            actor=actor, authority_user=actor, request_id='fresh-database-baseline:v1',
            source_model='FreshDatabaseBaseline', source_event_id='v1',
            deduplication_key='fresh-database-baseline:v1',
            metadata={'summary': report['summary'], 'location_counts': report['location_counts']},
            sensitive=True,
        )
    return report


def _reconcile_default_products() -> None:
    """Leave a fresh database with only the explicitly approved defaults."""
    from core.models import OriginationProductDefinition, Product, ProductVersion

    approved_codes = {code for code, _name in DEFAULT_PRODUCT_SPECS}
    unwanted = Product.objects.exclude(code__in=approved_codes).order_by('pk')
    for product in unwanted:
        # Historical migrations may have attached a dormant Origination schema
        # to a generated global product. Preserve the schema for later manual
        # configuration, but do not keep the product as a catalogue default.
        OriginationProductDefinition.objects.filter(
            product_version__product=product,
        ).update(product_version=None)
        ProductVersion.objects.filter(product=product).delete()
        product.delete()

    for sort_order, (code, name) in enumerate(DEFAULT_PRODUCT_SPECS):
        product = Product.objects.get(code=code)
        changed = []
        if product.name != name:
            product.name = name
            changed.append('name')
        if not product.active:
            product.active = True
            changed.append('active')
        if product.sort_order != sort_order:
            product.sort_order = sort_order
            changed.append('sort_order')
        if changed:
            product.save(update_fields=[*changed, 'updated_at'])
