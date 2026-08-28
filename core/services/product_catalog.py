"""Canonical global-product resolution, publication, availability, and requirements."""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.models import (
    Product,
    ProductAlias,
    ProductAvailability,
    ProductCustomAttribute,
    ProductMappingIssue,
    ProductRequirement,
    ProductVersion,
    ProductVersionEvent,
)


class ProductCatalogError(ValueError):
    """Stable, staff-safe global product error."""


def normalize_product_value(value: object) -> str:
    return re.sub(r'[^a-z0-9]+', '_', str(value or '').casefold()).strip('_')


def resolve_product(value: object, *, include_inactive: bool = False) -> Product | None:
    """Resolve an id, code, name, or approved alias without creating records."""
    if isinstance(value, Product):
        return value if include_inactive or value.active else None
    raw = str(value or '').strip()
    if not raw:
        return None
    query = Product.objects.all()
    if not include_inactive:
        query = query.filter(active=True)
    if raw.isdigit():
        match = query.filter(pk=int(raw)).first()
        if match:
            return match
    normalized = normalize_product_value(raw)
    match = query.filter(Q(code__iexact=normalized) | Q(name__iexact=raw)).first()
    if match:
        return match
    alias = ProductAlias.objects.select_related('product').filter(normalized_alias=normalized).first()
    if alias and (include_inactive or alias.product.active):
        return alias.product
    return None


def stage_product_mapping_issue(
    raw_value: object, *, workflow: str, source_model: str = '', source_record_id: object = '',
) -> ProductMappingIssue | None:
    raw = str(raw_value or '').strip()
    normalized = normalize_product_value(raw)
    if not normalized:
        return None
    issue, _created = ProductMappingIssue.objects.get_or_create(
        normalized_value=normalized,
        source_workflow=str(workflow or '').strip(),
        source_model=str(source_model or '').strip(),
        source_record_id=str(source_record_id or '').strip(),
        status=ProductMappingIssue.STATUS_OPEN,
        defaults={'raw_value': raw},
    )
    return issue


def resolve_or_stage_product(
    value: object, *, workflow: str, source_model: str = '', source_record_id: object = '',
) -> Product | None:
    product = resolve_product(value)
    if product is None and str(value or '').strip():
        stage_product_mapping_issue(
            value, workflow=workflow, source_model=source_model, source_record_id=source_record_id,
        )
    return product


@transaction.atomic
def resolve_product_mapping_issue(
    issue: ProductMappingIssue, *, product: Product, actor,
) -> ProductMappingIssue:
    """Approve an alias and attach the staged source record when it still exists."""
    if not getattr(actor, 'is_superuser', False):
        raise ProductCatalogError('Only a Django Superuser may resolve product mappings.')
    issue = ProductMappingIssue.objects.select_for_update().get(pk=issue.pk)
    if issue.status == issue.STATUS_RESOLVED:
        return issue
    normalized = normalize_product_value(issue.raw_value)
    conflict = ProductAlias.objects.filter(normalized_alias=normalized).exclude(product=product).first()
    if conflict:
        raise ProductCatalogError(f'That alias already belongs to {conflict.product}.')
    ProductAlias.objects.get_or_create(
        normalized_alias=normalized,
        defaults={'product': product, 'alias': issue.raw_value},
    )

    field_map = {
        'TatTrackerCase': ('product', 'product_version', 'product_key', product.code),
        'TatRepairJob': ('product', None, 'product_key', product.code),
        'WorkflowTatDailyMetric': ('product', None, 'product_key', product.code),
        'SpinCreditRequest': ('product', 'product_version', 'loan_product', product.name),
        'JawabuFarmerMaster': ('product', 'product_version', 'payment_product', product.name),
        'AccessGrant': ('product_ref', None, 'product', product.code),
        'EmergencyAccessGrant': ('product_ref', None, 'product', product.code),
        'JawabuApprovalDelegation': ('product_ref', None, 'product', product.code),
    }
    if issue.source_model in field_map and issue.source_record_id:
        from django.apps import apps
        model = apps.get_model('core', issue.source_model)
        record = model.objects.filter(pk=issue.source_record_id).first()
        if record:
            product_field, version_field, legacy_field, legacy_value = field_map[issue.source_model]
            setattr(record, product_field, product)
            setattr(record, legacy_field, legacy_value)
            update_fields = [product_field, legacy_field]
            version = active_product_version(product)
            if version_field and version:
                setattr(record, version_field, version)
                update_fields.append(version_field)
                if hasattr(record, 'product_terms_snapshot'):
                    record.product_terms_snapshot = serialize_product_version(version)
                    update_fields.append('product_terms_snapshot')
            record.save(update_fields=update_fields)

    issue.product = product
    issue.status = issue.STATUS_RESOLVED
    issue.resolved_by = actor
    issue.resolved_at = timezone.now()
    issue.save(update_fields=['product', 'status', 'resolved_by', 'resolved_at'])
    try:
        from core.services.compliance_audit import record_event
        record_event(
            workflow='access_control', action='global_product.mapping_resolved',
            category='configuration', origin='human',
            subject_type='product_mapping_issue', subject_id=str(issue.pk),
            actor=actor, authority_user=actor,
            source_model='ProductMappingIssue', source_event_id=str(issue.pk),
            deduplication_key=f'global-product-mapping:{issue.pk}',
            after_values={'product_code': product.code, 'source_workflow': issue.source_workflow},
        )
    except Exception as exc:
        raise ProductCatalogError('The product mapping audit event could not be recorded.') from exc
    return issue


