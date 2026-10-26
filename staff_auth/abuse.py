"""Closed-browser IP policy and privacy; never an alternative MFA verifier."""
from contextlib import contextmanager
import logging

from allauth.core.internal.ratelimit import get_ip
from django.views.decorators.debug import sensitive_variables

from core.services.request_throttling import consume, privacy_safe_identity_key


logger = logging.getLogger(__name__)


class AuthenticationUnavailable(Exception):
    """No backend diagnostics or credential values may cross this boundary."""


class AbuseControlUnavailable(AuthenticationUnavailable):
    """Pre-credential hold; retain previously established session progress."""


@sensitive_variables()
def consume_network(request, *, scope, limit=30, window_seconds=600):
    # Pinned allauth applies the same trusted-proxy and IPv6-prefix policy as
    # native limits. Do not use the legacy public limiter's unrestricted XFF.
    return consume(
        scope=scope, key_hash=privacy_safe_identity_key('staff-browser-network', get_ip(request)),
        limit=limit, window_seconds=window_seconds,
    )


@contextmanager
def native_authentication():
    """Contain native/cache failures, including backends with custom errors."""
    try:
        yield
    except Exception:
        # No exception text/traceback: cache errors can contain raw vendor keys.
        logger.error('Native company-browser authentication could not complete.')
        raise AuthenticationUnavailable from None
