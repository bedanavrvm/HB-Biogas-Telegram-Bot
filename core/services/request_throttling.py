"""Database-backed, privacy-safe throttling for selected public boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone as dt_timezone
import hashlib
import hmac

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from core.models import PublicEndpointThrottleBucket


@dataclass(frozen=True)
class ThrottleDecision:
    allowed: bool
    retry_after: int = 0


def _digest(scope: str, value: str) -> str:
    secret = str(settings.SECRET_KEY).encode('utf-8')
    message = f'{scope}\0{value}'.encode('utf-8', errors='replace')
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def privacy_safe_ip_key(request) -> str:
    """Return a keyed digest; raw network addresses never enter persistence."""
    forwarded = str(request.META.get('HTTP_X_FORWARDED_FOR') or '')
    address = forwarded.split(',', 1)[0].strip() if forwarded else ''
    address = address or str(request.META.get('REMOTE_ADDR') or 'unknown').strip()
    return _digest('network', address[:128] or 'unknown')


def privacy_safe_identity_key(kind: str, value: object) -> str:
    return _digest(f'identity:{kind}', str(value or '').strip()[:512] or 'unknown')


def _window(now, seconds: int) -> tuple[datetime, datetime]:
    epoch = int(now.timestamp())
    start_epoch = epoch - (epoch % seconds)
    start = datetime.fromtimestamp(start_epoch, tz=dt_timezone.utc)
    return start, start + timedelta(seconds=seconds)


def consume(
    *, scope: str, key_hash: str, limit: int, window_seconds: int | None = None,
) -> ThrottleDecision:
    """Atomically consume one fixed-window allowance."""
    limit = int(limit)
    seconds = int(
        window_seconds
        if window_seconds is not None
        else getattr(settings, 'PUBLIC_RATE_LIMIT_WINDOW_SECONDS', 600)
    )
    if limit <= 0 or seconds <= 0:
        return ThrottleDecision(allowed=True)
    now = timezone.now()
    window_start, expires_at = _window(now, seconds)
    with transaction.atomic():
        bucket, created = PublicEndpointThrottleBucket.objects.select_for_update().get_or_create(
            scope=str(scope)[:80],
            key_hash=str(key_hash)[:64],
            window_started_at=window_start,
            defaults={'request_count': 1, 'expires_at': expires_at},
        )
        if created:
            return ThrottleDecision(allowed=True)
        if bucket.request_count >= limit:
            retry_after = max(1, int((bucket.expires_at - now).total_seconds()) + 1)
            return ThrottleDecision(allowed=False, retry_after=retry_after)
        bucket.request_count += 1
        bucket.save(update_fields=['request_count', 'updated_at'])
    return ThrottleDecision(allowed=True)


def consume_ip(request, *, scope: str, limit: int) -> ThrottleDecision:
    return consume(scope=scope, key_hash=privacy_safe_ip_key(request), limit=limit)


def consume_identity(*, scope: str, kind: str, value: object, limit: int) -> ThrottleDecision:
    return consume(
        scope=scope,
        key_hash=privacy_safe_identity_key(kind, value),
        limit=limit,
    )
