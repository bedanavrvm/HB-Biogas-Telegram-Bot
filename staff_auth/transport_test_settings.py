"""Opt-in local full-schema tests; never use for a running application."""
import os
import sys

if 'test' not in sys.argv or os.environ.get('RUN_STAFF_BROWSER_E2E') != '1':
    raise RuntimeError('These settings are restricted to the explicit transport test runner.')

from config.settings import *  # noqa: F403

# Full checked-in migrations on an isolated, reusable test database. This never
# opens db.sqlite3 or uses a DATABASE_URL from deployment configuration.
test_directory = BASE_DIR / 'test-results'  # noqa: F405
test_directory.mkdir(exist_ok=True)
DATABASES = {'default': {
    'ENGINE': 'django.db.backends.sqlite3', 'NAME': ':memory:',
    'TEST': {'NAME': str(test_directory / 'staff-browser-transport.sqlite3')},
}}
TEST_RUNNER = 'staff_auth.transport_test_runner.ClosedTransportRunner'
