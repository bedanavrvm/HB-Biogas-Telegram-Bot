"""Read-only production readiness for enabled Origination e-signing."""

from core.production import production_security_readiness_issues


_ORIGINATION_CODES = (
    'origination-esign-',
    'conditional-approval-',
)


def origination_signing_readiness_issues(settings):
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
    try:
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
        issues.append(ReadinessIssue('warning', 'origination-esign-delivery-schema',
            'Apply the checked-in SMS migrations before checking existing-link delivery readiness.'))
    return issues
