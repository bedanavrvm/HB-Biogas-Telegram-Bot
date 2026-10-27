"""Fail closed on unsafe browser activation; no provider/database side effects."""
from django.conf import settings
from django.core.checks import Error, register
from django.core.exceptions import ImproperlyConfigured

from .crypto import keyring
from .cache_keys import PRIVACY_KEY_FUNCTION, SHARED_CACHE_BACKENDS


@register()
def staff_browser_checks(app_configs, **kwargs):
    if (getattr(settings, 'STAFF_BROWSER_DEMO_ENABLED', False)
            and settings.RELEASE_ENVIRONMENT not in {'development', 'staging', 'test'}):
        return [Error('Synthetic browser demos cannot be enabled in production.', id='staff_auth.E009')]
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
    from .production import release_errors
    release = release_errors(settings)
    if release:
        errors.append(Error(' '.join(message for _code,message in release),id='staff_auth.E006'))
    default_cache = settings.CACHES.get('default', {})
    postgres_security = (default_cache.get('BACKEND') == 'staff_auth.security_cache.PostgresSecurityCache'
                         and settings.DATABASES['default']['ENGINE'] == 'django.db.backends.postgresql')
    if not postgres_security and default_cache.get('BACKEND') not in SHARED_CACHE_BACKENDS:
        errors.append(Error(
            'Browser authentication requires PostgreSQL native security state or a reviewed shared Redis/Memcached cache; ordinary database/local caches are not accepted.',
            hint='Use ADR 0074 with PostgreSQL and the checked-in migration. Prove shared atomic state before M1. This check does not connect to a store.',
            id='staff_auth.E007',
        ))
    if default_cache.get('KEY_FUNCTION') != PRIVACY_KEY_FUNCTION:
        errors.append(Error(
            'Native authentication cache keys require staff_auth.cache_keys.native_cache_key before backend validation.',
            id='staff_auth.E008',
        ))
    return errors