def active_product_version(product: Product | object, *, on_date: date | None = None) -> ProductVersion | None:
    product = resolve_product(product) if not isinstance(product, Product) else product
    if product is None:
        return None
    current = on_date or timezone.localdate()
    return (
        product.versions.filter(
            status__in=[ProductVersion.STATUS_PUBLISHED, ProductVersion.STATUS_SCHEDULED],
            effective_from__lte=current,
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=current))
        .order_by('-effective_from', '-version')
        .first()
    )


def product_is_available(
    product: Product, *, branch=None, workflow: str = '', channel: str = '',
) -> bool:
    assignments = product.availability_assignments.filter(active=True)
    if not assignments.exists():
        return True
    branch_id = getattr(branch, 'pk', branch) or None
    query = assignments.filter(
        Q(branch__isnull=True) | Q(branch_id=branch_id),
        Q(workflow='') | Q(workflow=str(workflow or '').strip()),
        Q(channel='') | Q(channel=str(channel or '').strip()),
    )
    return query.exists()


def product_is_selectable(*, product: Product, workflow: str = '', channel: str = '') -> bool:
    """Pre-branch selector check; final creation still validates the chosen branch."""
    assignments = product.availability_assignments.filter(active=True)
    if not assignments.exists():
        return True
    return assignments.filter(
        Q(workflow='') | Q(workflow=str(workflow or '').strip()),
        Q(channel='') | Q(channel=str(channel or '').strip()),
    ).exists()


def available_products(*, branch=None, workflow: str = '', channel: str = '', on_date: date | None = None):
    return [
        product for product in Product.objects.filter(active=True).order_by('sort_order', 'name')
        if active_product_version(product, on_date=on_date)
        and product_is_available(product, branch=branch, workflow=workflow, channel=channel)
    ]


def serialize_product_version(version: ProductVersion, *, include_configuration: bool = True) -> dict[str, Any]:
    payload = {
        'product_id': version.product_id,
        'product_code': version.product.code,
        'product_name': version.product.name,
        'version_id': str(version.pk),
        'version': version.version,
        'currency': version.currency,
        'min_amount': str(version.min_amount),
        'max_amount': str(version.max_amount) if version.max_amount is not None else '',
        'min_tenor': version.min_tenor,
        'max_tenor': version.max_tenor,
        'tenor_unit': version.tenor_unit,
        'interest_method': version.interest_method,
        'interest_rate': str(version.interest_rate),
        'interest_rate_period': version.interest_rate_period,
        'repayment_frequency': version.repayment_frequency,
        'quote_amount_field_key': version.quote_amount_field_key,
        'quote_tenor_field_key': version.quote_tenor_field_key,
        'effective_from': version.effective_from.isoformat(),
        'effective_to': version.effective_to.isoformat() if version.effective_to else '',
    }
    if include_configuration:
        payload['fees'] = [
            {
                'key': fee.key, 'label': fee.label, 'fee_type': fee.fee_type,
                'fixed_amount': str(fee.fixed_amount) if fee.fixed_amount is not None else '',
                'percentage': str(fee.percentage) if fee.percentage is not None else '',
                'calculation_basis': fee.calculation_basis,
                'minimum_amount': str(fee.minimum_amount) if fee.minimum_amount is not None else '',
                'maximum_amount': str(fee.maximum_amount) if fee.maximum_amount is not None else '',
                'collection_mode': fee.collection_mode, 'mandatory': fee.mandatory,
            }
            for fee in version.fees.all()
        ]
        payload['requirements'] = [
            {
                'key': item.key, 'label': item.label, 'description': item.description,
                'type': item.requirement_type, 'workflow': item.workflow,
                'enforcement_stage': item.enforcement_stage, 'required': item.required,
                'validation': item.validation_config,
            }
            for item in version.requirements.filter(active=True)
        ]
        payload['custom_attributes'] = [
            {
                'key': item.key, 'label': item.label, 'type': item.attribute_type,
                'required': item.required, 'help_text': item.help_text,
                'options': item.options, 'validation': item.validation_config,
                'default': item.default_value, 'workflows': item.workflow_visibility,
            }
            for item in version.custom_attributes.all()
        ]
    return payload


