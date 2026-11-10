"""Verified rows can enter normal workflow while their workbook remains partial."""
import json
import re
import uuid
from contextlib import contextmanager
from copy import deepcopy
from unittest.mock import Mock, patch

from django.test import TestCase, override_settings
from django.urls import reverse
from gspread.http_client import HTTPClient
from gspread.worksheet import Worksheet

from core.models import IntegrationOperation, JawabuFarmerMaster
from core.tests_telegram_authentication import BOT_TOKEN
from .tests import LegacyHTTPMixin
from .models import LegacyRow, LegacyUpload
from .test_support import workbook_bytes
from .fence import blocked_cases


@override_settings(TELEGRAM_BOT_TOKEN=BOT_TOKEN, PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True,
    SECURE_SSL_REDIRECT=False, MINIAPP_TEST_DELETION_ENABLED=True, REQUIRE_MINIAPP_IDEMPOTENCY_KEY=True)
class LiveImportedCasesTests(LegacyHTTPMixin, TestCase):
    def partial(self, *, sync=True, source='Master Data', source_start=2):
        sheet = self.book.service(sheet_name=source)._sheet
        sheet.cells[1].append('No.')
        sheet.cells[2]=[]
        data=workbook_bytes([[source_start,'SYNTHETIC FIRST','712345678','12345678',5000,2500,46000],
                             [source_start+1,'SYNTHETIC SECOND','711111111','87654321',5000,0,0]])
        upload=self.cleanup(self.stage(data, source=source))
        first=self.rows(upload)[0]
        upload=self.request('select',{'rows':[{'id':first['id'],'approved':True}]},upload=upload)['upload']
        upload=self.finish(self.request('commit',upload=upload)['upload'],'committing')
        if sync:
            upload=self.finish(self.request('sync_rows',upload=upload)['upload'],'syncing_rows')
        row=LegacyRow.objects.select_related('farmer').get()
        return upload,row

    def post_case(self, name, body, **kwargs):
        return self.client.post(reverse(name,kwargs=kwargs),json.dumps(body),content_type='application/json',
            HTTP_X_REQUEST_ID=str(uuid.uuid4()),**self.headers)

    def test_reported_rejection_publishes_without_inventing_a_stage_or_finishing_review(self):
        for source in ('Master Data', 'Eco-conserve'):
            with self.subTest(source=source):
                sheet = self.book.service(sheet_name=source)._sheet
                sheet.cells[1].extend(['No.', 'Current Pipeline State'])
                sheet.cells[2] = []
                phone, national_id = ('712345678', '12345678') if source == 'Master Data' else ('713345678', '32345678')
                data = workbook_bytes([
                    [2, 'SYNTHETIC REJECTED', phone, national_id, 'Rejected'],
                    [3, 'SYNTHETIC HELD', '711111111', '87654321', 'Approved'],
                ], headers=['Source Row', 'Customer Name', 'Primary Phone', 'National ID', 'Legacy Outcome'])
                upload = self.cleanup(self.stage(data, source=source))
                first = self.rows(upload)[0]
                upload = self.request('select', {'rows': [{'id': first['id'], 'approved': True}]}, upload=upload)['upload']
                upload = self.finish(self.request('commit', upload=upload)['upload'], 'committing')
                upload = self.finish(self.request('sync_rows', upload=upload)['upload'], 'syncing_rows')
                row = LegacyRow.objects.select_related('farmer').get(draft_versions__pk=first['id'])
                self.assertEqual(row.farmer.workflow_state, 'legacy_review')
                self.assertEqual(row.farmer.credit_decision, '')
                self.assertFalse(row.continuation_confirmed)
                self.assertFalse(row.farmer.pipeline_events.exists())
                self.assertEqual(sheet.cells[2][sheet.cells[1].index('Current Pipeline State')], 'REJECTED')
                saved = LegacyUpload.objects.get(pk=upload['id'])
                self.assertTrue(saved.frozen)
                self.assertEqual(saved.phase, 'ready')
                self.assertEqual(saved.drafts.filter(legacy__isnull=True).count(), 1)

    @contextmanager
    def google_client_reads(self, sheet, *, before_verify=None):
        """Use the pinned SDK's real padding/rendering above synthetic provider IO."""
        read_row, read_all = sheet.row_values, sheet.get_all_values
        transport = Mock(spec=HTTPClient)

        def values_get(_spreadsheet, area, params=None):
            match = re.search(r'!A(\d+):(\d+)$', area)
            if match:
                first, last = map(int, match.groups())
                if first == 2 and before_verify:
                    before_verify()
                values = [read_row(number) for number in range(first, last+1)]
            else:
                values = read_all()
            if (params or {}).get('valueRenderOption') != 'FORMULA':
                values = [['3' if str(cell).startswith('=') else str(cell) for cell in row] for row in values]
            return {'range': area, 'majorDimension': 'ROWS', 'values': deepcopy(values)}

        transport.values_get.side_effect = values_get
        sdk = Worksheet(None, {'sheetId': sheet.id, 'title': sheet.title,
            'gridProperties': {'rowCount': sheet.row_count, 'columnCount': sheet.col_count}},
            spreadsheet_id=self.book.id, client=transport)
        with patch.object(sheet, 'row_values', side_effect=sdk.row_values), \
             patch.object(sheet, 'get_all_values', side_effect=sdk.get_all_values):
            yield transport

    def status_change_to_publish(self, source='Master Data', *, reordered=False):
        from core.services.portal_publication import queued_publication_operations

        upload, row = self.partial(source=source, source_start=72)
        self.group.workflow = {**self.group.workflow, 'master_sync_enabled': True}
        self.group.save(update_fields=['workflow'])
        sheet = self.book.service(sheet_name=source)._sheet
        sheet.row_count = max(sheet.row_count, row.farmer.source_row_number)
        if reordered:
            width = len(sheet.cells[1])
            sheet.cells[2].extend([''] * (width-len(sheet.cells[2])))
            sheet.cells[1].reverse()
            sheet.cells[2].reverse()
        sheet.cells[1].extend(['Current Pipeline State', 'Staff formula', 'Staff number'])
        sheet.col_count = max(sheet.col_count, len(sheet.cells[1]))
        sheet.cells[2].extend([''] * (len(sheet.cells[1])-len(sheet.cells[2])))
        sheet.cells[2][sheet.cells[1].index('Current Pipeline State')] = 'LEGACY REVIEW - STAGE NOT CONFIRMED'
        sheet.cells[2][sheet.cells[1].index('Staff formula')] = '=SUM(1,2)'
        response = self.post_case('portal_legacy_confirm', {'state': 'jbl_visit',
            'revision': row.revision, 'request_id': str(uuid.uuid4())}, row_id=row.pk)
        self.assertEqual(response.status_code, 200, response.content)
        row.farmer.refresh_from_db()
        self.assertEqual(row.farmer.workflow_state, 'jbl_visit')
        operation = queued_publication_operations().get(source_id=str(row.farmer_id))
        return upload, row, sheet, operation

    def assert_status_publishes_during_review(self, source, *, reordered=False):
        from core.services.portal_publication import attempt_publication

        upload, row, sheet, operation = self.status_change_to_publish(source, reordered=reordered)
        events = row.farmer.pipeline_events.count()
        with self.google_client_reads(sheet) as transport:
            self.assertGreater(len(sheet.get_all_values()[1]), len(sheet.row_values(2)))
            attempt_publication(operation)
            operation.refresh_from_db()
            self.assertEqual(operation.status, IntegrationOperation.STATUS_SUCCEEDED, operation.last_error)
            calls = transport.values_get.call_count
            attempt_publication(operation)
            self.assertEqual(transport.values_get.call_count, calls)
        self.assertEqual(sheet.cells[2][sheet.cells[1].index('Current Pipeline State')], 'AWAITING JBL VISIT')
        self.assertEqual(sheet.cells[2][sheet.cells[1].index('Staff formula')], '=SUM(1,2)')
        self.assertEqual(sheet.cells[2][sheet.cells[1].index('Master Record ID')], str(row.farmer_id))
        self.assertEqual(sum(str(row.farmer_id) in values for values in sheet.cells.values()), 1)
        self.assertEqual(row.farmer.pipeline_events.count(), events)
        saved = LegacyUpload.objects.get(pk=upload['id'])
        self.assertTrue(saved.frozen)
        self.assertEqual(saved.phase, 'ready')
        self.assertEqual(saved.drafts.filter(legacy__isnull=True).count(), 1)

    def test_saved_master_status_publishes_without_finishing_import(self):
        self.assert_status_publishes_during_review('Master Data')

    def test_saved_eco_status_publishes_with_reordered_headers(self):
        self.assert_status_publishes_during_review('Eco-conserve', reordered=True)

    def assert_real_edit_blocks_publication(self, field, value):
        from core.services.portal_publication import attempt_publication

        upload, row, sheet, operation = self.status_change_to_publish()
        def edit():
            sheet.cells[2][sheet.cells[1].index(field)] = value
        with self.google_client_reads(sheet, before_verify=edit):
            attempt_publication(operation)
        operation.refresh_from_db()
        row.farmer.refresh_from_db()
        self.assertEqual(operation.status, IntegrationOperation.STATUS_DEAD_LETTER)
        self.assertEqual(operation.last_error_code, 'sheet_row_changed')
        self.assertEqual(row.farmer.workflow_state, 'jbl_visit')
        self.assertEqual(sheet.cells[2][sheet.cells[1].index('Current Pipeline State')], 'LEGACY REVIEW - STAGE NOT CONFIRMED')
        self.assertEqual(sheet.cells[2][sheet.cells[1].index(field)], value)
        self.assertTrue(LegacyUpload.objects.get(pk=upload['id']).frozen)

    def test_real_sheet_edit_still_blocks_publication_and_retains_saved_status(self):
        self.assert_real_edit_blocks_publication('Customer Name', 'SYNTHETIC STAFF EDIT')

    def test_zero_added_to_blank_cell_still_blocks_publication(self):
        self.assert_real_edit_blocks_publication('Staff number', 0)

    def test_verified_case_correction_and_publication_during_partial_import(self):
        upload,row=self.partial()
        self.assertTrue(upload['frozen']);self.assertEqual(upload['sheet_sync']['not_imported'],1)
        self.assertFalse(blocked_cases(JawabuFarmerMaster.objects.filter(pk=row.farmer_id)).exists())
        self.group.workflow={**self.group.workflow,'master_sync_enabled':True};self.group.save()
        response=self.post_case('portal_farmer_case_correction',{'values':{'primary_phone':'254799999998'},
            'expected_revision':row.farmer.workflow_revision,'reason':'Verified correction after source review.'},farmer_id=row.farmer_id)
        self.assertEqual(response.status_code,200,response.content)
        row.farmer.refresh_from_db()
        from core.services.portal_publication import queued_publication_operations, attempt_publication
        operation=queued_publication_operations().get(source_id=str(row.farmer_id))
        attempt_publication(operation)
        operation.refresh_from_db()
        self.assertEqual(operation.status,IntegrationOperation.STATUS_SUCCEEDED, operation.last_error)
        sheet=self.book.sheets[0]
        self.assertEqual(sheet.cells[2][sheet.cells[1].index('Primary Phone')],'254799999998')
        from .projection import record_values
        self.assertEqual(record_values(row,['Primary Phone'],1),['254799999998'])
        self.assertEqual(row.values['primary_phone'],'712345678')
        self.assertTrue(LegacyUpload.objects.get(pk=upload['id']).frozen)

    def test_permission_flag_alone_does_not_release_initial_write(self):
        upload,row=self.partial(sync=False)
        row.publication_ready=True;row.save(update_fields=['publication_ready'])
        response=self.post_case('portal_farmer_case_correction',{'values':{'village':'NEW'},
            'expected_revision':row.farmer.workflow_revision,'reason':'Check blocked initial write'},farmer_id=row.farmer_id)
        self.assertEqual(response.status_code,503,response.content)
        self.assertEqual(response.json()['code'],'legacy_case_awaiting_sync')
        self.assertEqual(row.farmer.village,'')

    def test_verified_continuation_confirmation_is_audited_and_published(self):
        upload,row=self.partial()
        self.group.workflow={**self.group.workflow,'master_sync_enabled':True};self.group.save()
        # An ambiguous historical stage has to be confirmed explicitly.
        row.farmer.workflow_state='legacy_review';row.farmer.save(update_fields=['workflow_state'])
        response=self.post_case('portal_legacy_confirm',{'state':'jbl_visit','note':'Source reviewed; schedule the visit.',
            'revision':row.revision,'request_id':str(uuid.uuid4())},row_id=row.pk)
        self.assertEqual(response.status_code,200,response.content)
        row.farmer.refresh_from_db()
        self.assertEqual(row.farmer.workflow_state,'jbl_visit')
        self.assertTrue(row.farmer.pipeline_events.filter(action='legacy_continuation_confirmed').exists())
        self.assertTrue(IntegrationOperation.objects.filter(source_id=str(row.farmer_id)).exists())

    def test_replacement_holds_only_its_register_and_mixed_selection_is_blocked(self):
        upload,row=self.partial()
        other=JawabuFarmerMaster.objects.create(group_configuration=self.group,customer_name='ECO LIVE',legacy_fulfillment_partner='ECOCONSERVE')
        LegacyUpload.objects.filter(pk=upload['id']).update(phase='backup')
        self.assertTrue(blocked_cases(JawabuFarmerMaster.objects.filter(pk=row.farmer_id)).exists())
        self.assertFalse(blocked_cases(JawabuFarmerMaster.objects.filter(pk=other.pk)).exists())
        response=self.post_case('portal_requisition_preview',{'farmer_ids':[str(row.farmer_id),str(other.pk)]})
        self.assertEqual(response.status_code,503,response.content)
        self.assertEqual(response.json()['code'],'legacy_register_replacing')

    def test_verified_readiness_does_not_grant_edit_authority_or_bypass_global_holds(self):
        upload,row=self.partial()
        self.staff(role='JBL_OFFICER')
        response=self.post_case('portal_farmer_case_correction',{'values':{'village':'NOT ALLOWED'},
            'expected_revision':row.farmer.workflow_revision,'reason':'Attempt without IT authority'},farmer_id=row.farmer_id)
        self.assertEqual(response.status_code,403,response.content)
        # A fabricated case ID in a settings payload must not disable its owner fence.
        self.bind(self.actor,991001)
        response=self.post_case('portal_reports',{'farmer_ids':[str(row.farmer_id)],'title':'Bypass attempt'})
        self.assertEqual(response.status_code,503,response.content)

    def test_saved_stale_import_plan_cannot_restore_pre_correction_phone(self):
        from .projection import checksum,record_values
        upload,row=self.partial()
        saved=LegacyUpload.objects.get(pk=upload['id'])
        p=saved.state['row_sync'];sheet=self.book.sheets[0]
        old=sheet.row_values(2)
        p['plans']=[{'draft':saved.drafts.get(legacy=row).pk,'legacy':str(row.pk),'case':str(row.farmer_id),
            'row':2,'before':checksum([old]),'values':record_values(row,p['new_headers'],1,existing=old),
            'revision':row.farmer.workflow_revision}]
        saved.save(update_fields=['state'])
        response=self.post_case('portal_farmer_case_correction',{'values':{'primary_phone':'254799999998'},
            'expected_revision':row.farmer.workflow_revision,'reason':'Newer correction than saved import plan.'},farmer_id=row.farmer_id)
        self.assertEqual(response.status_code,200,response.content)
        # Resume the already-saved checkpoint, as after a worker interruption.
        upload=self.request('sync_rows',upload=upload)['upload']
        upload=self.finish(upload,'syncing_rows')
        self.assertEqual(sheet.row_values(2)[sheet.cells[1].index('Primary Phone')],'254799999998')
        self.assertEqual(upload['sheet_sync']['synced'],1)

    def test_document_action_resolves_entire_saved_membership(self):
        from core.models import RequisitionBatch
        upload,row=self.partial()
        document=RequisitionBatch.objects.create(order_number='HB-REVIEW',farmer_ids=[str(row.farmer_id)])
        response=self.post_case('portal_document_physical_signoff_upload',{},
            document_type='requisition',document_id=document.pk)
        # Admission succeeds; the document's own attestation guard still applies.
        self.assertEqual(response.status_code,400,response.content)
        pending=JawabuFarmerMaster.objects.create(group_configuration=self.group,customer_name='UNVERIFIED',legacy_fulfillment_partner='HB')
        document.farmer_ids.append(str(pending.pk));document.save(update_fields=['farmer_ids'])
        response=self.post_case('portal_document_physical_signoff_upload',{},
            document_type='requisition',document_id=document.pk)
        self.assertEqual(response.status_code,503,response.content)
        self.assertEqual(response.json()['code'],'legacy_case_awaiting_sync')
