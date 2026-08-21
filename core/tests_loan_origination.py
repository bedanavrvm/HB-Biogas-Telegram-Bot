from base64 import b64decode
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

from pypdf import PdfReader, PdfWriter

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from core.admin import OriginationProductDefinitionForm
from core.models import (
    LoanOriginationApplication,
    OriginationApplicationEvent,
    OriginationDocumentTemplate,
    OriginationProductDocumentAssignment,
    OriginationProductDefinition,
    OriginationSigningAction,
    OriginationSigningPackage,
    OriginationTemplateConfigurationRevision,
)
from core.services.loan_origination import (
    OriginationConflict,
    OriginationError,
    applicant_identity_snapshot,
    create_application,
    prepare_signing_package,
    review_application,
    render_application_preview,
    require_applicant_identity_fields,
    save_application_fields,
    serialize_application,
    submit_for_review,
    take_over_correction_review,
    normalize_form_payload,
    validate_applicant_identity_contract,
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
from core.services.origination_signing import (
    _validated_signature_capture,
    _test_overlay,
    serialize_test_signing,
    simulate_slot,
    test_signing_enabled,
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

    def test_duplicate_product_definition_is_a_form_error_not_an_admin_500(self):
        form = OriginationProductDefinitionForm(data={
            'product_key': self.product.product_key,
            'name': self.product.name,
            'form_schema': '{"fields":[{"key":"customer_name","type":"text","required":true}]}',
            'signer_rules': '[{"role":"customer"}]',
        })

        self.assertFalse(form.is_valid())
        self.assertIn('product_version', form.errors)
        self.assertIn('Create editable next version', form.errors['product_version'][0])

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

    def test_blank_application_cannot_be_submitted(self):
        application, _ = create_application(
            product_key=self.product.product_key,
            officer=self.officer,
            branch='Synthetic Branch',
            client_request_id='create-blank',
        )

        with self.assertRaisesRegex(OriginationError, 'Applicant details'):
            submit_for_review(
                application_id=application.pk,
                actor=self.officer,
                expected_revision=application.revision,
                request_id='submit-blank',
            )

    def test_queue_identity_summary_uses_canonical_applicant_values_and_masks_identifiers(self):
        self.product.form_schema = {
            'identity_contract': 'applicant_v1',
            'fields': [
                {'key': 'applicant_full_name', 'type': 'text', 'required': True},
                {'key': 'applicant_national_id', 'type': 'text', 'required': True},
                {'key': 'applicant_phone', 'type': 'text', 'required': True},
            ],
        }
        self.product.save(update_fields=['form_schema'])
        application, _ = create_application(
            product_key=self.product.product_key,
            officer=self.officer,
            branch='Synthetic Branch',
            client_request_id='create-identity',
        )
        application = save_application_fields(
            application_id=application.pk,
            actor=self.officer,
            payload={
                'applicant_full_name': 'Synthetic Applicant',
                'applicant_national_id': '12345678',
                'applicant_phone': '0712345678',
            },
            expected_revision=application.revision,
            request_id='save-identity',
        )

        summary = serialize_application(application, include_payload=False)['applicant_summary']

        self.assertEqual(summary['name'], 'Synthetic Applicant')
        self.assertEqual(summary['national_id'], '••••5678')
        self.assertEqual(summary['phone'], '••••••5678')

    def test_applicant_identity_contract_uses_explicit_borrower_mappings(self):
        schema = {
            'identity_contract': 'applicant_v1',
            'fields': [
                {'key': 'applicant_first_name', 'label': 'Applicant First Name', 'type': 'text'},
                {'key': 'applicant_id', 'label': 'Applicant ID', 'type': 'national_id'},
                {'key': 'applicant_phone_no', 'label': 'Applicant Phone No', 'type': 'phone'},
            ],
        }
        signer_rules = [{
            'role': 'borrower', 'required': True,
            'identity_fields': {
                'name': 'applicant_first_name',
                'national_id': 'applicant_id',
                'phone': 'applicant_phone_no',
            },
            'slots': [{'key': 'signature', 'type': 'signature', 'required': True}],
        }]

        normalized = require_applicant_identity_fields(schema, signer_rules)
        validate_applicant_identity_contract(normalized, signer_rules)

        self.assertTrue(all(item['required'] for item in normalized['fields']))
        self.assertEqual(
            applicant_identity_snapshot(
                {
                    'applicant_first_name': 'Synthetic',
                    'applicant_id': '12345678',
                    'applicant_phone_no': '0712345678',
                },
                schema=normalized, signer_rules=signer_rules,
            ),
            {
                'name': 'Synthetic', 'national_id': '12345678',
                'phone': '0712345678',
            },
        )

    def test_correction_only_unlocks_selected_targets_and_returns_to_original_checker(self):
        alternate_reviewer = get_user_model().objects.create_user(username='alternate-reviewer')
        application, _ = create_application(
            product_key=self.product.product_key,
            officer=self.officer,
            branch='Synthetic Branch',
            client_request_id='create-scoped-correction',
        )
        application.form_payload = {'customer_name': 'Original Name', 'consent': True}
        application.status = LoanOriginationApplication.STATUS_READY_FOR_REVIEW
        application.save(update_fields=['form_payload', 'status'])
        application = review_application(
            application_id=application.pk,
            actor=self.reviewer,
            expected_revision=application.revision,
            request_id='request-scoped-correction',
            decision='request_correction',
            reason='Correct only the Applicant name.',
            correction_items=[{
                'target_type': 'field',
                'target_key': 'customer_name',
                'instruction': 'Use the National ID spelling.',
            }],
        )
        self.assertEqual(application.recheck_assigned_to, self.reviewer)

        with self.assertRaisesRegex(OriginationError, 'Only fields requested'):
            save_application_fields(
                application_id=application.pk,
                actor=self.officer,
                payload={'customer_name': 'Original Name', 'consent': False},
                expected_revision=application.revision,
                request_id='change-locked-correction-field',
            )

        application = save_application_fields(
            application_id=application.pk,
            actor=self.officer,
            payload={'customer_name': 'Corrected Name', 'consent': True},
            expected_revision=application.revision,
            request_id='change-requested-correction-field',
        )
        OriginationApplicationEvent.objects.create(
            application=application,
            action='document_previewed',
            revision=application.revision,
            actor=self.officer,
            request_id='preview-corrected-application',
        )
        application = submit_for_review(
            application_id=application.pk,
            actor=self.officer,
            expected_revision=application.revision,
            request_id='resubmit-corrected-application',
        )
        self.assertEqual(application.recheck_assigned_to, self.reviewer)

        with self.assertRaisesRegex(OriginationError, 'original checker'):
            review_application(
                application_id=application.pk,
                actor=alternate_reviewer,
                expected_revision=application.revision,
                request_id='unauthorized-correction-recheck',
                decision='approve',
            )

        application = take_over_correction_review(
            application_id=application.pk,
            actor=alternate_reviewer,
            expected_revision=application.revision,
            request_id='take-over-correction-recheck',
            reason='The original checker is unavailable.',
        )
        self.assertEqual(application.recheck_assigned_to, alternate_reviewer)
        self.assertTrue(application.events.filter(action='correction_review_taken_over').exists())

    @override_settings(ORIGINATION_TEST_SIGNING_ENABLED=True, SENTRY_ENVIRONMENT='production')
    def test_test_signing_is_never_enabled_in_production(self):
        self.assertFalse(test_signing_enabled())

    @override_settings(ORIGINATION_TEST_SIGNING_ENABLED=True, SENTRY_ENVIRONMENT='')
    def test_test_signing_fails_closed_without_an_explicit_environment(self):
        self.assertFalse(test_signing_enabled())

    @override_settings(ORIGINATION_TEST_SIGNING_ENABLED=True, SENTRY_ENVIRONMENT='staging')
    def test_test_signing_is_idempotent_and_does_not_mark_application_fully_signed(self):
        application, _ = create_application(
            product_key=self.product.product_key,
            officer=self.officer,
            branch='Synthetic Branch',
            client_request_id='create-test-signing',
        )
        application.status = LoanOriginationApplication.STATUS_SIGNING_PENDING
        application.save(update_fields=['status'])
        package = OriginationSigningPackage.objects.create(
            application=application,
            application_revision=application.revision,
            external_reference='ESIGN-TEST-SYNTHETIC',
            document_type='synthetic_loan_agreement',
            participants_snapshot=[{
                'role': 'applicant',
                'required': True,
                'slots': [{
                    'key': 'applicant_signature',
                    'document_key': 'primary',
                    'type': 'signature',
                    'required': True,
                }],
            }],
            test_mode=True,
        )
        capture = {'method': 'typed', 'name': 'Synthetic Test Signer'}

        with self.assertRaisesRegex(OriginationError, 'Draw or type'):
            simulate_slot(
                package_id=package.pk,
                actor=self.reviewer,
                document_key='primary',
                slot_key='applicant_signature',
                signer_role='applicant',
                expected_revision=application.revision,
                request_id='missing-test-signature-capture',
            )

        with CaptureQueriesContext(connection) as queries:
            package, replayed = simulate_slot(
                package_id=package.pk,
                actor=self.reviewer,
                document_key='primary',
                slot_key='applicant_signature',
                signer_role='applicant',
                expected_revision=application.revision,
                request_id='simulate-applicant-signature',
                signature_capture=capture,
            )
        package_queries = [
            item['sql'].lower() for item in queries.captured_queries
            if 'originationsigningpackage' in item['sql'].lower()
        ]
        self.assertTrue(package_queries)
        self.assertFalse(any('operationallocation' in sql for sql in package_queries))
        with self.assertRaisesRegex(OriginationError, 'different test signing action'):
            simulate_slot(
                package_id=package.pk,
                actor=self.reviewer,
                document_key='primary',
                slot_key='applicant_signature',
                signer_role='applicant',
                expected_revision=application.revision,
                request_id='simulate-applicant-signature',
                signature_capture={'method': 'typed', 'name': 'Different Test Signer'},
            )
        repeated, replayed_again = simulate_slot(
            package_id=package.pk,
            actor=self.reviewer,
            document_key='primary',
            slot_key='applicant_signature',
            signer_role='applicant',
            expected_revision=application.revision,
            request_id='simulate-applicant-signature',
            signature_capture=capture,
        )
        another_retry, replayed_with_new_key = simulate_slot(
            package_id=package.pk,
            actor=self.reviewer,
            document_key='primary',
            slot_key='applicant_signature',
            signer_role='applicant',
            expected_revision=application.revision,
            request_id='simulate-applicant-signature-retry',
            signature_capture=capture,
        )

        application.refresh_from_db()
        package.refresh_from_db()
        self.assertFalse(replayed)
        self.assertTrue(replayed_again)
        self.assertTrue(replayed_with_new_key)
        self.assertEqual(repeated.pk, package.pk)
        self.assertEqual(another_retry.pk, package.pk)
        self.assertIsNotNone(package.test_completed_at)
        self.assertEqual(package.status, OriginationSigningPackage.STATUS_IN_PROGRESS)
        self.assertEqual(application.status, LoanOriginationApplication.STATUS_SIGNING_PENDING)
        self.assertEqual(OriginationSigningAction.objects.filter(package=package).count(), 1)
        action = OriginationSigningAction.objects.get(package=package)
        self.assertEqual(action.metadata['signature_capture'], capture)
        self.assertEqual(len(action.metadata['capture_sha256']), 64)
        serialized = serialize_test_signing(package)
        self.assertEqual(serialized['slots'][0]['capture_method'], 'typed')
        self.assertNotIn('signature_capture', serialized['slots'][0])

    def test_drawn_test_signature_capture_is_normalized_and_bounded(self):
        normalized = _validated_signature_capture({
            'method': 'drawn',
            'strokes': [[[0, 0], [0.123456, 0.654321], [1, 1]]],
        })
        self.assertEqual(normalized, {
            'method': 'drawn',
            'strokes': [[[0.0, 0.0], [0.1235, 0.6543], [1.0, 1.0]]],
        })
        with self.assertRaisesRegex(OriginationError, 'stay inside'):
            _validated_signature_capture({
                'method': 'drawn', 'strokes': [[[0, 0], [1.01, .5]]],
            })

    def test_typed_and_drawn_test_signatures_render_inside_pdf_slots(self):
        slot = {
            'box': {'x': 20, 'y': 20, 'width': 160, 'height': 45},
            'padding': {'x': 5, 'y': 4}, 'rotation': -4,
            'align': 'right', 'vertical_align': 'top', 'ink_color': 'blue',
            'typed_font': 'Times-Italic', 'font_size': 18, 'stroke_width': 3,
        }
        typed = SimpleNamespace(
            action_type=OriginationSigningAction.TYPE_SIGNATURE,
            stamp_asset_id=None,
            metadata={'signature_capture': {'method': 'typed', 'name': 'Synthetic Test Signer'}},
        )
        typed_pdf = PdfReader(BytesIO(_test_overlay(200, 100, [(slot, typed)])))
        typed_text = typed_pdf.pages[0].extract_text()
        self.assertIn('Synthetic Test Signer', typed_text)
        self.assertIn('TEST ONLY - NOT LEGALLY SIGNED', typed_text)

        drawn = SimpleNamespace(
            action_type=OriginationSigningAction.TYPE_SIGNATURE,
            stamp_asset_id=None,
            metadata={'signature_capture': {
                'method': 'drawn', 'strokes': [[[0, .5], [.5, 0], [1, .5]]],
            }},
        )
        drawn_pdf = PdfReader(BytesIO(_test_overlay(200, 100, [(slot, drawn)])))
        self.assertEqual(len(drawn_pdf.pages), 1)
        self.assertIn('TEST ONLY - NOT LEGALLY SIGNED', drawn_pdf.pages[0].extract_text())

        stamp = SimpleNamespace(
            action_type=OriginationSigningAction.TYPE_STAMP,
            stamp_asset_id='synthetic-stamp', metadata={},
            stamp_asset=SimpleNamespace(image_png=b64decode(
                'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
            )),
        )
        stamp_slot = {
            'box': {'x': 20, 'y': 20, 'width': 160, 'height': 45},
            'padding': {'x': 4, 'y': 3}, 'rotation': 6,
            'align': 'right', 'vertical_align': 'top', 'stamp_fit': 'contain',
        }
        stamp_pdf = PdfReader(BytesIO(_test_overlay(200, 100, [(stamp_slot, stamp)])))
        self.assertEqual(len(stamp_pdf.pages), 1)
        self.assertIn('TEST ONLY - NOT LEGALLY SIGNED', stamp_pdf.pages[0].extract_text())

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
            correction_items=[{
                'target_type': 'field', 'target_key': 'customer_name',
                'instruction': 'Confirm the Applicant name.',
            }],
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

    def test_primary_template_slots_preserve_product_signer_identity_mappings(self):
        self.product.form_schema = {'fields': [
            {'key': 'customer_name', 'type': 'text', 'required': True},
            {'key': 'applicant_mobile', 'type': 'phone', 'required': True},
        ]}
        self.product.signer_rules = [{
            'role': 'borrower', 'required': True,
            'identity_fields': {'name': 'customer_name', 'phone': 'applicant_mobile'},
            'slots': [{'key': 'product_signature', 'type': 'signature', 'required': True}],
        }]
        self.product.save(update_fields=['form_schema', 'signer_rules', 'updated_at'])
        OriginationDocumentTemplate.objects.create(
            product_definition=self.product,
            document_key='primary', document_role='primary', inclusion_mode='required',
            document_type=self.product.document_type, name='Primary LAF', version=1,
            status='active', source_filename='primary.pdf', source_sha256='1' * 64,
            source_byte_size=100, page_count=1, placement_config={}, created_by=self.officer,
            signer_rules=[{
                'role': 'borrower', 'required': True,
                'slots': [{'key': 'pdf_signature', 'type': 'signature', 'required': True}],
            }],
        )

        application, _replayed = create_application(
            product_key=self.product.product_key, officer=self.officer,
            branch='Synthetic Branch', client_request_id='primary-signer-merge',
        )

        rule = application.packet_documents.get(document_key='primary').signer_rules_snapshot[0]
        self.assertEqual(rule['identity_fields'], {
            'name': 'customer_name', 'phone': 'applicant_mobile',
        })
        self.assertEqual([item['key'] for item in rule['slots']], ['pdf_signature'])

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
                {'key': 'guarantor_phone', 'type': 'phone', 'required': True},
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
                'guarantor_phone': '0712345678',
            }, expected_revision=application.revision, request_id='packet-support-save',
        )
        support_document.refresh_from_db()
        self.assertEqual(application.form_payload['customer_name'], 'Synthetic Customer')
        self.assertEqual(support_document.field_payload, {
            'guarantor_name': 'Synthetic Guarantor',
            'guarantor_phone': '0712345678',
        })
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

        application.status = LoanOriginationApplication.STATUS_READY_FOR_REVIEW
        application.save(update_fields=['status'])
        application = review_application(
            application_id=application.pk,
            actor=self.reviewer,
            expected_revision=application.revision,
            request_id='request-supporting-field-correction',
            decision='request_correction',
            reason='Correct only the guarantor name.',
            correction_items=[{
                'target_type': 'document_field',
                'target_key': 'guarantor_consent.guarantor_name',
                'instruction': 'Use the National ID spelling.',
            }],
        )
        with self.assertRaisesRegex(OriginationError, 'Only supporting-document fields requested'):
            save_document_fields(
                application_id=application.pk,
                document_key='guarantor_consent',
                actor=self.officer,
                payload={'guarantor_phone': '0799999999'},
                expected_revision=application.revision,
                request_id='change-locked-supporting-field',
            )
        application = save_document_fields(
            application_id=application.pk,
            document_key='guarantor_consent',
            actor=self.officer,
            payload={'guarantor_name': 'Corrected Guarantor'},
            expected_revision=application.revision,
            request_id='save-supporting-field-correction',
        )
        support_document.refresh_from_db()
        self.assertEqual(support_document.field_payload, {
            'guarantor_name': 'Corrected Guarantor',
            'guarantor_phone': '0712345678',
        })

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
    def setUp(self):
        self.actor = get_user_model().objects.create_superuser(
            username='packet-wizard-admin', email='packet-wizard@example.test', password='password',
        )
        self.product = OriginationProductDefinition.objects.create(
            product_key='packet-admin', name='Packet admin product', version=1,
            form_schema={'fields': [{'key': 'consent', 'type': 'boolean', 'required': True}]},
            signer_rules=[], document_type='packet_admin', document_template_name='',
            document_template_version=1, document_template_sha256='', is_active=False,
        )
        self.client.force_login(self.actor)

    def test_draft_product_has_a_single_guided_supporting_document_entrypoint(self):
        response = self.client.get(reverse(
            'admin:core_originationproductdefinition_supporting_document_setup', args=[self.product.pk],
        ))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Add a supporting document')
        self.assertContains(response, 'Use a published reusable document')
        self.assertContains(response, 'Create a reusable document')
        self.assertContains(response, 'origination-product-builder')

    def test_packet_card_can_add_and_remove_a_reusable_document(self):
        template = OriginationDocumentTemplate.objects.create(
            product_definition=None, document_key='packet_guarantor', document_role='supporting',
            inclusion_mode='required', document_type='packet_guarantor', name='Packet guarantor form',
            version=1, status='active', source_filename='guarantor.pdf', source_sha256='4' * 64,
            source_byte_size=100, page_count=1, placement_config={}, created_by=self.actor,
            form_schema={'fields': [{'key': 'guarantor_name', 'type': 'text', 'required': True}]},
        )
        revision = OriginationTemplateConfigurationRevision.objects.create(
            template=template, revision=1, configuration={}, is_published=True, created_by=self.actor,
        )
        template.published_configuration_revision = revision
        template.save(update_fields=['published_configuration_revision'])
        add_url = reverse(
            'admin:core_originationproductdefinition_packet_add_shared', args=[self.product.pk],
        )

        response = self.client.post(add_url, {'template_id': template.pk})

        self.assertEqual(response.status_code, 200)
        assignment = OriginationProductDocumentAssignment.objects.get(product_definition=self.product)
        self.assertEqual(response.json()['assignment_id'], str(assignment.pk))
        remove_url = reverse(
            'admin:core_originationproductdefinition_packet_remove_shared',
            args=[self.product.pk, assignment.pk],
        )
        response = self.client.post(remove_url)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['removed'])
        self.assertFalse(OriginationProductDocumentAssignment.objects.filter(pk=assignment.pk).exists())
        self.assertTrue(OriginationDocumentTemplate.objects.filter(pk=template.pk).exists())
