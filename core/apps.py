from django.apps import AppConfig
from django.conf import settings


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'
    verbose_name = getattr(settings, 'APP_DISPLAY_NAME', 'Telegram Workflow Bot')

    def ready(self):
        from core.compat import patch_django_template_context_copy
        from core import signals  # noqa: F401
        from core import checks  # noqa: F401

        patch_django_template_context_copy()

        if not settings.SENTRY_DSN:
            return

        try:
            import sentry_sdk
            from sentry_sdk.integrations.django import DjangoIntegration
            from core.sentry_monitoring import sentry_init_options
        except ImportError:
            # Production readiness checks surface a configured DSN without its
            # dependency.  Do not make local commands unusable because an
            # optional monitoring integration was omitted.
            return

        sentry_sdk.init(
            integrations=[DjangoIntegration()],
            **sentry_init_options(settings),
        )
