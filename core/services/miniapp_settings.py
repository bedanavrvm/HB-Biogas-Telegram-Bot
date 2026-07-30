"""Controlled personal preferences and maker-checker TAT configuration.

Definitions remain in code so an admin can never create an unvalidated live
setting through a Mini App.  High-impact values are proposed first and applied
only by a different authorised reviewer.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from core.models import (
    BusinessCalendarHoliday,
    GroupSheetConfiguration,
    TatEscalationRule,
    UserMiniAppPreference,
    WorkflowConfigurationChangeRequest,
)
from core.services.access_policies import BUSINESS_ADMIN_ROLE
from core.services.compliance_audit import record_event


WORKFLOW_SCREENS = {
    'jawabu_portal': {'dashboard', 'jbl', 'credit', 'review', 'requisition', 'invoices', 'payments', 'documents'},
    'complaint_cases': {'queue'},
    'tat_tracker': {'home', 'new'},
    'spin_credit_analysis': {'requests', 'new'},
}
WORKFLOW_FILTER_KEYS = {
    'jawabu_portal': {'branch', 'status', 'queue'},
    'complaint_cases': {'branch', 'status'},
    'tat_tracker': {'branch', 'product_key'},
    'spin_credit_analysis': {'branch', 'status'},
}
SETTING_CAPABILITIES = {
    WorkflowConfigurationChangeRequest.SETTING_TARGETS: ('tat.settings.targets.propose', 'tat.settings.targets.approve'),
    WorkflowConfigurationChangeRequest.SETTING_HOLIDAYS: ('tat.settings.calendar.propose', 'tat.settings.calendar.approve'),
    WorkflowConfigurationChangeRequest.SETTING_ESCALATION: ('tat.settings.escalation.propose', 'tat.settings.escalation.approve'),
}

# This catalogue is intentionally code-owned.  A future recipient-level
# delivery worker must use it rather than re-deciding which notification can
# be quieted in a separate Mini App or task module.  Unknown alert types fail
# closed as mandatory until they are explicitly classified here.
MANDATORY_ALERT_TYPES = frozenset({
    'security.access',
    'workflow.assignment',
    'approval.decision',
    'sla.overdue_breach',
})
PREFERENCE_CONTROLLED_ALERT_TYPES = frozenset({
    'workflow.informational',
    'workflow.digest_eligible',
})


def alert_preference_applies(alert_type: str) -> bool:
    """Return whether a future delivery worker may apply a personal choice."""
    return str(alert_type or '').strip() in PREFERENCE_CONTROLLED_ALERT_TYPES


def preference_payload(user, workflow: str) -> dict[str, Any]:
    # Reading a Mini App shell must not silently create configuration data.
    # The preference row is created only when its owner explicitly saves it.
    preference = UserMiniAppPreference.objects.filter(user=user, workflow=workflow).first()
    if preference is None:
        return {
            'workflow': workflow,
            'default_screen': '',
            'default_filters': {},
            'compact_cards': False,
            'alert_mode': UserMiniAppPreference.ALERT_IMMEDIATE,
        }
    return {
        'workflow': workflow,
        'default_screen': preference.default_screen,
        'default_filters': preference.default_filters or {},
        'compact_cards': preference.compact_cards,
        'alert_mode': preference.alert_mode,
    }


def _normalise_boolean(value: Any, *, field: str) -> bool:
    """Accept JSON booleans (and explicit form fallbacks), never truthy text."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalised = value.strip().lower()
        if normalised in {'true', '1', 'yes', 'on'}:
            return True
        if normalised in {'false', '0', 'no', 'off', ''}:
            return False
    if value is None:
        return False
    raise ValueError(f'{field} must be true or false.')


