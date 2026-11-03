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

    def test_visible_case_id_is_staff_reference_and_uuid_stays_internal(self):
        upload=self.commit(self.stage())
        sheet=self.book.service(sheet_name='Master Data')._sheet
        sheet.cells={1:sheet.cells[1]}
        upload=self.complete(self.start(upload))
        legacy=LegacyRow.objects.get()
        headers=sheet.cells[1];values=sheet.cells[2]
        self.assertEqual(values[headers.index('Case ID')],f'JBL-{legacy.farmer.case_reference_number}')
        self.assertEqual(values[headers.index('Master Record ID')],str(legacy.farmer_id))
        self.assertIn(headers.index('Master Record ID'),sheet.hidden_columns)

    def test_empty_register_starts_at_row_two_despite_source_row_gaps(self):
        upload=self.commit(self.stage(workbook_bytes([[100,'FIRST'],[200,'SECOND']])))
        sheet=self.book.service(sheet_name='Master Data')._sheet
        sheet.cells={1:sheet.cells[1]}
        self.complete(self.start(upload))
        self.assertEqual([sheet.cells.get(n,[])[0:1] for n in (2,3)],[['FIRST'],['SECOND']])
        self.assertEqual(sorted(d.reconciliation['sheet_receipt']['row'] for d in LegacyDraft.objects.all()),[2,3])
        self.assertNotIn(100,sheet.cells);self.assertNotIn(200,sheet.cells)

    def test_verified_reset_then_import_restarts_after_the_header(self):
        import json,uuid
        from django.urls import reverse
        from core.models import JawabuFarmerMaster,PortalMaintenanceState
        from core.services.portal_full_reset import reset_portal_configuration
        PortalMaintenanceState.objects.update_or_create(singleton=1,defaults={'mode':'maintenance','reason':'Reviewed synthetic reset'})
        farmer=JawabuFarmerMaster.objects.create(group_configuration=self.group,customer_name='RESET ME')
        for sheet in self.book.sheets:sheet.cells={1:[*sheet.cells[1],'Master Record ID']}
        sheet=self.book.service(sheet_name='Master Data')._sheet
        sheet.cells[2]=['RESET ME']+['']*8+[str(farmer.pk)]
        result=reset_portal_configuration(self.group,actor=self.actor,backup_reference='verified-synthetic-backup')
        self.assertEqual(result['sheet_rows_deleted'],1)
        self.assertEqual(set(sheet.cells),{1})
        response=self.client.post(reverse('portal_set_maintenance'),json.dumps({'mode':'live'}),content_type='application/json',
            **self.headers,HTTP_X_REQUEST_ID=str(uuid.uuid4()))
        self.assertEqual(response.status_code,200,response.content[:500])
        self.complete(self.start(self.commit(self.stage(workbook_bytes([[100,'AFTER RESET']])))))
        self.assertEqual(sheet.cells[2][0],'AFTER RESET')
        self.assertNotIn(100,sheet.cells)

    def test_fifo_reuses_only_fully_empty_rows_and_preserves_unimported_content(self):
        upload=self.commit(self.stage(workbook_bytes([[100,'FIRST'],[200,'SECOND']])))
        sheet=self.book.service(sheet_name='Master Data')._sheet
        sheet.cells[4]=['PRESERVED UNIMPORTED']
        sheet.cells[1].append('Unmapped formula')
        sheet.cells[3]=['']*9+['=1+2']
        original=deepcopy(sheet.cells)
        self.complete(self.start(upload))
        self.assertEqual(sheet.cells[5][0],'FIRST');self.assertEqual(sheet.cells[6][0],'SECOND')
        for number,values in original.items():
            if number!=1:self.assertEqual(sheet.cells[number],values)

    def test_existing_visible_uuid_is_corrected_in_place_with_internal_binding(self):
        upload=self.commit(self.stage())
        sheet=self.book.service(sheet_name='Master Data')._sheet;legacy=LegacyRow.objects.get()
        sheet.cells[1].append('Case ID')
        sheet.cells[6]=['SYNTHETIC LEGACY','','','','','','','','',str(legacy.farmer_id)]
        self.complete(self.start(upload))
        self.assertEqual(sheet.cells[6][9],f'JBL-{legacy.farmer.case_reference_number}')
        self.assertEqual(sheet.cells[6][10],str(legacy.farmer_id))
        self.assertNotIn(3,sheet.cells)

    def test_restarting_old_allocation_checkpoint_keeps_confirmed_case_row(self):
        from .models import LegacyUpload
        upload=self.commit(self.stage(workbook_bytes([[100,'FIRST'],[200,'SECOND']])))
        sheet=self.book.service(sheet_name='Master Data')._sheet
        sheet.cells={1:sheet.cells[1]}
        upload=self.start(upload)
        saved=LegacyUpload.objects.get(pk=upload['id'])
        saved.state['row_sync']={'stage':'rows','return_phase':'ready','spreadsheet':str(self.book.id),
            'sheet':sheet.id,'header_row':1,'headers':sheet.cells[1],'new_headers':sheet.cells[1]+['Case ID','Master Record ID'],'case_rows':{}}
        saved.save(update_fields=['state'])
        self.complete(self.request(upload=upload,method='get')['upload'])
        self.assertEqual(sheet.cells[2][0],'FIRST');self.assertEqual(sheet.cells[3][0],'SECOND')

    def test_reviewed_binding_command_separates_visible_reference_and_hidden_uuid(self):
        from io import StringIO
        from pathlib import Path
        from django.core.management import call_command
        upload=self.commit(self.stage());legacy=LegacyRow.objects.get()
        manifest=Path(self.directory.name)/'reviewed-bindings.json'
        arguments={'batch':str(legacy.batch_id),'actor':self.actor.pk,'manifest':str(manifest),'stdout':StringIO()}
        call_command('bind_portal_legacy',**arguments)
        call_command('bind_portal_legacy',**arguments,apply=True,note='Reviewed synthetic exact binding')
        sheet=self.book.service(sheet_name='Master Data')._sheet;headers=sheet.cells[1]
        self.assertEqual(sheet.cells[2][0],'PRESERVED Master Data')
        self.assertEqual(sheet.cells[2][headers.index('Case ID')],f'JBL-{legacy.farmer.case_reference_number}')
        self.assertEqual(sheet.cells[2][headers.index('Master Record ID')],str(legacy.farmer_id))
        self.assertIn(headers.index('Master Record ID'),sheet.hidden_columns)

    def test_old_uncertain_uuid_write_is_verified_then_corrected_without_duplicate(self):
        from .models import LegacyUpload
        upload=self.commit(self.stage())
        sheet=self.book.service(sheet_name='Master Data')._sheet;sheet.cells={1:sheet.cells[1]}
        upload=self.start(upload)
        while upload['state']['row_sync']['stage']!='rows':upload=self.advance(upload)
        self.book.lose_ack=True;self.advance(upload,status=503)
        saved=LegacyUpload.objects.get(pk=upload['id']);p=saved.state['row_sync'];plan=p['plans'][0]
        column=p['new_headers'].index('Case ID')
        plan['values'][column]=plan['case'];sheet.cells[plan['row']][column]=plan['case']
        p.pop('allocation');saved.save(update_fields=['state'])
        self.complete(self.request(upload=upload,method='get')['upload'])
        legacy=LegacyRow.objects.get()
        self.assertEqual(sheet.cells[2][column],f'JBL-{legacy.farmer.case_reference_number}')
        self.assertEqual([number for number,values in sheet.cells.items() if number>1 and values and values[0]=='SYNTHETIC LEGACY'],[2])
        self.assertEqual(LegacyDraft.objects.get().reconciliation['sheet_receipt']['reference_format'],'staff')

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
