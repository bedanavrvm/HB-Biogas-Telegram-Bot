"""Runtime-equivalent launcher readiness for staff onboarding and Admin diagnostics.

This module deliberately calls the same exact-tuple authorization service used
by protected Mini App endpoints.  It never repairs or broadens access.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class LauncherReadiness:
    launcher_key: str
    workflow: str
    capability: str
    group_configuration_id: int | None
    group_id: str
    group_label: str
    ready: bool
    reason_code: str
    message: str
    matching_grant_ids: tuple[str, ...] = ()

    def payload(self) -> dict:
        return asdict(self)


REASON_MESSAGES = {
    'access_ready': 'Runtime access is ready.',
    'telegram_identity_unbound': 'Telegram identity has not been activated yet.',
    'workflow_grant_missing': 'No active access grant exists for this workflow.',
    'group_scope_mismatch': 'The active access grant does not cover this Telegram group.',
    'capability_policy_denied': 'The assigned role does not receive the launcher capability.',
}


def _workflows_with_active_grants(user) -> set[str]:
    from core.models import AccessGrant, EmergencyAccessGrant
    from django.utils import timezone

    workflows = set(AccessGrant.objects.filter(user=user, active=True).values_list('workflow', flat=True))
    workflows.update(EmergencyAccessGrant.objects.filter(
        user=user, revoked_at__isnull=True, expires_at__gt=timezone.now(),
    ).values_list('workflow', flat=True))
    return workflows


def launcher_readiness_for_group(user, group_configuration, *, require_identity: bool = True) -> list[LauncherReadiness]:
    """Return one exact runtime decision for each launcher assigned to ``user``.

    A group may advertise several launchers.  Only launchers whose workflow the
    user was actually granted are part of that user's onboarding contract.
    """
    from core.services.staff_telegram_onboarding import LAUNCHER_CAPABILITIES, LAUNCHER_WORKFLOWS
    from core.services.telegram_identity import user_access
    from core.services.telegram_launchers import configured_launcher_keys
    from core.services.workflow_access import workflow_access_decision

    profile = getattr(user, 'staff_profile', None)
    active_workflows = _workflows_with_active_grants(user)
    results: list[LauncherReadiness] = []
    for launcher_key in configured_launcher_keys(group_configuration):
        workflow = LAUNCHER_WORKFLOWS.get(launcher_key, '')
        capability = LAUNCHER_CAPABILITIES.get(launcher_key, '')
        if not workflow or not capability or workflow not in active_workflows:
            continue
        base = {
            'launcher_key': launcher_key,
            'workflow': workflow,
            'capability': capability,
            'group_configuration_id': getattr(group_configuration, 'pk', None),
            'group_id': str(getattr(group_configuration, 'group_id', '') or ''),
            'group_label': str(
                getattr(group_configuration, 'display_name', '')
                or getattr(group_configuration, 'group_id', '')
            ),
        }
        if require_identity and not str(getattr(profile, 'telegram_id', '') or '').strip():
            results.append(LauncherReadiness(
                **base, ready=False, reason_code='telegram_identity_unbound',
                message=REASON_MESSAGES['telegram_identity_unbound'],
            ))
            continue
        unscoped_access = user_access(user, workflow)
        if not unscoped_access.get('authorized'):
            results.append(LauncherReadiness(
                **base, ready=False, reason_code='workflow_grant_missing',
                message=REASON_MESSAGES['workflow_grant_missing'],
            ))
            continue
        scoped_access = user_access(user, workflow, group_configuration=group_configuration)
        if not scoped_access.get('authorized'):
            results.append(LauncherReadiness(
                **base, ready=False, reason_code='group_scope_mismatch',
                message=REASON_MESSAGES['group_scope_mismatch'],
            ))
            continue
        decision = workflow_access_decision(
            user, workflow, capability, access=scoped_access,
            group_configuration=group_configuration,
        )
        reason = 'access_ready' if decision.allowed else 'capability_policy_denied'
        results.append(LauncherReadiness(
            **base,
            ready=reason == 'access_ready',
            reason_code=reason,
            message=REASON_MESSAGES[reason],
            matching_grant_ids=decision.grant_ids,
        ))
    return results


def onboarding_readiness(onboarding, *, require_identity: bool = True) -> dict:
    rows: list[LauncherReadiness] = []
    for invitation in onboarding.group_invitations.select_related('group_configuration'):
        rows.extend(launcher_readiness_for_group(
            onboarding.user, invitation.group_configuration,
            require_identity=require_identity,
        ))
    # Selecting a Telegram group without any launcher matching the user's
    # grants is not a usable onboarding outcome.
    if onboarding.group_invitations.exists() and not rows:
        return {
            'ready': False,
            'reason_code': 'workflow_grant_missing',
            'message': REASON_MESSAGES['workflow_grant_missing'],
            'rows': [],
        }
    failed = next((row for row in rows if not row.ready), None)
    return {
        'ready': failed is None,
        'reason_code': failed.reason_code if failed else 'access_ready',
        'message': failed.message if failed else REASON_MESSAGES['access_ready'],
        'rows': [row.payload() for row in rows],
    }
