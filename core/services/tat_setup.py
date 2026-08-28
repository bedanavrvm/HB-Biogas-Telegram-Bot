"""Guided TAT setup, version-safe stage maintenance, and Sheet cutover gates."""
from __future__ import annotations

import re
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from core.models import (
    AccessGrant, GroupSheetConfiguration, IntegrationOperation, ProductTatConfiguration,
    ProductVersion, SheetRegisterContract, SheetSyncAuditSnapshot, TatConfigurationEvent,
    TatResponsibilityAssignment, TatTrackerCase,
)
from core.services.product_catalog import clone_product_version
from core.services.tat_responsibilities import stage_catalog


class TatSetupError(ValueError):
    pass


def _slug(value: object) -> str:
    return re.sub(r'[^a-z0-9]+', '_', str(value or '').strip().casefold()).strip('_')


def stage_editor_rows(version: ProductVersion) -> list[dict]:
    config = getattr(version, 'tat_configuration', None)
    return [dict(item) for item in (getattr(config, 'stages', None) or [])]


def setup_readiness(group: GroupSheetConfiguration) -> dict:
    workflow = dict(group.workflow or {})
    branches = [str(value).strip() for value in workflow.get('branches') or [] if str(value).strip()]
    catalogue = stage_catalog(workflow)
    roles = sorted({str(row['role']) for row in catalogue})
    grants = AccessGrant.objects.filter(
        workflow='tat_tracker', active=True, user__is_active=True,
    ).filter(group_configuration__isnull=True) | AccessGrant.objects.filter(
        workflow='tat_tracker', active=True, user__is_active=True, group_configuration=group,
    )
    assignments = TatResponsibilityAssignment.objects.filter(group_configuration=group, active=True)
    unresolved = TatTrackerCase.objects.filter(
        group_id=group.group_id, is_deleted=False,
        configuration_binding_status=TatTrackerCase.CONFIG_UNRESOLVED,
    ).count()
    assumed = TatTrackerCase.objects.filter(
        group_id=group.group_id, is_deleted=False,
        configuration_binding_status=TatTrackerCase.CONFIG_LEGACY_ASSUMED,
    ).count()
    steps = [
        {'key': 'foundation', 'label': 'Group and branches', 'complete': bool(group.enabled and branches)},
        {'key': 'products', 'label': 'Products', 'complete': bool(catalogue)},
        {'key': 'stages', 'label': 'Stage design', 'complete': bool(catalogue and all(row.get('role') for row in catalogue))},
        {'key': 'access', 'label': 'Access coverage', 'complete': bool(roles and grants.exists())},
        {'key': 'routing', 'label': 'Responsibilities', 'complete': bool(assignments.exists())},
        {'key': 'alerts', 'label': 'Alerts and SLA', 'complete': str(workflow.get('tat_notification_mode') or '') in {'group', 'shadow', 'hybrid'}},
        {'key': 'projection', 'label': 'Register projection', 'complete': (
            not group.tat_sheet_projection_enabled or SheetRegisterContract.objects.filter(
                group_configuration=group, subject_type=SheetRegisterContract.SUBJECT_TAT_CASE,
                enabled=True,
            ).exists()
        )},
        {'key': 'review', 'label': 'Review', 'complete': not unresolved},
    ]
    first_blocked = next((row['key'] for row in steps if not row['complete']), 'review')
    return {
        'steps': steps, 'complete_count': sum(int(row['complete']) for row in steps),
        'total_count': len(steps), 'first_blocked': first_blocked,
        'legacy_assumed_count': assumed, 'unresolved_count': unresolved,
    }


