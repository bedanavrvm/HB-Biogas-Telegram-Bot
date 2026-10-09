import json
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection
from django.test import RequestFactory, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from origination.models import (
    LoanOriginationApplication,
    OriginationDataField,
    OriginationDocumentProductEligibility,
    OriginationDocumentTemplate,
    OriginationProductDefinition,
    OriginationTemplateConfigurationRevision,
)
from core.models import OperationalLocation, Product, ProductAvailability, ProductVersion
from origination.services.loan_origination import (
    OriginationConflict,
    OriginationError,
    create_application,
    restart_application_with_main_laf,
)
from origination.services.origination_commercial_terms import (
    ensure_commercial_catalogue,
    merge_commercial_contract,
)
from origination.services.origination_document_catalogue import catalogue_for_product
from origination.services.origination_documents import select_documents


class OriginationDocumentCatalogueTests(TestCase):
    def setUp(self):
        self.officer = get_user_model().objects.create_user(username='catalogue-officer')
        self.branch = OperationalLocation.objects.create(
            location_type='branch', name='Catalogue Branch', code='CATALOGUE-BRANCH',
        )
        self.product_record = Product.objects.create(name='Catalogue Loan', code='catalogue_loan')
        self.product_version = ProductVersion.objects.create(
            product=self.product_record, version=1,
            min_amount='1000', max_amount='500000', min_tenor=1, max_tenor=24,
        )
        ProductVersion.objects.filter(pk=self.product_version.pk).update(
            status=ProductVersion.STATUS_PUBLISHED,
            published_at=timezone.now(),
        )
        self.product_version.refresh_from_db()
        ProductAvailability.objects.create(
            product=self.product_record, branch=self.branch,
            workflow='loan_origination', channel='portal', active=True,
        )
        fields = ensure_commercial_catalogue(actor=self.officer)
        self.schema = merge_commercial_contract(
            {'_revision': 0, 'sections': [], 'fields': []}, fields=fields,
        )
        self.signers = [{'role': 'customer'}, {'role': 'officer'}]
        self.definition = OriginationProductDefinition.objects.create(
            product_version=self.product_version,
            product_key=self.product_record.code, name=self.product_record.name,
            version=1, form_schema=self.schema, signer_rules=self.signers,
            document_type='legacy-only', lifecycle_status='published', is_active=True,
        )

    def _template(self, *, family, name, role='primary', schema=None, eligible=True, version=1):
        template = OriginationDocumentTemplate.objects.create(
            product_definition=None,
            document_key='primary' if role == 'primary' else family,
            document_role=role,
            inclusion_mode='required' if role == 'primary' else 'optional',
            officer_selectable=role != 'primary',
            form_schema=self.schema if schema is None else schema,
            signer_rules=self.signers if role == 'primary' else [],
            document_type=family, name=name, version=version, status='active',
            source_filename=f'{family}.pdf', source_sha256=(family[0] * 64),
            source_byte_size=100, page_count=1,
            placement_config={'field_overlay_manifest': {'fields': {'x': {'context_key': 'loan_amount'}}}},
            drive_file_id=f'drive-{family}', created_by=self.officer,
        )
        revision = OriginationTemplateConfigurationRevision.objects.create(
            template=template, revision=1, configuration=template.placement_config,
            is_published=True, created_by=self.officer, published_at=timezone.now(),
        )
        OriginationDocumentTemplate.objects.filter(pk=template.pk).update(
            published_configuration_revision=revision,
        )
        template.refresh_from_db()
        if eligible:
            OriginationDocumentProductEligibility.objects.create(
                template=template, product=self.product_record, created_by=self.officer,
            )
        return template

    def test_empty_allowlist_keeps_document_and_product_unavailable(self):
        self._template(family='private_laf', name='Private LAF', eligible=False)
        result = catalogue_for_product(self.definition)
        self.assertFalse(result['ready'])
        self.assertEqual(result['main_lafs'], [])
        self.assertIn('No published compatible Main LAF', result['reasons'][0])

    def test_guided_choices_include_published_documents_before_product_assignment(self):
        from origination.origination_setup_forms import SetupCatalogueSelectionForm
        standalone = self._template(family='standalone', name='Standalone LAF', eligible=False)
        shared = self._template(family='shared', name='Shared LAF', eligible=False)
        other = Product.objects.create(code='other_catalogue', name='Other product')
        OriginationDocumentProductEligibility.objects.create(template=shared, product=other)
        choices = SetupCatalogueSelectionForm(definition=self.definition).fields['templates'].queryset
        self.assertIn(standalone.pk, choices.values_list('pk', flat=True))
        self.assertIn(shared.pk, choices.values_list('pk', flat=True))
        self.assertFalse(catalogue_for_product(self.definition)['ready'])
        self.assertFalse(standalone.product_eligibilities.exists())

    def test_guided_choices_exclude_retired_failed_and_unpublished_documents(self):
        from origination.origination_setup_forms import SetupCatalogueSelectionForm
        for index, status in enumerate(['retired', 'upload_failed', 'ready', 'active']):
            with self.subTest(status=status):
                document = self._template(family=f'hidden_{index}', name=status, eligible=False)
                OriginationDocumentTemplate.objects.filter(pk=document.pk).update(
                    status=status, published_configuration_revision=None,
                )
                choices = SetupCatalogueSelectionForm(definition=self.definition).fields['templates'].queryset
                self.assertNotIn(document.pk, choices.values_list('pk', flat=True))

    def test_attaching_published_laf_retains_document_and_existing_application_snapshots(self):
        from origination.services.origination_setup_documents import select_documents as attach
        original = self._template(family='original_laf', name='Original LAF')
        catalogue = catalogue_for_product(self.definition)
        application, _ = create_application(
            product_key=self.definition.product_key, officer=self.officer, branch=self.branch.name,
            client_request_id='before-attachment', primary_template_id=original.pk,
            expected_catalogue_revision=catalogue['catalogue_revision'], supporting_template_ids=[],
        )
        snapshot = deepcopy(application.schema_snapshot)
        packet = application.packet_documents.get(template=original)
        packet_snapshot = deepcopy(packet.template_snapshot)
        document = self._template(family='new_published', name='Published LAF', eligible=False)
        before = {key: deepcopy(getattr(document, key)) for key in (
            'source_sha256', 'drive_file_id', 'form_schema', 'signer_rules', 'placement_config',
            'published_configuration_revision_id', 'status', 'version',
        )}
        actor = get_user_model().objects.create_superuser('attach-admin', 'qa@example.test', 'test-only')
        count = OriginationDocumentTemplate.objects.count()
        with patch('origination.services.origination_templates.load_template_source',
                   side_effect=AssertionError('Attachment must not contact Drive')):
            selected = attach(definition=self.definition, templates=[document], actor=actor, request_id='attach')
        self.assertEqual([item.pk for item in selected], [document.pk])
        self.assertEqual(OriginationDocumentTemplate.objects.count(), count)
        document.refresh_from_db()
        for key, value in before.items():
            self.assertEqual(getattr(document, key), value, key)
        self.assertEqual(document.configuration_revisions.count(), 1)
        self.assertTrue(document.product_eligibilities.filter(product=self.product_record).exists())
        self.assertIn(str(document.pk), [item['id'] for item in catalogue_for_product(self.definition)['main_lafs']])
        application.refresh_from_db()
        packet.refresh_from_db()
        self.assertEqual(application.schema_snapshot, snapshot)
        self.assertEqual(packet.template_snapshot, packet_snapshot)

    def test_attachment_retry_is_actor_and_content_bound(self):
        from origination.services.origination_setup_documents import select_documents as attach
        document = self._template(family='retry_laf', name='Retry LAF', eligible=False)
        actor = get_user_model().objects.create_superuser('retry-admin', 'qa@example.test', 'test-only')
        arguments = dict(definition=self.definition, templates=[document], actor=actor, request_id='attach-retry')
        attach(**arguments)
        attach(**arguments)
        self.assertEqual(document.product_eligibilities.count(), 1)
        self.assertEqual(document.events.filter(action='setup_product_connected').count(), 1)
        self.assertEqual(self.definition.events.filter(action='setup_documents_selected').count(), 1)
        with self.assertRaises(ValidationError):
            attach(**{**arguments, 'templates': []})
        other_actor = get_user_model().objects.create_superuser('other-admin', 'qa2@example.test', 'test-only')
        with self.assertRaises(ValidationError):
            attach(**{**arguments, 'actor': other_actor})

    def test_incompatible_published_attachment_rolls_back_the_whole_selection(self):
        from origination.services.origination_setup_documents import select_documents as attach
        compatible = self._template(family='compatible', name='Compatible LAF', eligible=False)
        incompatible = self._template(family='incompatible', name='Wrong fields', schema={'fields': []}, eligible=False)
        actor = get_user_model().objects.create_superuser('compat-admin', 'qa@example.test', 'test-only')
        with self.assertRaises(ValidationError):
            attach(definition=self.definition, templates=[compatible, incompatible], actor=actor, request_id='invalid')
        self.assertFalse(compatible.product_eligibilities.exists())
        self.assertFalse(incompatible.product_eligibilities.exists())
        self.assertFalse(self.definition.events.filter(action='setup_documents_selected').exists())
        self.assertEqual(OriginationDocumentTemplate.objects.count(), 2)

    def test_attachment_rechecks_retired_document_and_product_and_authority(self):
        from origination.services.origination_setup_documents import select_documents as attach
        document = self._template(family='stale_laf', name='Stale LAF', eligible=False)
        actor = get_user_model().objects.create_superuser('stale-admin', 'qa@example.test', 'test-only')
        with self.assertRaises(ValidationError):
            attach(definition=self.definition, templates=[document], actor=self.officer, request_id='not-authorized')
        OriginationDocumentTemplate.objects.filter(pk=document.pk).update(status='retired')
        with self.assertRaises(ValidationError):
            attach(definition=self.definition, templates=[document], actor=actor, request_id='stale-document')
        OriginationProductDefinition.objects.filter(pk=self.definition.pk).update(lifecycle_status='retired')
        with self.assertRaises(ValidationError):
            attach(definition=self.definition, templates=[], actor=actor, request_id='stale-product')
        self.assertFalse(document.product_eligibilities.exists())

    def test_catalogue_label_explains_an_unassigned_active_document(self):
        from django.contrib import admin
        from origination.admin import OriginationDocumentTemplateAdmin
        document = self._template(family='unassigned', name='Unassigned LAF', eligible=False)
        model_admin = OriginationDocumentTemplateAdmin(OriginationDocumentTemplate, admin.site)
        self.assertEqual(model_admin.eligible_products_summary(document), 'No products assigned')

    def _legacy_main_and_successor(self):
        main = self._template(family='legacy_contract', name='Legacy Main LAF')
        self.definition.signer_rules[0]['slots'] = [{'key': 'signature', 'type': 'signature'}]
        self.definition.lifecycle_status = 'retired'
        self.definition.is_active = False
        self.definition.save(update_fields=['signer_rules', 'lifecycle_status', 'is_active'])
        OriginationDocumentTemplate.objects.filter(pk=main.pk).update(
            product_definition=self.definition, form_schema={}, signer_rules=[],
        )
        main.refresh_from_db()
        successor = OriginationProductDefinition.objects.create(
            product_version=self.product_version, product_key=self.definition.product_key,
            name=self.definition.name, version=2, form_schema=self.schema,
            signer_rules=[{'role': 'customer'}, {'role': 'officer'}],
            document_type=self.definition.document_type, lifecycle_status='published', is_active=True,
        )
        return main, successor

    def test_published_legacy_main_remains_available_and_freezes_original_signer_slots(self):
        main, successor = self._legacy_main_and_successor()
        catalogue = catalogue_for_product(successor)
        self.assertTrue(catalogue['ready'], catalogue)
        application, _ = create_application(
            product_key=successor.product_key, officer=self.officer, branch=self.branch.name,
            client_request_id='legacy-contract-create', primary_template_id=main.pk,
            supporting_template_ids=[], expected_catalogue_revision=catalogue['catalogue_revision'],
        )
        self.assertEqual(application.signer_rules_snapshot[0]['slots'], self.definition.signer_rules[0]['slots'])
        document = application.packet_documents.get(template=main)
        self.assertEqual(document.signer_rules_snapshot[0]['slots'], self.definition.signer_rules[0]['slots'])
        main.refresh_from_db()
        self.assertEqual(main.form_schema, {})
        self.assertEqual(main.signer_rules, [])
        self.assertEqual(main.status, 'active')

    def test_legacy_main_still_rejects_conflicting_supporting_fields(self):
        from origination.services.origination_document_catalogue import validate_document_combination
        main, _ = self._legacy_main_and_successor()
        support = self._template(family='conflicting_legacy_support', name='Conflict', role='supporting',
                                 schema={'fields': [{'key': 'loan_amount', 'type': 'text'}]})
        with self.assertRaisesRegex(OriginationError, 'conflicting canonical field types'):
            validate_document_combination(main, [support])

    def test_legacy_main_does_not_borrow_new_product_signer_roles(self):
        main, successor = self._legacy_main_and_successor()
        successor.signer_rules = [*successor.signer_rules, {'role': 'branch_manager'}]
        catalogue = catalogue_for_product(successor)
        # The selected Main LAF owns its signers, not a product's stale mirror.
        self.assertTrue(catalogue['ready'], catalogue)
        from origination.services.origination_fields import template_form_contract
        _schema, signers = template_form_contract(main)
        self.assertNotIn('branch_manager', [item['role'] for item in signers])

    def test_retired_product_legacy_document_has_idempotent_independent_editable_exit(self):
        main, successor = self._legacy_main_and_successor()
        application, _ = create_application(
            product_key=successor.product_key, officer=self.officer, branch=self.branch.name,
            client_request_id='legacy-before-versioning', primary_template_id=main.pk,
            supporting_template_ids=[],
        )
        original_schema = application.schema_snapshot
        original_signers = application.signer_rules_snapshot
        actor = get_user_model().objects.create_superuser('legacy-document-admin', 'qa@example.test', 'x')
        self.client.force_login(actor)
        page = self.client.get(reverse('admin:origination_originationdocumenttemplate_change', args=[main.pk]))
        url = reverse('admin:origination_originationdocumenttemplate_create_editable_version', args=[main.pk])
        self.assertEqual(page.context['origination_create_editable_template_url'], url)
        self.assertContains(page, 'Create editable version')
        self.assertEqual(self.client.get(url).status_code, 405)
        response = self.client.post(url)
        editable = OriginationDocumentTemplate.objects.get(document_type=main.document_type, status='ready')
        self.assertRedirects(response, reverse('admin:origination_originationdocumenttemplate_calibrate',
                                            args=[editable.pk]), fetch_redirect_response=False)
        self.client.post(url)
        self.assertEqual(OriginationDocumentTemplate.objects.filter(document_type=main.document_type, status='ready').count(), 1)
        self.assertIsNone(editable.product_definition_id)
        self.assertEqual(editable.form_schema, self.definition.form_schema)
        self.assertEqual(editable.signer_rules, self.definition.signer_rules)
        self.assertEqual(editable.drive_file_id, main.drive_file_id)
        self.assertTrue(editable.eligible_products.filter(pk=self.product_record.pk).exists())
        main.refresh_from_db()
        self.assertEqual(main.status, 'active')
        self.assertEqual(main.form_schema, {})
        self.assertEqual(main.product_definition_id, self.definition.pk)
        application.refresh_from_db()
        self.assertEqual(application.schema_snapshot, original_schema)
        self.assertEqual(application.signer_rules_snapshot, original_signers)
        self.assertEqual(application.packet_documents.get(document_role='primary').template_id, main.pk)

    def test_catalogue_selected_version_action_and_alignment_offer_legacy_exit(self):
        from django.contrib import admin
        from origination.admin import OriginationDocumentTemplateAdmin
        main, _ = self._legacy_main_and_successor()
        actor = get_user_model().objects.create_superuser('legacy-action-admin', 'qa@example.test', 'x')
        self.client.force_login(actor)
        request = RequestFactory().get('/admin/')
        request.user = actor
        model_admin = OriginationDocumentTemplateAdmin(OriginationDocumentTemplate, admin.site)
        self.assertIn('create_editable_selected_template', model_admin.get_actions(request))
        response = self.client.post(reverse('admin:origination_originationdocumenttemplate_changelist'), {
            'action': 'create_editable_selected_template', '_selected_action': str(main.pk), 'index': '0',
        })
        editable = OriginationDocumentTemplate.objects.get(document_type=main.document_type, status='ready')
        self.assertRedirects(response, reverse('admin:origination_originationdocumenttemplate_calibrate',
                                            args=[editable.pk]), fetch_redirect_response=False)
        preview = self.client.get(reverse('admin:origination_originationdocumenttemplate_calibrate', args=[main.pk]))
        self.assertEqual(preview.context['calibration_create_editable_url'], reverse(
            'admin:origination_originationdocumenttemplate_create_editable_version', args=[main.pk]))

    @patch('origination.views._branch_creation_error', return_value=None)
    @patch('origination.views._capability_error', return_value=None)
    def test_public_create_rejects_cached_clients_without_catalogue_choice(
        self, _capability_error, _branch_error,
    ):
        from origination.views import portal_origination_applications

        request = RequestFactory().post(
            '/api/origination/api/applications/',
            data=json.dumps({
                'branch': self.branch.name,
                'product_key': self.definition.product_key,
                'client_request_id': 'cached-client-create',
            }),
            content_type='application/json',
        )
        request.origination_user = self.officer
        request.origination_access = None
        response = portal_origination_applications(request)
        payload = json.loads(response.content)

        self.assertEqual(response.status_code, 428)
        self.assertTrue(payload['outdated_client'])
        self.assertFalse(LoanOriginationApplication.objects.exists())

    def test_explicit_selection_drives_schema_and_freezes_supporting_candidates(self):
        main = self._template(family='catalogue_laf', name='Catalogue LAF')
        selected = self._template(
            family='selected_support', name='Selected support', role='supporting',
            schema={'fields': [{'key': 'selected_note', 'type': 'text'}]},
        )
        unselected = self._template(
            family='other_support', name='Other support', role='supporting',
            schema={'fields': [{'key': 'other_note', 'type': 'text'}]},
        )
        catalogue = catalogue_for_product(self.definition)
        application, replayed = create_application(
            product_key=self.definition.product_key, officer=self.officer,
            branch=self.branch.name, client_request_id='catalogue-create-1',
            primary_template_id=main.pk, supporting_template_ids=[selected.pk],
            expected_catalogue_revision=catalogue['catalogue_revision'],
        )
        self.assertFalse(replayed)
        self.assertEqual(application.schema_snapshot['commercial_contract_version'], 2)
        documents = {str(item.template_id): item for item in application.packet_documents.all()}
        self.assertTrue(documents[str(main.pk)].selected)
        self.assertTrue(documents[str(selected.pk)].selected)
        self.assertFalse(documents[str(unselected.pk)].selected)
        self.assertTrue(all(item.assignment_id is None for item in documents.values()))

    def test_creation_request_id_is_bound_to_document_digest(self):
        first = self._template(family='first_laf', name='First LAF')
        second = self._template(family='second_laf', name='Second LAF')
        catalogue = catalogue_for_product(self.definition)
        application, _ = create_application(
            product_key=self.definition.product_key, officer=self.officer,
            branch=self.branch.name, client_request_id='catalogue-digest-1',
            primary_template_id=first.pk, supporting_template_ids=[],
            expected_catalogue_revision=catalogue['catalogue_revision'],
        )
        replay, replayed = create_application(
            product_key=self.definition.product_key, officer=self.officer,
            branch=self.branch.name, client_request_id='catalogue-digest-1',
            primary_template_id=first.pk, supporting_template_ids=[],
            expected_catalogue_revision=catalogue['catalogue_revision'],
        )
        self.assertTrue(replayed)
        self.assertEqual(replay.pk, application.pk)
        with self.assertRaises(OriginationConflict):
            create_application(
                product_key=self.definition.product_key, officer=self.officer,
                branch=self.branch.name, client_request_id='catalogue-digest-1',
                primary_template_id=second.pk, supporting_template_ids=[],
                expected_catalogue_revision=catalogue['catalogue_revision'],
            )

    def test_supporting_type_conflict_is_rejected_on_toggle(self):
        main = self._template(family='conflict_laf', name='Conflict LAF')
        conflict = self._template(
            family='conflict_support', name='Conflict support', role='supporting',
            schema={'fields': [{'key': 'loan_amount', 'type': 'text'}]},
        )
        catalogue = catalogue_for_product(self.definition)
        application, _ = create_application(
            product_key=self.definition.product_key, officer=self.officer,
            branch=self.branch.name, client_request_id='catalogue-conflict-create',
            primary_template_id=main.pk, supporting_template_ids=[],
            expected_catalogue_revision=catalogue['catalogue_revision'],
        )
        with self.assertRaisesRegex(OriginationError, 'conflicting canonical field types'):
            select_documents(
                application_id=application.pk, actor=self.officer,
                selected_keys=[conflict.document_key], expected_revision=application.revision,
                request_id='catalogue-conflict-toggle',
            )
        application.refresh_from_db()
        self.assertFalse(application.packet_documents.get(template=conflict).selected)

    def test_open_draft_keeps_original_supporting_version_after_republication(self):
        main = self._template(family='race_laf', name='Race LAF')
        support_v1 = self._template(
            family='race_support', name='Race support', role='supporting',
            schema={'fields': [{'key': 'race_note', 'type': 'text'}]},
        )
        catalogue = catalogue_for_product(self.definition)
        application, _ = create_application(
            product_key=self.definition.product_key, officer=self.officer,
            branch=self.branch.name, client_request_id='catalogue-race-create',
            primary_template_id=main.pk, supporting_template_ids=[],
            expected_catalogue_revision=catalogue['catalogue_revision'],
        )
        OriginationDocumentTemplate.objects.filter(pk=support_v1.pk).update(status='retired')
        support_v2 = self._template(
            family='race_support', name='Race support', role='supporting', version=2,
            schema={'fields': [{'key': 'race_note', 'type': 'text'}]},
        )
        frozen = application.packet_documents.get(document_key='race_support')
        self.assertEqual(frozen.template_id, support_v1.pk)
        self.assertNotEqual(frozen.template_id, support_v2.pk)

    def test_restart_prefills_matching_values_and_cancels_source(self):
        first = self._template(family='restart_first', name='Restart First')
        second_schema = self.schema
        second = self._template(family='restart_second', name='Restart Second', schema=second_schema)
        catalogue = catalogue_for_product(self.definition)
        source, _ = create_application(
            product_key=self.definition.product_key, officer=self.officer,
            branch=self.branch.name, client_request_id='restart-source',
            primary_template_id=first.pk, supporting_template_ids=[],
            expected_catalogue_revision=catalogue['catalogue_revision'],
        )
        source.form_payload = {'loan_amount': '25000', 'repayment_tenor': '6'}
        source.save(update_fields=['form_payload'])
        with self.assertRaisesRegex(OriginationError, 'different Main LAF'):
            restart_application_with_main_laf(
                application_id=source.pk, officer=self.officer,
                primary_template_id=first.pk, supporting_template_ids=[],
                expected_revision=source.revision,
                expected_catalogue_revision=catalogue['catalogue_revision'],
                client_request_id='restart-same-main',
            )
        replacement, replayed = restart_application_with_main_laf(
            application_id=source.pk, officer=self.officer,
            primary_template_id=second.pk, supporting_template_ids=[],
            expected_revision=source.revision,
            expected_catalogue_revision=catalogue['catalogue_revision'],
            client_request_id='restart-replacement',
        )
        source.refresh_from_db()
        self.assertFalse(replayed)
        self.assertEqual(source.status, source.STATUS_CANCELLED)
        self.assertEqual(replacement.supersedes_application_id, source.pk)
        self.assertEqual(replacement.form_payload['loan_amount'], '25000')
        self.assertEqual(replacement.form_payload['repayment_tenor'], '6')
        self.assertFalse(replacement.requirement_evidence_files.exists())
        self.assertFalse(replacement.signing_packages.exists())
        replay, was_replayed = restart_application_with_main_laf(
            application_id=source.pk, officer=self.officer,
            primary_template_id=second.pk, supporting_template_ids=[],
            expected_revision=source.revision,
            expected_catalogue_revision=catalogue['catalogue_revision'],
            client_request_id='restart-replacement',
        )
        self.assertTrue(was_replayed)
        self.assertEqual(replay.pk, replacement.pk)
        with self.assertRaisesRegex(OriginationError, 'already cancelled'):
            restart_application_with_main_laf(
                application_id=source.pk, officer=self.officer,
                primary_template_id=second.pk, supporting_template_ids=[],
                expected_revision=source.revision,
                expected_catalogue_revision=catalogue['catalogue_revision'],
                client_request_id='restart-again',
            )


