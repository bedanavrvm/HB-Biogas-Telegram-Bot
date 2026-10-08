import json
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import signing
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from origination.models import LoanOriginationApplication, OriginationDocumentTemplate, OriginationProductDefinition
from core.models import OperationalLocation, Product, ProductAvailability, ProductVersionEvent
from origination.services.origination_setup import (
    OriginationSetupConflict,
    assert_expected_state,
    make_return_token,
    resolve_return_token,
    setup_readiness,
    step_tokens,
)


class OriginationSetupWorkspaceTests(TestCase):
    def test_maintenance_retry_payload_and_discard_are_idempotent(self):
        from origination.services.origination_setup_documents import stage_change, cancel_changes
        definition, source = self._published_maintenance_product()
        kwargs = dict(definition=definition, source=source, actor=self.superuser, request_id='same-change', action='remove')
        stage_change(**kwargs)
        stage_change(**kwargs)
        self.assertEqual(definition.events.filter(action='maintenance_staged').count(), 1)
        rows = {row['key']:row for row in setup_readiness(definition)}
        self.assertEqual(rows['documents']['status'], 'stale')
        self.assertEqual(rows['publish']['status'], 'stale')
        with self.assertRaises(ValidationError):
            stage_change(**{**kwargs, 'action':'edit'})
        cancel_changes(definition=definition, actor=self.superuser, request_id='discard-once')
        cancel_changes(definition=definition, actor=self.superuser, request_id='discard-once')
        self.assertEqual(definition.events.filter(action='maintenance_applied').count(), 1)

    def test_inflight_upload_has_one_owner(self):
        from origination.services.origination_setup_documents import prepare_edit, _upload_reserved_document
        definition, source = self._published_maintenance_product()
        draft = prepare_edit(definition=definition, source=source, actor=self.superuser, request_id='upload-owner')
        OriginationDocumentTemplate.objects.filter(pk=draft.pk).update(drive_file_id='', status='upload_failed')
        draft.refresh_from_db()
        draft.events.create(action='setup_upload_started', actor=self.superuser, metadata={'attempt_id':'other-owner'})
        with patch('origination.services.origination_templates.upload_template_record') as upload:
            with self.assertRaisesMessage(ValidationError, 'already uploading'):
                _upload_reserved_document(draft, data=b'not-used', actor=self.superuser)
            upload.assert_not_called()

    def test_old_explicit_connection_cannot_restore_withdrawn_product(self):
        from origination.services.origination_setup_documents import prepare_edit, reconcile_shared_eligibility
        from origination.models import OriginationDocumentProductEligibility
        definition, source = self._published_maintenance_product()
        draft = prepare_edit(definition=definition, source=source, actor=self.superuser, request_id='withdraw-connection')
        other = Product.objects.create(code='withdrawn-added', name='Withdrawn added')
        OriginationDocumentProductEligibility.objects.create(template=draft, product=other)
        draft.events.create(action='setup_product_connected', actor=self.superuser, metadata={'product_id':str(other.pk)})
        source.events.create(action='product_withdrawn', actor=self.superuser, metadata={'product_id':str(other.pk)})
        reconcile_shared_eligibility(draft)
        self.assertFalse(draft.product_eligibilities.filter(product=other).exists())

    def test_field_label_requiredness_and_order_are_document_local(self):
        from origination.services.origination_setup_documents import prepare_edit
        from origination.services.origination_fields import edit_template_field, template_schema_revision
        from origination.models import OriginationDataField
        definition, source = self._published_maintenance_product()
        draft = prepare_edit(definition=definition, source=source, actor=self.superuser, request_id='field-edit')
        original = draft.form_schema['fields'][0]
        canonical = OriginationDataField.objects.get(key=original['key'])
        old_label = canonical.label
        draft = edit_template_field(template=draft, key=original['key'], action='update',
            presentation={'label':'Requested amount', 'required':False, 'width':'full'}, actor=self.superuser,
            expected_schema_revision=template_schema_revision(draft), request_id='label-edit')
        self.assertEqual(draft.form_schema['fields'][0]['label'], 'Requested amount')
        self.assertFalse(draft.form_schema['fields'][0]['required'])
        self.assertEqual(draft.form_schema['fields'][0]['type'], original['type'])
        canonical.refresh_from_db()
        self.assertEqual(canonical.label, old_label)
        draft = edit_template_field(template=draft, key=original['key'], action='move_down',
            presentation={}, actor=self.superuser, expected_schema_revision=template_schema_revision(draft))
        self.assertEqual(draft.form_schema['fields'][1]['key'], original['key'])
        source.refresh_from_db()
        self.assertEqual(source.form_schema['fields'][0]['label'], original['label'])

    def test_field_removal_removes_placements_and_blocks_missing_commercial_contract(self):
        from origination.services.origination_setup_documents import prepare_edit, document_readiness
        from origination.services.origination_fields import edit_template_field, template_schema_revision
        definition, source = self._published_maintenance_product()
        draft = prepare_edit(definition=definition, source=source, actor=self.superuser, request_id='field-remove')
        key = draft.form_schema['fields'][0]['key']
        revision = draft.configuration_revisions.first()
        draft = edit_template_field(template=draft, key=key, action='remove', presentation={}, actor=self.superuser,
            expected_schema_revision=template_schema_revision(draft), configuration=revision.configuration,
            expected_revision=revision.revision, request_id='remove-field')
        self.assertNotIn(key, [item['key'] for item in draft.form_schema['fields']])
        self.assertNotIn(key, draft.configuration_revisions.order_by('-revision').first().configuration['field_overlay_manifest']['fields'])
        self.assertTrue(document_readiness(definition)[1])
        self.assertIn(key, [item['key'] for item in source.form_schema['fields']])

    def test_field_edit_rejects_stale_revision_and_published_documents(self):
        from origination.services.origination_setup_documents import prepare_edit
        from origination.services.origination_fields import edit_template_field, OriginationFieldError
        definition, source = self._published_maintenance_product()
        draft = prepare_edit(definition=definition, source=source, actor=self.superuser, request_id='field-conflict')
        for template, revision in [(source, 0), (draft, -1)]:
            with self.assertRaises(OriginationFieldError):
                edit_template_field(template=template, key=draft.form_schema['fields'][0]['key'], action='update',
                    presentation={'label':'Changed'}, actor=self.superuser, expected_schema_revision=revision)

    def test_incompatible_shared_product_blocks_entire_upgrade(self):
        from origination.services.origination_setup_documents import prepare_edit, maintenance_impact, apply_changes
        from origination.models import OriginationDocumentProductEligibility
        from core.models import ProductVersion
        definition, source = self._published_maintenance_product()
        other = Product.objects.create(code='incompatible-shared', name='Incompatible shared')
        version = ProductVersion.objects.create(product=other, version=1, status='draft')
        ProductVersion.objects.filter(pk=version.pk).update(status='published')
        OriginationProductDefinition.objects.create(product_version=version, product_key=other.code,
            name=other.name, version=1, is_active=True, lifecycle_status='published',
            form_schema=definition.form_schema, signer_rules=[{'role':'branch_manager', 'required':True}])
        OriginationDocumentProductEligibility.objects.create(template=source, product=other)
        draft = prepare_edit(definition=definition, source=source, actor=self.superuser, request_id='incompatible-edit')
        with self.assertRaises(ValidationError):
            apply_changes(definition=definition, actor=self.superuser, request_id='apply-incompatible',
                          expected_impact=maintenance_impact(definition)['token'])
        source.refresh_from_db(); draft.refresh_from_db()
        self.assertEqual(source.status, 'active')
        self.assertEqual(draft.status, 'ready')
        self.assertFalse(definition.events.filter(action='maintenance_applied').exists())

    def _published_maintenance_product(self):
        definition = self._ready_guided_draft()
        self.assertEqual(self._publish_guided(definition).status_code, 302)
        definition.refresh_from_db()
        return definition, OriginationDocumentTemplate.objects.get(document_type='guided-ready-laf')

    def test_last_laf_removal_is_staged_confirmed_scoped_and_replay_safe(self):
        from origination.services.origination_setup_documents import stage_change, apply_changes, maintenance_impact
        from origination.services.origination_document_catalogue import catalogue_for_product
        from origination.models import OriginationDocumentProductEligibility
        definition, source = self._published_maintenance_product()
        other = Product.objects.create(code='other-maintenance', name='Other maintenance')
        OriginationDocumentProductEligibility.objects.create(template=source, product=other)
        stage_change(definition=definition, action='remove', source=source, actor=self.superuser, request_id='remove-laf')
        self.assertTrue(catalogue_for_product(definition)['ready'])
        impact = maintenance_impact(definition)
        self.assertTrue(impact['unavailable'])
        with self.assertRaises(ValidationError):
            apply_changes(definition=definition, actor=self.superuser, request_id='apply-laf', expected_impact=impact['token'])
        apply_changes(definition=definition, actor=self.superuser, request_id='apply-laf', expected_impact=impact['token'], allow_unavailable=True)
        apply_changes(definition=definition, actor=self.superuser, request_id='apply-laf', expected_impact='replay', allow_unavailable=True)
        self.assertFalse(catalogue_for_product(definition)['ready'])
        self.assertTrue(source.eligible_products.filter(pk=other.pk).exists())
        source.refresh_from_db()
        self.assertEqual(source.status, 'active')
        self.assertEqual(source.events.filter(action='product_withdrawn').count(), 1)

    def test_switch_replaces_choice_without_changing_terms(self):
        from origination.services.origination_setup_documents import stage_change, apply_changes, maintenance_impact
        from origination.services.origination_document_catalogue import catalogue_for_product
        definition, source = self._published_maintenance_product()
        replacement = self._ready_document(definition, family='another-approved-laf')
        terms_id = definition.product_version_id
        stage_change(definition=definition, action='replace', source=source, target=replacement,
                     actor=self.superuser, request_id='switch-laf')
        self.assertEqual(len(catalogue_for_product(definition)['main_lafs']), 2)
        apply_changes(definition=definition, actor=self.superuser, request_id='apply-switch', expected_impact=maintenance_impact(definition)['token'])
        self.assertEqual([item['id'] for item in catalogue_for_product(definition)['main_lafs']], [str(replacement.pk)])
        definition.refresh_from_db()
        self.assertEqual(definition.product_version_id, terms_id)

    def test_impact_changes_when_another_product_changes_shared_availability(self):
        from origination.services.origination_setup_documents import prepare_edit, maintenance_impact, apply_changes
        from origination.models import OriginationDocumentProductEligibility
        definition, source = self._published_maintenance_product()
        prepare_edit(definition=definition, source=source, actor=self.superuser, request_id='edit-shared')
        before = maintenance_impact(definition)['token']
        other = Product.objects.create(code='new-shared-product', name='New shared product')
        OriginationDocumentProductEligibility.objects.create(template=source, product=other)
        with self.assertRaises(OriginationSetupConflict):
            apply_changes(definition=definition, actor=self.superuser, request_id='apply-shared', expected_impact=before)

    def test_shared_draft_does_not_restore_a_withdrawn_product(self):
        from origination.services.origination_setup_documents import prepare_edit, reconcile_shared_eligibility
        from origination.models import OriginationDocumentProductEligibility
        definition, source = self._published_maintenance_product()
        other = Product.objects.create(code='withdrawn-shared', name='Withdrawn shared')
        OriginationDocumentProductEligibility.objects.create(template=source, product=other)
        successor = prepare_edit(definition=definition, source=source, actor=self.superuser, request_id='edit-withdrawn')
        source.product_eligibilities.filter(product=other).delete()
        reconcile_shared_eligibility(successor)
        self.assertFalse(successor.eligible_products.filter(pk=other.pk).exists())
        self.assertTrue(successor.eligible_products.filter(pk=definition.product_version.product_id).exists())

    def test_discard_restores_published_choices(self):
        from origination.services.origination_setup_documents import stage_change, cancel_changes, selected_documents, pending_changes
        definition, source = self._published_maintenance_product()
        stage_change(definition=definition, action='remove', source=source, actor=self.superuser, request_id='stage-discard')
        self.assertFalse(selected_documents(definition).exists())
        cancel_changes(definition=definition, actor=self.superuser, request_id='discard')
        self.assertEqual(selected_documents(definition).get().pk, source.pk)
        self.assertEqual(pending_changes(definition), [])

    def test_same_pdf_keeps_source_and_alignment(self):
        from origination.services.origination_setup_documents import replace_pdf
        from django.core.files.uploadedfile import SimpleUploadedFile
        from core.tests_origination_templates import synthetic_pdf
        definition, source = self._published_maintenance_product()
        result = replace_pdf(definition=definition, source=source, actor=self.superuser, request_id='same-pdf',
                             pdf_file=SimpleUploadedFile('same.pdf', synthetic_pdf()))
        self.assertEqual(result.pk, source.pk)
        self.assertEqual(OriginationDocumentTemplate.objects.count(), 1)

    def test_pdf_replacement_retains_fields_clears_alignment_and_retries_same_candidate(self):
        from origination.services.origination_setup_documents import replace_pdf
        from django.core.files.uploadedfile import SimpleUploadedFile
        from core.tests_origination_templates import synthetic_pdf
        definition, source = self._published_maintenance_product()
        replacement_bytes = synthetic_pdf() + b'\n% replacement source\n'
        with patch('origination.services.origination_templates._upload_template_bytes', side_effect=ValueError('synthetic upload failure')):
            failed = replace_pdf(definition=definition, source=source, actor=self.superuser, request_id='replace-source',
                                 pdf_file=SimpleUploadedFile('updated.pdf', replacement_bytes))
        self.assertEqual(failed.status, 'upload_failed')
        source.refresh_from_db()
        self.assertEqual(source.status, 'active')
        with patch('origination.services.origination_templates._upload_template_bytes', return_value=('synthetic-replacement', 'https://example.test/pdf')):
            result = replace_pdf(definition=definition, source=source, actor=self.superuser, request_id='replace-source',
                                 pdf_file=SimpleUploadedFile('updated.pdf', replacement_bytes))
        self.assertEqual(result.pk, failed.pk)
        self.assertEqual(result.form_schema, source.form_schema)
        self.assertIsNone(result.native_consent_policy_id)
        self.assertEqual(result.configuration_revisions.first().configuration['field_overlay_manifest']['fields'], {})
        self.assertEqual(result.configuration_revisions.first().configuration['signature_overlay_manifest']['slots'], {})
        self.assertNotEqual(result.source_sha256, source.source_sha256)

    def test_maintenance_view_removal_can_be_applied_without_financial_successor(self):
        from origination.services.origination_setup_documents import maintenance_impact
        definition, source = self._published_maintenance_product()
        response = self.client.post(self._documents_url(definition), {'action':'remove', 'source':str(source.pk),
            'request_id':'remove-view', 'expected_tokens':json.dumps(step_tokens(definition))})
        self.assertEqual(response.status_code, 302)
        review = self.client.get(response.url)
        self.assertContains(review, 'New applications will be unavailable')
        response = self.client.post(self._documents_url(definition), {'action':'enable_documents',
            'request_id':'apply-view', 'expected_tokens':json.dumps(step_tokens(definition)),
            'maintenance_token':maintenance_impact(definition)['token'], 'allow_unavailable':'yes'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(definition.product_version.product.versions.count(), 1)

    def _published_with_same_day_successor(self):
        original = self._ready_guided_draft()
        self.assertEqual(self._publish_guided(original).status_code, 302)
        original.refresh_from_db()
        response = self.client.post(reverse(
            'admin:origination_origination_setup_revise', args=[original.pk]),
            {'request_id': str(uuid.uuid4())})
        self.assertEqual(response.status_code, 302)
        successor = OriginationProductDefinition.objects.get(product_key=original.product_key, lifecycle_status='draft')
        self.assertEqual(original.product_version.effective_from, successor.product_version.effective_from)
        return original, successor

    def test_same_day_guided_successor_replaces_active_version_without_rewriting_application(self):
        from core.services.product_catalog import active_product_version
        original, successor = self._published_with_same_day_successor()
        application = LoanOriginationApplication.objects.create(
            reference_number='SAME-DAY-TRAINING', officer=self.superuser, branch=self.branch.name,
            product_definition=original, product_version=original.product_version,
            schema_snapshot=original.form_schema, product_terms_snapshot={'interest_rate':'10'},
        )
        request_id = str(uuid.uuid4())
        self.assertEqual(self._publish_guided(successor, request_id).status_code, 302)
        original.refresh_from_db()
        successor.refresh_from_db()
        application.refresh_from_db()
        self.assertEqual(original.product_version.status, 'retired')
        self.assertEqual(successor.product_version.status, 'published')
        self.assertEqual(active_product_version(successor.product_version.product).pk, successor.product_version_id)
        self.assertEqual(original.product_version.effective_from, successor.product_version.effective_from)
        self.assertIsNone(original.product_version.effective_to)
        self.assertEqual(application.product_version_id, original.product_version_id)
        self.assertEqual(application.product_definition_id, original.pk)
        self.assertEqual(application.product_terms_snapshot, {'interest_rate':'10'})
        self.assertEqual(self._publish_guided(successor, request_id).status_code, 302)
        self.assertEqual(original.product_version.events.filter(action='same_day_replaced').count(), 1)

    def test_same_day_replacement_rolls_back_if_profile_publication_fails(self):
        original, successor = self._published_with_same_day_successor()
        with patch('origination.services.origination_setup.publish_product_profile',
                   side_effect=ValidationError('Synthetic profile failure')):
            response = self._publish_guided(successor)
        self.assertEqual(response.status_code, 400)
        original.refresh_from_db()
        successor.refresh_from_db()
        self.assertEqual(original.product_version.status, 'published')
        self.assertTrue(original.is_active)
        self.assertEqual(successor.product_version.status, 'draft')
        self.assertFalse(original.product_version.events.filter(action='same_day_replaced').exists())

    def _ready_guided_draft(self):
        self.test_terms_can_save_without_forcing_optional_repeatable_rows()
        definition = OriginationProductDefinition.objects.get(product_key='optional_rows_loan')
        definition.signer_rules = [{'role': 'officer', 'required': True}]
        definition.save(update_fields=['signer_rules'])
        self._ready_document(definition)
        return definition

    def _ready_document(self, definition, *, family='guided-ready-laf', active=True):
        from origination.models import OriginationDocumentProductEligibility, OriginationTemplateConfigurationRevision
        from origination.services.origination_templates import initial_template_configuration
        from core.tests_origination_templates import synthetic_pdf
        import hashlib
        pdf = synthetic_pdf()
        template = OriginationDocumentTemplate.objects.create(
            name='Guided Main LAF', document_type=family, version=1,
            document_role='primary', document_key='primary', status='active' if active else 'ready',
            form_schema=definition.form_schema, signer_rules=definition.signer_rules,
            source_filename='synthetic.pdf', source_sha256=hashlib.sha256(pdf).hexdigest(),
            source_byte_size=len(pdf), page_count=1, drive_file_id='synthetic-drive', created_by=self.superuser,
        )
        config = initial_template_configuration(None, form_schema=definition.form_schema)
        config.update(document_type=family, version=1)
        config['field_overlay_manifest']['fields'] = {
            field['key']: {'context_key':field['key'], 'page_number':1,
                           'box':{'x':10,'y':10,'width':100,'height':15}}
            for field in definition.form_schema.get('fields', [])
        }
        revision = OriginationTemplateConfigurationRevision.objects.create(
            template=template, revision=1, configuration=config, created_by=self.superuser,
            is_published=active,
        )
        if active:
            OriginationDocumentTemplate.objects.filter(pk=template.pk).update(published_configuration_revision=revision)
        OriginationDocumentProductEligibility.objects.create(
            template=template, product=definition.product_version.product, created_by=self.superuser,
        )
        template.refresh_from_db()
        return template

    def _publish_guided(self, definition, request_id=None):
        return self.client.post(reverse(
            'admin:origination_origination_setup_step', args=[definition.pk, 'publish'],
        ), {'expected_tokens': json.dumps(step_tokens(definition)),
            'request_id': request_id or str(uuid.uuid4())})

    def _documents_url(self, definition):
        return reverse('admin:origination_origination_setup_step', args=[definition.pk, 'documents'])

    def test_new_product_needs_only_name_and_branches(self):
        self.client.force_login(self.superuser)
        response = self.client.post(reverse('admin:origination_origination_setup_start'), {
            'name': 'Plain Loan', 'branches': [self.branch.pk], 'request_id': 'plain-start',
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Product.objects.filter(name='Plain Loan', code='plain_loan', active=False).exists())

    def test_enable_requires_document_not_just_valid_terms(self):
        definition = self._ready_guided_draft()
        definition.events.create(action='setup_documents_selected', actor=self.superuser, metadata={'template_ids': []})
        response = self._publish_guided(definition)
        self.assertEqual(response.status_code, 400)
        definition.product_version.refresh_from_db()
        self.assertEqual(definition.product_version.status, 'draft')
        self.assertContains(response, 'Choose a Main LAF', status_code=400)

    def test_reused_laf_derives_profile_and_preserves_original_document(self):
        from origination.models import OriginationDocumentProductEligibility
        from origination.services.origination_setup_documents import selected_documents
        definition = self._ready_guided_draft()
        template = OriginationDocumentTemplate.objects.get(document_type='guided-ready-laf')
        OriginationDocumentProductEligibility.objects.filter(template=template).delete()
        definition.signer_rules = []
        definition.save(update_fields=['signer_rules'])
        response = self.client.post(self._documents_url(definition), {
            'templates': [template.pk], 'request_id': 'reuse-document',
            'expected_tokens': json.dumps(step_tokens(definition)),
        })
        self.assertEqual(response.status_code, 302)
        chosen = selected_documents(definition).get()
        self.assertNotEqual(chosen.pk, template.pk)
        self.assertEqual(chosen.status, 'ready')
        self.assertEqual(chosen.form_schema, template.form_schema)
        self.assertEqual(chosen.drive_file_id, template.drive_file_id)
        template.refresh_from_db()
        self.assertEqual(template.status, 'active')
        self.assertFalse(template.eligible_products.filter(pk=definition.product_version.product_id).exists())
        definition.refresh_from_db()
        self.assertEqual(definition.signer_rules, template.signer_rules)
        self.assertEqual(chosen.configuration_revisions.count(), 1)

    @override_settings(GOOGLE_DRIVE_MEDIA_FOLDER_ID='synthetic-folder')
    @patch('core.services.order_approval.GoogleDriveMediaStorage')
    def test_enable_publishes_draft_document_and_product_together(self, storage):
        from core.tests_origination_templates import synthetic_pdf
        storage.return_value.download.return_value = synthetic_pdf()
        definition = self._ready_guided_draft()
        draft = self._ready_document(definition, family='draft-laf', active=False)
        definition.events.create(action='setup_documents_selected', actor=self.superuser,
                                 metadata={'template_ids': [str(draft.pk)]})
        response = self._publish_guided(definition)
        self.assertEqual(response.status_code, 302, getattr(response, 'context_data', None))
        draft.refresh_from_db()
        definition.refresh_from_db()
        self.assertEqual(draft.status, 'active')
        self.assertEqual(definition.lifecycle_status, 'published')

    @override_settings(GOOGLE_DRIVE_MEDIA_FOLDER_ID='synthetic-folder')
    @patch('core.services.order_approval.GoogleDriveMediaStorage')
    def test_document_activation_rolls_back_if_product_enable_fails(self, storage):
        from core.tests_origination_templates import synthetic_pdf
        storage.return_value.download.return_value = synthetic_pdf()
        definition = self._ready_guided_draft()
        draft = self._ready_document(definition, family='rollback-laf', active=False)
        definition.events.create(action='setup_documents_selected', actor=self.superuser,
                                 metadata={'template_ids': [str(draft.pk)]})
        with patch('origination.services.origination_setup.publish_product_profile', side_effect=ValidationError('Synthetic failure')):
            response = self._publish_guided(definition)
        self.assertEqual(response.status_code, 400)
        draft.refresh_from_db()
        definition.product_version.refresh_from_db()
        self.assertEqual(draft.status, 'ready')
        self.assertIsNone(draft.published_configuration_revision_id)
        self.assertEqual(definition.product_version.status, 'draft')
        self.assertFalse(draft.events.filter(action='activated').exists())

    def test_readiness_never_reads_external_files(self):
        definition = self._ready_guided_draft()
        with patch('origination.services.origination_templates.load_template_source', side_effect=AssertionError('External read')):
            self.assertEqual(self.client.get(self.dashboard_url).status_code, 200)
            self.assertEqual(self.client.get(self._documents_url(definition)).status_code, 200)

    def test_enabled_product_can_create_an_application_with_selected_contract(self):
        from origination.services.loan_origination import create_application
        from origination.services.origination_document_catalogue import catalogue_for_product
        definition = self._ready_guided_draft()
        self.assertEqual(self._publish_guided(definition).status_code, 302)
        definition.refresh_from_db()
        catalogue = catalogue_for_product(definition)
        self.assertTrue(catalogue['ready'])
        application, replayed = create_application(
            product_key=definition.product_key, officer=self.superuser, branch=self.branch.name,
            primary_template_id=catalogue['main_lafs'][0]['id'], supporting_template_ids=[],
            client_request_id='synthetic-enabled-application',
            expected_catalogue_revision=catalogue['catalogue_revision'],
        )
        self.assertFalse(replayed)
        self.assertEqual(application.product_definition_id, definition.pk)
        self.assertEqual(
            [(field['key'], field.get('type')) for field in application.schema_snapshot['fields']],
            [(field['key'], field.get('type')) for field in definition.form_schema['fields']],
        )

    def test_aligned_document_change_invalidates_enable_token(self):
        from origination.models import OriginationTemplateConfigurationRevision
        definition = self._ready_guided_draft()
        expected = step_tokens(definition)
        template = OriginationDocumentTemplate.objects.get(document_type='guided-ready-laf')
        OriginationTemplateConfigurationRevision.objects.create(template=template, revision=2,
            configuration=template.published_configuration_revision.configuration, created_by=self.superuser)
        response = self.client.post(reverse('admin:origination_origination_setup_step', args=[definition.pk, 'publish']), {
            'expected_tokens': json.dumps(expected), 'request_id': 'stale-alignment',
        })
        self.assertEqual(response.status_code, 409)

    def test_upload_is_independent_and_connected_to_inactive_product(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from core.tests_origination_templates import synthetic_pdf
        from origination.services.origination_setup_documents import selected_documents
        definition = self._ready_guided_draft()
        with patch('origination.services.origination_templates._upload_template_bytes', return_value=('synthetic-new-file','https://example.test/pdf')):
            payload = {'action':'upload', 'name':'New LAF', 'role':'primary', 'preset':'',
                       'pdf_file':SimpleUploadedFile('blank.pdf', synthetic_pdf(), content_type='application/pdf'),
                       'expected_tokens':json.dumps(step_tokens(definition)), 'request_id':'new-upload'}
            response = self.client.post(self._documents_url(definition), payload)
            payload['pdf_file'].seek(0)
            replay = self.client.post(self._documents_url(definition), payload)
        self.assertEqual(response.url, replay.url)
        self.assertEqual(response.status_code, 302)
        template = selected_documents(definition).get(name='New LAF')
        self.assertIsNone(template.product_definition_id)
        self.assertEqual(template.status, 'ready')
        self.assertFalse(definition.product_version.product.active)
        self.assertIn('setup_return=', response.url)
        self.assertEqual(self.client.get(response.url).context['calibration_setup_return_warning'], '')

    def test_published_document_repair_keeps_financial_version(self):
        definition = self._ready_guided_draft()
        self.assertEqual(self._publish_guided(definition).status_code, 302)
        definition.refresh_from_db()
        terms_id = definition.product_version_id
        template = OriginationDocumentTemplate.objects.get(document_type='guided-ready-laf')
        response = self.client.post(self._documents_url(definition), {
            'action':'enable_documents', 'templates':[template.pk],
            'expected_tokens':json.dumps(step_tokens(definition)), 'request_id':'repair-documents',
        })
        self.assertEqual(response.status_code, 302)
        definition.refresh_from_db()
        self.assertEqual(definition.product_version_id, terms_id)
        self.assertEqual(definition.lifecycle_status, 'published')

    def test_save_draft_returns_to_current_step_and_legacy_form_redirects(self):
        definition = self._ready_guided_draft()
        template = OriginationDocumentTemplate.objects.get(document_type='guided-ready-laf')
        response = self.client.post(self._documents_url(definition), {
            'intent':'stay', 'templates':[template.pk],
            'expected_tokens':json.dumps(step_tokens(definition)), 'request_id':'stay-documents',
        })
        self.assertEqual(response.url, self._documents_url(definition))
        response = self.client.get(reverse('admin:origination_origination_setup_step', args=[definition.pk, 'form']))
        self.assertEqual(response.url, self._documents_url(definition))

    def test_document_edit_version_keeps_workspace_return_and_selection(self):
        from origination.services.origination_setup_documents import selected_documents
        definition = self._ready_guided_draft()
        source = selected_documents(definition).get()
        token = make_return_token(definition_id=definition.pk, step_key='documents')
        response = self.client.post(reverse('admin:origination_originationdocumenttemplate_create_editable_version', args=[source.pk]), {'setup_return':token})
        self.assertEqual(response.status_code, 302)
        successor = selected_documents(definition).get()
        self.assertNotEqual(successor.pk, source.pk)
        self.assertIn('setup_return=', response.url)
        alignment = self.client.get(response.url)
        self.assertEqual(alignment.context['calibration_back_url'], self._documents_url(definition))
        source.refresh_from_db()
        self.assertEqual(source.status, 'active')

    def test_approval_policy_is_collected_without_another_signer_builder(self):
        definition = self._ready_guided_draft()
        template = OriginationDocumentTemplate.objects.get(document_type='guided-ready-laf')
        response = self.client.post(self._documents_url(definition), {
            'templates':[template.pk], 'approval_mode':'bm',
            'expected_tokens':json.dumps(step_tokens(definition)), 'request_id':'bm-policy',
        })
        self.assertEqual(response.status_code, 302)
        definition.refresh_from_db()
        self.assertEqual(definition.approval_roles, ['branch_manager'])
        self.assertIn('branch_manager', [rule['role'] for rule in definition.signer_rules])
        response = self._publish_guided(definition)
        self.assertEqual(response.status_code, 400)
        definition.product_version.refresh_from_db()
        self.assertEqual(definition.product_version.status, 'draft')

    def test_guided_publication_is_one_atomic_action_without_confirmation_gates(self):
        definition = self._ready_guided_draft()
        request_id = str(uuid.uuid4())
        self.assertEqual(definition.product_version.status, 'draft')
        response = self._publish_guided(definition, request_id)
        self.assertEqual(response.status_code, 302)
        definition.refresh_from_db()
        self.assertEqual(definition.lifecycle_status, 'published')
        self.assertEqual(definition.product_version.status, 'published')
        self.assertTrue(definition.is_active)
        replay = self._publish_guided(definition, request_id)
        self.assertEqual(replay.status_code, 302)
        self.assertEqual(definition.events.filter(action='published').count(), 1)
        self.assertEqual(definition.product_version.events.filter(action='published').count(), 1)

    def test_failed_profile_publication_rolls_back_financial_publication(self):
        definition = self._ready_guided_draft()
        with patch('origination.services.origination_setup.publish_product_profile',
                   side_effect=ValidationError('Synthetic publication failure')):
            response = self._publish_guided(definition)
        self.assertEqual(response.status_code, 400)
        definition.refresh_from_db()
        self.assertEqual(definition.product_version.status, 'draft')
        self.assertFalse(definition.product_version.product.active)
        self.assertEqual(definition.lifecycle_status, 'draft')
        self.assertFalse(definition.product_version.events.filter(action='published').exists())

    def test_financial_publication_metadata_does_not_make_terms_stale(self):
        definition = self._ready_guided_draft()
        from core.services.product_catalog import publish_product_version
        publish_product_version(version=definition.product_version, actor=self.superuser)
        rows = setup_readiness(definition)
        self.assertEqual(next(row for row in rows if row['key'] == 'terms')['status'], 'complete')
        self.assertEqual(self._publish_guided(definition).status_code, 302)

    def test_unrelated_identity_change_does_not_conflict_with_terms_save(self):
        definition = self._ready_guided_draft()
        expected = step_tokens(definition)
        product = definition.product_version.product
        product.description = 'A separate identity edit'
        product.save(update_fields=['description'])
        assert_expected_state(definition=definition, expected_tokens=expected, step_key='terms')
        definition.product_version.interest_rate = '12'
        definition.product_version.save(update_fields=['interest_rate'])
        with self.assertRaises(OriginationSetupConflict):
            assert_expected_state(definition=definition, expected_tokens=expected, step_key='terms')

    def test_legacy_confirmation_hash_cannot_soft_lock_valid_terms(self):
        definition = self._ready_guided_draft()
        event = definition.product_version.events.get(
            action='setup_step_completed', metadata__step_key='terms')
        metadata = dict(event.metadata)
        metadata.pop('content_sha256')
        metadata['state_sha256'] = 'legacy-publication-dependent-hash'
        ProductVersionEvent.objects.filter(pk=event.pk).update(metadata=metadata)
        self.assertEqual(self._publish_guided(definition).status_code, 302)

    def test_legacy_published_terms_can_get_an_editable_successor(self):
        definition = self._ready_guided_draft()
        from core.services.product_catalog import publish_product_version
        published = publish_product_version(version=definition.product_version, actor=self.superuser)
        response = self.client.post(reverse(
            'admin:origination_origination_setup_revise', args=[definition.pk]),
            {'request_id': str(uuid.uuid4())})
        self.assertEqual(response.status_code, 302)
        definition.refresh_from_db()
        self.assertNotEqual(definition.product_version_id, published.pk)
        self.assertEqual(definition.product_version.status, 'draft')
        published.refresh_from_db()
        self.assertEqual(published.status, 'published')

    def test_legacy_terms_publish_link_never_publishes_early(self):
        definition = self._ready_guided_draft()
        url = reverse('admin:origination_origination_setup_step', args=[definition.pk, 'terms_publish'])
        for method in (self.client.get, self.client.post):
            response = method(url)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.url, reverse(
                'admin:origination_origination_setup_step', args=[definition.pk, 'publish']))
        definition.product_version.refresh_from_db()
        self.assertEqual(definition.product_version.status, 'draft')

    def test_invalid_signers_still_block_publication(self):
        definition = self._ready_guided_draft()
        definition.signer_rules = []
        definition.save(update_fields=['signer_rules'])
        response = self._publish_guided(definition)
        self.assertEqual(response.status_code, 400)
        definition.product_version.refresh_from_db()
        self.assertEqual(definition.product_version.status, 'draft')

    def test_form_can_save_while_financial_terms_are_still_draft(self):
        definition = self._ready_guided_draft()
        response = self.client.post(reverse(
            'admin:origination_origination_setup_step', args=[definition.pk, 'form'],
        ), {'expected_tokens': json.dumps(step_tokens(definition)), 'request_id': str(uuid.uuid4()),
            'form_schema': json.dumps(definition.form_schema),
            'signer_rules': json.dumps(definition.signer_rules)})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse(
            'admin:origination_origination_setup_step', args=[definition.pk, 'documents']))
        definition.product_version.refresh_from_db()
        self.assertEqual(definition.product_version.status, 'draft')

    def test_changed_valid_financial_terms_are_advisory_not_a_publication_lock(self):
        definition = self._ready_guided_draft()
        definition.product_version.interest_rate = '12'
        definition.product_version.save(update_fields=['interest_rate'])
        row = next(row for row in setup_readiness(definition) if row['key'] == 'terms')
        self.assertEqual(row['status'], 'stale')
        self.assertEqual(row['status_label'], 'Review changes')
        self.assertTrue(row['valid'])
        self.assertEqual(self._publish_guided(definition).status_code, 302)

    def test_final_publication_rejects_a_concurrent_financial_edit(self):
        definition = self._ready_guided_draft()
        expected = step_tokens(definition)
        definition.product_version.interest_rate = '12'
        definition.product_version.save(update_fields=['interest_rate'])
        response = self.client.post(reverse(
            'admin:origination_origination_setup_step', args=[definition.pk, 'publish'],
        ), {'expected_tokens': json.dumps(expected), 'request_id': str(uuid.uuid4())})
        self.assertEqual(response.status_code, 409)
        definition.product_version.refresh_from_db()
        self.assertEqual(definition.product_version.status, 'draft')

    def setUp(self):
        from core.tests_origination_templates import synthetic_pdf
        source = patch('origination.services.origination_templates.load_template_source', return_value=synthetic_pdf())
        source.start()
        self.addCleanup(source.stop)
        self.superuser = get_user_model().objects.create_superuser(
            username='setup-admin', email='setup@example.test', password='secret',
        )
        self.staff = get_user_model().objects.create_user(
            username='setup-staff', password='secret', is_staff=True,
        )
        self.branch = OperationalLocation.objects.create(
            location_type='branch', name='Setup Branch', code='SETUP-BRANCH',
        )
        self.dashboard_url = reverse('admin:origination_origination_setup_dashboard')

    def test_every_setup_route_requires_active_superuser(self):
        self.client.force_login(self.staff)
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 403)

    def test_dashboard_renders_guided_workspace(self):
        self.client.force_login(self.superuser)
        response = self.client.get(self.dashboard_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Product setup workspace')
        self.assertContains(response, 'Start a product')
        self.assertContains(response, 'osw-admin-page')
        self.assertContains(response, 'admin/origination_setup_layout.css')

    def test_start_is_idempotent_and_creates_durable_draft(self):
        self.client.force_login(self.superuser)
        request_id = str(uuid.uuid4())
        payload = {
            'request_id': request_id,
            'name': 'Guided Loan',
            'code': 'guided_loan',
            'category': 'Credit',
            'description': 'Created through the guided setup.',
            'sort_order': 10,
            'branches': [self.branch.pk],
        }
        start_url = reverse('admin:origination_origination_setup_start')
        first = self.client.post(start_url, payload)
        second = self.client.post(start_url, payload)
        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        self.assertEqual(Product.objects.filter(code='guided_loan').count(), 1)
        definition = OriginationProductDefinition.objects.get(product_key='guided_loan')
        self.assertEqual(definition.lifecycle_status, definition.STATUS_DRAFT)
        self.assertFalse(definition.is_active)
        self.assertTrue(ProductAvailability.objects.filter(
            product=definition.product_version.product,
            branch=self.branch,
            workflow='loan_origination', channel='portal', active=True,
        ).exists())
        self.assertFalse(ProductAvailability.objects.filter(
            product=definition.product_version.product,
            workflow='loan_origination', channel='telegram', active=True,
        ).exists())
        self.assertEqual(ProductVersionEvent.objects.filter(
            action='setup_started', metadata__request_id=request_id,
        ).count(), 1)

    def test_changed_state_is_rejected_and_marks_completed_step_stale(self):
        self.client.force_login(self.superuser)
        self.client.post(reverse('admin:origination_origination_setup_start'), {
            'request_id': str(uuid.uuid4()), 'name': 'Conflict Loan',
            'code': 'conflict_loan', 'category': '', 'description': '',
            'sort_order': 0, 'branches': [self.branch.pk],
        })
        definition = OriginationProductDefinition.objects.get(product_key='conflict_loan')
        expected = step_tokens(definition)
        product = definition.product_version.product
        product.description = 'Changed in another tab.'
        product.save()
        with self.assertRaises(OriginationSetupConflict):
            assert_expected_state(definition=definition, expected_tokens=expected)
        identity = next(
            item for item in setup_readiness(definition) if item['key'] == 'identity'
        )
        self.assertEqual(identity['status'], 'stale')

    def test_stale_admin_write_returns_409_without_overwriting(self):
        self.client.force_login(self.superuser)
        self.client.post(reverse('admin:origination_origination_setup_start'), {
            'request_id': str(uuid.uuid4()), 'name': 'Concurrent Loan',
            'code': 'concurrent_loan', 'category': '', 'description': 'Original',
            'sort_order': 0, 'branches': [self.branch.pk],
        })
        definition = OriginationProductDefinition.objects.get(product_key='concurrent_loan')
        expected = step_tokens(definition)
        product = definition.product_version.product
        product.description = 'Newer value'
        product.save()
        response = self.client.post(reverse(
            'admin:origination_origination_setup_step', args=[definition.pk, 'identity'],
        ), {
            'expected_tokens': json.dumps(expected), 'request_id': str(uuid.uuid4()),
            'name': product.name, 'code': product.code, 'category': product.category,
            'description': 'My stale value', 'sort_order': product.sort_order,
            'branches': [self.branch.pk],
        })
        self.assertEqual(response.status_code, 409)
        product.refresh_from_db()
        self.assertEqual(product.description, 'Newer value')

    def test_signed_calibration_return_token_is_bounded_and_tamper_safe(self):
        definition_id = uuid.uuid4()
        token = make_return_token(definition_id=definition_id, step_key='calibration')
        self.assertEqual(resolve_return_token(token), {
            'definition_id': str(definition_id), 'step_key': 'calibration',
        })
        with self.assertRaises(signing.BadSignature):
            resolve_return_token(token + 'tampered')

    def test_calibration_accepts_only_signed_internal_workspace_return(self):
        self.client.force_login(self.superuser)
        self.client.post(reverse('admin:origination_origination_setup_start'), {
            'request_id': str(uuid.uuid4()), 'name': 'Return Loan',
            'code': 'return_loan', 'category': '', 'description': '',
            'sort_order': 0, 'branches': [self.branch.pk],
        })
        definition = OriginationProductDefinition.objects.get(product_key='return_loan')
        template = OriginationDocumentTemplate.objects.create(
            product_definition=definition, document_key='primary',
            document_role='primary', inclusion_mode='required',
            document_type=definition.document_type, name='Return LAF', version=1,
            source_filename='return.pdf', source_sha256='a' * 64,
            source_byte_size=100, page_count=1, placement_config={},
            drive_file_id='test-drive-file', created_by=self.superuser,
        )
        token = make_return_token(definition_id=definition.pk)
        response = self.client.get(
            reverse('admin:origination_originationdocumenttemplate_calibrate', args=[template.pk]),
            {'setup_return': token},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['calibration_back_url'], reverse(
            'admin:origination_origination_setup_step', args=[definition.pk, 'calibration'],
        ))
        invalid = self.client.get(
            reverse('admin:origination_originationdocumenttemplate_calibrate', args=[template.pk]),
            {'setup_return': token + 'tampered'},
        )
        self.assertEqual(
            invalid.context['calibration_back_url'],
            reverse('admin:origination_origination_setup_dashboard'),
        )
        self.assertContains(invalid, 'invalid or expired')

    def test_terms_step_posts_expected_state_contract(self):
        self.client.force_login(self.superuser)
        self.client.post(reverse('admin:origination_origination_setup_start'), {
            'request_id': str(uuid.uuid4()), 'name': 'Terms Loan',
            'code': 'terms_loan', 'category': '', 'description': '',
            'sort_order': 0, 'branches': [self.branch.pk],
        })
        definition = OriginationProductDefinition.objects.get(product_key='terms_loan')
        response = self.client.get(reverse(
            'admin:origination_origination_setup_step', args=[definition.pk, 'terms'],
        ))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="expected_tokens"')
        self.assertEqual(
            json.loads(response.context['expected_tokens']), step_tokens(definition),
        )

    def test_product_overview_is_read_only_and_superuser_only(self):
        self.client.force_login(self.superuser)
        self.client.post(reverse('admin:origination_origination_setup_start'), {
            'request_id': str(uuid.uuid4()), 'name': 'Overview Loan',
            'code': 'overview_loan', 'category': 'Credit', 'description': '',
            'sort_order': 0, 'branches': [self.branch.pk],
        })
        definition = OriginationProductDefinition.objects.get(product_key='overview_loan')
        url = reverse('admin:origination_origination_setup_detail', args=[definition.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Commercial terms')
        self.assertContains(response, 'Compatibility profile')
        self.assertContains(response, 'Historical product-attached packet')
        self.assertContains(response, 'Setup Branch')

        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(url).status_code, 403)

    @override_settings(ORIGINATION_WEBAPP_REQUIRE_TELEGRAM_AUTH=False, SECURE_SSL_REDIRECT=False)
    def test_guided_branch_availability_reaches_the_origination_product_api(self):
        self.client.force_login(self.superuser)
        self.client.post(reverse('admin:origination_origination_setup_start'), {
            'request_id': str(uuid.uuid4()), 'name': 'Visible Guided Loan',
            'code': 'visible_guided_loan', 'category': 'Credit', 'description': '',
            'sort_order': 0, 'branches': [self.branch.pk],
        })
        definition = OriginationProductDefinition.objects.get(
            product_key='visible_guided_loan',
        )
        from core.services.product_catalog import publish_product_version
        publish_product_version(
            version=definition.product_version, actor=self.superuser,
        )
        OriginationProductDefinition.objects.filter(pk=definition.pk).update(
            lifecycle_status=OriginationProductDefinition.STATUS_PUBLISHED,
            is_active=True,
        )

        response = self.client.get(
            reverse('loan_origination_products'), {'branch': self.branch.name},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            'visible_guided_loan',
            [item['product_key'] for item in response.json()['products']],
        )

    def test_terms_can_save_without_forcing_optional_repeatable_rows(self):
        self.client.force_login(self.superuser)
        self.client.post(reverse('admin:origination_origination_setup_start'), {
            'request_id': str(uuid.uuid4()), 'name': 'Optional Rows Loan',
            'code': 'optional_rows_loan', 'category': '', 'description': '',
            'sort_order': 0, 'branches': [self.branch.pk],
        })
        definition = OriginationProductDefinition.objects.get(product_key='optional_rows_loan')
        version = definition.product_version
        payload = {
            'expected_tokens': json.dumps(step_tokens(definition), sort_keys=True),
            'request_id': str(uuid.uuid4()),
            'currency': version.currency, 'min_amount': '1000', 'max_amount': '50000',
            'min_tenor': '1', 'max_tenor': '12', 'tenor_unit': version.tenor_unit,
            'interest_method': version.interest_method, 'interest_rate': '10',
            'interest_rate_period': version.interest_rate_period,
            'repayment_frequency': version.repayment_frequency,
            'quote_amount_field_key': version.quote_amount_field_key,
            'quote_tenor_field_key': version.quote_tenor_field_key,
            'effective_from': version.effective_from.isoformat(), 'effective_to': '',
            'fees-TOTAL_FORMS': '1', 'fees-INITIAL_FORMS': '0',
            'fees-MIN_NUM_FORMS': '0', 'fees-MAX_NUM_FORMS': '1000',
            'fees-0-position': '0', 'fees-0-fee_type': 'fixed',
            'fees-0-calculation_basis': 'principal',
            'fees-0-collection_mode': 'upfront', 'fees-0-mandatory': 'on',
            'requirements-TOTAL_FORMS': '1', 'requirements-INITIAL_FORMS': '0',
            'requirements-MIN_NUM_FORMS': '0', 'requirements-MAX_NUM_FORMS': '1000',
            'requirements-0-position': '0', 'requirements-0-required': 'on',
            'requirements-0-active': 'on',
            'attributes-TOTAL_FORMS': '1', 'attributes-INITIAL_FORMS': '0',
            'attributes-MIN_NUM_FORMS': '0', 'attributes-MAX_NUM_FORMS': '1000',
            'attributes-0-position': '0',
        }
        response = self.client.post(reverse(
            'admin:origination_origination_setup_step', args=[definition.pk, 'terms'],
        ), payload)
        self.assertEqual(response.status_code, 302)
        replay = self.client.post(reverse(
            'admin:origination_origination_setup_step', args=[definition.pk, 'terms'],
        ), payload)
        self.assertEqual(replay.status_code, 302)
        version.refresh_from_db()
        self.assertEqual(str(version.min_amount), '1000.00')
        self.assertEqual(version.fees.count(), 0)
        self.assertEqual(version.events.filter(
            action='setup_step_completed', metadata__step_key='terms',
        ).count(), 1)
