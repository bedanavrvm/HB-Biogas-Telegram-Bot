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
        self.book.lose_ack = True
        eco=self.book.service(sheet_name='Eco-conserve')._sheet
        eco.cells.pop(2);eco.row_count=65;eco.cells[64]=['UNIMPORTED SHEET ROW - RETAIN']
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
        self.assertEqual(self.book.replacements, [])
        self.assertEqual(eco.cells[64],['UNIMPORTED SHEET ROW - RETAIN'])

    def test_editable_review_issues_identity_evidence_and_persistence(self):
        self.clock.stop()
        root=Path(settings.BASE_DIR)
        workbook=Path(self.directory.name)/'synthetic-review.xlsx'
        workbook.write_bytes(workbook_bytes([[2,'BAD DEPOSIT','712000001','11111111','bad'],
            [3,'ID MATCH','712000002','22222222',5000],[4,'DUPLICATE A','712000003','33333333',5000],
            [5,'DUPLICATE B','712000004','33333333',5000],[6,'PHONE REVIEW','123','66666666',5000]]))
        JawabuFarmerMaster.objects.create(group_configuration=self.group,customer_name='EXISTING HOUSEHOLD',national_id='22222222',primary_phone='254700000002',legacy_fulfillment_partner='HB')
        result=subprocess.run([os.environ.get('PORTAL_TEST_NODE','node'),str(root/'scripts/test_portal_legacy_review.js')],
            input=json.dumps({'origin':self.live_server_url,'initData':self.headers['HTTP_X_TELEGRAM_INIT_DATA'],'group':str(self.group.pk),
                'workbook':str(workbook),'artifacts':str(root/'test-results/legacy-importer-review-browser')}),
            text=True,capture_output=True,timeout=180,cwd=root)
        self.assertEqual(result.returncode,0,(result.stdout+result.stderr)[-7000:])
        from .models import LegacyDraft
        draft=LegacyDraft.objects.get(source_row=2)
        self.assertEqual(draft.values['deposit_paid_hbg'],'5000')
        self.assertEqual(draft.reconciliation['original_values']['deposit_paid_hbg'],'bad')

    def test_admin_reset_of_imported_hb_baseline(self):
        self.clock.stop()
        from core.tests_portal_full_reset import PortalFullResetTests
        from .models import LegacyUpload,LegacyRow
        farmer,batch,upload,row=PortalFullResetTests.legacy_fixture(self)
        other=JawabuFarmerMaster.objects.create(group_configuration=self.other,customer_name='OTHER OWNER - RETAIN')
        self.actor.is_staff=True;self.actor.save(update_fields=['is_staff']);self.client.force_login(self.actor)
        root=Path(settings.BASE_DIR)
        result=subprocess.run([os.environ.get('PORTAL_TEST_NODE','node'),str(root/'scripts/test_portal_legacy_reset.js')],
            input=json.dumps({'origin':self.live_server_url,'group':str(self.group.pk),'groupId':self.group.group_id,
                'cookieName':settings.SESSION_COOKIE_NAME,'cookieValue':self.client.cookies[settings.SESSION_COOKIE_NAME].value,
                'artifacts':str(root/'test-results/legacy-importer-reset-browser')}),text=True,capture_output=True,timeout=90,cwd=root)
        self.assertEqual(result.returncode,0,(result.stdout+result.stderr)[-5000:])
        self.assertFalse(JawabuFarmerMaster.objects.filter(pk=farmer.pk).exists())
        self.assertFalse(LegacyUpload.objects.filter(pk=upload.pk).exists())
        self.assertFalse(LegacyRow.objects.filter(pk=row.pk).exists())
        self.assertTrue(JawabuFarmerMaster.objects.filter(pk=other.pk).exists())
