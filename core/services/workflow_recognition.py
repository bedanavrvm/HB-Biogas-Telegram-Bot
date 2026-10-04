"""Workflow-owned, read-only staff recognition projections.

Scores are deliberately derived from canonical audit events. They grant no
access, persist no ranking, and never join Portal and TAT identities.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from calendar import monthrange
from hashlib import sha256
from math import sqrt
import json

from django.db import transaction
from django.db.models import Count, Max, OuterRef, Subquery
from django.utils import timezone


MINIMUM_RANKED_SAMPLE = 20
RECOGNITION_STANDINGS_MINIMUM_SAMPLE = 1
TAT_RECOGNITION_SCORE_POLICY_VERSION = 1
WILSON_Z = 1.959963984540054
ON_TIME_SLA_STATES = frozenset({'within_target', 'near_target'})


def _recognition_access_signature(user) -> str:
    from core.models import AccessGrant
    from core.services.access_control import policy_version

    grants = list(AccessGrant.objects.filter(
        user=user, workflow='tat_tracker', active=True,
    ).order_by('pk').values_list(
        'pk', 'role', 'group_configuration_id', 'branch', 'product',
    ))
    value = [bool(user.is_active and user.is_superuser), policy_version(),
             [[str(part) for part in grant] for grant in grants]]
    return sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def tat_recognition_revision(user, *, group_id: str) -> str:
    """Cheap, opaque scoped change token; never exposes case or staff identifiers."""
    from core.models import TatTrackerCase, TatTrackerEvent
    from core.services.tat_reporting import _metric_scope_q
    from core.services.workflow_data_mode import WORKFLOW_TAT, mode_snapshot

    cases = TatTrackerCase.objects.filter(_metric_scope_q(user), is_deleted=False)
    if group_id:
        cases = cases.filter(group_id=group_id)
    case_state = cases.aggregate(count=Count('pk'), latest=Max('updated_at'))
    event_state = TatTrackerEvent.objects.filter(case__in=cases).aggregate(
        count=Count('pk'), latest=Max('created_at'),
    )
    parts = [group_id, mode_snapshot(WORKFLOW_TAT).data_scope_key, _recognition_access_signature(user),
             case_state['count'], str(case_state['latest']),
             event_state['count'], str(event_state['latest'])]
    return sha256(json.dumps(parts).encode()).hexdigest()


def _apply_live_rank_movement(user, *, group_id, scope_key, period_kind, period_key,
                              view, role, product, branch, include_people=False, rows, observed_at):
    """Persist net movement only when a standing actually changes."""
    from tat_recognition.models import TatRecognitionLiveStanding

    scope = _recognition_access_signature(user)
    identity = [str(user.pk), group_id, scope_key, period_kind, period_key,
                view, role, product, branch, bool(include_people), scope]
    context_key = sha256(json.dumps(identity).encode()).hexdigest()
    current_ranks = {str(row['key']): int(row['rank']) for row in rows if row.get('rank') is not None}
    fingerprint = sorted((str(row['key']), row.get('rank'), row.get('score'),
                          row.get('completed'), row.get('completed_total'),
                          row.get('on_time_rate'), row.get('within_target'),
                          row.get('near_target'), row.get('overdue_recovered')) for row in rows)
    signature = sha256(json.dumps(fingerprint, sort_keys=True).encode()).hexdigest()
    expires_at = observed_at + timedelta(days=45)
    with transaction.atomic():
        expired_ids = list(TatRecognitionLiveStanding.objects.filter(
            expires_at__lt=observed_at,
        ).order_by('expires_at').values_list('pk', flat=True)[:100])
        if expired_ids:
            TatRecognitionLiveStanding.objects.filter(
                pk__in=expired_ids, expires_at__lt=observed_at,
            ).delete()
        checkpoint, created = TatRecognitionLiveStanding.objects.get_or_create(
            context_key=context_key,
            defaults={'viewer': user, 'group_id': group_id, 'scope_key': scope_key,
                      'ranks': current_ranks, 'signature': signature, 'movement': {},
                      'observed_at': observed_at, 'expires_at': expires_at},
        )
        if not created:
            checkpoint = TatRecognitionLiveStanding.objects.select_for_update().get(pk=checkpoint.pk)
            if checkpoint.signature != signature and checkpoint.observed_at <= observed_at:
                previous = checkpoint.ranks or {}
                movement = {}
                for key, rank in current_ranks.items():
                    if key not in previous:
                        movement[key] = {'direction': 'new', 'places': 0}
                    else:
                        delta = int(previous[key]) - rank
                        movement[key] = {
                            'direction': 'up' if delta > 0 else 'down' if delta < 0 else 'same',
                            'places': abs(delta),
                        }
                checkpoint.ranks = current_ranks
                checkpoint.signature = signature
                checkpoint.movement = movement
                checkpoint.observed_at = observed_at
                checkpoint.expires_at = expires_at
                checkpoint.save(update_fields=['ranks', 'signature', 'movement', 'observed_at', 'expires_at'])
            elif checkpoint.expires_at < observed_at + timedelta(days=44):
                checkpoint.expires_at = expires_at
                checkpoint.save(update_fields=['expires_at'])
        movement = checkpoint.movement or {}
    for row in rows:
        row['movement'] = movement.get(str(row['key']), {'direction': 'none', 'places': 0})


def _month_bounds(value: str = '') -> tuple[date, date, str]:
    today = timezone.localdate()
    try:
        year, month = (int(part) for part in str(value or '').split('-', 1))
        if not 1900 <= year <= 9998:
            raise ValueError
        start = date(year, month, 1)
    except (TypeError, ValueError):
        start = today.replace(day=1)
    end = date(start.year, start.month, monthrange(start.year, start.month)[1])
    return start, end, start.strftime('%Y-%m')


def _recognition_period(kind: str, value: str) -> tuple[date, date, str, str]:
    """Resolve a calendar period using Django's Nairobi local date."""
    today = timezone.localdate()
    kind = str(kind or 'month').lower()
    if kind not in {'month', 'quarter', 'year'}:
        raise ValueError('Choose Month, Quarter, or Year.')
    if kind == 'month':
        start, end, key = _month_bounds(value)
    else:
        try:
            year_text, marker = (str(value or '').split('-', 1) + [''])[:2]
            year = int(year_text)
            if not 1900 <= year <= 9998:
                raise ValueError
            if kind == 'quarter':
                quarter = int(marker.removeprefix('Q'))
                if marker != f'Q{quarter}' or quarter not in {1, 2, 3, 4}:
                    raise ValueError
                start = date(year, (quarter - 1) * 3 + 1, 1)
                end_month = quarter * 3
                end = date(year, end_month, monthrange(year, end_month)[1])
                key = f'{year}-Q{quarter}'
            else:
                if marker:
                    raise ValueError
                start, end, key = date(year, 1, 1), date(year, 12, 31), str(year)
        except (TypeError, ValueError):
            if kind == 'quarter':
                quarter = (today.month - 1) // 3 + 1
                return _recognition_period('quarter', f'{today.year}-Q{quarter}')
            return _recognition_period('year', str(today.year))
    return start, end, key, kind


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
    rank_group_key: str = '', minimum_sample: int = MINIMUM_RANKED_SAMPLE,
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
        row['ranked'] = sample >= minimum_sample
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
        'within_target': 0, 'near_target': 0,
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
    target['within_target'] += int(sample.get('sla_state') == 'within_target')
    target['near_target'] += int(sample.get('sla_state') == 'near_target')
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


