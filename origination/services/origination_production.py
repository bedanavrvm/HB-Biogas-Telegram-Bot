"""Read-only production readiness for enabled Origination e-signing."""

from core.production import production_security_readiness_issues
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder


_ORIGINATION_CODES = (
    'origination-esign-',
    'conditional-approval-',
)
_SMS_MIGRATIONS = (
    ('core', '0206_advanta_integration'),
    ('origination', '0009_signer_sms_provider'),
)


def origination_signing_readiness_issues(settings, *, allow_pending_migrations=False):
    """Defer new-schema reads only during the release's pre-migration phase."""
    if not bool(getattr(settings, 'ORIGINATION_ESIGN_ENABLED', False)):
        return []
    issues = [
        issue
        for issue in production_security_readiness_issues(settings, check_database=True)
        if issue.code.startswith(_ORIGINATION_CODES)
    ]
    from core.production import ReadinessIssue
    from django.db import DatabaseError
    from django.utils import timezone
    from origination.models import OriginationSignerSession
    from origination.services.origination_signing_configuration import provider_configuration_issues
    from origination.services.origination_sms import ADVANTA, selected_provider
    from origination.services.origination_sms_delivery import runner_health
    applied = None
    try:
        applied = MigrationRecorder(connection).applied_migrations()
        pending = [f'{app}.{name}' for app, name in _SMS_MIGRATIONS if (app, name) not in applied]
        if pending:
            if not allow_pending_migrations:
                issues.append(ReadinessIssue('error', 'origination-esign-delivery-schema',
                    'SMS database migrations are pending: ' + ', '.join(pending)
                    + '. Complete the normal release.sh pre-deploy process, then rerun check_origination_signing_readiness.'))
            return issues
        active_providers = set(OriginationSignerSession.objects.filter(
            is_active=True, token_expires_at__gt=timezone.now(),
        ).values_list('sms_provider', flat=True).distinct())
        for provider in active_providers - {selected_provider(settings)}:
            if provider_configuration_issues(settings, provider=provider):
                issues.append(ReadinessIssue('warning', 'origination-esign-existing-provider',
                    'An existing signing link still needs its original SMS provider credentials. Keep them until the links expire or are replaced.'))
        health = runner_health()
        if selected_provider(settings) == ADVANTA or ADVANTA in active_providers or health['due_lookups']:
            if not health['fresh'] or health['status'] == 'failed':
                issues.append(ReadinessIssue('warning', 'origination-esign-delivery-runner',
                    'Schedule process_origination_deliveries --apply once per minute. Delivery tracking is stale; OTP verification remains available.'))
        if health['account_changed']:
            issues.append(ReadinessIssue('warning', 'origination-esign-provider-account-changed',
                'Delivery tracking found a changed SMS account. Review the original account in the SMS delivery runbook; do not resend the application.'))
    except DatabaseError:
        detail = ('SMS migrations are recorded as applied. Check database connectivity, permissions and schema consistency.'
                  if applied is not None else
                  'The migration register could not be read. Check DATABASE_URL, database connectivity and permissions.')
        issues.append(ReadinessIssue('error', 'origination-esign-delivery-database',
            'Could not check the SMS delivery database. ' + detail
            + ' Retry check_origination_signing_readiness after resolving the database issue.'))
    return issues
