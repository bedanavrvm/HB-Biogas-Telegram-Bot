"""Import counts distinguish local saves from verified Sheet readback."""
import json
import uuid
from datetime import timedelta
from django.test import TestCase, override_settings
from django.urls import reverse
from core.tests_telegram_authentication import BOT_TOKEN
from .tests import LegacyHTTPMixin
from .test_support import workbook_bytes
from .models import LegacyRow


@override_settings(TELEGRAM_BOT_TOKEN=BOT_TOKEN,PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True,
    SECURE_SSL_REDIRECT=False,MINIAPP_TEST_DELETION_ENABLED=True,REQUIRE_MINIAPP_IDEMPOTENCY_KEY=True)
class LegacySyncTests(LegacyHTTPMixin,TestCase):
    def test_saved_cases_are_not_reported_as_synced_before_readback(self):
        upload=self.commit(self.stage())
        self.assertEqual(upload['committed'],1)
        self.assertEqual(upload['sheet_sync']['synced'],0)
        self.assertEqual(upload['sheet_sync']['pending'],1)
        self.assertEqual(upload['sheet_sync']['state'],'awaiting_confirmation')
        self.assertEqual(self.book.replacements,[])
        upload=self.complete(self.projection(upload))
        self.assertEqual(upload['sheet_sync']['synced'],1)
        self.assertEqual(upload['sheet_sync']['pending'],0)
        self.assertEqual(upload['sheet_sync']['state'],'complete')

    def test_partial_import_exposes_remaining_rows_without_claiming_sync(self):
        upload=self.cleanup(self.stage(workbook_bytes([[2,'FIRST'],[3,'SECOND']])))
        row=self.rows(upload)[0]
        upload=self.request('select',{'rows':[{'id':row['id'],'approved':True}]},upload=upload)['upload']
        upload=self.finish(self.request('commit',upload=upload)['upload'],'committing')
        self.assertEqual(upload['sheet_sync'],{'state':'awaiting_import','synced':0,'pending':1,'not_imported':1,'error':''})
        result=self.request(upload=upload,method='get',query='?summary=1')
        self.assertNotIn('rows',result);self.assertEqual(result['upload']['sheet_sync']['not_imported'],1)
        self.request('projection_preview',upload=upload,status=409)
        self.assertEqual(self.book.replacements,[])

    def test_publication_permission_is_not_a_sheet_verification_receipt(self):
        upload=self.commit(self.stage())
        LegacyRow.objects.filter(draft_versions__upload_id=upload['id']).update(publication_ready=True)
        saved=self.request(upload=upload,method='get')['upload']
        self.assertEqual(saved['sheet_sync']['synced'],0)
        self.assertEqual(saved['sheet_sync']['pending'],1)

    def test_readback_failure_retains_verified_count_and_recovers(self):
        upload=self.projection(self.commit(self.stage(workbook_bytes([[i+2,f'SYNTHETIC {i}'] for i in range(151)]))))
        for _ in range(30):
            if upload['phase']=='readback':break
            self.now+=timedelta(seconds=5)
            upload=self.request('advance',upload=upload)['upload']
        self.assertEqual(upload['phase'],'readback')
        self.assertEqual(upload['sheet_sync']['synced'],0)
        self.now+=timedelta(seconds=5)
        upload=self.request('advance',upload=upload)['upload']
        self.assertEqual(upload['sheet_sync']['synced'],100);self.assertEqual(upload['sheet_sync']['pending'],51)
        self.book.corrupt_read='Master Data';self.now+=timedelta(seconds=5)
        self.request('advance',upload=upload,status=409)
        upload=self.request(upload=upload,method='get')['upload']
        self.assertEqual(upload['sheet_sync']['state'],'needs_attention');self.assertTrue(upload['frozen'])
        self.assertEqual(upload['sheet_sync']['synced'],100);self.assertEqual(upload['sheet_sync']['pending'],51)
        self.assertIn('readback mismatch',upload['sheet_sync']['error'])
        self.book.corrupt_read=None;upload=self.complete(upload)
        self.assertEqual(upload['sheet_sync']['synced'],151);self.assertEqual(upload['sheet_sync']['pending'],0)
        self.assertEqual(upload['sheet_sync']['error'],'');self.assertFalse(upload['frozen'])

    def test_background_pump_during_cutover_pauses_without_a_503_or_remote_write(self):
        self.commit(self.stage())
        response=self.client.post(reverse('portal_publication_pump'),json.dumps({}),content_type='application/json',
            **self.headers,HTTP_X_REQUEST_ID=str(uuid.uuid4()))
        self.assertEqual(response.status_code,200,response.content[:800])
        self.assertTrue(response.json()['paused'])
        self.assertEqual(response.json()['reason'],'legacy_cutover_maintenance')
        self.assertEqual(self.book.replacements,[])
