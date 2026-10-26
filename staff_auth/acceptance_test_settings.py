"""Explicit local PostgreSQL acceptance profile; never a deployment profile."""
import os
import sys

if 'test' not in sys.argv or os.environ.get('RUN_STAFF_BROWSER_E2E') != '1':
    raise RuntimeError('Use the explicit isolated browser acceptance test runner.')

from config.settings_test_postgres import *  # noqa: F403

DATABASES['default']['TEST'] = {'NAME': 'test_browser_acceptance'}  # noqa: F405
TEST_RUNNER = 'staff_auth.transport_test_runner.ClosedTransportRunner'
# No accidental provider calls, even when a developer has delivery credentials.
REPORT_EMAIL_DELIVERY_ENABLED = False
RESEND_API_KEY = ''
REPORT_EMAIL_FROM = ''
EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
CACHES = {'default': {'BACKEND':'staff_auth.security_cache.PostgresSecurityCache',
                      'KEY_FUNCTION':'staff_auth.cache_keys.native_cache_key'}}
