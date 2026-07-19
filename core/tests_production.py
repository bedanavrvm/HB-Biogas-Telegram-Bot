"""Tests for production-release safeguards that do not contact external services."""

from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from django.core.management import call_command
from django.test import SimpleTestCase, override_settings

from core.production import production_readiness_issues


class ProductionReadinessTests(SimpleTestCase):
    def _settings(self, service_account_file, **overrides):
        values = {
            'DEBUG': False,
            'SECRET_KEY': 'a' * 50,
            'DATABASES': {'default': {'ENGINE': 'django.db.backends.postgresql', 'CONN_MAX_AGE': 600}},
            'ALLOWED_HOSTS': ['app.example.test'],
            'APP_BASE_URL': 'https://app.example.test',
            'SECURE_SSL_REDIRECT': True,
            'SESSION_COOKIE_SECURE': True,
            'CSRF_COOKIE_SECURE': True,
            'SECURE_HSTS_SECONDS': 31536000,
            'SECURE_HSTS_PRELOAD': True,
            'SECURE_PROXY_SSL_HEADER': ('HTTP_X_FORWARDED_PROTO', 'https'),
            'TELEGRAM_BOT_TOKEN': '12345678:' + ('a' * 35),
            'TELEGRAM_WEBHOOK_SECRET': 'webhook-secret',
            'API_AUTH_TOKEN': 'manual-api-secret',
            'GOOGLE_SERVICE_ACCOUNT_FILE': str(service_account_file),
            'MEDIA_STORAGE_PROVIDER': 'google_drive',
            'GOOGLE_DRIVE_MEDIA_FOLDER_ID': 'drive-folder-id',
            'SENTRY_DSN': '',
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_valid_production_settings_only_warn_when_monitoring_is_not_configured(self):
        with TemporaryDirectory() as directory:
            credentials = Path(directory) / 'service-account.json'
            credentials.write_text('{}', encoding='utf-8')

            issues = production_readiness_issues(self._settings(credentials))

        self.assertEqual([(issue.severity, issue.code) for issue in issues], [('warning', 'error-monitoring')])

    def test_insecure_or_placeholder_settings_are_reported_as_errors(self):
        issues = production_readiness_issues(
            self._settings(
                '/missing/service-account.json',
                DEBUG=True,
                SECRET_KEY='django-inchange-me-in-production',
                DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'CONN_MAX_AGE': 0}},
                ALLOWED_HOSTS=['*'],
                APP_BASE_URL='http://example.com',
                SECURE_SSL_REDIRECT=False,
                SESSION_COOKIE_SECURE=False,
                CSRF_COOKIE_SECURE=False,
                SECURE_HSTS_SECONDS=0,
                SECURE_HSTS_PRELOAD=False,
                TELEGRAM_BOT_TOKEN='',
                TELEGRAM_WEBHOOK_SECRET='',
                API_AUTH_TOKEN='',
                GOOGLE_DRIVE_MEDIA_FOLDER_ID='',
            )
        )

        self.assertTrue(any(issue.code == 'debug-enabled' for issue in issues))
        self.assertTrue(any(issue.code == 'database-engine' for issue in issues))
        self.assertTrue(any(issue.severity == 'error' for issue in issues))

    @override_settings(
        DEBUG=True,
        SECRET_KEY='test-secret',
        DATABASES={'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:'}},
        ALLOWED_HOSTS=['*'],
        APP_BASE_URL='',
        TELEGRAM_BOT_TOKEN='',
        TELEGRAM_WEBHOOK_SECRET='',
        API_AUTH_TOKEN='',
        GOOGLE_SERVICE_ACCOUNT_FILE='/missing/service-account.json',
        MEDIA_STORAGE_PROVIDER='google_drive',
        GOOGLE_DRIVE_MEDIA_FOLDER_ID='',
        SENTRY_DSN='',
        SECURE_SSL_REDIRECT=False,
        SESSION_COOKIE_SECURE=False,
        CSRF_COOKIE_SECURE=False,
        SECURE_HSTS_SECONDS=0,
        SECURE_HSTS_PRELOAD=False,
    )
    def test_management_command_fails_for_unsafe_configuration(self):
        with self.assertRaisesMessage(Exception, 'Production readiness checks failed.'):
            call_command('check_production_readiness', '--strict', stdout=StringIO())
