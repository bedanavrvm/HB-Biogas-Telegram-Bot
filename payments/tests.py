from decimal import Decimal
from unittest.mock import patch

from django.apps import apps
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from openpyxl import Workbook

from core.models import GroupSheetConfiguration, JawabuFarmerMaster, PaymentDocument
from core.services.payment_documents import _write_payment_mode
from payments.models import PaymentBatch, PaymentCaseReview, PaymentSequenceState
from payments.services import (
    PaymentBatchError,
    add_cases,
    adjust_sequence,
    cancel_batch,
    complete_batch_for_document,
    create_batch,
    generate_reviewed_workbook,
    remove_case,
    review_case,
    serialize_batch,
    submit_for_review,
    update_mode,
)


class PaymentBatchServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='payment-operator')
        self.group = GroupSheetConfiguration.objects.create(
            group_id='-100-payment-test', display_name='Payment test', enabled=True,
            sheet_id='test-sheet', workflow={'type': 'jawabu_homebiogas'},
        )

    def farmer(self, suffix):
        return JawabuFarmerMaster.objects.create(
            customer_name=f'Customer {suffix}', national_id=f'12345{suffix}',
            primary_phone=f'25470000{suffix}', customer_no=f'CUST-{suffix}',
            order_number=f'ORDER-{suffix}', invoice_number=f'INV-{suffix}',
            balance_due=Decimal('1000'), repayment_date='10TH', repayment_day=10,
            repayment_tenor='6', repayment_tenor_months=6,
            payment_product='Business', final_decision='Approved', workflow_revision=1,
        )

    @staticmethod
    def ready(*args, farmer_ids=None, **kwargs):
        return {
            'ready': [{'farmer_id': value, 'row': {}} for value in (farmer_ids or [])],
            'blocked': [], 'ready_count': len(farmer_ids or []), 'blocked_count': 0,
        }

    def test_modes_are_governed(self):
        self.assertEqual(create_batch(group_configuration=self.group, payment_mode='CASH').payment_mode, 'CASH')
        with self.assertRaisesMessage(PaymentBatchError, 'Choose Loan - Jawabu or Cash'):
            create_batch(group_configuration=self.group, payment_mode='CHEQUE')

    def test_request_key_replays_only_the_same_payment_meaning(self):
        batch = create_batch(
            group_configuration=self.group, payment_mode='CASH', request_id='create-payment-1',
        )
        replay = create_batch(
            group_configuration=self.group, payment_mode='CASH', request_id='create-payment-1',
        )
        self.assertEqual(replay.pk, batch.pk)
        with self.assertRaisesMessage(PaymentBatchError, 'different payment change'):
            create_batch(
                group_configuration=self.group, payment_mode='LOAN-JAWABU',
                request_id='create-payment-1',
            )

    @patch('payments.services.payment_readiness', side_effect=ready.__func__)
    def test_payment_numbers_allocate_consecutively_and_retry_idempotently(self, _readiness):
        first_farmer, second_farmer = self.farmer('01'), self.farmer('02')
        first = create_batch(group_configuration=self.group, payment_mode='LOAN-JAWABU')
        first = add_cases(first.id, farmer_ids=[first_farmer.id], expected_revision=first.revision)
        prior_revision = first.revision
        first = submit_for_review(first.id, expected_revision=prior_revision, actor=self.user, request_id='submit-1')
        replay = submit_for_review(first.id, expected_revision=prior_revision, actor=self.user, request_id='submit-1')
        second = create_batch(group_configuration=self.group, payment_mode='CASH')
        second = add_cases(second.id, farmer_ids=[second_farmer.id], expected_revision=second.revision)
        second = submit_for_review(second.id, expected_revision=second.revision, actor=self.user, request_id='submit-2')
        self.assertEqual((first.payment_number, replay.payment_number, second.payment_number), (1, 1, 2))
        self.assertEqual(PaymentSequenceState.objects.get(group_configuration=self.group).next_number, 3)

    @patch('payments.services.payment_readiness', side_effect=ready.__func__)
    def test_review_progress_is_durable_and_changed_values_invalidate_only_that_case(self, _readiness):
        first_farmer, second_farmer = self.farmer('03'), self.farmer('04')
        batch = create_batch(group_configuration=self.group, payment_mode='LOAN-JAWABU')
        batch = add_cases(batch.id, farmer_ids=[first_farmer.id, second_farmer.id], expected_revision=batch.revision)
        batch = submit_for_review(batch.id, expected_revision=batch.revision)
        batch = review_case(
            batch.id, first_farmer.id, decision='approved', comment='Payment details confirmed.',
            expected_revision=batch.revision, actor=self.user,
        )
        payload = serialize_batch(batch)
        self.assertEqual(payload['counts']['approved'], 1)
        self.assertEqual(payload['counts']['pending'], 1)
        first_farmer.balance_due = Decimal('1200')
        first_farmer.save(update_fields=['balance_due', 'updated_at'])
        payload = serialize_batch(PaymentBatch.objects.get(pk=batch.pk))
        self.assertEqual(payload['counts']['approved'], 0)
        self.assertEqual(payload['counts']['changed'], 1)

    @patch('payments.services.payment_readiness', side_effect=ready.__func__)
    def test_membership_change_before_scan_supersedes_workbook(self, _readiness):
        farmer = self.farmer('05')
        batch = create_batch(group_configuration=self.group, payment_mode='CASH')
        batch = add_cases(batch.id, farmer_ids=[farmer.id], expected_revision=batch.revision)
        document = PaymentDocument.objects.create(
            order_number='PAYMENT-1', payment_number='1', status='awaiting_scan', version=1,
        )
        batch.payment_number = 1
        batch.status = PaymentBatch.STATUS_AWAITING_SCAN
        batch.current_document = document
        batch.save()
        batch = remove_case(
            batch.id, farmer.id, reason='Customer moved to a later payment.',
            expected_revision=batch.revision, actor=self.user,
        )
        document.refresh_from_db()
        self.assertEqual(document.status, 'superseded')
        self.assertIsNone(batch.current_document_id)
        self.assertFalse(batch.case_memberships.get(farmer=farmer).is_active)

    @patch('payments.services.payment_readiness', side_effect=ready.__func__)
    def test_signed_scan_completion_locks_membership(self, _readiness):
        farmer = self.farmer('06')
        batch = create_batch(group_configuration=self.group, payment_mode='LOAN-JAWABU')
        batch = add_cases(batch.id, farmer_ids=[farmer.id], expected_revision=batch.revision)
        document = PaymentDocument.objects.create(
            order_number='PAYMENT-1', payment_number='1', status='awaiting_scan', version=1,
        )
        batch.payment_number = 1
        batch.status = PaymentBatch.STATUS_AWAITING_SCAN
        batch.current_document = document
        batch.save()
        batch = complete_batch_for_document(document, actor=self.user)
        self.assertEqual(batch.status, PaymentBatch.STATUS_COMPLETED)
        document.refresh_from_db()
        self.assertEqual(document.status, 'completed')
        with self.assertRaisesMessage(PaymentBatchError, 'cannot be removed'):
            remove_case(batch.id, farmer.id, reason='Too late', expected_revision=batch.revision)

    @patch('payments.services.payment_readiness', side_effect=ready.__func__)
    def test_remove_requires_reason(self, _readiness):
        farmer = self.farmer('07')
        batch = create_batch(group_configuration=self.group, payment_mode='CASH')
        batch = add_cases(batch.id, farmer_ids=[farmer.id], expected_revision=batch.revision)
        with self.assertRaisesMessage(PaymentBatchError, 'Give a reason'):
            remove_case(batch.id, farmer.id, reason='', expected_revision=batch.revision)

    @patch('payments.services.payment_readiness', side_effect=ready.__func__)
    def test_cancelling_releases_case_but_keeps_membership_history(self, _readiness):
        farmer = self.farmer('08')
        first = create_batch(group_configuration=self.group, payment_mode='CASH')
        first = add_cases(first.id, farmer_ids=[farmer.id], expected_revision=first.revision)
        first = cancel_batch(
            first.id, reason='Rebuild with a different set of clients.',
            expected_revision=first.revision, actor=self.user,
        )
        second = create_batch(group_configuration=self.group, payment_mode='LOAN-JAWABU')
        second = add_cases(second.id, farmer_ids=[farmer.id], expected_revision=second.revision)
        self.assertEqual(first.status, PaymentBatch.STATUS_CANCELLED)
        self.assertTrue(first.case_memberships.get(farmer=farmer).is_active)
        self.assertTrue(second.case_memberships.get(farmer=farmer).is_active)

    @patch('payments.services.payment_readiness', side_effect=ready.__func__)
    def test_sequence_adjustment_cannot_reuse_an_allocated_number(self, _readiness):
        farmer = self.farmer('09')
        batch = create_batch(group_configuration=self.group, payment_mode='CASH')
        batch = add_cases(batch.id, farmer_ids=[farmer.id], expected_revision=batch.revision)
        batch = submit_for_review(batch.id, expected_revision=batch.revision)
        with self.assertRaisesMessage(PaymentBatchError, 'higher than the allocated number 1'):
            adjust_sequence(group_configuration=self.group, next_number=1, reason='Unsafe rollback', actor=self.user)
        state = adjust_sequence(
            group_configuration=self.group, next_number=20,
            reason='Continue from the finance register.', actor=self.user, request_id='adjust-20',
        )
        replay = adjust_sequence(
            group_configuration=self.group, next_number=20,
            reason='Continue from the finance register.', actor=self.user, request_id='adjust-20',
        )
        self.assertEqual((state.next_number, replay.next_number), (20, 20))
        with self.assertRaisesMessage(PaymentBatchError, 'already used for a different'):
            adjust_sequence(
                group_configuration=self.group, next_number=21,
                reason='A different operation.', actor=self.user, request_id='adjust-20',
            )
        with self.assertRaisesMessage(PaymentBatchError, 'changed while you were working'):
            adjust_sequence(
                group_configuration=self.group, next_number=21,
                reason='Valid new number, stale screen.', actor=self.user, expected_revision=1,
            )

    @patch('payments.services.payment_readiness', side_effect=ready.__func__)
    def test_mode_or_membership_change_invalidates_existing_case_approvals(self, _readiness):
        first_farmer, second_farmer = self.farmer('11'), self.farmer('12')
        batch = create_batch(group_configuration=self.group, payment_mode='CASH')
        batch = add_cases(batch.id, farmer_ids=[first_farmer.id], expected_revision=batch.revision)
        batch = submit_for_review(batch.id, expected_revision=batch.revision)
        batch = review_case(
            batch.id, first_farmer.id, decision='approved', comment='Confirmed.',
            expected_revision=batch.revision, actor=self.user,
        )
        batch = update_mode(
            batch.id, payment_mode='LOAN-JAWABU', expected_revision=batch.revision, actor=self.user,
        )
        self.assertEqual(batch.case_memberships.get(farmer=first_farmer).review.decision, 'pending')

        batch = review_case(
            batch.id, first_farmer.id, decision='approved', comment='Confirmed again.',
            expected_revision=batch.revision, actor=self.user,
        )
        batch = add_cases(batch.id, farmer_ids=[second_farmer.id], expected_revision=batch.revision)
        self.assertEqual(batch.case_memberships.get(farmer=first_farmer).review.decision, 'pending')

    @patch('payments.services.payment_readiness', side_effect=ready.__func__)
    def test_changed_payment_values_block_generation_and_reopen_review(self, _readiness):
        farmer = self.farmer('13')
        batch = create_batch(group_configuration=self.group, payment_mode='CASH')
        batch = add_cases(batch.id, farmer_ids=[farmer.id], expected_revision=batch.revision)
        batch = submit_for_review(batch.id, expected_revision=batch.revision)
        batch = review_case(
            batch.id, farmer.id, decision='approved', comment='Ready.',
            expected_revision=batch.revision, actor=self.user,
        )
        farmer.repayment_date = '15TH'
        farmer.save(update_fields=['repayment_date', 'updated_at'])
        with patch('payments.services.create_payment_document') as generator:
            with self.assertRaisesMessage(PaymentBatchError, 'changed after review'):
                generate_reviewed_workbook(batch.id, expected_revision=batch.revision, actor=self.user)
        generator.assert_not_called()
        batch.refresh_from_db()
        self.assertEqual(batch.status, PaymentBatch.STATUS_IN_REVIEW)
        self.assertEqual(batch.case_memberships.get(farmer=farmer).review.decision, 'pending')

    @patch('payments.services.payment_readiness', side_effect=ready.__func__)
    def test_batch_change_during_generation_supersedes_generated_workbook(self, _readiness):
        farmer = self.farmer('10')
        batch = create_batch(group_configuration=self.group, payment_mode='CASH')
        batch = add_cases(batch.id, farmer_ids=[farmer.id], expected_revision=batch.revision)
        batch = submit_for_review(batch.id, expected_revision=batch.revision)
        batch = review_case(
            batch.id, farmer.id, decision='approved', comment='Ready for payment.',
            expected_revision=batch.revision, actor=self.user,
        )
        document = PaymentDocument.objects.create(
            order_number='PAYMENT-1', payment_number='1', status='awaiting_scan', version=1,
        )

        def mutate_during_generation(*args, **kwargs):
            PaymentBatch.objects.filter(pk=batch.pk).update(revision=batch.revision + 1)
            return document

        with patch('payments.services.create_payment_document', side_effect=mutate_during_generation):
            with self.assertRaisesMessage(PaymentBatchError, 'changed while the workbook was being generated'):
                generate_reviewed_workbook(batch.id, expected_revision=batch.revision, actor=self.user)
        document.refresh_from_db()
        self.assertEqual(document.status, 'superseded')


