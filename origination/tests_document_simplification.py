"""Synthetic regressions for copying, advisory publication and seed identity."""
from copy import deepcopy
from dataclasses import replace
import hashlib
from unittest.mock import patch
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.test import TransactionTestCase
from django.db import connection, close_old_connections
from django.urls import reverse
from django.utils import timezone

from core.tests_origination_templates import synthetic_pdf
from core.tests_origination_document_editor import DocumentEditorTests as _EditorFixture
from origination.models import OriginationDocumentTemplate, OriginationTemplateConfigurationRevision, OriginationProductDefinition
from origination.services.document_editor import publish_document, readiness
from origination.services.origination_templates import clone_reusable_template_version, clone_product_version, save_calibration_draft


class EditableAlignmentTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_superuser('synthetic-copy', '', 'test-only')
        self.pdf = synthetic_pdf()
        self.config = {'document_type': 'synthetic-copy', 'version': 1,
            'field_overlay_manifest': {'defaults': {'font_size': 11}, 'fields': {'name': {
                'context_key': 'synthetic_name', 'page_number': 1, 'box': {'x': 10, 'y': 30, 'width': 120, 'height': 16}}}},
            'signature_overlay_manifest': {'slots': {}}, 'sample_context': {'synthetic_name': 'Synthetic'}}
        self.source = OriginationDocumentTemplate.objects.create(document_type='synthetic-copy', version=1,
            name='Synthetic LAF', status='active', form_schema={'fields': [{'key': 'synthetic_name', 'type': 'text'}]},
            signer_rules=[], source_filename='synthetic.pdf', source_sha256=hashlib.sha256(self.pdf).hexdigest(),
            source_byte_size=len(self.pdf), page_count=1, drive_file_id='synthetic-drive',
            placement_config=self.config, created_by=self.actor)
        self.source.published_configuration_revision = OriginationTemplateConfigurationRevision.objects.create(
            template=self.source, revision=1, configuration=self.config, is_published=True,
            created_by=self.actor, published_at=timezone.now())
        self.source.save(update_fields=['published_configuration_revision'])

    def test_unrelated_blank_draft_is_not_an_editable_copy(self):
        blank = deepcopy(self.config)
        blank['version'] = 2
        blank['field_overlay_manifest']['fields'] = {}
        unrelated = OriginationDocumentTemplate.objects.create(document_type=self.source.document_type, version=2,
            name='Synthetic seed draft', status='ready', form_schema=self.source.form_schema, signer_rules=[],
            source_filename='synthetic.pdf', source_sha256=self.source.source_sha256, source_byte_size=len(self.pdf),
            page_count=1, drive_file_id='synthetic-drive', placement_config=blank, created_by=self.actor)
        OriginationTemplateConfigurationRevision.objects.create(template=unrelated, revision=1,
            configuration=blank, created_by=self.actor)
        copied, replayed = clone_reusable_template_version(self.source, actor=self.actor)
        self.assertFalse(replayed)
        self.assertNotEqual(copied.pk, unrelated.pk)
        self.assertEqual(copied.placement_config['field_overlay_manifest'], self.config['field_overlay_manifest'])
        unrelated.refresh_from_db()
        self.assertEqual(unrelated.placement_config, blank)

    def test_genuine_editable_draft_keeps_later_edits_on_reopen(self):
        copied, _ = clone_reusable_template_version(self.source, actor=self.actor)
        edited = deepcopy(copied.placement_config)
        edited['field_overlay_manifest']['fields']['name']['box']['x'] = 50
        with patch('origination.services.origination_templates.load_template_source', return_value=self.pdf):
            save_calibration_draft(template=copied, configuration=edited, actor=self.actor,
                expected_revision=1, client_request_id='synthetic-edit')
        reopened, replayed = clone_reusable_template_version(self.source, actor=self.actor)
        self.assertTrue(replayed)
        self.assertEqual(reopened.pk, copied.pk)
        self.assertEqual(reopened.configuration_revisions.latest('revision').configuration, edited)
        self.source.refresh_from_db()
        self.assertEqual(self.source.placement_config, self.config)

    def test_product_successor_inherits_published_layout_not_a_later_blank_draft(self):
        product = OriginationProductDefinition.objects.create(product_key='synthetic-copy-product',
            name='Synthetic product', lifecycle_status='published', is_active=True,
            document_type=self.source.document_type, document_template_sha256=self.source.source_sha256,
            form_schema=self.source.form_schema, signer_rules=[], created_by=self.actor)
        self.source.product_definition = product
        self.source.display_order = 20
        self.source.save(update_fields=['product_definition', 'display_order'])
        blank = deepcopy(self.config)
        blank['version'] = 2
        blank['field_overlay_manifest']['fields'] = {}
        OriginationDocumentTemplate.objects.create(product_definition=product,
            document_type=self.source.document_type, version=2, name='Unrelated draft', status='ready',
            source_filename='synthetic.pdf', source_sha256=self.source.source_sha256, source_byte_size=len(self.pdf),
            page_count=1, drive_file_id='synthetic-drive', placement_config=blank, created_by=self.actor)
        successor = clone_product_version(product, actor=self.actor)
        self.assertEqual(successor.document_templates.count(), 1)
        self.assertEqual(successor.document_templates.get().placement_config['field_overlay_manifest'],
                         self.config['field_overlay_manifest'])


