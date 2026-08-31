"""Compatibility adapter for the canonical Telegram identity verifier.

New callers should use :mod:`core.services.telegram_identity` directly. This
module temporarily preserves the legacy ``(valid, error, payload)`` shape used
by older workflow boundaries.
"""
from __future__ import annotations

from django.conf import settings


def authentication_bypass_allowed() -> bool:
    """Allow unsigned local requests only in an explicit debug/test runtime."""
    return bool(
        getattr(settings, 'DEBUG', False)
        or getattr(settings, 'RUNNING_TESTS', False)
    )


def validate_telegram_init_data(
    init_data: str,
    *,
    require_auth: bool = True,
    max_age_seconds: int = 86400,
) -> tuple[bool, str, dict]:
    """Delegate verification while preserving the legacy response tuple."""
    if not require_auth:
        if authentication_bypass_allowed():
            return True, '', {}
        return (
            False,
            'Telegram Mini App authentication can only be disabled in an explicit local or test runtime.',
            {},
        )
    from core.services.telegram_identity import (
        TelegramAuthenticationError,
        validate_telegram_init_data as validate_canonical_telegram_init_data,
    )
    try:
        payload, _identity = validate_canonical_telegram_init_data(
            init_data,
            max_age_seconds=max_age_seconds,
        )
    except TelegramAuthenticationError as exc:
        return False, str(exc), {}
    return True, '', payload
