"""Capability-scoped Portal performance from audited, attributable milestones."""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from hashlib import sha256
import json

from django.db import transaction
from django.db.models import OuterRef, Subquery
from django.utils import timezone

from core.services.workflow_recognition import (
    MINIMUM_RANKED_SAMPLE, _recognition_period, _score_rows,
)


STAGES = {
    'jbl_visit_completed': ('JBL_OFFICER', 'JBL visit', 'application_imported_to_jbl_visit_completed'),
    'credit_decision_recorded': ('CREDIT_ANALYST', 'Credit decision', 'jbl_visit_completed_to_credit_decision_recorded'),
    'final_decision_recorded': ('BUSINESS_ADMIN', 'Final review', 'credit_decision_recorded_to_final_decision_recorded'),
    'order_assigned': ('OPERATIONS_ADMIN', 'Order', 'final_decision_recorded_to_order_assigned'),
    'installation_completed': ('HB_STAFF', 'Installation', 'hb_order_released_to_installation_completed'),
    'commissioning_completed': ('HB_STAFF', 'Commissioning', 'installation_completed_to_commissioning_completed'),
    'payment_finalized': ('OPERATIONS_ADMIN', 'Payment finalized', ''),
}
ROLE_LABELS = {
    'JBL_OFFICER': 'JBL Officer', 'CREDIT_ANALYST': 'Credit Analyst',
    'BUSINESS_ADMIN': 'Head of Rural', 'OPERATIONS_ADMIN': 'Operations',
    'HB_STAFF': 'HomeBiogas',
}
PIPELINE_ACTIONS = frozenset(STAGES) - {'installation_completed', 'commissioning_completed'}


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


def _facts_for_cases(cases, *, start, end):
    """One first-completed action per case/stage; later edits update its live quality."""
    from core.models import JawabuPipelineEvent
    from hb_operations.models import HomeBiogasActionEvent
    from core.services.jawabu_case360 import calculate_case_tat

    candidate_ids = set(JawabuPipelineEvent.objects.filter(
        farmer__in=cases, action__in=PIPELINE_ACTIONS,
        occurred_at__date__range=(start, end),
    ).values_list('farmer_id', flat=True))
    candidate_ids.update(HomeBiogasActionEvent.objects.filter(
        action__farmer__in=cases,
        event_type__in=['installation.progressed', 'commissioning.completed'],
        created_at__date__range=(start, end),
    ).values_list('action__farmer_id', flat=True))
    cases = list(cases.filter(pk__in=candidate_ids).select_related('product'))
    if not cases:
        return []
    by_case = {case.pk: case for case in cases}
    pipeline = defaultdict(list)
    for event in JawabuPipelineEvent.objects.filter(farmer_id__in=by_case, action__in=[*PIPELINE_ACTIONS, 'returned_for_rework'])\
            .select_related('actor_user').order_by('occurred_at', 'created_at', 'pk'):
        pipeline[event.farmer_id].append(event)
    hb = defaultdict(list)
    for event in HomeBiogasActionEvent.objects.filter(action__farmer_id__in=by_case,
            event_type__in=['installation.progressed', 'commissioning.completed'])\
            .select_related('actor').order_by('created_at', 'pk'):
        hb[event.action.farmer_id].append(event)

    facts = []
    for case in cases:
        events = pipeline[case.pk]
        first = {}
        latest = {}
        for event in events:
            if event.action not in PIPELINE_ACTIONS:
                continue
            first.setdefault(event.action, event)
            latest[event.action] = event
        for event in hb[case.pk]:
            values = event.new_values or {}
            stage = ('installation_completed' if event.event_type == 'installation.progressed'
                     and values.get('installation_status') == 'installed' else
                     'commissioning_completed' if event.event_type == 'commissioning.completed'
                     and values.get('commissioning_status') == 'commissioned' else '')
            if stage:
                first.setdefault(stage, event)
                latest[stage] = event
        tat_by_key = None
        for stage, initial in first.items():
            completed_at = getattr(initial, 'occurred_at', None) or initial.created_at
            if not start <= timezone.localdate(completed_at) <= end:
                continue
            role, label, tat_key = STAGES[stage]
            current = latest[stage]
            actor = getattr(initial, 'actor_user', None) or getattr(initial, 'actor', None)
            # Legacy text-only actors are deliberately not placed on named standings.
            if not actor or not hasattr(actor, 'pk'):
                continue
            current_at = getattr(current, 'occurred_at', None) or current.created_at
            returns = [event for event in events if event.action == 'returned_for_rework'
                       and event.occurred_at > current_at and event.stage_key in {
                           getattr(initial, 'stage_key', ''), stage.replace('_completed', ''),
                       }]
            if tat_key and tat_by_key is None:
                tat_by_key = {item['key']: item for item in calculate_case_tat(case)['stages']}
            tat = (tat_by_key or {}).get(tat_key) or {}
            tat_state = tat.get('status') if tat.get('completed_at') else ''
            if tat_state not in {'within', 'near', 'over'}:
                tat_state = ''
            branch = str(case.system_branch or case.branch or 'Unassigned')
            product = str((case.product.code if case.product_id else '')
                          or case.payment_product or case.hbg_contract_name or 'Unassigned')
            facts.append({
                'case_id': str(case.pk), 'group_id': case.group_configuration_id or 0,
                'person_id': str(actor.pk),
                'person': actor.get_full_name().strip() or actor.get_username(),
                'role': role, 'stage': stage, 'stage_label': label,
                'branch': branch, 'product': product,
                'completed_at': completed_at.isoformat(),
                'accepted': not bool(returns), 'tat_state': tat_state,
            })
    return facts


