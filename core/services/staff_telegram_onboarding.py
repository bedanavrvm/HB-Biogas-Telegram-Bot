"""Durable, retry-safe Telegram handoff after staff lifecycle onboarding."""
from __future__ import annotations

import hashlib
import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.models import (
    GroupSheetConfiguration,
    StaffTelegramGroupInvitation,
    StaffTelegramOnboarding,
    UserProfile,
)
from core.services.external_resilience import (
    ExternalOperationError,
    execute_operation,
    redacted_error_code,
    reserve_operation,
)
from core.services.telegram_launchers import (
    build_launcher_url,
    configured_launcher_keys,
    publish_group_launcher,
    telegram_api_call,
)


logger = logging.getLogger(__name__)
INVITE_TTL_HOURS = 24
LAUNCHER_WORKFLOWS = {
    'tat_tracker': 'tat_tracker',
    'spin_credit': 'spin_credit_analysis',
    'complaint_cases': 'complaint_cases',
    'pipeline_portal': 'jawabu_portal',
    'order_approval': 'jawabu_portal',
    'loan_origination': 'jawabu_portal',
}
LAUNCHER_CAPABILITIES = {
    'tat_tracker': 'tat.home.view',
    'spin_credit': 'spin.request.view',
    'complaint_cases': 'complaint.queue.view',
    'pipeline_portal': 'portal.dashboard.view',
    'order_approval': 'portal.requisition.view',
    'loan_origination': 'portal.origination.view',
}


def staff_activation_launcher_url(*, fallback_url: str = '') -> str:
    bot_username = str(getattr(settings, 'TELEGRAM_BOT_USERNAME', '') or '').strip().lstrip('@')
    short_name = str(
        getattr(settings, 'STAFF_ACTIVATION_MINI_APP_SHORT_NAME', '') or '',
    ).strip().strip('/')
    if bot_username and short_name:
        return f'https://t.me/{bot_username}/{short_name}'
    return str(fallback_url or '')


def create_staff_telegram_onboarding(*, plan) -> StaffTelegramOnboarding | None:
    """Project a successfully applied Telegram onboarding plan into delivery rows."""
    identity = (plan.proposed_snapshot or {}).get('identity') or {}
    if plan.action != plan.ACTION_ONBOARD or identity.get('login_method') != 'telegram':
        return None
    onboarding, _ = StaffTelegramOnboarding.objects.get_or_create(
        plan=plan,
        defaults={'user': plan.target_user},
    )
    selected_ids = (plan.proposed_snapshot or {}).get('telegram_group_ids') or []
    groups = GroupSheetConfiguration.objects.filter(pk__in=selected_ids, enabled=True)
    existing_ids = set(onboarding.group_invitations.values_list('group_configuration_id', flat=True))
    StaffTelegramGroupInvitation.objects.bulk_create([
        StaffTelegramGroupInvitation(onboarding=onboarding, group_configuration=group)
        for group in groups if group.pk not in existing_ids
    ], ignore_conflicts=True)
    return onboarding


def _authorized_launcher_buttons(onboarding: StaffTelegramOnboarding) -> list[dict]:
    from core.services.telegram_identity import user_access
    from core.services.workflow_capabilities import has_capability

    buttons = []
    seen = set()
    for invitation in onboarding.group_invitations.select_related('group_configuration'):
        config = invitation.group_configuration
        for key in configured_launcher_keys(config):
            workflow = LAUNCHER_WORKFLOWS.get(key)
            access = user_access(onboarding.user, workflow, group_configuration=config) if workflow else {}
            if (
                key in seen
                or not workflow
                or not access.get('authorized')
                or not has_capability(
                    onboarding.user, workflow, LAUNCHER_CAPABILITIES[key], access=access,
                )
            ):
                continue
            url = build_launcher_url(key, config.group_id)
            if not url:
                continue
            seen.add(key)
            label = {
                'tat_tracker': 'TAT Tracker', 'spin_credit': 'SPIN / CRB',
                'order_approval': 'Order Approval', 'pipeline_portal': 'Pipeline Portal',
                'complaint_cases': 'Complaint Cases', 'loan_origination': 'Loan Origination',
            }[key]
            buttons.append({'text': label, 'url': url})
    return buttons


