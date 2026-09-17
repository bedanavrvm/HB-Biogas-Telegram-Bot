"""Workflow-owned, read-only staff recognition projections.

Scores are deliberately derived from canonical audit events. They grant no
access, persist no ranking, and never join Portal and TAT identities.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from calendar import monthrange
from hashlib import sha256
from math import sqrt
from statistics import median

from django.db.models import OuterRef, Subquery
from django.utils import timezone


MINIMUM_RANKED_SAMPLE = 20
WILSON_Z = 1.959963984540054
ON_TIME_SLA_STATES = frozenset({'within_target', 'near_target'})


def _month_bounds(value: str = '') -> tuple[date, date, str]:
    today = timezone.localdate()
    try:
        year, month = (int(part) for part in str(value or '').split('-', 1))
        start = date(year, month, 1)
    except (TypeError, ValueError):
        start = today.replace(day=1)
    end = date(start.year, start.month, monthrange(start.year, start.month)[1])
    return start, end, start.strftime('%Y-%m')


def _wilson_lower_bound(successes: int, sample: int, *, z: float = WILSON_Z) -> float:
    """Return the conservative lower confidence bound for a binary rate."""
    if sample <= 0:
        return 0.0
    proportion = max(0.0, min(1.0, successes / sample))
    denominator = 1 + (z * z / sample)
    centre = proportion + (z * z / (2 * sample))
    margin = z * sqrt((proportion * (1 - proportion) / sample) + (z * z / (4 * sample * sample)))
    return max(0.0, (centre - margin) / denominator) * 100


def _score_rows(
    rows: list[dict], *, quality_key: str, volume_key: str, success_key: str | None = None,
    rank_group_key: str = '',
) -> list[dict]:
    """Score each row independently so access scope cannot change its score.

    Volume remains visible context, but is deliberately not scored until the
    platform has a governed opportunity denominator. Relative-to-the-largest
    visible-row scoring made results depend on the viewer and branch size.
    """
    for row in rows:
        sample = int(row.get(volume_key) or 0)
        quality = float(row.get(quality_key) or 0)
        successes = (
            int(row.get(success_key) or 0) if success_key
            else int(round(sample * quality / 100))
        )
        row['score'] = round(_wilson_lower_bound(successes, sample), 1)
        row['score_basis'] = 'wilson_quality_lower_bound'
        row['ranked'] = sample >= MINIMUM_RANKED_SAMPLE
        row['sample_status'] = 'ranked' if row['ranked'] else 'building_sample'
    rank_groups = defaultdict(list)
    for row in rows:
        rank_groups[str(row.get(rank_group_key) or '') if rank_group_key else 'all'].append(row)
    for group_rows in rank_groups.values():
        ranked = sorted(
            (row for row in group_rows if row['ranked']),
            key=lambda row: (-row['score'], -float(row.get(quality_key) or 0), -int(row.get(volume_key) or 0), row['label'].casefold()),
        )
        previous = None
        rank = 0
        for index, row in enumerate(ranked, 1):
            signature = (row['score'], row.get(quality_key), row.get(volume_key))
            if signature != previous:
                rank = index
                previous = signature
            row['rank'] = rank
    for row in rows:
        row.setdefault('rank', None)
    return sorted(rows, key=lambda row: (
        str(row.get(rank_group_key) or '').casefold() if rank_group_key else '',
        not row['ranked'], row['rank'] or 999999, row['label'].casefold(),
    ))


def _empty_tat_counts() -> dict:
    return {
        'completed': 0, 'completed_total': 0, 'on_time': 0,
        'overdue_recovered': 0, 'excluded_target_unavailable': 0,
        'corrected': 0, 'attribution_fallback': 0, '_durations': [],
    }


def _accumulate_tat_sample(target: dict, sample: dict, *, attribution_fallback: bool) -> None:
    """Add one completed stage without penalising missing target policy."""
    target['completed_total'] += 1
    target['corrected'] += int(bool(sample.get('corrected')))
    target['attribution_fallback'] += int(attribution_fallback)
    if sample.get('sla_state') == 'target_unavailable':
        target['excluded_target_unavailable'] += 1
        return
    target['completed'] += 1
    target['on_time'] += int(sample.get('sla_state') in ON_TIME_SLA_STATES)
    target['overdue_recovered'] += int(sample.get('sla_state') == 'overdue')
    if sample.get('elapsed_minutes') is not None:
        target['_durations'].append(float(sample['elapsed_minutes']))


def portal_performance_payload(user, *, access=None, period: str = '', include_people: bool = False) -> dict:
    from core.models import JawabuPipelineEvent
    from core.services.portal_permissions import scope_portal_case_queryset
    from core.services.jawabu_pipeline import all_cases, JBL_FORWARD_STATUSES

    start, end, label = _month_bounds(period)
    cases = scope_portal_case_queryset(all_cases(), user, 'portal.case.read', access=access)
    first_event = JawabuPipelineEvent.objects.filter(
        farmer_id=OuterRef('farmer_id'), action='jbl_visit_completed',
    ).order_by('occurred_at', 'created_at', 'pk').values('pk')[:1]
    visits = JawabuPipelineEvent.objects.filter(
        farmer__in=cases, action='jbl_visit_completed', pk=Subquery(first_event),
        occurred_at__date__range=(start, end),
    ).select_related('actor_user', 'farmer', 'farmer__product').order_by('occurred_at', 'created_at')
    first_by_case = {event.farmer_id: event for event in visits}
    case_ids = list(first_by_case)
    downstream = defaultdict(set)
    for event in JawabuPipelineEvent.objects.filter(
        farmer_id__in=case_ids,
        action__in=['final_decision_recorded', 'payment_finalized'],
    ).values('farmer_id', 'action', 'new_values'):
        if event['action'] == 'final_decision_recorded':
            downstream['final_decided'].add(event['farmer_id'])
            if str((event.get('new_values') or {}).get('decision') or '').casefold() == 'approved':
                downstream['final_approved'].add(event['farmer_id'])
            continue
        downstream[event['action']].add(event['farmer_id'])

    people = defaultdict(lambda: {'visits_completed': 0, 'credit_ready': 0, 'final_decided': 0, 'final_approved': 0, 'payment_finalized': 0})
    branches = defaultdict(lambda: {'visits_completed': 0, 'credit_ready': 0, 'final_decided': 0, 'final_approved': 0, 'payment_finalized': 0})
    for farmer_id, event in first_by_case.items():
        person_key = event.actor_user_id or f'label:{event.actor or "Unassigned"}'
        person_label = event.actor_user.get_full_name().strip() if event.actor_user_id else str(event.actor or 'Unassigned')
        person_label = person_label or (event.actor_user.username if event.actor_user_id else 'Unassigned')
        branch = str(event.farmer.system_branch or event.farmer.branch or 'Unassigned')
        product = str(
            (event.farmer.product.code if event.farmer.product_id else '')
            or event.farmer.payment_product or event.farmer.hbg_contract_name or 'Unassigned'
        )
        cohort = f'{branch} · {product}'
        forwarded = str(event.farmer.jbl_visit_status or '') in JBL_FORWARD_STATUSES
        for target in (people[(str(person_key), person_label, cohort)], branches[cohort]):
            target['visits_completed'] += 1
            target['credit_ready'] += int(forwarded)
            target['final_decided'] += int(farmer_id in downstream['final_decided'])
            target['final_approved'] += int(farmer_id in downstream['final_approved'])
            target['payment_finalized'] += int(farmer_id in downstream['payment_finalized'])

    def rows(source, *, names=False):
        result = []
        for key, counts in source.items():
            if names:
                identity, display, cohort = key
            else:
                identity, display, cohort = key, key, key
            total = counts['visits_completed']
            result.append({
                'key': str(identity), 'label': display, 'cohort': str(cohort), **counts,
                'credit_conversion': round(counts['credit_ready'] * 100 / total, 1) if total else 0,
                'final_conversion': round(counts['final_approved'] * 100 / total, 1) if total else 0,
                'payment_conversion': round(counts['payment_finalized'] * 100 / total, 1) if total else 0,
                'pending_outcome': max(0, total - counts['final_decided']),
            })
        return _score_rows(
            result, quality_key='credit_conversion', volume_key='visits_completed',
            success_key='credit_ready', rank_group_key='cohort' if names else '',
        )

    person_rows = rows(people, names=True)
    personal_rows = [row for row in person_rows if row['key'] == str(user.pk)]
    personal = personal_rows[0] if len(personal_rows) == 1 else None
    return {
        'period': label, 'minimum_ranked_sample': MINIMUM_RANKED_SAMPLE,
        'calculated_at': timezone.now().isoformat(),
        'result_status': 'live_provisional',
        'formula': 'Conservative visit-to-credit quality score (95% Wilson lower bound); visit volume is context only',
        'cohort_basis': 'Like-for-like branch and product cohorts; officer results use the authenticated user who recorded the first accepted visit completion',
        'revision_policy': 'Live results can change when an audited correction changes canonical workflow evidence. They are not permanent awards.',
        'team_rows': rows(branches), 'personal': personal, 'personal_rows': personal_rows,
        'people_rows': person_rows if include_people else [],
        'people_visible': bool(include_people),
    }


def tat_recognition_payload(user, *, period: str = '', include_people: bool = False) -> dict:
    from core.models import TatActionTask, TatActionTaskRecipient, TatTrackerCase
    from core.services.tat_reporting import _ReportContext, _metric_scope_q, _stage_samples

    start, end, label = _month_bounds(period)
    cases = list(TatTrackerCase.objects.filter(_metric_scope_q(user), is_deleted=False))
    filters = {'stage': '', 'role': '', 'date_from': start, 'date_to': end, 'sla_state': ''}
    samples = _stage_samples(cases, filters, include_people=True, context=_ReportContext(user, cases, include_people=True))
    responsibility = {}
    tasks = TatActionTask.objects.filter(
        case__in=cases, status=TatActionTask.STATUS_ACTED,
    ).select_related('acted_by', 'case').prefetch_related('recipients__user').order_by('created_at')
    for task in tasks:
        primary = next(
            (recipient.user for recipient in task.recipients.all()
             if recipient.kind == TatActionTaskRecipient.KIND_PRIMARY),
            None,
        )
        responsible = primary or task.acted_by
        if responsible:
            responsibility.setdefault(
                (str(task.case.group_id), str(task.case.case_id), task.stage_key),
                (str(responsible.pk), responsible.get_full_name().strip() or responsible.get_username()),
            )

    people = defaultdict(_empty_tat_counts)
    roles = defaultdict(_empty_tat_counts)
    for sample in samples:
        assigned = responsibility.get((
            str(sample.get('group_id') or ''), str(sample.get('case_id') or ''),
            str(sample.get('stage_key') or ''),
        ))
        person_key = assigned[0] if assigned else str(sample.get('person_user_id') or f'label:{sample.get("person") or "Unassigned"}')
        person_label = assigned[1] if assigned else str(sample.get('person') or 'Unassigned')
        role = str(sample.get('role') or 'Unassigned')
        branch = str(sample.get('branch') or 'Unassigned')
        product = str(sample.get('product') or sample.get('product_key') or 'Unassigned')
        cohort = ' · '.join((role, branch, product))
        cohort_key = '|'.join([
            str(sample.get('group_id') or ''), str(sample.get('branch') or ''),
            str(sample.get('product_key') or ''), role,
        ])
        for target in (
            people[(person_key, person_label, cohort, role, branch, product)],
            roles[(cohort_key, role, branch, product)],
        ):
            _accumulate_tat_sample(target, sample, attribution_fallback=not bool(assigned))

    def rows(source, *, names=False):
        result = []
        for key, counts in source.items():
            if names:
                identity, display, rank_group, role, branch, product = key
            else:
                raw_cohort_key, role, branch, product = key
                identity = f'cohort-{sha256(raw_cohort_key.encode("utf-8")).hexdigest()[:12]}'
                display = role
                rank_group = ''
            cohort = ' · '.join((role, branch, product))
            completed = counts['completed']
            durations = counts.get('_durations') or []
            public_counts = {key: value for key, value in counts.items() if not key.startswith('_')}
            result.append({
                'key': str(identity), 'label': display, 'cohort': str(cohort), **public_counts,
                'role': role, 'branch': branch, 'product': product,
                '_rank_group': rank_group,
                'on_time_rate': round(counts['on_time'] * 100 / completed, 1) if completed else 0,
                'median_minutes': round(median(durations), 1) if durations else None,
            })
        scored = _score_rows(
            result, quality_key='on_time_rate', volume_key='completed', success_key='on_time',
            rank_group_key='_rank_group' if names else '',
        )
        for row in scored:
            row.pop('_rank_group', None)
        return scored

    team_rows = rows(roles)
    person_rows = rows(people, names=True)
    personal_rows = [row for row in person_rows if row['key'] == str(user.pk)]
    personal = personal_rows[0] if len(personal_rows) == 1 else None
    methodology = None
    if include_people:
        methodology = {
            'score_method': 'The performance score is the 95% Wilson lower bound for on-time completion. It rewards consistent results without overstating small samples.',
            'cohort_basis': 'Role standings are grouped by workflow group, branch, product, and role. Individual comparisons use the same role, branch, and product.',
            'correction_policy': 'Audited timestamp corrections update live results retrospectively. These results are not permanent awards.',
            'late_work_policy': 'Recovered overdue work remains visible in data checks but does not count as on time.',
            'completed_total': sum(int(row.get('completed_total') or 0) for row in team_rows),
            'counted_total': sum(int(row.get('completed') or 0) for row in team_rows),
            'excluded_target_unavailable': sum(int(row.get('excluded_target_unavailable') or 0) for row in team_rows),
            'corrected': sum(int(row.get('corrected') or 0) for row in team_rows),
            'attribution_fallback': sum(int(row.get('attribution_fallback') or 0) for row in team_rows),
            'overdue_recovered': sum(int(row.get('overdue_recovered') or 0) for row in team_rows),
        }
    return {
        'period': label, 'minimum_ranked_sample': MINIMUM_RANKED_SAMPLE,
        'calculated_at': timezone.now().isoformat(),
        'result_status': 'live_provisional',
        'team_rows': team_rows, 'personal': personal, 'personal_rows': personal_rows,
        'people_rows': person_rows if include_people else [],
        'people_visible': bool(include_people),
        'technical_details_visible': bool(include_people),
        'methodology': methodology,
    }
