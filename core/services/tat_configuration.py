"""Immutable TAT configuration snapshots and explicit legacy reconciliation."""
from __future__ import annotations

from decimal import Decimal

from django.db import transaction

from core.models import ProductTatConfiguration, ProductVersion, TatConfigurationEvent, TatTrackerCase


class TatConfigurationError(ValueError):
    """Stable, staff-safe TAT configuration error."""


def serialize_tat_configuration(version: ProductVersion) -> dict:
    """Return the exact TAT adapter used by cases created under ``version``."""
    version = ProductVersion.objects.select_related('product').get(pk=version.pk)
    try:
        config = ProductTatConfiguration.objects.get(product_version=version)
    except ProductTatConfiguration.DoesNotExist as exc:
        raise TatConfigurationError('This product version has no TAT stage configuration.') from exc
    return {
        'schema_version': 1,
        'product_id': version.product_id,
        'product_key': version.product.code,
        'product_label': version.product.name,
        'product_version_id': str(version.pk),
        'product_version': version.version,
        'min_amount': str(version.min_amount),
        'max_amount': str(version.max_amount) if version.max_amount is not None else '',
        'sheet_name': config.sheet_name,
        'case_prefix': config.case_prefix,
        'remarks_col': config.remarks_col,
        'status_col': config.status_col,
        'tat_start_col': config.tat_start_col,
        'stage_columns': dict(config.stage_columns or {}),
        'stages': list(config.stages or []),
        'stage_tat_columns': list(config.stage_tat_columns or []),
    }


def product_config_from_snapshot(snapshot: dict):
    """Adapt a stored snapshot to the legacy read-only ProductConfig interface."""
    from core.services.tat_tracker import ProductConfig, StageConfig, StageTatColumn

    if not isinstance(snapshot, dict) or not snapshot.get('stages'):
        raise TatConfigurationError('This case has no deterministic TAT stage configuration.')
    stages = tuple(
        StageConfig(
            key=str(item.get('key') or ''),
            label=str(item.get('label') or item.get('key') or ''),
            column=int(item.get('column') or 0),
            role=str(item.get('role') or ''),
            kind=str(item.get('kind') or 'timestamp'),
            options=tuple(item.get('options') or ()),
            auto_timestamp_key=str(item.get('auto_timestamp_key') or ''),
            requires_signature_certificate=bool(item.get('requires_signature_certificate', False)),
        )
        for item in snapshot.get('stages') or []
        if item.get('key')
    )
    stage_keys = {item.key for item in stages}
    tat_columns = tuple(
        StageTatColumn(
            stage_key=str(item.get('stage_key') or ''),
            fallback_col=int(item.get('fallback_col') or 0),
            aliases=tuple(item.get('aliases') or ()),
        )
        for item in snapshot.get('stage_tat_columns') or []
        if item.get('stage_key') in stage_keys
    )
    max_amount = snapshot.get('max_amount')
    return ProductConfig(
        key=str(snapshot.get('product_key') or ''),
        label=str(snapshot.get('product_label') or snapshot.get('product_key') or ''),
        sheet_name=str(snapshot.get('sheet_name') or ''),
        case_prefix=str(snapshot.get('case_prefix') or ''),
        min_amount=Decimal(str(snapshot.get('min_amount') or '0')),
        max_amount=Decimal(str(max_amount)) if max_amount not in (None, '') else None,
        remarks_col=int(snapshot.get('remarks_col') or 0),
        status_col=int(snapshot.get('status_col') or 0),
        tat_start_col=int(snapshot.get('tat_start_col') or 0),
        stage_columns={str(key): int(value) for key, value in (snapshot.get('stage_columns') or {}).items()},
        stages=stages,
        product_id=snapshot.get('product_id'),
        version_id=str(snapshot.get('product_version_id') or ''),
        stage_tat_columns=tat_columns,
    )


def product_config_for_case(case: TatTrackerCase):
    """Resolve a case against its frozen configuration, never the current product."""
    snapshot = case.tat_configuration_snapshot or {}
    if snapshot.get('stages'):
        return product_config_from_snapshot(snapshot)
    if case.configuration_binding_status == TatTrackerCase.CONFIG_UNRESOLVED:
        raise TatConfigurationError(
            'This legacy case has no verified product-version configuration. Resolve it in TAT Control Center before editing it.'
        )
    # Compatibility for pre-migration/test rows explicitly classified as
    # legacy_assumed. This remains visible as a non-deterministic binding and
    # is excluded from bulk migration and Sheet cutover readiness.
    from core.services.tat_tracker import product_by_key
    return product_by_key(case.product_key)


@transaction.atomic
def resolve_case_configuration(
    *, case: TatTrackerCase, version: ProductVersion, actor, reason: str, request_id: str,
) -> TatTrackerCase:
    """Explicitly bind one unresolved/assumed legacy case to reviewed bytes."""
    if not getattr(actor, 'is_superuser', False):
        raise TatConfigurationError('Only a Django Superuser may resolve a legacy TAT configuration.')
    reason = str(reason or '').strip()
    request_id = str(request_id or '').strip()
    if len(reason) < 10:
        raise TatConfigurationError('Explain why this product version is correct (at least 10 characters).')
    if not request_id:
        raise TatConfigurationError('A request ID is required.')
    case = TatTrackerCase.objects.select_for_update().select_related('product').get(pk=case.pk)
    existing = TatConfigurationEvent.objects.filter(action='legacy_case_resolved', request_id=request_id).first()
    if existing:
        return case
    version = ProductVersion.objects.select_for_update().select_related('product').get(pk=version.pk)
    expected_product_id = case.product_id or getattr(case.product, 'pk', None)
    if expected_product_id and version.product_id != expected_product_id:
        raise TatConfigurationError('The selected version belongs to a different product.')
    if not expected_product_id and version.product.code != case.product_key:
        raise TatConfigurationError('The selected version does not match this case product.')
    before = {
        'binding_status': case.configuration_binding_status,
        'product_version_id': str(case.product_version_id or ''),
    }
    snapshot = serialize_tat_configuration(version)
    configured_stage_keys = {str(item.get('key') or '') for item in snapshot['stages']}
    used_stage_keys = {str(key) for key in (case.stage_values or {}).keys()} - {'created'}
    missing = sorted(used_stage_keys - configured_stage_keys)
    if missing:
        raise TatConfigurationError(
            'This version does not contain stage history already used by the case: ' + ', '.join(missing)
        )
    case.product = version.product
    case.product_version = version
    case.product_key = version.product.code
    case.product_label = version.product.name
    case.tat_configuration_snapshot = snapshot
    case.configuration_binding_status = TatTrackerCase.CONFIG_VERSIONED
    case.save(update_fields=[
        'product', 'product_version', 'product_key', 'product_label',
        'tat_configuration_snapshot', 'configuration_binding_status', 'updated_at',
    ])
    TatConfigurationEvent.objects.create(
        action='legacy_case_resolved', actor=actor, request_id=request_id, reason=reason,
        before_snapshot=before,
        after_snapshot={
            'binding_status': case.configuration_binding_status,
            'product_version_id': str(version.pk),
        },
        metadata={'case_id': case.case_id, 'case_pk': str(case.pk)},
    )
    return case

