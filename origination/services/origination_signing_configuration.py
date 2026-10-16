"""One secret-free configuration verdict shared by deployment and OTP runtime."""
from core.production import _blank_or_placeholder


def provider_configuration_issues(settings, *, provider=None) -> list[tuple[str, str]]:
    from origination.services.origination_sms import ADVANTA, AFRICAS_TALKING, selected_provider
    provider = selected_provider(settings) if provider is None else provider
    if provider == ADVANTA:
        return [(f'origination-esign-advanta-{suffix}', f'Configure {name} for Advanta signing delivery.')
                for suffix, name in (('partner', 'ORIGINATION_ADVANTA_PARTNER_ID'),
                                     ('api-key', 'ORIGINATION_ADVANTA_API_KEY'),
                                     ('sender', 'ORIGINATION_ADVANTA_SENDER_ID'))
                if _blank_or_placeholder(getattr(settings, name, ''))]
    if provider != AFRICAS_TALKING:
        return [('origination-esign-provider',
                 'Set ORIGINATION_SMS_PROVIDER to africas_talking or advanta for new signing links.')]
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


def signing_available(settings, *, provider=None) -> bool:
    return bool(getattr(settings, 'ORIGINATION_ESIGN_ENABLED', False)) and not provider_configuration_issues(settings, provider=provider)