def _create_group_invite(invitation: StaffTelegramGroupInvitation) -> str:
    now = timezone.now()
    if (
        invitation.pending_invite_url
        and invitation.invite_expires_at
        and invitation.invite_expires_at > now
    ):
        return invitation.pending_invite_url
    onboarding = invitation.onboarding
    config = invitation.group_configuration
    expires_at = now + timedelta(hours=INVITE_TTL_HOURS)
    operation, _ = reserve_operation(
        integration='telegram', operation_type='staff_group_invite',
        deduplication_key=(
            f'telegram:staff-onboarding:{onboarding.pk}:group:{config.pk}:'
            f'invite:{onboarding.revision}'
        ),
        source_model='StaffTelegramOnboarding', source_id=str(onboarding.pk),
        operation_payload=(str(onboarding.pk), config.group_id, onboarding.revision),
        metadata={'group_configuration_id': config.pk},
    )

    def create_once():
        payload = telegram_api_call('createChatInviteLink', {
            'chat_id': config.group_id,
            'name': f'JBL staff onboarding {str(onboarding.pk)[:8]}',
            'expire_date': int(expires_at.timestamp()),
            'member_limit': 1,
            'creates_join_request': False,
        })
        invite_link = str((payload.get('result') or {}).get('invite_link') or '')
        if not invite_link:
            raise ExternalOperationError('Telegram did not return a group invitation.')
        invitation.status = invitation.STATUS_READY
        invitation.invite_created_at = now
        invitation.invite_expires_at = expires_at
        invitation.invite_digest = hashlib.sha256(invite_link.encode()).hexdigest()
        invitation.pending_invite_url = invite_link
        invitation.last_error_code = ''
        invitation.save()
        return {'invite_link': invite_link}

    result = execute_operation(operation, create_once)
    invite_url = str((result or {}).get('invite_link') or '')
    if not invite_url:
        invitation.refresh_from_db()
        invite_url = invitation.pending_invite_url
    if not invite_url:
        raise ExternalOperationError('The existing invitation cannot be recovered; replace it from Admin.')
    invitation.status = invitation.STATUS_READY
    invitation.invite_created_at = now
    invitation.invite_expires_at = expires_at
    invitation.invite_digest = hashlib.sha256(invite_url.encode()).hexdigest()
    invitation.pending_invite_url = invite_url
    invitation.last_error_code = ''
    invitation.save()
    return invite_url


def deliver_staff_telegram_onboarding(*, onboarding: StaffTelegramOnboarding) -> dict:
    """Publish launchers, create invites and send one private welcome."""
    onboarding.refresh_from_db()
    profile = UserProfile.objects.filter(user=onboarding.user).first()
    if not profile or not profile.telegram_id:
        return {'status': onboarding.STATUS_PENDING, 'message': 'Telegram activation is still pending.'}

    onboarding.status = onboarding.STATUS_DELIVERING
    onboarding.activated_at = onboarding.activated_at or timezone.now()
    onboarding.last_error_code = ''
    onboarding.save(update_fields=['status', 'activated_at', 'last_error_code', 'updated_at'])
    invite_buttons = []
    failures = 0
    for invitation in onboarding.group_invitations.select_related('group_configuration'):
        if invitation.status in {invitation.STATUS_SENT, invitation.STATUS_JOINED}:
            continue
        try:
            publish_group_launcher(
                invitation.group_configuration,
                operation_key_suffix=f'staff-{onboarding.pk}-{onboarding.revision}',
            )
            invitation.launcher_ready_at = timezone.now()
            invitation.save(update_fields=['launcher_ready_at', 'updated_at'])
            invite_url = _create_group_invite(invitation)
            invite_buttons.append({
                'text': f'Join {invitation.group_configuration.display_name or invitation.group_configuration.group_id}',
                'url': invite_url,
            })
        except Exception as exc:
            failures += 1
            invitation.status = invitation.STATUS_ATTENTION
            invitation.last_error_code = redacted_error_code(exc)
            invitation.save(update_fields=['status', 'last_error_code', 'updated_at'])
            logger.warning('Staff Telegram group invitation failed for onboarding %s.', onboarding.pk, exc_info=True)

    # Include still-valid links created by an earlier partial delivery.
    for invitation in onboarding.group_invitations.select_related('group_configuration').filter(
        status=StaffTelegramGroupInvitation.STATUS_READY,
    ):
        if invitation.pending_invite_url and not any(row['url'] == invitation.pending_invite_url for row in invite_buttons):
            invite_buttons.append({
                'text': f'Join {invitation.group_configuration.display_name or invitation.group_configuration.group_id}',
                'url': invitation.pending_invite_url,
            })

    app_buttons = _authorized_launcher_buttons(onboarding)
    keyboard_buttons = app_buttons + invite_buttons
    keyboard = [keyboard_buttons[index:index + 2] for index in range(0, len(keyboard_buttons), 2)]
    name = onboarding.user.get_full_name().strip() or onboarding.user.get_username()
    text = (
        f'Welcome to JBL Field Workflow, {name}. Your Telegram identity is verified and your staff access is active. '
        'Use the buttons below to open the tools assigned to you. Use each private group link below to join the JBL '
        'groups selected by your administrator. Each group link works once and expires after 24 hours. If anything '
        'is missing, contact your administrator.'
    )
    operation, _ = reserve_operation(
        integration='telegram', operation_type='staff_onboarding_welcome',
        deduplication_key=f'telegram:staff-onboarding:{onboarding.pk}:welcome:{onboarding.revision}',
        source_model='StaffTelegramOnboarding', source_id=str(onboarding.pk),
        operation_payload=(str(onboarding.pk), profile.telegram_id, onboarding.revision),
        metadata={'group_count': onboarding.group_invitations.count(), 'app_count': len(app_buttons)},
    )

    try:
        result = execute_operation(operation, lambda: {
            'message_id': (telegram_api_call('sendMessage', {
                'chat_id': profile.telegram_id,
                'text': text,
                'reply_markup': {'inline_keyboard': keyboard},
                'disable_web_page_preview': True,
            }).get('result') or {}).get('message_id'),
        })
        onboarding.welcome_sent_at = onboarding.welcome_sent_at or timezone.now()
        onboarding.status = onboarding.STATUS_ATTENTION if failures else onboarding.STATUS_COMPLETE
        onboarding.completed_at = None if failures else timezone.now()
        onboarding.last_error_code = 'partial_group_delivery' if failures else ''
        onboarding.save()
        onboarding.group_invitations.filter(
            status=StaffTelegramGroupInvitation.STATUS_READY,
        ).update(status=StaffTelegramGroupInvitation.STATUS_SENT, pending_invite_url='', last_error_code='')
        _record_onboarding(onboarding, 'staff_telegram_onboarding.welcome_sent')
        return {
            'status': onboarding.status,
            'message': ('Telegram identity verified and onboarding sent.' if not failures else
                        'Telegram identity verified. Some group invitations need administrator attention.'),
            'message_id': (result or {}).get('message_id'),
        }
    except Exception as exc:
        onboarding.status = onboarding.STATUS_ATTENTION
        onboarding.last_error_code = redacted_error_code(exc)
        onboarding.save(update_fields=['status', 'last_error_code', 'updated_at'])
        logger.warning('Staff Telegram welcome failed for onboarding %s.', onboarding.pk, exc_info=True)
        return {
            'status': onboarding.status,
            'message': 'Telegram identity verified. Your administrator must retry the welcome message.',
        }


