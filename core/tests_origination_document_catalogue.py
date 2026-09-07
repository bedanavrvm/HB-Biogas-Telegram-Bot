import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from core.models import (
    LoanOriginationApplication,
    OperationalLocation,
    OriginationDataField,
    OriginationDocumentProductEligibility,
    OriginationDocumentTemplate,
    OriginationProductDefinition,
    OriginationTemplateConfigurationRevision,
    Product,
    ProductAvailability,
    ProductVersion,
)
from core.services.loan_origination import (
    OriginationConflict,
    OriginationError,
    create_application,
    restart_application_with_main_laf,
)
from core.services.origination_commercial_terms import (
    ensure_commercial_catalogue,
    merge_commercial_contract,
)
from core.services.origination_document_catalogue import catalogue_for_product
from core.services.origination_documents import select_documents


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

    @patch('core.api.origination_views._branch_creation_error', return_value=None)
    @patch('core.api.origination_views._capability_error', return_value=None)
    def test_public_create_rejects_cached_clients_without_catalogue_choice(
        self, _capability_error, _branch_error,
    ):
        from core.api.origination_views import portal_origination_applications

        request = RequestFactory().post(
            '/api/origination/api/applications/',
            data=json.dumps({
                'branch': self.branch.name,
                'product_key': self.definition.product_key,
                'client_request_id': 'cached-client-create',
            }),
            content_type='application/json',
        )
        request.portal_user = self.officer
        request.portal_access = None
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
