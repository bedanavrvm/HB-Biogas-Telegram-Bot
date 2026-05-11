from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'
    verbose_name = 'Biogas Telegram Bot'

    def ready(self):
        from core.compat import patch_django_template_context_copy

        patch_django_template_context_copy()
