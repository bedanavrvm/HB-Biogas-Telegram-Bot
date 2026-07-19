"""Pinned, group-scoped Telegram Mini App launchers."""

from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING

import requests
from django.conf import settings
from django.utils import timezone

if TYPE_CHECKING:
    from core.models import GroupSheetConfiguration


logger = logging.getLogger(__name__)

TAT_TRACKER_LAUNCHER = 'tat_tracker'
SPIN_LAUNCHER = 'spin_credit'
ORDER_APPROVAL_LAUNCHER = 'order_approval'
PIPELINE_PORTAL_LAUNCHER = 'pipeline_portal'
COMPLAINT_CASES_LAUNCHER = 'complaint_cases'

MINI_APP_LAUNCHER_CHOICES = (
    (TAT_TRACKER_LAUNCHER, 'TAT Tracker'),
    (SPIN_LAUNCHER, 'SPIN / CRB'),
    (ORDER_APPROVAL_LAUNCHER, 'Order Approval'),
    (PIPELINE_PORTAL_LAUNCHER, 'Pipeline Portal'),
    (COMPLAINT_CASES_LAUNCHER, 'Complaint Cases'),
)

_LAUNCHER_LABELS = dict(MINI_APP_LAUNCHER_CHOICES)
_DEFAULTS_BY_WORKFLOW = {
    'tat_tracker': (TAT_TRACKER_LAUNCHER,),
    'spin_credit_analysis': (SPIN_LAUNCHER,),
    'order_approval': (ORDER_APPROVAL_LAUNCHER,),
    'case': (COMPLAINT_CASES_LAUNCHER,),
}
_LAUNCHER_METADATA_KEY = 'telegram_launcher'


class TelegramLauncherError(Exception):
    """A stable, staff-safe error while publishing a Telegram launcher."""


class _TelegramApiError(TelegramLauncherError):
    def __init__(self, method: str, description: str = '', migration_group_id: str = ''):
        self.method = method
        self.description = description
        self.migration_group_id = migration_group_id
        super().__init__(f'Telegram {method} could not complete.')


def default_launcher_keys(workflow: dict | None) -> list[str]:
    workflow_type = str((workflow or {}).get('type') or '').strip()
    return list(_DEFAULTS_BY_WORKFLOW.get(workflow_type, ()))


def configured_launcher_keys(config: 'GroupSheetConfiguration') -> list[str]:
    workflow = config.workflow or {}
    configured = workflow.get('mini_app_launchers')
    source = configured if isinstance(configured, list) else default_launcher_keys(workflow)
    seen = set()
    return [
        key for key in source
        if isinstance(key, str)
        and key in _LAUNCHER_LABELS
        and not (key in seen or seen.add(key))
    ]


def _pipeline_portal_url() -> str:
    bot_username = str(getattr(settings, 'TELEGRAM_BOT_USERNAME', '') or '').strip().lstrip('@')
    short_name = str(getattr(settings, 'PORTAL_MINI_APP_SHORT_NAME', '') or '').strip().strip('/')
    if bot_username and short_name:
        return f'https://t.me/{bot_username}/{short_name}'
    base_url = str(getattr(settings, 'APP_BASE_URL', '') or '').rstrip('/')
    return f'{base_url}/api/portal/' if base_url else ''


def build_launcher_url(launcher_key: str, group_id: str) -> str:
    """Build a durable Mini App URL for a pinned group launcher.

    These links deliberately do not embed the short-lived form token used by a
    one-off command response. The Mini App APIs still require verified Telegram
    initData and their existing staff authorization checks.
    """
    if launcher_key == TAT_TRACKER_LAUNCHER:
        from core.services.tat_tracker import build_tat_tracker_launcher_url
        return build_tat_tracker_launcher_url(group_id)
    if launcher_key == SPIN_LAUNCHER:
        from core.services.spin_credit import build_spin_launcher_url
        return build_spin_launcher_url(group_id)
    if launcher_key == ORDER_APPROVAL_LAUNCHER:
        from core.services.order_approval import build_order_approval_launcher_url
        return build_order_approval_launcher_url(group_id)
    if launcher_key == PIPELINE_PORTAL_LAUNCHER:
        return _pipeline_portal_url()
    if launcher_key == COMPLAINT_CASES_LAUNCHER:
        from core.services.complaint_cases import build_complaint_cases_launcher_url
        return build_complaint_cases_launcher_url(group_id)
    return ''


def preview_group_launcher(config: 'GroupSheetConfiguration') -> dict:
    keys = configured_launcher_keys(config)
    if not keys:
        raise TelegramLauncherError('Select at least one Mini App before publishing this group launcher.')

    buttons = []
    for key in keys:
        url = build_launcher_url(key, config.group_id)
        if not url:
            raise TelegramLauncherError(
                f'{_LAUNCHER_LABELS[key]} is not configured for Telegram launch.'
            )
        buttons.append({'text': _LAUNCHER_LABELS[key], 'url': url})

    keyboard = [buttons[index:index + 2] for index in range(0, len(buttons), 2)]
    payload = {
        'text': 'JBL Apps\nChoose a tool for this group.',
        'reply_markup': {'inline_keyboard': keyboard},
    }
    signature = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(',', ':')).encode('utf-8')
    ).hexdigest()
    return {**payload, 'keys': keys, 'signature': signature}


