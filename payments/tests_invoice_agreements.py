import io
import json
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.http import JsonResponse
from pypdf import PdfWriter

from core import tests_invoice_identity as identity_fixtures
from core.tests_invoice_name_change_letters import synthetic_letter
from core.models import InvoiceNameChangeLetterTemplate
from core.services.invoice_identity import ensure_identity_review, decide_identity_review, create_name_change, identity_gate, mark_name_change_sent
from core.services.invoice_name_change_letters import generate_letter_artifact
from payments.invoice_agreements import accept_agreement
from payments.models import InvoiceNameAgreement


def signed_pdf():
    writer = PdfWriter(); writer.add_blank_page(width=595, height=842)
    output = io.BytesIO(); writer.write(output)
    return SimpleUploadedFile('Agreed-letter.pdf', output.getvalue(), content_type='application/pdf')


class InvoiceAgreementTests(TestCase):
    setUp = identity_fixtures.InvoiceIdentityWorkflowTests.setUp
    invoice = identity_fixtures.InvoiceIdentityWorkflowTests.invoice
    def make_change(self):
        self.farmer.hb_sales_person = 'Training Sales'; self.farmer.save(update_fields=['hb_sales_person'])
        invoice = self.invoice(customer_name='Jane Wanjiku', customer_id='87654321', customer_phone='0700000000')
        review = ensure_identity_review(invoice, self.farmer)
        decide_identity_review(review, outcome='different_person_confirmed', actor='Operations', note='Confirmed spouse')
        item = create_name_change(review, actor='Operations', relationship_type='spouse', related_name=invoice.customer_name,
            related_national_id=invoice.customer_id, related_phone=invoice.customer_phone,
            attestation_note='Confirmed household', evidence_reference='synthetic', client_request_id='agreement-change')
        InvoiceNameChangeLetterTemplate.objects.create(name='Synthetic letter', file='synthetic.docx', is_active=True)
        with patch('core.services.invoice_name_change_letters._template_bytes', return_value=synthetic_letter()):
            artifact, _ = generate_letter_artifact(item.batch, actor='Operations', client_request_id='agreement-letter', publish_to_drive=False)
        return invoice, item, artifact

    def test_sent_alone_blocks_but_agreed_letter_clears_identity_and_retry_is_single(self):
        invoice, item, artifact = self.make_change()
        mark_name_change_sent(item.batch, artifact=artifact, actor='Operations')
        self.assertEqual(identity_gate(invoice, self.farmer)['blocker'], 'invoice_name_change_pending')
        agreement = accept_agreement(item.batch_id, artifact_id=artifact.pk, uploaded_file=signed_pdf(), actor='Operations', confirmed=True)
        replay = accept_agreement(item.batch_id, artifact_id=artifact.pk, uploaded_file=signed_pdf(), actor='Operations', confirmed=True)
        self.assertEqual(agreement.pk, replay.pk)
        self.assertEqual(InvoiceNameAgreement.objects.count(), 1)
        self.assertEqual(identity_gate(invoice, self.farmer)['blocker'], '')
        self.assertTrue(identity_gate(invoice, self.farmer)['agreement_accepted'])
        self.assertEqual(self.farmer.national_id, '12345678')
        self.assertEqual(invoice.customer_id, '87654321')
        self.assertIsNone(item.replacement_invoice_id)
        self.assertEqual(self.farmer.pipeline_events.filter(action='invoice_name_agreement_accepted').count(), 1)

    def test_changed_applicant_cannot_reuse_agreement(self):
        invoice, item, artifact = self.make_change()
        mark_name_change_sent(item.batch, artifact=artifact, actor='Operations')
        accept_agreement(item.batch_id, artifact_id=artifact.pk, uploaded_file=signed_pdf(), actor='Operations', confirmed=True)
        self.farmer.national_id = '99999999'; self.farmer.save(update_fields=['national_id'])
        self.assertEqual(identity_gate(invoice, self.farmer)['blocker'], 'invoice_name_change_pending')

    def test_requires_attestation_and_sent_letter_and_rejects_fake_pdf(self):
        _, item, artifact = self.make_change()
        with self.assertRaisesMessage(ValueError, 'Confirm'):
            accept_agreement(item.batch_id, artifact_id=artifact.pk, uploaded_file=signed_pdf(), actor='Operations', confirmed=False)
        with self.assertRaisesMessage(ValueError, 'Record the current letter as sent'):
            accept_agreement(item.batch_id, artifact_id=artifact.pk, uploaded_file=signed_pdf(), actor='Operations', confirmed=True)
        mark_name_change_sent(item.batch, artifact=artifact, actor='Operations')
        with self.assertRaises(ValueError):
            accept_agreement(item.batch_id, artifact_id=artifact.pk, uploaded_file=SimpleUploadedFile('fake.pdf', b'not-pdf'), actor='Operations', confirmed=True)
        self.assertEqual(InvoiceNameAgreement.objects.count(), 0)

    def test_review_flag_overrides_agreement_and_receipt_marks_cleared_identity_ready(self):
        from core.models import InvoiceIdentityReview
        from payments.receipt_batches import _item_disposition
        invoice, item, artifact = self.make_change()
        mark_name_change_sent(item.batch, artifact=artifact, actor='Operations')
        accept_agreement(item.batch_id, artifact_id=artifact.pk, uploaded_file=signed_pdf(), actor='Operations', confirmed=True)
        self.assertEqual(_item_disposition(invoice, self.farmer)[0], 'matched')
        item.review.status = InvoiceIdentityReview.STATUS_FLAGGED
        item.review.save(update_fields=['status'])
        self.assertEqual(identity_gate(invoice, self.farmer)['blocker'], 'invoice_identity_flagged')

    def test_revoked_relationship_and_superseded_request_do_not_clear_payment(self):
        from core.services.invoice_identity import correct_sent_name_change
        invoice, item, artifact = self.make_change()
        mark_name_change_sent(item.batch, artifact=artifact, actor='Operations')
        accept_agreement(item.batch_id, artifact_id=artifact.pk, uploaded_file=signed_pdf(), actor='Operations', confirmed=True)
        item.relationship.status = 'revoked'; item.relationship.save(update_fields=['status'])
        self.assertEqual(identity_gate(invoice, self.farmer)['blocker'], 'invoice_name_change_pending')
        item.relationship.status = 'confirmed'; item.relationship.save(update_fields=['status'])
        item.refresh_from_db()
        correct_sent_name_change(item, actor='Operations', reason='Correct relationship', relationship_type='household_member',
            explanation='Synthetic correction', expected_revision=item.revision, client_request_id='correct-agreed-request')
        self.assertEqual(identity_gate(invoice, self.farmer)['blocker'], 'invoice_name_change_pending')
        self.assertEqual(InvoiceNameAgreement.objects.count(), 1)

    def test_api_enforces_capability_before_upload_or_preview(self):
        from core.api.portal_views import portal_invoice_name_agreement
        _, item, artifact = self.make_change()
        for method in ['get', 'post']:
            request = getattr(RequestFactory(), method)('/synthetic-agreement/')
            with patch('core.api.portal_views._portal_capability_error', return_value=JsonResponse({'ok':False}, status=403)) as check:
                self.assertEqual(portal_invoice_name_agreement(request, str(artifact.pk)).status_code, 403)
            check.assert_called_once_with(request, 'portal.invoice_identity.manage', item.farmer)
        self.assertEqual(InvoiceNameAgreement.objects.count(), 0)

    def test_review_and_matched_workspaces_are_disjoint_and_counts_follow_clearance(self):
        from core.api.portal_views import portal_invoice_pool
        invoice, item, artifact = self.make_change()
        def workspace(name):
            request = RequestFactory().get('/synthetic-invoices/', {'workspace':name})
            request.portal_access = {}
            with patch('core.api.portal_views._portal_read_access_error', return_value=None):
                response = portal_invoice_pool(request)
            self.assertEqual(response.status_code, 200)
            return json.loads(response.content)
        review, matched = workspace('inbox'), workspace('matched')
        self.assertIn(str(invoice.pk), {row['id'] for row in review['invoices']})
        self.assertNotIn(str(invoice.pk), {row['id'] for row in matched['invoices']})
        self.assertEqual(review['summary']['needs_action_count'], 1)
        self.assertEqual(matched['summary']['matched_count'], 0)
        mark_name_change_sent(item.batch, artifact=artifact, actor='Operations')
        accept_agreement(item.batch_id, artifact_id=artifact.pk, uploaded_file=signed_pdf(), actor='Operations', confirmed=True)
        review, matched = workspace('inbox'), workspace('matched')
        self.assertNotIn(str(invoice.pk), {row['id'] for row in review['invoices']})
        self.assertIn(str(invoice.pk), {row['id'] for row in matched['invoices']})
        self.assertEqual(review['summary']['needs_action_count'], 0)
        self.assertEqual(matched['summary']['matched_count'], 1)

    def test_related_person_identity_change_invalidates_consent(self):
        invoice, item, artifact = self.make_change()
        mark_name_change_sent(item.batch, artifact=artifact, actor='Operations')
        accept_agreement(item.batch_id, artifact_id=artifact.pk, uploaded_file=signed_pdf(), actor='Operations', confirmed=True)
        person = item.relationship.related_person
        person.national_id = '99999998'; person.save(update_fields=['national_id'])
        self.assertEqual(identity_gate(invoice, self.farmer)['blocker'], 'invoice_name_change_pending')

    def test_agreement_does_not_clear_missing_financial_data(self):
        from core.services.payment_documents import payment_readiness
        invoice, item, artifact = self.make_change()
        before = payment_readiness('ORDER-1', farmer_ids=[self.farmer.pk])
        self.assertIn('Signed/agreed name-change letter', before['blocked'][0]['missing'])
        mark_name_change_sent(item.batch, artifact=artifact, actor='Operations')
        accept_agreement(item.batch_id, artifact_id=artifact.pk, uploaded_file=signed_pdf(), actor='Operations', confirmed=True)
        after = payment_readiness('ORDER-1', farmer_ids=[self.farmer.pk])
        self.assertGreater(after['blocked_count'], 0)
        self.assertNotIn('Signed/agreed name-change letter', after['blocked'][0]['missing'])

    def test_owned_reset_removes_agreements_without_protected_foreign_key_failure(self):
        from core.models import GroupSheetConfiguration, PortalMaintenanceState
        from django.contrib.auth import get_user_model
        from core.services.portal_full_reset import reset_portal_configuration, portal_reset_manifest
        _, item, artifact = self.make_change()
        group = GroupSheetConfiguration.objects.create(group_id='-100synthetic-agreement-reset', workflow={'type':'jawabu_homebiogas'})
        self.farmer.group_configuration = group; self.farmer.save(update_fields=['group_configuration'])
        PortalMaintenanceState.objects.create(singleton=1, mode='maintenance', reason='Synthetic reset')
        actor = get_user_model().objects.create_superuser(username='synthetic-agreement-reset', password='synthetic-only')
        mark_name_change_sent(item.batch, artifact=artifact, actor='Operations')
        accept_agreement(item.batch_id, artifact_id=artifact.pk, uploaded_file=signed_pdf(), actor='Operations', confirmed=True)
        self.assertEqual(portal_reset_manifest(group)['counts']['signed_name_agreements'], 1)
        with patch('core.services.portal_full_reset._delete_verified_sheet_rows', return_value=0):
            reset_portal_configuration(group, actor=actor, backup_reference='synthetic-backup')
        self.assertEqual(InvoiceNameAgreement.objects.count(), 0)


class SignedPreviewTests(SimpleTestCase):
    def test_signed_pdf_is_webview_safe_and_images_keep_their_type(self):
        from core.api.portal_views import _signed_scan_response
        with patch('core.services.secure_media_preview.pdf_preview_html', return_value=b'<figure><img src="data:image/jpeg;base64,synthetic"></figure>') as render:
            result = _signed_scan_response(b'%PDF-synthetic', 'application/pdf', 'signed.pdf')
        self.assertTrue(result['Content-Type'].startswith('text/html'))
        render.assert_called_once_with(b'%PDF-synthetic', 'signed.pdf', show_filename=False, show_single_page_caption=False)
        self.assertEqual(_signed_scan_response(b'synthetic', 'image/png', 'signed.png')['Content-Type'], 'image/png')
        self.assertEqual(_signed_scan_response(b'bad', 'text/html', 'bad.html').status_code, 400)
