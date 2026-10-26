"""Run Portal checks with synthetic settings and all network connections blocked.

Run with .venv/Scripts/python.exe scripts/portal_local_audit.py [Django test labels].
Evidence is retained under test-results/portal-local-audit-2026-10-26/.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'test-results' / 'portal-local-audit-2026-10-26'
DEFAULT_LABELS = [
    'core.tests_system_export', 'core.tests_sysup_review',
    'core.tests_portal_imports', 'core.tests_pipeline',
    'core.tests_portal_approval_controls', 'core.tests_portal_case_corrections',
    'core.tests_portal_decision_reasons', 'core.tests_portal_role_separation',
    'core.tests_portal_role_remediation', 'core.tests_portal_operations_policy',
    'core.tests_portal_dashboard', 'core.tests_portal_navigation',
    'core.tests_portal_hardening', 'core.tests_portal_engineering',
    'core.tests_portal_publication_scheduler', 'core.tests_reliability',
    'core.tests_requisition', 'requisitions', 'core.tests_payment_documents',
    'core.tests_invoice_identity', 'core.tests_invoice_name_change_letters',
    'core.tests_invoice_upload_policy', 'core.tests_invoice_concurrency',
    'core.tests_portal_payment_candidates', 'payments', 'hb_operations',
    'core.tests_portal_reporting', 'core.tests_portal_report_insights',
    'portal_recognition', 'report_delivery', 'core.tests_sheets_validation',
    'core.tests_jbl_visit_documents', 'core.tests_jawabu_data_quality',
    'core.tests_document_signoffs', 'core.tests_portal_full_reset',
    'core.tests_portal_voice', 'core.tests_template_storage',
    'core.tests_portal_audit_fixes',
    'core.tests_miniapp_messages',
    'core.tests_tat_tracker.TatTrackerWorkflowTest.test_create_endpoint_alerts_next_stage_role',
    'core.tests_tat_tracker.TatTrackerWorkflowTest.test_create_endpoint_returns_specific_invalid_bro_message',
]


def configure(database_name='audit.sqlite3'):
    sys.path.insert(0, str(ROOT))
    OUTPUT.mkdir(parents=True, exist_ok=True)
    # Ignore the checkout's .env entirely, including deployment credentials.
    import decouple
    decouple.config = decouple.Config(decouple.RepositoryEmpty())
    os.environ.update({
        'DJANGO_SETTINGS_MODULE': 'config.settings', 'DEBUG': 'true',
        'DJANGO_SECRET_KEY': 'synthetic-local-portal-audit-secret-never-for-deployment',
        'DATABASE_URL': 'sqlite:///' + (OUTPUT / database_name).as_posix(),
        'TELEGRAM_BOT_TOKEN': '', 'TELEGRAM_WEBHOOK_SECRET': '',
        'GOOGLE_SERVICE_ACCOUNT_FILE': str(OUTPUT / 'absent-credentials.json'),
        'GOOGLE_SHEET_ID': '', 'GOOGLE_DRIVE_MEDIA_FOLDER_ID': '',
        'GROUP_MAPPING': '{}', 'SENTRY_DSN': '',
        'MEDIA_STORAGE_PROVIDER': 'google_drive', 'SECURE_SSL_REDIRECT': 'false',
        'STAFF_BROWSER_AUTH_ENABLED': 'false',
        'STAFF_BROWSER_COMPLAINTS_ENABLED': 'false',
        'CREDIT_ASSESSMENT_GMAIL_ENABLED': 'false',
        'ACCESS_GRANT_GOVERNANCE_ENFORCED': 'false',
        'ORIGINATION_LAF_BOOTSTRAP_ENABLED': 'false',
    })
    def blocked(*args, **kwargs):
        raise OSError('Portal local audit blocks every network connection')
    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked
    socket.create_connection = blocked
    from django.conf import settings
    settings.MEDIA_ROOT = OUTPUT / 'storage'
    settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
    settings.CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}
    settings.ALLOWED_HOSTS = ['testserver', 'localhost', '127.0.0.1']
    settings.PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
    settings.RUNNING_TESTS = True
    settings.DATABASES['default']['TEST'] = {'NAME': str(OUTPUT / 'suite-verified.sqlite3')}
    import django
    django.setup()
    assert settings.DATABASES['default']['ENGINE'] == 'django.db.backends.sqlite3'
    assert Path(settings.DATABASES['default']['NAME']).resolve() == (OUTPUT / database_name).resolve()
    try:
        socket.create_connection(('example.invalid', 443))
    except OSError:
        pass
    else:
        raise AssertionError('Network guard is inactive')


def main():
    import sqlite3
    journey = sys.argv[1:] == ['--journey']
    database_name = f'journey-{time.time_ns()}.sqlite3' if journey else 'audit.sqlite3'
    if journey:
        baseline = OUTPUT / 'baseline.sqlite3'
        if not baseline.exists():
            raise SystemExit('Run --prepare before the connected journey.')
        with sqlite3.connect(baseline) as source, sqlite3.connect(OUTPUT / database_name) as target:
            assert source.execute('SELECT COUNT(*) FROM core_jawabufarmermaster').fetchone()[0] == 0
            source.backup(target)
    configure(database_name)
    if sys.argv[1:] == ['--prepare']:
        if (OUTPUT / 'baseline.sqlite3').exists():
            with sqlite3.connect(OUTPUT / 'baseline.sqlite3') as baseline:
                assert baseline.execute('SELECT COUNT(*) FROM core_jawabufarmermaster').fetchone()[0] == 0
            print('Reusing the migrated, customer-free local baseline.')
            return 0
        from django.core.management import call_command
        call_command('migrate', interactive=False, verbosity=1)
        with sqlite3.connect(OUTPUT / 'audit.sqlite3') as source, sqlite3.connect(OUTPUT / 'baseline.sqlite3') as target:
            source.backup(target)
        return 0
    if sys.argv[1:] == ['--journey']:
        from portal_local_journey import run
        return run(OUTPUT)
    from django.test.runner import DiscoverRunner
    if (OUTPUT / 'baseline.sqlite3').exists():
        with sqlite3.connect(OUTPUT / 'baseline.sqlite3') as source, sqlite3.connect(OUTPUT / 'suite-verified.sqlite3') as target:
            source.backup(target)
    labels = list(dict.fromkeys(sys.argv[1:] or DEFAULT_LABELS))
    started = time.monotonic()
    class EvidenceRunner(DiscoverRunner):
        def run_suite(self, suite, **kwargs):
            result = super().run_suite(suite, **kwargs)
            self.audit_result = result
            return result
    runner = EvidenceRunner(verbosity=2, interactive=False, keepdb=True)
    failures = runner.run_tests(labels)
    summary = {'labels': labels, 'failure_count': failures,
               'tests_run': runner.audit_result.testsRun,
               'failures': [{'test': test.id(), 'traceback': trace} for test, trace in runner.audit_result.failures],
               'errors': [{'test': test.id(), 'traceback': trace} for test, trace in runner.audit_result.errors],
               'skipped': [{'test': test.id(), 'reason': reason} for test, reason in runner.audit_result.skipped],
               'elapsed_seconds': round(time.monotonic() - started, 2),
               'database': 'local SQLite', 'network': 'blocked', '.env': 'ignored'}
    summary_name = 'focused-suite-summary.json' if sys.argv[1:] else 'suite-summary.json'
    (OUTPUT / summary_name).write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in summary.items() if key not in ('failures', 'errors', 'skipped')}))
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
