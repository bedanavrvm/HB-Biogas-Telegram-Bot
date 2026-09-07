"""Explicit Superuser-only clean-slate reset for TAT database records.

The reset is deliberately database-only. It never calls Google Sheets,
Telegram, an e-signature provider, or file storage, and it preserves shared
catalogue, access-control, register-audit, and compliance-ledger records.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any
import uuid

from django.db import transaction

from core.models import (
    ComplianceAuditEvent,
    DurableJobRunnerHeartbeat,
    GroupSheetConfiguration,
    LiveSheetRecordChange,
    ProductAvailability,
    ProductTatConfiguration,
    TatActionTask,
    TatActionTaskLocator,
    TatActionTaskRecipient,
    TatCaseSequence,
    TatConfigurationEvent,
    TatEscalationRule,
    TatGroupExceptionStatus,
    TatNotificationProcessorRun,
    TatPresentationSettings,
    TatPrivateAlertConnection,
    TatPrivateAlertConnectionEvent,
    TatRepairJob,
    TatResponsibilityAssignment,
    TatResponsibilityBackup,
    TatResponsibilityChangePlan,
    TatResponsibilityEvent,
    TatTaskRerouteEvent,
    TatTrackerApprovalCertificate,
    TatTrackerCase,
    TatTrackerEvent,
    TatUpdateSideEffectDispatch,
    WorkflowConfigurationChangeRequest,
    WorkflowDataModeEvent,
    WorkflowDataModeState,
    WorkflowPilotFormulaReadiness,
    WorkflowPilotPurgeRun,
    WorkflowSlaEscalation,
    WorkflowTatDailyMetric,
    WorkflowTatMetricRebuildRequest,
    WorkflowTimelineAnnotation,
    WORKFLOW_DATA_MODE_PILOT,
)
from core.services.compliance_audit import record_event


WORKFLOW_TAT = 'tat_tracker'
TAT_REPAIR_RUNNER_KEY = 'tat_repairs'


class TatFullResetError(ValueError):
    """Stable validation failure exposed by the guarded Admin reset UI."""


@dataclass(frozen=True)
class TatResetTarget:
    group: str
    model: type
    filters: tuple[tuple[str, Any], ...] = ()
    tat_group_scoped: bool = False
    label: str = ''

    def queryset(self, *, tat_group_ids: tuple[str, ...]):
        queryset = self.model.objects.all()
        if self.filters:
            queryset = queryset.filter(**dict(self.filters))
        if self.tat_group_scoped:
            queryset = queryset.filter(group_id__in=tat_group_ids)
        return queryset

    @property
    def display_label(self) -> str:
        return self.label or str(self.model._meta.verbose_name_plural).title()


# Order is deletion order. Explicit children precede protected parents so the
# reset does not depend on broad cascades and every target can be previewed.
TAT_RESET_TARGETS = (
    TatResetTarget('Cases, tasks, and reporting', TatActionTaskLocator),
    TatResetTarget('Cases, tasks, and reporting', TatActionTaskRecipient),
    TatResetTarget('Cases, tasks, and reporting', TatTaskRerouteEvent),
    TatResetTarget('Cases, tasks, and reporting', TatActionTask),
    TatResetTarget('Cases, tasks, and reporting', TatTrackerApprovalCertificate),
    TatResetTarget('Cases, tasks, and reporting', TatUpdateSideEffectDispatch),
    TatResetTarget('Cases, tasks, and reporting', WorkflowTatMetricRebuildRequest),
    TatResetTarget('Cases, tasks, and reporting', TatTrackerEvent),
    TatResetTarget('Cases, tasks, and reporting', TatTrackerCase),
    TatResetTarget(
        'Cases, tasks, and reporting', WorkflowTatDailyMetric,
        filters=(('workflow', WORKFLOW_TAT),),
        label='TAT Tracker daily metrics',
    ),
    TatResetTarget(
        'Cases, tasks, and reporting', WorkflowSlaEscalation,
        filters=(('workflow', WORKFLOW_TAT),),
        label='TAT Tracker SLA escalations',
    ),
    TatResetTarget(
        'Cases, tasks, and reporting', WorkflowTimelineAnnotation,
        filters=(('workflow', WORKFLOW_TAT),),
        label='TAT Tracker timeline annotations',
    ),
    TatResetTarget(
        'Cases, tasks, and reporting', LiveSheetRecordChange,
        tat_group_scoped=True,
        label='TAT group live-Sheet change records',
    ),

    TatResetTarget('Routing and notifications', TatResponsibilityBackup),
    TatResetTarget('Routing and notifications', TatResponsibilityChangePlan),
    TatResetTarget('Routing and notifications', TatResponsibilityEvent),
    TatResetTarget('Routing and notifications', TatResponsibilityAssignment),
    TatResetTarget('Routing and notifications', TatPrivateAlertConnectionEvent),
    TatResetTarget('Routing and notifications', TatPrivateAlertConnection),
    TatResetTarget('Routing and notifications', TatGroupExceptionStatus),
    TatResetTarget('Routing and notifications', TatNotificationProcessorRun),
    TatResetTarget('Routing and notifications', TatRepairJob),
    TatResetTarget(
        'Routing and notifications', DurableJobRunnerHeartbeat,
        filters=(('runner_key', TAT_REPAIR_RUNNER_KEY),),
        label='TAT repair runner heartbeat',
    ),

    TatResetTarget('TAT configuration', TatEscalationRule),
    TatResetTarget('TAT configuration', TatConfigurationEvent),
    TatResetTarget('TAT configuration', TatPresentationSettings),
    TatResetTarget('TAT configuration', ProductTatConfiguration),
    TatResetTarget('TAT configuration', TatCaseSequence),
    TatResetTarget(
        'TAT configuration', ProductAvailability,
        filters=(('workflow', WORKFLOW_TAT),),
        label='TAT-specific product availability',
    ),
    TatResetTarget(
        'TAT configuration', WorkflowConfigurationChangeRequest,
        filters=(('workflow', WORKFLOW_TAT),),
        label='TAT configuration change requests',
    ),

    TatResetTarget(
        'Pilot and mode history', WorkflowDataModeEvent,
        filters=(('workflow', WORKFLOW_TAT),),
        label='TAT data-mode events',
    ),
    TatResetTarget(
        'Pilot and mode history', WorkflowPilotFormulaReadiness,
        filters=(('workflow', WORKFLOW_TAT),),
        label='TAT pilot Sheet readiness records',
    ),
    TatResetTarget(
        'Pilot and mode history', WorkflowPilotPurgeRun,
        filters=(('scope', WORKFLOW_TAT),),
        label='TAT-only pilot purge runs',
    ),
)

TAT_RESET_MODELS = tuple(dict.fromkeys(
    target.model
    for target in TAT_RESET_TARGETS
    if target.model.__name__.startswith(('Tat', 'WorkflowTat', 'ProductTat'))
))


def _tat_group_ids() -> tuple[str, ...]:
    return tuple(sorted({
        str(group_id)
        for group_id, workflow in GroupSheetConfiguration.objects.values_list('group_id', 'workflow')
        if str((workflow or {}).get('type') or '').strip() == WORKFLOW_TAT
    }))


def preview_full_tat_reset() -> dict[str, Any]:
    """Count every database row selected by the TAT clean-slate reset."""
    tat_group_ids = _tat_group_ids()
    grouped: dict[str, list[dict[str, Any]]] = {}
    counts: dict[str, int] = {}
    total = 0
    for target in TAT_RESET_TARGETS:
        count = target.queryset(tat_group_ids=tat_group_ids).count()
        key = target.model._meta.label
        counts[key] = count
        total += count
        grouped.setdefault(target.group, []).append({
            'model': key,
            'label': target.display_label,
            'count': count,
        })
    groups = [
        {
            'label': group_label,
            'count': sum(item['count'] for item in models),
            'models': models,
        }
        for group_label, models in grouped.items()
    ]
    return {
        'groups': groups,
        'counts': counts,
        'total': total,
        'tat_group_ids': tat_group_ids,
    }


def _delete_target(target: TatResetTarget, *, tat_group_ids: tuple[str, ...], counts: Counter) -> None:
    queryset = target.queryset(tat_group_ids=tat_group_ids)
    count = queryset.count()
    if not count:
        return
    queryset.delete()
    counts[target.model._meta.label] += count


def _reset_tat_mode_state(*, actor) -> dict[str, Any]:
    state, _created = WorkflowDataModeState.objects.select_for_update().get_or_create(
        pk=WorkflowDataModeState.SINGLETON_PK,
    )
    before = {
        'tat_mode': state.tat_mode,
        'tat_pilot_cycle_id': str(state.tat_pilot_cycle_id),
        'tat_mode_version': state.tat_mode_version,
        'active_tat_purge_id': str(state.active_tat_purge_id) if state.active_tat_purge_id else None,
    }
    state.tat_mode = WORKFLOW_DATA_MODE_PILOT
    state.tat_pilot_cycle_id = uuid.uuid4()
    state.tat_mode_version += 1
    state.active_tat_purge_id = None
    state.updated_by = actor
    state.save(update_fields=[
        'tat_mode', 'tat_pilot_cycle_id', 'tat_mode_version',
        'active_tat_purge_id', 'updated_by', 'updated_at',
    ])
    return {
        'before': before,
        'after': {
            'tat_mode': state.tat_mode,
            'tat_pilot_cycle_id': str(state.tat_pilot_cycle_id),
            'tat_mode_version': state.tat_mode_version,
            'active_tat_purge_id': None,
        },
    }


@transaction.atomic
def reset_all_tat_data(
    *, actor, reason: str, request_id: str,
) -> dict[str, Any]:
    """Remove TAT database state without touching external or shared records."""
    if not getattr(actor, 'is_active', False) or not getattr(actor, 'is_superuser', False):
        raise TatFullResetError('The full reset is available only to an active Django Superuser.')
    normalized_reason = str(reason or '').strip()
    if not normalized_reason:
        raise TatFullResetError('Provide a reason for this permanent reset.')
    if len(normalized_reason) > 500:
        raise TatFullResetError('The reset reason must be 500 characters or fewer.')
    stable_request_id = str(request_id or '').strip()
    if not stable_request_id:
        raise TatFullResetError('A stable reset request ID is required.')
    if len(stable_request_id) > 128:
        raise TatFullResetError('The reset request ID must be 128 characters or fewer.')

    deduplication_key = f'tat:full-reset:{stable_request_id}'
    existing = ComplianceAuditEvent.objects.filter(deduplication_key=deduplication_key).first()
    if existing:
        existing_reason = str((existing.metadata or {}).get('reason') or '')
        if existing_reason != normalized_reason:
            raise TatFullResetError('This reset request ID was already used with a different reason.')
        return {
            'before': dict(existing.before_values or {}),
            'deleted': dict((existing.after_values or {}).get('deleted') or {}),
            'after': preview_full_tat_reset(),
            'mode_state': dict((existing.after_values or {}).get('mode_state') or {}),
            'reason': normalized_reason,
            'replayed': True,
        }

    before = preview_full_tat_reset()
    deleted: Counter[str] = Counter()
    tat_group_ids = tuple(before['tat_group_ids'])
    for target in TAT_RESET_TARGETS:
        _delete_target(target, tat_group_ids=tat_group_ids, counts=deleted)

    mode_state = _reset_tat_mode_state(actor=actor)
    after = preview_full_tat_reset()
    remaining = {label: count for label, count in after['counts'].items() if count}
    if remaining:
        raise TatFullResetError(f'The reset left TAT records behind: {remaining}')

    record_event(
        workflow=ComplianceAuditEvent.WORKFLOW_TAT,
        action='database_reset',
        category='administration',
        subject_type='tat_database',
        subject_id='all',
        actor=actor,
        authority_user=actor,
        request_id=stable_request_id,
        source_model='TatTrackerCase',
        deduplication_key=deduplication_key,
        before_values=before,
        after_values={
            'deleted': dict(sorted(deleted.items())),
            'remaining': {},
            'mode_state': mode_state,
            'external_systems_untouched': True,
        },
        metadata={
            'reason': normalized_reason,
            'scope': 'tat_database_only',
            'preserved': [
                'users', 'products', 'locations', 'workflow_groups', 'access_control',
                'sheet_register_audits', 'compliance_ledger', 'spin_state',
            ],
        },
        sensitive=True,
    )
    return {
        'before': before,
        'deleted': dict(sorted(deleted.items())),
        'after': after,
        'mode_state': mode_state,
        'reason': normalized_reason,
        'replayed': False,
    }
