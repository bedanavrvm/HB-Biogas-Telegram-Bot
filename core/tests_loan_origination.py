from io import BytesIO
from unittest.mock import patch

from pypdf import PdfReader, PdfWriter

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from core.models import (
    LoanOriginationApplication,
    OriginationApplicationEvent,
    OriginationDocumentTemplate,
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
from core.services.origination_documents import (
    mark_document_previewed,
    save_document_fields,
    select_documents,
    serialize_packet,
    render_packet,
    validate_applicability_rule,
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

    def test_supporting_document_rules_are_non_executable_and_field_scoped(self):
        validate_applicability_rule(
            {'all': [
                {'field': 'consent', 'operator': 'equals', 'value': True},
                {'field': 'customer_name', 'operator': 'not_equals', 'value': ''},
            ]},
            allowed_fields={'consent', 'customer_name'},
        )
        with self.assertRaisesRegex(ValueError, 'unknown field'):
            validate_applicability_rule(
                {'field': '__import__', 'operator': 'equals', 'value': 'unsafe'},
                allowed_fields={'consent'},
            )

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

    @patch('core.services.partnership_laf_preview.render_origination_document', return_value=b'%PDF-product-specific')
    def test_preview_renders_non_partnership_product_with_its_document_type(self, renderer):
        application, _ = create_application(
            product_key=self.product.product_key, officer=self.officer,
            branch='Synthetic Branch', client_request_id='create-generic-preview',
        )
        application.form_payload = {'customer_name': 'Synthetic Customer', 'consent': True}
        application.save(update_fields=['form_payload'])

        content = render_application_preview(application)

        self.assertEqual(content, b'%PDF-product-specific')
        self.assertEqual(renderer.call_args.kwargs['document_type'], 'synthetic_loan_agreement')
        self.assertEqual(renderer.call_args.kwargs['version'], 1)

    def test_optional_supporting_document_is_separate_prefilled_and_revision_checked(self):
        primary = OriginationDocumentTemplate.objects.create(
            product_definition=self.product,
            document_key='primary', document_role='primary', inclusion_mode='required',
            document_type=self.product.document_type, name='Primary LAF', version=1,
            status='active', source_filename='primary.pdf', source_sha256='1' * 64,
            source_byte_size=100, page_count=1, placement_config={}, created_by=self.officer,
        )
        support = OriginationDocumentTemplate.objects.create(
            product_definition=self.product,
            document_key='guarantor_consent', document_role='supporting',
            inclusion_mode='optional', officer_selectable=True,
            applicability_rule={'field': 'consent', 'operator': 'equals', 'value': True},
            form_schema={'fields': [
                {'key': 'customer_name', 'type': 'text', 'required': True},
                {'key': 'guarantor_name', 'type': 'text', 'required': True},
            ]},
            signer_rules=[{'role': 'guarantor'}], display_order=10,
            document_type='pilot-product-guarantor-consent', name='Guarantor consent', version=1,
            status='active', source_filename='guarantor.pdf', source_sha256='2' * 64,
            source_byte_size=100, page_count=1, placement_config={}, created_by=self.officer,
        )
        application, _ = create_application(
            product_key=self.product.product_key, officer=self.officer,
            branch='Synthetic Branch', client_request_id='packet-create',
        )
        self.assertEqual(application.packet_documents.count(), 2)
        support_document = application.packet_documents.get(document_key=support.document_key)
        self.assertFalse(support_document.applicable)
        application = save_application_fields(
            application_id=application.pk, actor=self.officer,
            payload={'customer_name': 'Synthetic Customer', 'consent': True},
            expected_revision=application.revision, request_id='packet-main-save',
        )
        support_document.refresh_from_db()
        self.assertTrue(support_document.applicable)
        application.primary_previewed_revision = application.revision
        application.save(update_fields=['primary_previewed_revision'])
        application = select_documents(
            application_id=application.pk, actor=self.officer,
            selected_keys=['guarantor_consent'], expected_revision=application.revision,
            request_id='packet-selection',
        )
        application = save_document_fields(
            application_id=application.pk, document_key='guarantor_consent',
            actor=self.officer, payload={
                'customer_name': 'Attempted overwrite',
                'guarantor_name': 'Synthetic Guarantor',
            }, expected_revision=application.revision, request_id='packet-support-save',
        )
        support_document.refresh_from_db()
        self.assertEqual(application.form_payload['customer_name'], 'Synthetic Customer')
        self.assertEqual(support_document.field_payload, {'guarantor_name': 'Synthetic Guarantor'})
        mark_document_previewed(application, 'guarantor_consent')
        packet = serialize_packet(application)
        self.assertTrue(packet['ready'])
        self.assertTrue(packet['primary_ready'])
        self.assertEqual(primary.document_key, 'primary')
        rendered_documents = []
        for width in (200, 300):
            writer = PdfWriter()
            writer.add_blank_page(width=width, height=400)
            output = BytesIO()
            writer.write(output)
            rendered_documents.append(output.getvalue())
        with patch(
            'core.services.origination_documents.render_document',
            side_effect=rendered_documents,
        ):
            combined, manifest = render_packet(application)
        self.assertEqual(len(PdfReader(BytesIO(combined)).pages), 2)
        self.assertEqual([item['key'] for item in manifest], ['primary', 'guarantor_consent'])
        self.assertTrue(all(len(item['rendered_sha256']) == 64 for item in manifest))

    def test_supporting_document_selection_requires_current_primary_preview(self):
        OriginationDocumentTemplate.objects.create(
            product_definition=self.product,
            document_key='optional_notice', document_role='supporting',
            inclusion_mode='optional', officer_selectable=True,
            form_schema={'fields': [{'key': 'notice_value', 'type': 'text'}]},
            document_type='pilot-product-optional-notice', name='Optional notice', version=1,
            status='active', source_filename='notice.pdf', source_sha256='3' * 64,
            source_byte_size=100, page_count=1, placement_config={}, created_by=self.officer,
        )
        application, _ = create_application(
            product_key=self.product.product_key, officer=self.officer,
            branch='Synthetic Branch', client_request_id='packet-gate-create',
        )
        with self.assertRaisesRegex(OriginationError, 'preview the primary LAF'):
            select_documents(
                application_id=application.pk, actor=self.officer,
                selected_keys=['optional_notice'], expected_revision=application.revision,
                request_id='packet-gate-select',
            )
