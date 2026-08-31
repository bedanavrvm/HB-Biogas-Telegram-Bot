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

MINIAPP_AUTH_SETTINGS = (
    ('portal', 'PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH'),
    ('complaint-cases', 'COMPLAINT_CASES_WEBAPP_REQUIRE_TELEGRAM_AUTH'),
    ('tat-tracker', 'TAT_TRACKER_WEBAPP_REQUIRE_TELEGRAM_AUTH'),
    ('spin', 'SPIN_WEBAPP_REQUIRE_TELEGRAM_AUTH'),
    ('order-approval', 'ORDER_APPROVAL_WEBAPP_REQUIRE_TELEGRAM_AUTH'),
)

TELEGRAM_AUTH_AGE_SETTINGS = (
    ('shared', 'TELEGRAM_AUTH_MAX_AGE_SECONDS'),
    ('portal', 'PORTAL_WEBAPP_AUTH_MAX_AGE_SECONDS'),
    ('complaint-cases', 'COMPLAINT_CASES_WEBAPP_AUTH_MAX_AGE_SECONDS'),
    ('tat-tracker', 'TAT_TRACKER_WEBAPP_AUTH_MAX_AGE_SECONDS'),
    ('spin', 'SPIN_WEBAPP_AUTH_MAX_AGE_SECONDS'),
    ('order-approval', 'ORDER_APPROVAL_WEBAPP_AUTH_MAX_AGE_SECONDS'),
)


@dataclass(frozen=True)
class ReadinessIssue:
    severity: str
    code: str
    message: str


def _blank_or_placeholder(value: object) -> bool:
    text = str(value or '').strip().lower()
    return not text or any(marker in text for marker in PLACEHOLDER_MARKERS)