def _validate_version_children(version: ProductVersion) -> None:
    version.full_clean()
    for collection in (version.fees.all(), version.requirements.all(), version.custom_attributes.all()):
        for item in collection:
            item.full_clean()
    if hasattr(version, 'tat_configuration'):
        version.tat_configuration.full_clean()


@transaction.atomic
def publish_product_version(*, version: ProductVersion, actor) -> ProductVersion:
    """Superuser-only publication with effective-date overlap protection."""
    if not getattr(actor, 'is_superuser', False):
        raise ProductCatalogError('Only a Django Superuser may publish product terms.')
    version = ProductVersion.objects.select_for_update().select_related('product').get(pk=version.pk)
    if version.status in {ProductVersion.STATUS_PUBLISHED, ProductVersion.STATUS_SCHEDULED}:
        return version
    if version.status != ProductVersion.STATUS_DRAFT:
        raise ProductCatalogError('Only a draft product version can be published.')
    _validate_version_children(version)

    overlapping = (
        ProductVersion.objects.select_for_update()
        .filter(
            product=version.product,
            status__in=[ProductVersion.STATUS_PUBLISHED, ProductVersion.STATUS_SCHEDULED],
            effective_from__lte=version.effective_to or date.max,
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gte=version.effective_from))
        .exclude(pk=version.pk)
        .order_by('-effective_from')
    )
    for previous in overlapping:
        if previous.effective_from >= version.effective_from:
            raise ProductCatalogError('Published product-version effective dates cannot overlap.')
        previous.effective_to = version.effective_from - timedelta(days=1)
        previous._allow_catalog_publication = True
        try:
            previous.save(update_fields=['effective_to', 'updated_at'])
        finally:
            del previous._allow_catalog_publication
        ProductVersionEvent.objects.create(
            product_version=previous, action='effective_period_closed', actor=actor,
            metadata={'successor_id': str(version.pk), 'effective_to': previous.effective_to.isoformat()},
        )

    current = timezone.localdate()
    version.status = (
        ProductVersion.STATUS_PUBLISHED
        if version.effective_from <= current
        else ProductVersion.STATUS_SCHEDULED
    )
    version.published_by = actor
    version.published_at = timezone.now()
    version.product.active = True
    version.product.save(update_fields=['active', 'updated_at'])
    version._allow_catalog_publication = True
    try:
        version.save(update_fields=['status', 'published_by', 'published_at', 'updated_at'])
    finally:
        del version._allow_catalog_publication
    event = ProductVersionEvent.objects.create(
        product_version=version, action='published', actor=actor,
        metadata={'status': version.status, 'effective_from': version.effective_from.isoformat()},
    )
    try:
        from core.services.compliance_audit import record_event
        record_event(
            workflow='portal', action='global_product.version_published',
            category='configuration', origin='human',
            subject_type='product_version', subject_id=str(version.pk),
            actor=actor, authority_user=actor,
            source_model='ProductVersionEvent', source_event_id=str(event.pk),
            deduplication_key=f'global-product:ProductVersionEvent:{event.pk}',
            after_values={'product_code': version.product.code, 'version': version.version},
        )
    except Exception as exc:
        raise ProductCatalogError('The product audit event could not be recorded.') from exc
    return version