class PaymentWorkflowContractTests(TestCase):
    def test_payment_mode_marker_supports_configured_and_detected_cells(self):
        configured = Workbook()
        ws = configured.active
        self.assertTrue(_write_payment_mode(ws, {'payment_mode_cell': 'D4'}, 'CASH'))
        self.assertEqual(ws['D4'].value, 'CASH')

        detected = Workbook()
        ws = detected.active
        ws['B2'] = 'Mode of Payment'
        self.assertTrue(_write_payment_mode(ws, {}, 'LOAN-JAWABU'))
        self.assertEqual(ws['C2'].value, 'LOAN-JAWABU')

    def test_payment_models_and_fields_are_documented(self):
        for model in apps.get_app_config('payments').get_models():
            self.assertTrue(model._meta.db_table_comment, model._meta.label)
            for field in model._meta.concrete_fields:
                self.assertTrue(field.db_comment, f'{model._meta.label}.{field.name}')

    def test_governed_payment_routes_are_named(self):
        batch_id = '00000000-0000-0000-0000-000000000001'
        farmer_id = '00000000-0000-0000-0000-000000000002'
        self.assertEqual(reverse('portal_payment_batches'), '/api/portal/payments/batches/')
        self.assertEqual(reverse('portal_payment_sequence'), '/api/portal/payments/sequence/')
        self.assertIn(batch_id, reverse('portal_payment_batch_detail', kwargs={'batch_id': batch_id}))
        self.assertIn(farmer_id, reverse(
            'portal_payment_batch_case_review', kwargs={'batch_id': batch_id, 'farmer_id': farmer_id},
        ))