def production_security_readiness_issues(
    settings,
    *,
    check_database: bool = False,
) -> list[ReadinessIssue]:
    """Return fail-closed Mini App and signing configuration issues."""
    from core.services.telegram_identity import TELEGRAM_AUTH_MAX_AGE_LIMIT_SECONDS

    issues: list[ReadinessIssue] = []

    def error(code: str, message: str) -> None:
        issues.append(ReadinessIssue('error', code, message))

    for surface, setting_name in MINIAPP_AUTH_SETTINGS:
        if not bool(getattr(settings, setting_name, False)):
            error(
                f'miniapp-auth-{surface}',
                f'{setting_name} must be enabled in production.',
            )

    for surface, setting_name in TELEGRAM_AUTH_AGE_SETTINGS:
        raw_value = getattr(settings, setting_name, None)
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            value = 0
        if value <= 0 or value > TELEGRAM_AUTH_MAX_AGE_LIMIT_SECONDS:
            error(
                f'telegram-auth-age-{surface}',
                f'{setting_name} must be between 1 and '
                f'{TELEGRAM_AUTH_MAX_AGE_LIMIT_SECONDS} seconds.',
            )

    if _blank_or_placeholder(getattr(settings, 'TELEGRAM_WEBHOOK_SECRET', '')):
        error('telegram-webhook-secret', 'TELEGRAM_WEBHOOK_SECRET must be configured with a real secret.')

    if bool(getattr(settings, 'TAT_TRACKER_SIGNATURES_ENABLED', False)):
        base_url = str(getattr(settings, 'ESIGNATURES_BASE_URL', '') or '').strip()
        parsed_url = urlparse(base_url)
        if (
            _blank_or_placeholder(base_url)
            or parsed_url.scheme != 'https'
            or not parsed_url.hostname
        ):
            error(
                'tat-esignatures-base-url',
                'ESIGNATURES_BASE_URL must be an absolute HTTPS URL when TAT signatures are enabled.',
            )
        for code, setting_name in (
            ('tat-esignatures-api-key', 'ESIGNATURES_API_KEY'),
            ('tat-esignatures-webhook-secret', 'ESIGNATURES_WEBHOOK_SECRET'),
        ):
            if _blank_or_placeholder(getattr(settings, setting_name, '')):
                error(code, f'{setting_name} must be configured when TAT signatures are enabled.')

    origination_esign_enabled = bool(
        getattr(settings, 'ORIGINATION_ESIGN_ENABLED', False)
    )
    if origination_esign_enabled:
        provider_environment = str(
            getattr(settings, 'AFRICASTALKING_SMS_ENVIRONMENT', '') or ''
        ).strip().casefold()
        application_environment = str(
            getattr(settings, 'SENTRY_ENVIRONMENT', '') or ''
        ).strip().casefold()
        username = str(getattr(settings, 'AFRICASTALKING_USERNAME', '') or '').strip()
        if application_environment != 'production':
            error(
                'origination-esign-application-environment',
                'SENTRY_ENVIRONMENT must be production when Origination e-signing is enabled in production.',
            )
        if provider_environment != 'production':
            error(
                'origination-esign-environment',
                'AFRICASTALKING_SMS_ENVIRONMENT must be production when Origination e-signing is enabled in production.',
            )
        if _blank_or_placeholder(username) or username.casefold() == 'sandbox':
            error(
                'origination-esign-username',
                'AFRICASTALKING_USERNAME must be a production account when Origination e-signing is enabled.',
            )
        if _blank_or_placeholder(getattr(settings, 'AFRICASTALKING_API_KEY', '')):
            error(
                'origination-esign-api-key',
                'AFRICASTALKING_API_KEY must be configured when Origination e-signing is enabled.',
            )

    conditional_enabled = bool(
        getattr(settings, 'ORIGINATION_CONDITIONAL_APPROVAL_ENABLED', False)
    )
    if conditional_enabled and not origination_esign_enabled:
        error(
            'conditional-approval-esign',
            'ORIGINATION_ESIGN_ENABLED must be enabled before conditional approval.',
        )
    if conditional_enabled and check_database:
        try:
            from django.db import OperationalError, ProgrammingError
            from core.models import OriginationConsentPolicyVersion

            policy = OriginationConsentPolicyVersion.objects.filter(
                status=OriginationConsentPolicyVersion.STATUS_ACTIVE,
            ).first()
            if policy is None:
                error(
                    'conditional-approval-consent-policy',
                    'Publish one active compliance-approved Origination consent policy before enabling conditional approval.',
                )
            else:
                if not (
                    str(policy.approval_reference or '').strip()
                    and policy.approved_by_id
                    and policy.approved_at
                ):
                    error(
                        'conditional-approval-consent-approval',
                        'The active Origination consent policy is missing compliance approval evidence.',
                    )
                if policy.content_sha256 != policy._content_hash():
                    error(
                        'conditional-approval-consent-integrity',
                        'The active Origination consent policy failed its integrity check.',
                    )
        except (OperationalError, ProgrammingError):
            error(
                'conditional-approval-consent-readiness',
                'The Origination consent-policy register could not be checked.',
            )

    if not bool(getattr(settings, 'ACCESS_GRANT_GOVERNANCE_ENFORCED', False)):
        error(
            'access-grant-governance',
            'ACCESS_GRANT_GOVERNANCE_ENFORCED must be enabled in production.',
        )
    return issues


def production_readiness_issues(settings, *, check_database: bool = False) -> list[ReadinessIssue]:
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

    signing_base_url = str(getattr(settings, 'ORIGINATION_SIGNING_BASE_URL', '') or '').strip()
    if signing_base_url:
        parsed_signing_url = urlparse(signing_base_url)
        if (
            parsed_signing_url.scheme != 'https' or not parsed_signing_url.hostname
            or parsed_signing_url.path not in {'', '/'}
            or parsed_signing_url.query or parsed_signing_url.fragment
        ):
            error(
                'origination-signing-base-url',
                'ORIGINATION_SIGNING_BASE_URL must be an absolute HTTPS origin without a path, query, or fragment.',
            )
        elif parsed_signing_url.hostname not in hosts:
            error(
                'origination-signing-base-url-host',
                'ORIGINATION_SIGNING_BASE_URL host must also appear in ALLOWED_HOSTS.',
            )

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

    for setting_name in ('TELEGRAM_BOT_TOKEN', 'API_AUTH_TOKEN'):
        if _blank_or_placeholder(getattr(settings, setting_name, '')):
            error(setting_name.lower(), f'{setting_name} must be configured with a real secret.')

    issues.extend(production_security_readiness_issues(
        settings,
        check_database=check_database,
    ))

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
