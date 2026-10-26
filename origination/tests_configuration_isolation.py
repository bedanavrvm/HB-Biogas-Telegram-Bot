"""Synthetic contracts for document-owned requirements and shared products."""
from types import SimpleNamespace
from unittest.mock import Mock

from django.test import SimpleTestCase

from origination.services.document_editor import readiness
from origination.services.loan_origination import validate_product_form_contract
from origination.services.origination_templates import _expected_signature_slots


class DocumentConfigurationTests(SimpleTestCase):
    def document(self):
        return SimpleNamespace(
            form_schema={'fields': [{'key': 'applicant_name', 'type': 'text'}],
                         'required_signer_roles': ['asset_owner', 'officer']},
            signer_rules=[], product_definition_id=None, product_definition=None,
            document_role='supporting', ROLE_PRIMARY='primary', ROLE_SUPPORTING='supporting',
            configuration_revisions=Mock(**{'order_by.return_value.first.return_value': None}),
            placement_config={'field_overlay_manifest': {'fields': {}},
                              'signature_overlay_manifest': {'slots': {}}},
            status='ready', drive_file_id='synthetic', page_count=1,
        )

    def test_deleted_seed_signers_do_not_return_as_warnings(self):
        labels = [task['label'] for task in readiness(self.document())['tasks']]
        self.assertFalse(any(label.startswith('Review signer:') for label in labels), labels)

    def test_empty_document_signers_do_not_inherit_product_signers(self):
        product = SimpleNamespace(signer_rules=[{'role': 'borrower', 'slots': [{'key': 'signature'}]}])
        self.assertEqual(_expected_signature_slots(product, self.document()), {})

    def test_static_signature_free_document_is_valid(self):
        validate_product_form_contract({'fields': []}, [], require_signers=False, require_fields=False)

    def test_supporting_signer_can_reference_shared_main_laf_identity(self):
        validate_product_form_contract({'fields': [{'key': 'visit_notes', 'type': 'text'}]},
            [{'role': 'borrower', 'required': True, 'slots': [{'key': 'signature'}],
              'identity_fields': {'name': 'applicant_name', 'phone': 'applicant_phone'}}],
            require_signers=False, allow_shared_identity=True)

    def test_static_supporting_pdf_can_join_a_shared_value_packet(self):
        from origination.services.origination_value_contracts import build_packet_contract, upgrade_schema
        contract = build_packet_contract(upgrade_schema({'fields': [{'key': 'applicant_name', 'type': 'text'}]}),
            [{'key': 'static_visit', 'schema': {'fields': []}}])
        self.assertIn('applicant_name', contract['fields'])
        self.assertEqual(contract['documents']['static_visit'], {})


from copy import deepcopy
from django.contrib.auth import get_user_model
from django.test import TestCase
from core.models import Product, ProductVersion, ProductAvailability, TatTrackerCase
from origination.models import OriginationProductDefinition


class SharedProductIsolationTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_superuser('isolation-admin', password='synthetic-only')
        self.product = Product.objects.create(code='isolation_loan', name='Isolation loan')
        self.version = ProductVersion.objects.create(product=self.product, version=1)
        self.availability = ProductAvailability.objects.create(product=self.product, workflow='tat_tracker')
        self.case = TatTrackerCase.objects.create(group_id='synthetic-isolation', case_id='SYNTHETIC-1',
            client_name='Synthetic applicant', branch='Synthetic', product=self.product, product_version=self.version)
        self.definition = OriginationProductDefinition.objects.create(product_version=self.version,
            product_key=self.product.code, name=self.product.name, document_type='synthetic',
            workflow_configuration={'version': 1, 'requirements': [], 'custom_attributes': []})

    def test_global_reset_is_blocked_without_touching_any_app(self):
        from core.services.product_catalog_full_reset import preview_full_product_catalog_reset, reset_full_product_catalog, ProductCatalogFullResetError
        preview = preview_full_product_catalog_reset()
        self.assertFalse(preview['can_reset'])
        self.assertTrue(any(item['id'] == str(self.product.pk) for item in preview['blockers']))
        with self.assertRaisesRegex(ProductCatalogFullResetError, 'Reset blocked'):
            reset_full_product_catalog(actor=self.actor, reason='Synthetic reset', request_id='isolation-reset')
        self.product.refresh_from_db()
        self.assertTrue(self.product.active)
        self.assertTrue(ProductAvailability.objects.filter(pk=self.availability.pk).exists())
        self.assertTrue(TatTrackerCase.objects.filter(pk=self.case.pk).exists())
        self.assertTrue(OriginationProductDefinition.objects.filter(pk=self.definition.pk).exists())

    def test_origination_reset_preserves_global_product_and_tat_state(self):
        from origination.services.origination_god_mode import reset_all_origination_data
        before = (Product.objects.values().get(pk=self.product.pk),
                  ProductVersion.objects.values().get(pk=self.version.pk),
                  TatTrackerCase.objects.values().get(pk=self.case.pk),
                  ProductAvailability.objects.values().get(pk=self.availability.pk))
        reset_all_origination_data(actor=self.actor, reason='Synthetic Origination-only reset')
        self.assertFalse(OriginationProductDefinition.objects.filter(pk=self.definition.pk).exists())
        after = (Product.objects.values().get(pk=self.product.pk),
                 ProductVersion.objects.values().get(pk=self.version.pk),
                 TatTrackerCase.objects.values().get(pk=self.case.pk),
                 ProductAvailability.objects.values().get(pk=self.availability.pk))
        self.assertEqual(before, after)

    def test_local_successor_keeps_shared_financial_version(self):
        from origination.services.origination_templates import clone_product_version
        OriginationProductDefinition.objects.filter(pk=self.definition.pk).update(lifecycle_status='published', is_active=True)
        self.definition.refresh_from_db()
        successor = clone_product_version(self.definition, actor=self.actor)
        self.assertEqual(successor.product_version_id, self.version.pk)
        self.assertEqual(successor.workflow_configuration, self.definition.workflow_configuration)
        self.assertEqual(successor.form_schema, self.definition.form_schema)
        self.assertEqual(self.product.versions.count(), 1)

    def test_local_requirements_and_attributes_are_snapshotted_independently(self):
        from origination.services.origination_product_configuration import apply_configuration, validate_snapshot_custom_values
        self.definition.workflow_configuration = {'requirements': [{'key': 'local_proof', 'type': 'document',
            'label': 'Local proof', 'required': True, 'enforcement_stage': 'review'}],
            'custom_attributes': [{'key': 'local_note', 'label': 'Local note', 'type': 'text', 'required': True}]}
        terms = apply_configuration({'requirements': [{'key': 'tat_only'}]}, self.definition)
        self.definition.workflow_configuration['requirements'].clear()
        self.assertEqual([item['key'] for item in terms['requirements']], ['local_proof'])
        self.assertIn('local_note', validate_snapshot_custom_values(terms, {}))
        self.assertEqual(validate_snapshot_custom_values(terms, {'local_note': 'Synthetic'}), {})

    def test_local_forms_do_not_write_global_requirement_rows(self):
        from origination.origination_setup_forms import local_configuration_forms, local_configuration_values
        data = {'requirements-TOTAL_FORMS': '1', 'requirements-INITIAL_FORMS': '0',
            'requirements-0-key': 'proof', 'requirements-0-label': 'Proof', 'requirements-0-position': '0',
            'requirements-0-requirement_type': 'document', 'requirements-0-enforcement_stage': 'review',
            'requirements-0-required': 'on', 'requirements-0-active': 'on',
            'attributes-TOTAL_FORMS': '0', 'attributes-INITIAL_FORMS': '0'}
        requirements, attributes = local_configuration_forms(data, {})
        self.assertTrue(requirements.is_valid(), requirements.errors)
        self.assertTrue(attributes.is_valid(), attributes.errors)
        configuration = local_configuration_values(requirements, attributes, {})
        self.assertEqual(configuration['requirements'][0]['key'], 'proof')
        self.assertEqual(self.version.requirements.count(), 0)

    def test_migration_copies_only_origination_configuration_and_keeps_shared_rows(self):
        import importlib
        from django.apps import apps
        from django.db import connection
        from core.models import ProductRequirement, ProductCustomAttribute
        ProductRequirement.objects.create(product_version=self.version, key='shared', label='Shared',
            requirement_type='text', workflow='', enforcement_stage='review')
        ProductRequirement.objects.create(product_version=self.version, key='tat', label='TAT',
            requirement_type='text', workflow='tat_tracker')
        ProductCustomAttribute.objects.create(product_version=self.version, key='local', label='Local',
            attribute_type='text', workflow_visibility=['loan_origination'])
        OriginationProductDefinition.objects.filter(pk=self.definition.pk).update(workflow_configuration={})
        migration = importlib.import_module('origination.migrations.0014_originationproductdefinition_workflow_configuration')
        migration.capture_origination_configuration(apps, SimpleNamespace(connection=connection))
        self.definition.refresh_from_db()
        self.assertEqual([item['key'] for item in self.definition.workflow_configuration['requirements']], ['shared'])
        self.assertEqual([item['key'] for item in self.definition.workflow_configuration['custom_attributes']], ['local'])
        self.assertEqual(self.version.requirements.count(), 2)