@transaction.atomic
def save_stage_design(
    *, version: ProductVersion, stages: list[dict], actor, expected_updated_at: str,
    reason: str, request_id: str,
) -> ProductVersion:
    if not getattr(actor, 'is_superuser', False):
        raise TatSetupError('Only a Django Superuser may change TAT stages.')
    reason = str(reason or '').strip()
    request_id = str(request_id or '').strip()
    if len(reason) < 10:
        raise TatSetupError('Explain the stage change (at least 10 characters).')
    if not request_id:
        raise TatSetupError('A request ID is required.')
    existing = TatConfigurationEvent.objects.filter(action='stage_design_saved', request_id=request_id).first()
    if existing:
        return ProductVersion.objects.get(pk=existing.metadata['product_version_id'])
    source = ProductVersion.objects.select_for_update().select_related('product').get(pk=version.pk)
    if expected_updated_at and source.updated_at.isoformat() != str(expected_updated_at):
        raise TatSetupError('This product version changed in another session. Reload before saving.')
    if source.status != ProductVersion.STATUS_DRAFT:
        existing_draft = source.product.versions.filter(status=ProductVersion.STATUS_DRAFT).first()
        if existing_draft:
            raise TatSetupError(
                f'Editable version {existing_draft.version} already exists. Return to setup and open that draft.'
            )
        source = clone_product_version(source, actor=actor)
        source = ProductVersion.objects.select_for_update().select_related('product').get(pk=source.pk)
    if not isinstance(stages, list) or not stages:
        raise TatSetupError('Add at least one TAT stage.')
    normalized = []
    keys = set()
    columns = set()
    for position, raw in enumerate(stages, start=1):
        key = _slug(raw.get('key'))
        label = str(raw.get('label') or '').strip()
        role = str(raw.get('role') or '').strip().upper()
        kind = str(raw.get('kind') or 'timestamp').strip().lower()
        try:
            column = int(raw.get('column') or 0)
        except (TypeError, ValueError) as exc:
            raise TatSetupError(f'Stage {position} needs a valid Sheet column number.') from exc
        if not key or not label or not role:
            raise TatSetupError(f'Stage {position} needs a key, label, and responsible role.')
        if key in keys:
            raise TatSetupError(f'Stage key "{key}" is duplicated.')
        if column < 1 or column in columns:
            raise TatSetupError(f'Stage {position} needs a unique positive Sheet column.')
        if kind not in {'timestamp', 'dropdown'}:
            raise TatSetupError(f'Stage {position} has an unsupported control type.')
        options = [str(value).strip() for value in raw.get('options') or [] if str(value).strip()]
        if kind == 'dropdown' and not options:
            raise TatSetupError(f'Stage {position} is a dropdown and needs at least one option.')
        normalized.append({
            'key': key, 'label': label, 'column': column, 'role': role, 'kind': kind,
            'options': options, 'auto_timestamp_key': _slug(raw.get('auto_timestamp_key')),
            'requires_signature_certificate': bool(raw.get('requires_signature_certificate', False)),
        })
        keys.add(key)
        columns.add(column)
    config = ProductTatConfiguration.objects.select_for_update().filter(product_version=source).first()
    if not config:
        raise TatSetupError('Configure the product TAT adapter before designing stages.')
    before = {'stages': list(config.stages or [])}
    config.stages = normalized
    config.save(update_fields=['stages'])
    # Touch the draft to supply an optimistic-concurrency token for the next edit.
    source.save(update_fields=['updated_at'])
    TatConfigurationEvent.objects.create(
        action='stage_design_saved', actor=actor, request_id=request_id, reason=reason,
        before_snapshot=before, after_snapshot={'stages': normalized},
        metadata={'product_version_id': str(source.pk), 'product_code': source.product.code},
    )
    return source