@transaction.atomic
def update_preference(user, workflow: str, payload: dict[str, Any]) -> dict[str, Any]:
    if workflow not in WORKFLOW_SCREENS:
        raise ValueError('Unknown Mini App preference scope.')
    default_screen = str(payload.get('default_screen') or '').strip()
    if default_screen and default_screen not in WORKFLOW_SCREENS[workflow]:
        raise ValueError('Select a valid landing screen.')
    filters = payload.get('default_filters') or {}
    if not isinstance(filters, dict) or set(filters).difference(WORKFLOW_FILTER_KEYS[workflow]):
        raise ValueError('One or more saved filters are not valid for this Mini App.')
    clean_filters = {str(key): str(value).strip() for key, value in filters.items() if str(value).strip()}
    alert_mode = str(payload.get('alert_mode') or UserMiniAppPreference.ALERT_IMMEDIATE)
    if alert_mode not in dict(UserMiniAppPreference.ALERT_CHOICES):
        raise ValueError('Select a valid non-critical alert mode.')
    preference, _ = UserMiniAppPreference.objects.select_for_update().get_or_create(user=user, workflow=workflow)
    before = preference_payload(user, workflow)
    preference.default_screen = default_screen
    preference.default_filters = clean_filters
    preference.compact_cards = _normalise_boolean(payload.get('compact_cards'), field='Compact cards')
    preference.alert_mode = alert_mode
    preference.save(update_fields=['default_screen', 'default_filters', 'compact_cards', 'alert_mode', 'updated_at'])
    after = preference_payload(user, workflow)
    record_event(
        workflow={'jawabu_portal': 'portal', 'complaint_cases': 'complaint_cases', 'tat_tracker': 'tat_tracker', 'spin_credit_analysis': 'spin'}[workflow],
        action='miniapp.preference.updated', subject_type='user_miniapp_preference', subject_id=str(preference.pk),
        deduplication_key=f'preference:{preference.pk}:{preference.updated_at.isoformat()}', actor=user,
        before_values=before, after_values=after, sensitive=False,
    )
    return after


def _capable(actor: dict, capability: str) -> bool:
    return capability in set(actor.get('capabilities') or [])


def _request_user(actor: dict):
    user_id = actor.get('user_id')
    user = get_user_model().objects.filter(pk=user_id).first()
    if not user:
        raise ValueError('Your staff account could not be resolved.')
    return user


def _holiday_snapshot() -> dict[str, Any]:
    return {'holidays': [
        {'date': holiday.date.isoformat(), 'name': holiday.name, 'active': holiday.active}
        for holiday in BusinessCalendarHoliday.objects.order_by('date')
    ]}


def _escalation_snapshot(config) -> dict[str, Any]:
    return {'rules': [
        {'threshold_percent': rule.threshold_percent, 'routing_role': rule.routing_role, 'branch': rule.branch}
        for rule in config.tat_escalation_rules.filter(active=True).order_by('branch', 'threshold_percent')
    ]}


def _normalise_holidays(payload: Any) -> dict[str, Any]:
    """Return a complete holiday snapshot while leaving past dates immutable.

    The Mini App only shows future holidays.  Historical entries remain in the
    proposal snapshot so an edit cannot accidentally erase the calendar used
    to explain an earlier SLA result.
    """
    rows = payload.get('holidays') if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ValueError('Submit holidays as a list.')
    today = timezone.localdate()
    historic = {
        item['date']: item
        for item in _holiday_snapshot()['holidays']
        if date.fromisoformat(item['date']) <= today
    }
    clean, dates = list(historic.values()), set(historic)
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Each holiday must be valid.')
        try:
            holiday_date = date.fromisoformat(str(row.get('date') or ''))
        except ValueError as exc:
            raise ValueError('Each holiday needs a valid date.') from exc
        iso_date = holiday_date.isoformat()
        if holiday_date <= today:
            existing = historic.get(iso_date)
            requested = {
                'date': iso_date,
                'name': ' '.join(str(row.get('name') or '').split())[:160],
                'active': _normalise_boolean(row.get('active', True), field='Holiday active'),
            }
            if existing != requested:
                raise ValueError('Historical holidays cannot be changed in the Mini App.')
            continue
        if iso_date in dates:
            raise ValueError('A holiday date may appear only once.')
        name = ' '.join(str(row.get('name') or '').split())
        if not name:
            raise ValueError('Each holiday needs a name.')
        dates.add(iso_date)
        clean.append({
            'date': iso_date,
            'name': name[:160],
            'active': _normalise_boolean(row.get('active', True), field='Holiday active'),
        })
    return {'holidays': sorted(clean, key=lambda item: item['date'])}


