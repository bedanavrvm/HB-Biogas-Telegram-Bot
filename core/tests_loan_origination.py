from io import BytesIO
from unittest.mock import patch

from pypdf import PdfReader, PdfWriter

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from core.models import (
    LoanOriginationApplication,
    OriginationApplicationEvent,
    OriginationDocumentTemplate,
    OriginationProductDocumentAssignment,
    OriginationProductDefinition,
    OriginationTemplateConfigurationRevision,
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
    normalize_form_payload,
    validate_form_payload,
)
from core.services.origination_documents import (
    mark_document_previewed,
    save_document_fields,
    select_documents,
    serialize_packet,
    render_packet,
    validate_applicability_rule,
)
from core.services.origination_templates import attach_shared_supporting_template


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

    def test_required_supporting_document_key_is_ignored_by_selection_endpoint(self):
        """Cached clients may include a disabled, required checkbox in their payload."""
        OriginationDocumentTemplate.objects.create(
            product_definition=self.product,
            document_key='primary', document_role='primary', inclusion_mode='required',
            document_type=self.product.document_type, name='Primary LAF', version=1,
            status='active', source_filename='primary.pdf', source_sha256='4' * 64,
            source_byte_size=100, page_count=1, placement_config={}, created_by=self.officer,
        )
        support = OriginationDocumentTemplate.objects.create(
            product_definition=self.product,
            document_key='required_guarantor', document_role='supporting',
            inclusion_mode='required', form_schema={'fields': []},
            document_type='pilot-product-required-guarantor', name='Required guarantor form', version=1,
            status='active', source_filename='guarantor.pdf', source_sha256='5' * 64,
            source_byte_size=100, page_count=1, placement_config={}, created_by=self.officer,
        )
        application, _ = create_application(
            product_key=self.product.product_key, officer=self.officer,
            branch='Synthetic Branch', client_request_id='required-selection-create',
        )
        OriginationApplicationEvent.objects.create(
            application=application, action='document_previewed',
            revision=application.revision, actor=self.officer,
            request_id='required-selection-preview',
        )

        saved = select_documents(
            application_id=application.pk, actor=self.officer,
            selected_keys=[support.document_key], expected_revision=application.revision,
            request_id='required-selection-request',
        )

        selected = saved.packet_documents.get(document_key=support.document_key)
        self.assertTrue(selected.selected)
        self.assertEqual(selected.selection_source, selected.SOURCE_REQUIRED)

    def test_repeatable_secured_assets_are_typed_capped_and_decimal_normalized(self):
        schema = {'fields': [{
            'key': 'secured_assets', 'type': 'repeating_group', 'required': True,
            'structure': {
                'min_items': 1, 'max_items': 11,
                'columns': [
                    {'key': 'description', 'type': 'text', 'required': True},
                    {'key': 'estimated_value', 'type': 'money', 'required': True, 'validation': {'min': '0'}},
                ],
            },
        }]}
        normalized = normalize_form_payload(schema, {'secured_assets': [
            {'description': 'Synthetic asset', 'estimated_value': '12500.50'},
        ]})
        self.assertEqual(normalized['secured_assets'][0]['estimated_value'], '12500.50')
        self.assertEqual(len(normalized['secured_assets'][0]['row_id']), 36)
        self.assertTrue(validate_form_payload(schema, normalized, require_complete=True).valid)
        too_many = {'secured_assets': normalized['secured_assets'] * 12}
        result = validate_form_payload(schema, too_many, require_complete=True)
        self.assertFalse(result.valid)
        self.assertIn('11', result.errors['secured_assets'])
        duplicate = {'secured_assets': [normalized['secured_assets'][0], normalized['secured_assets'][0]]}
        result = validate_form_payload(schema, duplicate, require_complete=True)
        self.assertFalse(result.valid)
        self.assertIn('duplicate identity', result.errors['secured_assets'])

    def test_shared_supporting_assignment_is_snapshotted_and_pinned(self):
        template = OriginationDocumentTemplate.objects.create(
            product_definition=None, document_key='shared_guarantee', document_role='supporting',
            inclusion_mode='required', document_type='shared_guarantee', name='Shared guarantee',
            version=3, status='active', source_filename='shared.pdf', source_sha256='9' * 64,
            source_byte_size=100, page_count=1, placement_config={}, created_by=self.officer,
            form_schema={'fields': [{'key': 'guarantor_1_name', 'type': 'text', 'required': True}]},
        )
        revision = OriginationTemplateConfigurationRevision.objects.create(
            template=template, revision=1, configuration={}, is_published=True,
            created_by=self.officer,
        )
        template.published_configuration_revision = revision
        template.save(update_fields=['published_configuration_revision'])
        assignment = OriginationProductDocumentAssignment.objects.create(
            product_definition=self.product, template=template,
            document_key='guarantee', name='Guarantee and undertaking',
            inclusion_mode='required', display_order=20, created_by=self.officer,
        )
        application, _ = create_application(
            product_key=self.product.product_key, officer=self.officer,
            branch='Synthetic Branch', client_request_id='shared-assignment-create',
        )
        document = application.packet_documents.get(document_key='guarantee')
        self.assertEqual(document.assignment, assignment)
        self.assertEqual(document.template_snapshot['version'], 3)
        self.assertEqual(document.template_snapshot['assignment_id'], str(assignment.pk))
        self.assertEqual(document.template_snapshot['assignment_version_policy'], 'latest_compatible')

        template.status = template.STATUS_RETIRED
        template.save(update_fields=['status'])
        successor = OriginationDocumentTemplate.objects.create(
            product_definition=None, document_key='shared_guarantee', document_role='supporting',
            inclusion_mode='required', document_type='shared_guarantee', name='Shared guarantee',
            version=4, status='active', source_filename='shared-v4.pdf', source_sha256='8' * 64,
            source_byte_size=100, page_count=1, placement_config={}, created_by=self.officer,
            form_schema={'fields': [{'key': 'guarantor_1_name', 'type': 'text', 'required': True}]},
        )
        successor_revision = OriginationTemplateConfigurationRevision.objects.create(
            template=successor, revision=1, configuration={}, is_published=True,
            created_by=self.officer,
        )
        successor.published_configuration_revision = successor_revision
        successor.save(update_fields=['published_configuration_revision'])
        newer_application, _ = create_application(
            product_key=self.product.product_key, officer=self.officer,
            branch='Synthetic Branch', client_request_id='shared-assignment-newer',
        )
        self.assertEqual(
            newer_application.packet_documents.get(document_key='guarantee').template_id,
            successor.pk,
        )
        document.refresh_from_db()
        self.assertEqual(document.template_id, template.pk)

        assignment.version_policy = assignment.VERSION_PINNED
        assignment.save(update_fields=['version_policy'])
        pinned_application, _ = create_application(
            product_key=self.product.product_key, officer=self.officer,
            branch='Synthetic Branch', client_request_id='shared-assignment-pinned',
        )
        self.assertEqual(
            pinned_application.packet_documents.get(document_key='guarantee').template_id,
            template.pk,
        )

        assignment.version_policy = assignment.VERSION_LATEST_COMPATIBLE
        assignment.save(update_fields=['version_policy'])
        successor.status = successor.STATUS_RETIRED
        successor.save(update_fields=['status'])
        incompatible = OriginationDocumentTemplate.objects.create(
            product_definition=None, document_key='shared_guarantee', document_role='supporting',
            inclusion_mode='required', document_type='shared_guarantee', name='Shared guarantee',
            version=5, status='active', source_filename='shared-v5.pdf', source_sha256='7' * 64,
            source_byte_size=100, page_count=1, placement_config={}, created_by=self.officer,
            form_schema={'fields': [{'key': 'guarantor_1_name', 'type': 'money', 'required': True}]},
        )
        incompatible_revision = OriginationTemplateConfigurationRevision.objects.create(
            template=incompatible, revision=1, configuration={}, is_published=True,
            created_by=self.officer,
        )
        incompatible.published_configuration_revision = incompatible_revision
        incompatible.save(update_fields=['published_configuration_revision'])
        fallback_application, _ = create_application(
            product_key=self.product.product_key, officer=self.officer,
            branch='Synthetic Branch', client_request_id='shared-assignment-fallback',
        )
        self.assertEqual(
            fallback_application.packet_documents.get(document_key='guarantee').template_id,
            successor.pk,
        )

        self.product.lifecycle_status = self.product.STATUS_PUBLISHED
        self.product.save(update_fields=['lifecycle_status'])
        with self.assertRaisesRegex(ValidationError, 'immutable'):
            OriginationProductDocumentAssignment.objects.create(
                product_definition=self.product, template=template,
                document_key='late-guarantee', name='Late guarantee',
                inclusion_mode='required', display_order=30, created_by=self.officer,
            )

    def test_packet_wizard_attach_uses_latest_compatible_global_template(self):
        draft = OriginationProductDefinition.objects.create(
            product_key='packet-wizard', name='Packet wizard product', version=1,
            form_schema={'fields': [{'key': 'consent', 'type': 'boolean', 'required': True}]},
            signer_rules=[], document_type='packet_wizard',
            document_template_name='', document_template_version=1,
            document_template_sha256='', is_active=False,
        )
        template = OriginationDocumentTemplate.objects.create(
            product_definition=None, document_key='guarantor_form', document_role='supporting',
            inclusion_mode='required', document_type='guarantor_form', name='Guarantor form',
            version=1, status='active', source_filename='guarantor.pdf', source_sha256='6' * 64,
            source_byte_size=100, page_count=1, placement_config={}, created_by=self.officer,
            form_schema={'fields': [{'key': 'customer_name', 'type': 'text', 'required': True}]},
        )
        revision = OriginationTemplateConfigurationRevision.objects.create(
            template=template, revision=1, configuration={}, is_published=True, created_by=self.officer,
        )
        template.published_configuration_revision = revision
        template.save(update_fields=['published_configuration_revision'])

        assignment = attach_shared_supporting_template(
            product_definition=draft, template=template,
            inclusion_mode='conditional_required', display_order=15,
            officer_selectable=False, default_selected=False,
            applicability_rule={'field': 'consent', 'operator': 'truthy'}, actor=self.officer,
        )

        self.assertEqual(assignment.product_definition, draft)
        self.assertEqual(assignment.template, template)
        self.assertEqual(assignment.version_policy, assignment.VERSION_LATEST_COMPATIBLE)
        self.assertEqual(assignment.applicability_rule['field'], 'consent')
        repeated = attach_shared_supporting_template(
            product_definition=draft, template=template,
            inclusion_mode='conditional_required', display_order=15,
            officer_selectable=False, default_selected=False,
            applicability_rule={'field': 'consent', 'operator': 'truthy'}, actor=self.officer,
        )
        self.assertEqual(repeated.pk, assignment.pk)
        self.assertEqual(draft.document_assignments.count(), 1)


class OriginationSupportingDocumentSetupAdminTests(TestCase):
    def test_draft_product_has_a_single_guided_supporting_document_entrypoint(self):
        actor = get_user_model().objects.create_superuser(
            username='packet-wizard-admin', email='packet-wizard@example.test', password='password',
        )
        product = OriginationProductDefinition.objects.create(
            product_key='packet-admin', name='Packet admin product', version=1,
            form_schema={'fields': [{'key': 'consent', 'type': 'boolean', 'required': True}]},
            signer_rules=[], document_type='packet_admin', document_template_name='',
            document_template_version=1, document_template_sha256='', is_active=False,
        )
        self.client.force_login(actor)

        response = self.client.get(reverse(
            'admin:core_originationproductdefinition_supporting_document_setup', args=[product.pk],
        ))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Add a supporting document')
        self.assertContains(response, 'Use a published reusable document')
        self.assertContains(response, 'Create a reusable document')
        self.assertContains(response, 'origination-product-builder')
