"""One secret-free configuration verdict shared by deployment and OTP runtime."""
from core.production import _blank_or_placeholder


def provider_configuration_issues(settings) -> list[tuple[str, str]]:
    issues = []
    environment = str(getattr(settings, 'AFRICASTALKING_SMS_ENVIRONMENT', '') or '').strip().casefold()
    username = str(getattr(settings, 'AFRICASTALKING_USERNAME', '') or '').strip()
    if environment not in {'sandbox', 'production'}:
        issues.append(('origination-esign-environment',
                       'Set AFRICASTALKING_SMS_ENVIRONMENT to sandbox or production to enable OTP delivery.'))
    if _blank_or_placeholder(username) or (
        environment == 'sandbox' and username != 'sandbox'
    ) or (environment == 'production' and username.casefold() == 'sandbox'):
        issues.append(('origination-esign-username',
                       'Configure the Africa\'s Talking username for the selected SMS environment.'))
    if _blank_or_placeholder(getattr(settings, 'AFRICASTALKING_API_KEY', '')):
        issues.append(('origination-esign-api-key',
                       'Configure AFRICASTALKING_API_KEY to enable OTP delivery.'))
    return issues


def signing_available(settings) -> bool:
    return bool(getattr(settings, 'ORIGINATION_ESIGN_ENABLED', False)) and not provider_configuration_issues(settings)
