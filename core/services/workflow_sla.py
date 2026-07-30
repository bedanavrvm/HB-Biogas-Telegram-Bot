"""Read-only SLA evaluation and idempotent escalation persistence.

Delivery is deliberately outside this module. A scheduled operator can first
review dry-run output, then persist pending follow-up records without causing
Telegram, Sheets, Drive, or workflow-state side effects.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import ROUND_CEILING, Decimal, InvalidOperation

from django.utils import timezone

from core.models import (
    GroupSheetConfiguration,
    JawabuFarmerMaster,
    TatEscalationRule,
    TatTrackerCase,
    WorkflowSlaEscalation,
    WorkflowTatDailyMetric,
)
from core.services.jawabu_case360 import calculate_case_tat
from core.services.jawabu_pipeline import JAWABU_TERMINAL_STATES, current_workflow_state
from core.services.tat_tracker import (
    is_tat_tracker_workflow,
    next_action,
    product_by_key,
    stage_target_minutes,
    stage_target_minutes_for_case,
    stage_business_tat_minutes,
    stage_tat_minutes,
    stage_completed_at,
)


@dataclass(frozen=True)
class WorkflowSlaCandidate:
    workflow: str
    subject_id: str
    group_id: str
    stage_key: str
    target_minutes: int
    overdue_minutes: int
    branch: str = ''
    responsible_role: str = ''
    responsible_actor: str = ''

    def payload(self) -> dict:
        payload = asdict(self)
        payload.update(escalation_tier(
            self.target_minutes, self.overdue_minutes,
            workflow=self.workflow, group_id=self.group_id, branch=self.branch,
        ))
        return payload


def escalation_tier(target_minutes: int, overdue_minutes: int, *, workflow: str = '', group_id: str = '', branch: str = '') -> dict[str, int | str]:
    """Return the current in-app owner; notification delivery remains separate."""
    target = Decimal(str(target_minutes or 0))
    elapsed = target + max(Decimal('0'), Decimal(str(overdue_minutes or 0)))
    percent = int((elapsed * Decimal('100') / target)) if target > 0 else 0
    if workflow == 'tat_tracker' and group_id:
        config = GroupSheetConfiguration.objects.filter(group_id=str(group_id)).first()
        if config:
            rules = list(TatEscalationRule.objects.filter(
                group_configuration=config, active=True, branch__in=['', str(branch or '')],
                threshold_percent__lte=percent,
            ).order_by('threshold_percent'))
            if rules:
                rule = rules[-1]
                return {
                    'escalation_level': len(rules),
                    'threshold_percent': rule.threshold_percent,
                    'routing_role': rule.routing_role,
                }
    if target > 0 and elapsed * Decimal('100') >= target * Decimal('200'):
        return {'escalation_level': 3, 'threshold_percent': 200, 'routing_role': 'MANAGEMENT'}
    if target > 0 and elapsed * Decimal('100') >= target * Decimal('150'):
        return {'escalation_level': 2, 'threshold_percent': 150, 'routing_role': 'BRANCH_MANAGER'}
    return {'escalation_level': 1, 'threshold_percent': 100, 'routing_role': 'RESPONSIBLE_ROLE'}


def _jawabu_responsible_role(stage_key: str) -> str:
    stage_key = str(stage_key or '')
    if 'jbl_visit' in stage_key:
        return 'JBL_OFFICER'
    if 'credit' in stage_key:
        return 'CREDIT_ANALYST'
    if 'final_decision' in stage_key:
        return 'HEAD_OF_RURAL'
    if 'order' in stage_key:
        return 'OPERATIONS'
    if 'invoice' in stage_key or 'payment' in stage_key:
        return 'FINANCE'
    return 'OPERATIONS'


def _jawabu_responsible_actor(farmer: JawabuFarmerMaster, stage_key: str) -> str:
    """Attribute an individual only where the workflow records one explicitly."""
    if 'jbl_visit' in str(stage_key or ''):
        return str(farmer.jbl_officer or farmer.system_loan_officer or '')
    return ''


def _positive_minutes(value) -> int | None:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return int(number)


def _decimal_minutes(value) -> Decimal | None:
    """Preserve timing precision for trend reporting; zero is meaningful."""
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number >= 0 else None


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
            elapsed = _positive_minutes(stage.get('sla_minutes', stage.get('minutes')))
            if not target or elapsed is None:
                continue
            candidates.append(WorkflowSlaCandidate(
                workflow='jawabu_pipeline',
                subject_id=str(farmer.pk),
                group_id='',
                stage_key=str(stage.get('key') or ''),
                target_minutes=target,
                overdue_minutes=max(0, elapsed - target),
                branch=str(farmer.branch or ''),
                responsible_role=_jawabu_responsible_role(stage.get('key')),
                responsible_actor=_jawabu_responsible_actor(farmer, stage.get('key')),
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
            target = stage_target_minutes_for_case(case, workflow, product, stage)
            elapsed = stage_business_tat_minutes(case, stage, now=now)
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
                branch=str(case.branch or ''),
                responsible_role=str(stage.role or ''),
                responsible_actor=str(case.bro_name or '') if str(stage.role or '').upper() == 'BRO' else '',
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
        tier = escalation_tier(
            item.target_minutes, item.overdue_minutes,
            workflow=item.workflow, group_id=item.group_id, branch=item.branch,
        )
        record, created = WorkflowSlaEscalation.objects.get_or_create(
            workflow=item.workflow,
            subject_id=item.subject_id,
            stage_key=item.stage_key,
            escalation_date=today,
            defaults={
                'group_id': item.group_id,
                'branch': item.branch,
                'responsible_role': item.responsible_role,
                'responsible_actor': item.responsible_actor,
                'target_minutes': item.target_minutes,
                'overdue_minutes': item.overdue_minutes,
                'escalation_level': tier['escalation_level'],
                'threshold_percent': tier['threshold_percent'],
            },
        )
        if not created and record.status != 'resolved':
            update_fields = []
            for field, value in {
                'group_id': item.group_id,
                'branch': item.branch,
                'responsible_role': item.responsible_role,
                'responsible_actor': item.responsible_actor,
                'target_minutes': item.target_minutes,
                'overdue_minutes': item.overdue_minutes,
                'escalation_level': tier['escalation_level'],
                'threshold_percent': tier['threshold_percent'],
            }.items():
                if getattr(record, field) != value:
                    setattr(record, field, value)
                    update_fields.append(field)
            if update_fields:
                record.save(update_fields=update_fields)
        records.append(record)
        created_count += int(created)
    return records, created_count


def _metric_percentile(values: list[Decimal], percentile: Decimal) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    # Nearest-rank percentile without coercing timing data through float.
    index = max(0, int((Decimal(len(ordered)) * percentile).to_integral_value(rounding=ROUND_CEILING)) - 1)
    return ordered[index].quantize(Decimal('0.01'))


def _metric_bucket(
    buckets: dict,
    *,
    workflow: str,
    group_id: str,
    branch: str,
    product_key: str,
    stage_key: str,
    responsible_role: str,
    responsible_actor: str,
) -> dict:
    key = (workflow, group_id, branch, product_key, stage_key, responsible_role, responsible_actor)
    return buckets.setdefault(key, {
        'workflow': workflow,
        'group_id': group_id,
        'branch': branch,
        'product_key': product_key,
        'stage_key': stage_key,
        'responsible_role': responsible_role,
        'responsible_actor': responsible_actor,
        'active_count': 0,
        'completed_count': 0,
        'overdue_count': 0,
        'sla_values': [],
        'wall_clock_values': [],
    })


def collect_tat_daily_metrics(*, metric_date=None, now=None) -> list[dict]:
    """Build a current-day, query-time operational trend snapshot.

    Completed counts are based on exact stage timestamps that fall on
    ``metric_date``.  Active and overdue counts describe the queue at scan
    time, making the snapshot useful without mutating a case or Sheet.
    """
    now = now or timezone.now()
    metric_date = metric_date or timezone.localdate(now)
    buckets: dict = {}

    for farmer in JawabuFarmerMaster.objects.filter(status='active').prefetch_related('pipeline_events'):
        if current_workflow_state(farmer) in JAWABU_TERMINAL_STATES | {'deferred'}:
            continue
        tat = calculate_case_tat(farmer, now=now)
        for stage in tat.get('stages') or []:
            if not stage.get('started_at'):
                continue
            bucket = _metric_bucket(
                buckets,
                workflow='jawabu_pipeline',
                group_id='',
                branch=str(farmer.branch or ''),
                product_key=str(farmer.payment_product or ''),
                stage_key=str(stage.get('key') or ''),
                responsible_role=_jawabu_responsible_role(stage.get('key')),
                responsible_actor=_jawabu_responsible_actor(farmer, stage.get('key')),
            )
            sla_minutes = _decimal_minutes(stage.get('sla_minutes'))
            wall_clock_minutes = _decimal_minutes(stage.get('wall_clock_minutes'))
            if sla_minutes is not None:
                bucket['sla_values'].append(sla_minutes)
            if wall_clock_minutes is not None:
                bucket['wall_clock_values'].append(wall_clock_minutes)
            if stage.get('completed_at'):
                completed_at = timezone.datetime.fromisoformat(stage['completed_at'])
                if timezone.localdate(completed_at) == metric_date:
                    bucket['completed_count'] += 1
            else:
                bucket['active_count'] += 1
                if stage.get('status') == 'over':
                    bucket['overdue_count'] += 1

    configs = [config for config in GroupSheetConfiguration.objects.filter(enabled=True) if is_tat_tracker_workflow(config)]
    for config in configs:
        workflow = config.workflow or {}
        for case in TatTrackerCase.objects.filter(
            group_id=str(config.group_id),
            is_deleted=False,
            status='Active',
        ):
            product = product_by_key(case.product_key)
            for stage in product.stages:
                sla_minutes = stage_business_tat_minutes(case, stage, now=now)
                wall_clock_minutes = stage_tat_minutes(case, stage, now=now)
                if sla_minutes is None:
                    continue
                bucket = _metric_bucket(
                    buckets,
                    workflow='tat_tracker',
                    group_id=str(case.group_id),
                    branch=str(case.branch or ''),
                    product_key=case.product_key,
                    stage_key=stage.key,
                    responsible_role=stage.role,
                    responsible_actor=str(case.bro_name or '') if str(stage.role or '').upper() == 'BRO' else '',
                )
                bucket['sla_values'].append(sla_minutes)
                if wall_clock_minutes is not None:
                    bucket['wall_clock_values'].append(wall_clock_minutes)
                completed_at = stage_completed_at(case, stage)
                if completed_at:
                    if timezone.localdate(completed_at) == metric_date:
                        bucket['completed_count'] += 1
                elif next_action(case) and next_action(case).key == stage.key:
                    bucket['active_count'] += 1
                    target = stage_target_minutes_for_case(case, workflow, product, stage)
                    if target and sla_minutes > target:
                        bucket['overdue_count'] += 1

    metrics = []
    for bucket in buckets.values():
        sla_values = bucket.pop('sla_values')
        wall_clock_values = bucket.pop('wall_clock_values')
        bucket['sample_count'] = len(sla_values)
        bucket['median_sla_minutes'] = _metric_percentile(sla_values, Decimal('0.5'))
        bucket['p90_sla_minutes'] = _metric_percentile(sla_values, Decimal('0.9'))
        bucket['median_wall_clock_minutes'] = _metric_percentile(wall_clock_values, Decimal('0.5'))
        metrics.append(bucket)
    return sorted(metrics, key=lambda item: (
        item['workflow'], item['group_id'], item['branch'], item['product_key'], item['stage_key'], item['responsible_role'], item['responsible_actor'],
    ))


def record_tat_daily_metrics(metrics: list[dict], *, metric_date=None) -> tuple[list[WorkflowTatDailyMetric], int]:
    """Upsert one date-stable reporting projection per metric dimension."""
    metric_date = metric_date or timezone.localdate()
    records: list[WorkflowTatDailyMetric] = []
    created_count = 0
    dimensions = ('workflow', 'group_id', 'branch', 'product_key', 'stage_key', 'responsible_role', 'responsible_actor')
    values = (
        'active_count', 'completed_count', 'overdue_count', 'sample_count',
        'median_sla_minutes', 'p90_sla_minutes', 'median_wall_clock_minutes',
    )
    for item in metrics:
        lookup = {field: item.get(field, '') for field in dimensions}
        record, created = WorkflowTatDailyMetric.objects.update_or_create(
            metric_date=metric_date,
            **lookup,
            defaults={field: item.get(field) for field in values},
        )
        records.append(record)
        created_count += int(created)
    return records, created_count
