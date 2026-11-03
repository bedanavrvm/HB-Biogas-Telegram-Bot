"""Real signed HTTP and Sheet wire simulation for FIFO/non-destructive recovery."""
from datetime import timedelta
from copy import deepcopy
from django.test import TestCase, override_settings
from core.tests_telegram_authentication import BOT_TOKEN
from .models import LegacyDraft, LegacyRow
from .tests import LegacyHTTPMixin
from .test_support import workbook_bytes


@override_settings(TELEGRAM_BOT_TOKEN=BOT_TOKEN,PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True,
    SECURE_SSL_REDIRECT=False,MINIAPP_TEST_DELETION_ENABLED=True,REQUIRE_MINIAPP_IDEMPOTENCY_KEY=True)
class LegacyRowSyncTests(LegacyHTTPMixin,TestCase):
    def start(self,upload):return self.request('sync_rows',upload=upload)['upload']

    def advance(self,upload,status=200):
        self.now+=timedelta(seconds=11)
        result=self.request('advance',upload=upload,status=status)
        return result.get('upload',upload)

    def test_partial_fifo_sync_preserves_unimported_rows_and_recovers_lost_ack(self):
        content=workbook_bytes([[2,'FIRST','712345678','12345678',5000],[3,'SECOND','712345679','87654321',7000],[4,'HELD','712345680','23456789',0]])
        upload=self.cleanup(self.stage(content))
        rows=self.rows(upload)
        # Commit row 3 before row 2: FIFO follows commit time, not spreadsheet position.
        for row in [rows[1],rows[0]]:
            upload=self.request('select',{'rows':[{'id':row['id'],'approved':True}]},upload=upload)['upload']
            upload=self.finish(self.request('commit',upload=upload)['upload'],'committing')
            self.now+=timedelta(seconds=5)
        sheet=self.book.service(sheet_name='Master Data')._sheet
        sheet.cells[2]=['FIRST','0712345678','12345678'];sheet.cells[3]=['SECOND','0712345679','87654321']
        sheet.cells[1].append('Unmapped calculation')
        sheet.cells[2].extend(['']*6+['=1+2'])
        sheet.cells[4]=['HELD','0712345680','23456789','UNCHANGED']
        held=deepcopy(sheet.cells[4]);other=deepcopy(self.book.service(sheet_name='Eco-conserve')._sheet.cells)
        upload=self.start(upload)
        while upload['state']['row_sync']['stage']!='rows':upload=self.advance(upload)
        self.book.lose_ack=True
        self.advance(upload,status=503)
        saved=self.request(upload=upload,method='get')['upload']
        self.assertEqual(saved['sheet_sync']['synced'],0)
        from .models import LegacyUpload
        plan=LegacyUpload.objects.get(pk=upload['id']).state['row_sync']['plans']
        self.assertEqual([p['row'] for p in plan],[3,2])
        upload=self.advance(saved)
        self.assertEqual(upload['sheet_sync']['synced'],2)
        upload=self.advance(upload)
        self.assertEqual(upload['phase'],'ready');self.assertEqual(upload['sheet_sync']['not_imported'],1)
        self.assertEqual(sheet.cells[4],held);self.assertEqual(self.book.service(sheet_name='Eco-conserve')._sheet.cells,other)
        self.assertEqual(sheet.cells[2][9],'=1+2')
        self.assertEqual(self.book.replacements,[])
        self.assertEqual(LegacyDraft.objects.filter(reconciliation__sheet_receipt__verified=True).count(),2)

    def test_sheet_identity_conflict_never_overwrites_another_case_or_claims_sync(self):
        upload=self.commit(self.stage())
        sheet=self.book.service(sheet_name='Master Data')._sheet;before=deepcopy(sheet.cells)
        upload=self.start(upload)
        while upload['state']['row_sync']['stage']!='rows':upload=self.advance(upload)
        self.advance(upload,status=409)
        self.assertEqual(sheet.cells,before)
        saved=self.request(upload=upload,method='get')['upload']
        self.assertEqual(saved['sheet_sync']['synced'],0)
        self.assertIn('do not confirm',saved['sheet_sync']['error'])
        self.assertEqual(LegacyRow.objects.filter(publication_ready=True).count(),0)
