from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from core.models import (
    LoanOriginationApplication,
    OriginationApplicationEvent,
    OriginationProductDefinition,
)
from core.services.loan_origination import (
    OriginationConflict,
    OriginationError,
    create_application,
    prepare_signing_package,
    review_application,
    render_application_preview,
    save_application_fields,
    submit_for_review,
)


class LoanOriginationServiceTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.officer = user_model.objects.create_user(username='origination-officer')
        self.reviewer = user_model.objects.create_user(username='origination-reviewer')
        self.product = OriginationProductDefinition.objects.create(
            product_key='pilot-product',
            name='Synthetic pilot product',
            version=1,
            form_schema={'fields': [
                {'key': 'customer_name', 'type': 'text', 'required': True},
                {'key': 'consent', 'type': 'boolean', 'required': True},
            ]},
            signer_rules=[{'role': 'customer'}, {'role': 'officer'}],
            document_type='synthetic_loan_agreement',
            document_template_name='Synthetic Agreement.pdf',
            document_template_version=1,
            document_template_sha256='a' * 64,
            is_active=True,
        )
        self.audit_patch = patch('core.services.compliance_audit.record_event')
        self.audit_patch.start()
        self.addCleanup(self.audit_patch.stop)

    def test_active_product_requires_complete_contract(self):
        definition = OriginationProductDefinition(
            product_key='invalid', name='Invalid', version=1, is_active=True,
            form_schema={}, signer_rules=[], document_type='',
            document_template_name='', document_template_sha256='',
            document_template_version=1,
        )
        with self.assertRaises(ValidationError):
            definition.full_clean()

    def test_create_and_write_requests_are_idempotent_and_revision_checked(self):
        application, replayed = create_application(
            product_key=self.product.product_key,
            officer=self.officer,
            branch='Synthetic Branch',
            client_request_id='create-1',
        )
        repeated, replayed_again = create_application(
            product_key=self.product.product_key,
            officer=self.officer,
            branch='Another Branch',
            client_request_id='create-1',
        )
        self.assertFalse(replayed)
        self.assertTrue(replayed_again)
        self.assertEqual(repeated.pk, application.pk)

        saved = save_application_fields(
            application_id=application.pk,
            actor=self.officer,
            payload={'customer_name': 'Synthetic Customer', 'consent': True},
            expected_revision=1,
            request_id='save-1',
        )
        replayed_save = save_application_fields(
            application_id=application.pk,
            actor=self.officer,
            payload={'customer_name': 'Changed', 'consent': False},
            expected_revision=1,
            request_id='save-1',
        )
        self.assertEqual(replayed_save.revision, saved.revision)
        self.assertEqual(replayed_save.form_payload, saved.form_payload)
        with self.assertRaises(OriginationConflict):
            save_application_fields(
                application_id=application.pk,
                actor=self.officer,
                payload=saved.form_payload,
                expected_revision=1,
                request_id='save-stale',
            )

    def test_review_is_maker_checker_and_signing_preparation_has_no_dispatch(self):
        application, _ = create_application(
            product_key=self.product.product_key,
            officer=self.officer,
            branch='Synthetic Branch',
            client_request_id='create-flow',
        )
        application = save_application_fields(
            application_id=application.pk,
            actor=self.officer,
            payload={'customer_name': 'Synthetic Customer', 'consent': True},
            expected_revision=1,
            request_id='save-flow',
        )
        OriginationApplicationEvent.objects.create(
            application=application, action='document_previewed', revision=application.revision,
            actor=self.officer, request_id='preview-flow',
        )
        application = submit_for_review(
            application_id=application.pk,
            actor=self.officer,
            expected_revision=application.revision,
            request_id='submit-flow',
        )
        with self.assertRaises(OriginationError):
            review_application(
                application_id=application.pk,
                actor=self.officer,
                expected_revision=application.revision,
                request_id='self-review',
                decision='approve',
            )
        application = review_application(
            application_id=application.pk,
            actor=self.reviewer,
            expected_revision=application.revision,
            request_id='review-flow',
            decision='approve',
        )
        package, replayed = prepare_signing_package(
            application_id=application.pk,
            actor=self.reviewer,
            expected_revision=application.revision,
            request_id='signing-flow',
        )
        repeated, replayed_again = prepare_signing_package(
            application_id=application.pk,
            actor=self.reviewer,
            expected_revision=application.revision + 1,
            request_id='signing-flow',
        )
        application.refresh_from_db()
        self.assertFalse(replayed)
        self.assertTrue(replayed_again)
        self.assertEqual(repeated.pk, package.pk)
        self.assertEqual(application.status, LoanOriginationApplication.STATUS_SIGNING_PENDING)
        self.assertEqual(OriginationApplicationEvent.objects.filter(application=application).count(), 6)

    def test_non_approval_review_requires_reason(self):
        application, _ = create_application(
            product_key=self.product.product_key,
            officer=self.officer,
            branch='Synthetic Branch',
            client_request_id='create-correction',
        )
        application.form_payload = {'customer_name': 'Synthetic Customer', 'consent': True}
        application.status = LoanOriginationApplication.STATUS_READY_FOR_REVIEW
        application.save(update_fields=['form_payload', 'status'])
        with self.assertRaises(OriginationError):
            review_application(
                application_id=application.pk,
                actor=self.reviewer,
                expected_revision=application.revision,
                request_id='correction-review',
                decision='request_correction',
            )

    def test_superuser_may_review_own_submission_as_break_glass_override(self):
        self.officer.is_superuser = True
        self.officer.is_staff = True
        self.officer.save(update_fields=['is_superuser', 'is_staff'])
        application, _ = create_application(
            product_key=self.product.product_key, officer=self.officer,
            branch='Synthetic Branch', client_request_id='superuser-correction',
        )
        application.status = LoanOriginationApplication.STATUS_READY_FOR_REVIEW
        application.save(update_fields=['status'])
        corrected = review_application(
            application_id=application.pk, actor=self.officer,
            expected_revision=application.revision, request_id='superuser-correction-review',
            decision='request_correction', reason='Correct the preview alignment.',
        )
        self.assertEqual(corrected.status, LoanOriginationApplication.STATUS_CORRECTION_REQUIRED)

        corrected.status = LoanOriginationApplication.STATUS_READY_FOR_REVIEW
        corrected.save(update_fields=['status'])
        approved = review_application(
            application_id=corrected.pk, actor=self.officer,
            expected_revision=corrected.revision, request_id='superuser-approve-review',
            decision='approve',
        )
        self.assertEqual(approved.status, LoanOriginationApplication.STATUS_REVIEWED)

    @patch('core.services.partnership_laf_preview.render_partnership_laf')
    def test_preview_uses_approved_local_template_contract(self, renderer):
        self.product.document_type = 'partnership_loan_application'
        self.product.document_template_name = 'Jawabu Partnership LAF.pdf'
        self.product.document_template_sha256 = '5e7d264c0cf3e4264e9ab768fd89a4fd1dab131eedd733cce439ce11c6e345f1'
        self.product.save(update_fields=['document_type', 'document_template_name', 'document_template_sha256'])
        application, _ = create_application(
            product_key=self.product.product_key, officer=self.officer,
            branch='Synthetic Branch', client_request_id='create-preview',
        )
        application.form_payload = {'customer_name': 'Synthetic Customer', 'consent': True}
        application.save(update_fields=['form_payload'])
        renderer.return_value = b'%PDF-synthetic'

        content = render_application_preview(application)

        self.assertEqual(content, b'%PDF-synthetic')
        context = renderer.call_args.args[0]
        self.assertEqual(context['branch_code'], 'Synthetic Branch')
        self.assertEqual(context['customer_name'], 'Synthetic Customer')
        self.assertEqual(renderer.call_args.kwargs['version'], self.product.document_template_version)
        self.assertEqual(
            renderer.call_args.kwargs['expected_sha256'],
            self.product.document_template_sha256,
        )
