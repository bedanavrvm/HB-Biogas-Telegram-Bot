"""Governed SPIN/TAT pilot cycles and centralized operational visibility.

Records take a mode/cycle snapshot when they are created.  Changing the
switchboard never relabels historical rows.  Normal operational queries must
use the helpers in this module so closed pilot cycles cannot leak into live
queues or SLA reporting.
"""
from __future__ import annotations

from dataclasses import dataclass
import uuid

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q, QuerySet

from core.models import (
    SpinBatchReviewItem,
    SpinCreditRequest,
    TatTrackerCase,
    WorkflowDataModeEvent,
    WorkflowDataModeState,
    WORKFLOW_DATA_MODE_PILOT,
    WORKFLOW_DATA_MODE_PRODUCTION,
)


WORKFLOW_SPIN = 'spin'
WORKFLOW_TAT = 'tat_tracker'
WORKFLOWS = {WORKFLOW_SPIN, WORKFLOW_TAT}


class WorkflowModeChanged(RuntimeError):
    """A cached client attempted to mutate a row outside the active scope."""

    code = 'WORKFLOW_MODE_CHANGED'

    def __init__(self, message='The workflow mode changed. Reload to continue safely.'):
        super().__init__(message)


@dataclass(frozen=True)
class WorkflowModeSnapshot:
    workflow: str
    mode: str
    pilot_cycle_id: uuid.UUID
    mode_version: int

    @property
    def data_scope_key(self) -> str:
        if self.mode == WORKFLOW_DATA_MODE_PRODUCTION:
            return WORKFLOW_DATA_MODE_PRODUCTION
        return f'{WORKFLOW_DATA_MODE_PILOT}:{self.pilot_cycle_id}'

    def creation_fields(self) -> dict:
        return {
            'data_mode': self.mode,
            'pilot_cycle_id': self.pilot_cycle_id if self.mode == WORKFLOW_DATA_MODE_PILOT else None,
            'data_scope_key': self.data_scope_key,
        }


def _validate_workflow(workflow: str) -> str:
    if workflow not in WORKFLOWS:
        raise ValueError(f'Unsupported workflow: {workflow}')
    return workflow


def get_state(*, for_update: bool = False) -> WorkflowDataModeState:
    queryset = WorkflowDataModeState.objects
    if for_update:
        queryset = queryset.select_for_update()
    state, _ = queryset.get_or_create(pk=WorkflowDataModeState.SINGLETON_PK)
    return state


def mode_snapshot(workflow: str, *, for_update: bool = False) -> WorkflowModeSnapshot:
    _validate_workflow(workflow)
    state = get_state(for_update=for_update)
    prefix = 'spin' if workflow == WORKFLOW_SPIN else 'tat'
    return WorkflowModeSnapshot(
        workflow=workflow,
        mode=getattr(state, f'{prefix}_mode'),
        pilot_cycle_id=getattr(state, f'{prefix}_pilot_cycle_id'),
        mode_version=getattr(state, f'{prefix}_mode_version'),
    )


def operational_q(workflow: str, *, snapshot: WorkflowModeSnapshot | None = None) -> Q:
    snapshot = snapshot or mode_snapshot(workflow)
    query = Q(data_mode=WORKFLOW_DATA_MODE_PRODUCTION)
    if snapshot.mode == WORKFLOW_DATA_MODE_PILOT:
        query |= Q(
            data_mode=WORKFLOW_DATA_MODE_PILOT,
            pilot_cycle_id=snapshot.pilot_cycle_id,
        )
    return query


def operational_spin_requests(queryset: QuerySet | None = None) -> QuerySet:
    queryset = queryset if queryset is not None else SpinCreditRequest.objects.all()
    return queryset.filter(operational_q(WORKFLOW_SPIN))


def operational_spin_review_items(queryset: QuerySet | None = None) -> QuerySet:
    queryset = queryset if queryset is not None else SpinBatchReviewItem.objects.all()
    return queryset.filter(operational_q(WORKFLOW_SPIN))


def operational_tat_cases(queryset: QuerySet | None = None) -> QuerySet:
    queryset = queryset if queryset is not None else TatTrackerCase.objects.all()
    return queryset.filter(operational_q(WORKFLOW_TAT))


def is_record_operational(record, *, snapshot: WorkflowModeSnapshot | None = None) -> bool:
    workflow = WORKFLOW_SPIN if isinstance(record, (SpinCreditRequest, SpinBatchReviewItem)) else WORKFLOW_TAT
    snapshot = snapshot or mode_snapshot(workflow)
    if record.data_mode == WORKFLOW_DATA_MODE_PRODUCTION:
        return True
    return (
        snapshot.mode == WORKFLOW_DATA_MODE_PILOT
        and record.pilot_cycle_id == snapshot.pilot_cycle_id
    )


def assert_record_writable(record, *, expected_mode_version: int | None = None) -> WorkflowModeSnapshot:
    workflow = WORKFLOW_SPIN if isinstance(record, (SpinCreditRequest, SpinBatchReviewItem)) else WORKFLOW_TAT
    snapshot = mode_snapshot(workflow)
    if expected_mode_version is not None and expected_mode_version != snapshot.mode_version:
        raise WorkflowModeChanged()
    if not is_record_operational(record, snapshot=snapshot):
        raise WorkflowModeChanged(
            'This item belongs to a closed pilot cycle and is now read-only. Reload the queue.'
        )
    return snapshot


