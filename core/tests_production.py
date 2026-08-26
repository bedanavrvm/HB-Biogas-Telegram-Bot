"""Tests for production-release safeguards that do not contact external services."""

from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from django.core.management import call_command
from django.test import SimpleTestCase, override_settings

from core.production import production_readiness_issues
from core.sentry_monitoring import scrub_event, scrub_transaction, sentry_init_options


class ProductionReadinessTests(SimpleTestCase):
    def _settings(self, service_account_file, **overrides):
        values = {
            'DEBUG': False,
            'SECRET_KEY': 'a' * 50,
            'DATABASES': {'default': {'ENGINE': 'django.db.backends.postgresql', 'CONN_MAX_AGE': 600}},
            'ALLOWED_HOSTS': ['app.example.test'],
            'APP_BASE_URL': 'https://app.example.test',
            'ORIGINATION_SIGNING_BASE_URL': '',
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

    def test_optional_origination_signing_origin_requires_https_and_allowed_host(self):
        insecure = production_readiness_issues(self._settings(
            '/missing/service-account.json',
            ORIGINATION_SIGNING_BASE_URL='http://sign.example.test',
        ))
        wrong_host = production_readiness_issues(self._settings(
            '/missing/service-account.json',
            ORIGINATION_SIGNING_BASE_URL='https://sign.example.test',
        ))
        allowed = production_readiness_issues(self._settings(
            '/missing/service-account.json',
            ALLOWED_HOSTS=['app.example.test', 'sign.example.test'],
            ORIGINATION_SIGNING_BASE_URL='https://sign.example.test',
        ))

        self.assertTrue(any(item.code == 'origination-signing-base-url' for item in insecure))
        self.assertTrue(any(item.code == 'origination-signing-base-url-host' for item in wrong_host))
        self.assertFalse(any(item.code.startswith('origination-signing-base-url') for item in allowed))

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

    def test_sentry_event_scrubbing_preserves_only_safe_request_context(self):
        cleaned = scrub_event({
            'request': {
                'method': 'post',
                'url': 'https://portal.example.test/api/portal/?national_id=12345678#ignored',
                'headers': {'X-Telegram-Init-Data': 'signed-secret'},
                'data': {'customer_name': 'Customer Name'},
                'cookies': {'sessionid': 'secret'},
            },
            'user': {'id': 'telegram-user'},
            'extra': {'invoice_amount': '50000'},
            'breadcrumbs': {'values': [{'message': 'Customer Name'}]},
            'message': 'National ID 12345678 failed validation',
            'exception': {'values': [{'type': 'ValueError', 'value': 'Customer Name: 12345678'}]},
        })

        self.assertEqual(cleaned['request'], {
            'method': 'POST',
            'url': 'https://portal.example.test/api/portal/',
        })
        self.assertNotIn('user', cleaned)
        self.assertNotIn('extra', cleaned)
        self.assertNotIn('breadcrumbs', cleaned)
        self.assertNotIn('message', cleaned)
        self.assertEqual(cleaned['exception'], {'values': [{'type': 'ValueError'}]})

    def test_sentry_options_keep_release_metadata_without_enabling_pii(self):
        configured = self._settings(
            '/tmp/service-account.json',
            SENTRY_DSN='https://public@example.ingest.sentry.io/123',
            SENTRY_ENVIRONMENT='production',
            SENTRY_TRACES_SAMPLE_RATE=0.0,
            APP_RELEASE='33df0bc',
        )

        options = sentry_init_options(configured)

        self.assertEqual(options['release'], '33df0bc')
        self.assertFalse(options['send_default_pii'])
        self.assertEqual(options['traces_sample_rate'], 0.0)
        self.assertIs(options['before_send'], scrub_event)
        self.assertIs(options['before_send_transaction'], scrub_transaction)

    def test_sentry_transaction_keeps_only_safe_trace_and_request_correlation(self):
        cleaned = scrub_transaction({
            'transaction': '/api/portal/farmers/customer-id/',
            'request': {
                'method': 'get',
                'url': 'https://portal.example.test/api/portal/farmers/customer-id/?national_id=123',
                'headers': {
                    'X-Request-ID': 'request-12345678',
                    'X-Telegram-Init-Data': 'signed-secret',
                },
            },
            'spans': [{
                'span_id': 'abc', 'trace_id': 'trace', 'op': 'http.client',
                'description': '/api/portal/farmers/customer-id/',
                'data': {'http.request.body': 'customer data'},
            }],
        })

        self.assertEqual(cleaned['transaction'], 'miniapp.portal')
        self.assertEqual(cleaned['tags'], {
            'request_id': 'request-12345678', 'miniapp_surface': 'portal',
        })
        self.assertEqual(cleaned['spans'], [{
            'span_id': 'abc', 'trace_id': 'trace', 'op': 'http.client',
        }])
        self.assertNotIn('headers', cleaned['request'])