@skipUnless(connection.vendor == 'postgresql', 'PostgreSQL row locks are required.')
class OriginationDocumentAttachmentConcurrencyTests(TransactionTestCase):
    _template = OriginationDocumentCatalogueTests._template

    def setUp(self):
        OriginationDocumentCatalogueTests.setUp(self)
        self.actor = get_user_model().objects.create_superuser('concurrent-admin', 'qa@example.test', 'test-only')

    def test_concurrent_first_attachment_has_one_connection_and_receipt(self):
        from origination.services.origination_setup_documents import select_documents as attach
        document = self._template(family='concurrent_laf', name='Concurrent LAF', eligible=False)
        barrier = Barrier(2)

        def submit():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                selected = attach(definition=self.definition, templates=[document], actor=self.actor, request_id='first-attach')
                return [item.pk for item in selected]
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as workers:
            first, second = workers.submit(submit), workers.submit(submit)
            self.assertEqual(first.result(timeout=30), [document.pk])
            self.assertEqual(second.result(timeout=30), [document.pk])
        self.assertEqual(document.product_eligibilities.count(), 1)
        self.assertEqual(document.events.filter(action='setup_product_connected').count(), 1)
        self.assertEqual(self.definition.events.filter(action='setup_documents_selected').count(), 1)
        self.assertEqual(OriginationDocumentTemplate.objects.count(), 1)