def _recognition_facts(user, *, group_id, start, end, period_kind, period_key):
    """Freeze group facts once; apply the viewer's *current* scope on every read."""
    from core.models import (
        AccessGrant,
        TatActionTask,
        TatActionTaskRecipient,
        TatTrackerCase,
        WORKFLOW_DATA_MODE_PILOT,
        WORKFLOW_DATA_MODE_PRODUCTION,
    )
    from core.services.tat_reporting import _ReportContext, _metric_scope_q, _stage_samples, TERMINAL
    from core.services.tat_tracker import overall_tat_end
    from core.services.workflow_data_mode import WORKFLOW_TAT, mode_snapshot
    from tat_recognition.models import TatRecognitionPeriodSnapshot
    from django.db.models import Q

    def build(cases):
        context = _ReportContext(user, cases, include_people=True)
        period_filters = {'stage': '', 'role': '', 'date_from': start, 'date_to': end, 'sla_state': ''}
        action_samples = _stage_samples(cases, period_filters, include_people=True, context=context)
        qualifying = []
        for case in cases:
            if case.status not in TERMINAL or not start <= timezone.localdate(case.created_at) <= end:
                continue
            finished = overall_tat_end(case, now=case.updated_at)
            if finished and start <= timezone.localdate(finished) <= end:
                qualifying.append(case)
        branch_samples = _stage_samples(
            qualifying,
            {**period_filters, 'date_from': date(1900, 1, 1), 'date_to': date(9998, 12, 31)},
            include_people=True, context=context,
        )
        assignments = {}
        for task in TatActionTask.objects.filter(
            case__in=cases, status=TatActionTask.STATUS_ACTED,
        ).select_related('acted_by', 'case').prefetch_related('recipients__user').order_by('created_at'):
            primary = next((item.user for item in task.recipients.all() if item.kind == TatActionTaskRecipient.KIND_PRIMARY), None)
            responsible = primary or task.acted_by
            if responsible:
                assignments.setdefault(
                    (str(task.case.group_id), str(task.case.case_id), task.stage_key),
                    (str(responsible.pk), responsible.get_full_name().strip() or responsible.get_username()),
                )
        for sample in action_samples + branch_samples:
            assigned = assignments.get((str(sample.get('group_id') or ''), str(sample.get('case_id') or ''), str(sample.get('stage_key') or '')))
            sample['recognition_assignment'] = list(assigned) if assigned else []
            sample['recognition_assignment_frozen'] = True
        return {
            'score_policy_version': TAT_RECOGNITION_SCORE_POLICY_VERSION,
            'minimum_ranked_sample': MINIMUM_RANKED_SAMPLE,
            'actions': action_samples, 'branches': branch_samples,
        }

    group_id = str(group_id or '').strip()
    is_settled = bool(group_id and end <= date.max - timedelta(days=30) and timezone.localdate() > end + timedelta(days=30))
    if not is_settled:
        cases = TatTrackerCase.objects.filter(_metric_scope_q(user), is_deleted=False)
        if group_id:
            cases = cases.filter(group_id=group_id)
        return build(list(cases)), None

    mode = mode_snapshot(WORKFLOW_TAT)
    scope_key = mode.data_scope_key
    identity = dict(group_id=group_id, scope_key=scope_key, period_kind=period_kind, period_key=period_key)
    snapshot = TatRecognitionPeriodSnapshot.objects.filter(**identity).first()
    if snapshot is None:
        operational = Q(data_mode=WORKFLOW_DATA_MODE_PRODUCTION)
        if mode.mode == WORKFLOW_DATA_MODE_PILOT:
            operational |= Q(data_mode=WORKFLOW_DATA_MODE_PILOT, pilot_cycle_id=mode.pilot_cycle_id)
        cases = list(TatTrackerCase.objects.filter(operational, group_id=group_id, is_deleted=False))
        snapshot, _ = TatRecognitionPeriodSnapshot.objects.get_or_create(
            **identity, defaults={'facts': build(cases)},
        )

    if user.is_active and user.is_superuser:
        return snapshot.facts, snapshot.captured_at
    grants = list(AccessGrant.objects.filter(user=user, workflow='tat_tracker', active=True).select_related('group_configuration'))

    def permitted(sample):
        for grant in grants:
            if grant.group_configuration_id and str(grant.group_configuration.group_id) != group_id:
                continue
            if grant.branch and str(grant.branch).casefold() != str(sample.get('branch') or '').casefold():
                continue
            if grant.product and str(grant.product).casefold() != str(sample.get('product_key') or '').casefold():
                continue
            return True
        return False

    return {
        'score_policy_version': snapshot.facts.get('score_policy_version'),
        'minimum_ranked_sample': snapshot.facts.get('minimum_ranked_sample'),
        **{
            key: [sample for sample in snapshot.facts.get(key, []) if permitted(sample)]
            for key in ('actions', 'branches')
        },
    }, snapshot.captured_at


