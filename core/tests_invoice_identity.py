from datetime import date
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.utils import timezone
from django.test.utils import CaptureQueriesContext

from core.models import (
    InvoiceIdentityReview, InvoiceUploadBatch, JawabuDataQualityIssue,
    JawabuFarmerMaster, JawabuRelatedPerson, ParsedInvoice, RequisitionBatch,
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
from core.services.invoice_parser import (
    InvoiceMatchEligibilityError,
    manually_match_invoice,
    official_requisition_eligibility,
)
from core.services.payment_documents import payment_readiness


class InvoiceIdentityWorkflowTests(TestCase):
    def setUp(self):
        from core.models import ComplianceAuditChainState
        ComplianceAuditChainState.objects.get_or_create(singleton=1)
        self.farmer = JawabuFarmerMaster.objects.create(
            customer_name='Mary Wanjiku',
            imab_customer_name='MARY WANJIKU',
            national_id='12345678',
            primary_phone='0712345678',
            customer_no='C-1',
            order_number='ORDER-1',
            requisition_date=date(2026, 9, 1),
            status='active',
        )
        order = RequisitionBatch.objects.create(
            order_number='ORDER-1', version=1,
            requisition_date=self.farmer.requisition_date,
            finalized_at=timezone.now(), farmer_ids=[str(self.farmer.id)],
            farmer_count=1, file_content=b'official-workbook',
            content_checksum='official-checksum', status='generated',
        )
        from core.models import DocumentPhysicalSignoff
        from django.contrib.auth import get_user_model
        signer = get_user_model().objects.create_user(username='synthetic-order-signer')
        DocumentPhysicalSignoff.objects.create(document_type='requisition', requisition_batch=order,
            source_version=order.version, source_checksum=order.content_checksum, status='signed_approved',
            uploaded_by=signer, approved_by=signer, approved_at=timezone.now(),
            scan_checksum='a' * 64, scan_filename='synthetic-order-scan.pdf', scan_content_type='application/pdf')
        self.farmer.requisition_batch = order
        self.farmer.save(update_fields=['requisition_batch'])
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

    def test_unmatching_invoice_dates_a_restored_legacy_deposit_and_retains_prior_date(self):
        from unittest.mock import patch
        from datetime import datetime, timezone as utc_timezone
        from core.services.invoice_parser import unmatch_invoice
        self.farmer.invoice_number = 'INV-1'
        self.farmer.deposit_paid_hbg = Decimal('7000')
        self.farmer.actual_receipts = '5000'
        self.farmer.hb_deposit_date = date(2024,2,29)
        self.farmer.save()
        invoice = self.invoice(payment=Decimal('7000'))
        with patch('django.utils.timezone.now', return_value=datetime(2026,10,25,22,30,tzinfo=utc_timezone.utc)):
            unmatch_invoice(invoice, actor='Synthetic Operations')
        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.hb_deposit_date, date(2026,10,26))
        event = self.farmer.pipeline_events.get(action='hb_deposit_invoice_updated')
        self.assertEqual(event.old_values['hb_deposit_date'], '2024-02-29')
        self.assertEqual(event.new_values['deposit_paid_hbg'], '5000.00')

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

    def test_replacement_confirmation_does_not_outer_join_nullable_locked_relations(self):
        original = self.invoice(customer_id='87654321', customer_name='Jane Wanjiku', customer_phone='0700000000')
        review = ensure_identity_review(original, self.farmer)
        decide_identity_review(review, outcome='different_person_confirmed', actor='Operations', note='Confirmed spouse invoice.')
        item = create_name_change(
            review, actor='Operations', relationship_type='spouse',
            related_name='Jane Wanjiku', related_national_id='87654321',
            related_phone='0700000000', attestation_note='Confirmed relationship.',
            evidence_reference='evidence-2', client_request_id='lock-safe-change',
        )
        item.batch.legacy_manual_letter_allowed = True
        item.batch.save(update_fields=['legacy_manual_letter_allowed', 'updated_at'])
        mark_name_change_sent(
            item.batch, actor='Operations', letter_reference='letter-2', sent_reference='HB-email-2',
        )
        replacement = self.invoice(
            invoice_no='INV-LOCK-SAFE', customer_name='Mary Wanjiku', customer_id='12345678',
            status='unmatched', matched_farmer=None, matched_order_number='', invoice_date=date(2026, 9, 15),
        )

        with CaptureQueriesContext(connection) as captured:
            confirm_replacement(item, replacement, actor='Operations')

        locked_entity_reads = [
            query['sql'].upper() for query in captured.captured_queries
            if query['sql'].lstrip().upper().startswith('SELECT') and any(
                table in query['sql'].upper() for table in (
                    'CORE_INVOICENAMECHANGEITEM', 'CORE_INVOICENAMECHANGEBATCH',
                    'CORE_PARSEDINVOICE', 'CORE_JAWABUFARMERMASTER',
                )
            )
        ]
        self.assertTrue(locked_entity_reads)
        self.assertFalse(any('LEFT OUTER JOIN' in query for query in locked_entity_reads))

    def test_invoice_match_requires_membership_in_a_finalized_requisition(self):
        eligible = official_requisition_eligibility(self.farmer)
        self.assertTrue(eligible['eligible'])

        RequisitionBatch.objects.filter(order_number=self.farmer.order_number).update(farmer_ids=[])
        mismatch = official_requisition_eligibility(self.farmer)
        self.assertFalse(mismatch['eligible'])
        self.assertEqual(mismatch['code'], 'invoice_requisition_mismatch')

        invoice = self.invoice(status='unmatched', matched_farmer=None, matched_order_number='')
        with self.assertRaisesMessage(InvoiceMatchEligibilityError, 'finalized requisition membership'):
            manually_match_invoice(invoice, self.farmer, actor='Operations')
        invoice.refresh_from_db()
        self.farmer.refresh_from_db()
        self.assertEqual(invoice.status, 'unmatched')
        self.assertIsNone(invoice.matched_farmer_id)
        self.assertEqual(self.farmer.invoice_number, '')

    def test_replacement_allows_name_variance_and_requires_phone_difference_note(self):
        original = self.invoice(customer_id='87654321', customer_name='Jane Wanjiku', customer_phone='0700000000')
        item = start_invoice_correction(
            original, actor='Operations', relationship_type='spouse', explanation='', confirmed=True,
            expected_invoice_revision=original.revision,
            expected_application_revision=self.farmer.workflow_revision,
            client_request_id='replacement-identity-rules',
        )
        item.batch.legacy_manual_letter_allowed = True
        item.batch.save(update_fields=['legacy_manual_letter_allowed', 'updated_at'])
        mark_name_change_sent(
            item.batch, actor='Operations', letter_reference='letter-rules', sent_reference='HB-email-rules',
        )
        phone_difference = self.invoice(
            invoice_no='INV-PHONE', customer_name='Mary Wanjiku', customer_id='12345678',
            customer_phone='0700111222', status='unmatched', matched_farmer=None, matched_order_number='',
        )
        with self.assertRaisesMessage(ValueError, 'phone-number difference'):
            confirm_replacement(item, phone_difference, actor='Operations')

        confirmed = confirm_replacement(
            item, phone_difference, actor='Operations',
            verification_note='Confirmed the alternate number with the applicant.',
        )
        self.assertEqual(confirmed.status, 'completed')

    def correction(self, *, sent=True):
        original = self.invoice(customer_id='87654321', customer_name='Synthetic household person')
        item = start_invoice_correction(
            original, actor='Operations', relationship_type='spouse', explanation='', confirmed=True,
            expected_invoice_revision=original.revision,
            expected_application_revision=self.farmer.workflow_revision,
            client_request_id='synthetic-correction-' + str(original.pk),
        )
        if sent:
            item.batch.legacy_manual_letter_allowed = True
            item.batch.save(update_fields=['legacy_manual_letter_allowed', 'updated_at'])
            mark_name_change_sent(item.batch, actor='Operations', letter_reference='synthetic-letter', sent_reference='sent')
        return original, item

    def test_corrected_invoice_accepts_matching_id_with_name_warning(self):
        original, item = self.correction()
        replacement = self.invoice(customer_id='12345678', customer_name='M. Wanjiku',
            invoice_no='CORRECTED', matched_farmer=None, status='unmatched')
        confirmed = confirm_replacement(item, replacement, actor='Operations')
        self.assertEqual(confirmed.status, 'completed')
        self.assertEqual(identity_gate(replacement, self.farmer)['blocker'], '')

    def test_unmatch_closes_only_its_own_pending_correction(self):
        from core.services.invoice_parser import unmatch_invoice
        for sent, expected in [(False, 'cancelled'), (True, 'withdrawn')]:
            original, item = self.correction(sent=sent)
            unmatch_invoice(original, actor='Operations')
            item.refresh_from_db()
            self.assertEqual(item.status, expected)
            self.assertTrue(item.closed_at)
            self.assertEqual(item.closed_by, 'Operations')
            self.assertFalse(original.identity_reviews.filter(status='pending').exists())
            unmatch_invoice(original, actor='Operations')
            item.refresh_from_db()
            self.assertEqual(item.status, expected)

    def test_duplicate_requires_all_business_fields(self):
        from core.api.portal_views import _invoice_duplicate_count, _invoice_duplicate_ids
        one = self.invoice(invoice_amount=Decimal('1000'))
        two = self.invoice(invoice_no='DIFFERENT', invoice_amount=Decimal('2000'))
        self.assertEqual(_invoice_duplicate_count(one), 0)
        copy = self.invoice(invoice_amount=Decimal('1000'))
        self.assertEqual(_invoice_duplicate_count(one), 1)
        self.assertEqual(_invoice_duplicate_ids(ParsedInvoice.objects.all()), {one.pk, copy.pk})

    def test_duplicate_fingerprint_distinguishes_every_business_value(self):
        from core.services.invoice_duplicates import fingerprint
        base = self.invoice(invoice_date=date(2026, 9, 1), invoice_amount=Decimal('1000'),
            total_after_discount=Decimal('900'), discount=Decimal('100'), payment=Decimal('300'),
            balance_due=Decimal('600'), raw_payload={'order_reference':'ORDER-1'})
        for field, value in {'customer_id':'87654321', 'invoice_no':'OTHER',
                'invoice_date':date(2026, 9, 2), 'customer_name':'Different Person',
                'customer_phone':'0799999999', 'invoice_amount':Decimal('1001'),
                'total_after_discount':Decimal('901'), 'discount':None, 'payment':Decimal('0'),
                'balance_due':Decimal('601'), 'raw_payload':{'order_reference':'ORDER-2'}}.items():
            other = self.invoice(**{key:getattr(base, key) for key in (
                'customer_id','invoice_no','invoice_date','customer_name','customer_phone',
                'invoice_amount','total_after_discount','discount','payment','balance_due','raw_payload')},
            )
            setattr(other, field, value)
            self.assertNotEqual(fingerprint(base), fingerprint(other), field)
        base.customer_id = '12 345 678'
        equivalent = self.invoice(customer_id='12345678')
        self.assertEqual(fingerprint(base)[0], fingerprint(equivalent)[0])

    def test_replacement_candidates_hide_deleted_and_warn_on_name_difference(self):
        import json
        from django.contrib.auth import get_user_model
        from django.test import RequestFactory
        from core.api.portal_views import portal_invoice_name_change_replacement_candidates
        original, item = self.correction()
        deleted = self.invoice(status='deleted', matched_farmer=None)
        replacement = self.invoice(customer_id='12345678', customer_name='M. Wanjiku',
            invoice_no='CORRECTED', matched_farmer=None, status='unmatched')
        request = RequestFactory().get('/synthetic')
        request.portal_user = get_user_model().objects.create_superuser('synthetic-operations-admin', password=None)
        response = portal_invoice_name_change_replacement_candidates(request, str(item.pk))
        self.assertEqual(response.status_code, 200)
        rows = json.loads(response.content)['candidates']
        self.assertNotIn(str(deleted.pk), [row['invoice']['id'] for row in rows])
        candidate = next(row for row in rows if row['invoice']['id'] == str(replacement.pk))
        self.assertTrue(candidate['selectable'])
        self.assertTrue(candidate['warnings'])

    def test_replacement_rechecks_deleted_id_and_revision(self):
        original, item = self.correction()
        replacement = self.invoice(invoice_no='CORRECTED', customer_id='12345678',
            matched_farmer=None, status='deleted')
        with self.assertRaises(ValueError):
            confirm_replacement(item, replacement, actor='Operations')
        replacement.status = 'unmatched'
        replacement.customer_id = '11111111'
        replacement.save()
        with self.assertRaisesMessage(ValueError, 'national ID does not match'):
            confirm_replacement(item, replacement, actor='Operations')
        replacement.customer_id = '12345678'
        replacement.save()
        with self.assertRaisesMessage(ValueError, 'changed'):
            confirm_replacement(item, replacement, actor='Operations', expected_revision=item.revision + 1)
        item.refresh_from_db()
        self.assertEqual(item.status, 'awaiting_replacement')

    def test_replacement_rejects_an_invoice_from_another_group(self):
        from core.models import GroupSheetConfiguration
        original, item = self.correction()
        other_group = GroupSheetConfiguration.objects.create(group_id='synthetic-other-group', workflow='jawabu_portal')
        upload = InvoiceUploadBatch.objects.create(group_configuration=other_group, original_filename='other.pdf')
        replacement = self.invoice(batch=upload, invoice_no='OTHER', customer_id='12345678', status='unmatched', matched_farmer=None)
        with self.assertRaisesMessage(ValueError, 'different group'):
            confirm_replacement(item, replacement, actor='Operations')

    def test_new_upload_suggests_correction_instead_of_auto_matching(self):
        from core.services.invoice_parser import auto_match_invoice_batch
        from core.services.invoice_identity import pending_corrections_for_invoice
        original, item = self.correction()
        self.farmer.invoice_number = original.invoice_no
        self.farmer.save(update_fields=['invoice_number'])
        upload = InvoiceUploadBatch.objects.create(original_filename='corrected.pdf', status='parsed')
        replacement = self.invoice(batch=upload, invoice_no='CORRECTED', customer_id='12345678',
            invoice_date=date(2026, 9, 1), customer_name='M. Wanjiku', matched_farmer=None, status='unmatched')
        result = auto_match_invoice_batch(upload, farmers=[self.farmer], actor='Operations')
        self.assertEqual(result['matched'], [])
        self.assertIn('corrected invoice is ready', result['manual_review'][0]['reason'])
        self.assertEqual([row.pk for row in pending_corrections_for_invoice(replacement)], [item.pk])
        self.farmer.refresh_from_db()
        self.assertEqual(self.farmer.invoice_number, original.invoice_no)

    def test_signed_payment_blocks_unmatch_without_cancelling_correction(self):
        from core.services.invoice_parser import unmatch_invoice
        from core.models import GroupSheetConfiguration
        from payments.models import PaymentBatch, PaymentBatchCase
        original, item = self.correction()
        group = GroupSheetConfiguration.objects.create(group_id='synthetic-signed-payment', workflow='jawabu_portal')
        batch = PaymentBatch.objects.create(group_configuration=group, status='completed')
        PaymentBatchCase.objects.create(batch=batch, farmer=self.farmer, payment_mode='LOAN-JAWABU')
        with self.assertRaisesMessage(ValueError, 'signed payment'):
            unmatch_invoice(original, actor='Operations')
        item.refresh_from_db()
        self.assertEqual(item.status, 'awaiting_replacement')

    def test_unmatch_invalidates_unsigned_review_and_rematch_has_no_old_correction(self):
        from core.services.invoice_parser import unmatch_invoice
        from core.models import GroupSheetConfiguration
        from payments.models import PaymentBatch, PaymentBatchCase, PaymentCaseReview
        original, item = self.correction()
        group = GroupSheetConfiguration.objects.create(group_id='synthetic-unsigned-payment', workflow='jawabu_portal')
        batch = PaymentBatch.objects.create(group_configuration=group, status='review_complete')
        member = PaymentBatchCase.objects.create(batch=batch, farmer=self.farmer, payment_mode='LOAN-JAWABU')
        review = PaymentCaseReview.objects.create(membership=member, decision='approved')
        unmatch_invoice(original, actor='Operations')
        review.refresh_from_db()
        self.assertEqual(review.decision, 'pending')
        replacement = self.invoice(invoice_no='NEW', customer_id='12345678', matched_farmer=None, status='unmatched')
        manually_match_invoice(replacement, self.farmer, actor='Operations')
        self.assertIsNone(identity_gate(replacement, self.farmer)['name_change'])
        self.assertEqual(identity_gate(replacement, self.farmer)['blocker'], '')

    def test_letter_download_link_keeps_filename_and_current_authorization(self):
        import json
        from django.contrib.auth import get_user_model
        from django.test import RequestFactory
        from core.models import InvoiceNameChangeLetterTemplate, InvoiceNameChangeLetterArtifact
        from core.api.portal_views import portal_invoice_name_change_download_link, portal_invoice_name_change_download
        from urllib.parse import unquote
        original, item = self.correction()
        template = InvoiceNameChangeLetterTemplate.objects.create(original_filename='synthetic.docx')
        artifact = InvoiceNameChangeLetterArtifact.objects.create(batch=item.batch, template=template,
            version=1, filename='Synthetic Letter v1.docx', file_content=b'synthetic-docx', checksum='a'*64)
        request = RequestFactory().get('/synthetic')
        actor = get_user_model().objects.create_superuser('synthetic-download-user', password=None)
        request.portal_user = actor
        response = portal_invoice_name_change_download_link(request, str(artifact.pk))
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data['filename'], artifact.filename)
        token = unquote(data['download_url'].split('invoice-name-change-download/')[1].rstrip('/'))
        download = portal_invoice_name_change_download(RequestFactory().get('/synthetic-download'), token)
        self.assertEqual(download.content, b'synthetic-docx')
        self.assertIn(artifact.filename, download['Content-Disposition'])
        actor.is_active = False
        actor.save(update_fields=['is_active'])
        self.assertEqual(portal_invoice_name_change_download(RequestFactory().get('/synthetic-download'), token).status_code, 403)

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

    def test_sent_request_withdrawal_requires_hb_notification_but_no_typed_reference(self):
        original = self.invoice(customer_id='87654321', customer_name='Jane Wanjiku')
        review = ensure_identity_review(original, self.farmer)
        decide_identity_review(review, outcome='different_person_confirmed', actor='Operations', note='Confirmed spouse.')
        item = create_name_change(
            review, actor='Operations', relationship_type='spouse', related_name='Jane Wanjiku',
            related_national_id='87654321', related_phone='0700000000',
            attestation_note='Relationship verified.', evidence_reference='synthetic-evidence',
            client_request_id='withdraw-confirmation-request',
        )
        batch = item.batch
        batch.legacy_manual_letter_allowed = True
        batch.save(update_fields=['legacy_manual_letter_allowed'])
        mark_name_change_sent(batch, actor='Operations', letter_reference='synthetic-letter', sent_reference='')
        item.refresh_from_db()
        with self.assertRaisesRegex(ValueError, 'HB has been notified'):
            close_name_change(item, actor='Operations', reason='', withdraw=True)
        result = close_name_change(item, actor='Operations', reason='', withdraw=True, hb_notified=True)
        self.assertEqual(result.status, 'withdrawn')
        self.assertEqual(result.hb_communication_reference, '')
        self.assertEqual(result.closed_reason, 'Sent request withdrawn by staff confirmation.')
        self.assertTrue(identity_gate(original, self.farmer)['blocker'])
        replay = close_name_change(item, actor='Operations', reason='', withdraw=True, hb_notified=True)
        self.assertEqual(replay.revision, result.revision)

    def test_flag_for_review_does_not_require_retyping_the_action_as_a_note(self):
        invoice = self.invoice(customer_id='87654321', customer_name='Synthetic invoice holder')
        review = ensure_identity_review(invoice, self.farmer)
        result = decide_identity_review(review, outcome='flagged_for_review', actor='Operations', note='')
        self.assertEqual(result.status, 'flagged_for_review')
        self.assertEqual(result.decision_note, 'Flagged for identity review by staff confirmation.')
        self.assertTrue(identity_gate(invoice, self.farmer)['blocker'])

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
        closed = close_name_change(item, actor='Operations', reason='')
        self.assertEqual(closed.closed_reason, 'Unsent request cancelled by staff confirmation.')
        replay = close_name_change(item, actor='Operations', reason='')
        self.assertEqual(closed.revision, replay.revision)

        follow_up = create_name_change_follow_up(
            item, actor='Operations', client_request_id='follow-up-request-1',
        )

        self.assertEqual(follow_up.follow_up_of_id, item.id)
        self.assertEqual(follow_up.review.status, InvoiceIdentityReview.STATUS_PENDING)
        with self.assertRaises(NameChangeBatchConflict):
            assemble_name_change_batch(
                [follow_up], actor='Operations', client_request_id='follow-up-batch-1',
            )
