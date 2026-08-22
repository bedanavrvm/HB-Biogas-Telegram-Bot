"""Verified, resumable deletion of closed SPIN/TAT pilot cycles.

The active pilot cycle is never eligible.  A purge freezes immutable record IDs,
removes matching Sheet rows bottom-up, re-reads each Sheet to prove absence, and
only then deletes the corresponding Django operational rows.  Drive files and
generic media metadata are deliberately outside this service.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from core.models import (
    GroupSheetConfiguration,
    SpinBatchReviewItem,
    SpinCreditRequest,
    TatTrackerApprovalCertificate,
    TatTrackerCase,
    WorkflowDataModeEvent,
    WorkflowDataModeState,
    WorkflowPilotFormulaReadiness,
    WorkflowPilotPurgeRun,
    WorkflowSlaEscalation,
    WorkflowTatDailyMetric,
)
from core.services.sheets import get_sheets_service
from core.services.spin_credit import configured_spin_batch_sheet_name, spin_request_id
from core.services.workflow_data_mode import (
    WORKFLOW_SPIN,
    WORKFLOW_TAT,
    get_state,
)


PURGE_SCOPES = {WORKFLOW_SPIN, WORKFLOW_TAT, 'both'}


def _workflows(scope: str) -> tuple[str, ...]:
    if scope == 'both':
        return (WORKFLOW_SPIN, WORKFLOW_TAT)
    if scope in {WORKFLOW_SPIN, WORKFLOW_TAT}:
        return (scope,)
    raise ValidationError({'scope': 'Select SPIN, TAT Tracker, or both.'})


def _require_superuser(actor) -> None:
    if not actor or not actor.is_active or not actor.is_superuser:
        raise PermissionDenied('Only an active Django Superuser may purge pilot data.')


def _stable_hash(value) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(',', ':'), default=str)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def _manifest_hash(manifest: dict) -> str:
    """Hash the purge population, not the transient preview timestamp."""
    identity = dict(manifest)
    identity.pop('cutoff_at', None)
    return _stable_hash(identity)


def _closed_pilot_filter(workflow: str, state, cutoff_at):
    return {
        'data_mode': 'pilot',
        'pilot_cycle_id__isnull': False,
        'created_at__lte': cutoff_at,
    }


def _closed_pilot_queryset(workflow: str, state, cutoff_at):
    prefix = 'spin' if workflow == WORKFLOW_SPIN else 'tat'
    model = SpinCreditRequest if workflow == WORKFLOW_SPIN else TatTrackerCase
    queryset = model.objects.filter(**_closed_pilot_filter(workflow, state, cutoff_at))
    return queryset.exclude(pilot_cycle_id=getattr(state, f'{prefix}_pilot_cycle_id'))


def _sheet_key(item: dict) -> str:
    return _stable_hash([item['workflow'], item['sheet_id'], item['sheet_tab']])


def build_manifest(scope: str, *, cutoff_at=None) -> dict:
    """Freeze only non-PII IDs and destinations for closed pilot rows."""
    cutoff_at = cutoff_at or timezone.now()
    state = get_state()
    records = []
    cycles = {workflow: set() for workflow in _workflows(scope)}
    configurations = {
        str(item.group_id): item
        for item in GroupSheetConfiguration.objects.filter(enabled=True)
    }
    for workflow in _workflows(scope):
        queryset = _closed_pilot_queryset(workflow, state, cutoff_at)
        for record in queryset.only(
            'pk', 'pilot_cycle_id', 'data_scope_key', 'group_id', 'sheet_id',
            'sheet_name', 'row_number', *([] if workflow == WORKFLOW_SPIN else ['case_id']),
            *([] if workflow == WORKFLOW_TAT else ['public_sequence_year', 'public_sequence_number']),
        ):
            configuration = configurations.get(str(record.group_id))
            sheet_id = str(record.sheet_id or getattr(configuration, 'sheet_id', '') or '')
            sheet_tab = str(record.sheet_name or '')
            if not sheet_tab and configuration and workflow == WORKFLOW_SPIN:
                sheet_tab = configured_spin_batch_sheet_name(
                    configuration.workflow or {}, configuration.sheet_name,
                )
            if not sheet_tab and configuration and workflow == WORKFLOW_TAT:
                from core.services.tat_tracker import product_by_key
                try:
                    sheet_tab = str(product_by_key(record.product_key).sheet_name or '')
                except ValueError:
                    sheet_tab = ''
            cycle = str(record.pilot_cycle_id or '')
            cycles[workflow].add(cycle)
            records.append({
                'workflow': workflow,
                'record_id': str(record.pk),
                'external_id': spin_request_id(record) if workflow == WORKFLOW_SPIN else record.case_id,
                'pilot_cycle_id': cycle,
                'data_scope_key': record.data_scope_key,
                'group_id': str(record.group_id),
                'sheet_id': sheet_id,
                'sheet_tab': sheet_tab,
                'destination_required': bool(configuration or sheet_id or sheet_tab),
                'recorded_row_number': record.row_number,
            })
    records.sort(key=lambda item: (item['workflow'], item['sheet_id'], item['sheet_tab'], item['external_id']))
    return {
        'version': 1,
        'scope': scope,
        'cutoff_at': cutoff_at.isoformat(),
        'state_versions': {
            'spin': state.spin_mode_version,
            'tat_tracker': state.tat_mode_version,
        },
        'active_cycles': {
            'spin': str(state.spin_pilot_cycle_id),
            'tat_tracker': str(state.tat_pilot_cycle_id),
        },
        'cycles': {key: sorted(value) for key, value in cycles.items()},
        'records': records,
    }


def preview_purge(scope: str) -> dict:
    manifest = build_manifest(scope)
    sheet_groups = defaultdict(int)
    counts = defaultdict(int)
    for item in manifest['records']:
        counts[item['workflow']] += 1
        if item['sheet_id'] and item['sheet_tab']:
            sheet_groups[(item['workflow'], item['sheet_id'], item['sheet_tab'])] += 1
    return {
        'manifest': manifest,
        'manifest_hash': _manifest_hash(manifest),
        'counts': dict(counts),
        'sheet_groups': [
            {'workflow': key[0], 'sheet_id': key[1], 'sheet_tab': key[2], 'count': count}
            for key, count in sorted(sheet_groups.items())
        ],
    }


def _worksheet(sheet_id: str, sheet_tab: str):
    service = get_sheets_service(sheet_id=sheet_id, sheet_name=sheet_tab)
    if not service.is_available():
        raise RuntimeError('The configured Google Sheet is unavailable.')
    worksheet = getattr(service, '_sheet', None)
    if worksheet is None:
        raise RuntimeError('The configured Google Sheet tab could not be opened.')
    return worksheet


def _sheet_layout(workflow: str, sheet_id: str, sheet_tab: str) -> dict:
    sheet = _worksheet(sheet_id, sheet_tab)
    values = sheet.get_all_values()
    formula_values = sheet.get_all_values(value_render_option='FORMULA')
    formulas = []
    for row_index, row in enumerate(formula_values, start=1):
        for column_index, value in enumerate(row, start=1):
            text = str(value or '')
            if text.startswith('='):
                formulas.append([row_index, column_index, text])

    if workflow == WORKFLOW_TAT:
        id_column = 0
        data_start_row = 5
        header_row = 2
    else:
        id_column = None
        header_row = None
        for row_index, row in enumerate(values[:10], start=1):
            for column_index, value in enumerate(row):
                if str(value or '').strip().casefold() in {'request id', 'spin request id'}:
                    header_row = row_index
                    id_column = column_index
                    break
            if id_column is not None:
                break
        if id_column is None:
            raise RuntimeError('The SPIN Sheet does not expose a Request ID header.')
        data_start_row = header_row + 1

    configuration = {
        'workflow': workflow,
        'sheet_id': sheet_id,
        'sheet_tab': sheet_tab,
        'header_row': header_row,
        'data_start_row': data_start_row,
        'id_column': id_column,
    }
    return {
        **configuration,
        'configuration_fingerprint': _stable_hash(configuration),
        'formula_fingerprint': _stable_hash(formulas),
        'formula_count': len(formulas),
        'values': values,
        'sheet': sheet,
    }


def inspect_sheet_readiness(workflow: str, sheet_id: str, sheet_tab: str) -> dict:
    layout = _sheet_layout(workflow, sheet_id, sheet_tab)
    acknowledged = WorkflowPilotFormulaReadiness.objects.filter(
        workflow=workflow,
        sheet_id=sheet_id,
        sheet_tab=sheet_tab,
        configuration_fingerprint=layout['configuration_fingerprint'],
        formula_fingerprint=layout['formula_fingerprint'],
    ).exists()
    return {
        key: layout[key] for key in (
            'workflow', 'sheet_id', 'sheet_tab', 'header_row', 'data_start_row',
            'id_column', 'configuration_fingerprint', 'formula_fingerprint', 'formula_count',
        )
    } | {'acknowledged': acknowledged}


def acknowledge_sheet_readiness(
    workflow: str,
    sheet_id: str,
    sheet_tab: str,
    *,
    actor,
    note: str,
) -> WorkflowPilotFormulaReadiness:
    _require_superuser(actor)
    note = (note or '').strip()
    if not note:
        raise ValidationError({'note': 'Record what was checked before acknowledging this Sheet layout.'})
    inspection = inspect_sheet_readiness(workflow, sheet_id, sheet_tab)
    config = GroupSheetConfiguration.objects.filter(sheet_id=sheet_id).first()
    readiness, _ = WorkflowPilotFormulaReadiness.objects.get_or_create(
        workflow=workflow,
        sheet_id=sheet_id,
        sheet_tab=sheet_tab,
        configuration_fingerprint=inspection['configuration_fingerprint'],
        formula_fingerprint=inspection['formula_fingerprint'],
        defaults={
            'group_configuration': config,
            'note': note,
            'acknowledged_by': actor,
        },
    )
    return readiness


def _manifest_sheet_groups(manifest: dict) -> dict[tuple[str, str, str], list[dict]]:
    groups = defaultdict(list)
    for item in manifest.get('records') or []:
        if item['sheet_id'] and item['sheet_tab']:
            groups[(item['workflow'], item['sheet_id'], item['sheet_tab'])].append(item)
    return groups


def _unresolved_destinations(manifest: dict) -> list[dict]:
    return [
        item for item in manifest.get('records') or []
        if item.get('destination_required') and not (item.get('sheet_id') and item.get('sheet_tab'))
    ]


def _validate_manifest_against_state(manifest: dict, state) -> None:
    for workflow in _workflows(manifest['scope']):
        prefix = 'spin' if workflow == WORKFLOW_SPIN else 'tat'
        if manifest['state_versions'][workflow] != getattr(state, f'{prefix}_mode_version'):
            raise ValidationError('The workflow mode or pilot cycle changed. Generate a new purge preview.')
        active = str(getattr(state, f'{prefix}_pilot_cycle_id'))
        if any(item['pilot_cycle_id'] == active for item in manifest['records'] if item['workflow'] == workflow):
            raise ValidationError('The active pilot cycle can never be purged. Rotate it first.')


@transaction.atomic
def start_purge(
    scope: str,
    manifest_hash: str,
    *,
    actor,
    reason: str,
    request_id: str = '',
) -> tuple[WorkflowPilotPurgeRun, bool]:
    """Acquire workflow locks and freeze a fresh manifest; no Sheet write occurs here."""
    _require_superuser(actor)
    reason = (reason or '').strip()
    if not reason:
        raise ValidationError({'reason': 'A purge reason is required.'})
    if request_id:
        prior = WorkflowPilotPurgeRun.objects.filter(scope=scope, request_id=request_id).first()
        if prior:
            return prior, True

    state = get_state(for_update=True)
    manifest = build_manifest(scope)
    actual_hash = _manifest_hash(manifest)
    if not manifest_hash or manifest_hash != actual_hash:
        raise ValidationError('The purge preview is stale. Preview the eligible rows again.')
    _validate_manifest_against_state(manifest, state)
    if not manifest['records']:
        raise ValidationError('There are no closed pilot records to purge.')
    if _unresolved_destinations(manifest):
        raise ValidationError(
            'One or more pilot rows have a configured Sheet destination that cannot be resolved. Repair their Sheet metadata first.'
        )
    for workflow in _workflows(scope):
        prefix = 'spin' if workflow == WORKFLOW_SPIN else 'tat'
        if getattr(state, f'active_{prefix}_purge_id'):
            raise ValidationError(f'Another {workflow} pilot purge is already active.')
    for (workflow, sheet_id, sheet_tab), _items in _manifest_sheet_groups(manifest).items():
        readiness = inspect_sheet_readiness(workflow, sheet_id, sheet_tab)
        if not readiness['acknowledged']:
            raise ValidationError(
                f'Acknowledge the formula/range readiness check for {sheet_tab} before purging.'
            )

    run = WorkflowPilotPurgeRun.objects.create(
        scope=scope,
        status='pending',
        reason=reason,
        request_id=request_id,
        manifest=manifest,
        manifest_hash=actual_hash,
        progress={'verified_sheet_groups': [], 'deleted_records': 0},
        cutoff_at=timezone.datetime.fromisoformat(manifest['cutoff_at']),
        requested_by=actor,
    )
    update_fields = []
    for workflow in _workflows(scope):
        prefix = 'spin' if workflow == WORKFLOW_SPIN else 'tat'
        setattr(state, f'active_{prefix}_purge_id', run.pk)
        update_fields.append(f'active_{prefix}_purge_id')
        WorkflowDataModeEvent.objects.create(
            workflow=workflow,
            action='purge_started',
            reason=reason,
            request_id=f'{request_id}:{workflow}' if request_id else '',
            actor=actor,
            metadata={'purge_run_id': str(run.pk), 'record_count': sum(
                1 for item in manifest['records'] if item['workflow'] == workflow
            )},
        )
    state.updated_by = actor
    state.save(update_fields=[*update_fields, 'updated_by', 'updated_at'])
    return run, False


def _rows_for_ids(layout: dict, target_ids: set[str]) -> dict[str, list[int]]:
    found = defaultdict(list)
    for row_number, row in enumerate(layout['values'], start=1):
        if row_number < layout['data_start_row']:
            continue
        value = str(row[layout['id_column']] if len(row) > layout['id_column'] else '').strip().lstrip("'")
        if value in target_ids:
            found[value].append(row_number)
    return found


def _verify_and_delete_sheet_group(workflow: str, sheet_id: str, sheet_tab: str, items: list[dict]) -> dict:
    layout = _sheet_layout(workflow, sheet_id, sheet_tab)
    readiness_exists = WorkflowPilotFormulaReadiness.objects.filter(
        workflow=workflow, sheet_id=sheet_id, sheet_tab=sheet_tab,
        configuration_fingerprint=layout['configuration_fingerprint'],
        formula_fingerprint=layout['formula_fingerprint'],
    ).exists()
    if not readiness_exists:
        raise RuntimeError('The Sheet layout changed after confirmation; purge stopped safely.')
    target_ids = {item['external_id'] for item in items}
    found = _rows_for_ids(layout, target_ids)
    delete_rows = sorted({row for rows in found.values() for row in rows}, reverse=True)
    if not hasattr(layout['sheet'], 'delete_rows'):
        raise RuntimeError('The configured Sheet adapter cannot delete rows.')
    for row_number in delete_rows:
        layout['sheet'].delete_rows(row_number)
    verified = _sheet_layout(workflow, sheet_id, sheet_tab)
    remaining = _rows_for_ids(verified, target_ids)
    if remaining:
        raise RuntimeError('One or more pilot IDs are still present after Sheet deletion.')
    _repair_row_pointers(workflow, sheet_id, sheet_tab, verified)
    return {'deleted_sheet_rows': len(delete_rows), 'target_count': len(target_ids)}


def _repair_row_pointers(workflow: str, sheet_id: str, sheet_tab: str, layout: dict) -> None:
    """Recalculate surviving Django row pointers from the verified live Sheet."""
    row_by_id = {}
    for row_number, row in enumerate(layout['values'], start=1):
        if row_number < layout['data_start_row']:
            continue
        external_id = str(
            row[layout['id_column']] if len(row) > layout['id_column'] else ''
        ).strip().lstrip("'")
        if external_id:
            row_by_id[external_id] = row_number
    model = SpinCreditRequest if workflow == WORKFLOW_SPIN else TatTrackerCase
    for record in model.objects.filter(sheet_id=sheet_id, sheet_name=sheet_tab).iterator():
        external_id = spin_request_id(record) if workflow == WORKFLOW_SPIN else record.case_id
        row_number = row_by_id.get(external_id)
        if row_number and record.row_number != row_number:
            model.objects.filter(pk=record.pk).update(row_number=row_number)


def _delete_local_items(items: list[dict]) -> int:
    if not items:
        return 0
    workflow = items[0]['workflow']
    ids = [item['record_id'] for item in items]
    cycles = {item['pilot_cycle_id'] for item in items}
    if workflow == WORKFLOW_SPIN:
        queryset = SpinCreditRequest.objects.filter(pk__in=ids, data_mode='pilot')
        if queryset.exclude(pilot_cycle_id__in=cycles).exists():
            raise RuntimeError('The SPIN manifest no longer matches the database rows.')
        count = queryset.count()
        queryset.delete()
        return count
    queryset = TatTrackerCase.objects.filter(pk__in=ids, data_mode='pilot')
    if queryset.exclude(pilot_cycle_id__in=cycles).exists():
        raise RuntimeError('The TAT manifest no longer matches the database rows.')
    TatTrackerApprovalCertificate.objects.filter(case__in=queryset).delete()
    count = queryset.count()
    queryset.delete()
    return count


def process_purge(run_id) -> WorkflowPilotPurgeRun:
    """Resume a frozen run. Completed Sheet groups are never repeated."""
    run = WorkflowPilotPurgeRun.objects.get(pk=run_id)
    if run.status in {'completed', 'cancelled'}:
        return run
    with transaction.atomic():
        locked = WorkflowPilotPurgeRun.objects.select_for_update().get(pk=run.pk)
        if locked.status == 'running':
            stale_before = timezone.now() - timedelta(minutes=5)
            if locked.heartbeat_at and locked.heartbeat_at > stale_before:
                raise ValidationError('This purge run is already being processed.')
        state = get_state(for_update=True)
        _validate_manifest_against_state(locked.manifest, state)
        locked.status = 'running'
        locked.started_at = locked.started_at or timezone.now()
        locked.heartbeat_at = timezone.now()
        locked.failures = []
        locked.save(update_fields=['status', 'started_at', 'heartbeat_at', 'failures', 'updated_at'])

    verified_keys = set((run.progress or {}).get('verified_sheet_groups') or [])
    failures = []
    deleted_records = int((run.progress or {}).get('deleted_records') or 0)
    try:
        grouped = _manifest_sheet_groups(run.manifest)
        sheet_backed_ids = set()
        for key, items in grouped.items():
            group_key = _stable_hash(key)
            sheet_backed_ids.update(item['record_id'] for item in items)
            if group_key not in verified_keys:
                _verify_and_delete_sheet_group(*key, items)
                verified_keys.add(group_key)
            deleted_records += _delete_local_items(items)
            run.progress = {
                'verified_sheet_groups': sorted(verified_keys),
                'deleted_records': deleted_records,
            }
            run.heartbeat_at = timezone.now()
            run.save(update_fields=['progress', 'heartbeat_at', 'updated_at'])

        local_only = [
            item for item in run.manifest['records'] if item['record_id'] not in sheet_backed_ids
        ]
        for workflow in _workflows(run.scope):
            items = [item for item in local_only if item['workflow'] == workflow]
            deleted_records += _delete_local_items(items)

        # Review queue items and reporting projections use the same frozen scope.
        for workflow in _workflows(run.scope):
            scopes = run.manifest['cycles'].get(workflow) or []
            scope_keys = [f'pilot:{cycle}' for cycle in scopes if cycle]
            if workflow == WORKFLOW_SPIN:
                SpinBatchReviewItem.objects.filter(data_mode='pilot', pilot_cycle_id__in=scopes).delete()
            else:
                WorkflowSlaEscalation.objects.filter(workflow='tat_tracker', data_scope_key__in=scope_keys).delete()
                WorkflowTatDailyMetric.objects.filter(workflow='tat_tracker', data_scope_key__in=scope_keys).delete()
    except Exception as exc:
        failures.append({'message': str(exc)[:500], 'at': timezone.now().isoformat()})
        WorkflowPilotPurgeRun.objects.filter(pk=run.pk).update(
            status='partial' if verified_keys else 'failed',
            progress={'verified_sheet_groups': sorted(verified_keys), 'deleted_records': deleted_records},
            failures=failures,
            heartbeat_at=timezone.now(),
        )
        return WorkflowPilotPurgeRun.objects.get(pk=run.pk)

    with transaction.atomic():
        run = WorkflowPilotPurgeRun.objects.select_for_update().get(pk=run.pk)
        state = get_state(for_update=True)
        run.status = 'completed'
        run.completed_at = timezone.now()
        run.heartbeat_at = run.completed_at
        run.progress = {'verified_sheet_groups': sorted(verified_keys), 'deleted_records': deleted_records}
        run.failures = []
        run.save(update_fields=['status', 'completed_at', 'heartbeat_at', 'progress', 'failures', 'updated_at'])
        update_fields = []
        for workflow in _workflows(run.scope):
            prefix = 'spin' if workflow == WORKFLOW_SPIN else 'tat'
            if getattr(state, f'active_{prefix}_purge_id') == run.pk:
                setattr(state, f'active_{prefix}_purge_id', None)
                update_fields.append(f'active_{prefix}_purge_id')
            WorkflowDataModeEvent.objects.create(
                workflow=workflow,
                action='purge_completed',
                reason=run.reason,
                actor=run.requested_by,
                metadata={
                    'purge_run_id': str(run.pk),
                    'record_count': sum(1 for item in run.manifest['records'] if item['workflow'] == workflow),
                },
            )
        if update_fields:
            state.save(update_fields=[*update_fields, 'updated_at'])
    return run