@transaction.atomic
def clone_product_version(version: ProductVersion, *, actor) -> ProductVersion:
    if not getattr(actor, 'is_superuser', False):
        raise ProductCatalogError('Only a Django Superuser may create a product terms version.')
    source = ProductVersion.objects.select_for_update().select_related('product').get(pk=version.pk)
    existing = source.product.versions.filter(status=ProductVersion.STATUS_DRAFT).first()
    if existing:
        return existing
    next_number = (source.product.versions.order_by('-version').values_list('version', flat=True).first() or 0) + 1
    clone = ProductVersion.objects.create(
        product=source.product, version=next_number, status=ProductVersion.STATUS_DRAFT,
        currency=source.currency, min_amount=source.min_amount, max_amount=source.max_amount,
        min_tenor=source.min_tenor, max_tenor=source.max_tenor, tenor_unit=source.tenor_unit,
        interest_method=source.interest_method, interest_rate=source.interest_rate,
        interest_rate_period=source.interest_rate_period,
        repayment_frequency=source.repayment_frequency,
        quote_amount_field_key=source.quote_amount_field_key,
        quote_tenor_field_key=source.quote_tenor_field_key,
        effective_from=max(timezone.localdate(), (source.effective_to + timedelta(days=1)) if source.effective_to else timezone.localdate()),
        supersedes=source, created_by=actor,
    )
    for fee in source.fees.all():
        fee.pk = None
        fee.product_version = clone
        fee.save()
    for requirement in source.requirements.all():
        requirement.pk = None
        requirement.product_version = clone
        requirement.save()
    for attribute in source.custom_attributes.all():
        attribute.pk = None
        attribute.product_version = clone
        attribute.save()
    if hasattr(source, 'tat_configuration'):
        config = source.tat_configuration
        config.pk = None
        config.product_version = clone
        config.save()
    ProductVersionEvent.objects.create(
        product_version=clone, action='version_created', actor=actor,
        metadata={'supersedes_id': str(source.pk)},
    )
    return clone


def missing_product_requirements(
    version: ProductVersion | None, *, workflow: str, stage: str,
    evidence: dict[str, Any] | None,
) -> list[dict[str, str]]:
    if version is None:
        return []
    evidence = evidence if isinstance(evidence, dict) else {}
    requirements = version.requirements.filter(
        active=True, required=True, enforcement_stage=str(stage or '').strip(),
    ).filter(Q(workflow='') | Q(workflow=str(workflow or '').strip()))
    missing = []
    for requirement in requirements:
        value = evidence.get(requirement.key)
        valid = value not in (None, '', [], {})
        if requirement.requirement_type in {ProductRequirement.TYPE_CHECKBOX, ProductRequirement.TYPE_ELIGIBILITY}:
            valid = value is True
        elif requirement.requirement_type == ProductRequirement.TYPE_AMOUNT and valid:
            try:
                amount = Decimal(str(value))
                minimum = requirement.validation_config.get('min')
                maximum = requirement.validation_config.get('max')
                valid = (minimum in (None, '') or amount >= Decimal(str(minimum))) and (
                    maximum in (None, '') or amount <= Decimal(str(maximum))
                )
            except (InvalidOperation, TypeError, ValueError):
                valid = False
        if not valid:
            missing.append({'key': requirement.key, 'label': requirement.label, 'type': requirement.requirement_type})
    return missing


def validate_custom_values(
    version: ProductVersion | None, values: dict[str, Any] | None, *, workflow: str = '',
) -> dict[str, str]:
    if version is None:
        return {}
    values = values if isinstance(values, dict) else {}
    errors = {}
    for attribute in version.custom_attributes.all():
        visible = attribute.workflow_visibility or []
        if visible and workflow and workflow not in visible:
            continue
        value = values.get(attribute.key, attribute.default_value)
        if attribute.required and value in (None, '', [], {}):
            errors[attribute.key] = f'{attribute.label} is required.'
            continue
        if value in (None, ''):
            continue
        if attribute.attribute_type == ProductCustomAttribute.TYPE_BOOLEAN and not isinstance(value, bool):
            errors[attribute.key] = f'{attribute.label} must be yes or no.'
        elif attribute.attribute_type in {ProductCustomAttribute.TYPE_NUMBER, ProductCustomAttribute.TYPE_MONEY}:
            try:
                number = Decimal(str(value))
                minimum = (attribute.validation_config or {}).get('min')
                maximum = (attribute.validation_config or {}).get('max')
                if minimum not in (None, '') and number < Decimal(str(minimum)):
                    errors[attribute.key] = f'{attribute.label} must be at least {minimum}.'
                elif maximum not in (None, '') and number > Decimal(str(maximum)):
                    errors[attribute.key] = f'{attribute.label} must not exceed {maximum}.'
            except (InvalidOperation, TypeError, ValueError):
                errors[attribute.key] = f'{attribute.label} must be a number.'
        elif attribute.attribute_type == ProductCustomAttribute.TYPE_DATE:
            try:
                date.fromisoformat(str(value))
            except (TypeError, ValueError):
                errors[attribute.key] = f'{attribute.label} must be a valid date.'
        elif attribute.attribute_type == ProductCustomAttribute.TYPE_CHOICE and value not in (attribute.options or []):
            errors[attribute.key] = f'Select an approved value for {attribute.label}.'
        elif attribute.attribute_type == ProductCustomAttribute.TYPE_TEXT:
            pattern = str((attribute.validation_config or {}).get('pattern') or '')
            if pattern and re.fullmatch(pattern, str(value)) is None:
                errors[attribute.key] = f'{attribute.label} is not in the required format.'
    return errors
