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

PUBLIC_RATE_LIMIT_SETTINGS = (
    ('staff-activation', 'STAFF_ACTIVATION_RATE_LIMIT'),
    ('telegram-session-login', 'TELEGRAM_SESSION_LOGIN_RATE_LIMIT'),
    ('signing-token', 'SIGNING_TOKEN_RATE_LIMIT'),
    ('miniapp-diagnostics', 'MINIAPP_DIAGNOSTICS_RATE_LIMIT'),
    ('manual-api-auth-failure', 'MANUAL_API_AUTH_FAILURE_RATE_LIMIT'),
)

NON_PRODUCTION_ENVIRONMENTS = frozenset({
    'development',
    'dev',
    'local',
    'test',
    'testing',
    'staging',
})


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

    def warning(code: str, message: str) -> None:
        issues.append(ReadinessIssue('warning', code, message))

    if not bool(getattr(settings, 'REQUIRE_MINIAPP_IDEMPOTENCY_KEY', False)):
        error(
            'miniapp-idempotency-strict-mode',
            'REQUIRE_MINIAPP_IDEMPOTENCY_KEY must be enabled in production.',
        )

    try:
        observation_days = int(
            getattr(settings, 'MINIAPP_IDEMPOTENCY_OBSERVATION_DAYS', 14)
        )
    except (TypeError, ValueError):
        observation_days = 0
    if observation_days <= 0 or observation_days > 90:
        error(
            'miniapp-idempotency-observation-window',
            'MINIAPP_IDEMPOTENCY_OBSERVATION_DAYS must be between 1 and 90.',
        )
    elif check_database:
        try:
            from django.db import OperationalError, ProgrammingError
            from core.services.miniapp_idempotency import recent_legacy_write_summary

            summary = recent_legacy_write_summary(observation_days=observation_days)
            legacy_count = summary['accepted'] + summary['rejected']
            if legacy_count:
                warning(
                    'miniapp-idempotency-legacy-observed',
                    f"Observed {legacy_count} legacy Mini App write attempt(s) across "
                    f"{summary['route_count']} route(s) in the last {observation_days} day(s).",
                )
        except (OperationalError, ProgrammingError):
            # The release command runs before migrations. The first deployment
            # that creates this aggregate must remain able to reach migrate;
            # strict transport enforcement is still checked above.
            pass

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

    try:
        throttle_window = int(getattr(settings, 'PUBLIC_RATE_LIMIT_WINDOW_SECONDS', 600))
    except (TypeError, ValueError):
        throttle_window = 0
    if throttle_window < 1 or throttle_window > 86400:
        error(
            'public-rate-limit-window',
            'PUBLIC_RATE_LIMIT_WINDOW_SECONDS must be between 1 and 86400.',
        )
    for surface, setting_name in PUBLIC_RATE_LIMIT_SETTINGS:
        try:
            value = int(getattr(settings, setting_name, 0))
        except (TypeError, ValueError):
            value = 0
        if value < 1 or value > 100000:
            error(
                f'public-rate-limit-{surface}',
                f'{setting_name} must be between 1 and 100000.',
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
        release_environment = str(
            getattr(settings, 'RELEASE_ENVIRONMENT', '') or ''
        ).strip().casefold()
        username = str(getattr(settings, 'AFRICASTALKING_USERNAME', '') or '').strip()
        sandbox_readiness = bool(
            application_environment in NON_PRODUCTION_ENVIRONMENTS
            and release_environment in NON_PRODUCTION_ENVIRONMENTS
            and provider_environment == 'sandbox'
        )
        if sandbox_readiness:
            if username.casefold() != 'sandbox':
                error(
                    'origination-esign-username',
                    'AFRICASTALKING_USERNAME must be sandbox for an explicitly non-production Sandbox release.',
                )
        else:
            if application_environment != 'production':
                error(
                    'origination-esign-application-environment',
                    'SENTRY_ENVIRONMENT must be production unless both application and release environments are explicitly non-production.',
                )
            if provider_environment != 'production':
                error(
                    'origination-esign-environment',
                    'AFRICASTALKING_SMS_ENVIRONMENT must be production unless an explicitly non-production release uses Sandbox.',
                )
            if _blank_or_placeholder(username) or username.casefold() == 'sandbox':
                error(
                    'origination-esign-username',
                    'AFRICASTALKING_USERNAME must be a production account unless an explicitly non-production release uses Sandbox.',
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

    try:
        lease_seconds = int(getattr(settings, 'DURABLE_JOB_LEASE_SECONDS', 300))
    except (TypeError, ValueError):
        lease_seconds = 0
    try:
        runner_silence = int(getattr(settings, 'DURABLE_JOB_RUNNER_MAX_SILENCE_SECONDS', 900))
    except (TypeError, ValueError):
        runner_silence = 0
    if lease_seconds < 30 or lease_seconds > 3600:
        error('durable-job-lease', 'DURABLE_JOB_LEASE_SECONDS must be between 30 and 3600 seconds.')
    if runner_silence < 60 or runner_silence > 86400:
        error(
            'durable-job-runner-silence',
            'DURABLE_JOB_RUNNER_MAX_SILENCE_SECONDS must be between 60 and 86400 seconds.',
        )
    for code, setting_name, default_value in (
        ('complaint-import-runner-limit', 'COMPLAINT_IMPORT_RUNNER_MAX_ITEMS', 10),
        ('tat-repair-runner-limit', 'TAT_REPAIR_RUNNER_MAX_CASES', 5),
    ):
        try:
            value = int(getattr(settings, setting_name, default_value))
        except (TypeError, ValueError):
            value = 0
        if value < 1 or value > 1000:
            error(code, f'{setting_name} must be between 1 and 1000.')

    if check_database:
        try:
            from django.db import OperationalError, ProgrammingError
            from core.services.durable_jobs import durable_job_health

            health = durable_job_health(max_silence_seconds=runner_silence or 900)
            for runner_key, required_setting in (
                ('complaint_imports', 'COMPLAINT_IMPORT_RUNNER_REQUIRED'),
                ('tat_repairs', 'TAT_REPAIR_RUNNER_REQUIRED'),
            ):
                required = bool(getattr(settings, required_setting, False))
                runner = health['runners'][runner_key]
                if required and not runner['fresh']:
                    error(
                        f'{runner_key.replace("_", "-")}-runner-stale',
                        f'{required_setting} is enabled but the scheduled runner has no fresh heartbeat.',
                    )
                elif required and runner.get('status') == 'failed':
                    error(
                        f'{runner_key.replace("_", "-")}-runner-failed',
                        f'{required_setting} is enabled but the latest scheduled runner invocation failed.',
                    )
            for job_key in ('complaint_imports', 'tat_repairs'):
                stalled = int(health[job_key]['stalled'])
                if stalled:
                    warning(
                        f'{job_key.replace("_", "-")}-jobs-stalled',
                        f'{stalled} stale {job_key.replace("_", " ")} job(s) are awaiting lease recovery.',
                    )
        except (OperationalError, ProgrammingError):
            if bool(getattr(settings, 'COMPLAINT_IMPORT_RUNNER_REQUIRED', False)) or bool(
                getattr(settings, 'TAT_REPAIR_RUNNER_REQUIRED', False)
            ):
                error(
                    'durable-job-runner-readiness',
                    'The durable runner heartbeat register could not be checked.',
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
