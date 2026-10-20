"""Fail closed on unsafe browser activation; no provider/database side effects."""
from django.conf import settings
from django.core.checks import Error, register
from django.core.exceptions import ImproperlyConfigured

from .crypto import keyring
from .cache_keys import PRIVACY_KEY_FUNCTION, SHARED_CACHE_BACKENDS


@register()
def staff_browser_checks(app_configs, **kwargs):
    if not settings.STAFF_BROWSER_AUTH_ENABLED:
        return []
    errors = []
    try:
        keyring()
    except ImproperlyConfigured:
        errors.append(Error('Configure dedicated staff MFA encryption keys before activation.', id='staff_auth.E001'))
    if (
        settings.MFA_ADAPTER != 'staff_auth.adapters.StaffMFAAdapter'
        or settings.ACCOUNT_ADAPTER != 'staff_auth.adapters.StaffAccountAdapter'
    ):
        errors.append(Error('Browser access requires the closed staff account and encrypted MFA adapters.', id='staff_auth.E002'))
    if (
        set(settings.MFA_SUPPORTED_TYPES) != {'totp', 'recovery_codes'}
        or settings.MFA_TRUST_ENABLED
        or not settings.MFA_RECOVERY_CODES_SHOW_ONCE
        or getattr(settings, 'MFA_TOTP_INSECURE_BYPASS_CODE', None)
        or settings.MFA_ALLOW_UNVERIFIED_EMAIL
        or settings.ACCOUNT_EMAIL_VERIFICATION != 'mandatory'
        or settings.ACCOUNT_LOGIN_BY_CODE_ENABLED
    ):
        errors.append(Error(
            'Company MFA requires TOTP/recovery, verified email and no trust/code bypass.',
            id='staff_auth.E003',
        ))
    if (
        type(settings.STAFF_BROWSER_SESSION_AGE_SECONDS) is not int
        or not 1 <= settings.STAFF_BROWSER_SESSION_AGE_SECONDS <= 86400
    ):
        errors.append(Error('Set a bounded staff-browser session lifetime.', id='staff_auth.E004'))
    if not settings.DEBUG and (
        not settings.SESSION_COOKIE_SECURE
        or not settings.SESSION_COOKIE_HTTPONLY
        or not settings.CSRF_COOKIE_SECURE
        or settings.SESSION_ENGINE == 'django.contrib.sessions.backends.signed_cookies'
    ):
        errors.append(Error('Company browser sessions require secure server-side cookies and CSRF.', id='staff_auth.E005'))
    # P1a is only a dormant foundation, not a provision/enroll/recover product.
    errors.append(Error('P1a has no approved browser login/enrollment/recovery routes. Keep STAFF_BROWSER_AUTH_ENABLED=False.', id='staff_auth.E006'))
    default_cache = settings.CACHES.get('default', {})
    if default_cache.get('BACKEND') not in SHARED_CACHE_BACKENDS:
        errors.append(Error(
            'Browser authentication requires a reviewed shared Redis/Memcached cache; local, file, database and dummy caches are not accepted.',
            hint='Prove all workers share non-evicting security state, consistent reads and atomic add before M1. This check does not connect to a cache.',
            id='staff_auth.E007',
        ))
    if default_cache.get('KEY_FUNCTION') != PRIVACY_KEY_FUNCTION:
        errors.append(Error(
            'Native authentication cache keys require staff_auth.cache_keys.native_cache_key before backend validation.',
            id='staff_auth.E008',
        ))
    return errors
