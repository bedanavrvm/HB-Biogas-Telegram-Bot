from datetime import date
from hashlib import sha256
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import TestCase
from django.utils import timezone
from django.core.management import call_command
from django.core.exceptions import ValidationError
from io import StringIO

from core.models import DocumentPhysicalSignoff, GroupSheetConfiguration, JawabuFarmerMaster, RequisitionBatch, PaymentDocument
from core.services.document_signoffs import source_artifact, PhysicalSignoffError
from core.services.invoice_parser import official_requisition_eligibility
from requisitions.models import OrderSequenceState, OrderNumberClaim, OrderWorkbookVersion
from requisitions.services import cancel_order, claim_number, proposed_number, resolve_order, retain_finalized_requisition, unsigned_daily_orders
from payments.models import PaymentBatch, PaymentSequenceState, PaymentNumberClaim
from payments.services import _allocate_payment_number_for_generation, cancel_batch
from core.models import JawabuApprovalRecord
from core.services.jawabu_approvals import approval_is_effective


class UnsignedFinanceWorkspaceTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user(username='synthetic-operator')
        self.group = GroupSheetConfiguration.objects.create(group_id='-100-training-finance', workflow={'type': 'jawabu_homebiogas'})
        self.sequence = OrderSequenceState.objects.create(group_configuration=self.group, partner='HB', next_number=10)

    def order(self, number='HB-10', *, claim=True):
        with transaction.atomic():
            batch = retain_finalized_requisition(group_configuration=self.group, fulfillment_partner='HB',
                order_number=number, version=1, finalized_at=timezone.now(), finalized_by=self.actor,
                filename=f'{number}.xlsx', file_content=b'training-workbook', content_checksum=sha256(b'training-workbook').hexdigest(),
                farmer_ids=[], requisition_date=date(2026, 10, 6))
            if claim:
                claim_number(self.sequence, batch, actor=self.actor, request_id=f'generate:{batch.pk}')
        return batch

    def sign(self, batch):
        return DocumentPhysicalSignoff.objects.create(document_type='requisition', requisition_batch=batch,
            source_version=batch.version, source_checksum=batch.content_checksum, status='signed_approved',
            uploaded_by=self.actor, approved_by=self.actor, approved_at=timezone.now(), source_filename=batch.filename,
            source_content_type=batch.content_type, scan_filename='training-scan.pdf', scan_content_type='application/pdf', scan_checksum='a' * 64)

    def test_preview_does_not_consume_and_partner_is_independent(self):
        self.assertEqual(proposed_number(self.sequence), 10)
        self.assertEqual(proposed_number(self.sequence), 10)
        self.sequence.refresh_from_db()
        self.assertEqual(self.sequence.next_number, 10)
        eco = OrderSequenceState.objects.create(group_configuration=self.group, partner='ECOCONSERVE', next_number=4)
        self.assertEqual(proposed_number(eco), 4)

    def test_cancel_releases_number_without_rewinding_or_deleting_bytes(self):
        original = self.order()
        cancelled = cancel_order(original.pk, expected_version=1, actor=self.actor, request_id='cancel-1')
        self.assertEqual(cancelled.status, 'cancelled')
        self.sequence.refresh_from_db()
        self.assertEqual(self.sequence.next_number, 11)
        self.assertEqual(proposed_number(self.sequence), 10)
        replacement = self.order()
        self.assertNotEqual(original.pk, replacement.pk)
        self.assertEqual(OrderNumberClaim.objects.get(sequence=self.sequence, number=10).batch_id, replacement.pk)
        self.assertEqual(OrderWorkbookVersion.objects.filter(batch=original).count(), 1)
        with self.assertRaises(ValueError):
            resolve_order('HB-10')
        self.assertEqual(resolve_order(str(original.pk)).pk, original.pk)

    def test_signed_order_cannot_cancel_or_be_offered_for_append(self):
        batch = self.order()
        self.sign(batch)
        with self.assertRaisesMessage(ValueError, 'signed order is final'):
            cancel_order(batch.pk, expected_version=1, actor=self.actor, request_id='cancel-signed')
        self.assertEqual(unsigned_daily_orders(self.sequence, batch.requisition_date), [])

    def test_cancel_releases_case_without_invalidating_credit_or_final_approval(self):
        batch = self.order()
        farmer = JawabuFarmerMaster.objects.create(group_configuration=self.group,
            customer_name='Training Reviewed Case', order_number=batch.order_number,
            requisition_date=batch.requisition_date, requisition_batch=batch,
            credit_decision='Approved', final_decision='Approved', workflow_state='invoice')
        for gate in ('credit', 'final_review'):
            JawabuApprovalRecord.objects.create(farmer=farmer, gate=gate, decision='approved', decided_by=self.actor)
        batch.farmer_ids = [str(farmer.pk)]
        batch.save(update_fields=['farmer_ids'])
        with patch('core.services.portal_publication.reserve_farmer_publication'):
            cancel_order(batch.pk, expected_version=1, actor=self.actor, request_id='release-training-case')
        farmer.refresh_from_db()
        self.assertFalse(farmer.order_number)
        self.assertIsNone(farmer.requisition_batch_id)
        self.assertEqual(farmer.workflow_state, 'order')
        for gate in ('credit', 'final_review'):
            self.assertTrue(approval_is_effective(farmer, gate))
        self.assertEqual((farmer.credit_decision, farmer.final_decision), ('Approved', 'Approved'))

    def test_cancel_replay_is_bound_to_actor_and_workspace(self):
        batch = self.order()
        cancel_order(batch.pk, expected_version=1, actor=self.actor, request_id='same-cancel')
        replay = cancel_order(batch.pk, expected_version=1, actor=self.actor, request_id='same-cancel')
        self.assertEqual(replay.pk, batch.pk)
        other = get_user_model().objects.create_user(username='another-training-operator')
        with self.assertRaises(ValueError):
            cancel_order(batch.pk, expected_version=1, actor=other, request_id='same-cancel')

    def test_retained_workbook_cannot_be_edited_in_place(self):
        batch = self.order()
        version = batch.workbook_versions.get(version=1)
        version.file_content = b'changed-bytes'
        with self.assertRaises(ValidationError):
            version.save()
        version.refresh_from_db()
        self.assertEqual(bytes(version.file_content), b'training-workbook')

    def test_cancelled_workbook_cannot_receive_scan(self):
        batch = self.order()
        cancel_order(batch.pk, expected_version=1, actor=self.actor, request_id='cancel-before-scan')
        with self.assertRaises(PhysicalSignoffError):
            source_artifact('requisition', str(batch.pk))

    def test_invoice_requires_current_signed_version_and_exact_workspace(self):
        batch = self.order()
        farmer = JawabuFarmerMaster.objects.create(customer_name='Training Applicant', order_number=batch.order_number,
            requisition_date=batch.requisition_date, requisition_batch=batch)
        batch.farmer_ids = [str(farmer.pk)]
        batch.save(update_fields=['farmer_ids'])
        self.assertEqual(official_requisition_eligibility(farmer)['code'], 'invoice_order_unsigned')
        self.sign(batch)
        self.assertTrue(official_requisition_eligibility(farmer)['eligible'])
        batch.version += 1
        batch.save(update_fields=['version'])
        self.assertFalse(official_requisition_eligibility(farmer)['eligible'])

    def test_payment_cancel_reuses_number_and_preserves_batch_identity(self):
        sequence = PaymentSequenceState.objects.create(group_configuration=self.group, next_number=20)
        first = PaymentBatch.objects.create(group_configuration=self.group)
        with transaction.atomic():
            _allocate_payment_number_for_generation(first, actor=self.actor, request_id='pay-a')
            first.save()
        cancel_batch(first.pk, reason='', expected_revision=1, actor=self.actor, request_id='cancel-payment')
        second = PaymentBatch.objects.create(group_configuration=self.group)
        with transaction.atomic():
            _allocate_payment_number_for_generation(second, actor=self.actor, request_id='pay-b')
            second.save()
        self.assertEqual(second.payment_number, first.payment_number)
        sequence.refresh_from_db()
        self.assertEqual(sequence.next_number, 21)
        self.assertEqual(PaymentNumberClaim.objects.get(sequence=sequence, number=20).batch_id, second.pk)

    def test_untracked_historical_cancel_does_not_make_reusable_slot(self):
        self.order('HB-3', claim=False)
        batch = self.order('HB-4', claim=False)
        cancel_order(batch.pk, expected_version=1, actor=self.actor, request_id='cancel-legacy')
        self.assertEqual(proposed_number(self.sequence), 10)

    def test_missing_sequence_returns_actionable_error_without_mutation(self):
        batch = self.order('HB-3', claim=False)
        self.sequence.delete()
        with self.assertRaisesMessage(ValueError, 'Ask IT to configure'):
            cancel_order(batch.pk, expected_version=1, actor=self.actor, request_id='cancel-without-sequence')
        batch.refresh_from_db()
        self.assertEqual(batch.status, 'generated')

    def test_stale_upload_cannot_publish_over_an_amended_workspace(self):
        batch = self.order()
        def upload(*args, **kwargs):
            RequisitionBatch.objects.filter(pk=batch.pk).update(version=2, content_checksum='b' * 64)
            return 'synthetic-file', 'https://example.invalid/training'
        with patch('core.services.order_approval.GoogleDriveMediaStorage') as storage:
            storage.return_value.upload.side_effect = upload
            from core.services.document_sync import retry_requisition_batch_upload
            result = retry_requisition_batch_upload(batch)
        self.assertFalse(result['ok'])
        batch.refresh_from_db()
        self.assertEqual(batch.version, 2)
        self.assertFalse(batch.drive_url)

    def test_delivery_archive_preserves_items_and_cancel_releases_delivery(self):
        from payments.models import PaymentReceiptBatch
        from payments.receipt_batches import set_archived
        receipt = PaymentReceiptBatch.objects.create(group_configuration=self.group)
        archived = set_archived(receipt.pk, archived=True, expected_revision=1,
            actor=self.actor, request_id='archive-training')
        self.assertIsNotNone(archived.archived_at)
        replay = set_archived(receipt.pk, archived=True, expected_revision=1,
            actor=self.actor, request_id='archive-training')
        self.assertEqual(replay.revision, archived.revision)
        restored = set_archived(receipt.pk, archived=False, expected_revision=archived.revision,
            actor=self.actor, request_id='restore-training')
        self.assertIsNone(restored.archived_at)
        batch = PaymentBatch.objects.create(group_configuration=self.group, receipt_batch=receipt)
        cancel_batch(batch.pk, reason='', expected_revision=1, actor=self.actor, request_id='cancel-receipt-payment')
        batch.refresh_from_db()
        self.assertIsNone(batch.receipt_batch_id)
        self.assertEqual(batch.events.get(action='cancelled').metadata['receipt_batch_id'], str(receipt.pk))

    def test_payment_with_accepted_scan_cannot_cancel_even_if_status_drifted(self):
        document = PaymentDocument.objects.create(payment_number='20', version=1,
            filename='training-payment.xlsx', file_content=b'training-workbook',
            status='awaiting_scan')
        batch = PaymentBatch.objects.create(group_configuration=self.group, current_document=document,
            status=PaymentBatch.STATUS_AWAITING_SCAN)
        DocumentPhysicalSignoff.objects.create(document_type='payment', payment_document=document,
            source_version=1, source_checksum=sha256(bytes(document.file_content)).hexdigest(), status='signed_approved',
            uploaded_by=self.actor, approved_by=self.actor, approved_at=timezone.now(),
            scan_filename='training-scan.pdf', scan_content_type='application/pdf', scan_checksum='b' * 64)
        with self.assertRaisesMessage(ValueError, 'signed'):
            cancel_batch(batch.pk, reason='', expected_revision=1, actor=self.actor, request_id='cancel-signed-payment')

    def test_legacy_financial_evidence_is_not_offered_for_amendment(self):
        batch = self.order()
        farmer = JawabuFarmerMaster.objects.create(customer_name='Training Legacy Invoice',
            group_configuration=self.group, order_number=batch.order_number,
            requisition_date=batch.requisition_date, requisition_batch=batch, invoice_number='training-invoice')
        batch.farmer_ids = [str(farmer.pk)]
        batch.save(update_fields=['farmer_ids'])
        self.assertEqual(unsigned_daily_orders(self.sequence, batch.requisition_date), [])
        before = farmer.workflow_revision
        output = StringIO()
        call_command('audit_finance_order_links', configuration=self.group.pk, stdout=output)
        self.assertIn('unsigned_order', output.getvalue())
        farmer.refresh_from_db()
        self.assertEqual(farmer.workflow_revision, before)
        self.assertEqual(farmer.invoice_number, 'training-invoice')
