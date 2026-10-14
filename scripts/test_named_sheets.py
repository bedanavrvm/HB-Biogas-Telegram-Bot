"""Isolated local acceptance run; providers disabled, no live database allowed."""
import os
import sys
from pathlib import Path

TEST_LABELS = sys.argv[1:]
CHECK_ONLY = '--check-only' in TEST_LABELS
if CHECK_ONLY:
    TEST_LABELS.remove('--check-only')
FRESH_DATABASE = '--fresh-database' in TEST_LABELS
if FRESH_DATABASE:
    TEST_LABELS.remove('--fresh-database')
sys.argv = [sys.argv[0], 'test', *TEST_LABELS]

ROOT = Path(os.environ.get('NAMED_SHEET_TEST_ROOT') or Path(__file__).resolve().parents[1]).resolve()
sys.path.insert(0, str(ROOT))
local_database = os.environ.get('NAMED_SHEET_TEST_DATABASE_URL', 'sqlite:///:memory:')
if local_database != 'sqlite:///:memory:':
    from urllib.parse import urlsplit
    parsed = urlsplit(local_database)
    if parsed.hostname != '127.0.0.1' or parsed.port != 55462 or parsed.path != '/named_tat_columns':
        raise SystemExit('Only the task-owned local PostgreSQL test database is allowed.')
os.environ['DATABASE_URL'] = local_database
os.environ['DJANGO_SETTINGS_MODULE'] = 'config.settings'
os.environ['DJANGO_SECRET_KEY'] = 'local-named-column-acceptance-only-' + '0' * 32
os.environ['SENTRY_DSN'] = ''
os.environ['SENTRY_BROWSER_DSN'] = ''
os.environ['REPORT_EMAIL_DELIVERY_ENABLED'] = 'False'
os.environ['CREDIT_ASSESSMENT_GMAIL_ENABLED'] = 'False'
os.environ['SECURE_SSL_REDIRECT'] = 'False'
os.environ['DEBUG'] = 'True'
os.environ['TELEGRAM_BOT_TOKEN'] = ''
os.environ['GOOGLE_SHEET_ID'] = ''
os.environ['GOOGLE_SERVICE_ACCOUNT_FILE'] = str(ROOT / 'test-results' / 'no-provider-credentials.json')
os.environ['GROUP_MAPPING_JSON'] = '{}'

import django
from django.conf import settings

settings.DATABASES['default']['TEST'] = {'NAME': (
    str(ROOT / 'test-results' / 'named-columns-tests.sqlite3') if local_database.startswith('sqlite:')
    else 'test_named_tat_columns'
)}
settings.SILENCED_SYSTEM_CHECKS = ['fields.W163', 'models.W046']
settings.SECURE_SSL_REDIRECT = False
django.setup()
import logging
logging.getLogger().setLevel(logging.WARNING)
for logger in [logging.getLogger(), *[item for item in logging.Logger.manager.loggerDict.values()
                                     if isinstance(item, logging.Logger)]]:
    for handler in logger.handlers:
        handler.setLevel(logging.WARNING)
from django.core.management import call_command

if CHECK_ONLY:
    call_command('check')
    call_command('makemigrations', check=True, dry_run=True, interactive=False)
else:
    call_command('test', *(TEST_LABELS or ['core.tests_sheet_columns']), keepdb=not FRESH_DATABASE, interactive=False, verbosity=1)
