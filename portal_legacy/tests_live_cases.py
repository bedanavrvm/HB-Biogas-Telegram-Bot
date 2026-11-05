"""Verified rows can enter normal workflow while their workbook remains partial."""
import json
import uuid
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import IntegrationOperation, JawabuFarmerMaster
from core.tests_telegram_authentication import BOT_TOKEN
from .tests import LegacyHTTPMixin
from .models import LegacyRow, LegacyUpload
from .test_support import workbook_bytes
from .fence import blocked_cases


@override_settings(TELEGRAM_BOT_TOKEN=BOT_TOKEN, PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True,
    SECURE_SSL_REDIRECT=False, MINIAPP_TEST_DELETION_ENABLED=True, REQUIRE_MINIAPP_IDEMPOTENCY_KEY=True)
class LiveImportedCasesTests(LegacyHTTPMixin, TestCase):
    def partial(self, *, sync=True):
        self.book.sheets[0].cells[1].append('No.')
        self.book.sheets[0].cells[2]=[]
        data=workbook_bytes([[2,'SYNTHETIC FIRST','712345678','12345678',5000,2500,46000],
                             [3,'SYNTHETIC SECOND','711111111','87654321',5000,0,0]])
        upload=self.cleanup(self.stage(data))
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
