"""Deployment checks for security-critical Mini App settings."""

from django.conf import settings
from django.core.checks import Error, Tags, register


@register(Tags.security, deploy=True)
def portal_authentication_check(app_configs, **kwargs):
    if not settings.DEBUG and not getattr(settings, 'PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH', True):
        return [Error(
            'Portal Telegram authentication is disabled outside DEBUG mode.',
            hint='Set PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True before deployment.',
            id='core.E001',
        )]
    return []
