"""Canonical TAT responsibility configuration and audit helpers.

AccessGrant answers whether a person may act.  This module answers who should
receive a TAT task first; it must never grant access as a side effect.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone


def stage_catalog(workflow: dict | None = None):
    """Return canonical product/stage rows without inventing another policy."""
    from core.services.tat_tracker import configured_products

    rows = []
    for product in configured_products(workflow or {}):
        for position, stage in enumerate(product.stages, start=1):
            rows.append({
                'product_key': product.key,
                'product_label': product.label,
                'position': position,
                'stage_key': stage.key,
                'stage_label': stage.label,
                'role': str(stage.role or '').strip().upper(),
                'capability_key': f'tat.stage.{stage.key}.update',
            })
    return rows


def canonical_stage_role(*, stage_key: str, product_key: str = '', workflow: dict | None = None) -> str:
    """Resolve one stage owner, requiring a product when definitions disagree."""
    stage_key = str(stage_key or '').strip()
    product_key = str(product_key or '').strip().lower()
    matches = [row for row in stage_catalog(workflow) if row['stage_key'] == stage_key]
    if product_key:
        matches = [row for row in matches if row['product_key'].casefold() == product_key.casefold()]
    if not matches:
        raise ValidationError({'stage_key': 'Choose a stage configured for the selected TAT product scope.'})
    roles = {row['role'] for row in matches if row['role']}
    if len(roles) != 1:
        raise ValidationError({
            'stage_key': 'This stage has different responsible roles across products. Choose one product first.',
        })
    return roles.pop()


def assignment_snapshot(assignment) -> dict:
    backups = list(assignment.backups.order_by('rank', 'created_at').values(
        'user_id', 'rank', 'threshold_percent', 'active',
    )) if assignment.pk else []
    return {
        'id': str(assignment.pk),
        'group_configuration_id': assignment.group_configuration_id,
        'branch': assignment.branch,
        'role': assignment.role,
        'product_key': assignment.product_key,
        'stage_key': assignment.stage_key,
        'primary_user_id': assignment.primary_user_id,
        'active': assignment.active,
        'effective_from': assignment.effective_from.isoformat() if assignment.effective_from else None,
        'effective_until': assignment.effective_until.isoformat() if assignment.effective_until else None,
        'backups': backups,
    }


def eligible_responsibility_users(*, group_configuration, branch: str, role: str, product_key: str = ''):
    """Return active users whose explicit TAT grant covers this routing scope.

    This query is shared by the Admin form and its dependent-select endpoint so
    changing a scope in the browser cannot make its displayed choices diverge
    from server-side validation.
    """
    from core.models import AccessGrant

    users = get_user_model().objects.none()
    branch = str(branch or '').strip()
    role = str(role or '').strip().upper()
    product_key = str(product_key or '').strip().lower()
    if not group_configuration or not branch or not role:
        return users

    grants = AccessGrant.objects.filter(
        workflow='tat_tracker', role__iexact=role, active=True,
        user__is_active=True,
    ).filter(
        Q(group_configuration__isnull=True)
        | Q(group_configuration=group_configuration)
    ).filter(
        Q(branch='') | Q(branch__iexact=branch)
    )
    if product_key:
        grants = grants.filter(Q(product='') | Q(product__iexact=product_key))
    else:
        # An all-products roster must not nominate someone whose permission is
        # limited to only one product.
        grants = grants.filter(product='')
    return get_user_model().objects.filter(
        access_grants__in=grants, is_active=True,
    ).distinct().order_by('first_name', 'last_name', 'username')


def responsibility_access_grants(*, group_configuration, branch: str, role: str, product_key: str):
    """Return the grants which actually cover one concrete routing scope."""
    from core.models import AccessGrant

    return AccessGrant.objects.filter(
        workflow='tat_tracker', role__iexact=role, active=True, user__is_active=True,
    ).filter(
        Q(group_configuration__isnull=True) | Q(group_configuration=group_configuration),
    ).filter(
        Q(branch='') | Q(branch__iexact=branch),
    ).filter(
        Q(product='') | Q(product__iexact=product_key),
    ).select_related('user', 'group_configuration')


def user_has_responsibility_access(
    *, user_id=None, group_configuration, branch: str, role: str, product_key: str,
) -> bool:
    grants = responsibility_access_grants(
        group_configuration=group_configuration, branch=branch, role=role,
        product_key=product_key,
    )
    if user_id is not None:
        grants = grants.filter(user_id=user_id)
    return grants.exists()


def _assignment_scope_score(assignment, *, branch: str, role: str, product_key: str, stage_key: str):
    if assignment.branch.casefold() != branch.casefold() or assignment.role.casefold() != role.casefold():
        return None
    if assignment.product_key and assignment.product_key.casefold() != product_key.casefold():
        return None
    if assignment.stage_key and assignment.stage_key != stage_key:
        return None
    return int(bool(assignment.product_key)) + (2 * int(bool(assignment.stage_key)))


def effective_candidates_from_rows(*, rows, branch: str, role: str, product_key: str, stage_key: str):
    ranked = []
    for assignment in rows:
        score = _assignment_scope_score(
            assignment, branch=branch, role=role,
            product_key=product_key, stage_key=stage_key,
        )
        if score is not None:
            ranked.append((score, assignment))
    if not ranked:
        return []
    highest = max(item[0] for item in ranked)
    return [assignment for score, assignment in ranked if score == highest]


def effective_assignment_candidates(
    *, group_configuration, branch: str, role: str, product_key: str,
    stage_key: str, at=None,
):
    """Return equally specific effective assignments using runtime precedence."""
    from core.models import TatResponsibilityAssignment

    at = at or timezone.now()
    rows = TatResponsibilityAssignment.objects.filter(
        group_configuration=group_configuration, branch__iexact=branch,
        role__iexact=role, active=True, effective_from__lte=at,
    ).filter(
        Q(effective_until__isnull=True) | Q(effective_until__gt=at),
    ).select_related(
        'primary_user', 'primary_user__staff_profile', 'group_configuration',
    ).prefetch_related('backups__user', 'backups__user__staff_profile')
    return effective_candidates_from_rows(
        rows=rows, branch=branch, role=role,
        product_key=product_key, stage_key=stage_key,
    )


def _person_label(user) -> str:
    return user.get_full_name().strip() or user.get_username()


def _connection_statuses(user_ids) -> dict:
    from core.models import TatPrivateAlertConnection

    return {
        row.user_id: row.status
        for row in TatPrivateAlertConnection.objects.filter(user_id__in=user_ids)
    }


def _health_reason(code: str, severity: str, label: str, detail: str) -> dict:
    return {'code': code, 'severity': severity, 'label': label, 'detail': detail}


_HEALTH_ORDER = {'critical': 0, 'warning': 1, 'ready': 2, 'neutral': 3}


def effective_routing_overview(*, group_configuration, branches, product_keys) -> dict:
    """Project what routing will do, rather than exposing configuration rows.

    The projection is read-only. Access grants remain authorization and the
    runtime resolver remains responsible for creating task recipient snapshots.
    """
    from core.models import AccessGrant, TatPrivateAlertConnection, TatResponsibilityAssignment

    workflow = dict(group_configuration.workflow or {})
    mode = str(workflow.get('tat_notification_mode') or 'group').strip().lower()
    if mode not in {'group', 'shadow', 'hybrid'}:
        mode = 'group'
    catalogue = [
        row for row in stage_catalog(workflow)
        if row['product_key'] in set(product_keys)
    ]
    at = timezone.now()
    assignments = list(TatResponsibilityAssignment.objects.filter(
        group_configuration=group_configuration,
    ).select_related(
        'primary_user', 'primary_user__staff_profile', 'group_configuration',
    ).prefetch_related('backups__user', 'backups__user__staff_profile'))
    expired = [
        item for item in assignments
        if item.active and item.effective_until and item.effective_until <= at
    ]
    scheduled = [
        item for item in assignments if item.active and item.effective_from > at
    ]
    effective_assignments = [
        item for item in assignments
        if item.active and item.effective_from <= at
        and (item.effective_until is None or item.effective_until > at)
    ]
    grants = list(AccessGrant.objects.filter(
        workflow='tat_tracker', active=True, user__is_active=True,
    ).filter(
        Q(group_configuration__isnull=True) | Q(group_configuration=group_configuration),
    ).select_related('user', 'group_configuration'))
    role_data = {}
    all_user_ids = set()
    concrete = []
    for branch in branches:
        for stage in catalogue:
            role = stage['role']
            scope_grants = [
                grant for grant in grants
                if grant.role.casefold() == role.casefold()
                and (not grant.branch or grant.branch.casefold() == branch.casefold())
                and (not grant.product or grant.product.casefold() == stage['product_key'].casefold())
            ]
            eligible = {grant.user_id: grant.user for grant in scope_grants}
            all_user_ids.update(eligible)
            winners = effective_candidates_from_rows(
                rows=effective_assignments, branch=branch, role=role,
                product_key=stage['product_key'], stage_key=stage['stage_key'],
            )
            concrete.append({
                'branch': branch, 'stage': stage, 'role': role,
                'eligible': eligible, 'grants': scope_grants, 'winners': winners,
            })
            for winner in winners:
                all_user_ids.add(winner.primary_user_id)
                all_user_ids.update(
                    backup.user_id for backup in winner.backups.all() if backup.active
                )
    connections = _connection_statuses(all_user_ids)

    for scope in concrete:
        stage = scope['stage']
        role = scope['role']
        row = role_data.setdefault(role, {
            'role': role,
            'role_label': role.replace('_', ' ').title(),
            'stages': {}, 'staff': {}, 'outcomes': [], 'reasons': {},
            'primary_ids': set(), 'primary_labels': set(), 'backup_labels': set(),
            'assignments': {}, 'exceptions': [], 'route_signatures': set(),
        })
        stage_identity = (stage['product_key'], stage['stage_key'])
        row['stages'][stage_identity] = {
            'label': stage['stage_label'], 'product_label': stage['product_label'],
            'stage_key': stage['stage_key'], 'capability_key': stage['capability_key'],
        }
        for grant in scope['grants']:
            person = row['staff'].setdefault(grant.user_id, {
                'id': grant.user_id, 'label': _person_label(grant.user), 'scopes': set(),
                'connection_status': connections.get(
                    grant.user_id, TatPrivateAlertConnection.STATUS_UNKNOWN,
                ),
            })
            person['scopes'].add(
                f"{grant.role} · {grant.branch or 'All branches'} · {grant.product or 'All products'}"
            )

        winners = scope['winners']
        reasons = []
        assignment = winners[0] if len(winners) == 1 else None
        if len(winners) > 1:
            reasons.append(_health_reason(
                'ambiguous-routing', 'critical', 'Ambiguous routing',
                'More than one equally specific roster wins for this stage.',
            ))
        elif not scope['eligible']:
            reasons.append(_health_reason(
                'no-eligible-staff', 'critical', 'No eligible staff',
                'No active TAT access grant covers this role and scope.',
            ))
        elif not assignment:
            scheduled_matches = [
                item for item in scheduled
                if item.branch.casefold() == scope['branch'].casefold()
                and item.role.casefold() == role.casefold()
                and (not item.product_key or item.product_key == stage['product_key'])
                and (not item.stage_key or item.stage_key == stage['stage_key'])
            ]
            if scheduled_matches:
                next_assignment = min(scheduled_matches, key=lambda item: item.effective_from)
                row['assignments'][next_assignment.pk] = next_assignment
                reasons.append(_health_reason(
                    'scheduled-roster', 'warning', 'Roster starts later',
                    f"The next roster starts {timezone.localtime(next_assignment.effective_from):%d %b %Y %H:%M}.",
                ))
            else:
                severity = 'critical' if mode in {'shadow', 'hybrid'} else 'neutral'
                reasons.append(_health_reason(
                    'role-fallback', severity,
                    'No dedicated roster' if severity == 'critical' else 'Group delivery mode',
                    'Runtime will use the de-duplicated eligible-role fallback.',
                ))
        else:
            row['assignments'][assignment.pk] = assignment
            row['primary_ids'].add(assignment.primary_user_id)
            row['primary_labels'].add(_person_label(assignment.primary_user))
            if assignment.stage_key:
                row['exceptions'].append({
                    'assignment': assignment, 'stage': stage,
                    'branch': scope['branch'],
                })
            if assignment.primary_user_id not in scope['eligible']:
                reasons.append(_health_reason(
                    'primary-missing-access', 'critical', 'Primary missing access',
                    f'{_person_label(assignment.primary_user)} cannot act in this scope.',
                ))
            primary_connection = connections.get(
                assignment.primary_user_id, TatPrivateAlertConnection.STATUS_UNKNOWN,
            )
            if mode == 'hybrid' and primary_connection != TatPrivateAlertConnection.STATUS_CONNECTED:
                connection_label = dict(TatPrivateAlertConnection.STATUS_CHOICES).get(
                    primary_connection, 'Unknown',
                )
                reasons.append(_health_reason(
                    f'primary-dm-{primary_connection}', 'critical', f'DM {connection_label.lower()}',
                    f'{_person_label(assignment.primary_user)} is not ready for private alerts.',
                ))
            for backup in assignment.backups.all():
                if not backup.active:
                    continue
                backup_label = f'{_person_label(backup.user)} at {backup.threshold_percent}%'
                row['backup_labels'].add(backup_label)
                if backup.user_id not in scope['eligible']:
                    reasons.append(_health_reason(
                        'backup-missing-access', 'warning', 'Backup missing access',
                        f'{_person_label(backup.user)} cannot act in this scope.',
                    ))
                backup_connection = connections.get(
                    backup.user_id, TatPrivateAlertConnection.STATUS_UNKNOWN,
                )
                if mode == 'hybrid' and backup_connection != TatPrivateAlertConnection.STATUS_CONNECTED:
                    reasons.append(_health_reason(
                        f'backup-dm-{backup_connection}', 'warning', 'Backup DM unavailable',
                        f'{_person_label(backup.user)} may not receive the escalation alert.',
                    ))
        for expired_assignment in expired:
            if (
                expired_assignment.branch.casefold() == scope['branch'].casefold()
                and expired_assignment.role.casefold() == role.casefold()
                and (not expired_assignment.product_key or expired_assignment.product_key == stage['product_key'])
                and (not expired_assignment.stage_key or expired_assignment.stage_key == stage['stage_key'])
            ):
                row['assignments'][expired_assignment.pk] = expired_assignment
                reasons.append(_health_reason(
                    'expired-enabled', 'critical', 'Expired but enabled',
                    'This expired active record blocks a clean replacement.',
                ))
        outcome = {
            'branch': scope['branch'], 'stage': stage, 'assignment': assignment,
            'eligible_count': len(scope['eligible']), 'reasons': reasons,
        }
        if assignment:
            row['route_signatures'].add(('user', assignment.primary_user_id))
        elif len(winners) > 1:
            row['route_signatures'].add(('ambiguous',))
        elif scope['eligible']:
            row['route_signatures'].add(('fallback',))
        else:
            row['route_signatures'].add(('none',))
        row['outcomes'].append(outcome)
        for reason in reasons:
            row['reasons'][reason['code']] = reason

    role_rows = []
    for row in role_data.values():
        reasons = sorted(
            row['reasons'].values(),
            key=lambda item: (_HEALTH_ORDER[item['severity']], item['label']),
        )
        if reasons:
            health = reasons[0]
        elif mode == 'shadow':
            health = _health_reason(
                'ready-shadow', 'ready', 'Ready for shadow',
                'Routing is valid; private messages are intentionally not sent.',
            )
        elif mode == 'group':
            health = _health_reason(
                'group-mode', 'neutral', 'Group delivery mode',
                'Private responsibility routing is not active in this mode.',
            )
        else:
            health = _health_reason('ready', 'ready', 'Ready', 'Routing and private delivery are ready.')
        staff = list(row['staff'].values())
        for person in staff:
            person['scopes'] = sorted(person['scopes'])
        staff.sort(key=lambda item: item['label'].casefold())
        primary_labels = sorted(row['primary_labels'])
        if len(row['route_signatures']) > 1:
            primary_label = 'Varies by stage'
        elif row['route_signatures'] == {('fallback',)}:
            primary_label = 'Eligible-role fallback'
        elif row['route_signatures'] in ({('none',)}, {('ambiguous',)}):
            primary_label = 'No effective primary'
        else:
            primary_label = primary_labels[0] if primary_labels else 'No effective primary'
        row.update({
            'stages': sorted(row['stages'].values(), key=lambda item: (
                item['product_label'], item['label'],
            )),
            'staff': staff,
            'staff_count': len(staff),
            'primary_label': primary_label,
            'backup_labels': sorted(row['backup_labels']),
            'reasons': reasons,
            'health': health,
            'sort_key': (_HEALTH_ORDER[health['severity']], row['role_label'].casefold()),
        })
        role_rows.append(row)
    role_rows.sort(key=lambda item: item['sort_key'])
    return {
        'mode': mode,
        'mode_label': {'group': 'Group', 'shadow': 'Shadow', 'hybrid': 'Hybrid'}[mode],
        'roles': role_rows,
    }


def parse_revision(value) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except (TypeError, ValueError) as exc:
        raise ValidationError('The roster revision is invalid. Reload and try again.') from exc
    return parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed)


@transaction.atomic
def replace_expired_assignment(
    *, assignment, primary_user, actor, reason: str, request_id: str,
    expected_updated_at,
):
    """Atomically replace one expired roster and redistribute pending work."""
    from core.models import (
        TatResponsibilityAssignment, TatResponsibilityChangePlan,
        TatResponsibilityEvent,
    )

    if not getattr(actor, 'is_active', False) or not getattr(actor, 'is_superuser', False):
        raise ValidationError('Only an active Django Superuser may replace a TAT roster.')
    reason = str(reason or '').strip()
    request_id = str(request_id or '').strip()
    if len(reason) < 10:
        raise ValidationError('Explain why this replacement is required (at least 10 characters).')
    if not request_id:
        raise ValidationError('A request ID is required.')
    existing = TatResponsibilityChangePlan.objects.filter(request_id=request_id).first()
    if existing:
        successor_id = str((existing.proposed_snapshot or {}).get('successor_assignment_id') or '')
        successor = TatResponsibilityAssignment.objects.filter(pk=successor_id).first()
        if existing.assignment_id != assignment.pk or not successor:
            raise ValidationError('This request ID was already used for another roster change.')
        return successor
    predecessor = TatResponsibilityAssignment.objects.select_for_update().prefetch_related(
        'backups__user',
    ).get(pk=assignment.pk)
    expected = parse_revision(expected_updated_at)
    if predecessor.updated_at != expected:
        raise ValidationError('This roster changed after review. Reload and review it again.')
    now = timezone.now()
    if not predecessor.active or not predecessor.effective_until or predecessor.effective_until > now:
        raise ValidationError('Only an active roster whose effective period ended can be replaced here.')
    if str((predecessor.group_configuration.workflow or {}).get('type') or '') != 'tat_tracker':
        raise ValidationError('This responsibility is not attached to a TAT Tracker group.')
    if not user_has_responsibility_access(
        user_id=primary_user.pk,
        group_configuration=predecessor.group_configuration,
        branch=predecessor.branch,
        role=predecessor.role,
        product_key=predecessor.product_key,
    ):
        raise ValidationError('The new primary recipient lacks active access for this exact TAT scope.')
    before = assignment_snapshot(predecessor)
    plan = TatResponsibilityChangePlan.objects.create(
        assignment=predecessor,
        proposed_snapshot={'primary_user_id': primary_user.pk},
        expected_updated_at=predecessor.updated_at,
        effective_at=now,
        status=TatResponsibilityChangePlan.STATUS_DRAFT,
        reason=reason,
        request_id=request_id,
        created_by=actor,
    )
    # Deactivation must remain possible when the reason for replacement is
    # precisely that the historical primary has since lost access.
    TatResponsibilityAssignment.objects.filter(pk=predecessor.pk).update(
        active=False, updated_at=now,
    )
    predecessor.active = False
    predecessor.updated_at = now
    successor = TatResponsibilityAssignment.objects.create(
        group_configuration=predecessor.group_configuration,
        branch=predecessor.branch,
        role=predecessor.role,
        product_key=predecessor.product_key,
        stage_key=predecessor.stage_key,
        primary_user=primary_user,
        active=True,
        effective_from=now,
        effective_until=None,
        created_by=actor,
    )
    for backup in predecessor.backups.all():
        if (
            backup.active
            and backup.user_id != primary_user.pk
            and user_has_responsibility_access(
                user_id=backup.user_id,
                group_configuration=predecessor.group_configuration,
                branch=predecessor.branch,
                role=predecessor.role,
                product_key=predecessor.product_key,
            )
        ):
            successor.backups.create(
                user=backup.user, rank=backup.rank,
                threshold_percent=backup.threshold_percent, active=True,
            )
    TatResponsibilityEvent.objects.create(
        assignment=predecessor, assignment_id_snapshot=predecessor.pk,
        action=TatResponsibilityEvent.ACTION_UPDATED, actor=actor, reason=reason,
        before_snapshot=before, after_snapshot=assignment_snapshot(predecessor),
    )
    TatResponsibilityEvent.objects.create(
        assignment=successor, assignment_id_snapshot=successor.pk,
        action=TatResponsibilityEvent.ACTION_CREATED, actor=actor, reason=reason,
        before_snapshot={}, after_snapshot=assignment_snapshot(successor),
    )
    plan.status = TatResponsibilityChangePlan.STATUS_APPLIED
    plan.applied_at = now
    plan.proposed_snapshot = {
        'primary_user_id': primary_user.pk,
        'successor_assignment_id': str(successor.pk),
    }
    plan.save(update_fields=['status', 'applied_at', 'proposed_snapshot'])
    from core.services.tat_notifications import reconcile_pending_tasks_for_group

    routing_result = reconcile_pending_tasks_for_group(
        group_configuration=successor.group_configuration,
        actor=actor,
        reason=f'Expired roster replacement: {reason}',
        request_id=f'replace-expired-roster:{request_id}',
    )
    successor._rerouted_task_count = routing_result['changed']
    return successor


def configuration_issues(assignments) -> dict:
    """Classify routing problems for the Admin workspace without changing data."""
    issues = defaultdict(list)
    for assignment in assignments:
        if assignment.stage_key:
            try:
                expected = canonical_stage_role(
                    stage_key=assignment.stage_key,
                    product_key=assignment.product_key,
                    workflow=assignment.group_configuration.workflow,
                )
            except ValidationError as exc:
                issues['invalid_stage'].append((assignment, '; '.join(exc.messages)))
            else:
                if assignment.role.upper() != expected:
                    issues['role_conflict'].append((assignment, f'Expected {expected}.'))
        now = timezone.now()
        if assignment.active and assignment.effective_until and assignment.effective_until <= now:
            issues['expired_assignment'].append((
                assignment,
                'This active roster has expired and must be deactivated before a replacement can be activated.',
            ))
        if assignment.active and assignment.effective_from <= now and (
            assignment.effective_until is None or assignment.effective_until > now
        ):
            from core.services.tat_notifications import user_can_receive_scope
            if not user_can_receive_scope(
                assignment.primary_user,
                group=assignment.group_configuration,
                branch=assignment.branch,
                product_key=assignment.product_key,
                role=assignment.role,
            ):
                issues['invalid_primary'].append((assignment, 'Primary user lacks matching active TAT access.'))
    return dict(issues)