def tat_recognition_payload(
    user, *, period: str = '', period_kind: str = 'month', include_people: bool = False,
    group_id: str = '', role: str = '', product: str = '', branch: str = '',
    view: str = 'personal', page: int = 1,
) -> dict:
    """Return group-scoped overall, filtered and like-for-like standings."""
    from core.models import TatActionTask, TatActionTaskRecipient, TatTrackerCase
    from core.services.tat_reporting import _metric_scope_q
    from core.services.tat_tracker import role_display_name
    from core.services.workflow_data_mode import WORKFLOW_TAT, mode_snapshot

    observed_at = timezone.now()
    data_revision = tat_recognition_revision(user, group_id=str(group_id or '').strip())
    start, end, label, period_kind = _recognition_period(period_kind, period)
    cases_qs = TatTrackerCase.objects.filter(_metric_scope_q(user), is_deleted=False)
    if str(group_id or '').strip():
        cases_qs = cases_qs.filter(group_id=str(group_id).strip())
    cases = list(cases_qs)
    facts, captured_at = _recognition_facts(
        user, group_id=group_id, start=start, end=end,
        period_kind=period_kind, period_key=label,
    )
    samples = facts['actions']
    branch_samples = facts['branches']
    minimum_sample = int(facts.get('minimum_ranked_sample') or MINIMUM_RANKED_SAMPLE)
    if int(facts.get('score_policy_version') or 0) != TAT_RECOGNITION_SCORE_POLICY_VERSION:
        raise ValueError('This final recognition score uses an unsupported policy version.')

    responsibility = {}
    tasks = TatActionTask.objects.filter(
        case__in=cases,
        status=TatActionTask.STATUS_ACTED,
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
    person_branches = defaultdict(set)
    branches = defaultdict(_empty_tat_counts)
    contexts = defaultdict(_empty_tat_counts)
    personal_total = _empty_tat_counts()
    overall_stages = defaultdict(_empty_tat_counts)
    overall_roles = set()
    personal_months = defaultdict(_empty_tat_counts)
    personal_slice = _empty_tat_counts()

    def attribution(sample):
        assigned = sample.get('recognition_assignment') if sample.get('recognition_assignment_frozen') else responsibility.get((
            str(sample.get('group_id') or ''), str(sample.get('case_id') or ''),
            str(sample.get('stage_key') or ''),
        ))
        actor_roles = {
            value.strip().upper()
            for value in str(sample.get('person_roles') or '').split(',') if value.strip()
        }
        sample_role = str(sample.get('role') or 'Unassigned').strip().upper()
        technical_override = not assigned and 'IT' in actor_roles and sample_role not in actor_roles
        identity = assigned[0] if assigned else str(sample.get('person_user_id') or '').strip()
        display = assigned[1] if assigned else str(sample.get('person') or '').strip()
        return assigned, ('' if technical_override else identity), ('' if technical_override else display)

    for sample in branch_samples:
        sample_role = str(sample.get('role') or 'Unassigned').strip().upper()
        sample_branch = str(sample.get('branch') or 'Unassigned')
        product_label = str(sample.get('product') or sample.get('product_key') or 'Unassigned').strip()
        product_key = str(sample.get('product_key') or product_label).strip().lower()
        assigned, _, _ = attribution(sample)
        _accumulate_tat_sample(
            branches[(sample_role, product_key, product_label, sample_branch)],
            sample, attribution_fallback=not bool(assigned),
        )
    for sample in samples:
        assigned, person_identity, person_label = attribution(sample)
        sample_role = str(sample.get('role') or 'Unassigned').strip().upper()
        sample_branch = str(sample.get('branch') or 'Unassigned')
        product_label = str(sample.get('product') or sample.get('product_key') or 'Unassigned').strip()
        product_key = str(sample.get('product_key') or product_label).strip().lower()
        context_key = (sample_role, product_key, product_label)
        _accumulate_tat_sample(contexts[context_key], sample, attribution_fallback=not bool(assigned))
        if not (person_identity or person_label):
            continue
        person_key = person_identity or f'label:{person_label}'
        person_key_tuple = (person_key, person_label or 'Unassigned', *context_key)
        person_branches[person_key_tuple].add(sample_branch)
        _accumulate_tat_sample(
            people[person_key_tuple], sample, attribution_fallback=not bool(assigned),
        )
        if person_identity == str(user.pk):
            _accumulate_tat_sample(personal_total, sample, attribution_fallback=not bool(assigned))
            overall_roles.add(sample_role)
            stage_key = (sample_role, str(sample.get('stage_key') or ''), str(sample.get('stage') or 'Stage'))
            _accumulate_tat_sample(overall_stages[stage_key], sample, attribution_fallback=not bool(assigned))

    def merge_counts(target, source):
        for name, value in source.items():
            if name == '_durations':
                target[name].extend(value)
            else:
                target[name] += value

    def scored_people_rows(role_filter='', product_filter='', branch_filter='', allowed_contexts=None):
        totals = defaultdict(_empty_tat_counts)
        details = defaultdict(lambda: {'roles': set(), 'products': set(), 'branches': set()})
        labels = {}
        for key, counts in people.items():
            identity, display, item_role, product_key, product_label = key
            if ((role_filter and item_role != role_filter)
                    or (product_filter and product_key != product_filter)
                    or (allowed_contexts is not None and (item_role, product_key) not in allowed_contexts)):
                continue
            item_branches = person_branches[key]
            if branch_filter:
                # A person's counts must be split by branch before aggregation.
                # The unfiltered tuple contains actions across all their branches.
                continue
            merge_counts(totals[identity], counts)
            labels.setdefault(identity, display)
            details[identity]['roles'].add(item_role)
            details[identity]['products'].add((product_key, product_label))
            details[identity]['branches'].update(item_branches)
        if branch_filter:
            for sample in samples:
                assigned, identity, display = attribution(sample)
                item_role = str(sample.get('role') or 'Unassigned').strip().upper()
                product_label = str(sample.get('product') or sample.get('product_key') or 'Unassigned').strip()
                product_key = str(sample.get('product_key') or product_label).strip().lower()
                sample_branch = str(sample.get('branch') or 'Unassigned')
                if (not identity or sample_branch.casefold() != branch_filter.casefold()
                        or (role_filter and item_role != role_filter)
                        or (product_filter and product_key != product_filter)
                        or (allowed_contexts is not None and (item_role, product_key) not in allowed_contexts)):
                    continue
                _accumulate_tat_sample(totals[identity], sample, attribution_fallback=not bool(assigned))
                labels.setdefault(identity, display or 'Unassigned')
                details[identity]['roles'].add(item_role)
                details[identity]['products'].add((product_key, product_label))
                details[identity]['branches'].add(sample_branch)
        result = []
        for identity, counts in totals.items():
            if not counts['completed']:
                continue
            meta = details[identity]
            roles = sorted(meta['roles'])
            products = sorted(meta['products'])
            item_branches = sorted(meta['branches'], key=str.casefold)
            completed = counts['completed']
            result.append({
                'key': str(identity), 'label': labels[identity],
                **{name: value for name, value in counts.items() if not name.startswith('_')},
                'role': roles[0] if len(roles) == 1 else '', 'role_count': len(roles),
                'product_key': products[0][0] if len(products) == 1 else '',
                'product': products[0][1] if len(products) == 1 else '', 'product_count': len(products),
                'branch': item_branches[0] if len(item_branches) == 1 else '',
                'branch_count': len(item_branches),
                'on_time_rate': round(counts['on_time'] * 100 / completed, 1) if completed else 0,
            })
        return _score_rows(result, quality_key='on_time_rate', volume_key='completed',
                           success_key='on_time', minimum_sample=RECOGNITION_STANDINGS_MINIMUM_SAMPLE)

    def scored_branch_rows(role_filter='', product_filter='', branch_filter='', allowed_contexts=None):
        totals = defaultdict(_empty_tat_counts)
        details = defaultdict(lambda: {'roles': set(), 'products': set()})
        labels = {}
        for (item_role, product_key, product_label, item_branch), counts in branches.items():
            if ((role_filter and item_role != role_filter)
                    or (product_filter and product_key != product_filter)
                    or (branch_filter and item_branch.casefold() != branch_filter.casefold())
                    or (allowed_contexts is not None and (item_role, product_key) not in allowed_contexts)):
                continue
            identity = item_branch.casefold()
            merge_counts(totals[identity], counts)
            labels.setdefault(identity, item_branch)
            details[identity]['roles'].add(item_role)
            details[identity]['products'].add((product_key, product_label))
        result = []
        for identity, counts in totals.items():
            if not counts['completed']:
                continue
            roles = sorted(details[identity]['roles'])
            products = sorted(details[identity]['products'])
            completed = counts['completed']
            result.append({
                'key': f'branch-{sha256(identity.encode("utf-8")).hexdigest()[:12]}',
                'label': labels[identity], 'branch': labels[identity],
                'role': roles[0] if len(roles) == 1 else '', 'role_count': len(roles),
                'product_key': products[0][0] if len(products) == 1 else '',
                'product': products[0][1] if len(products) == 1 else '', 'product_count': len(products),
                **{name: value for name, value in counts.items() if not name.startswith('_')},
                'on_time_rate': round(counts['on_time'] * 100 / completed, 1) if completed else 0,
            })
        return _score_rows(result, quality_key='on_time_rate', volume_key='completed',
                           success_key='on_time', minimum_sample=RECOGNITION_STANDINGS_MINIMUM_SAMPLE)

    requested_branch = str(branch or '').strip()
    context_keys = sorted(
        contexts,
        key=lambda item: (role_display_name(item[0]).casefold(), item[2].casefold()),
    )
    personal_contexts = {(key[2], key[3]) for key in people if key[0] == str(user.pk)}
    visible_context_keys = context_keys if include_people else [
        item for item in context_keys if (item[0], item[1]) in personal_contexts
    ]
    available_roles = {item[0] for item in visible_context_keys}
    requested_role = str(role or '').strip().upper()
    selected_role = requested_role if requested_role in available_roles else ''
    available_products = {
        item[1]: item[2] for item in visible_context_keys
        if not selected_role or item[0] == selected_role
    }
    requested_product = str(product or '').strip().lower()
    selected_product_key = requested_product if requested_product in available_products else ''
    selected_product_label = available_products.get(selected_product_key, '')
    available_branches = sorted({
        str(sample.get('branch') or 'Unassigned')
        for sample in (samples + branch_samples if include_people else samples)
        if (include_people or attribution(sample)[1] == str(user.pk))
        and (not selected_role or str(sample.get('role') or '').upper() == selected_role)
        and (not selected_product_key or str(sample.get('product_key') or '').lower() == selected_product_key)
    }, key=str.casefold)
    selected_branch = next((item for item in available_branches if item.casefold() == requested_branch.casefold()), '')

    role_options = [{'key': '', 'label': 'All roles'}] + [
        {'key': role_key, 'label': role_display_name(role_key)}
        for role_key in sorted(
            {item[0] for item in visible_context_keys}, key=lambda value: role_display_name(value).casefold(),
        )
    ]
    product_options = [{'key': '', 'label': 'All products'}] + [
        {'key': key, 'label': label}
        for key, label in sorted(available_products.items(), key=lambda item: item[1].casefold())
    ]
    branch_options = [{'key': '', 'label': 'All branches'}] + [
        {'key': item, 'label': item} for item in available_branches
    ]
    allowed_contexts = None if include_people else personal_contexts
    selected_people = scored_people_rows(selected_role, selected_product_key, selected_branch, allowed_contexts)
    selected_branches = scored_branch_rows(selected_role, selected_product_key, selected_branch, allowed_contexts)
    eligible_people = sum(1 for row in selected_people if row['ranked'])
    eligible_branches = sum(1 for row in selected_branches if row['ranked'])
    people_have_competition = eligible_people >= 2
    branches_have_competition = eligible_branches >= 2
    peer_numbers = {
        identity: index
        for index, identity in enumerate(
            sorted((row['key'] for row in selected_people), key=str.casefold), 1,
        )
    }

    def public_person(row):
        result = dict(row)
        is_current = row['key'] == str(user.pk)
        if is_current:
            result['label'] = 'You'
        elif not include_people:
            result['label'] = f"Peer {peer_numbers[row['key']]}"
        result['is_current_user'] = is_current
        for field in (
            'key', 'on_time', 'completed_total', 'overdue_recovered',
            'excluded_target_unavailable', 'corrected', 'attribution_fallback',
            'sample_status', 'score_basis', 'within_target', 'near_target',
        ):
            result.pop(field, None)
        return result

    def public_branch(row):
        result = dict(row)
        result['over_target'] = result.get('overdue_recovered', 0)
        for field in (
            'key', 'on_time', 'completed_total', 'overdue_recovered',
            'excluded_target_unavailable', 'corrected', 'attribution_fallback',
            'sample_status', 'score_basis',
        ):
            result.pop(field, None)
        return result

    personal = next((public_person(row) for row in selected_people if row['key'] == str(user.pk)), None)
    selected_view = str(view or 'personal').strip().lower()
    if selected_view not in {'personal', 'people', 'branches'}:
        selected_view = 'personal'
    source_rows = (
        selected_people if selected_view == 'people'
        else selected_branches if selected_view == 'branches'
        else []
    )
    if selected_view != 'personal':
        if captured_at:
            for row in source_rows:
                row['movement'] = {'direction': 'none', 'places': 0}
        else:
            _apply_live_rank_movement(
                user, group_id=str(group_id or '').strip(),
                scope_key=mode_snapshot(WORKFLOW_TAT).data_scope_key,
                period_kind=period_kind, period_key=label, view=selected_view,
                role=selected_role, product=selected_product_key, branch=selected_branch,
                include_people=include_people,
                rows=source_rows, observed_at=observed_at,
            )
    has_competition = (
        people_have_competition if selected_view == 'people'
        else branches_have_competition if selected_view == 'branches'
        else False
    )
    try:
        selected_page = max(1, int(page or 1))
    except (TypeError, ValueError):
        selected_page = 1
    page_size = 10
    page_count = max(1, (len(source_rows) + page_size - 1) // page_size)
    selected_page = min(selected_page, page_count)
    start_index = (selected_page - 1) * page_size
    page_rows = source_rows[start_index:start_index + page_size]
    current_user_row = None
    if selected_view == 'people':
        public_rows = [public_person(row) for row in page_rows]
        if not any(row['key'] == str(user.pk) for row in page_rows):
            current_user_row = next(
                (public_person(row) for row in selected_people if row['key'] == str(user.pk)),
                None,
            )
    elif selected_view == 'branches':
        public_rows = [public_branch(row) for row in page_rows]
    else:
        public_rows = []

    selected_counts = _empty_tat_counts()
    selected_stages = defaultdict(_empty_tat_counts)
    for sample in samples:
        sample_role = str(sample.get('role') or 'Unassigned').strip().upper()
        sample_product = str(sample.get('product_key') or sample.get('product') or '').strip().lower()
        sample_branch = str(sample.get('branch') or 'Unassigned')
        if ((selected_role and sample_role != selected_role)
                or (selected_product_key and sample_product != selected_product_key)
                or (selected_branch and sample_branch.casefold() != selected_branch.casefold())):
            continue
        assigned, person_identity, _ = attribution(sample)
        _accumulate_tat_sample(selected_counts, sample, attribution_fallback=not bool(assigned))
        if person_identity == str(user.pk):
            _accumulate_tat_sample(personal_slice, sample, attribution_fallback=not bool(assigned))
            stage_key = (sample_role, str(sample.get('stage_key') or ''), str(sample.get('stage') or 'Stage'))
            _accumulate_tat_sample(selected_stages[stage_key], sample, attribution_fallback=not bool(assigned))

    # Personal best is a live self-comparison over the actor's accessible cases.
    # Final period standings remain fixed independently of this current insight.
    if cases and str(view or 'personal').strip().lower() == 'personal':
        from core.services.tat_reporting import _ReportContext, _stage_samples
        all_time = _stage_samples(
            cases, {'stage': '', 'role': '', 'date_from': date(1900, 1, 1),
                    'date_to': date(9998, 12, 31), 'sla_state': ''},
            include_people=True, context=_ReportContext(user, cases, include_people=True),
        )
        for sample in all_time:
            assigned, person_identity, _ = attribution(sample)
            if person_identity != str(user.pk) or not sample.get('completed_at'):
                continue
            completed = datetime.fromisoformat(sample['completed_at'])
            if timezone.is_naive(completed):
                completed = timezone.make_aware(completed)
            month_key = timezone.localtime(completed).strftime('%Y-%m')
            _accumulate_tat_sample(personal_months[month_key], sample, attribution_fallback=not bool(assigned))

    def result_summary(counts):
        completed = int(counts['completed'])
        return {
            'completed': completed, 'completed_total': int(counts['completed_total']),
            'on_time_rate': round(counts['on_time'] * 100 / completed, 1) if completed else 0,
            'score': round(_wilson_lower_bound(counts['on_time'], completed), 1),
            'ranked': completed >= RECOGNITION_STANDINGS_MINIMUM_SAMPLE,
        }

    def breakdown(counts):
        scored = int(counts['completed'])
        return {
            'counted': scored, 'recorded': int(counts['completed_total']),
            'within_target': int(counts['within_target']),
            'near_target': int(counts['near_target']),
            'over_target': int(counts['overdue_recovered']),
            'target_unavailable': int(counts['excluded_target_unavailable']),
            'corrected': int(counts['corrected']),
            'attribution_fallback': int(counts['attribution_fallback']),
            'percentages': {
                key: round(counts[field] * 100 / scored, 1) if scored else 0
                for key, field in (
                    ('within_target', 'within_target'), ('near_target', 'near_target'),
                    ('over_target', 'overdue_recovered'),
                )
            } | {'target_unavailable': round(
                counts['excluded_target_unavailable'] * 100 / counts['completed_total'], 1,
            ) if counts['completed_total'] else 0},
        }

    stage_contributions = []
    if selected_stages:
        for (item_role, stage_key, stage_label), counts in selected_stages.items():
            if not counts['completed']:
                continue
            stage_contributions.append({
                'role': role_display_name(item_role), 'stage_key': stage_key,
                'stage': stage_label, **result_summary(counts), 'breakdown': breakdown(counts),
            })
        stage_contributions.sort(key=lambda item: (-item['completed'], item['stage'].casefold()))

    overall_stage_highlights = []
    if len(overall_roles) > 1:
        for (item_role, _stage_key, stage_label), counts in overall_stages.items():
            if counts['completed']:
                overall_stage_highlights.append({
                    'role': role_display_name(item_role), 'stage': stage_label,
                    'completed': int(counts['completed']),
                    'on_time_rate': round(counts['on_time'] * 100 / counts['completed'], 1),
                })
        overall_stage_highlights.sort(key=lambda item: (-item['completed'], item['stage'].casefold()))
        overall_stage_highlights = overall_stage_highlights[:2]

    personal_best = None
    if personal_months:
        qualified = [(key, counts) for key, counts in personal_months.items() if counts['completed'] >= minimum_sample]
        if qualified:
            best_key, best_counts = max(qualified, key=lambda item: (
                _wilson_lower_bound(item[1]['on_time'], item[1]['completed']), item[0],
            ))
            personal_best = {'month': best_key, **result_summary(best_counts)}

    selected_completed = int(selected_counts.get('completed') or 0)
    role_summary = {
        'completed': selected_completed,
        'role': selected_role,
        'role_label': role_display_name(selected_role) if selected_role else '',
        'product_key': selected_product_key, 'product': selected_product_label,
        'on_time_rate': round(
            int(selected_counts.get('on_time') or 0) * 100 / selected_completed, 1,
        ) if selected_completed else 0,
        'score': round(_wilson_lower_bound(int(selected_counts.get('on_time') or 0), selected_completed), 1),
    }
    methodology = None
    if include_people:
        methodology = {
            'score_method': 'The performance score is the 95% Wilson lower bound for on-time completion. It rewards consistent results without overstating small samples.',
            'cohort_basis': 'People count stage actions completed in the selected period. Each person appears once across the selected roles, products, and branches. Branches count completed stages on cases both created and finally resolved in that period; cases spanning periods do not enter a monthly branch cohort.',
            'correction_policy': 'Audited corrections update live results. A final period keeps the facts captured after its 30-day settlement window and does not change with later corrections. Recognition is informational, not an HR or compensation decision input.',
            'late_work_policy': 'Recovered overdue work remains visible in data checks but does not count as on time.',
            'completed_total': int(selected_counts.get('completed_total') or 0),
            'counted_total': selected_completed,
            'excluded_target_unavailable': int(selected_counts.get('excluded_target_unavailable') or 0),
            'corrected': int(selected_counts.get('corrected') or 0),
            'attribution_fallback': int(selected_counts.get('attribution_fallback') or 0),
            'overdue_recovered': int(selected_counts.get('overdue_recovered') or 0),
        }
    return {
        'contract_version': 3,
        'period': label, 'period_kind': period_kind, 'period_start': start.isoformat(),
        'period_end': end.isoformat(), 'minimum_ranked_sample': RECOGNITION_STANDINGS_MINIMUM_SAMPLE,
        'minimum_personal_best_sample': minimum_sample,
        'calculated_at': timezone.now().isoformat(),
        'data_revision': data_revision,
        'result_status': 'final' if captured_at else 'live_provisional',
        'captured_at': captured_at.isoformat() if captured_at else '',
        'view': selected_view,
        'role_options': role_options, 'product_options': product_options, 'branch_options': branch_options,
        'selected': {
            'role': selected_role,
            'role_label': role_display_name(selected_role) if selected_role else '',
            'product': selected_product_key, 'product_label': selected_product_label,
            'branch': selected_branch,
        },
        'overall_result': result_summary(personal_total),
        'overall_stage_highlights': overall_stage_highlights,
        'slice_result': {
            **result_summary(personal_slice),
            'share_of_overall': round(personal_slice['completed'] * 100 / personal_total['completed'], 1)
            if personal_total['completed'] else 0,
        },
        'breakdown': {'overall': breakdown(personal_total), 'slice': breakdown(personal_slice)},
        'stage_contributions': stage_contributions, 'personal_best': personal_best,
        'personal_result': personal, 'role_summary': role_summary,
        'standings': {
            'dimension': selected_view, 'rows': public_rows,
            'current_user_row': current_user_row,
            'page': selected_page, 'pages': page_count, 'total': len(source_rows),
            'page_size': page_size, 'has_competition': bool(has_competition),
            'eligible_count': (
                eligible_people if selected_view == 'people'
                else eligible_branches if selected_view == 'branches'
                else 0
            ),
        },
        'people_visible': bool(include_people),
        'technical_details_visible': bool(include_people),
        'methodology': methodology,
    }
