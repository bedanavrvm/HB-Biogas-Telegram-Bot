"""Read-only production configuration checks used before a release."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


PLACEHOLDER_MARKERS = (
    'change-in-production',
    'your-',
    'example.com',
    'changeme',
)


@dataclass(frozen=True)
class ReadinessIssue:
    severity: str
    code: str
    message: str


def _blank_or_placeholder(value: object) -> bool:
    text = str(value or '').strip().lower()
    return not text or any(marker in text for marker in PLACEHOLDER_MARKERS)


def production_readiness_issues(settings) -> list[ReadinessIssue]:
    """Return configuration-only readiness issues without external calls."""
    issues: list[ReadinessIssue] = []

    def error(code: str, message: str) -> None:
        issues.append(ReadinessIssue('error', code, message))

    def warning(code: str, message: str) -> None:
        issues.append(ReadinessIssue('warning', code, message))

    if settings.DEBUG:
        error('debug-enabled', 'DEBUG must be False in production.')
    if _blank_or_placeholder(settings.SECRET_KEY) or len(settings.SECRET_KEY) < 50:
        error('secret-key', 'DJANGO_SECRET_KEY must be a non-placeholder value of at least 50 characters.')

    engine = settings.DATABASES['default']['ENGINE']
    if 'postgresql' not in engine:
        error('database-engine', 'Production must use PostgreSQL, not SQLite or another local database.')
    if not settings.DATABASES['default'].get('CONN_MAX_AGE'):
        warning('database-connections', 'Set DATABASE_CONN_MAX_AGE to reuse PostgreSQL connections.')

    hosts = list(settings.ALLOWED_HOSTS)
    if not hosts or '*' in hosts or any(_blank_or_placeholder(host) for host in hosts):
        error('allowed-hosts', 'ALLOWED_HOSTS must contain only explicit production host names.')

    parsed_base_url = urlparse(settings.APP_BASE_URL)
    if parsed_base_url.scheme != 'https' or not parsed_base_url.hostname:
        error('app-base-url', 'APP_BASE_URL must be an absolute HTTPS production URL.')
    elif parsed_base_url.hostname not in hosts:
        error('app-base-url-host', 'APP_BASE_URL host must also appear in ALLOWED_HOSTS.')

    for setting_name, message in (
        ('SECURE_SSL_REDIRECT', 'SECURE_SSL_REDIRECT must be enabled.'),
        ('SESSION_COOKIE_SECURE', 'SESSION_COOKIE_SECURE must be enabled.'),
        ('CSRF_COOKIE_SECURE', 'CSRF_COOKIE_SECURE must be enabled.'),
    ):
        if not getattr(settings, setting_name):
            error(setting_name.lower(), message)
    if settings.SECURE_HSTS_SECONDS < 31536000:
        error('hsts', 'SECURE_HSTS_SECONDS must be at least 31536000 (one year).')
    if not settings.SECURE_HSTS_PRELOAD:
        error('hsts-preload', 'SECURE_HSTS_PRELOAD must be enabled for the HTTPS-only production domain.')
    if settings.SECURE_PROXY_SSL_HEADER != ('HTTP_X_FORWARDED_PROTO', 'https'):
        error('proxy-ssl', 'SECURE_PROXY_SSL_HEADER must trust Render HTTPS proxy headers.')

    for setting_name in ('TELEGRAM_BOT_TOKEN', 'TELEGRAM_WEBHOOK_SECRET', 'API_AUTH_TOKEN'):
        if _blank_or_placeholder(getattr(settings, setting_name, '')):
            error(setting_name.lower(), f'{setting_name} must be configured with a real secret.')

    service_account_path = Path(settings.GOOGLE_SERVICE_ACCOUNT_FILE)
    if not service_account_path.is_file():
        error('google-service-account', 'GOOGLE_SERVICE_ACCOUNT_FILE must exist in the deployed environment.')
    if settings.MEDIA_STORAGE_PROVIDER == 'google_drive' and _blank_or_placeholder(
        settings.GOOGLE_DRIVE_MEDIA_FOLDER_ID
    ):
        error('google-drive-folder', 'GOOGLE_DRIVE_MEDIA_FOLDER_ID is required when media uses Google Drive.')

    if not settings.SENTRY_DSN:
        warning('error-monitoring', 'Configure SENTRY_DSN for production error alerting.')
    elif _blank_or_placeholder(settings.SENTRY_DSN):
        error('sentry-dsn', 'SENTRY_DSN is configured with a placeholder value.')
    else:
        try:
            import sentry_sdk  # noqa: F401
        except ImportError:
            error('sentry-sdk', 'SENTRY_DSN is configured but sentry-sdk is not installed.')

    return issues
