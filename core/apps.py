from django.apps import AppConfig
from django.conf import settings


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'
    verbose_name = getattr(settings, 'APP_DISPLAY_NAME', 'Telegram Workflow Bot')

    def ready(self):
        from core.compat import patch_django_template_context_copy

        patch_django_template_context_copy()