def _period_facts(user, *, start, end, kind, key, access):
    from core.services.jawabu_pipeline import all_cases
    from portal_recognition.models import PortalRecognitionPeriodSnapshot

    scoped = _scoped_cases(user, 'portal.performance.view', access)
    case_ids = list(scoped.values_list('pk', flat=True))
    group_ids = sorted(set(scoped.values_list('group_configuration_id', flat=True)), key=lambda item: item or 0)
    settled = timezone.localdate() > end + timedelta(days=30)
    if not settled:
        return _facts_for_cases(scoped, start=start, end=end), False, None, group_ids
    facts = []
    captured = []
    for group_id in group_ids:
        owned = all_cases().filter(group_configuration_id=group_id)
        defaults = {'facts': _facts_for_cases(owned, start=start, end=end)}
        with transaction.atomic():
            snapshot, _ = PortalRecognitionPeriodSnapshot.objects.get_or_create(
                group_configuration_id=group_id or 0, period_kind=kind,
                period_key=key, defaults=defaults,
            )
        facts.extend(snapshot.facts)
        captured.append(snapshot.captured_at)
    allowed = {str(item) for item in case_ids}
    return [fact for fact in facts if fact['case_id'] in allowed], True, (
        max(captured).isoformat() if captured else None), group_ids


def _aggregate(facts, *, metric, key_name):
    groups = defaultdict(lambda: {'completed': 0, 'accepted': 0, 'reworked': 0,
                                  'within': 0, 'near': 0, 'over': 0, 'stages': defaultdict(int)})
    for fact in facts:
        if metric == 'tat' and not fact['tat_state']:
            continue
        identity = fact['person_id'] if key_name == 'person' else fact['branch']
        item = groups[identity]
        item['completed'] += 1
        item['accepted'] += int(fact['accepted'])
        item['reworked'] += int(not fact['accepted'])
        item['within'] += int(fact['tat_state'] == 'within')
        item['near'] += int(fact['tat_state'] == 'near')
        item['over'] += int(fact['tat_state'] == 'over')
        item['stages'][fact['stage_label']] += 1
    rows = []
    labels = {fact['person_id'] if key_name == 'person' else fact['branch']:
              fact['person'] if key_name == 'person' else fact['branch'] for fact in facts}
    for key, count in groups.items():
        successes = count['accepted'] if metric == 'outcome' else count['within'] + count['near']
        rows.append({'key': str(key), 'label': labels[key],
                     'completed': count['completed'], 'accepted': count['accepted'],
                     'reworked': count['reworked'], 'within': count['within'],
                     'near': count['near'], 'over': count['over'],
                     'successes': successes, 'success_rate': round(successes * 100 / count['completed'], 1),
                     'stages': [{'label': name, 'completed': volume}
                                for name, volume in sorted(count['stages'].items(), key=lambda pair: -pair[1])]})
    return _score_rows(rows, quality_key='success_rate', volume_key='completed',
                       success_key='successes', minimum_sample=MINIMUM_RANKED_SAMPLE)


