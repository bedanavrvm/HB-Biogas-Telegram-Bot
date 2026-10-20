"""Request-local protection for the vendor's transient enrollment secret.

This is storage adaptation, not permission to enroll. Never install it as the
global session backend or treat an ordinary authenticated session as MFA proof.
"""
import json
import math
import time
from collections.abc import MutableMapping
from contextlib import contextmanager

from allauth.mfa.totp.internal.auth import SECRET_SESSION_KEY

from .crypto import MFASecretUnavailable, decrypt_secret, encrypt_secret
from .models import StaffBrowserAdmission


CHANNEL_KEY = 'staff_browser_channel_v1'
ENROLLMENT_CONTEXT_KEY = 'staff_browser_enrollment_v1'
SETUP_CONTEXT_KEY = 'staff_browser_initial_setup_v1'
ENROLLMENT_SECONDS = 600


def clear_browser_context(request):
    if request is not None and hasattr(request, 'session'):
        request.session.pop(CHANNEL_KEY, None)
        request.session.pop(ENROLLMENT_CONTEXT_KEY, None)
        request.session.pop(SETUP_CONTEXT_KEY, None)
        # Discard opaque encrypted/expired material without decrypting it.
        if SECRET_SESSION_KEY in request.session:
            del request.session[SECRET_SESSION_KEY]


class EnrollmentSession(MutableMapping):
    def __init__(self, session, request):
        self.wrapped = session
        self.request = request

    def __getattr__(self, name):
        return getattr(self.wrapped, name)

    def __iter__(self):
        return iter(self.wrapped.keys())

    def __len__(self):
        return len(self.wrapped.keys())

    def __contains__(self, key):
        return key in self.wrapped

    def _binding(self):
        actor = getattr(self.request, 'user', None)
        if not actor or not actor.is_authenticated:
            raise MFASecretUnavailable('Restart approved browser enrollment.')
        row = StaffBrowserAdmission.objects.filter(user_id=actor.pk, user__is_active=True, enabled=True).first()
        if row is None:
            raise MFASecretUnavailable('Restart approved browser enrollment.')
        return {'user_id': str(actor.pk), 'admission_id': str(row.pk), 'revision': row.revision}

    def __getitem__(self, key):
        raw = self.wrapped[key]
        if key != SECRET_SESSION_KEY:
            return raw
        try:
            payload = json.loads(decrypt_secret(raw))
            if not isinstance(payload, dict):
                raise ValueError
            now = time.time()
            expires = payload['expires_at']
            if (
                payload.get('purpose') != 'staff-browser-totp-enrollment-v1'
                or type(expires) not in (int, float)
                or not math.isfinite(expires)
                or not 0 < expires - now <= ENROLLMENT_SECONDS
                or payload['binding'] != self._binding()
                or not isinstance(payload['secret'], str)
                or not payload['secret']
            ):
                raise ValueError
            return payload['secret']
        except (ValueError, TypeError, KeyError):
            self.wrapped.pop(key, None)
            raise MFASecretUnavailable('Restart approved browser enrollment.') from None

    def __setitem__(self, key, value):
        if key == SECRET_SESSION_KEY:
            if not isinstance(value, str) or not value:
                raise MFASecretUnavailable('Restart approved browser enrollment.')
            value = encrypt_secret(json.dumps({
                'purpose': 'staff-browser-totp-enrollment-v1', 'secret': value,
                'binding': self._binding(), 'expires_at': time.time() + ENROLLMENT_SECONDS,
            }, sort_keys=True))
        self.wrapped[key] = value

    def __delitem__(self, key):
        del self.wrapped[key]

    def pop(self, key, *default):
        # The pinned vendor only discards this key; a discard must also work
        # after expiry/key rotation/revocation, without exposing its value.
        if key == SECRET_SESSION_KEY:
            if key not in self.wrapped and not default:
                raise KeyError(key)
            self.wrapped.pop(key, None)
            return None
        return self.wrapped.pop(key, *default)


@contextmanager
def protected_browser_session(request):
    original = request.session
    previous = getattr(request, '_staff_browser_auth_boundary', False)
    request.session = EnrollmentSession(original, request)
    request._staff_browser_auth_boundary = True
    try:
        yield
    finally:
        request.session = original
        request._staff_browser_auth_boundary = previous
