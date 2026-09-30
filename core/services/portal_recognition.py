"""Officer-owned Portal case milestones and versioned, scoped standings."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from hashlib import sha256
import json

from django.db import transaction
from django.utils import timezone

from core.services.workflow_recognition import _recognition_period


SCORE_POLICY_VERSION = 2
MILESTONES = (
    ('jbl_visit_completed', 'JBL visit'),
    ('credit_decision_recorded', 'Credit approved'),
    ('final_decision_recorded', 'Final approval'),
    ('order.released_to_hb', 'Signed order'),
    ('installation_completed', 'Installed'),
    ('commissioning_completed', 'Commissioned'),
)
PIPELINE_ACTIONS = {key for key, _ in MILESTONES[:3]}
HB_EVENTS = {'order.released_to_hb', 'installation.progressed', 'commissioning.completed'}


def _action_code(event):
    action = getattr(event, 'action', None)
    return action if isinstance(action, str) else getattr(event, 'event_type', '')


def _scoped_cases(user, capability, access):
    from core.services.jawabu_pipeline import all_cases
    from core.services.workflow_access import scope_workflow_queryset
    return scope_workflow_queryset(
        all_cases(), user, 'jawabu_portal', capability, access=access,
        branch_field='branch', product_field='product__code',
        group_field='group_configuration__group_id',
    )


def _access_signature(user):
    from core.models import AccessGrant
    from core.services.access_control import policy_version
    grants = list(AccessGrant.objects.filter(user=user, workflow='jawabu_portal', active=True)
                  .order_by('pk').values_list('pk', 'role', 'group_configuration_id', 'branch', 'product'))
    value = [bool(user.is_active and user.is_superuser), policy_version(),
             [[str(part) for part in grant] for grant in grants]]
    return sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def _event_milestone(event):
    """A rejected visit still happened; later stages require successful outcomes."""
    action = _action_code(event)
    values = event.new_values or {}
    decision = str(values.get('decision') or '').casefold()
    if action == 'jbl_visit_completed':
        return action
    if action == 'credit_decision_recorded' and decision in {'approved', 'exemption approved'}:
        return action
    if action == 'final_decision_recorded' and decision == 'approved':
        return action
    if action == 'order.released_to_hb':
        return action
    if action == 'installation.progressed' and values.get('installation_status') == 'installed':
        return 'installation_completed'
    if action == 'commissioning.completed' and values.get('commissioning_status') == 'commissioned':
        return 'commissioning_completed'
    return ''


def _facts_for_cases(cases, *, start, end, frozen_awards=None):
    """One currently valid point per case/milestone, owned by its first JBL visitor."""
    from core.models import AccessGrant, JawabuPipelineEvent
    from hb_operations.models import HomeBiogasActionEvent

    frozen_awards = frozen_awards or set()
    candidates = set(JawabuPipelineEvent.objects.filter(
        farmer__in=cases, action__in=PIPELINE_ACTIONS,
        occurred_at__date__range=(start, end),
    ).values_list('farmer_id', flat=True))
    candidates.update(HomeBiogasActionEvent.objects.filter(
        action__farmer__in=cases, event_type__in=HB_EVENTS,
        created_at__date__range=(start, end),
    ).values_list('action__farmer_id', flat=True))
    case_rows = list(cases.filter(pk__in=candidates).select_related('product'))
    if not case_rows:
        return []
    case_by_id = {case.pk: case for case in case_rows}
    events_by_case = defaultdict(list)
    for event in JawabuPipelineEvent.objects.filter(
        farmer_id__in=case_by_id, action__in=[*PIPELINE_ACTIONS, 'returned_for_rework'],
    ).select_related('actor_user').order_by('occurred_at', 'created_at', 'pk'):
        events_by_case[event.farmer_id].append(event)
    for event in HomeBiogasActionEvent.objects.filter(
        action__farmer_id__in=case_by_id, event_type__in=HB_EVENTS,
    ).order_by('created_at', 'pk'):
        events_by_case[event.action.farmer_id].append(event)

    visit_actor_ids = {event.actor_user_id for events in events_by_case.values() for event in events
                       if getattr(event, 'action', '') == 'jbl_visit_completed' and event.actor_user_id}
    officer_ids = set(AccessGrant.objects.filter(
        workflow='jawabu_portal', role='JBL_OFFICER', user_id__in=visit_actor_ids,
    ).values_list('user_id', flat=True))
    owners = {}
    for case in case_rows:
        visits = [event for event in events_by_case[case.pk]
                  if getattr(event, 'action', '') == 'jbl_visit_completed' and event.actor_user_id in officer_ids]
        if visits:
            owners[case.pk] = min(visits, key=lambda item: (item.occurred_at, item.created_at, str(item.pk))).actor_user

    facts = []
    for case in case_rows:
        owner = owners.get(case.pk)
        if not owner or owner.pk not in officer_ids:
            continue  # No text-only/technical-override person on an officer standing.
        events = sorted(events_by_case[case.pk], key=lambda item: (
            getattr(item, 'occurred_at', None) or item.created_at, item.created_at, str(item.pk),
        ))
        awards = {}
        for event in events:
            action = _action_code(event)
            event_at = getattr(event, 'occurred_at', None) or event.created_at
            if action == 'jbl_visit_completed' and event.actor_user_id != owner.pk:
                continue
            if action == 'returned_for_rework':
                stage = str(event.stage_key or '')
                reverse = {'credit': 'credit_decision_recorded',
                           'final_review': 'final_decision_recorded', 'order': 'order.released_to_hb'}
                awards.pop(reverse.get(stage, stage), None)
                continue
            # Later rejected/deferred decisions invalidate an earlier approval.
            if action in {'credit_decision_recorded', 'final_decision_recorded'}:
                if not _event_milestone(event):
                    awards.pop(action, None)
            if action == 'installation.progressed' and (event.new_values or {}).get('installation_status') != 'installed':
                awards.pop('installation_completed', None)
            if action == 'commissioning.completed' and (event.new_values or {}).get('commissioning_status') != 'commissioned':
                awards.pop('commissioning_completed', None)
            milestone = _event_milestone(event)
            if milestone:
                awards.setdefault(milestone, event_at)
        for milestone, event_at in awards.items():
            if not start <= timezone.localdate(event_at) <= end:
                continue
            if (str(case.pk), milestone) in frozen_awards:
                continue
            facts.append({
                'case_id': str(case.pk), 'group_id': case.group_configuration_id or 0,
                'person_id': str(owner.pk),
                'person': owner.get_full_name().strip() or owner.get_username(),
                'stage': milestone,
                'branch': str(case.system_branch or case.branch or 'Unassigned'),
                'product': str((case.product.code if case.product_id else '')
                               or case.payment_product or case.hbg_contract_name or 'Unassigned'),
                'completed_at': event_at.isoformat(),
            })
    return facts


def _frozen_awards(group_id, kind):
    from portal_recognition.models import PortalRecognitionPeriodSnapshot
    keys = set()
    for facts in PortalRecognitionPeriodSnapshot.objects.filter(
        group_configuration_id=group_id or 0, period_kind=kind,
        score_policy_version=SCORE_POLICY_VERSION,
    ).values_list('facts', flat=True):
        keys.update((item['case_id'], item['stage']) for item in facts)
    return keys


def _period_facts(user, *, start, end, kind, key, access):
    from core.services.jawabu_pipeline import all_cases
    from portal_recognition.models import PortalRecognitionPeriodSnapshot

    scoped = _scoped_cases(user, 'portal.performance.view', access)
    case_ids = {str(pk) for pk in scoped.values_list('pk', flat=True)}
    group_ids = sorted(set(scoped.values_list('group_configuration_id', flat=True)), key=lambda item: item or 0)
    settled = timezone.localdate() > end + timedelta(days=30)
    if not settled:
        frozen = set().union(*(_frozen_awards(group_id, kind) for group_id in group_ids)) if group_ids else set()
        return _facts_for_cases(scoped, start=start, end=end, frozen_awards=frozen), False, None, group_ids
    facts, captured = [], []
    for group_id in group_ids:
        owned = all_cases().filter(group_configuration_id=group_id)
        defaults = {'facts': _facts_for_cases(
            owned, start=start, end=end, frozen_awards=_frozen_awards(group_id, kind),
        )}
        with transaction.atomic():
            snapshot, _ = PortalRecognitionPeriodSnapshot.objects.get_or_create(
                group_configuration_id=group_id or 0, period_kind=kind,
                period_key=key, score_policy_version=SCORE_POLICY_VERSION, defaults=defaults,
            )
        facts.extend(snapshot.facts)
        captured.append(snapshot.captured_at)
    return [fact for fact in facts if fact['case_id'] in case_ids], True, (
        max(captured).isoformat() if captured else None), group_ids


def _aggregate(facts, *, key_name):
    labels = dict(MILESTONES)
    groups = defaultdict(lambda: {'points': 0, 'stages': defaultdict(int), 'cases': set(), 'visits': 0})
    names = {}
    for fact in facts:
        key = fact['person_id'] if key_name == 'person' else fact['branch']
        item = groups[key]
        item['points'] += 1
        item['stages'][fact['stage']] += 1
        item['cases'].add(fact['case_id'])
        item['visits'] += int(fact['stage'] == 'jbl_visit_completed')
        names[key] = fact['person'] if key_name == 'person' else fact['branch']
    rows = [dict(key=str(key), label=names[key], score=value['points'], points=value['points'],
                 visits=value['visits'], cases=len(value['cases']),
                 milestones=[{'key': stage, 'label': labels[stage], 'count': value['stages'][stage]}
                             for stage, _ in MILESTONES])
            for key, value in groups.items()]
    rows.sort(key=lambda item: (-item['points'], -item['visits'], item['label'].casefold()))
    previous_points, rank = None, 0
    for index, item in enumerate(rows, 1):
        if item['points'] != previous_points:
            rank = index
            previous_points = item['points']
        item['rank'] = rank
    return rows


def _rank_movement(user, *, context, group_ids, rows, observed_at):
    from portal_recognition.models import PortalRecognitionLiveStanding
    identity = [str(user.pk), _access_signature(user), SCORE_POLICY_VERSION, *context]
    context_key = sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    ranks = {item['key']: item['rank'] for item in rows}
    signature = sha256(json.dumps([(item['key'], item['rank'], item['points']) for item in rows],
                                   sort_keys=True).encode()).hexdigest()
    with transaction.atomic():
        expired_ids = list(PortalRecognitionLiveStanding.objects.filter(expires_at__lt=observed_at)
                           .order_by('expires_at').values_list('pk', flat=True)[:100])
        if expired_ids:
            PortalRecognitionLiveStanding.objects.filter(pk__in=expired_ids).delete()
        checkpoint, created = PortalRecognitionLiveStanding.objects.get_or_create(
            context_key=context_key,
            defaults={'viewer': user, 'group_configuration_ids': group_ids, 'ranks': ranks,
                      'signature': signature, 'movement': {}, 'observed_at': observed_at,
                      'expires_at': observed_at + timedelta(days=45)},
        )
        if not created:
            checkpoint = PortalRecognitionLiveStanding.objects.select_for_update().get(pk=checkpoint.pk)
            if checkpoint.signature != signature and checkpoint.observed_at <= observed_at:
                previous = checkpoint.ranks or {}
                movement = {}
                for key, rank in ranks.items():
                    if key in previous:
                        delta = int(previous[key]) - rank
                        movement[key] = {'direction': 'up' if delta > 0 else 'down' if delta < 0 else 'none',
                                         'places': abs(delta)}
                checkpoint.ranks, checkpoint.signature, checkpoint.movement = ranks, signature, movement
                checkpoint.observed_at, checkpoint.expires_at = observed_at, observed_at + timedelta(days=45)
                checkpoint.save(update_fields=['ranks', 'signature', 'movement', 'observed_at', 'expires_at'])
        movement = checkpoint.movement or {}
    for row in rows:
        row['movement'] = movement.get(row['key'], {'direction': 'none', 'places': 0})


def portal_recognition_payload(user, *, access=None, period='', period_kind='month',
                               view='people', branch='', product='', page=1, include_people=False):
    if access is None:
        from core.services.telegram_identity import user_access
        access = user_access(user, 'jawabu_portal')
    if view not in {'people', 'branches'}:
        raise ValueError('Choose a valid performance standing.')
    start, end, key, kind = _recognition_period(period_kind, period)
    observed_at = timezone.now()
    facts, final, captured_at, group_ids = _period_facts(
        user, start=start, end=end, kind=kind, key=key, access=access,
    )
    named_case_ids = ({str(pk) for pk in _scoped_cases(
        user, 'portal.performance.people.view', access,
    ).values_list('pk', flat=True)} if include_people else set())
    own = [fact for fact in facts if fact['person_id'] == str(user.pk)]
    branches = sorted({fact['branch'] for fact in facts})
    if branch not in branches:
        branch = ''
    products = sorted({fact['product'] for fact in facts if not branch or fact['branch'] == branch})
    if product not in products:
        product = ''
    selected = [fact for fact in facts if (not branch or fact['branch'] == branch)
                and (not product or fact['product'] == product)]
    personal = (_aggregate(own, key_name='person') or [None])[0]
    slice_result = (_aggregate([fact for fact in selected if fact['person_id'] == str(user.pk)],
                               key_name='person') or [None])[0]
    if view == 'people' and not include_people:
        view = 'branches'
    standing_facts = ([fact for fact in selected if fact['case_id'] in named_case_ids]
                      if view == 'people' else selected)
    rows = _aggregate(standing_facts, key_name='person' if view == 'people' else 'branch')
    if final:
        for row in rows:
            row['movement'] = {'direction': 'none', 'places': 0}
    else:
        _rank_movement(user, context=[kind, key, view, branch, product, include_people],
                       group_ids=group_ids, rows=rows, observed_at=observed_at)
    try:
        page = max(1, int(page))
    except (TypeError, ValueError):
        page = 1
    pages = max(1, (len(rows) + 9) // 10)
    page = min(page, pages)

    def public(row):
        return {key: value for key, value in row.items() if key != 'key'} if row else None

    return {
        'period': key, 'period_kind': kind, 'view': view, 'branch': branch, 'product': product,
        'score_policy_version': SCORE_POLICY_VERSION,
        'filter_options': {'branches': branches, 'products': products,
                           'products_by_branch': {name: sorted({fact['product'] for fact in facts
                                                               if fact['branch'] == name}) for name in branches}},
        'personal': public(personal), 'slice': public(slice_result),
        'rows': [public(row) for row in rows[(page - 1) * 10:page * 10]],
        'page': page, 'pages': pages, 'total': len(rows),
        'people_visible': bool(include_people), 'final': final,
        'captured_at': captured_at, 'calculated_at': observed_at.isoformat(),
    }
