"""Server-owned browser assurance; authentication never grants workflow access.

No operational route uses this foundation yet. The final allauth login signal,
not a password check, request header, Telegram login or MFA-enrollment flag,
is the sole issuer. Pin/test the library's authentication record contract.
"""
import hashlib
import json
import math
import time

from allauth.account.authentication import get_authentication_records
from allauth.mfa.models import Authenticator
from django.conf import settings
from django.contrib.auth import HASH_SESSION_KEY, SESSION_KEY, get_user_model
from django.core.exceptions import PermissionDenied
from django.utils.crypto import constant_time_compare

from .models import StaffBrowserAdmission


ASSURANCE_KEY = 'staff_browser_assurance_v1'
MAX_LOGIN_SECONDS = 900


def _time(value):
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _factor_fingerprint(factor):
    raw = json.dumps(factor.data, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(raw).hexdigest()


def _factor_id(value):
    # Persisted session state can outlive a code/version change. Malformed
    # identifiers deny access instead of escaping the boundary as a DB error.
    if type(value) is int and 0 < value <= 9223372036854775807:
        return value
    return None


def clear_assurance(request):
    if request is not None and hasattr(request, 'session'):
        request.session.pop(ASSURANCE_KEY, None)


def issue_assurance(request, user):
    """Called only after allauth completes login; never completes MFA itself."""
    clear_assurance(request)
    if not settings.STAFF_BROWSER_AUTH_ENABLED or not user.is_active or request is None or not hasattr(request, 'session'):
        return False
    if str(request.session.get(SESSION_KEY, '')) != str(user.pk):
        return False
    if not constant_time_compare(str(request.session.get(HASH_SESSION_KEY, '')), user.get_session_auth_hash()):
        return False
    records = get_authentication_records(request)
    if not isinstance(records, list):
        return False
    password = next((row for row in reversed(records) if isinstance(row, dict) and row.get('method') == 'password'), None)
    mfa = next((row for row in reversed(records) if isinstance(row, dict) and row.get('method') == 'mfa'), None)
    if not password or not mfa or mfa.get('type') not in ('totp', 'recovery_codes'):
        return False
    password_at, mfa_at = _time(password.get('at')), _time(mfa.get('at'))
    now = time.time()
    if password_at is None or mfa_at is None or not 0 <= mfa_at - password_at <= MAX_LOGIN_SECONDS or not 0 <= now - mfa_at <= MAX_LOGIN_SECONDS:
        return False
    admission = StaffBrowserAdmission.objects.filter(user_id=user.pk, enabled=True).first()
    if admission is None or password_at < admission.updated_at.timestamp():
        return False
    factor_id = _factor_id(mfa.get('id'))
    if factor_id is None:
        return False
    factor = Authenticator.objects.filter(user_id=user.pk, pk=factor_id, type=mfa['type']).first()
    totp = Authenticator.objects.filter(user_id=user.pk, type='totp').first()
    if factor is None or totp is None:
        return False
    request.session[ASSURANCE_KEY] = {
        'user_id': str(user.pk), 'at': mfa_at,
        'auth_hash': user.get_session_auth_hash(),
        'totp_id': totp.pk, 'totp_fingerprint': _factor_fingerprint(totp),
        'admission_id': str(admission.pk), 'admission_revision': admission.revision,
    }
    return True


def require_browser_user(request):
    """Resolve current identity only; the caller must still check workflow policy.

    Future unsafe browser endpoints must also enforce Django CSRF protection.
    A disabled/expired/revoked session is denied before any business service.
    """
    def deny():
        clear_assurance(request)
        raise PermissionDenied('Complete company password and MFA authentication.')

    if not settings.STAFF_BROWSER_AUTH_ENABLED or request.headers.get('X-Telegram-Init-Data'):
        deny()
    if not hasattr(request, 'session'):
        deny()
    marker = request.session.get(ASSURANCE_KEY)
    actor = getattr(request, 'user', None)
    if not actor or not actor.is_authenticated or not isinstance(marker, dict):
        deny()
    if str(marker.get('user_id')) != str(actor.pk) or str(request.session.get(SESSION_KEY)) != str(actor.pk):
        deny()
    user = get_user_model().objects.filter(pk=actor.pk, is_active=True).first()
    if user is None:
        deny()
    admission = StaffBrowserAdmission.objects.filter(user_id=user.pk, enabled=True).first()
    if (
        admission is None
        or str(marker.get('admission_id')) != str(admission.pk)
        or type(marker.get('admission_revision')) is not int
        or marker['admission_revision'] != admission.revision
    ):
        deny()
    stamp = _time(marker.get('at'))
    if stamp is None or not 0 <= time.time() - stamp <= settings.STAFF_BROWSER_SESSION_AGE_SECONDS:
        deny()
    current_hash = user.get_session_auth_hash()
    if not constant_time_compare(str(marker.get('auth_hash', '')), current_hash) or not constant_time_compare(str(request.session.get(HASH_SESSION_KEY, '')), current_hash):
        deny()
    factor_id = _factor_id(marker.get('totp_id'))
    if factor_id is None:
        deny()
    totp = Authenticator.objects.filter(pk=factor_id, user_id=user.pk, type='totp').first()
    if totp is None or not constant_time_compare(str(marker.get('totp_fingerprint', '')), _factor_fingerprint(totp)):
        deny()
    return user
