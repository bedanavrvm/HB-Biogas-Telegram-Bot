"""Shared Telegram Mini App initData verification."""
from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import parse_qsl

from django.conf import settings


def validate_telegram_init_data(
    init_data: str,
    *,
    require_auth: bool = True,
    max_age_seconds: int = 86400,
) -> tuple[bool, str, dict]:
    """Return the verified Telegram query fields, or a staff-safe error."""
    if not require_auth:
        return True, '', {}
    bot_token = str(getattr(settings, 'TELEGRAM_BOT_TOKEN', '') or '').strip()
    if not bot_token:
        return False, 'Telegram authentication is not configured.', {}
    if not init_data:
        return False, 'Telegram Mini App authentication data is missing.', {}

    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop('hash', '')
    if not received_hash:
        return False, 'Telegram Mini App hash is missing.', {}
    if not _has_valid_hash(pairs, received_hash, bot_token):
        return False, 'Telegram Mini App authentication failed.', {}
    auth_error = _auth_date_error(pairs.get('auth_date'), max_age_seconds)
    if auth_error:
        return False, auth_error, {}
    return True, '', pairs


def _has_valid_hash(pairs: dict, received_hash: str, bot_token: str) -> bool:
    data_check_string = '\n'.join(f'{key}={value}' for key, value in sorted(pairs.items()))
    secret_key = hmac.new(b'WebAppData', bot_token.encode('utf-8'), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode('utf-8'), hashlib.sha256).hexdigest()
    return hmac.compare_digest(calculated_hash, received_hash)


def _auth_date_error(auth_date: str, max_age_seconds: int) -> str:
    if not auth_date or max_age_seconds <= 0:
        return ''
    try:
        expired = time.time() - int(auth_date) > max_age_seconds
    except ValueError:
        return 'Telegram Mini App auth date is invalid.'
    return 'Telegram Mini App authentication expired.' if expired else ''
