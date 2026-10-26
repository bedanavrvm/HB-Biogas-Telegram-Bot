"""Unsigned catalogue applications complete without inventing loan approval."""
from copy import deepcopy
import json

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from core.models import ComplianceAuditChainState, OperationalLocation, Product, ProductAvailability, ProductVersion
from origination.models import (OriginationDocumentTemplate, OriginationDocumentProductEligibility, OriginationProductDefinition,
    OriginationTemplateConfigurationRevision)
from origination.services.application_completion import without_signing
from origination.services.loan_origination import (OriginationError, OriginationConflict, create_application,
    serialize_application, submit_for_review, confirm_and_start_conditional_signing, save_application_fields)
from origination.services.origination_document_catalogue import catalogue_for_product
from origination.services.origination_setup_documents import pending_changes, selected_documents
from origination.views import portal_origination_submit


class UnsignedApplicationTests(TestCase):
    def setUp(self):
        ComplianceAuditChainState.objects.get_or_create(singleton=1)
        self.actor = get_user_model().objects.create_superuser('synthetic-unsigned-officer', '', 'test-only')
        self.branch = OperationalLocation.objects.create(location_type='branch', name='Training', code='UNSIGNED-TRAINING')
        self.product = Product.objects.create(name='Training Loan', code='unsigned_training')
        self.version = ProductVersion.objects.create(product=self.product, version=1,
            min_amount='1000', max_amount='500000', min_tenor=1, max_tenor=24)
        ProductVersion.objects.filter(pk=self.version.pk).update(status='published', published_at=timezone.now())
        self.version.refresh_from_db()
        ProductAvailability.objects.create(product=self.product, branch=self.branch,
            workflow='loan_origination', channel='portal')
        self.schema = {'fields': [{'key': 'applicant_full_name', 'label': 'Applicant name', 'type': 'text', 'required': True}]}
        self.definition = OriginationProductDefinition.objects.create(product_key=self.product.code,
            product_version=self.version, name=self.product.name, form_schema=self.schema,
            signer_rules=[{'role': 'customer', 'required': True}, {'role': 'officer', 'required': True}],
            signing_policy='all_required', lifecycle_status='published', is_active=True)
        self.template = self.document('training_laf', version=6)

    def document(self, key, *, version=1, role='primary', signers=None):
        document = OriginationDocumentTemplate.objects.create(document_type=key, document_key=key,
            document_role=role, name='Training LAF' if role == 'primary' else 'Guarantee', version=version,
            status='active', page_count=1, source_byte_size=100, source_sha256='a' * 64, drive_file_id='synthetic-pdf',
            form_schema=self.schema, signer_rules=signers or [], created_by=self.actor)
        from origination.tests_form_projection import layout
        config = OriginationTemplateConfigurationRevision.objects.create(template=document, revision=1,
            configuration=layout('applicant_full_name'), is_published=True, published_at=timezone.now(), created_by=self.actor)
        OriginationDocumentTemplate.objects.filter(pk=document.pk).update(published_configuration_revision=config)
        OriginationDocumentProductEligibility.objects.create(template=document, product=self.product)
        document.refresh_from_db()
        return document

    def create(self, *, support=None, key='unsigned-create'):
        catalogue = catalogue_for_product(self.definition)
        return create_application(product_key=self.definition.product_key, officer=self.actor, branch=self.branch.name,
            client_request_id=key, primary_template_id=self.template.pk, supporting_template_ids=support or [],
            expected_catalogue_revision=catalogue['catalogue_revision'])[0]

    def ready(self):
        application = self.create()
        application.form_payload = {'applicant_full_name': 'Synthetic Applicant', 'loan_amount': '5000', 'repayment_tenor': '3'}
        application.primary_previewed_revision = application.revision
        application.save(update_fields=['form_payload', 'primary_previewed_revision'])
        return application

    def test_published_v6_is_available_without_old_product_signer_mirrors(self):
        catalogue = catalogue_for_product(self.definition)
        self.assertTrue(catalogue['ready'], catalogue['reasons'])
        self.assertEqual([row['version'] for row in catalogue['main_lafs']], [6])
        application = self.create()
        self.assertTrue(without_signing(application))
        self.assertEqual(application.signer_rules_snapshot, [])
        self.assertEqual(application.packet_documents.get(document_role='primary').signer_rules_snapshot, [])
        self.assertEqual(application.packet_documents.get(document_role='primary').template_id, self.template.pk)
        self.assertFalse(application.signing_participants.exists())
        self.assertIsNone(serialize_application(application, actor=self.actor).get('signing_workspace'))

    def test_empty_product_signer_mirror_also_allows_document_owned_creation(self):
        self.definition.signer_rules = []
        self.definition.save(update_fields=['signer_rules'])
        self.assertTrue(without_signing(self.create()))

    def test_document_owned_signers_inherit_identity_mappings_only(self):
        from origination.services.origination_documents import _primary_signer_rules
        rules = _primary_signer_rules([{'role': 'customer'}], [{'role': 'customer', 'required': True,
            'slots': [{'key': 'retired_signature'}], 'identity_fields': {'name': 'applicant_full_name'}}], document_owned=True)
        self.assertNotIn('required', rules[0])
        self.assertNotIn('slots', rules[0])
        self.assertEqual(rules[0]['identity_fields'], {'name': 'applicant_full_name'})

    def test_product_can_publish_with_a_published_unsigned_main(self):
        from origination.services.origination_setup import publish_product_profile
        self.definition.lifecycle_status = 'draft'
        self.definition.is_active = False
        self.definition.signer_rules = []
        self.definition.save(update_fields=['lifecycle_status', 'is_active', 'signer_rules'])
        published = publish_product_profile(definition=self.definition, actor=self.actor)
        self.assertEqual(published.lifecycle_status, 'published')
        self.assertTrue(catalogue_for_product(published)['ready'])

    def test_completion_is_idempotent_locked_and_not_approval(self):
        application = self.ready()
        result = submit_for_review(application_id=application.pk, actor=self.actor, expected_revision=1, request_id='complete')
        self.assertEqual(result.status, 'completed')
        self.assertEqual(result.revision, 2)
        self.assertIsNotNone(result.submitted_at)
        self.assertIsNone(result.reviewed_at)
        self.assertIsNone(result.final_reviewed_at)
        self.assertFalse(result.signing_packages.exists())
        self.assertEqual(result.events.filter(action='application_completed').count(), 1)
        self.assertFalse(result.packet_documents.filter(selected=True, completed_at__isnull=True).exists())
        replay = submit_for_review(application_id=application.pk, actor=self.actor, expected_revision=1, request_id='complete')
        self.assertEqual(replay.revision, 2)
        with self.assertRaises(OriginationError):
            save_application_fields(application_id=application.pk, actor=self.actor, expected_revision=2,
                       request_id='edit-completed', payload={'applicant_full_name': 'Changed'})
        from origination.services.origination_queues import STATUS_GROUPS
        self.assertIn('completed', STATUS_GROUPS['completed'][1])

    def test_normal_draft_save_preserves_unsigned_completion(self):
        application = self.create()
        saved = save_application_fields(application_id=application.pk, actor=self.actor, expected_revision=1,
            request_id='actual-save', payload={'applicant_full_name': 'Synthetic Applicant',
                                            'loan_amount': '5000', 'repayment_tenor': '3'})
        self.assertTrue(without_signing(saved))
        self.assertEqual(saved.schema_snapshot['document_completion_version'], 1)
        saved.primary_previewed_revision = saved.revision
        saved.save(update_fields=['primary_previewed_revision'])
        completed = submit_for_review(application_id=saved.pk, actor=self.actor,
            expected_revision=saved.revision, request_id='saved-complete')
        self.assertEqual(completed.status, 'completed')

    def test_seed_identity_flag_does_not_require_removed_identity_fields(self):
        self.template.form_schema = {**self.template.form_schema, 'identity_contract': 'applicant_v1'}
        self.template.save(update_fields=['form_schema'])
        application = self.ready()
        completed = submit_for_review(application_id=application.pk, actor=self.actor,
            expected_revision=application.revision, request_id='removed-identity-fields')
        self.assertEqual(completed.status, 'completed')
        self.assertNotIn('national_id', completed.form_payload)

    def test_submission_api_chooses_completion_even_with_old_approval_settings(self):
        application = self.ready()
        application.approval_roles_snapshot = ['branch_manager']
        application.save(update_fields=['approval_roles_snapshot'])
        request = RequestFactory().post('/', json.dumps({'revision': 1, 'client_request_id': 'api-complete'}), content_type='application/json')
        request.origination_user = self.actor
        response = portal_origination_submit(request, str(application.pk))
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(json.loads(response.content)['application']['status'], 'completed')

    def test_viewing_completed_application_does_not_move_its_document_dates(self):
        from origination.services.origination_documents import mark_document_previewed, mark_packet_previewed
        application = self.ready()
        completed = submit_for_review(application_id=application.pk, actor=self.actor, expected_revision=1, request_id='done')
        before = list(completed.packet_documents.values('completed_at', 'previewed_application_revision', 'updated_at'))
        mark_document_previewed(completed, 'primary')
        mark_packet_previewed(completed)
        self.assertEqual(list(completed.packet_documents.values('completed_at', 'previewed_application_revision', 'updated_at')), before)

    def test_required_fields_preview_revision_owner_and_evidence_are_not_bypassed(self):
        application = self.create()
        with self.assertRaises(OriginationError):
            submit_for_review(application_id=application.pk, actor=self.actor, expected_revision=1, request_id='empty')
        application.form_payload = {'applicant_full_name': 'Synthetic Applicant'}
        application.save(update_fields=['form_payload'])
        with self.assertRaises(OriginationError):
            submit_for_review(application_id=application.pk, actor=self.actor, expected_revision=1, request_id='unpreviewed')
        application.primary_previewed_revision = 1
        application.product_terms_snapshot = {'requirements': [{'key': 'proof', 'label': 'Proof', 'required': True,
            'workflow': 'loan_origination', 'enforcement_stage': 'review', 'type': 'text'}]}
        application.save(update_fields=['primary_previewed_revision', 'product_terms_snapshot'])
        with self.assertRaises(OriginationError):
            submit_for_review(application_id=application.pk, actor=self.actor, expected_revision=1, request_id='evidence')
        other = get_user_model().objects.create_superuser('synthetic-other-officer', '', 'test-only')
        with self.assertRaises(OriginationError):
            submit_for_review(application_id=application.pk, actor=other, expected_revision=1, request_id='other')
        with self.assertRaises(OriginationConflict):
            submit_for_review(application_id=application.pk, actor=self.actor, expected_revision=2, request_id='stale')
        application.refresh_from_db()
        self.assertEqual(application.status, 'draft')

    def test_supporting_required_signatures_are_retained_and_selection_is_rechecked(self):
        support = self.document('training_guarantee', role='supporting', signers=[
            {'role': 'customer', 'required': True, 'slots': [{'key': 'customer_sign', 'required': True}]},
            {'role': 'officer', 'required': True, 'slots': [{'key': 'officer_sign', 'required': True}]},
        ])
        application = self.create(support=[support.pk])
        self.assertFalse(without_signing(application))
        self.assertTrue(application.signing_participants.exists())
        # A document with mandatory signatures cannot take the unsigned path.
        application.packet_documents.filter(document_key=support.document_key).update(selected=False)
        self.assertTrue(without_signing(application))
        application.packet_documents.filter(document_key=support.document_key).update(selected=True)
        self.assertFalse(without_signing(application))

    def test_historical_applications_do_not_adopt_the_new_completion_policy(self):
        application = self.ready()
        schema = deepcopy(application.schema_snapshot)
        schema.pop('document_completion_version')
        application.schema_snapshot = schema
        application.signing_policy_snapshot = 'legacy'
        application.save(update_fields=['schema_snapshot', 'signing_policy_snapshot'])
        self.assertFalse(without_signing(application))
        submitted = submit_for_review(application_id=application.pk, actor=self.actor, expected_revision=1, request_id='historical')
        self.assertEqual(submitted.status, 'ready_for_review')

    def test_unsigned_application_cannot_be_accidentally_sent_to_signing(self):
        application = self.ready()
        with self.assertRaisesMessage(OriginationError, 'No signatures are required'):
            confirm_and_start_conditional_signing(application_id=application.pk, actor=self.actor,
                expected_revision=1, request_id='wrong-action')
        self.assertFalse(application.signing_packages.exists())

    def test_independently_published_replacement_clears_only_resolved_maintenance(self):
        source = self.template
        OriginationDocumentTemplate.objects.filter(pk=source.pk).update(status='retired')
        successor = self.document(source.document_type, version=7)
        pending_support = self.document('pending_support', role='supporting')
        changes = [{'action': 'edit', 'source': str(source.pk), 'target': str(successor.pk)},
                   {'action': 'remove', 'source': str(pending_support.pk), 'target': ''}]
        self.definition.events.create(action='maintenance_staged', actor=self.actor, metadata={'changes': changes})
        self.assertEqual(pending_changes(self.definition), [changes[1]])
        self.assertIn(successor, selected_documents(self.definition))
        self.assertEqual(self.definition.events.get(action='maintenance_staged').metadata['changes'], changes)
        self.assertIn(str(successor.pk), [row['id'] for row in catalogue_for_product(self.definition)['main_lafs']])

    def test_unpublished_or_unconnected_replacement_stays_pending(self):
        successor = self.document('draft_replacement', version=7)
        OriginationDocumentTemplate.objects.filter(pk=successor.pk).update(status='ready')
        changes = [{'action': 'edit', 'source': str(self.template.pk), 'target': str(successor.pk)}]
        self.definition.events.create(action='maintenance_staged', actor=self.actor, metadata={'changes': changes})
        self.assertEqual(pending_changes(self.definition), changes)