@override_settings(SECURE_SSL_REDIRECT=False)
class AdvisoryPublicationTests(_EditorFixture):
    def test_invalid_supplied_geometry_is_still_a_blocker(self):
        document = self.ready()
        config = deepcopy(document.configuration_revisions.latest('revision').configuration)
        config['field_overlay_manifest']['fields'][next(iter(config['field_overlay_manifest']['fields']))]['box']['width'] = -1
        from origination.services.origination_templates import OriginationTemplateError
        with self.assertRaises(OriginationTemplateError):
            save_calibration_draft(template=document, configuration=config, actor=self.actor,
                expected_revision=2, client_request_id='invalid-geometry')
        self.assertEqual(document.configuration_revisions.count(), 2)

    def test_warnings_do_not_bypass_publish_revision_or_source_integrity(self):
        saved = save_calibration_draft(template=self.document, configuration=self.document.placement_config,
            actor=self.actor, expected_revision=0, client_request_id='integrity-save')
        with self.assertRaisesRegex(ValidationError, 'document changed'):
            publish_document(document=self.document, actor=self.actor, revision=0,
                request_id='stale-warning-publish', impact_token='')
        from origination.services.origination_templates import OriginationTemplateError
        with patch('core.services.order_approval.GoogleDriveMediaStorage') as storage:
            storage.return_value.download.return_value = b'not-the-reviewed-pdf'
            with self.assertRaisesRegex(OriginationTemplateError, 'integrity'):
                publish_document(document=self.document, actor=self.actor, revision=saved.revision,
                    request_id='bad-source-warning-publish', impact_token='')
        self.document.refresh_from_db()
        self.assertEqual(self.document.status, 'ready')
        self.assertIsNone(self.document.published_configuration_revision_id)

    def test_static_document_can_publish_without_unused_field_warnings(self):
        saved = save_calibration_draft(template=self.document, configuration=self.document.placement_config,
            actor=self.actor, expected_revision=0, client_request_id='empty-save')
        self.document.refresh_from_db()
        self.assertTrue(readiness(self.document)['can_publish'])
        self.assertEqual(readiness(self.document)['outstanding_count'], 0)
        published = publish_document(document=self.document, actor=self.actor, revision=saved.revision,
            request_id='empty-publish', impact_token='')
        self.assertEqual(published.status, 'active')
        self.assertEqual(published.placement_config['field_overlay_manifest']['fields'], {})

    def test_missing_required_fields_and_signature_are_warnings(self):
        document = self.save([{'role': 'borrower', 'required': True}])
        result = readiness(document)
        self.assertTrue(result['can_publish'])
        self.assertTrue(any(item['key'].startswith('signature:') for item in result['tasks']))
        published = publish_document(document=document, actor=self.actor, revision=1,
            request_id='missing-publish', impact_token='')
        self.assertEqual(published.status, 'active')

    def test_legacy_borrower_not_offered_but_its_existing_placements_survive(self):
        document = self.save([{'role': 'customer', 'label': 'Borrower', 'required': True}])
        response = self.client.get(reverse('admin:origination_originationdocumenttemplate_calibration_state', args=[document.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('customer', [role[0] for role in response.json()['signer_roles']])
        self.assertEqual(document.signer_rules[0]['role'], 'customer')

    def test_editor_does_not_render_lending_field_shortcut(self):
        response = self.client.get(reverse('admin:origination_originationdocumenttemplate_calibrate', args=[self.document.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Add lending fields')


@override_settings(GOOGLE_DRIVE_MEDIA_FOLDER_ID='synthetic-folder')
class SeedIdentityTests(TestCase):
    def setUp(self):
        from core.models import ComplianceAuditChainState
        ComplianceAuditChainState.objects.get_or_create(singleton=1)
        self.actor = get_user_model().objects.create_superuser('synthetic-seed-root', '', 'test-only')
        self.upload = self.enterContext(patch('origination.services.origination_templates._upload_template_bytes',
            side_effect=lambda template, **kwargs: (f'synthetic-{template.pk}', 'https://example.test/blank')))

    @override_settings(ORIGINATION_LAF_BOOTSTRAP_ENABLED=True, ORIGINATION_LAF_BOOTSTRAP_ACTOR='synthetic-seed-root')
    def test_environment_completion_survives_changed_fingerprint_and_missing_assets(self):
        from origination.services import origination_laf_bootstrap as bootstrap
        bootstrap.bootstrap_lafs_from_environment()
        with patch.object(bootstrap, 'bootstrap_fingerprint', return_value='different-contract'), \
             patch.object(bootstrap, 'bundled_definitions', side_effect=AssertionError('Completed seeds need no asset reads')):
            self.assertEqual(bootstrap.bootstrap_lafs_from_environment()['status'], 'already_completed')
        self.assertEqual(OriginationDocumentTemplate.objects.count(), 11)
        self.assertEqual(self.upload.call_count, 11)

    def test_seed_reuses_edited_assigned_document_instead_of_creating_blank_version(self):
        from core.models import Product
        from origination.services.origination_laf_bootstrap import bundled_definitions, ASSET_ROOT
        from origination.services.origination_main_laf_seeds import apply_seed
        definition = bundled_definitions()[0]
        first = apply_seed(definition, laf_root=ASSET_ROOT, actor=self.actor, shared_values=True, unassigned=True)['template']
        first.form_schema['fields'][0]['label'] = 'Human edited label'
        first.save(update_fields=['form_schema'])
        first.product_eligibilities.create(product=Product.objects.create(code='synthetic-seed-product', name='Synthetic'))
        changed = replace(definition, name='Changed seed definition name')
        second = apply_seed(changed, laf_root=ASSET_ROOT, actor=self.actor, shared_values=True, unassigned=True)
        self.assertEqual(second['template'].pk, first.pk)
        self.assertFalse(second['created_template'])
        self.assertEqual(second['template'].form_schema['fields'][0]['label'], 'Human edited label')
        self.assertEqual(self.upload.call_count, 1)


@skipUnless(connection.vendor == 'postgresql', 'Requires real PostgreSQL row locks.')
@override_settings(GOOGLE_DRIVE_MEDIA_FOLDER_ID='synthetic-folder')
class ConcurrentSeedIdentityTests(TransactionTestCase):
    def test_manual_first_requests_create_and_upload_one_logical_seed(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from origination.services.origination_laf_bootstrap import bundled_definitions, ASSET_ROOT
        from origination.services.origination_main_laf_seeds import apply_seed
        actor = get_user_model().objects.create_superuser('synthetic-seed-concurrency', '', 'test-only')
        definition = bundled_definitions()[0]
        start = Barrier(2)

        def run():
            close_old_connections()
            try:
                local_actor = get_user_model().objects.get(pk=actor.pk)
                start.wait(timeout=20)
                result = apply_seed(definition, laf_root=ASSET_ROOT, actor=local_actor, shared_values=True, unassigned=True)
                return result['template'].pk, result['created_template']
            finally:
                close_old_connections()

        with patch('origination.services.origination_templates._upload_template_bytes',
                   return_value=('synthetic-drive', 'https://example.test/blank')) as upload, ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run) for _ in range(2)]
            results = [future.result(timeout=30) for future in futures]
        self.assertEqual(results[0][0], results[1][0])
        self.assertEqual(sum(created for _pk, created in results), 1)
        self.assertEqual(OriginationDocumentTemplate.objects.count(), 1)
        self.assertEqual(upload.call_count, 1)


@skipUnless(connection.vendor == 'postgresql', 'Requires real PostgreSQL row locks.')
class ConcurrentEditableDocumentTests(TransactionTestCase):
    def test_independent_editor_requests_reuse_one_copy_without_caller_transaction(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        EditableAlignmentTests.setUp(self)
        barrier = Barrier(2)

        def run():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                document, replayed = clone_reusable_template_version(self.source, actor=self.actor)
                return document.pk, replayed
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [pool.submit(run) for _ in range(2)]
            results = [result.result(timeout=30) for result in results]
        self.assertEqual(results[0][0], results[1][0])
        self.assertEqual(sum(not replayed for _pk, replayed in results), 1)
        self.assertEqual(OriginationDocumentTemplate.objects.filter(status='ready').count(), 1)