def _business_context(user, *, access, start, end):
    """Current downstream conversions; shown as context, never as staff score."""
    from core.models import JawabuPipelineEvent
    from core.services.jawabu_pipeline import JBL_FORWARD_STATUSES

    scoped = _scoped_cases(user, 'portal.performance.view', access)
    first = JawabuPipelineEvent.objects.filter(
        farmer_id=OuterRef('farmer_id'), action='jbl_visit_completed',
    ).order_by('occurred_at', 'created_at', 'pk').values('pk')[:1]
    visit_ids = list(JawabuPipelineEvent.objects.filter(
        farmer__in=scoped, action='jbl_visit_completed', pk=Subquery(first),
        occurred_at__date__range=(start, end),
    ).values_list('farmer_id', flat=True))
    if not visit_ids:
        return {'visits': 0, 'to_credit': 0, 'final_approved': 0, 'payment_finalized': 0}
    from core.models import JawabuFarmerMaster
    to_credit = JawabuFarmerMaster.objects.filter(pk__in=visit_ids,
        jbl_visit_status__in=JBL_FORWARD_STATUSES).count()
    approved = set()
    paid = set()
    for event in JawabuPipelineEvent.objects.filter(
        farmer_id__in=visit_ids, action__in=['final_decision_recorded', 'payment_finalized'],
    ).values('farmer_id', 'action', 'new_values'):
        if event['action'] == 'payment_finalized':
            paid.add(event['farmer_id'])
        elif str((event['new_values'] or {}).get('decision') or '').casefold() == 'approved':
            approved.add(event['farmer_id'])
    return {'visits': len(visit_ids), 'to_credit': to_credit,
            'final_approved': len(approved), 'payment_finalized': len(paid)}


def _rank_movement(user, *, context, group_ids, rows, observed_at):
    from portal_recognition.models import PortalRecognitionLiveStanding
    identity = [str(user.pk), _access_signature(user), *context]
    context_key = sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    ranks = {item['key']: item['rank'] for item in rows if item['rank'] is not None}
    signature = sha256(json.dumps([(item['key'], item['rank'], item['score'], item['completed'])
                                   for item in rows], sort_keys=True).encode()).hexdigest()
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
                checkpoint.ranks = ranks
                checkpoint.signature = signature
                checkpoint.movement = movement
                checkpoint.observed_at = observed_at
                checkpoint.expires_at = observed_at + timedelta(days=45)
                checkpoint.save(update_fields=['ranks', 'signature', 'movement', 'observed_at', 'expires_at'])
        movement = checkpoint.movement or {}
    for row in rows:
        row['movement'] = movement.get(row['key'], {'direction': 'none', 'places': 0})


