from base64 import b64decode
import hashlib
import json
from io import BytesIO, StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from pypdf import PdfReader, PdfWriter

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from core.admin import OriginationProductDefinitionForm
from core.models import (
    LoanOriginationApplication,
    OriginationApplicationEvent,
    OriginationConsentPolicyVersion,
    OriginationReviewerNotice,
    OriginationDataField,
    OriginationDocumentTemplate,
    OriginationProductDocumentAssignment,
    OriginationProductDefinition,
    OriginationSigningAction,
    OriginationSigningActionInvalidation,
    OriginationSigningPackage,
    OriginationTemplateConfigurationRevision,
)
from core.services.loan_origination import (
    OriginationConflict,
    OriginationError,
    OriginationRecallConfirmationRequired,
    _package_review_scope_hash,
    applicant_identity_snapshot,
    create_application,
    frozen_unsigned_package_content,
    prepare_review_package,
    prepare_signing_package,
    preview_context,
    recover_legacy_frozen_package,
    recall_application,
    review_application,
    render_review_package,
    reset_unrecoverable_package_for_review,
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
    mark_packet_previewed,
    save_document_fields,
    select_documents,
    serialize_packet,
    render_packet,
    validate_applicability_rule,
)
from core.services.origination_consent import apply_consent_notice
from core.services.origination_final_review import final_review_signed_packet
from core.services.origination_templates import (
    attach_shared_document_template,
    attach_shared_supporting_template,
)
from core.services.origination_signing import (
    _validated_signature_capture,
    _slot_overlay,
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

    def test_optional_second_guarantor_is_complete_or_empty(self):
        schema = {'fields': [
            {'key': 'guarantor_2_name', 'type': 'text', 'required': False},
            {'key': 'guarantor_2_id_number', 'type': 'national_id', 'required': False},
            {'key': 'guarantor_2_phone', 'type': 'phone', 'required': False},
            {'key': 'guarantor_2_relationship', 'type': 'text', 'required': False},
            {'key': 'guarantor_2_residence_location', 'type': 'text', 'required': False},
        ]}
        empty = validate_form_payload(schema, {}, require_complete=True)
        partial = validate_form_payload(schema, {'guarantor_2_phone': '0712345678'}, require_complete=True)
        complete = validate_form_payload(schema, {
            'guarantor_2_name': 'Synthetic Guarantor',
            'guarantor_2_id_number': '12345678',
            'guarantor_2_phone': '0712345678',
            'guarantor_2_relationship': 'Friend',
            'guarantor_2_residence_location': 'Synthetic Place',
        }, require_complete=True)
        self.assertTrue(empty.valid)
        self.assertFalse(partial.valid)
        self.assertIn('guarantor_2_name', partial.errors)
        self.assertTrue(complete.valid)

    def test_repeatable_form_column_widths_require_one_hundred_percent(self):
        from core.services.loan_origination import validate_product_form_contract
        schema = {'fields': [{
            'key': 'loans', 'type': 'repeating_group',
            'structure': {'min_items': 0, 'max_items': 3, 'columns': [{'key': 'institution'}]},
            'repeatable_layout': {'column_widths': [40, 40]},
        }]}
        with self.assertRaisesRegex(OriginationError, 'totaling 100%'):
            validate_product_form_contract(schema, [], require_signers=False)
        schema['fields'][0]['repeatable_layout']['column_widths'] = [35, 65]
        validate_product_form_contract(schema, [], require_signers=False)

    def test_pdf_dates_use_kenyan_short_format(self):
        from core.services.partnership_laf_preview import _formatted_value
        self.assertEqual(_formatted_value('2026-08-26', {'value_format': 'date_dmy_short'}), '26-08-26')

    def _freeze_for_review(self, application, *, reviewer=None, request_id='preview-frozen-packet'):
        content = b'%PDF-synthetic-frozen-review'
        content_hash = hashlib.sha256(content).hexdigest()
        package = OriginationSigningPackage.objects.create(
            application=application,
            application_revision=application.revision,
            external_reference=f'REVIEW-{str(application.pk)[:12]}-{application.revision}',
            document_type=application.product_definition.document_type,
            template_version=application.product_definition.document_template_version,
            template_sha256=application.product_definition.document_template_sha256,
            context_snapshot={'revision': application.revision},
            participants_snapshot=[],
            requirement_evidence_snapshot=[],
            document_manifest_snapshot=[],
            template_configuration_snapshot={},
            combined_document_hash=content_hash,
            frozen_unsigned_document=content,
            unsigned_document_hash=content_hash,
            prepared_by=self.officer,
            prepared_at=timezone.now(),
        )
        package.review_scope_sha256 = _package_review_scope_hash(package)
        package.save(update_fields=['review_scope_sha256', 'updated_at'])
        if reviewer:
            OriginationApplicationEvent.objects.create(
                application=application,
                action='review_packet_previewed',
                revision=application.revision,
                actor=reviewer,
                request_id=request_id,
                after_values={
                    'package_id': str(package.pk),
                    'unsigned_document_hash': package.unsigned_document_hash,
                    'review_scope_sha256': package.review_scope_sha256,
                },
            )
        return package

    @staticmethod
    def _review_packet_kwargs(package):
        return {
            'package_id': package.pk,
            'expected_unsigned_hash': package.unsigned_document_hash,
            'expected_review_scope_hash': package.review_scope_sha256,
        }

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
        review_package = self._freeze_for_review(application, reviewer=self.reviewer)
        with self.assertRaises(OriginationError):
            review_application(
                application_id=application.pk,
                actor=self.officer,
                expected_revision=application.revision,
                request_id='self-review',
                decision='approve',
                **self._review_packet_kwargs(review_package),
            )
        application = review_application(
            application_id=application.pk,
            actor=self.reviewer,
            expected_revision=application.revision,
            request_id='review-flow',
            decision='approve',
            **self._review_packet_kwargs(review_package),
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
        self.assertEqual(OriginationApplicationEvent.objects.filter(application=application).count(), 7)

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

    @patch('core.services.origination_documents.render_packet')
    def test_operations_freezes_packet_before_checker_review(self, render_packet_mock):
        render_packet_mock.return_value = (b'%PDF-frozen-review', [{
            'key': 'primary', 'rendered_sha256': 'c' * 64,
        }])
        OriginationDocumentTemplate.objects.create(
            product_definition=self.product,
            document_key='primary', document_role='primary', inclusion_mode='required',
            document_type=self.product.document_type, name='Primary LAF', version=1,
            status='active', source_filename='primary.pdf', source_sha256='c' * 64,
            source_byte_size=100, page_count=1, placement_config={}, created_by=self.officer,
        )
        application, _ = create_application(
            product_key=self.product.product_key, officer=self.officer,
            branch='Synthetic Branch', client_request_id='freeze-review-packet',
        )
        application.status = LoanOriginationApplication.STATUS_READY_FOR_REVIEW
        application.save(update_fields=['status'])

        package, replayed = prepare_review_package(
            application_id=application.pk, actor=self.reviewer,
            expected_revision=application.revision, request_id='prepare-review-packet',
        )

        application.refresh_from_db()
        self.assertFalse(replayed)
        self.assertEqual(application.status, LoanOriginationApplication.STATUS_READY_FOR_REVIEW)
        self.assertEqual(package.prepared_by, self.reviewer)
        self.assertEqual(len(package.unsigned_document_hash), 64)
        self.assertEqual(len(package.review_scope_sha256), 64)
        self.assertEqual(bytes(package.frozen_unsigned_document), b'%PDF-frozen-review')
        self.assertTrue(application.events.filter(action='review_packet_prepared').exists())

    @patch('core.services.origination_documents.render_packet')
    def test_approved_review_packet_uses_exact_frozen_bytes(self, render_packet_mock):
        frozen = b'%PDF-exact-checker-review'
        render_packet_mock.return_value = (frozen, [{'key': 'primary', 'page_count': 1}])
        OriginationDocumentTemplate.objects.create(
            product_definition=self.product,
            document_key='primary', document_role='primary', inclusion_mode='required',
            document_type=self.product.document_type, name='Primary LAF', version=1,
            status='active', source_filename='primary.pdf', source_sha256='c' * 64,
            source_byte_size=100, page_count=1, placement_config={}, created_by=self.officer,
        )
        application, _ = create_application(
            product_key=self.product.product_key, officer=self.officer,
            branch='Synthetic Branch', client_request_id='immutable-review-bytes',
        )
        application.status = LoanOriginationApplication.STATUS_READY_FOR_REVIEW
        application.save(update_fields=['status'])
        package, _ = prepare_review_package(
            application_id=application.pk, actor=self.reviewer,
            expected_revision=application.revision, request_id='immutable-review-prepare',
        )
        application.reviewed_by = self.reviewer
        application.reviewed_at = timezone.now()
        application.save(update_fields=['reviewed_by', 'reviewed_at'])

        render_packet_mock.side_effect = AssertionError('live application must not be rendered')
        self.assertEqual(render_review_package(package), frozen)

    def test_checker_identity_is_not_projected_as_branch_manager(self):
        application, _ = create_application(
            product_key=self.product.product_key, officer=self.officer,
            branch='Synthetic Branch', client_request_id='separate-checker-branch-manager',
        )
        application.reviewed_by = self.reviewer
        application.save(update_fields=['reviewed_by'])
        self.assertEqual(preview_context(application)['branch_manager_name'], '')

    def test_frozen_packet_integrity_rejects_corrupted_bytes(self):
        application, _ = create_application(
            product_key=self.product.product_key, officer=self.officer,
            branch='Synthetic Branch', client_request_id='corrupted-frozen-bytes',
        )
        package = self._freeze_for_review(application)
        package.frozen_unsigned_document = b'tampered'
        with self.assertRaisesRegex(OriginationConflict, 'integrity check'):
            frozen_unsigned_package_content(package)

    @patch('core.services.origination_documents.render_packet')
    def test_legacy_packet_recovery_requires_exact_original_hashes(self, render_packet_mock):
        application, _ = create_application(
            product_key=self.product.product_key, officer=self.officer,
            branch='Synthetic Branch', client_request_id='legacy-review-recovery',
        )
        content = b'%PDF-legacy-frozen'
        manifest = [{'key': 'primary', 'page_count': 1}]
        digest = hashlib.sha256(content).hexdigest()
        package = OriginationSigningPackage.objects.create(
            application=application, application_revision=application.revision,
            external_reference='LEGACY-RECOVERY-PACKAGE', document_type='synthetic',
            context_snapshot={'branch_manager_name': ''}, document_manifest_snapshot=manifest,
            unsigned_document_hash=digest, combined_document_hash=digest,
        )
        render_packet_mock.return_value = (content, manifest)

        dry_run = recover_legacy_frozen_package(
            package_id=package.pk, request_id='legacy-recover-dry-run', apply=False,
        )
        self.assertTrue(dry_run['recoverable'])
        package.refresh_from_db()
        self.assertFalse(package.frozen_unsigned_document)

        applied = recover_legacy_frozen_package(
            package_id=package.pk, request_id='legacy-recover-apply', apply=True,
        )
        self.assertTrue(applied['applied'])
        package.refresh_from_db()
        self.assertEqual(bytes(package.frozen_unsigned_document), content)
        self.assertTrue(application.events.filter(action='frozen_packet_recovered').exists())

    def test_unrecoverable_untouched_package_returns_application_to_review(self):
        application, _ = create_application(
            product_key=self.product.product_key, officer=self.officer,
            branch='Synthetic Branch', client_request_id='legacy-review-reset',
        )
        application.status = LoanOriginationApplication.STATUS_REVIEWED
        application.reviewed_by = self.reviewer
        application.reviewed_at = timezone.now()
        application.save(update_fields=['status', 'reviewed_by', 'reviewed_at'])
        package = OriginationSigningPackage.objects.create(
            application=application, application_revision=application.revision,
            external_reference='LEGACY-RESET-PACKAGE', document_type='synthetic',
            unsigned_document_hash='d' * 64, combined_document_hash='d' * 64,
        )

        reset = reset_unrecoverable_package_for_review(
            package_id=package.pk, request_id='legacy-reset-apply',
        )
        package.refresh_from_db()
        self.assertEqual(package.status, OriginationSigningPackage.STATUS_CANCELLED)
        self.assertEqual(reset.status, LoanOriginationApplication.STATUS_READY_FOR_REVIEW)
        self.assertIsNone(reset.reviewed_by)
        self.assertTrue(reset.events.filter(action='legacy_packet_reset_for_review').exists())

    def test_legacy_packet_repair_command_is_dry_run_by_default(self):
        application, _ = create_application(
            product_key=self.product.product_key, officer=self.officer,
            branch='Synthetic Branch', client_request_id='legacy-command-dry-run',
        )
        content = b'%PDF-command-recovery'
        digest = hashlib.sha256(content).hexdigest()
        package = OriginationSigningPackage.objects.create(
            application=application, application_revision=application.revision,
            external_reference='LEGACY-COMMAND-PACKAGE', document_type='synthetic',
            unsigned_document_hash=digest, combined_document_hash=digest,
        )
        output = StringIO()
        with patch(
            'core.services.origination_documents.render_packet', return_value=(content, []),
        ):
            call_command(
                'repair_origination_frozen_packet', package_id=str(package.pk), stdout=output,
            )
        package.refresh_from_db()
        self.assertFalse(package.frozen_unsigned_document)
        self.assertIn('DRY-RUN', output.getvalue())
        with self.assertRaises(CommandError):
            call_command(
                'repair_origination_frozen_packet', package_id=str(package.pk),
                reset_for_review=True, stdout=StringIO(), stderr=StringIO(),
            )

    def test_checker_must_preview_frozen_packet_and_approved_recall_is_explicit(self):
        application, _ = create_application(
            product_key=self.product.product_key, officer=self.officer,
            branch='Synthetic Branch', client_request_id='approved-recall',
        )
        application.status = LoanOriginationApplication.STATUS_READY_FOR_REVIEW
        application.save(update_fields=['status'])
        package = self._freeze_for_review(application)
        review_kwargs = self._review_packet_kwargs(package)
        with self.assertRaisesRegex(OriginationError, 'Open the frozen review packet'):
            review_application(
                application_id=application.pk, actor=self.reviewer,
                expected_revision=application.revision, request_id='approve-before-preview',
                decision='approve', **review_kwargs,
            )
        OriginationApplicationEvent.objects.create(
            application=application, action='review_packet_previewed',
            revision=application.revision, actor=self.reviewer, request_id='checker-preview',
            after_values={
                'package_id': str(package.pk),
                'unsigned_document_hash': package.unsigned_document_hash,
                'review_scope_sha256': package.review_scope_sha256,
            },
        )
        application = review_application(
            application_id=application.pk, actor=self.reviewer,
            expected_revision=application.revision, request_id='approve-after-preview',
            decision='approve', **review_kwargs,
        )
        with self.assertRaises(OriginationRecallConfirmationRequired):
            recall_application(
                application_id=application.pk, actor=self.officer,
                expected_revision=application.revision, request_id='recall-unconfirmed',
            )
        recalled = recall_application(
            application_id=application.pk, actor=self.officer,
            expected_revision=application.revision, request_id='recall-confirmed',
            confirmed_package_id=str(package.pk),
            confirmed_package_hash=package.unsigned_document_hash,
        )
        package.refresh_from_db()
        self.assertEqual(recalled.status, LoanOriginationApplication.STATUS_DRAFT)
        self.assertEqual(recalled.recheck_assigned_to, self.reviewer)
        self.assertEqual(package.status, OriginationSigningPackage.STATUS_CANCELLED)
        self.assertTrue(OriginationReviewerNotice.objects.filter(
            application=recalled, recipient=self.reviewer,
        ).exists())

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
        review_package = self._freeze_for_review(application, reviewer=self.reviewer)
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
            **self._review_packet_kwargs(review_package),
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
        review_package = self._freeze_for_review(
            application, reviewer=alternate_reviewer, request_id='alternate-review-preview',
        )

        with self.assertRaisesRegex(OriginationError, 'original checker'):
            review_application(
                application_id=application.pk,
                actor=alternate_reviewer,
                expected_revision=application.revision,
                request_id='unauthorized-correction-recheck',
                decision='approve',
                **self._review_packet_kwargs(review_package),
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
                }, {
                    'key': 'agreement_signature',
                    'document_key': 'primary',
                    'type': 'signature',
                    'required': True,
                }, {
                    'key': 'signed_date',
                    'document_key': 'primary',
                    'type': 'date_signed',
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
        self.assertEqual(OriginationSigningAction.objects.filter(package=package).count(), 3)
        signature_actions = OriginationSigningAction.objects.filter(
            package=package, action_type=OriginationSigningAction.TYPE_SIGNATURE,
        )
        self.assertEqual(signature_actions.count(), 2)
        self.assertEqual(
            {action.metadata['signature_capture']['name'] for action in signature_actions},
            {'Synthetic Test Signer'},
        )
        self.assertTrue(all(len(action.metadata['capture_sha256']) == 64 for action in signature_actions))
        serialized = serialize_test_signing(package)
        self.assertEqual(serialized['slots'][0]['capture_method'], 'typed')
        self.assertEqual(serialized['slots'][1]['capture_method'], 'typed')
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

    def test_verified_overlay_without_slots_still_has_one_mergeable_page(self):
        overlay = PdfReader(BytesIO(_slot_overlay(200, 100, [], test_mode=False)))

        self.assertEqual(len(overlay.pages), 1)

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
        review_package = self._freeze_for_review(application, reviewer=self.officer)
        corrected = review_application(
            application_id=application.pk, actor=self.officer,
            expected_revision=application.revision, request_id='superuser-correction-review',
            decision='request_correction', reason='Correct the preview alignment.',
            correction_items=[{
                'target_type': 'field', 'target_key': 'customer_name',
                'instruction': 'Confirm the Applicant name.',
            }],
            **self._review_packet_kwargs(review_package),
        )
        self.assertEqual(corrected.status, LoanOriginationApplication.STATUS_CORRECTION_REQUIRED)

        corrected.status = LoanOriginationApplication.STATUS_READY_FOR_REVIEW
        corrected.save(update_fields=['status'])
        review_package = self._freeze_for_review(
            corrected, reviewer=self.officer, request_id='superuser-approved-preview',
        )
        approved = review_application(
            application_id=corrected.pk, actor=self.officer,
            expected_revision=corrected.revision, request_id='superuser-approve-review',
            decision='approve',
            **self._review_packet_kwargs(review_package),
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
        mark_packet_previewed(application)
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
        review_package = self._freeze_for_review(application, reviewer=self.reviewer)
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
            **self._review_packet_kwargs(review_package),
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

    def test_supporting_document_selection_does_not_require_a_separate_primary_preview(self):
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
        selected = select_documents(
            application_id=application.pk, actor=self.officer,
            selected_keys=['optional_notice'], expected_revision=application.revision,
            request_id='packet-gate-select',
        )
        self.assertTrue(selected.packet_documents.get(document_key='optional_notice').selected)
        self.assertIsNone(selected.primary_previewed_revision)

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
            {'description': 'Synthetic asset', 'estimated_value': '12500'},
        ]})
        self.assertEqual(normalized['secured_assets'][0]['estimated_value'], '12500')
        self.assertEqual(len(normalized['secured_assets'][0]['row_id']), 36)
        self.assertTrue(validate_form_payload(schema, normalized, require_complete=True).valid)
        fractional = normalize_form_payload(schema, {'secured_assets': [
            {'description': 'Synthetic asset', 'estimated_value': '12500.50'},
        ]})
        self.assertFalse(validate_form_payload(schema, fractional, require_complete=True).valid)
        too_many = {'secured_assets': normalized['secured_assets'] * 12}
        result = validate_form_payload(schema, too_many, require_complete=True)
        self.assertFalse(result.valid)
        self.assertIn('11', result.errors['secured_assets'])
        duplicate = {'secured_assets': [normalized['secured_assets'][0], normalized['secured_assets'][0]]}
        result = validate_form_payload(schema, duplicate, require_complete=True)
        self.assertFalse(result.valid)
        self.assertIn('duplicate identity', result.errors['secured_assets'])

    def test_saved_repeatable_security_repairs_blank_containers_and_grouped_amounts(self):
        schema = {'fields': [{
            'key': 'pledged_assets', 'type': 'repeating_group', 'required': True,
            'structure': {
                'min_items': 1, 'max_items': 4,
                'columns': [
                    {'key': 'description', 'label': 'Description', 'type': 'text', 'required': True},
                    {'key': 'year_of_purchase', 'label': 'Year of purchase', 'type': 'number', 'required': True},
                    {'key': 'serial_number', 'label': 'Serial number', 'type': 'text', 'required': False},
                    {'key': 'current_value', 'label': 'Current value', 'type': 'money', 'required': True},
                ],
            },
        }]}
        normalized = normalize_form_payload(schema, {'pledged_assets': [{
            'description': 'Synthetic asset',
            'year_of_purchase': [],
            'serial_number': {},
            'current_value': 'KES 12\u202f500',
        }]})

        row = normalized['pledged_assets'][0]
        self.assertEqual(row['year_of_purchase'], '')
        self.assertEqual(row['serial_number'], '')
        self.assertEqual(row['current_value'], '12500')
        self.assertTrue(validate_form_payload(schema, normalized, require_complete=False).valid)
        complete = validate_form_payload(schema, normalized, require_complete=True)
        self.assertFalse(complete.valid)
        self.assertEqual(
            complete.errors['pledged_assets'],
            'Complete Year of purchase in row 1.',
        )

        invalid = normalize_form_payload(schema, {'pledged_assets': [{
            'description': 'Synthetic asset',
            'year_of_purchase': 'not-a-year',
            'serial_number': '',
            'current_value': '12500',
        }]})
        invalid_result = validate_form_payload(schema, invalid, require_complete=False)
        self.assertEqual(
            invalid_result.errors['pledged_assets'],
            'Enter a valid Year of purchase in row 1.',
        )

        self.product.form_schema = schema
        self.product.save(update_fields=['form_schema'])
        application, _ = create_application(
            product_key=self.product.product_key,
            officer=self.officer,
            branch='Synthetic Branch',
            client_request_id='saved-security-repair-create',
        )
        saved = save_application_fields(
            application_id=application.pk,
            actor=self.officer,
            payload={'pledged_assets': [{
                'description': 'Synthetic asset',
                'year_of_purchase': [],
                'serial_number': {},
                'current_value': 'KES 12\u202f500',
            }]},
            expected_revision=application.revision,
            request_id='saved-security-repair-save',
        )
        self.assertEqual(saved.form_payload['pledged_assets'][0]['year_of_purchase'], '')
        self.assertEqual(saved.form_payload['pledged_assets'][0]['current_value'], '12500')

    @staticmethod
    def _blank_pdf() -> bytes:
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        output = BytesIO()
        writer.write(output)
        return output.getvalue()

    def _active_consent_policy(self):
        return OriginationConsentPolicyVersion.objects.create(
            version='conditional-v1', status=OriginationConsentPolicyVersion.STATUS_ACTIVE,
            packet_clause=(
                'The signatures in this packet record provisional consent. The application and '
                'packet remain subject to JBL verification and independent final approval.'
            ),
            signer_consent_text='I provisionally consent to these exact packet bytes.',
            signer_completion_text='Signing is complete and JBL final approval is pending.',
            resigning_text='The corrected packet differs from the prior packet and requires fresh consent.',
            approval_reference='COMPLIANCE-SYNTHETIC-001', approved_by=self.reviewer,
            approved_at=timezone.now(), created_by=self.reviewer,
        )

    @override_settings(ORIGINATION_CONDITIONAL_APPROVAL_ENABLED=True)
    def test_conditional_clause_is_inside_the_exact_packet_bytes(self):
        policy = self._active_consent_policy()
        application, _ = create_application(
            product_key=self.product.product_key, officer=self.officer,
            branch='Synthetic Branch', client_request_id='conditional-notice-application',
        )

        original = self._blank_pdf()
        content, manifest, delivery = apply_consent_notice(
            application=application, packet_pdf=original,
            document_manifest=[{'key': 'primary', 'page_count': 1}], policy=policy,
        )

        reader = PdfReader(BytesIO(content))
        self.assertEqual(len(reader.pages), 2)
        notice_text = ' '.join(reader.pages[0].extract_text().split())
        self.assertIn('subject to JBL verification', notice_text)
        self.assertEqual(delivery, 'notice_page')
        self.assertEqual(manifest[0]['consent_policy_sha256'], policy.content_sha256)
        self.assertNotEqual(hashlib.sha256(content).hexdigest(), hashlib.sha256(original).hexdigest())

    def _signed_conditional_package(self, *, with_signature=False):
        policy = self._active_consent_policy()
        application, _ = create_application(
            product_key=self.product.product_key, officer=self.officer,
            branch='Synthetic Branch', client_request_id=f'conditional-signed-{with_signature}',
        )
        application.status = LoanOriginationApplication.STATUS_SIGNED_PENDING_APPROVAL
        application.save(update_fields=['status'])
        content = self._blank_pdf()
        digest = hashlib.sha256(content).hexdigest()
        participants = []
        if with_signature:
            participants = [{
                'role': 'branch_manager', 'required': True, 'applicable': True,
                'slots': [{
                    'key': 'approval_signature', 'document_key': 'primary',
                    'type': 'signature', 'required': True,
                }],
            }]
        package = OriginationSigningPackage.objects.create(
            application=application, application_revision=application.revision,
            external_reference=f'CONDITIONAL-{str(application.pk)[:12]}',
            document_type=self.product.document_type,
            template_version=1, template_sha256=self.product.document_template_sha256,
            context_snapshot={}, participants_snapshot=participants,
            requirement_evidence_snapshot=[], document_manifest_snapshot=[],
            template_configuration_snapshot={}, combined_document_hash=digest,
            frozen_unsigned_document=content, unsigned_document_hash=digest,
            status=OriginationSigningPackage.STATUS_FULLY_SIGNED,
            conditional_approval=True, consent_policy=policy,
            consent_policy_snapshot={
                'id': str(policy.pk), 'version': policy.version,
                'content_sha256': policy.content_sha256,
            },
            signed_document_hash=digest, pending_signed_document=content,
            finalized_at=timezone.now(), archive_status='not_ready',
            prepared_by=self.officer, prepared_at=timezone.now(),
        )
        action = None
        if with_signature:
            action = OriginationSigningAction.objects.create(
                package=package, document_key='primary', slot_key='approval_signature',
                signer_role='branch_manager', action_type=OriginationSigningAction.TYPE_SIGNATURE,
                mode=OriginationSigningAction.MODE_VERIFIED, actor=self.reviewer,
                request_id='conditional-original-signature', metadata={},
            )
        OriginationApplicationEvent.objects.create(
            application=application, action='signed_packet_accessed',
            revision=application.revision, actor=self.reviewer,
            request_id=f'conditional-packet-open-{with_signature}',
            after_values={
                'package_id': str(package.pk), 'signed_document_hash': digest,
            },
        )
        return application, package, action

    @patch('core.services.origination_esign._archive_signed_package_after_commit')
    def test_independent_final_review_approves_exact_opened_hash(self, archive_mock):
        application, package, _action = self._signed_conditional_package()

        reviewed = final_review_signed_packet(
            application_id=application.pk, package_id=package.pk, actor=self.reviewer,
            expected_revision=application.revision,
            expected_signed_hash=package.signed_document_hash,
            decision='approve', reason='', correction_items=[],
            request_id='conditional-final-approve',
        )

        package.refresh_from_db()
        self.assertEqual(reviewed.status, LoanOriginationApplication.STATUS_APPROVED)
        self.assertEqual(package.final_approved_signed_document_hash, package.signed_document_hash)
        self.assertEqual(package.archive_status, 'pending')
        event = reviewed.events.get(action='final_review_approve')
        self.assertIsNotNone(event.after_values['signed_to_review_seconds'])
        archive_mock.assert_not_called()

    def test_signature_only_correction_invalidates_and_supersedes_exact_action(self):
        application, package, action = self._signed_conditional_package(with_signature=True)

        reviewed = final_review_signed_packet(
            application_id=application.pk, package_id=package.pk, actor=self.reviewer,
            expected_revision=application.revision,
            expected_signed_hash=package.signed_document_hash,
            decision='request_correction', reason='Capture the management signature again.',
            correction_items=[{
                'target_type': 'signature_slot',
                'target_key': 'primary.approval_signature',
                'instruction': 'The prior signature is incomplete.',
            }], request_id='conditional-signature-correction',
        )

        package.refresh_from_db()
        self.assertEqual(reviewed.status, LoanOriginationApplication.STATUS_PARTIALLY_SIGNED)
        self.assertTrue(OriginationSigningActionInvalidation.objects.filter(action=action).exists())
        self.assertEqual(package.signed_document_hash, '')
        from core.services.origination_esign import _create_or_get_active_action
        replacement, created = _create_or_get_active_action(
            package=package, document_key='primary', slot_key='approval_signature',
            defaults={
                'signer_role': 'branch_manager',
                'action_type': OriginationSigningAction.TYPE_SIGNATURE,
                'mode': OriginationSigningAction.MODE_VERIFIED,
                'actor': self.reviewer, 'request_id': 'conditional-replacement-signature',
                'metadata': {},
            },
        )
        self.assertTrue(created)
        self.assertEqual(replacement.supersedes_id, action.pk)

    @patch('core.services.origination_esign._archive_signed_package_after_commit')
    def test_corrected_final_review_requires_reasoned_checker_takeover(self, archive_mock):
        alternate_reviewer = get_user_model().objects.create_user(
            username='conditional-alternate-reviewer',
        )
        application, package, _action = self._signed_conditional_package()
        application.recheck_assigned_to = self.reviewer
        application.save(update_fields=['recheck_assigned_to'])

        with self.assertRaisesRegex(OriginationError, 'original checker'):
            final_review_signed_packet(
                application_id=application.pk, package_id=package.pk,
                actor=alternate_reviewer, expected_revision=application.revision,
                expected_signed_hash=package.signed_document_hash,
                decision='approve', reason='', correction_items=[],
                request_id='conditional-unrecorded-takeover',
            )

        application = take_over_correction_review(
            application_id=application.pk, actor=alternate_reviewer,
            expected_revision=application.revision,
            request_id='conditional-recorded-takeover',
            reason='The original checker is unavailable.',
        )
        takeover_event = application.events.get(action='correction_review_taken_over')
        self.assertEqual(takeover_event.after_values['review_stage'], 'post_sign_final_review')
        OriginationApplicationEvent.objects.create(
            application=application, action='signed_packet_accessed',
            revision=application.revision, actor=alternate_reviewer,
            request_id='conditional-alternate-packet-open',
            after_values={
                'package_id': str(package.pk),
                'signed_document_hash': package.signed_document_hash,
            },
        )
        reviewed = final_review_signed_packet(
            application_id=application.pk, package_id=package.pk,
            actor=alternate_reviewer, expected_revision=application.revision,
            expected_signed_hash=package.signed_document_hash,
            decision='approve', reason='', correction_items=[],
            request_id='conditional-approved-after-takeover',
        )

        self.assertEqual(reviewed.status, LoanOriginationApplication.STATUS_APPROVED)
        self.assertEqual(reviewed.final_reviewed_by, alternate_reviewer)
        archive_mock.assert_not_called()

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

    def test_reusable_primary_is_merged_snapshotted_and_keeps_document_requirements(self):
        template = OriginationDocumentTemplate.objects.create(
            product_definition=None, document_key='primary', document_role='primary',
            inclusion_mode='required', display_order=0,
            document_type='generic_primary', name='Generic primary LAF', version=1,
            status='active', source_filename='generic.pdf', source_sha256='5' * 64,
            source_byte_size=100, page_count=2, placement_config={}, created_by=self.officer,
            form_schema={
                'identity_contract': 'applicant_v1',
                'sections': [{'key': 'applicant', 'label': 'Applicant'}],
                'fields': [
                    {'key': 'applicant_first_name', 'type': 'text', 'required': True, 'section_key': 'applicant'},
                    {'key': 'applicant_surname', 'type': 'text', 'required': True, 'section_key': 'applicant'},
                    {'key': 'applicant_id_number', 'type': 'national_id', 'required': True, 'section_key': 'applicant'},
                    {'key': 'applicant_phone', 'type': 'phone', 'required': True, 'section_key': 'applicant'},
                    {'key': 'guarantor_1_name', 'type': 'text', 'required': True, 'section_key': 'applicant'},
                ],
                'evidence_requirements': [{
                    'key': 'guarantor_1_id_copy', 'label': 'Guarantor 1 ID Copy',
                    'type': 'document', 'workflow': 'loan_origination',
                    'enforcement_stage': 'review', 'required': True, 'validation': {},
                }, {
                    'key': 'guarantor_2_id_copy', 'label': 'Guarantor 2 ID Copy',
                    'type': 'document', 'workflow': 'loan_origination',
                    'enforcement_stage': 'review', 'required': False,
                    'validation': {'required_when': {'field': 'guarantor_2_name', 'operator': 'truthy'}},
                }],
            },
            signer_rules=[{
                'role': 'borrower', 'required': True,
                'identity_fields': {
                    'name': 'applicant_first_name', 'national_id': 'applicant_id_number',
                    'phone': 'applicant_phone',
                },
                'slots': [{'key': 'borrower_signature', 'type': 'signature', 'required': True}],
            }],
        )
        revision = OriginationTemplateConfigurationRevision.objects.create(
            template=template, revision=1, configuration={}, is_published=True,
            created_by=self.officer,
        )
        template.published_configuration_revision = revision
        template.save(update_fields=['published_configuration_revision'])

        assignment = attach_shared_document_template(
            product_definition=self.product, template=template,
            inclusion_mode='optional', display_order=99, officer_selectable=True,
            default_selected=True, applicability_rule={'field': 'consent', 'operator': 'truthy'},
            actor=self.officer,
        )
        self.product.refresh_from_db()

        self.assertEqual(assignment.document_key, 'primary')
        self.assertEqual(assignment.display_order, 0)
        self.assertEqual(assignment.inclusion_mode, 'required')
        self.assertEqual(assignment.version_policy, assignment.VERSION_PINNED)
        self.assertFalse(assignment.officer_selectable)
        self.assertEqual(self.product.document_template_sha256, template.source_sha256)
        self.assertIn(
            'applicant_id_number',
            {item['key'] for item in self.product.form_schema['fields']},
        )

        application, _ = create_application(
            product_key=self.product.product_key, officer=self.officer,
            branch='Synthetic Branch', client_request_id='shared-primary-create',
        )
        document = application.packet_documents.get(document_key='primary')
        self.assertEqual(document.document_role, 'primary')
        self.assertTrue(document.selected)
        self.assertEqual(document.template_id, template.pk)
        self.assertIn(
            'guarantor_1_id_copy',
            {item['key'] for item in application.product_terms_snapshot['requirements']},
        )
        from core.services.loan_origination import _missing_application_requirements
        self.assertEqual(
            {item['key'] for item in _missing_application_requirements(application, stage='review')},
            {'guarantor_1_id_copy'},
        )
        application.form_payload = {'guarantor_2_name': 'Synthetic Guarantor'}
        self.assertEqual(
            {item['key'] for item in _missing_application_requirements(application, stage='review')},
            {'guarantor_1_id_copy', 'guarantor_2_id_copy'},
        )

        template.status = template.STATUS_RETIRED
        template.save(update_fields=['status'])
        successor = OriginationDocumentTemplate.objects.create(
            product_definition=None, document_key='primary', document_role='primary',
            inclusion_mode='required', display_order=0,
            document_type='generic_primary', name='Generic primary LAF', version=2,
            status='active', source_filename='generic-v2.pdf', source_sha256='4' * 64,
            source_byte_size=100, page_count=2, placement_config={}, created_by=self.officer,
            form_schema=template.form_schema, signer_rules=template.signer_rules,
        )
        successor_revision = OriginationTemplateConfigurationRevision.objects.create(
            template=successor, revision=1, configuration={'marker': 'v2'}, is_published=True,
            created_by=self.officer,
        )
        successor.published_configuration_revision = successor_revision
        successor.save(update_fields=['published_configuration_revision'])

        newer, _ = create_application(
            product_key=self.product.product_key, officer=self.officer,
            branch='Synthetic Branch', client_request_id='shared-primary-v2-create',
        )
        self.assertEqual(newer.packet_documents.get(document_key='primary').template_id, template.pk)
        self.assertEqual(newer.template_configuration_snapshot, {})
        application.refresh_from_db()
        self.assertEqual(application.packet_documents.get(document_key='primary').template_id, template.pk)

    def test_generic_laf_net_income_fields_are_independent_manual_values(self):
        from core.services.generic_jawabu_laf_seed import FIELD_SPECS

        specs = {item['key']: item for item in FIELD_SPECS}
        self.assertEqual(specs['enterprise_net_income']['type'], 'money')
        self.assertEqual(specs['household_net_income']['type'], 'money')
        self.assertEqual(specs['enterprise_net_income']['source'], 'user_input')
        self.assertEqual(specs['household_net_income']['source'], 'user_input')
        self.assertEqual(specs['enterprise_net_income']['validation'], {})
        self.assertEqual(specs['household_net_income']['validation'], {})

    @patch('core.services.generic_jawabu_laf_seed.upload_template_record')
    def test_generic_laf_seed_is_idempotent_and_does_not_attach_products(self, upload_mock):
        from core.services.generic_jawabu_laf_seed import apply_seed

        upload_mock.side_effect = lambda template, **_kwargs: template
        actor = get_user_model().objects.create_superuser(
            username='generic-laf-seed-admin', email='seed@example.test', password='password',
        )
        with TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / 'synthetic-generic-laf.pdf'
            writer = PdfWriter()
            writer.add_blank_page(width=612, height=792)
            writer.add_blank_page(width=612, height=792)
            with pdf_path.open('wb') as output:
                writer.write(output)

            first = apply_seed(pdf_path=pdf_path, actor=actor)
            second = apply_seed(pdf_path=pdf_path, actor=actor)

        self.assertEqual(first['template'].pk, second['template'].pk)
        self.assertEqual(first['template'].document_role, 'primary')
        self.assertIsNone(first['template'].product_definition_id)
        self.assertEqual(first['template'].page_count, 2)
        self.assertEqual(
            OriginationDocumentTemplate.objects.filter(
                document_type='jawabu_generic_laf', source_sha256=first['template'].source_sha256,
            ).count(),
            1,
        )
        self.assertFalse(
            OriginationProductDocumentAssignment.objects.filter(template=first['template']).exists(),
        )
        schema = first['template'].form_schema
        field_keys = [item['key'] for item in schema['fields']]
        self.assertEqual(schema['commercial_section_key'], 'loan_details')
        self.assertNotIn('commercial_terms', [item['key'] for item in schema['sections']])
        self.assertEqual(len(field_keys), len(set(field_keys)))
        self.assertLess(field_keys.index('loan_amount'), field_keys.index('repayment_tenor'))
        repeatables = {item['key']: item for item in schema['fields'] if item['type'] == 'repeating_group'}
        self.assertEqual(repeatables['external_loans']['repeatable_layout']['column_widths'], [50, 50])


class OriginationProductFamilyPurgeTests(TestCase):
    def test_family_purge_is_scoped_audited_and_idempotent(self):
        from core.models import ComplianceAuditChainState, ComplianceAuditEvent
        from core.services.origination_god_mode import purge_origination_product_family

        actor = get_user_model().objects.create_superuser(
            username='family-purge-admin', email='family-purge@example.test', password='password',
        )
        officer = get_user_model().objects.create_user(username='family-purge-officer')
        v1 = OriginationProductDefinition.objects.create(
            product_key='purge-family', name='Purge family', version=1,
            form_schema={'fields': []}, signer_rules=[], document_type='purge-family',
            document_template_name='Purge.pdf', document_template_version=1,
            document_template_sha256='1' * 64, is_active=False,
        )
        OriginationProductDefinition.objects.create(
            product_key='purge-family', name='Purge family', version=2, supersedes=v1,
            form_schema={'fields': []}, signer_rules=[], document_type='purge-family',
            document_template_name='Purge.pdf', document_template_version=2,
            document_template_sha256='2' * 64, is_active=True,
        )
        other = OriginationProductDefinition.objects.create(
            product_key='keep-family', name='Keep family', version=1,
            form_schema={'fields': []}, signer_rules=[], document_type='keep-family',
            document_template_name='Keep.pdf', document_template_version=1,
            document_template_sha256='3' * 64, is_active=True,
        )
        application = LoanOriginationApplication.objects.create(
            reference_number='ORG-PURGE-FAMILY-1',
            product_definition=OriginationProductDefinition.objects.get(product_key='purge-family', version=2),
            officer=officer, branch='Synthetic Branch', client_request_id='family-purge-application',
            schema_snapshot={'fields': []}, signer_rules_snapshot=[],
        )
        ComplianceAuditChainState.objects.get_or_create(singleton=1)

        counts, replayed = purge_origination_product_family(
            product_key='purge-family', actor=actor, reason='Synthetic family cleanup',
            request_id='purge-family-request-1',
        )
        replay_counts, replayed_again = purge_origination_product_family(
            product_key='purge-family', actor=actor, reason='Synthetic family cleanup',
            request_id='purge-family-request-1',
        )

        self.assertFalse(replayed)
        self.assertTrue(replayed_again)
        self.assertEqual(counts, replay_counts)
        self.assertFalse(OriginationProductDefinition.objects.filter(product_key='purge-family').exists())
        self.assertFalse(LoanOriginationApplication.objects.filter(pk=application.pk).exists())
        self.assertTrue(OriginationProductDefinition.objects.filter(pk=other.pk).exists())
        event = ComplianceAuditEvent.objects.get(deduplication_key='origination:product-family-purge:purge-family-request-1')
        self.assertEqual(event.subject_id, 'purge-family')
        self.assertTrue(event.after_values['drive_files_untouched'])


class OriginationDocumentTemplateUploadAdminTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_superuser(
            username='template-upload-admin', email='template-upload@example.test', password='password',
        )
        self.client.force_login(self.actor)
        self.add_url = reverse('admin:core_originationdocumenttemplate_add')

    @staticmethod
    def _pdf_upload(name='generic-laf.pdf', *, width=612):
        output = BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=width, height=792)
        writer.add_blank_page(width=width, height=792)
        writer.write(output)
        return SimpleUploadedFile(name, output.getvalue(), content_type='application/pdf')

    @staticmethod
    def _mark_uploaded(template, **_kwargs):
        template.drive_file_id = f'synthetic-drive-{template.version}'
        template.drive_url = f'https://example.test/templates/{template.pk}'
        template.status = template.STATUS_READY
        template.save(update_fields=['drive_file_id', 'drive_url', 'status', 'updated_at'])
        return template

    def test_upload_page_exposes_reusable_family_and_reviewed_field_setup(self):
        response = self.client.get(self.add_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Reusable template family')
        self.assertContains(response, 'Generic Jawabu LAF - reviewed two-page field set')
        self.assertContains(response, 'No JSON or code entry is required')

    def test_published_reusable_document_prominently_creates_an_editable_version(self):
        configuration = {
            'document_type': 'admin_editable_family',
            'version': 1,
            'field_overlay_manifest': {'fields': {
                'consent': {
                    'context_key': 'consent', 'page_number': 1, 'units': 'pt',
                    'box': {'x': 20, 'y': 700, 'width': 120, 'height': 16},
                },
            }},
            'signature_overlay_manifest': {'slots': {}},
        }
        template = OriginationDocumentTemplate.objects.create(
            product_definition=None, document_key='primary', document_role='primary',
            inclusion_mode='required', display_order=0, document_type='admin_editable_family',
            name='Admin editable family', version=1, status='active',
            source_filename='admin-editable.pdf', source_sha256='d' * 64,
            source_byte_size=100, page_count=1, placement_config=configuration,
            drive_file_id='drive-admin-editable',
            form_schema={'fields': [{'key': 'consent', 'type': 'boolean', 'required': True}]},
            signer_rules=[], created_by=self.actor,
        )
        published = OriginationTemplateConfigurationRevision.objects.create(
            template=template, revision=1, configuration=configuration,
            is_published=True, created_by=self.actor, published_at=timezone.now(),
        )
        template.published_configuration_revision = published
        template.save(update_fields=['published_configuration_revision'])
        change_url = reverse(
            'admin:core_originationdocumenttemplate_change', args=[template.pk],
        )

        page = self.client.get(change_url)

        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Published reusable document')
        self.assertContains(page, 'Create editable version')
        self.assertContains(page, 'Upload replacement PDF instead')
        self.assertContains(page, 'Preview published mapping')

        response = self.client.post(reverse(
            'admin:core_originationdocumenttemplate_create_editable_version',
            args=[template.pk],
        ))

        successor = OriginationDocumentTemplate.objects.get(
            document_type=template.document_type, version=2,
        )
        self.assertRedirects(
            response,
            reverse('admin:core_originationdocumenttemplate_calibrate', args=[successor.pk]),
            fetch_redirect_response=False,
        )
        self.assertEqual(successor.status, successor.STATUS_READY)
        self.assertEqual(successor.drive_file_id, template.drive_file_id)

    @patch('core.services.origination_templates.upload_template_record')
    def test_admin_upload_applies_generic_laf_contract_and_versions_its_family(self, upload_mock):
        upload_mock.side_effect = self._mark_uploaded
        first_response = self.client.post(self.add_url, {
            'product_definition': '',
            'reusable_family': '',
            'schema_preset': 'generic_jawabu_laf',
            'name': 'Generic Jawabu LAF',
            'document_role': OriginationDocumentTemplate.ROLE_PRIMARY,
            'inclusion_mode': OriginationDocumentTemplate.INCLUDE_REQUIRED,
            'display_order': '0',
            'pdf_file': self._pdf_upload(),
        })

        self.assertEqual(first_response.status_code, 302)
        first = OriginationDocumentTemplate.objects.get(document_type='jawabu_generic_laf', version=1)
        self.assertIsNone(first.product_definition_id)
        self.assertEqual(first.document_key, 'primary')
        self.assertEqual(first.document_role, OriginationDocumentTemplate.ROLE_PRIMARY)
        self.assertGreater(len(first.form_schema['fields']), 20)
        self.assertGreater(len(first.signer_rules), 2)
        self.assertTrue(OriginationDataField.objects.filter(key='enterprise_net_income').exists())
        self.assertIn(
            reverse('admin:core_originationdocumenttemplate_calibrate', args=[first.pk]),
            first_response['Location'],
        )

        second_response = self.client.post(self.add_url, {
            'product_definition': '',
            'reusable_family': 'jawabu_generic_laf',
            'schema_preset': '',
            'name': 'Generic Jawabu LAF revised PDF',
            # The selected family is authoritative even if a stale browser posts another role.
            'document_role': OriginationDocumentTemplate.ROLE_SUPPORTING,
            'inclusion_mode': OriginationDocumentTemplate.INCLUDE_REQUIRED,
            'display_order': '0',
            'pdf_file': self._pdf_upload('generic-laf-v2.pdf', width=613),
        })

        self.assertEqual(second_response.status_code, 302)
        second = OriginationDocumentTemplate.objects.get(document_type='jawabu_generic_laf', version=2)
        self.assertEqual(second.document_role, OriginationDocumentTemplate.ROLE_PRIMARY)
        self.assertEqual(second.document_key, 'primary')
        self.assertEqual(second.form_schema, first.form_schema)
        self.assertEqual(second.signer_rules, first.signer_rules)

    @patch('core.services.origination_templates.upload_template_record')
    def test_product_owned_primary_upload_derives_technical_identity(self, upload_mock):
        upload_mock.side_effect = self._mark_uploaded
        product = OriginationProductDefinition.objects.create(
            product_key='admin-upload-product', name='Admin upload product', version=1,
            form_schema={
                'sections': [{'key': 'application', 'label': 'Application'}],
                'fields': [{
                    'key': 'application_note', 'label': 'Application note', 'type': 'text',
                    'required': True, 'section_key': 'application',
                }],
            },
            signer_rules=[], document_type='admin_upload_product',
            document_template_name='', document_template_version=1,
            document_template_sha256='', is_active=False,
        )

        response = self.client.post(self.add_url, {
            'product_definition': str(product.pk),
            'reusable_family': '',
            'schema_preset': '',
            'name': 'Admin upload LAF',
            'document_role': OriginationDocumentTemplate.ROLE_PRIMARY,
            'inclusion_mode': OriginationDocumentTemplate.INCLUDE_REQUIRED,
            'display_order': '0',
            'pdf_file': self._pdf_upload('product-owned.pdf'),
        })

        self.assertEqual(response.status_code, 302)
        template = OriginationDocumentTemplate.objects.get(product_definition=product)
        self.assertEqual(template.document_key, 'primary')
        self.assertEqual(template.document_type, product.document_type)
        self.assertEqual(template.version, product.version)
        self.assertEqual(template.form_schema, product.form_schema)


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

    def test_packet_card_can_assign_a_reusable_primary_and_merge_its_contract(self):
        template = OriginationDocumentTemplate.objects.create(
            product_definition=None, document_key='primary', document_role='primary',
            inclusion_mode='required', display_order=0, document_type='generic_admin_primary',
            name='Generic Admin Primary', version=1, status='active',
            source_filename='generic.pdf', source_sha256='3' * 64,
            source_byte_size=100, page_count=2, placement_config={}, created_by=self.actor,
            form_schema={
                'sections': [{'key': 'applicant', 'label': 'Applicant'}],
                'fields': [{'key': 'applicant_name', 'type': 'text', 'required': True, 'section_key': 'applicant'}],
            },
            signer_rules=[],
        )
        revision = OriginationTemplateConfigurationRevision.objects.create(
            template=template, revision=1, configuration={}, is_published=True,
            created_by=self.actor,
        )
        template.published_configuration_revision = revision
        template.save(update_fields=['published_configuration_revision'])

        response = self.client.post(reverse(
            'admin:core_originationproductdefinition_packet_add_shared', args=[self.product.pk],
        ), {'template_id': template.pk})

        self.assertEqual(response.status_code, 200)
        assignment = self.product.document_assignments.get()
        self.assertEqual(assignment.document_key, 'primary')
        self.assertEqual(assignment.display_order, 0)
        self.assertEqual(assignment.version_policy, assignment.VERSION_PINNED)
        self.product.refresh_from_db()
        self.assertEqual(self.product.document_template_sha256, template.source_sha256)
        self.assertIn('applicant_name', {item['key'] for item in self.product.form_schema['fields']})

    def test_ajax_publish_returns_the_real_validation_error_instead_of_hiding_it(self):
        from core.services.origination_templates import OriginationTemplateError

        template = OriginationDocumentTemplate.objects.create(
            product_definition=None, document_key='primary', document_role='primary',
            inclusion_mode='required', display_order=0, document_type='publish_error_primary',
            name='Publish error primary', version=1, status='active',
            source_filename='publish-error.pdf', source_sha256='8' * 64,
            source_byte_size=100, page_count=1, placement_config={}, created_by=self.actor,
            form_schema=self.product.form_schema, signer_rules=self.product.signer_rules,
        )
        revision = OriginationTemplateConfigurationRevision.objects.create(
            template=template, revision=1, configuration={}, is_published=True,
            created_by=self.actor,
        )
        template.published_configuration_revision = revision
        template.save(update_fields=['published_configuration_revision'])
        OriginationProductDocumentAssignment.objects.create(
            product_definition=self.product, template=template,
            version_policy=OriginationProductDocumentAssignment.VERSION_PINNED,
            document_key='primary', name=template.name, inclusion_mode='required',
            display_order=0, created_by=self.actor,
        )
        url = reverse(
            'admin:core_originationproductdefinition_publish_assigned_primary',
            args=[self.product.pk],
        )

        with patch(
            'core.services.origination_templates.publish_product_template',
            side_effect=OriginationTemplateError('Required field loan_amount is not calibrated.'),
        ):
            response = self.client.post(
                url, {'request_id': 'publish-validation-error'},
                HTTP_X_REQUESTED_WITH='XMLHttpRequest',
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {'ok': False, 'error': 'Required field loan_amount is not calibrated.'},
        )
        self.product.refresh_from_db()
        self.assertFalse(self.product.is_active)
        self.assertEqual(self.product.lifecycle_status, self.product.STATUS_DRAFT)

    def test_ajax_publish_confirms_active_state_and_redirects_to_product_list(self):
        template = OriginationDocumentTemplate.objects.create(
            product_definition=None, document_key='primary', document_role='primary',
            inclusion_mode='required', display_order=0, document_type='publish_success_primary',
            name='Publish success primary', version=1, status='active',
            source_filename='publish-success.pdf', source_sha256='7' * 64,
            source_byte_size=100, page_count=1, placement_config={}, created_by=self.actor,
            form_schema=self.product.form_schema, signer_rules=self.product.signer_rules,
        )
        revision = OriginationTemplateConfigurationRevision.objects.create(
            template=template, revision=1, configuration={}, is_published=True,
            created_by=self.actor,
        )
        template.published_configuration_revision = revision
        template.save(update_fields=['published_configuration_revision'])
        OriginationProductDocumentAssignment.objects.create(
            product_definition=self.product, template=template,
            version_policy=OriginationProductDocumentAssignment.VERSION_PINNED,
            document_key='primary', name=template.name, inclusion_mode='required',
            display_order=0, created_by=self.actor,
        )
        url = reverse(
            'admin:core_originationproductdefinition_publish_assigned_primary',
            args=[self.product.pk],
        )

        def publish_success(**_kwargs):
            self.product.is_active = True
            self.product.lifecycle_status = self.product.STATUS_PUBLISHED
            self.product.save(update_fields=['is_active', 'lifecycle_status', 'updated_at'])
            return self.product, template, revision

        with patch(
            'core.services.origination_templates.publish_product_template',
            side_effect=publish_success,
        ):
            response = self.client.post(
                url, {'request_id': 'publish-success'},
                HTTP_X_REQUESTED_WITH='XMLHttpRequest',
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['ok'])
        self.assertTrue(payload['is_active'])
        self.assertEqual(payload['lifecycle_status'], self.product.STATUS_PUBLISHED)
        self.assertEqual(
            payload['redirect_url'],
            reverse('admin:core_originationproductdefinition_changelist'),
        )

    def test_product_can_be_created_from_published_reusable_primary_without_upload(self):
        template = OriginationDocumentTemplate.objects.create(
            product_definition=None, document_key='primary', document_role='primary',
            inclusion_mode='required', display_order=0, document_type='library_primary',
            name='Library primary', version=1, status='active',
            source_filename='library.pdf', source_sha256='9' * 64,
            source_byte_size=100, page_count=1, placement_config={}, created_by=self.actor,
            form_schema={
                'sections': [{'key': 'application', 'label': 'Application'}],
                'fields': [{
                    'key': 'application_note', 'type': 'text', 'required': True,
                    'section_key': 'application',
                }],
            },
            signer_rules=[],
        )
        revision = OriginationTemplateConfigurationRevision.objects.create(
            template=template, revision=1, configuration={}, is_published=True,
            created_by=self.actor,
        )
        template.published_configuration_revision = revision
        template.save(update_fields=['published_configuration_revision'])

        response = self.client.post(reverse('admin:core_originationproductdefinition_add'), {
            'product_version': '',
            'product_key': 'library-created-product',
            'name': 'Library-created product',
            'main_laf_source': 'library',
            'reusable_primary_template': str(template.pk),
            'laf_pdf': '',
            'form_schema': json.dumps({'sections': [], 'fields': []}),
            'signer_rules': '[{"role":"borrower"}]',
            '_save': 'Save',
        })

        self.assertEqual(response.status_code, 302)
        product = OriginationProductDefinition.objects.get(product_key='library-created-product')
        assignment = product.document_assignments.get(document_key='primary')
        self.assertEqual(assignment.template, template)
        self.assertEqual(assignment.version_policy, assignment.VERSION_PINNED)
        self.assertFalse(product.document_templates.exists())
        self.assertIn('application_note', {item['key'] for item in product.form_schema['fields']})

    def test_configure_later_draft_is_saved_and_flagged_as_missing_main_laf(self):
        response = self.client.post(reverse('admin:core_originationproductdefinition_add'), {
            'product_version': '',
            'product_key': 'configure-later-product',
            'name': 'Configure later product',
            'main_laf_source': 'later',
            'reusable_primary_template': '',
            'laf_pdf': '',
            'form_schema': json.dumps({
                'sections': [{'key': 'application', 'label': 'Application'}],
                'fields': [{
                    'key': 'application_note', 'type': 'text', 'required': True,
                    'section_key': 'application',
                }],
            }),
            'signer_rules': '[{"role":"borrower"}]',
            '_save': 'Save',
        })

        self.assertEqual(response.status_code, 302)
        product = OriginationProductDefinition.objects.get(product_key='configure-later-product')
        model_admin = admin.site._registry[OriginationProductDefinition]
        self.assertEqual(model_admin.template_readiness(product), 'Main LAF missing')

    def test_pinned_primary_upgrade_is_explicit_and_audited(self):
        baseline = OriginationDocumentTemplate.objects.create(
            product_definition=None, document_key='primary', document_role='primary',
            inclusion_mode='required', display_order=0, document_type='upgrade_primary',
            name='Upgrade primary', version=1, status='retired',
            source_filename='v1.pdf', source_sha256='a' * 64,
            source_byte_size=100, page_count=1, placement_config={}, created_by=self.actor,
            form_schema={'fields': [{'key': 'consent', 'type': 'boolean', 'required': True}]},
            signer_rules=[],
        )
        baseline_revision = OriginationTemplateConfigurationRevision.objects.create(
            template=baseline, revision=1, configuration={}, is_published=True,
            created_by=self.actor,
        )
        baseline.published_configuration_revision = baseline_revision
        baseline.save(update_fields=['published_configuration_revision'])
        successor = OriginationDocumentTemplate.objects.create(
            product_definition=None, document_key='primary', document_role='primary',
            inclusion_mode='required', display_order=0, document_type='upgrade_primary',
            name='Upgrade primary', version=2, status='active',
            source_filename='v2.pdf', source_sha256='b' * 64,
            source_byte_size=100, page_count=1, placement_config={}, created_by=self.actor,
            form_schema={'fields': [{'key': 'consent', 'type': 'boolean', 'required': True}]},
            signer_rules=[],
        )
        successor_revision = OriginationTemplateConfigurationRevision.objects.create(
            template=successor, revision=1, configuration={}, is_published=True,
            created_by=self.actor,
        )
        successor.published_configuration_revision = successor_revision
        successor.save(update_fields=['published_configuration_revision'])
        assignment = OriginationProductDocumentAssignment.objects.create(
            product_definition=self.product, template=baseline,
            version_policy=OriginationProductDocumentAssignment.VERSION_PINNED,
            document_key='primary', name='Upgrade primary', inclusion_mode='required',
            display_order=0, created_by=self.actor,
        )

        response = self.client.post(reverse(
            'admin:core_originationproductdefinition_packet_upgrade_primary',
            args=[self.product.pk, assignment.pk],
        ))

        self.assertEqual(response.status_code, 200)
        assignment.refresh_from_db()
        self.assertEqual(assignment.template, successor)
        self.assertTrue(self.product.events.filter(action='shared_primary_upgraded').exists())
