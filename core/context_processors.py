"""Small global template configuration surfaces."""

from django.conf import settings


def miniapp_diagnostics(request):
    """Expose only public/non-sensitive browser monitoring configuration."""
    return {
        'miniapp_diagnostics_enabled': bool(settings.MINIAPP_DIAGNOSTICS_ENABLED),
        'miniapp_diagnostics_heartbeat_seconds': int(settings.MINIAPP_DIAGNOSTICS_HEARTBEAT_SECONDS),
        'miniapp_sentry_browser_dsn': settings.SENTRY_BROWSER_DSN,
        'miniapp_sentry_environment': settings.SENTRY_ENVIRONMENT,
        'miniapp_sentry_release': settings.APP_RELEASE,
        'miniapp_sentry_traces_sample_rate': float(settings.SENTRY_BROWSER_TRACES_SAMPLE_RATE),
    }
