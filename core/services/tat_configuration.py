"""Immutable TAT configuration snapshots and explicit legacy reconciliation."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

from django.db import transaction

from core.models import ProductTatConfiguration, ProductVersion, TatConfigurationEvent, TatTrackerCase


VALUATION_STAGE_KEY = 'valuation_ready'
HOCC_STAGE_KEYS = {
    'bm_hocc_request', 'tat_scheduled', 'tat_held', 'decision',
    'minutes_shared', 'sanctions',
}

GLOBAL_TAT_SHEET_NAME = 'TAT Register'
GLOBAL_TAT_STAGES = [
    {'key': 'mpesa_to_admin', 'label': 'MPESA sent to Admin', 'column': 11, 'role': 'BRO', 'kind': 'timestamp'},
    {'key': 'mpesa_verified', 'label': 'MPESA verified by Business Admin and sent to CA', 'column': 12, 'role': 'BUSINESS_ADMIN', 'kind': 'timestamp'},
    {'key': 'ca_analysis_sent', 'label': 'Credit analysis sent', 'column': 13, 'role': 'CA', 'kind': 'timestamp'},
    {'key': 'bro_response', 'label': 'BRO response to CA', 'column': 14, 'role': 'BRO', 'kind': 'timestamp'},
    {'key': 'bm_response', 'label': 'BM response to CA', 'column': 15, 'role': 'BM', 'kind': 'dropdown', 'options': ['Approved', 'Declined'], 'auto_timestamp_key': 'bm_response_ts', 'requires_signature_certificate': True},
    {'key': 'valuation_ready', 'label': 'Valuation ready', 'column': 17, 'role': 'BM', 'kind': 'timestamp'},
    {'key': 'bm_hocc_request', 'label': 'BM HOCC request', 'column': 18, 'role': 'BM', 'kind': 'timestamp'},
    {'key': 'tat_scheduled', 'label': 'HOCC scheduled', 'column': 19, 'role': 'SECRETARY', 'kind': 'timestamp'},
    {'key': 'tat_held', 'label': 'HOCC held', 'column': 20, 'role': 'SECRETARY', 'kind': 'timestamp'},
    {'key': 'decision', 'label': 'Decision', 'column': 21, 'role': 'CHAIR', 'kind': 'dropdown', 'options': ['Approved', 'Rejected', 'Deferred'], 'auto_timestamp_key': 'decision_ts'},
    {'key': 'minutes_shared', 'label': 'Minutes shared', 'column': 23, 'role': 'SECRETARY', 'kind': 'dropdown', 'options': ['Yes', 'No'], 'auto_timestamp_key': 'minutes_shared_ts'},
    {'key': 'sanctions', 'label': 'Sanctions', 'column': 25, 'role': 'LOAN_APPROVER', 'kind': 'dropdown', 'options': ['Pending', 'Met', 'Not Met'], 'auto_timestamp_key': 'sanctions_ts'},
    {'key': 'bro_applied', 'label': 'BRO applied loan on system', 'column': 27, 'role': 'BRO', 'kind': 'dropdown', 'options': ['Pending', 'Met', 'Not Met'], 'auto_timestamp_key': 'bro_applied_ts'},
    {'key': 'disbursement_register', 'label': 'Business Admin disbursement register', 'column': 30, 'role': 'BUSINESS_ADMIN', 'kind': 'dropdown', 'options': ['10:00am', '1:00pm', '3:30pm'], 'auto_timestamp_key': 'register_ts'},
    {'key': 'register_approved', 'label': 'Register approved', 'column': 32, 'role': 'LOAN_APPROVER', 'kind': 'dropdown', 'options': ['Approved', 'Pending'], 'auto_timestamp_key': 'register_approved_ts'},
    {'key': 'disbursement', 'label': 'Finance disbursement', 'column': 33, 'role': 'FINANCE', 'kind': 'timestamp'},
]


def apply_global_register_defaults(config: ProductTatConfiguration) -> ProductTatConfiguration:
    """Apply the governed global-register adapter without exposing JSON editing."""
    config.sheet_name = GLOBAL_TAT_SHEET_NAME
    config.remarks_col = 35
    config.status_col = 34
    config.tat_start_col = 36
    config.stage_columns = {
        'created': 8,
        'bm_response_ts': 16,
        'decision_ts': 22,
        'minutes_shared_ts': 24,
        'sanctions_ts': 26,
        'bro_applied_ts': 28,
        'final_loan_amount': 29,
        'register_ts': 31,
    }
    config.stages = deepcopy(GLOBAL_TAT_STAGES)
    config.stage_tat_columns = [
        {
            'stage_key': stage['key'],
            'fallback_col': 39 + index,
            'aliases': [
                f"{stage['label']} TAT Minutes",
                f"{stage['label']} TAT",
                f"{stage['key']} TAT Minutes",
            ],
        }
        for index, stage in enumerate(GLOBAL_TAT_STAGES)
    ]
    return config


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
        'requires_valuation': bool(config.requires_valuation),
        'hocc_threshold': str(config.hocc_threshold) if config.hocc_threshold is not None else '',
    }


def resolve_tat_configuration(version: ProductVersion, *, requested_amount: Decimal) -> dict:
    """Freeze only stages applicable to this product and routing amount."""
    snapshot = serialize_tat_configuration(version)
    amount = Decimal(str(requested_amount))
    threshold_raw = snapshot.get('hocc_threshold')
    threshold = Decimal(str(threshold_raw)) if threshold_raw not in (None, '') else None
    valuation = bool(snapshot.get('requires_valuation'))
    hocc = threshold is not None and amount >= threshold

    applicable = []
    for stage in snapshot.get('stages') or []:
        key = str(stage.get('key') or '')
        if key == VALUATION_STAGE_KEY and not valuation:
            continue
        if key in HOCC_STAGE_KEYS and not hocc:
            continue
        applicable.append(stage)
    applicable_keys = {str(stage.get('key') or '') for stage in applicable}
    snapshot['stages'] = applicable
    snapshot['stage_tat_columns'] = [
        row for row in (snapshot.get('stage_tat_columns') or [])
        if str(row.get('stage_key') or '') in applicable_keys
    ]
    path = 'HOCC' if hocc else 'Standard'
    if valuation:
        path += ' + Valuation'
    snapshot['workflow_path'] = path
    snapshot['routing_amount'] = str(amount)
    return snapshot


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
        workflow_path=str(snapshot.get('workflow_path') or 'Standard'),
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
    from core.services.tat_tracker import PRODUCTS
    try:
        return PRODUCTS[case.product_key]
    except KeyError as exc:
        raise TatConfigurationError('This legacy case has no compatible static TAT configuration.') from exc


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

