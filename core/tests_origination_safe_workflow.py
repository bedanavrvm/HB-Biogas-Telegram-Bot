import json
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from core.models import (
    LoanOriginationApplication,
    OriginationApplicationDocument,
    OriginationApplicationEvent,
    OriginationCorrectionRequest,
    OriginationProductDefinition,
    OriginationRequirementEvidence,
    OriginationSigningPackage,
)
from core.services.loan_origination import (
    OriginationError,
    _package_review_scope_hash,
    _missing_application_requirements,
    prepare_review_package,
    review_application,
    save_application_fields,
    save_signing_requirements,
    submit_for_review,
    validate_form_payload,
)
from core.services.origination_access import (
    DENIED,
    FULL,
    MASKED,
    application_presentation_mode,
    scope_application_queryset,
)
from core.services.origination_evidence import (
    remove_requirement_evidence,
    upload_requirement_evidence,
    validate_evidence_file,
)


class OriginationSafeWorkflowTests(TestCase):
    @staticmethod
    def _pdf_upload(name='identity.pdf'):
        from pypdf import PdfWriter

        stream = BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=200, height=200)
        writer.write(stream)
        return SimpleUploadedFile(name, stream.getvalue(), content_type='application/pdf')

    def setUp(self):
        users = get_user_model()
        self.officer = users.objects.create_user(username='safe-field-officer')
        self.other_officer = users.objects.create_user(username='other-field-officer')
        self.reviewer = users.objects.create_user(username='safe-reviewer')
        self.definition = OriginationProductDefinition.objects.create(
            product_key='safe-workflow-product',
            name='Safe Workflow Product',
            version=1,
            form_schema={
                'sections': [{'key': 'applicant', 'label': 'Applicant'}],
                'fields': [
                    {
                        'key': 'applicant_name', 'label': 'Applicant name',
                        'type': 'text', 'section_key': 'applicant', 'required': True,
                        'validation': {'min_length': '3', 'max_length': '40'},
                        'masking_policy': 'partial',
                    },
                    {
                        'key': 'loan_amount', 'label': 'Loan amount',
                        'type': 'money', 'section_key': 'applicant', 'required': True,
                        'validation': {'min': '1000', 'max': '5000'},
                        'masking_policy': 'full',
                    },
                ],
            },
            signer_rules=[{'role': 'borrower'}],
            document_type='safe-workflow-agreement',
            document_template_name='Safe Workflow.pdf',
            document_template_sha256='b' * 64,
            is_active=True,
        )
        terms = {
            'requirements': [{
                'key': 'national_id_copy', 'label': 'National ID copy',
                'type': 'document', 'workflow': 'loan_origination',
                'enforcement_stage': 'review', 'required': True,
            }],
        }
        self.application = LoanOriginationApplication.objects.create(
            reference_number='ORG-SAFE-001', product_definition=self.definition,
            officer=self.officer, branch='Embu', schema_snapshot=self.definition.form_schema,
            signer_rules_snapshot=self.definition.signer_rules,
            product_terms_snapshot=terms,
        )
        self.other_application = LoanOriginationApplication.objects.create(
            reference_number='ORG-SAFE-002', product_definition=self.definition,
            officer=self.other_officer, branch='Embu', schema_snapshot=self.definition.form_schema,
            signer_rules_snapshot=self.definition.signer_rules,
            product_terms_snapshot=terms,
        )
        self.outside_application = LoanOriginationApplication.objects.create(
            reference_number='ORG-SAFE-003', product_definition=self.definition,
            officer=self.other_officer, branch='Nakuru', schema_snapshot=self.definition.form_schema,
            signer_rules_snapshot=self.definition.signer_rules,
            product_terms_snapshot=terms,
        )
        self.audit_patch = patch('core.services.compliance_audit.record_event')
        self.audit_patch.start()
        self.addCleanup(self.audit_patch.stop)

    def _freeze_for_review(self, application, *, reviewer=None, request_id='safe-review-preview'):
        package = OriginationSigningPackage.objects.create(
            application=application, application_revision=application.revision,
            external_reference=f'SAFE-REVIEW-{application.revision}-{str(application.pk)[:8]}',
            document_type=application.product_definition.document_type,
            template_version=application.product_definition.document_template_version,
            template_sha256=application.product_definition.document_template_sha256,
            context_snapshot={'revision': application.revision}, participants_snapshot=[],
            requirement_evidence_snapshot=[], document_manifest_snapshot=[],
            template_configuration_snapshot={}, combined_document_hash='d' * 64,
            unsigned_document_hash='d' * 64, prepared_by=self.reviewer,
            prepared_at=timezone.now(),
        )
        package.review_scope_sha256 = _package_review_scope_hash(package)
        package.save(update_fields=['review_scope_sha256', 'updated_at'])
        if reviewer:
            OriginationApplicationEvent.objects.create(
                application=application, action='review_packet_previewed',
                revision=application.revision, actor=reviewer, request_id=request_id,
                after_values={
                    'package_id': str(package.pk),
                    'unsigned_document_hash': package.unsigned_document_hash,
                    'review_scope_sha256': package.review_scope_sha256,
                },
            )
        return package

    @staticmethod
    def _review_kwargs(package):
        return {
            'package_id': package.pk,
            'expected_unsigned_hash': package.unsigned_document_hash,
            'expected_review_scope_hash': package.review_scope_sha256,
        }

    @patch('core.services.origination_access.effective_capability_keys')
    def test_officer_sees_only_owned_applications_and_reviewer_gets_branch_queue(self, capabilities):
        from core.models import AccessGrant
        from core.services.telegram_identity import user_access

        AccessGrant.objects.create(
            user=self.officer, workflow='jawabu_portal', role='JBL_OFFICER', branch='EMBU',
        )
        access = user_access(self.officer, 'jawabu_portal')
        capabilities.return_value = {'portal.origination.view', 'portal.origination.create'}

        officer_scope = scope_application_queryset(
            LoanOriginationApplication.objects.all(), user=self.officer, access=access,
        )

        self.assertEqual(list(officer_scope.values_list('pk', flat=True)), [self.application.pk])
        self.assertEqual(
            application_presentation_mode(
                self.other_application, user=self.officer, access=access,
            ),
            DENIED,
        )

        capabilities.return_value = {'portal.origination.view', 'portal.origination.review'}
        AccessGrant.objects.create(
            user=self.reviewer, workflow='jawabu_portal', role='OPERATIONS_ADMIN', branch='EMBU',
        )
        reviewer_access = user_access(self.reviewer, 'jawabu_portal')
        reviewer_scope = scope_application_queryset(
            LoanOriginationApplication.objects.all(), user=self.reviewer,
            access=reviewer_access,
        )
        self.assertEqual(set(reviewer_scope.values_list('pk', flat=True)), {
            self.application.pk, self.other_application.pk,
        })
        self.assertEqual(
            application_presentation_mode(
                self.application, user=self.reviewer,
                access=reviewer_access,
            ),
            FULL,
        )

    def test_product_specific_validation_returns_field_keyed_errors(self):
        result = validate_form_payload(
            self.definition.form_schema,
            {'applicant_name': 'Al', 'loan_amount': '6000'},
            require_complete=True,
        )

        self.assertFalse(result.valid)
        self.assertEqual(set(result.errors), {'applicant_name', 'loan_amount'})

    @patch('core.services.origination_access.effective_capability_keys')
    def test_view_only_presentation_is_masked(self, capabilities):
        from core.models import AccessGrant, WorkflowRoleCapability
        from core.services.telegram_identity import user_access
        from core.services.loan_origination import serialize_application

        capabilities.return_value = {'portal.origination.view'}
        AccessGrant.objects.create(
            user=self.reviewer, workflow='jawabu_portal', role='OPERATIONS_ADMIN', branch='EMBU',
        )
        WorkflowRoleCapability.objects.filter(
            workflow='jawabu_portal', role='OPERATIONS_ADMIN',
            capability_key__in=['portal.origination.review', 'portal.origination.signing.start'],
        ).update(effect='deny', enabled=False)
        self.application.form_payload = {
            'applicant_name': 'Synthetic Applicant', 'loan_amount': '2500',
        }
        self.application.save(update_fields=['form_payload'])
        mode = application_presentation_mode(
            self.application, user=self.reviewer,
            access=user_access(self.reviewer, 'jawabu_portal'),
        )
        payload = serialize_application(self.application, presentation=mode)

        self.assertEqual(mode, MASKED)
        self.assertEqual(payload['form_payload']['applicant_name'], '••••cant')
        self.assertEqual(payload['form_payload']['loan_amount'], '••••')

    def test_application_queue_filters_and_counts_before_pagination(self):
        from core.api.origination_views import portal_origination_applications

        self.application.status = LoanOriginationApplication.STATUS_CORRECTION_REQUIRED
        self.application.save(update_fields=['status'])
        request = RequestFactory().get('/api/origination/api/applications/', {
            'queue': 'mine', 'page': '1', 'page_size': '1',
        })
        request.portal_user = self.officer
        request.portal_access = None

        response = portal_origination_applications(request)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload['pagination']['total'], 1)
        self.assertEqual(payload['counts']['correction_required'], 1)
        self.assertEqual(payload['applications'][0]['id'], str(self.application.pk))

    def test_application_queue_never_returns_more_than_ten_and_clamps_page(self):
        from core.api.origination_views import portal_origination_applications

        LoanOriginationApplication.objects.bulk_create([
            LoanOriginationApplication(
                reference_number=f'ORG-PAGE-{index:03d}',
                product_definition=self.definition, officer=self.officer, branch='Embu',
                schema_snapshot=self.definition.form_schema,
                signer_rules_snapshot=self.definition.signer_rules,
                product_terms_snapshot={},
            )
            for index in range(10)
        ])
        request = RequestFactory().get('/api/origination/api/applications/', {
            'queue': 'mine', 'page': '1', 'page_size': '25',
        })
        request.portal_user = self.officer
        request.portal_access = None

        first = json.loads(portal_origination_applications(request).content)

        self.assertEqual(first['pagination'], {
            'page': 1, 'page_size': 10, 'total': 11, 'pages': 2,
        })
        self.assertEqual(len(first['applications']), 10)

        request = RequestFactory().get('/api/origination/api/applications/', {
            'queue': 'mine', 'page': '99', 'page_size': '25',
        })
        request.portal_user = self.officer
        request.portal_access = None
        last = json.loads(portal_origination_applications(request).content)

        self.assertEqual(last['pagination']['page'], 2)
        self.assertEqual(len(last['applications']), 1)

    @patch('core.api.origination_views._capability_error', return_value=None)
    @patch('core.services.origination_access.effective_capability_keys')
    def test_application_detail_denies_another_officers_record(
        self, capabilities, _capability_error,
    ):
        from core.api.origination_views import portal_origination_application_detail

        capabilities.return_value = {'portal.origination.view', 'portal.origination.create'}
        request = RequestFactory().get('/api/origination/api/applications/other/')
        request.portal_user = self.officer
        request.portal_access = {'branches': ['Embu'], 'roles': ['JBL_OFFICER']}

        response = portal_origination_application_detail(request, str(self.other_application.pk))

        self.assertEqual(response.status_code, 403)

    @patch('core.api.origination_views._capability_error', return_value=None)
    def test_stale_draft_patch_returns_structured_revision_conflict(self, _capability_error):
        from core.api.origination_views import portal_origination_application_detail

        self.application.form_payload = {
            'applicant_name': 'Server Applicant', 'loan_amount': '2000',
        }
        self.application.revision = 2
        self.application.save(update_fields=['form_payload', 'revision'])
        request = RequestFactory().patch(
            f'/api/origination/api/applications/{self.application.pk}/',
            data=json.dumps({
                'revision': 1,
                'form_payload': {
                    'applicant_name': 'Phone Applicant', 'loan_amount': '2500',
                },
                'request_id': 'stale-phone-save',
            }),
            content_type='application/json',
            HTTP_IDEMPOTENCY_KEY='stale-phone-save',
        )
        request.portal_user = self.officer
        request.portal_access = None

        response = portal_origination_application_detail(
            request, str(self.application.pk),
        )
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 409)
        self.assertEqual(payload['code'], 'revision_conflict')
        self.assertTrue(payload['conflict'])
        self.assertEqual(payload['expected_revision'], 1)
        self.assertEqual(payload['current_revision'], 2)
        self.assertNotIn('application', payload)

    @patch('core.api.origination_views._capability_error', return_value=None)
    def test_invalid_draft_patch_identifies_field_without_logging_submitted_value(
        self, _capability_error,
    ):
        from core.api.origination_views import portal_origination_application_detail

        request = RequestFactory().patch(
            f'/api/origination/api/applications/{self.application.pk}/',
            data=json.dumps({
                'revision': self.application.revision,
                'form_payload': {
                    'applicant_name': 'Synthetic Applicant',
                    'loan_amount': 'private-invalid-value',
                },
                'request_id': 'invalid-draft-save',
            }),
            content_type='application/json',
            HTTP_IDEMPOTENCY_KEY='invalid-draft-save',
        )
        request.portal_user = self.officer
        request.portal_access = None

        with self.assertLogs('core.api.origination_views', level='WARNING') as captured:
            response = portal_origination_application_detail(
                request, str(self.application.pk),
            )
        payload = json.loads(response.content)
        log_output = '\n'.join(captured.output)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(payload['code'], 'invalid_application_fields')
        self.assertEqual(payload['errors'], {'loan_amount': 'Enter a valid amount.'})
        self.assertIn("error_fields=['loan_amount']", log_output)
        self.assertIn("error_messages=['Enter a valid amount.']", log_output)
        self.assertIn('request_id=invalid-draft-save', log_output)
        self.assertNotIn('private-invalid-value', log_output)

    def test_correction_targets_are_validated_and_closed_on_resubmission(self):
        self.application.form_payload = {'applicant_name': 'Applicant', 'loan_amount': '2000'}
        self.application.status = LoanOriginationApplication.STATUS_READY_FOR_REVIEW
        self.application.save(update_fields=['form_payload', 'status'])
        review_package = self._freeze_for_review(self.application, reviewer=self.reviewer)

        corrected = review_application(
            application_id=self.application.pk,
            actor=self.reviewer,
            expected_revision=self.application.revision,
            request_id='safe-correction-review',
            decision='request_correction',
            reason='Correct the applicant name and replace the ID copy.',
            correction_items=[
                {'target_type': 'field', 'target_key': 'applicant_name', 'instruction': 'Use the legal name.'},
                {'target_type': 'requirement', 'target_key': 'national_id_copy', 'instruction': 'Replace the unreadable ID copy.'},
            ],
            **self._review_kwargs(review_package),
        )

        correction = OriginationCorrectionRequest.objects.get(application=self.application)
        self.assertEqual(correction.items.count(), 2)
        self.assertEqual(corrected.status, LoanOriginationApplication.STATUS_CORRECTION_REQUIRED)
        corrected = save_application_fields(
            application_id=corrected.pk, actor=self.officer,
            payload={'applicant_name': 'Legal Applicant', 'loan_amount': '2000'},
            expected_revision=corrected.revision, request_id='safe-correction-save',
        )
        OriginationApplicationEvent.objects.create(
            application=corrected, action='document_previewed', revision=corrected.revision,
            actor=self.officer, request_id='safe-correction-preview',
        )
        # This test focuses correction closure; make the review-stage document
        # requirement non-blocking without inventing a fake successful upload.
        corrected.product_terms_snapshot['requirements'][0]['enforcement_stage'] = 'signing'
        corrected.save(update_fields=['product_terms_snapshot'])
        submitted = submit_for_review(
            application_id=corrected.pk, actor=self.officer,
            expected_revision=corrected.revision, request_id='safe-correction-submit',
        )
        correction.refresh_from_db()
        self.assertEqual(submitted.status, LoanOriginationApplication.STATUS_READY_FOR_REVIEW)
        self.assertEqual(correction.status, OriginationCorrectionRequest.STATUS_ADDRESSED)
        self.assertEqual(correction.addressed_by, self.officer)

    def test_unknown_correction_target_is_rejected(self):
        self.application.status = LoanOriginationApplication.STATUS_READY_FOR_REVIEW
        self.application.save(update_fields=['status'])
        review_package = self._freeze_for_review(self.application, reviewer=self.reviewer)
        with self.assertRaisesMessage(OriginationError, 'not part of this application'):
            review_application(
                application_id=self.application.pk, actor=self.reviewer,
                expected_revision=self.application.revision,
                request_id='unknown-correction-target', decision='request_correction',
                reason='Fix an unknown field.',
                correction_items=[{
                    'target_type': 'field', 'target_key': 'not_real',
                    'instruction': 'Correct this value.',
                }],
                **self._review_kwargs(review_package),
            )

    def test_signing_staff_can_save_only_snapshotted_signing_requirements(self):
        self.application.product_terms_snapshot['requirements'].append({
            'key': 'disbursement_reference', 'label': 'Disbursement reference',
            'type': 'text', 'workflow': 'loan_origination',
            'enforcement_stage': 'signing', 'required': True,
        })
        self.application.status = LoanOriginationApplication.STATUS_REVIEWED
        self.application.save(update_fields=['product_terms_snapshot', 'status'])

        with self.assertRaisesMessage(OriginationError, 'Complete signing requirements'):
            save_signing_requirements(
                application_id=self.application.pk, actor=self.reviewer,
                requirement_evidence={}, expected_revision=self.application.revision,
                request_id='missing-signing-requirements',
            )

        saved = save_signing_requirements(
            application_id=self.application.pk, actor=self.reviewer,
            requirement_evidence={'disbursement_reference': 'SYNTHETIC-REF'},
            expected_revision=self.application.revision,
            request_id='safe-signing-requirements',
        )

        self.assertEqual(saved.product_requirement_evidence['disbursement_reference'], 'SYNTHETIC-REF')
        self.assertEqual(saved.status, LoanOriginationApplication.STATUS_REVIEWED)
        self.assertTrue(saved.events.filter(action='signing_requirements_saved').exists())

    def test_document_text_reference_cannot_satisfy_file_requirement(self):
        self.application.product_requirement_evidence = {'national_id_copy': 'ID-REF-ONLY'}
        self.application.save(update_fields=['product_requirement_evidence'])

        missing = _missing_application_requirements(self.application, stage='review')

        self.assertEqual([item['key'] for item in missing], ['national_id_copy'])

    def test_file_validation_rejects_extension_content_mismatch(self):
        fake_pdf = SimpleUploadedFile('identity.pdf', b'not-a-pdf', content_type='application/pdf')
        with self.assertRaisesMessage(OriginationError, 'genuine PDF'):
            validate_evidence_file(fake_pdf)

    @override_settings(
        GOOGLE_DRIVE_MEDIA_FOLDER_ID='synthetic-drive-root',
        ORIGINATION_EVIDENCE_MAX_FILE_SIZE_MB=2,
        ORIGINATION_EVIDENCE_MAX_FILES_PER_REQUIREMENT=2,
        ORIGINATION_EVIDENCE_MAX_TOTAL_UPLOAD_MB=4,
    )
    @patch(
        'core.services.order_approval.GoogleDriveMediaStorage.upload',
        return_value=('drive-file-1', 'https://drive.example.test/file-1'),
    )
    def test_evidence_upload_is_hashed_idempotent_and_logically_removed(self, upload):
        uploaded = self._pdf_upload()
        item, replayed = upload_requirement_evidence(
            application_id=self.application.pk, actor=self.officer,
            requirement_key='national_id_copy', expected_revision=1,
            request_id='safe-evidence-upload', file_obj=uploaded,
        )
        self.application.refresh_from_db()
        self.assertFalse(replayed)
        self.assertEqual(item.status, OriginationRequirementEvidence.STATUS_UPLOADED)
        self.assertEqual(len(item.content_sha256), 64)
        self.assertEqual(self.application.revision, 2)
        self.assertEqual(_missing_application_requirements(self.application, stage='review'), [])
        self.assertEqual(upload.call_count, 1)

        duplicate = self._pdf_upload()
        repeated, duplicate_replayed = upload_requirement_evidence(
            application_id=self.application.pk, actor=self.officer,
            requirement_key='national_id_copy', expected_revision=1,
            request_id='safe-evidence-duplicate', file_obj=duplicate,
        )
        self.assertTrue(duplicate_replayed)
        self.assertEqual(repeated.pk, item.pk)
        self.assertEqual(upload.call_count, 1)

        removed = remove_requirement_evidence(
            evidence_id=item.pk, actor=self.officer, expected_revision=2,
            request_id='safe-evidence-remove',
        )
        self.assertEqual(removed.status, OriginationRequirementEvidence.STATUS_REMOVED)
        self.assertTrue(_missing_application_requirements(self.application, stage='review'))

    @override_settings(
        GOOGLE_DRIVE_MEDIA_FOLDER_ID='synthetic-drive-root',
        ORIGINATION_EVIDENCE_MAX_FILE_SIZE_MB=2,
    )
    @patch(
        'core.services.order_approval.GoogleDriveMediaStorage.upload',
        return_value=('drive-file-signing', 'https://drive.example.test/signing'),
    )
    def test_signing_package_freezes_active_evidence_manifest(self, _upload):
        item, _replayed = upload_requirement_evidence(
            application_id=self.application.pk, actor=self.officer,
            requirement_key='national_id_copy', expected_revision=1,
            request_id='safe-evidence-for-signing', file_obj=self._pdf_upload(),
        )
        self.application.refresh_from_db()
        self.application.status = LoanOriginationApplication.STATUS_READY_FOR_REVIEW
        self.application.save(update_fields=['status'])
        OriginationApplicationDocument.objects.create(
            application=self.application, document_key='primary', name='Primary LAF',
            document_role='primary', inclusion_mode='required', selection_source='required',
            applicable=True, selected=True, template_snapshot={}, schema_snapshot={'fields': []},
        )

        with patch(
            'core.services.origination_documents.render_packet',
            return_value=(b'%PDF-safe-review', [{'key': 'primary', 'rendered_sha256': 'e' * 64}]),
        ):
            package, replayed = prepare_review_package(
                application_id=self.application.pk, actor=self.reviewer,
                expected_revision=self.application.revision,
                request_id='safe-prepare-review',
            )

        self.assertFalse(replayed)
        self.assertEqual(package.requirement_evidence_snapshot[0]['evidence_id'], str(item.pk))
        self.assertEqual(package.requirement_evidence_snapshot[0]['sha256'], item.content_sha256)
        self.assertNotIn('drive_file_id', package.requirement_evidence_snapshot[0])

        self.application.status = LoanOriginationApplication.STATUS_REVIEWED
        self.application.save(update_fields=['status'])
        with self.assertRaisesMessage(OriginationError, 'Recall the prepared packet'):
            upload_requirement_evidence(
                application_id=self.application.pk, actor=self.reviewer,
                requirement_key='national_id_copy', expected_revision=self.application.revision,
                request_id='safe-evidence-after-freeze', file_obj=self._pdf_upload(),
                allow_signing_actor=True,
            )
        with self.assertRaisesMessage(OriginationError, 'Recall the prepared packet'):
            remove_requirement_evidence(
                evidence_id=item.pk, actor=self.reviewer,
                expected_revision=self.application.revision,
                request_id='safe-evidence-remove-after-freeze', allow_signing_actor=True,
            )
