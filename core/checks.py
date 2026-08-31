"""Deployment checks for security-critical Mini App settings."""

from django.conf import settings
from django.core.checks import Error, Tags, register

from core.production import production_security_readiness_issues


_CHECK_IDS = {
    'miniapp-auth-portal': 'core.E001',
    'miniapp-auth-complaint-cases': 'core.E002',
    'miniapp-auth-tat-tracker': 'core.E003',
    'miniapp-auth-spin': 'core.E004',
    'miniapp-auth-order-approval': 'core.E005',
    'telegram-auth-age-shared': 'core.E006',
    'telegram-auth-age-portal': 'core.E007',
    'telegram-auth-age-complaint-cases': 'core.E008',
    'telegram-auth-age-tat-tracker': 'core.E009',
    'telegram-auth-age-spin': 'core.E010',
    'telegram-auth-age-order-approval': 'core.E011',
    'telegram-webhook-secret': 'core.E012',
    'tat-esignatures-base-url': 'core.E013',
    'tat-esignatures-api-key': 'core.E014',
    'tat-esignatures-webhook-secret': 'core.E015',
    'origination-esign-environment': 'core.E016',
    'origination-esign-username': 'core.E017',
    'origination-esign-api-key': 'core.E018',
    'conditional-approval-esign': 'core.E019',
    'access-grant-governance': 'core.E020',
    'origination-esign-application-environment': 'core.E021',
    'miniapp-idempotency-strict-mode': 'core.E022',
    'miniapp-idempotency-observation-window': 'core.E023',
    'public-rate-limit-window': 'core.E024',
    'public-rate-limit-staff-activation': 'core.E025',
    'public-rate-limit-telegram-session-login': 'core.E026',
    'public-rate-limit-signing-token': 'core.E027',
    'public-rate-limit-miniapp-diagnostics': 'core.E028',
    'public-rate-limit-manual-api-auth-failure': 'core.E029',
}


def _django_errors(codes: set[str]) -> list[Error]:
    return [
        Error(issue.message, id=_CHECK_IDS[issue.code])
        for issue in production_security_readiness_issues(settings)
        if issue.code in codes
    ]


@register(Tags.security, deploy=True)
def portal_authentication_check(app_configs, **kwargs):
    """Keep the historical callable while checking every Mini App auth gate."""
    if settings.DEBUG:
        return []
    return _django_errors({
        code for code in _CHECK_IDS
        if code.startswith('miniapp-auth-') or code.startswith('telegram-auth-age-')
    })


@register(Tags.security, deploy=True)
def production_security_configuration_check(app_configs, **kwargs):
    if settings.DEBUG:
        return []
    return _django_errors({
        code for code in _CHECK_IDS
        if not code.startswith('miniapp-auth-') and not code.startswith('telegram-auth-age-')
    })