def _normalise_escalation(payload: Any) -> dict[str, Any]:
    rows = payload.get('rules') if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        raise ValueError('Provide at least one escalation rule.')
    allowed_roles = {value for value, _ in TatEscalationRule.ROUTING_CHOICES}
    from core.services.branches import global_branch_choices

    allowed_branches = set(global_branch_choices())
    clean = []
    for row in rows:
        try:
            threshold = int(row.get('threshold_percent'))
        except (TypeError, ValueError) as exc:
            raise ValueError('Escalation thresholds must be whole percentages.') from exc
        role = str(row.get('routing_role') or '').strip().upper()
        branch = ' '.join(str(row.get('branch') or '').split())
        key = (branch, threshold)
        if threshold < 100 or threshold > 1000 or key in {(item['branch'], item['threshold_percent']) for item in clean}:
            raise ValueError('Use unique escalation thresholds from 100% to 1000%.')
        if role not in allowed_roles:
            raise ValueError('Select a valid escalation recipient role.')
        if branch and branch not in allowed_branches:
            raise ValueError('Select a configured branch for an escalation rule.')
        clean.append({'threshold_percent': threshold, 'routing_role': role, 'branch': branch})
    return {'rules': sorted(clean, key=lambda item: (item['branch'], item['threshold_percent']))}


def tat_settings_payload(config, actor: dict) -> dict[str, Any]:
    from core.services.tat_tracker import tat_target_settings
    pending = WorkflowConfigurationChangeRequest.objects.filter(
        workflow='tat_tracker', group_configuration=config, status=WorkflowConfigurationChangeRequest.STATUS_PENDING,
    ).order_by('-requested_at')
    cards = {}
    for setting_key, (propose, approve) in SETTING_CAPABILITIES.items():
        cards[setting_key] = {'can_propose': _capable(actor, propose), 'can_approve': _capable(actor, approve)}
    return {
        'settings_version': int((config.workflow or {}).get('settings_version') or 1),
        'targets': tat_target_settings(config.workflow),
        # Future rows are configurable; old rows remain immutable evidence for
        # historical business-hour calculations.
        'holidays': {'holidays': [
            item for item in _holiday_snapshot()['holidays']
            if date.fromisoformat(item['date']) > timezone.localdate()
        ]},
        'escalation': _escalation_snapshot(config),
        'cards': cards,
        'pending': [
            {'id': str(item.pk), 'setting_key': item.setting_key, 'reason': item.reason, 'requested_at': item.requested_at.isoformat(), 'requested_by': item.requested_by.get_username()}
            for item in pending[:20]
        ],
    }


@transaction.atomic
def create_tat_configuration_request(config, actor: dict, *, setting_key: str, proposed: Any, reason: str, request_id: str = ''):
    if setting_key not in SETTING_CAPABILITIES or not _capable(actor, SETTING_CAPABILITIES[setting_key][0]):
        raise PermissionError('Your role cannot propose this setting change.')
    reason = ' '.join(str(reason or '').split())
    if len(reason) < 8:
        raise ValueError('Provide a short reason for this configuration change.')
    if setting_key == WorkflowConfigurationChangeRequest.SETTING_TARGETS:
        from core.services.tat_tracker import normalize_tat_target_settings
        before = {'targets': (config.workflow or {}).get('tat_targets_minutes') or {}}
        after = {'targets': normalize_tat_target_settings(config.workflow, proposed)}
    elif setting_key == WorkflowConfigurationChangeRequest.SETTING_HOLIDAYS:
        before, after = _holiday_snapshot(), _normalise_holidays(proposed)
    else:
        before, after = _escalation_snapshot(config), _normalise_escalation(proposed)
    if before == after:
        raise ValueError('The proposed setting is unchanged.')
    requester = _request_user(actor)
    if request_id:
        existing = WorkflowConfigurationChangeRequest.objects.filter(requested_by=requester, request_id=request_id).first()
        if existing:
            return existing
    return WorkflowConfigurationChangeRequest.objects.create(
        setting_key=setting_key, group_configuration=config, before_snapshot=before, proposed_snapshot=after,
        reason=reason, requested_by=requester, request_id=request_id,
    )


