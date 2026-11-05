"""Native API, retained source evidence and provider uncertainty at changeover."""
from copy import deepcopy
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from core.models import ParsedMessage, ComplaintCaseControl, IntegrationOperation
from core.tests_telegram_authentication import BOT_TOKEN
from .models import ImportChunk, ImportUpload
from .tests import ImportFixture, source
from .test_support import ComplaintBook


@override_settings(TELEGRAM_BOT_TOKEN=BOT_TOKEN, COMPLAINT_CASES_WEBAPP_REQUIRE_TELEGRAM_AUTH=True, SECURE_SSL_REDIRECT=False)
class ComplaintProjectionTests(ImportFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.book = ComplaintBook()
        provider = patch('core.services.complaint_cases.get_sheets_service', return_value=self.book.service_instance)
        provider.start(); self.addCleanup(provider.stop)

    def reset(self, upload):
        self.user.is_superuser = True; self.user.save(update_fields=['is_superuser'])
        result = self.call('cutover-preview', upload=upload)
        upload = self.call('cutover-confirm', {'token':result['preview']['token'], 'manual_edits_paused':True}, upload=result['upload'])['upload']
        for _ in range(20):
            if upload['phase']=='ready': return upload
            upload=self.call('advance',upload=upload)['upload']
        self.fail('Changeover failed to finish')

    def test_changeover_is_confirmed_scoped_and_preserves_imported_provenance(self):
        old=self.commit(self.stage())
        imported=ParsedMessage.objects.get(source='complaint_legacy')
        test=ParsedMessage.objects.create(processed_message=imported.processed_message,group_id=self.owner.group_id,message_id='synthetic-test',customer_name='DELETE TEST')
        ComplaintCaseControl.objects.create(parsed_message=test,reference_number='CMP-DELETE-TEST')
        foreign=ParsedMessage.objects.create(processed_message=imported.processed_message,group_id=self.other.group_id,message_id='synthetic-foreign')
        upload=self.stage(source([[50,'NEXT SYNTHETIC','OPEN','24-May-2025']]))
        self.call('cutover-preview', upload=upload, status=403)
        counterpart=deepcopy(self.book.sheets[0].cells)
        upload=self.reset(upload)
        self.assertFalse(ParsedMessage.objects.filter(pk=test.pk).exists())
        self.assertTrue(ParsedMessage.objects.filter(pk__in=[imported.pk,foreign.pk]).count()==2)
        self.assertTrue(ImportUpload.objects.filter(pk=old['id']).exists())
        self.assertTrue(ImportChunk.objects.filter(upload_id=upload['id'],kind__startswith='bak').exists())
        self.assertEqual(self.book.register.row_values(2),[])
        self.assertEqual(self.book.sheets[0].cells,counterpart)
        self.assertEqual(self.call(upload=old,method='get')['upload']['awaiting_sync'],1)
        self.call('cutover-preview',upload=upload,status=409)

    def test_fifo_batches_verify_values_and_lost_ack_does_not_duplicate(self):
        upload=self.stage(source([[1000-i,f'SYNTHETIC {i}','OPEN','24-May-2025'] for i in range(61)]))
        upload=self.reset(upload);upload=self.commit(upload)
        self.book.lose_ack=True
        self.call('sync',upload=upload,status=409)
        upload=self.call(upload=upload,method='get')['upload']
        self.assertEqual(upload['synced'],0)
        self.assertEqual(len([r for r in self.book.register.cells.values() if len(r)>1 and str(r[1]).startswith('CMP-')]),50)
        upload=self.call('sync',upload=upload)['upload']
        self.assertEqual(upload['synced'],50)
        first=[row for row in self.book.register.get_all_values()[1:] if row and row[1]]
        self.assertEqual([r[4] for r in first],['SYNTHETIC '+str(i) for i in range(60,10,-1)])
        upload=self.call('publish',upload=upload)['upload'];upload=self.finish(upload,'publishing')
        self.assertEqual((upload['synced'],upload['awaiting_sync']),(61,0))
        self.assertEqual([r[0] for r in self.book.register.get_all_values()[1:] if r and r[1]],list(map(str,range(1,62))))
        self.assertEqual(IntegrationOperation.objects.filter(operation_type='complaint_browser.sheet',status='succeeded').count(),61)
        self.call('publish',upload=upload,status=409)

    def test_readback_failure_remains_pending_and_old_imports_resume_on_worker(self):
        upload=self.commit(self.stage())
        self.book.corrupt_read='Complaints Register'
        self.call('sync',upload=upload,status=409)
        self.assertFalse(ParsedMessage.objects.get(source='complaint_legacy').synced_to_sheets)
        self.book.corrupt_read=None
        upload=self.call(upload=upload,method='get')['upload']
        obj=ImportUpload.objects.get(pk=upload['id']); obj.state.pop('sync_retry_at',None);obj.save(update_fields=['state'])
        call_command('drain_complaint_publications',apply=True,limit=10,max_seconds=50,stdout=StringIO())
        self.assertTrue(ParsedMessage.objects.get(source='complaint_legacy').synced_to_sheets)
        self.assertEqual(self.call(upload=upload,method='get')['upload']['synced'],1)

    def test_changed_sheet_can_be_reviewed_again_without_losing_the_first_backup(self):
        upload=self.stage();self.user.is_superuser=True;self.user.save(update_fields=['is_superuser'])
        result=self.call('cutover-preview',upload=upload)
        upload=self.call('cutover-confirm',{'token':result['preview']['token'],'manual_edits_paused':True},upload=result['upload'])['upload']
        self.call('discard',upload=upload,status=409)
        while upload['phase']!='clearing': upload=self.call('advance',upload=upload)['upload']
        self.book.register.cells[2][4]='CHANGED AFTER BACKUP'
        self.call('advance',upload=upload,status=409)
        upload=self.call(upload=upload,method='get')['upload']
        upload=self.reset(upload)
        self.assertEqual(ImportChunk.objects.filter(upload_id=upload['id'],kind__startswith='bak',position=0).count(),2)
        self.assertTrue(upload['cutover_complete']);self.assertEqual(self.book.register.row_values(2),[])

    def test_stale_confirmation_and_shared_destination_do_not_delete_or_clear(self):
        upload=self.stage();self.user.is_superuser=True;self.user.save(update_fields=['is_superuser'])
        result=self.call('cutover-preview',upload=upload)
        from core.models import RawMessage, ProcessedMessage
        raw=RawMessage.objects.create(telegram_message_id='late-synthetic',content='synthetic')
        processed=ProcessedMessage.objects.create(raw_message=raw,message_hash='late-synthetic')
        case=ParsedMessage.objects.create(processed_message=processed,group_id=self.owner.group_id,message_id='late-synthetic')
        self.call('cutover-confirm',{'token':result['preview']['token'],'manual_edits_paused':True},upload=result['upload'],status=409)
        self.assertTrue(ParsedMessage.objects.filter(pk=case.pk).exists())
        self.assertEqual(self.book.register.row_values(2)[1],'CMP-OLD-TEST')
        self.other.sheet_id=self.owner.sheet_id;self.other.sheet_name=self.owner.sheet_name
        self.other.save(update_fields=['sheet_id','sheet_name'])
        upload=self.call(upload=upload,method='get')['upload']
        self.call('cutover-preview',upload=upload,status=409)