def complete_staff_telegram_onboarding(*, user) -> dict:
    onboarding = StaffTelegramOnboarding.objects.filter(user=user).order_by('-created_at').first()
    if onboarding is None:
        return {'status': 'not_required', 'message': 'Telegram identity verified. You can now open your JBL Mini App.'}
    return deliver_staff_telegram_onboarding(onboarding=onboarding)


@transaction.atomic
def prepare_staff_telegram_onboarding_retry(*, onboarding: StaffTelegramOnboarding) -> StaffTelegramOnboarding:
    onboarding = StaffTelegramOnboarding.objects.select_for_update().get(pk=onboarding.pk)
    onboarding.revision += 1
    onboarding.status = onboarding.STATUS_DELIVERING
    onboarding.last_error_code = ''
    onboarding.save(update_fields=['revision', 'status', 'last_error_code', 'updated_at'])
    retryable = onboarding.group_invitations.filter(
        Q(status=StaffTelegramGroupInvitation.STATUS_ATTENTION)
        | Q(
            status=StaffTelegramGroupInvitation.STATUS_SENT,
            invite_expires_at__lte=timezone.now(),
        )
    )
    retryable.update(
        status=StaffTelegramGroupInvitation.STATUS_PENDING,
        pending_invite_url='', invite_digest='', invite_created_at=None,
        invite_expires_at=None, last_error_code='',
    )
    return onboarding


@transaction.atomic
def record_governed_group_join(*, telegram_id: str, group_id: str) -> bool:
    invitation = StaffTelegramGroupInvitation.objects.select_for_update().filter(
        onboarding__user__staff_profile__telegram_id=str(telegram_id),
        group_configuration__group_id=str(group_id),
        status__in=[
            StaffTelegramGroupInvitation.STATUS_READY,
            StaffTelegramGroupInvitation.STATUS_SENT,
            StaffTelegramGroupInvitation.STATUS_ATTENTION,
        ],
    ).select_related('onboarding').first()
    if invitation is None:
        return False
    invitation.status = invitation.STATUS_JOINED
    invitation.joined_at = timezone.now()
    invitation.pending_invite_url = ''
    invitation.last_error_code = ''
    invitation.save()
    onboarding = invitation.onboarding
    if (
        onboarding.welcome_sent_at
        and not onboarding.group_invitations.exclude(status=invitation.STATUS_JOINED).exists()
    ):
        onboarding.status = onboarding.STATUS_COMPLETE
        onboarding.completed_at = timezone.now()
        onboarding.last_error_code = ''
        onboarding.save()
    _record_onboarding(onboarding, 'staff_telegram_onboarding.group_joined')
    return True


def _record_onboarding(onboarding: StaffTelegramOnboarding, action: str) -> None:
    from core.services.compliance_audit import record_event

    record_event(
        workflow='access_control', action=action, category='authorization',
        subject_type='staff_telegram_onboarding', subject_id=str(onboarding.pk),
        actor=onboarding.plan.reviewed_by or onboarding.plan.requested_by,
        authority_user=onboarding.plan.reviewed_by or onboarding.plan.requested_by,
        request_id=onboarding.plan.request_key or str(onboarding.pk),
        source_model='StaffTelegramOnboarding', source_event_id=f'{onboarding.pk}:{action}:{onboarding.revision}',
        deduplication_key=f'staff-telegram:{onboarding.pk}:{action}:{onboarding.revision}',
        before_values={}, after_values={'status': onboarding.status},
        metadata={'group_count': onboarding.group_invitations.count()}, sensitive=True,
        occurred_at=timezone.now(),
    )
