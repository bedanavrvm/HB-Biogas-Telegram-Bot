"""Playwright against the actual authenticated Django importer and database."""
import json
import os
from pathlib import Path
import subprocess
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest import skipUnless

import requests

from django.conf import settings
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import LiveServerTestCase, override_settings
from django.db import connection
from django.urls import reverse

from core.models import JawabuFarmerMaster
from core.tests_telegram_authentication import BOT_TOKEN
from portal_legacy.models import LegacyRow
from portal_legacy.tests import LegacyHTTPMixin
from portal_legacy.test_support import workbook_bytes


@override_settings(TELEGRAM_BOT_TOKEN=BOT_TOKEN, PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True,
                   SECURE_SSL_REDIRECT=False, MINIAPP_TEST_DELETION_ENABLED=True,
                   REQUIRE_MINIAPP_IDEMPOTENCY_KEY=True, DEBUG=True,
                   SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False)
class LegacyConcurrentTests(LegacyHTTPMixin, LiveServerTestCase):
    @skipUnless(connection.vendor == 'postgresql', 'Independent-worker locks require PostgreSQL')
    def test_independent_workers_cannot_advance_the_same_projection(self):
        upload = self.projection(self.commit(self.stage()))
        started, release = Event(), Event()
        def read():
            started.set()
            if not release.wait(15): raise TimeoutError('Synthetic provider gate timed out')
        self.book.before_read = read
        url = self.live_server_url+reverse('portal_legacy_upload_action', kwargs={'upload_id': upload['id'], 'action': 'advance'})
        headers = {'X-Telegram-Init-Data': self.headers['HTTP_X_TELEGRAM_INIT_DATA'], 'X-Request-ID': 'parallel-worker-advance'}
        body = {'revision': upload['revision'], 'source_sheet': upload['source_sheet']}
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(requests.post, url, json=body, headers=headers, timeout=20)
            try:
                self.assertTrue(started.wait(10), 'First worker did not reach the provider')
                second = requests.post(url, json=body, headers=headers, timeout=10)
                self.assertEqual(second.status_code, 409, second.text)
                self.assertEqual(second.json()['code'], 'conflict_reload')
            finally: release.set()
            self.assertEqual(first.result().status_code, 200)
        self.assertEqual(self.book.replacements, [])


@skipUnless(os.environ.get('RUN_PORTAL_LEGACY_E2E') == '1', 'Opt-in real Django/Playwright workflow')
@override_settings(TELEGRAM_BOT_TOKEN=BOT_TOKEN, PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True,
                   SECURE_SSL_REDIRECT=False, MINIAPP_TEST_DELETION_ENABLED=True,
                   REQUIRE_MINIAPP_IDEMPOTENCY_KEY=True, DEBUG=True,
                   SESSION_COOKIE_SECURE=False, CSRF_COOKIE_SECURE=False)
class LegacyBrowserTests(LegacyHTTPMixin, StaticLiveServerTestCase):
    def test_actual_shell_upload_review_commit_resume_and_projection(self):
        self.clock.stop()
        root = Path(settings.BASE_DIR)
        workbook = Path(self.directory.name)/'synthetic-browser.xlsx'
        workbook.write_bytes(workbook_bytes([[i+2, f'SYNTHETIC BROWSER {i}', '', '', 5000, 2500, 46000] for i in range(61)]))
        master = JawabuFarmerMaster.objects.create(group_configuration=self.group, customer_name='PRESERVED MASTER', legacy_fulfillment_partner='HB')
        result = subprocess.run([os.environ.get('PORTAL_TEST_NODE', 'node'), str(root/'scripts/test_portal_legacy_transport.js')],
                    input=json.dumps({'origin': self.live_server_url, 'initData': self.headers['HTTP_X_TELEGRAM_INIT_DATA'],
                                      'group': str(self.group.pk), 'workbook': str(workbook),
                                      'artifacts': str(root/'test-results/legacy-importer-automated-browser')}),
                    text=True, capture_output=True, timeout=180, cwd=root)
        self.assertEqual(result.returncode, 0, (result.stdout+result.stderr)[-7000:])
        self.assertTrue(JawabuFarmerMaster.objects.filter(pk=master.pk, customer_name='PRESERVED MASTER').exists())
        self.assertEqual(LegacyRow.objects.filter(source_sheet='Eco-conserve', publication_ready=True).count(), 61)
        self.assertEqual(JawabuFarmerMaster.objects.filter(legacy_fulfillment_partner='ECOCONSERVE').count(), 61)
        self.assertEqual(self.book.replacements, ['Eco-conserve'])
