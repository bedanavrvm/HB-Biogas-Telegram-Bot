"""Workflow-owned, read-only staff recognition projections.

Scores are deliberately derived from canonical audit events. They grant no
access, persist no ranking, and never join Portal and TAT identities.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from calendar import monthrange
from statistics import median

from django.db.models import Q
from django.utils import timezone


MINIMUM_RANKED_SAMPLE = 5


def _month_bounds(value: str = '') -> tuple[date, date, str]:
    today = timezone.localdate()
    try:
        year, month = (int(part) for part in str(value or '').split('-', 1))
        start = date(year, month, 1)
    except (TypeError, ValueError):
        start = today.replace(day=1)
    end = date(start.year, start.month, monthrange(start.year, start.month)[1])
    return start, end, start.strftime('%Y-%m')


def _score_rows(rows: list[dict], *, quality_key: str, volume_key: str) -> list[dict]:
    maximum = max((int(row.get(volume_key) or 0) for row in rows), default=0)
    for row in rows:
        sample = int(row.get(volume_key) or 0)
        quality = float(row.get(quality_key) or 0)
        volume = (sample * 100 / maximum) if maximum else 0
        row['score'] = round((quality * .60) + (volume * .40), 1)
        row['ranked'] = sample >= MINIMUM_RANKED_SAMPLE
        row['sample_status'] = 'ranked' if row['ranked'] else 'building_sample'
    ranked = sorted(
        (row for row in rows if row['ranked']),
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
    return sorted(rows, key=lambda row: (not row['ranked'], row['rank'] or 999999, row['label'].casefold()))


def portal_performance_payload(user, *, access=None, period: str = '', include_people: bool = False) -> dict:
    from core.models import JawabuPipelineEvent
    from core.services.portal_permissions import scope_portal_case_queryset
    from core.services.jawabu_pipeline import all_cases, JBL_FORWARD_STATUS

    start, end, label = _month_bounds(period)
    cases = scope_portal_case_queryset(all_cases(), user, 'portal.case.read', access=access)
    visits = JawabuPipelineEvent.objects.filter(
        farmer__in=cases, action='jbl_visit_completed', occurred_at__date__range=(start, end),
    ).select_related('actor_user', 'farmer').order_by('occurred_at', 'created_at')
    latest_by_case = {}
    for event in visits:
        latest_by_case[event.farmer_id] = event
    case_ids = list(latest_by_case)
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
    for farmer_id, event in latest_by_case.items():
        person_key = event.actor_user_id or f'label:{event.actor or "Unassigned"}'
        person_label = event.actor_user.get_full_name().strip() if event.actor_user_id else str(event.actor or 'Unassigned')
        person_label = person_label or (event.actor_user.username if event.actor_user_id else 'Unassigned')
        branch = str(event.farmer.system_branch or event.farmer.branch or 'Unassigned')
        forwarded = str((event.new_values or {}).get('status') or '') == JBL_FORWARD_STATUS
        for target in (people[(str(person_key), person_label)], branches[branch]):
            target['visits_completed'] += 1
            target['credit_ready'] += int(forwarded)
            target['final_decided'] += int(farmer_id in downstream['final_decided'])
            target['final_approved'] += int(farmer_id in downstream['final_approved'])
            target['payment_finalized'] += int(farmer_id in downstream['payment_finalized'])

    def rows(source, *, names=False):
        result = []
        for key, counts in source.items():
            identity, display = key if names else (key, key)
            total = counts['visits_completed']
            result.append({
                'key': str(identity), 'label': display, **counts,
                'credit_conversion': round(counts['credit_ready'] * 100 / total, 1) if total else 0,
                'final_conversion': round(counts['final_approved'] * 100 / total, 1) if total else 0,
                'payment_conversion': round(counts['payment_finalized'] * 100 / total, 1) if total else 0,
                'pending_outcome': max(0, total - counts['final_decided']),
            })
        return _score_rows(result, quality_key='credit_conversion', volume_key='visits_completed')

    person_rows = rows(people, names=True)
    personal = next((row for row in person_rows if row['key'] == str(user.pk)), None)
    return {
        'period': label, 'minimum_ranked_sample': MINIMUM_RANKED_SAMPLE,
        'formula': '60% visit-to-credit conversion + 40% completed-visit contribution',
        'team_rows': rows(branches), 'personal': personal,
        'people_rows': person_rows if include_people else [],
        'people_visible': bool(include_people),
    }


def tat_recognition_payload(user, *, period: str = '', include_people: bool = False) -> dict:
    from core.models import TatTrackerCase
    from core.services.tat_reporting import _ReportContext, _metric_scope_q, _stage_samples

    start, end, label = _month_bounds(period)
    cases = list(TatTrackerCase.objects.filter(_metric_scope_q(user), is_deleted=False))
    filters = {'stage': '', 'role': '', 'date_from': start, 'date_to': end, 'sla_state': ''}
    samples = _stage_samples(cases, filters, include_people=True, context=_ReportContext(user, cases, include_people=True))
    people = defaultdict(lambda: {'completed': 0, 'on_time': 0, 'overdue_recovered': 0, '_durations': []})
    roles = defaultdict(lambda: {'completed': 0, 'on_time': 0, 'overdue_recovered': 0, '_durations': []})
    for sample in samples:
        person_key = str(sample.get('person_user_id') or f'label:{sample.get("person") or "Unassigned"}')
        person_label = str(sample.get('person') or 'Unassigned')
        role = str(sample.get('role') or 'Unassigned')
        on_time = sample.get('sla_state') == 'within_target'
        for target in (people[(person_key, person_label)], roles[role]):
            target['completed'] += 1
            target['on_time'] += int(on_time)
            target['overdue_recovered'] += int(sample.get('sla_state') == 'overdue')
            if sample.get('elapsed_minutes') is not None:
                target['_durations'].append(float(sample['elapsed_minutes']))

    def rows(source, *, names=False):
        result = []
        for key, counts in source.items():
            identity, display = key if names else (key, key)
            completed = counts['completed']
            durations = counts.get('_durations') or []
            public_counts = {key: value for key, value in counts.items() if not key.startswith('_')}
            result.append({
                'key': str(identity), 'label': display, **public_counts,
                'on_time_rate': round(counts['on_time'] * 100 / completed, 1) if completed else 0,
                'median_minutes': round(median(durations), 1) if durations else None,
            })
        return _score_rows(result, quality_key='on_time_rate', volume_key='completed')

    person_rows = rows(people, names=True)
    personal = next((row for row in person_rows if row['key'] == str(user.pk)), None)
    return {
        'period': label, 'minimum_ranked_sample': MINIMUM_RANKED_SAMPLE,
        'formula': '60% on-time completion + 40% completed-stage contribution',
        'team_rows': rows(roles), 'personal': personal,
        'people_rows': person_rows if include_people else [],
        'people_visible': bool(include_people),
    }