class SelectedPacketTests(TestCase):
    def setUp(self):
        import hashlib
        from django.utils import timezone
        from core.models import OperationalLocation, ComplianceAuditChainState
        from core.tests_origination_templates import synthetic_pdf
        self.actor = get_user_model().objects.create_superuser('packet-isolation', password='synthetic-only')
        ComplianceAuditChainState.objects.get_or_create(singleton=1)
        self.branch = OperationalLocation.objects.create(location_type='branch', name='Synthetic Branch', code='SYNTHETIC-ISOLATION')
        self.product = Product.objects.create(code='packet_isolation', name='Synthetic packet loan')
        self.version = ProductVersion.objects.create(product=self.product, version=1,
            min_amount='1000', max_amount='100000', min_tenor=1, max_tenor=12)
        ProductVersion.objects.filter(pk=self.version.pk).update(status='published', published_at=timezone.now())
        self.version.refresh_from_db()
        ProductAvailability.objects.create(product=self.product, workflow='loan_origination', branch=self.branch, channel='portal')
        self.definition = OriginationProductDefinition.objects.create(product_version=self.version,
            product_key=self.product.code, name=self.product.name, document_type='unused-product-mirror',
            form_schema={'fields': []}, signer_rules=[{'role': 'asset_owner', 'required': True}],
            lifecycle_status='published', is_active=True)
        self.pdf = synthetic_pdf()
        self.digest = hashlib.sha256(self.pdf).hexdigest()

    def template(self, key, fields, rules=(), role='primary'):
        from django.utils import timezone
        from origination.models import OriginationDocumentTemplate, OriginationTemplateConfigurationRevision, OriginationDocumentProductEligibility
        from origination.services.origination_value_contracts import upgrade_schema
        schema = upgrade_schema({'sections': [{'key': 'details', 'label': 'Details'}],
            'fields': [{**field, 'section_key': 'details'} for field in fields]})
        config = {'document_type': key, 'version': 1, 'field_overlay_manifest': {'fields': {
            field['key']: {'context_key': field['key'], 'page_number': 1,
                'box': {'x': 10, 'y': 30 + 20 * index, 'width': 160, 'height': 15}}
            for index, field in enumerate(fields)}}, 'signature_overlay_manifest': {'slots': {
                rule['role'] + '.' + slot['key']: {'label': 'Signature', 'slot_type': slot.get('type', 'signature'),
                    'page_number': 1, 'allowed_area': {'x': 10, 'y': 150, 'width': 120, 'height': 30}}
                for rule in rules for slot in rule['slots']}}}
        document = OriginationDocumentTemplate.objects.create(document_type=key, name=key, version=1,
            document_key='primary' if role == 'primary' else key, document_role=role, status='active',
            form_schema=schema, signer_rules=list(rules), source_filename='synthetic.pdf',
            source_sha256=self.digest, source_byte_size=len(self.pdf), page_count=1,
            drive_file_id='synthetic', placement_config=config, created_by=self.actor)
        document.published_configuration_revision = OriginationTemplateConfigurationRevision.objects.create(
            template=document, revision=1, configuration=config, is_published=True,
            created_by=self.actor, published_at=timezone.now())
        document.save(update_fields=['published_configuration_revision'])
        OriginationDocumentProductEligibility.objects.create(template=document, product=self.product, created_by=self.actor)
        return document

    def test_main_identity_is_reused_and_unprinted_loan_inputs_save_and_quote(self):
        from origination.services.loan_origination import create_application, save_application_fields
        from origination.services.origination_document_catalogue import catalogue_for_product
        from origination.services.origination_value_contracts import application_input_schema
        main = self.template('synthetic-main', [
            {'key': 'applicant_name', 'label': 'Applicant', 'type': 'text'},
            {'key': 'applicant_phone', 'label': 'Phone', 'type': 'phone'}])
        support = self.template('synthetic-visit', [{'key': 'visit_notes', 'label': 'Notes', 'type': 'text'}],
            [{'role': 'borrower', 'required': True, 'identity_fields': {'name': 'applicant_name', 'phone': 'applicant_phone'},
              'slots': [{'key': 'signature', 'type': 'signature', 'required': True}]}], role='supporting')
        catalogue = catalogue_for_product(self.definition)
        self.assertTrue(catalogue['ready'], catalogue)
        self.assertIn(str(main.pk), catalogue['supporting_documents'][0]['compatible_main_ids'])
        application, _ = create_application(product_key=self.product.code, officer=self.actor,
            branch=self.branch.name, client_request_id='synthetic-packet', primary_template_id=main.pk,
            supporting_template_ids=[support.pk], expected_catalogue_revision=catalogue['catalogue_revision'])
        input_schema = application_input_schema(application)
        fields = input_schema['fields']
        self.assertEqual(sum(section['key'] == 'loan_details' for section in input_schema['sections']), 1)
        for key in ['applicant_name', 'applicant_phone', 'loan_amount', 'repayment_tenor']:
            self.assertEqual(sum(field['key'] == key for field in fields), 1)
        self.assertEqual(application.signer_rules_snapshot, [])
        self.assertEqual(application.packet_documents.get(template=support).signer_rules_snapshot[0]['role'], 'borrower')
        application = save_application_fields(application_id=application.pk, actor=self.actor,
            payload={'applicant_name': 'Synthetic Applicant', 'applicant_phone': '+254700000000',
                     'loan_amount': '5000', 'repayment_tenor': '3'},
            expected_revision=application.revision, request_id='synthetic-packet-save')
        from decimal import Decimal
        self.assertEqual(Decimal(application.form_payload['loan_amount']), Decimal('5000'))
        self.assertTrue(application.product_quote_snapshot)
        from origination.services.origination_documents import packet_signers, validate_signing_placements
        signers = packet_signers(application)
        self.assertEqual([signer['role'] for signer in signers], ['borrower'])
        self.assertEqual(signers[0]['identity']['phone'], '254700000000')
        validate_signing_placements(application, signers)
        main.refresh_from_db()
        self.assertNotIn('loan_amount', [field['key'] for field in main.form_schema['fields']])

    def test_last_signature_removal_removes_only_that_document_obligation_and_replays(self):
        from unittest.mock import patch
        from origination.services.origination_templates import save_calibration_draft
        from origination.services.origination_fields import template_form_contract
        document = self.template('signature-removal', [{'key': 'notes', 'type': 'text'}],
            [{'role': 'officer', 'required': True, 'slots': [{'key': 'signature', 'type': 'signature'},
                {'key': 'signature_date', 'type': 'date_signed', 'signature_key': 'signature'}]},
             {'role': 'borrower', 'required': True, 'slots': [{'key': 'signature', 'type': 'signature'}]}])
        document.status = 'ready'
        document.published_configuration_revision = None
        document.save(update_fields=['status', 'published_configuration_revision'])
        config = deepcopy(document.placement_config)
        config['signature_overlay_manifest']['slots'].pop('officer.signature')
        with patch('origination.services.origination_templates.load_template_source', return_value=self.pdf):
            saved = save_calibration_draft(template=document, configuration=config, actor=self.actor,
                expected_revision=1, client_request_id='synthetic-remove')
            replay = save_calibration_draft(template=document, configuration=config, actor=self.actor,
                expected_revision=1, client_request_id='synthetic-remove')
        self.assertEqual(saved.pk, replay.pk)
        document.refresh_from_db()
        self.assertEqual([rule['role'] for rule in document.signer_rules], ['borrower'])
        self.assertEqual([rule['role'] for rule in template_form_contract(document)[1]], ['borrower'])
        self.assertNotIn('officer.signature_date', saved.configuration['signature_overlay_manifest']['slots'])

    def test_removed_signing_date_does_not_return_on_signer_edit(self):
        from origination.services.document_editor import save_signers
        from origination.services.origination_templates import save_calibration_draft
        from origination.services.origination_fields import template_schema_revision
        document = self.template('date-removal', [], [{'role': 'officer', 'required': True, 'slots': [
            {'key': 'signature', 'type': 'signature'},
            {'key': 'signature_date', 'type': 'date_signed', 'signature_key': 'signature'}]}])
        document.status = 'ready'
        document.published_configuration_revision = None
        document.save(update_fields=['status', 'published_configuration_revision'])
        config = deepcopy(document.placement_config)
        config['signature_overlay_manifest']['slots'].pop('officer.signature_date')
        from unittest.mock import patch
        with patch('origination.services.origination_templates.load_template_source', return_value=self.pdf):
            saved = save_calibration_draft(template=document, configuration=config, actor=self.actor,
                expected_revision=1, client_request_id='synthetic-date-remove')
            document.refresh_from_db()
            document = save_signers(document=document, rules=document.signer_rules, actor=self.actor,
                schema_revision=template_schema_revision(document), revision=saved.revision,
                configuration=saved.configuration, request_id='synthetic-later-signer-edit')
        self.assertEqual([slot['key'] for slot in document.signer_rules[0]['slots']], ['signature'])
