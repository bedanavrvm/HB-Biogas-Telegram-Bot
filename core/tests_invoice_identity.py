from datetime import date
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from core.models import (
    InvoiceIdentityReview, InvoiceUploadBatch, JawabuDataQualityIssue,
    JawabuFarmerMaster, JawabuRelatedPerson, ParsedInvoice,
)
from core.services.invoice_identity import (
    InvoiceCorrectionConflict,
    NameChangeBatchConflict,
    assemble_name_change_batch,
    close_name_change,
    confirm_replacement,
    create_name_change,
    create_name_change_follow_up,
    decide_identity_review,
    discrepancy_codes,
    ensure_identity_review,
    identity_gate,
    mark_name_change_sent,
    start_invoice_correction,
)
from core.services.payment_documents import payment_readiness


class InvoiceIdentityWorkflowTests(TestCase):
    def setUp(self):
        self.farmer = JawabuFarmerMaster.objects.create(
            customer_name='Mary Wanjiku',
            imab_customer_name='MARY WANJIKU',
            national_id='12345678',
            primary_phone='0712345678',
            customer_no='C-1',
            order_number='ORDER-1',
            status='active',
        )
        self.batch = InvoiceUploadBatch.objects.create(original_filename='invoice.pdf', status='parsed')

    def invoice(self, **overrides):
        values = {
            'batch': self.batch,
            'invoice_no': 'INV-1',
            'customer_name': 'Mary Wanjiko',
            'customer_id': '12 345 678',
            'customer_phone': '254712345678',
            'balance_due': Decimal('43000'),
            'status': 'matched',
            'matched_farmer': self.farmer,
            'matched_order_number': self.farmer.order_number,
        }
        values.update(overrides)
        return ParsedInvoice.objects.create(**values)

    def test_misspelled_name_with_same_normalized_id_is_informational(self):
        invoice = self.invoice()
        self.assertEqual(discrepancy_codes(invoice, self.farmer), ['name_variance'])
        review = ensure_identity_review(invoice, self.farmer)
        self.assertIsNone(review)
        gate = identity_gate(invoice, self.farmer)
        self.assertEqual(gate['blocker'], '')
        self.assertEqual(gate['status_label'], 'Matched')
        self.assertFalse(invoice.name_change_requests.exists())

    def test_same_id_phone_difference_is_verification_only(self):
        invoice = self.invoice(customer_name='MARY WANJIKU', customer_phone='0700000000')
        self.assertEqual(discrepancy_codes(invoice, self.farmer), ['phone_mismatch'])
        review = ensure_identity_review(invoice, self.farmer)
        self.assertIsNone(review)
        self.assertEqual(identity_gate(invoice, self.farmer)['blocker'], '')

    def test_name_or_phone_variance_with_same_id_cannot_start_name_change(self):
        invoice = self.invoice(customer_name='M. Wanjiku', customer_phone='0700000000')
        with self.assertRaisesMessage(ValueError, 'national IDs match'):
            start_invoice_correction(
                invoice, actor='Operations', relationship_type='spouse', explanation='', confirmed=True,
                expected_invoice_revision=invoice.revision,
                expected_application_revision=self.farmer.workflow_revision,
                client_request_id='same-id-change',
            )

    def test_different_ids_cannot_be_confirmed_as_same_person(self):
        invoice = self.invoice(customer_id='87654321', customer_name='Jane Wanjiku')
        review = ensure_identity_review(invoice, self.farmer)
        with self.assertRaisesMessage(ValueError, 'Different national IDs'):
            decide_identity_review(review, outcome='same_person_confirmed', actor='Operations', note='Incorrect decision')

    def test_name_change_preserves_applicant_and_supersedes_original_on_replacement(self):
        original = self.invoice(customer_id='87654321', customer_name='Jane Wanjiku', customer_phone='0700000000')
        review = ensure_identity_review(original, self.farmer)
        decide_identity_review(review, outcome='different_person_confirmed', actor='Operations', note='Confirmed spouse invoice.')
        item = create_name_change(
            review,
            actor='Operations',
            relationship_type='spouse',
            related_name='Jane Wanjiku',
            related_national_id='87654321',
            related_phone='0700000000',
            attestation_note='Applicant and supporting record confirm spouse.',
            evidence_reference='drive-reference-1',
            client_request_id='change-request-1',
        )
        self.assertIsNotNone(item.batch_id)
        self.assertEqual(identity_gate(original, self.farmer)['blocker'], 'invoice_name_change_pending')
        item.batch.legacy_manual_letter_allowed = True
        item.batch.save(update_fields=['legacy_manual_letter_allowed', 'updated_at'])
        mark_name_change_sent(
            item.batch, actor='Operations', letter_reference='drive-letter-1', sent_reference='HB-email-1'
        )
        replacement = self.invoice(
            invoice_no='INV-2', customer_name='Mary Wanjiku', customer_id='12345678',
            status='unmatched', matched_farmer=None, matched_order_number='', invoice_date=date(2026, 8, 11),
        )

        confirm_replacement(item, replacement, actor='Operations')

        original.refresh_from_db()
        replacement.refresh_from_db()
        self.farmer.refresh_from_db()
        item.refresh_from_db()
        self.assertEqual(original.status, 'superseded')
        self.assertEqual(replacement.status, 'matched')
        self.assertEqual(item.status, 'completed')
        self.assertEqual(self.farmer.customer_name, 'Mary Wanjiku')
        self.assertEqual(self.farmer.national_id, '12345678')
        self.assertEqual(self.farmer.invoice_number, 'INV-2')

    def test_missing_invoice_id_stays_blocked_for_manual_verification(self):
        invoice = self.invoice(customer_id='')
        self.assertIn('national_id_missing', discrepancy_codes(invoice, self.farmer))
        ensure_identity_review(invoice, self.farmer)
        self.assertEqual(identity_gate(invoice, self.farmer)['blocker'], 'invoice_identity_verification_pending')
        self.farmer.invoice_number = invoice.invoice_no
        self.farmer.save(update_fields=['invoice_number', 'updated_at'])
        readiness = payment_readiness(self.farmer.order_number)
        self.assertIn('invoice_identity_verification_pending', readiness['blocked'][0]['blocker_codes'])

    def test_flagged_review_stays_blocked_and_hides_specialist_note_from_general_projection(self):
        original = self.invoice(customer_id='87654321', customer_name='Jane Wanjiku')
        review = ensure_identity_review(original, self.farmer)

        review = decide_identity_review(
            review, outcome=InvoiceIdentityReview.STATUS_FLAGGED,
            actor='Operations', note='Escalated due to conflicting evidence.',
        )

        gate = identity_gate(original, self.farmer)
        self.assertEqual(gate['blocker'], 'invoice_identity_flagged')
        self.assertEqual(gate['review']['decision_note'], '')
        review.refresh_from_db()
        self.assertEqual(review.decision_note, 'Escalated due to conflicting evidence.')

    def test_verified_name_change_gets_a_private_single_case_batch(self):
        original = self.invoice(customer_id='87654321', customer_name='Jane Wanjiku')
        review = ensure_identity_review(original, self.farmer)
        decide_identity_review(
            review, outcome='different_person_confirmed', actor='Operations',
            note='Confirmed spouse invoice.',
        )
        item = create_name_change(
            review, actor='Operations', relationship_type='spouse',
            related_name='Jane Wanjiku', related_national_id='87654321',
            related_phone='0700000000', attestation_note='Relationship verified.',
            evidence_reference='evidence-1', client_request_id='independent-request-1',
        )

        self.assertIsNotNone(item.batch_id)
        self.assertEqual(item.batch.items.count(), 1)
        with self.assertRaises(NameChangeBatchConflict):
            assemble_name_change_batch([item], actor='Operations', client_request_id='assembled-batch-2')

    def test_inline_correction_is_idempotent_and_reuses_related_person_by_exact_id(self):
        existing = JawabuRelatedPerson.objects.create(
            full_name='Jane Wanjiku', national_id='87 654 321', primary_phone='254700000000',
        )
        invoice = self.invoice(customer_id='87654321', customer_name='Jane Wanjiku')
        item = start_invoice_correction(
            invoice, actor='Operations', relationship_type='spouse', explanation='', confirmed=True,
            expected_invoice_revision=invoice.revision,
            expected_application_revision=self.farmer.workflow_revision,
            client_request_id='inline-change-1',
        )
        replay = start_invoice_correction(
            invoice, actor='Operations', relationship_type='spouse', explanation='', confirmed=True,
            expected_invoice_revision=invoice.revision,
            expected_application_revision=self.farmer.workflow_revision,
            client_request_id='inline-change-1',
        )
        self.assertEqual(item.id, replay.id)
        self.assertEqual(item.relationship.related_person_id, existing.id)
        self.assertEqual(item.batch.items.count(), 1)

    def test_inline_correction_locks_nullable_farmer_independently(self):
        invoice = self.invoice(customer_id='87654321', customer_name='Jane Wanjiku')

        with CaptureQueriesContext(connection) as captured:
            item = start_invoice_correction(
                invoice, actor='Operations', relationship_type='spouse', explanation='', confirmed=True,
                expected_invoice_revision=invoice.revision,
                expected_application_revision=self.farmer.workflow_revision,
                client_request_id='inline-independent-locks',
            )

        invoice_reads = [
            query['sql'].upper() for query in captured.captured_queries
            if 'FROM "CORE_PARSEDINVOICE"' in query['sql'].upper()
        ]
        farmer_reads = [
            query['sql'].upper() for query in captured.captured_queries
            if 'FROM "CORE_JAWABUFARMERMASTER"' in query['sql'].upper()
        ]
        self.assertIsNotNone(item.pk)
        self.assertTrue(any('JOIN' not in query for query in invoice_reads))
        self.assertTrue(any('JOIN' not in query for query in farmer_reads))

    def test_inline_correction_rejects_stale_invoice_or_application_revision(self):
        invoice = self.invoice(customer_id='87654321', customer_name='Jane Wanjiku')
        with self.assertRaisesMessage(InvoiceCorrectionConflict, 'invoice changed'):
            start_invoice_correction(
                invoice, actor='Operations', relationship_type='spouse', explanation='', confirmed=True,
                expected_invoice_revision=invoice.revision + 1,
                expected_application_revision=self.farmer.workflow_revision,
                client_request_id='inline-stale-invoice',
            )
        with self.assertRaisesMessage(InvoiceCorrectionConflict, 'applicant changed'):
            start_invoice_correction(
                invoice, actor='Operations', relationship_type='spouse', explanation='', confirmed=True,
                expected_invoice_revision=invoice.revision,
                expected_application_revision=self.farmer.workflow_revision + 1,
                client_request_id='inline-stale-applicant',
            )
        self.assertFalse(invoice.name_change_requests.exists())

    def test_duplicate_related_person_ids_block_without_creating_another_person(self):
        JawabuRelatedPerson.objects.create(full_name='Jane One', national_id='87654321')
        JawabuRelatedPerson.objects.create(full_name='Jane Two', national_id='87 654 321')
        invoice = self.invoice(customer_id='87654321', customer_name='Jane Wanjiku')
        with self.assertRaisesMessage(ValueError, 'Several household records'):
            start_invoice_correction(
                invoice, actor='Operations', relationship_type='spouse', explanation='', confirmed=True,
                expected_invoice_revision=invoice.revision,
                expected_application_revision=self.farmer.workflow_revision,
                client_request_id='inline-change-conflict',
            )
        self.assertEqual(JawabuRelatedPerson.objects.count(), 2)
        self.assertTrue(JawabuDataQualityIssue.objects.filter(
            farmer=self.farmer, code='duplicate_related_person_national_id', active=True,
        ).exists())

    def test_cancelled_request_can_start_linked_follow_up_that_requires_reverification(self):
        original = self.invoice(customer_id='87654321', customer_name='Jane Wanjiku')
        review = ensure_identity_review(original, self.farmer)
        decide_identity_review(
            review, outcome='different_person_confirmed', actor='Operations',
            note='Confirmed spouse invoice.',
        )
        item = create_name_change(
            review, actor='Operations', relationship_type='spouse',
            related_name='Jane Wanjiku', related_national_id='87654321',
            related_phone='0700000000', attestation_note='Relationship verified.',
            evidence_reference='evidence-1', client_request_id='cancel-request-1',
        )
        close_name_change(item, actor='Operations', reason='Request was opened in error.')

        follow_up = create_name_change_follow_up(
            item, actor='Operations', client_request_id='follow-up-request-1',
        )

        self.assertEqual(follow_up.follow_up_of_id, item.id)
        self.assertEqual(follow_up.review.status, InvoiceIdentityReview.STATUS_PENDING)
        with self.assertRaises(NameChangeBatchConflict):
            assemble_name_change_batch(
                [follow_up], actor='Operations', client_request_id='follow-up-batch-1',
            )