def publish_group_launcher(
    config: 'GroupSheetConfiguration',
    *,
    token: str | None = None,
    timeout: int | None = None,
    allow_disabled: bool = False,
) -> dict:
    if not config.enabled and not allow_disabled:
        raise TelegramLauncherError('Disabled groups cannot publish a launcher.')
    token = str(token or getattr(settings, 'TELEGRAM_BOT_TOKEN', '') or '').strip()
    if not token:
        raise TelegramLauncherError('TELEGRAM_BOT_TOKEN is not configured.')
    timeout = int(timeout or getattr(settings, 'API_REQUEST_TIMEOUT', 10))

    try:
        return _publish_once(config, token, timeout)
    except _TelegramApiError as exc:
        if not exc.migration_group_id:
            raise _safe_api_error(exc) from exc
        _apply_migrated_group_id(config, exc.migration_group_id)
        return _publish_once(config, token, timeout)


def _publish_once(config: 'GroupSheetConfiguration', token: str, timeout: int) -> dict:
    preview = preview_group_launcher(config)
    state = dict((config.metadata or {}).get(_LAUNCHER_METADATA_KEY) or {})
    message_id = state.get('message_id')
    action = 'sent'

    if message_id:
        try:
            _telegram_call(
                token,
                'editMessageText',
                {
                    'chat_id': config.group_id,
                    'message_id': message_id,
                    'text': preview['text'],
                    'reply_markup': preview['reply_markup'],
                },
                timeout,
            )
            action = 'updated'
        except _TelegramApiError as exc:
            if exc.migration_group_id:
                raise
            if _is_unchanged_message(exc):
                action = 'unchanged'
            elif _is_missing_or_uneditable_message(exc):
                message_id = None
            else:
                raise

    if not message_id:
        response = _telegram_call(
            token,
            'sendMessage',
            {
                'chat_id': config.group_id,
                'text': preview['text'],
                'reply_markup': preview['reply_markup'],
                'disable_web_page_preview': True,
            },
            timeout,
        )
        message_id = (response.get('result') or {}).get('message_id')
        if not message_id:
            raise TelegramLauncherError('Telegram did not return the launcher message ID.')
        action = 'sent'

    try:
        _telegram_call(
            token,
            'pinChatMessage',
            {
                'chat_id': config.group_id,
                'message_id': message_id,
                'disable_notification': True,
            },
            timeout,
        )
    except _TelegramApiError as exc:
        _save_launcher_state(
            config,
            message_id=message_id,
            signature=preview['signature'],
            pin_status='un-pinned',
            error='Launcher was published, but Telegram could not pin it.',
        )
        raise _safe_api_error(exc, pinning=True) from exc

    _save_launcher_state(
        config,
        message_id=message_id,
        signature=preview['signature'],
        pin_status='pinned',
        error='',
    )
    logger.info('Published Telegram launcher for group %s (%s).', config.group_id, action)
    return {'action': action, 'message_id': message_id, 'keys': preview['keys']}


def _telegram_call(token: str, method: str, payload: dict, timeout: int) -> dict:
    try:
        response = requests.post(
            f'https://api.telegram.org/bot{token}/{method}',
            json=payload,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise _TelegramApiError(method) from exc
    try:
        response_payload = response.json()
    except ValueError:
        response_payload = {}
    if response.status_code >= 400 or not response_payload.get('ok'):
        parameters = response_payload.get('parameters') or {}
        raise _TelegramApiError(
            method,
            str(response_payload.get('description') or ''),
            str(parameters.get('migrate_to_chat_id') or ''),
        )
    return response_payload


def _is_unchanged_message(error: _TelegramApiError) -> bool:
    return 'message is not modified' in error.description.lower()


def _is_missing_or_uneditable_message(error: _TelegramApiError) -> bool:
    description = error.description.lower()
    return any(
        phrase in description
        for phrase in ('message to edit not found', 'message can\'t be edited')
    )


def _safe_api_error(error: _TelegramApiError, *, pinning: bool = False) -> TelegramLauncherError:
    if pinning:
        return TelegramLauncherError(
            'Launcher was published but could not be pinned. Make the bot a group admin with pin permission.'
        )
    return TelegramLauncherError(
        'Telegram could not publish the launcher. Check bot membership, administrator permissions, and chat configuration.'
    )


def _save_launcher_state(
    config: 'GroupSheetConfiguration',
    *,
    message_id: int,
    signature: str,
    pin_status: str,
    error: str,
) -> None:
    metadata = dict(config.metadata or {})
    metadata[_LAUNCHER_METADATA_KEY] = {
        'message_id': int(message_id),
        'content_signature': signature,
        'published_at': timezone.now().isoformat(),
        'pin_status': pin_status,
        'last_error': error,
    }
    config.metadata = metadata
    config.save(update_fields=['metadata', 'updated_at'])


def _apply_migrated_group_id(config: 'GroupSheetConfiguration', new_group_id: str) -> None:
    from core.models import GroupSheetConfiguration

    new_group_id = str(new_group_id).strip()
    if not new_group_id or str(config.group_id) == new_group_id:
        raise TelegramLauncherError('Telegram group migration could not be applied.')
    existing = (
        GroupSheetConfiguration.objects.filter(group_id=new_group_id)
        .exclude(pk=config.pk)
        .first()
    )
    metadata = dict(config.metadata or {})
    metadata['migrated_from_chat_id'] = str(config.group_id)
    metadata['migrated_to_chat_id'] = new_group_id
    if existing:
        metadata['migration_conflict_config_id'] = existing.pk
        config.enabled = False
        config.metadata = metadata
        config.save(update_fields=['enabled', 'metadata', 'updated_at'])
        raise TelegramLauncherError(
            'Telegram migrated this group, but the new chat ID already has a configuration. The stale row was disabled.'
        )

    launcher_state = dict(metadata.get(_LAUNCHER_METADATA_KEY) or {})
    launcher_state.pop('message_id', None)
    if launcher_state:
        metadata[_LAUNCHER_METADATA_KEY] = launcher_state
    config.group_id = new_group_id
    config.metadata = metadata
    config.save(update_fields=['group_id', 'metadata', 'updated_at'])