@transaction.atomic
def review_tat_configuration_request(request_id: str, actor: dict, *, approve: bool, review_comment: str = ''):
    request = WorkflowConfigurationChangeRequest.objects.select_for_update().select_related('group_configuration', 'requested_by').get(pk=request_id)
    approve_capability = SETTING_CAPABILITIES[request.setting_key][1]
    actor_roles = {str(role or '').strip().upper() for role in (actor.get('roles') or [])}
    if BUSINESS_ADMIN_ROLE not in actor_roles or not _capable(actor, approve_capability):
        raise PermissionError('Only an authorised Business Admin can approve this setting change.')
    reviewer = _request_user(actor)
    if reviewer.pk == request.requested_by_id:
        raise PermissionError('A different authorised Business Admin must review this change.')
    if request.status != WorkflowConfigurationChangeRequest.STATUS_PENDING:
        raise ValueError('This setting proposal has already been reviewed.')
    request.reviewed_by = reviewer
    request.reviewed_at = timezone.now()
    request.review_comment = str(review_comment or '').strip()
    if not approve:
        request.status = WorkflowConfigurationChangeRequest.STATUS_REJECTED
        request.save(update_fields=['reviewed_by', 'reviewed_at', 'review_comment', 'status'])
        return request
    config = GroupSheetConfiguration.objects.select_for_update().get(pk=request.group_configuration_id)
    if request.setting_key == WorkflowConfigurationChangeRequest.SETTING_TARGETS:
        workflow = dict(config.workflow or {})
        workflow['tat_targets_minutes'] = request.proposed_snapshot['targets']
        workflow['settings_version'] = int(workflow.get('settings_version') or 1) + 1
        config.workflow = workflow
        config.save(update_fields=['workflow', 'updated_at'])
        # GroupRegistry caches workflow configuration for message handling.
        # Reload it after the committed change so only future stage entries use
        # the newly approved target values.
        from core.services.group_config import GroupRegistry
        GroupRegistry.get_instance().reload()
    elif request.setting_key == WorkflowConfigurationChangeRequest.SETTING_HOLIDAYS:
        requested_dates = {row['date'] for row in request.proposed_snapshot['holidays']}
        for holiday in BusinessCalendarHoliday.objects.filter(date__gt=timezone.localdate()).exclude(date__in=requested_dates):
            holiday.active = False
            holiday.save(update_fields=['active', 'updated_at'])
        for row in request.proposed_snapshot['holidays']:
            BusinessCalendarHoliday.objects.update_or_create(date=date.fromisoformat(row['date']), defaults={'name': row['name'], 'active': row['active']})
    else:
        config.tat_escalation_rules.filter(active=True).update(active=False, retired_at=timezone.now())
        TatEscalationRule.objects.bulk_create([
            TatEscalationRule(group_configuration=config, threshold_percent=row['threshold_percent'], routing_role=row['routing_role'], branch=row['branch'], approved_by=reviewer)
            for row in request.proposed_snapshot['rules']
        ])
    request.status = WorkflowConfigurationChangeRequest.STATUS_APPROVED
    request.applied_at = timezone.now()
    request.save(update_fields=['reviewed_by', 'reviewed_at', 'review_comment', 'status', 'applied_at'])
    record_event(
        workflow='tat_tracker', action='tat.settings.approved', subject_type='workflow_configuration_change_request',
        subject_id=str(request.pk), deduplication_key=f'tat-setting-approved:{request.pk}', actor=request.requested_by,
        authority_user=reviewer, before_values=request.before_snapshot, after_values=request.proposed_snapshot,
        metadata={'setting_key': request.setting_key, 'group_id': str(config.group_id)}, sensitive=False,
    )
    return request
