from django.apps import AppConfig


class StaffAuthConfig(AppConfig):
    name = 'staff_auth'
    verbose_name = 'Staff browser authentication'

    def ready(self):
        from . import checks, signals  # noqa: F401