def _require_superuser(actor) -> None:
    if not actor or not actor.is_active or not actor.is_superuser:
        raise PermissionDenied('Only an active Django Superuser may change workflow modes.')


@transaction.atomic
def change_mode(
    workflow: str,
    new_mode: str,
    *,
    actor,
    reason: str,
    request_id: str = '',
) -> tuple[WorkflowDataModeState, WorkflowDataModeEvent, bool]:
    """Change one workflow's creation mode without relabelling existing rows."""
    _validate_workflow(workflow)
    _require_superuser(actor)
    reason = (reason or '').strip()
    if not reason:
        raise ValidationError({'reason': 'A reason is required.'})
    if new_mode not in {WORKFLOW_DATA_MODE_PILOT, WORKFLOW_DATA_MODE_PRODUCTION}:
        raise ValidationError({'mode': 'Select Pilot or Production.'})

    if request_id:
        prior = WorkflowDataModeEvent.objects.filter(
            workflow=workflow, action='mode_changed', request_id=request_id,
        ).first()
        if prior:
            return get_state(), prior, True

    state = get_state(for_update=True)
    prefix = 'spin' if workflow == WORKFLOW_SPIN else 'tat'
    if getattr(state, f'active_{prefix}_purge_id'):
        raise ValidationError('A pilot purge is active for this workflow. Finish it before changing the mode.')
    old_mode = getattr(state, f'{prefix}_mode')
    old_cycle = getattr(state, f'{prefix}_pilot_cycle_id')
    if old_mode == new_mode:
        raise ValidationError({'mode': f'{workflow} is already in {new_mode} mode.'})

    new_cycle = uuid.uuid4() if new_mode == WORKFLOW_DATA_MODE_PILOT else old_cycle
    setattr(state, f'{prefix}_mode', new_mode)
    setattr(state, f'{prefix}_pilot_cycle_id', new_cycle)
    setattr(state, f'{prefix}_mode_version', getattr(state, f'{prefix}_mode_version') + 1)
    state.updated_by = actor
    state.save(update_fields=[
        f'{prefix}_mode', f'{prefix}_pilot_cycle_id', f'{prefix}_mode_version',
        'updated_by', 'updated_at',
    ])
    event = WorkflowDataModeEvent.objects.create(
        workflow=workflow,
        action='mode_changed',
        old_mode=old_mode,
        new_mode=new_mode,
        old_cycle_id=old_cycle,
        new_cycle_id=new_cycle,
        reason=reason,
        request_id=request_id,
        actor=actor,
    )
    return state, event, False


@transaction.atomic
def rotate_pilot_cycle(
    workflow: str,
    *,
    actor,
    reason: str,
    request_id: str = '',
) -> tuple[WorkflowDataModeState, WorkflowDataModeEvent, bool]:
    """Close the active pilot cycle and start a fresh, purge-protected cycle."""
    _validate_workflow(workflow)
    _require_superuser(actor)
    reason = (reason or '').strip()
    if not reason:
        raise ValidationError({'reason': 'A reason is required.'})
    if request_id:
        prior = WorkflowDataModeEvent.objects.filter(
            workflow=workflow, action='cycle_rotated', request_id=request_id,
        ).first()
        if prior:
            return get_state(), prior, True

    state = get_state(for_update=True)
    prefix = 'spin' if workflow == WORKFLOW_SPIN else 'tat'
    if getattr(state, f'{prefix}_mode') != WORKFLOW_DATA_MODE_PILOT:
        raise ValidationError('Pilot cycles can only be rotated while the workflow is in Pilot mode.')
    if getattr(state, f'active_{prefix}_purge_id'):
        raise ValidationError('A pilot purge is active for this workflow. Finish it before rotating the cycle.')
    old_cycle = getattr(state, f'{prefix}_pilot_cycle_id')
    new_cycle = uuid.uuid4()
    setattr(state, f'{prefix}_pilot_cycle_id', new_cycle)
    setattr(state, f'{prefix}_mode_version', getattr(state, f'{prefix}_mode_version') + 1)
    state.updated_by = actor
    state.save(update_fields=[
        f'{prefix}_pilot_cycle_id', f'{prefix}_mode_version', 'updated_by', 'updated_at',
    ])
    event = WorkflowDataModeEvent.objects.create(
        workflow=workflow,
        action='cycle_rotated',
        old_mode=WORKFLOW_DATA_MODE_PILOT,
        new_mode=WORKFLOW_DATA_MODE_PILOT,
        old_cycle_id=old_cycle,
        new_cycle_id=new_cycle,
        reason=reason,
        request_id=request_id,
        actor=actor,
    )
    return state, event, False


def serialize_mode(workflow: str) -> dict:
    snapshot = mode_snapshot(workflow)
    return {
        'workflow': workflow,
        'mode': snapshot.mode,
        'mode_version': snapshot.mode_version,
        'pilot_cycle_id': str(snapshot.pilot_cycle_id) if snapshot.mode == WORKFLOW_DATA_MODE_PILOT else None,
        'is_pilot': snapshot.mode == WORKFLOW_DATA_MODE_PILOT,
    }