def sheet_cutover_readiness(group: GroupSheetConfiguration) -> dict:
    contract = SheetRegisterContract.objects.filter(
        group_configuration=group, subject_type=SheetRegisterContract.SUBJECT_TAT_CASE,
        enabled=True,
    ).first()
    snapshots = SheetSyncAuditSnapshot.objects.filter(contract=contract) if contract else SheetSyncAuditSnapshot.objects.none()
    healthy = snapshots.filter(
        status=SheetSyncAuditSnapshot.STATUS_HEALTHY, discrepancy_count=0,
    ).order_by('-created_at')
    observed = snapshots.filter(created_at__lte=timezone.now() - timedelta(days=7)).exists()
    legacy = TatTrackerCase.objects.filter(
        group_id=group.group_id, is_deleted=False,
    ).exclude(configuration_binding_status=TatTrackerCase.CONFIG_VERSIONED).count()
    pending_ops = IntegrationOperation.objects.filter(
        integration=IntegrationOperation.INTEGRATION_GOOGLE_SHEETS,
        status__in=[
            IntegrationOperation.STATUS_PENDING, IntegrationOperation.STATUS_RUNNING,
            IntegrationOperation.STATUS_RETRYABLE, IntegrationOperation.STATUS_DEAD_LETTER,
        ],
    ).filter(metadata__group_id=group.group_id).count()
    blockers = []
    if not contract:
        blockers.append('No governed TAT Sheet register contract exists.')
    if not observed:
        blockers.append('The parallel observation period has not reached seven days.')
    if healthy.count() < 3:
        blockers.append('Fewer than three discrepancy-free parity audits are recorded.')
    latest = snapshots.order_by('-created_at').first()
    if not latest or latest.status != SheetSyncAuditSnapshot.STATUS_HEALTHY or latest.discrepancy_count:
        blockers.append('The latest parity audit is not healthy.')
    if legacy:
        blockers.append(f'{legacy} case(s) still lack an exact version binding.')
    if pending_ops:
        blockers.append(f'{pending_ops} Sheet operation(s) are pending or failed.')
    return {'ready': not blockers, 'blockers': blockers, 'healthy_audits': healthy.count(), 'legacy_cases': legacy, 'pending_operations': pending_ops}


@transaction.atomic
def disable_sheet_projection(*, group: GroupSheetConfiguration, actor, reason: str, request_id: str):
    if not getattr(actor, 'is_superuser', False):
        raise TatSetupError('Only a Django Superuser may disable TAT Sheet projection.')
    reason = str(reason or '').strip()
    request_id = str(request_id or '').strip()
    if len(reason) < 10 or not request_id:
        raise TatSetupError('A reason and request ID are required for Sheet cutover.')
    existing = TatConfigurationEvent.objects.filter(action='sheet_projection_disabled', request_id=request_id).first()
    if existing:
        return GroupSheetConfiguration.objects.get(pk=group.pk)
    group = GroupSheetConfiguration.objects.select_for_update().get(pk=group.pk)
    readiness = sheet_cutover_readiness(group)
    if not readiness['ready']:
        raise TatSetupError('Sheet projection cannot be disabled: ' + ' '.join(readiness['blockers']))
    group.tat_sheet_projection_enabled = False
    group.tat_sheet_projection_disabled_at = timezone.now()
    group.save(update_fields=['tat_sheet_projection_enabled', 'tat_sheet_projection_disabled_at', 'updated_at'])
    TatConfigurationEvent.objects.create(
        group_configuration=group, action='sheet_projection_disabled', actor=actor,
        request_id=request_id, reason=reason,
        before_snapshot={'enabled': True}, after_snapshot={'enabled': False},
        metadata=readiness,
    )
    return group


@transaction.atomic
def enable_sheet_projection(*, group: GroupSheetConfiguration, actor, reason: str, request_id: str):
    if not getattr(actor, 'is_superuser', False):
        raise TatSetupError('Only a Django Superuser may enable TAT Sheet projection.')
    reason = str(reason or '').strip()
    request_id = str(request_id or '').strip()
    if len(reason) < 10 or not request_id:
        raise TatSetupError('A reason and request ID are required to enable Sheet projection.')
    existing = TatConfigurationEvent.objects.filter(action='sheet_projection_enabled', request_id=request_id).first()
    if existing:
        return GroupSheetConfiguration.objects.get(pk=group.pk)
    group = GroupSheetConfiguration.objects.select_for_update().get(pk=group.pk)
    if not group.sheet_id:
        raise TatSetupError('Configure the Google Sheet ID before enabling projection.')
    if not SheetRegisterContract.objects.filter(
        group_configuration=group, subject_type=SheetRegisterContract.SUBJECT_TAT_CASE,
        enabled=True,
    ).exists():
        raise TatSetupError('Create and enable the governed TAT Sheet register contract first.')
    group.tat_sheet_projection_enabled = True
    group.tat_sheet_projection_disabled_at = None
    group.save(update_fields=['tat_sheet_projection_enabled', 'tat_sheet_projection_disabled_at', 'updated_at'])
    TatConfigurationEvent.objects.create(
        group_configuration=group, action='sheet_projection_enabled', actor=actor,
        request_id=request_id, reason=reason,
        before_snapshot={'enabled': False}, after_snapshot={'enabled': True},
    )
    return group
