"""Read-only SLA evaluation and idempotent escalation persistence.

Delivery is deliberately outside this module. A scheduled operator can first
review dry-run output, then persist pending follow-up records without causing
Telegram, Sheets, Drive, or workflow-state side effects.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation

from django.utils import timezone

from core.models import GroupSheetConfiguration, JawabuFarmerMaster, TatTrackerCase, WorkflowSlaEscalation
from core.services.jawabu_case360 import calculate_case_tat
from core.services.jawabu_pipeline import JAWABU_TERMINAL_STATES, current_workflow_state
from core.services.tat_tracker import (
    is_tat_tracker_workflow,
    next_action,
    product_by_key,
    stage_target_minutes,
    stage_tat_minutes,
)


@dataclass(frozen=True)
class WorkflowSlaCandidate:
    workflow: str
    subject_id: str
    group_id: str
    stage_key: str
    target_minutes: int
    overdue_minutes: int

    def payload(self) -> dict:
        return asdict(self)


def _positive_minutes(value) -> int | None:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return int(number)


def jawabu_sla_candidates(*, now=None) -> list[WorkflowSlaCandidate]:
    """Find incomplete configured Jawabu TAT segments that are overdue."""
    candidates: list[WorkflowSlaCandidate] = []
    for farmer in JawabuFarmerMaster.objects.filter(status='active').prefetch_related('pipeline_events'):
        if current_workflow_state(farmer) in JAWABU_TERMINAL_STATES | {'deferred'}:
            continue
        tat = calculate_case_tat(farmer, now=now)
        for stage in tat.get('stages') or []:
            if stage.get('completed_at') or stage.get('status') != 'over':
                continue
            target = _positive_minutes(stage.get('target_minutes'))
            elapsed = _positive_minutes(stage.get('minutes'))
            if not target or elapsed is None:
                continue
            candidates.append(WorkflowSlaCandidate(
                workflow='jawabu_pipeline',
                subject_id=str(farmer.pk),
                group_id='',
                stage_key=str(stage.get('key') or ''),
                target_minutes=target,
                overdue_minutes=max(0, elapsed - target),
            ))
    return candidates


def tat_sla_candidates(*, now=None) -> list[WorkflowSlaCandidate]:
    """Find active TAT cases whose current configured stage is overdue."""
    candidates: list[WorkflowSlaCandidate] = []
    configs = [config for config in GroupSheetConfiguration.objects.filter(enabled=True) if is_tat_tracker_workflow(config)]
    for config in configs:
        workflow = config.workflow or {}
        cases = TatTrackerCase.objects.filter(group_id=str(config.group_id), is_deleted=False, status='Active')
        for case in cases:
            stage = next_action(case)
            if not stage:
                continue
            product = product_by_key(case.product_key)
            target = stage_target_minutes(workflow, product, stage)
            elapsed = stage_tat_minutes(case, stage, now=now)
            target_value = _positive_minutes(target)
            elapsed_value = _positive_minutes(elapsed)
            if not target_value or elapsed_value is None or elapsed_value <= target_value:
                continue
            candidates.append(WorkflowSlaCandidate(
                workflow='tat_tracker',
                subject_id=str(case.pk),
                group_id=str(case.group_id),
                stage_key=stage.key,
                target_minutes=target_value,
                overdue_minutes=elapsed_value - target_value,
            ))
    return candidates


def collect_sla_candidates(*, workflow: str = 'all', now=None) -> list[WorkflowSlaCandidate]:
    selected = str(workflow or 'all')
    candidates: list[WorkflowSlaCandidate] = []
    if selected in {'all', 'jawabu_pipeline'}:
        candidates.extend(jawabu_sla_candidates(now=now))
    if selected in {'all', 'tat_tracker'}:
        candidates.extend(tat_sla_candidates(now=now))
    return candidates


def record_sla_candidates(candidates: list[WorkflowSlaCandidate], *, today=None) -> tuple[list[WorkflowSlaEscalation], int]:
    """Persist one pending follow-up record per overdue case/stage/day."""
    today = today or timezone.localdate()
    records: list[WorkflowSlaEscalation] = []
    created_count = 0
    for item in candidates:
        record, created = WorkflowSlaEscalation.objects.get_or_create(
            workflow=item.workflow,
            subject_id=item.subject_id,
            stage_key=item.stage_key,
            escalation_date=today,
            defaults={
                'group_id': item.group_id,
                'target_minutes': item.target_minutes,
                'overdue_minutes': item.overdue_minutes,
            },
        )
        records.append(record)
        created_count += int(created)
    return records, created_count
