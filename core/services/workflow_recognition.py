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


def tat_recognition_payload(
    user, *, period: str = '', include_people: bool = False, group_id: str = '',
    role: str = '', product: str = '', view: str = 'personal', page: int = 1,
) -> dict:
    """Return one compact, group-scoped role/product recognition slice."""
    from core.models import TatActionTask, TatActionTaskRecipient, TatTrackerCase
    from core.services.tat_reporting import _ReportContext, _metric_scope_q, _stage_samples
    from core.services.tat_tracker import role_display_name

    start, end, label = _month_bounds(period)
    cases_qs = TatTrackerCase.objects.filter(_metric_scope_q(user), is_deleted=False)
    if str(group_id or '').strip():
        cases_qs = cases_qs.filter(group_id=str(group_id).strip())
    cases = list(cases_qs)
    filters = {'stage': '', 'role': '', 'date_from': start, 'date_to': end, 'sla_state': ''}
    samples = _stage_samples(
        cases, filters, include_people=True,
        context=_ReportContext(user, cases, include_people=True),
    )

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
    person_branches = defaultdict(set)
    branches = defaultdict(_empty_tat_counts)
    contexts = defaultdict(_empty_tat_counts)
    for sample in samples:
        assigned = responsibility.get((
            str(sample.get('group_id') or ''), str(sample.get('case_id') or ''),
            str(sample.get('stage_key') or ''),
        ))
        sample_role = str(sample.get('role') or 'Unassigned').strip().upper()
        branch = str(sample.get('branch') or 'Unassigned')
        product_label = str(sample.get('product') or sample.get('product_key') or 'Unassigned').strip()
        product_key = str(sample.get('product_key') or product_label).strip().lower()
        context_key = (sample_role, product_key, product_label)
        branch_key = (*context_key, branch)
        for target in (branches[branch_key], contexts[context_key]):
            _accumulate_tat_sample(target, sample, attribution_fallback=not bool(assigned))
        actor_roles = {
            value.strip().upper()
            for value in str(sample.get('person_roles') or '').split(',') if value.strip()
        }
        technical_override = not assigned and 'IT' in actor_roles and sample_role not in actor_roles
        person_identity = assigned[0] if assigned else str(sample.get('person_user_id') or '').strip()
        person_label = assigned[1] if assigned else str(sample.get('person') or '').strip()
        if technical_override or not (person_identity or person_label):
            continue
        person_key = person_identity or f'label:{person_label}'
        person_key_tuple = (person_key, person_label or 'Unassigned', *context_key)
        person_branches[person_key_tuple].add(branch)
        _accumulate_tat_sample(
            people[person_key_tuple], sample, attribution_fallback=not bool(assigned),
        )

    def scored_people_rows():
        result = []
        for key, counts in people.items():
            identity, display, item_role, product_key, product_label = key
            completed = counts['completed']
            public_counts = {name: value for name, value in counts.items() if not name.startswith('_')}
            item_branches = sorted(person_branches[key], key=str.casefold)
            result.append({
                'key': str(identity), 'label': display, **public_counts,
                'role': item_role, 'product_key': product_key, 'product': product_label,
                'branch': item_branches[0] if len(item_branches) == 1 else '',
                'branch_count': len(item_branches), '_rank_group': f'{item_role}|{product_key}',
                'on_time_rate': round(counts['on_time'] * 100 / completed, 1) if completed else 0,
            })
        scored = _score_rows(
            result, quality_key='on_time_rate', volume_key='completed', success_key='on_time',
            rank_group_key='_rank_group',
        )
        for row in scored:
            row.pop('_rank_group', None)
        return scored

    def scored_branch_rows():
        result = []
        for (item_role, product_key, product_label, branch), counts in branches.items():
            completed = counts['completed']
            public_counts = {name: value for name, value in counts.items() if not name.startswith('_')}
            result.append({
                'key': f'branch-{sha256(f"{item_role}|{product_key}|{branch}".encode("utf-8")).hexdigest()[:12]}',
                'label': branch, 'branch': branch, 'role': item_role,
                'product_key': product_key, 'product': product_label, **public_counts,
                '_rank_group': f'{item_role}|{product_key}',
                'on_time_rate': round(counts['on_time'] * 100 / completed, 1) if completed else 0,
            })
        scored = _score_rows(
            result, quality_key='on_time_rate', volume_key='completed', success_key='on_time',
            rank_group_key='_rank_group',
        )
        for row in scored:
            row.pop('_rank_group', None)
        return scored

    person_rows = scored_people_rows()
    branch_rows = scored_branch_rows()
    context_keys = sorted(
        contexts,
        key=lambda item: (role_display_name(item[0]).casefold(), item[2].casefold()),
    )
    personal_candidates = [row for row in person_rows if row['key'] == str(user.pk)]
    personal_contexts = {
        (row['role'], row['product_key']) for row in personal_candidates
    }
    visible_context_keys = context_keys if include_people else [
        item for item in context_keys if (item[0], item[1]) in personal_contexts
    ]
    requested_role = str(role or '').strip().upper()
    requested_product = str(product or '').strip().lower()
    selected = next(
        (item for item in visible_context_keys if item[0] == requested_role and item[1] == requested_product),
        None,
    )
    if selected is None and requested_role:
        role_contexts = [item for item in visible_context_keys if item[0] == requested_role]
        if role_contexts:
            selected = sorted(
                role_contexts,
                key=lambda item: (-int(contexts[item].get('completed') or 0), item[2].casefold()),
            )[0]
    if selected is None and personal_candidates:
        preferred = sorted(
            personal_candidates,
            key=lambda row: (-int(row.get('completed') or 0), row['role'], row['product']),
        )[0]
        selected = next(
            item for item in visible_context_keys
            if item[0] == preferred['role'] and item[1] == preferred['product_key']
        )
    if selected is None and visible_context_keys:
        selected = sorted(
            visible_context_keys,
            key=lambda item: (-int(contexts[item].get('completed') or 0), item[0], item[2]),
        )[0]
    selected = selected or ('', '', '')
    selected_role, selected_product_key, selected_product_label = selected

    role_options = [
        {'key': role_key, 'label': role_display_name(role_key)}
        for role_key in sorted(
            {item[0] for item in visible_context_keys}, key=lambda value: role_display_name(value).casefold(),
        )
    ]
    product_options = [
        {'key': item[1], 'label': item[2]}
        for item in visible_context_keys if item[0] == selected_role
    ]
    selected_people = [
        row for row in person_rows
        if row['role'] == selected_role and row['product_key'] == selected_product_key
    ]
    selected_branches = [
        row for row in branch_rows
        if row['role'] == selected_role and row['product_key'] == selected_product_key
    ]
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
        result['rank'] = row.get('rank') if people_have_competition else None
        for field in (
            'key', 'on_time', 'completed_total', 'overdue_recovered',
            'excluded_target_unavailable', 'corrected', 'attribution_fallback',
            'sample_status', 'score_basis',
        ):
            result.pop(field, None)
        return result

    def public_branch(row):
        result = dict(row)
        result['rank'] = row.get('rank') if branches_have_competition else None
        for field in (
            'key', 'on_time', 'completed_total', 'overdue_recovered',
            'excluded_target_unavailable', 'corrected', 'attribution_fallback',
            'sample_status', 'score_basis',
        ):
            result.pop(field, None)
        return result

    personal = next(
        (public_person(row) for row in selected_people if row['key'] == str(user.pk)),
        None,
    )
    selected_view = str(view or 'personal').strip().lower()
    if selected_view not in {'personal', 'people', 'branches'}:
        selected_view = 'personal'
    source_rows = (
        selected_people if selected_view == 'people'
        else selected_branches if selected_view == 'branches'
        else []
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
    page_size = 5
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

    selected_counts = contexts.get(selected, _empty_tat_counts())
    selected_completed = int(selected_counts.get('completed') or 0)
    role_summary = {
        'completed': selected_completed,
        'role': selected_role,
        'role_label': role_display_name(selected_role) if selected_role else '',
        'product_key': selected_product_key, 'product': selected_product_label,
        'on_time_rate': round(
            int(selected_counts.get('on_time') or 0) * 100 / selected_completed, 1,
        ) if selected_completed else 0,
        'score': round(
            _wilson_lower_bound(int(selected_counts.get('on_time') or 0), selected_completed), 1,
        ),
    }
    methodology = None
    if include_people:
        methodology = {
            'score_method': 'The performance score is the 95% Wilson lower bound for on-time completion. It rewards consistent results without overstating small samples.',
            'cohort_basis': 'People are compared within the current TAT group, role, and product. Branch standings describe the originating cases, not staff assignment.',
            'correction_policy': 'Audited timestamp corrections update live results retrospectively. These results are not permanent awards.',
            'late_work_policy': 'Recovered overdue work remains visible in data checks but does not count as on time.',
            'completed_total': int(selected_counts.get('completed_total') or 0),
            'counted_total': selected_completed,
            'excluded_target_unavailable': int(selected_counts.get('excluded_target_unavailable') or 0),
            'corrected': int(selected_counts.get('corrected') or 0),
            'attribution_fallback': int(selected_counts.get('attribution_fallback') or 0),
            'overdue_recovered': int(selected_counts.get('overdue_recovered') or 0),
        }
    return {
        'contract_version': 2,
        'period': label, 'minimum_ranked_sample': MINIMUM_RANKED_SAMPLE,
        'calculated_at': timezone.now().isoformat(),
        'result_status': 'live_provisional', 'view': selected_view,
        'role_options': role_options, 'product_options': product_options,
        'selected': {
            'role': selected_role,
            'role_label': role_display_name(selected_role) if selected_role else '',
            'product': selected_product_key, 'product_label': selected_product_label,
        },
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