def portal_recognition_payload(user, *, access=None, period='', period_kind='month',
                               metric='outcome', view='people', role='', branch='', product='',
                               page=1, include_people=False):
    if access is None:
        # The generic scope helper interprets None as explicit local/test mode.
        # Performance must never turn a missing request context into a wildcard.
        from core.services.telegram_identity import user_access
        access = user_access(user, 'jawabu_portal')
    start, end, key, kind = _recognition_period(period_kind, period)
    if metric not in {'outcome', 'tat'} or view not in {'people', 'branches'}:
        raise ValueError('Choose a valid performance standing.')
    observed_at = timezone.now()
    facts, final, captured_at, group_ids = _period_facts(user, start=start, end=end,
                                                         kind=kind, key=key, access=access)
    if include_people:
        named_case_ids = {str(pk) for pk in _scoped_cases(
            user, 'portal.performance.people.view', access,
        ).values_list('pk', flat=True)}
    else:
        named_case_ids = set()
    own = [fact for fact in facts if fact['person_id'] == str(user.pk)]
    roles = sorted({fact['role'] for fact in facts})
    own_roles = Counter(fact['role'] for fact in own)
    default_role = sorted(own_roles, key=lambda item: (-own_roles[item], ROLE_LABELS.get(item, item)))[:1]
    selected_role = role if role in roles else (default_role[0] if default_role else (roles[0] if roles else ''))
    role_facts = [fact for fact in facts if fact['role'] == selected_role]
    branches = sorted({fact['branch'] for fact in role_facts})
    if branch not in branches:
        branch = ''
    products = sorted({fact['product'] for fact in role_facts
                       if not branch or fact['branch'] == branch})
    if product not in products:
        product = ''
    options = {
        'roles': [{'value': item, 'label': ROLE_LABELS.get(item, item)} for item in roles],
        'branches': branches, 'products': products,
        'by_role': {
            item: {
                'branches': sorted({fact['branch'] for fact in facts if fact['role'] == item}),
                'products_by_branch': {
                    name: sorted({fact['product'] for fact in facts
                                  if fact['role'] == item and fact['branch'] == name})
                    for name in {fact['branch'] for fact in facts if fact['role'] == item}
                },
                'products': sorted({fact['product'] for fact in facts if fact['role'] == item}),
            } for item in roles
        },
    }
    selected = [fact for fact in facts if (not selected_role or fact['role'] == selected_role)
                and (not branch or fact['branch'] == branch)
                and (not product or fact['product'] == product)]
    personal = {name: (_aggregate(own, metric=name, key_name='person') or [None])[0]
                for name in ('outcome', 'tat')}
    own_slice = [fact for fact in selected if fact['person_id'] == str(user.pk)]
    slice_result = (_aggregate(own_slice, metric=metric, key_name='person') or [None])[0]
    if view == 'people' and not include_people:
        view = 'branches'
    rows = _aggregate(selected, metric=metric, key_name='person' if view == 'people' else 'branch')
    if view == 'people':
        rows = _aggregate([fact for fact in selected if fact['case_id'] in named_case_ids],
                          metric=metric, key_name='person')
    # Building a sample is a personal state, never an unnumbered standing row.
    rows = [row for row in rows if row['ranked']]
    if final:
        for row in rows:
            row['movement'] = {'direction': 'none', 'places': 0}
    else:
        _rank_movement(user, context=[kind, key, metric, view, selected_role, branch, product, include_people],
                       group_ids=group_ids, rows=rows, observed_at=observed_at)
    try:
        page = max(1, int(page))
    except (TypeError, ValueError):
        page = 1
    total_pages = max(1, (len(rows) + 9) // 10)
    page = min(page, total_pages)
    # Internal stable identifiers are not part of the public standing contract.
    def public(row):
        if not row:
            return None
        return {key: value for key, value in row.items() if key != 'key'}
    return {
        'period': key, 'period_kind': kind, 'metric': metric, 'view': view,
        'role': selected_role, 'branch': branch, 'product': product,
        'roles': options['roles'], 'filter_options': options,
        'personal': {name: public(value) for name, value in personal.items()},
        'personal_missing_target': sum(not fact['tat_state'] for fact in own),
        'business_context': _business_context(user, access=access, start=start, end=end),
        'slice': public(slice_result), 'rows': [public(row) for row in rows[(page - 1) * 10:page * 10]],
        'page': page, 'pages': total_pages, 'total': len(rows),
        'minimum_ranked_sample': MINIMUM_RANKED_SAMPLE,
        'people_visible': bool(include_people), 'final': final, 'captured_at': captured_at,
        'calculated_at': observed_at.isoformat(),
    }
