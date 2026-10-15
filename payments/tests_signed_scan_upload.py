"""Payment Preparation's multipart signed-copy contract and exact-version finality."""
from decimal import Decimal
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase

from core.api.portal_views import portal_document_physical_signoff_upload
from core.models import (DocumentPhysicalSignoff, DocumentSignoffPolicy,
    GroupSheetConfiguration, JawabuFarmerMaster, PaymentDocument)
from core.services.document_signoffs import retry_physical_signoff
from core.services.telegram_identity import user_access
from payments.models import PaymentBatch
from payments.services import add_cases, create_batch, review_case, submit_for_review


class PaymentScanUploadTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_superuser('synthetic-payment-signoff', '', 'test-only')
        DocumentSignoffPolicy.objects.update_or_create(document_type='payment', defaults={
            'workflow': 'jawabu_portal', 'approval_role': 'BUSINESS_ADMIN',
            'approval_roles': ['BUSINESS_ADMIN'], 'is_active': True})
        self.group = GroupSheetConfiguration.objects.create(group_id='-100-payment-scan-training',
            display_name='Synthetic payment scans', enabled=True, sheet_id='synthetic-sheet',
            workflow={'type': 'jawabu_homebiogas'})
        self.farmer = JawabuFarmerMaster.objects.create(customer_name='Synthetic Applicant',
            national_id='99999991', primary_phone='254700000001', customer_no='TRAINING',
            invoice_number='TRAINING-INVOICE', order_number='TRAINING-ORDER',
            balance_due=Decimal('1000'), workflow_revision=1)
        with patch('payments.services.payment_readiness', return_value={
            'ready': [{'farmer_id': str(self.farmer.pk), 'row': {}}], 'blocked': [],
            'ready_count': 1, 'blocked_count': 0}):
            batch = create_batch(group_configuration=self.group, actor=self.actor)
            batch = add_cases(batch.pk, farmer_ids=[self.farmer.pk], payment_modes={str(self.farmer.pk): 'CASH'},
                              expected_revision=batch.revision, actor=self.actor)
            batch = submit_for_review(batch.pk, expected_revision=batch.revision, actor=self.actor)
            batch = review_case(batch.pk, self.farmer.pk, decision='approved', comment='Confirmed.',
                                expected_revision=batch.revision, actor=self.actor)
        self.document = PaymentDocument.objects.create(order_number='PAYMENT-89', payment_number='89',
            filename='Training payment 89.xlsx', status='awaiting_scan', version=2,
            farmer_ids=[str(self.farmer.pk)], file_content=b'synthetic-retained-workbook-version-2')
        batch.current_document = self.document
        batch.status = PaymentBatch.STATUS_AWAITING_SCAN
        batch.payment_number = 89
        batch.save()
        self.batch = batch
        self.access = user_access(self.actor, 'jawabu_portal')
        # Scope itself has independent coverage. Keep this synthetic fixture
        # focused on the actual endpoint, scan retention and payment completion.
        self.enterContext(patch('core.api.portal_views._portal_saved_document_in_scope', return_value=True))
        self.storage = self.enterContext(patch('core.services.order_approval.GoogleDriveMediaStorage'))
        self.storage.return_value.upload.return_value = ('synthetic-scan', 'https://drive.test/synthetic-scan')

    def upload(self, *, attested=True, request_id='synthetic-upload', filename='signed-payment.pdf',
               content_type='application/pdf'):
        values = {'signed_scan': SimpleUploadedFile(filename, b'%PDF-synthetic-signed-payment', content_type=content_type)}
        if attested:
            values['attested_complete'] = 'true'
        request = RequestFactory().post('/', values, HTTP_X_REQUEST_ID=request_id)
        request.portal_user = self.actor
        request.portal_access = self.access
        return portal_document_physical_signoff_upload(request, 'payment', str(self.document.pk))

    def test_missing_attestation_reproduces_rejection_before_storage_or_completion(self):
        response = self.upload(attested=False)
        self.assertEqual(response.status_code, 400)
        self.assertIn('Confirm that the scan', json.loads(response.content)['error'])
        self.storage.return_value.upload.assert_not_called()
        self.assertFalse(DocumentPhysicalSignoff.objects.exists())
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.status, 'awaiting_scan')

    def test_attested_upload_completes_current_payment_and_retries_do_not_duplicate(self):
        response = self.upload()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(json.loads(response.content)['ok'])
        self.batch.refresh_from_db()
        self.document.refresh_from_db()
        self.assertEqual(self.batch.status, 'completed')
        self.assertEqual(self.document.status, 'completed')
        signoff = DocumentPhysicalSignoff.objects.get(payment_document=self.document)
        self.assertTrue(signoff.attested_complete)
        self.assertEqual(signoff.source_version, 2)
        self.assertEqual(bytes(signoff.source_file_content), bytes(self.document.file_content))
        revision = self.batch.revision
        replay = self.upload()
        self.assertEqual(replay.status_code, 200)
        self.assertTrue(json.loads(replay.content)['idempotent_replay'])
        self.assertEqual(DocumentPhysicalSignoff.objects.count(), 1)
        self.assertEqual(self.storage.return_value.upload.call_count, 1)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.revision, revision)
        self.assertEqual(self.batch.events.filter(action='signed_scan_accepted').count(), 1)

    def test_drive_failure_retains_scan_without_completing_payment_and_retry_finishes(self):
        self.storage.return_value.upload.side_effect = RuntimeError('Synthetic Drive outage')
        response = self.upload()
        self.assertEqual(response.status_code, 202, response.content)
        data = json.loads(response.content)
        self.assertFalse(data['ok'])
        self.assertTrue(data['pending_retry'])
        signoff = DocumentPhysicalSignoff.objects.get(pk=data['signoff']['id'])
        self.assertEqual(bytes(signoff.scan_file_content), b'%PDF-synthetic-signed-payment')
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.status, 'awaiting_scan')
        self.storage.return_value.upload.side_effect = None
        completed = retry_physical_signoff(signoff_id=str(signoff.pk), actor=self.actor, access=self.access)
        self.assertEqual(completed.status, 'signed_approved')
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.status, 'completed')

    def test_changed_payment_facts_still_prevent_accepting_the_previous_document(self):
        self.farmer.balance_due = Decimal('2000')
        self.farmer.save(update_fields=['balance_due'])
        response = self.upload()
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn('changed after review', json.loads(response.content)['error'])
        self.storage.return_value.upload.assert_not_called()
        self.assertFalse(DocumentPhysicalSignoff.objects.exists())

    def test_wrong_file_type_and_out_of_scope_upload_still_fail_before_storage(self):
        response = self.upload(filename='not-a-scan.xlsx', content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        self.assertEqual(response.status_code, 400)
        with patch('core.api.portal_views._portal_saved_document_in_scope', return_value=False):
            response = self.upload()
        self.assertEqual(response.status_code, 403)
        self.storage.return_value.upload.assert_not_called()
        self.assertFalse(DocumentPhysicalSignoff.objects.exists())
