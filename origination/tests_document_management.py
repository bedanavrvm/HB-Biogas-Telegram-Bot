"""Manage documents through the same draft-owned interface used by the Mini App."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.http import JsonResponse
from django.db import close_old_connections, connection
from django.test import RequestFactory, TestCase, TransactionTestCase

from core import tests_origination_document_catalogue as fixtures
from origination.models import LoanOriginationApplication, OriginationDocumentTemplate, OriginationSigningParticipant, OriginationTemplateConfigurationRevision
from origination.services.loan_origination import OriginationConflict, OriginationError, create_application, restart_application_with_main_laf
from origination.services.origination_document_catalogue import catalogue_for_product
from origination.services.origination_document_choices import document_choices
from origination.services.origination_documents import select_documents


class ManageDocumentsTests(TestCase):
    _template = fixtures.OriginationDocumentCatalogueTests._template

    def setUp(self):
        from core.models import ComplianceAuditChainState
        ComplianceAuditChainState.objects.get_or_create(singleton=1)
        fixtures.OriginationDocumentCatalogueTests.setUp(self)

    def application(self, supporting=()):
        self.main = self._template(family='manage_main', name='Main LAF')
        self.catalogue = catalogue_for_product(self.definition)
        app, _ = create_application(product_key=self.definition.product_key, officer=self.officer,
            branch=self.branch.name, client_request_id='manage-create', primary_template_id=self.main.pk,
            supporting_template_ids=[str(item.pk) for item in supporting],
            expected_catalogue_revision=self.catalogue['catalogue_revision'])
        return app

    def select(self, app, identities, request_id='manage-select', **kwargs):
        return select_documents(application_id=app.pk, actor=self.officer,
            expected_revision=app.revision, request_id=request_id,
            supporting_template_ids=identities,
            expected_catalogue_revision=document_choices(app)['catalogue_revision'], **kwargs)

    def test_one_main_still_offers_captured_unselected_and_new_documents(self):
        captured = self._template(family='original_support', name='Original support', role='supporting', schema={'fields': []})
        app = self.application()
        new = self._template(family='new_support', name='New support', role='supporting', schema={'fields': []})
        choices = document_choices(app)
        self.assertEqual(len(choices['main_lafs']), 1)
        self.assertEqual(choices['primary_template_id'], str(self.main.pk))
        self.assertEqual({row['id'] for row in choices['supporting_documents']}, {str(captured.pk), str(new.pk)})
        app.form_payload = {'loan_amount': '25000'}
        app.save(update_fields=['form_payload'])
        updated = self.select(app, [str(new.pk)])
        self.assertEqual(updated.pk, app.pk)
        self.assertEqual(updated.form_payload, app.form_payload)
        self.assertEqual(updated.packet_documents.get(document_key='new_support').template_id, new.pk)
        self.assertFalse(updated.packet_documents.get(document_key='original_support').selected)

    def test_deselection_retains_answers_and_removes_document_evidence_requirements(self):
        support_schema = {'fields': [], 'evidence_requirements': [
            {'key': 'visit_copy', 'label': 'Visit copy', 'type': 'file', 'required': True, 'enforcement_stage': 'signing'}]}
        support = self._template(family='evidence_support', name='Evidence support', role='supporting', schema=support_schema)
        app = self.application([support])
        document = app.packet_documents.get(document_key='evidence_support')
        document.field_payload = {'note': 'Recoverable saved note'}
        document.save(update_fields=['field_payload'])
        self.assertIn('visit_copy', [row['key'] for row in app.product_terms_snapshot['requirements']])
        updated = self.select(app, [])
        self.assertNotIn('visit_copy', [row['key'] for row in updated.product_terms_snapshot['requirements']])
        restored = self.select(updated, [str(support.pk)], request_id='restore-support')
        self.assertEqual(restored.packet_documents.get(document_key='evidence_support').field_payload, document.field_payload)
        self.assertIn('visit_copy', [row['key'] for row in restored.product_terms_snapshot['requirements']])

    def test_captured_versions_are_not_upgraded_and_new_attachment_is_frozen(self):
        support = self._template(family='pinned_support', name='Pinned support', role='supporting', schema={'fields': []})
        app = self.application([support])
        OriginationDocumentTemplate.objects.filter(pk=support.pk).update(status='retired')
        successor = self._template(family='pinned_support', name='Pinned support', role='supporting', schema={'fields': []}, version=2)
        choices = document_choices(app)
        self.assertEqual([row['id'] for row in choices['supporting_documents']], [str(support.pk)])
        self.assertNotIn(str(successor.pk), [row['id'] for row in choices['supporting_documents']])
        new = self._template(family='later_support', name='Later support', role='supporting', schema={'fields': []})
        saved = self.select(app, [str(support.pk), str(new.pk)])
        self.assertEqual(saved.packet_documents.get(document_key='pinned_support').template_snapshot['version'], 1)
        self.assertEqual(saved.packet_documents.get(document_key='later_support').template_snapshot['version'], 1)

    def test_bad_ids_mixed_shapes_and_incompatible_types_are_atomic(self):
        app = self.application()
        bad = self._template(family='bad_support', name='Bad support', role='supporting',
            schema={'fields': [{'key': 'loan_amount', 'type': 'phone'}]})
        foreign = self._template(family='foreign_support', name='Foreign support', role='supporting', schema={'fields': []}, eligible=False)
        for identities in ([str(bad.pk)], [str(foreign.pk)], [str(bad.pk), str(bad.pk)]):
            with self.assertRaises(OriginationError):
                self.select(app, identities)
        with self.assertRaises(OriginationError):
            self.select(app, [], selected_keys=[])
        self.assertFalse(app.packet_documents.filter(document_role='supporting').exists())
        app.refresh_from_db()
        self.assertEqual(app.revision, 1)

    def test_stale_catalogue_revision_duplicate_retry_and_changed_retry(self):
        app = self.application()
        new = self._template(family='retry_support', name='Retry support', role='supporting', schema={'fields': []})
        token = document_choices(app)['catalogue_revision']
        with self.assertRaises(OriginationConflict):
            select_documents(application_id=app.pk, actor=self.officer, expected_revision=app.revision,
                request_id='stale', supporting_template_ids=[str(new.pk)], expected_catalogue_revision=self.catalogue['catalogue_revision'])
        saved = self.select(app, [str(new.pk)])
        replay = select_documents(application_id=app.pk, actor=self.officer, expected_revision=1,
            request_id='manage-select', supporting_template_ids=[str(new.pk)], expected_catalogue_revision=token)
        self.assertEqual(replay.revision, saved.revision)
        self.assertEqual(replay.packet_documents.filter(document_key='retry_support').count(), 1)
        with self.assertRaises(OriginationConflict):
            select_documents(application_id=app.pk, actor=self.officer, expected_revision=1,
                request_id='manage-select', supporting_template_ids=[], expected_catalogue_revision=token)

    def test_choices_endpoint_allows_owner_denies_nonowner_and_non_draft(self):
        from origination.views import portal_origination_document_choices
        app = self.application()
        request = RequestFactory().get('/')
        request.origination_user = self.officer
        with patch('origination.views._capability_error', return_value=None), patch('origination.views._application_access_error', return_value=None):
            self.assertEqual(portal_origination_document_choices(request, str(app.pk)).status_code, 200)
            request.origination_user = get_user_model().objects.create_user('another-document-officer')
            self.assertEqual(portal_origination_document_choices(request, str(app.pk)).status_code, 403)
            request.origination_user = self.officer
            app.status = 'approved'
            app.save(update_fields=['status'])
            self.assertEqual(portal_origination_document_choices(request, str(app.pk)).status_code, 400)
        with patch('origination.views._capability_error', return_value=JsonResponse({'ok': False}, status=403)):
            self.assertEqual(portal_origination_document_choices(request, str(app.pk)).status_code, 403)

    def test_changed_selection_invalidates_preview_and_preserves_required_choices(self):
        support = self._template(family='required_support', name='Required support', role='supporting', schema={'fields': []})
        app = self.application([support])
        app.packet_documents.filter(template=support).update(inclusion_mode='required')
        app.primary_previewed_revision = 1
        app.save(update_fields=['primary_previewed_revision'])
        new = self._template(family='extra_support', name='Extra support', role='supporting', schema={'fields': []})
        saved = self.select(app, [str(new.pk)])
        self.assertIsNone(saved.primary_previewed_revision)
        self.assertTrue(saved.packet_documents.get(template=support).selected)

    def test_plan_reconciliation_preserves_assignments_and_updates_slots(self):
        from origination.services.origination_signing_plans import reconcile_document_plan
        app = self.application()
        app.signing_policy_snapshot = 'all_required'
        old_config = {'role': 'officer', 'participant_key': 'officer', 'required': True,
                      'slots': [{'key': 'old', 'document_key': 'primary'}]}
        old = OriginationSigningParticipant.objects.create(application=app, role='officer',
            participant_key='officer', configuration=old_config, staff_user=self.officer)
        app.signing_plan = {'participants': [str(old.pk)]}
        app.save(update_fields=['signing_policy_snapshot', 'signing_plan'])
        new_config = {**deepcopy(old_config), 'slots': [*old_config['slots'], {'key': 'extra', 'document_key': 'support'}]}
        with patch('origination.services.origination_signing_plans.enabled', return_value=True), \
             patch('origination.services.origination_signing_plans.candidates', return_value={'officer': new_config}), \
             patch('origination.services.origination_signing_plans.default_choices', return_value=[]):
            reconcile_document_plan(app, {'officer'})
        row = app.signing_participants.get(pk=app.signing_plan['participants'][0])
        self.assertEqual(row.staff_user_id, self.officer.pk)
        self.assertEqual(row.configuration, new_config)
        old.refresh_from_db()
        self.assertEqual(old.configuration, old_config)

    def test_document_selection_rebuilds_legacy_supporting_form_from_placed_fields(self):
        self._check_dynamic_supporting_form(shared=False)

    def test_document_selection_rebuilds_shared_and_local_supporting_sections(self):
        self._check_dynamic_supporting_form(shared=True)

    def _check_dynamic_supporting_form(self, *, shared):
        from origination.services.origination_documents import save_document_fields, serialize_packet
        from origination.services.origination_value_contracts import application_input_schema, upgrade_schema
        from origination.tests_form_projection import layout
        from origination.tests_value_contracts import field, schema
        if shared:
            self.schema = upgrade_schema(self.schema)
        app = self.application()
        source = schema(field('visit_note', scope='document', required=True),
                        field('visit_phone', scope='document', type='phone'),
                        field('unused_local', scope='document', required=True),
                        field('visit_location'))
        source['sections'] = [{'key': 'visit_details', 'label': 'Visit details'}]
        for item in source['fields']:
            item['section_key'] = 'visit_details'
            if not shared:
                item.pop('value_contract')
        if not shared:
            source.pop('value_contract_version')
        support = self._template(family='dynamic_support', name='Dynamic supporting form', role='supporting', schema=source)
        config = layout('visit_note', 'visit_phone', 'visit_location')
        OriginationTemplateConfigurationRevision.objects.filter(pk=support.published_configuration_revision_id).update(configuration=config)
        app = self.select(app, [str(support.pk)])
        document = next(row for row in serialize_packet(app)['documents'] if row['key'] == 'dynamic_support')
        self.assertEqual({item['key'] for item in document['schema']['fields']}, {'visit_note', 'visit_phone', 'visit_location'})
        self.assertEqual(document['schema']['sections'][0]['label'], 'Visit details')
        self.assertIn('visit_note', document['missing_fields'])
        self.assertNotIn('unused_local', document['missing_fields'])
        if shared:
            fields = application_input_schema(app)['fields']
            self.assertEqual([item['key'] for item in fields].count('visit_location'), 1)
            self.assertIn({'key': 'visit_details', 'label': 'Visit details'}, application_input_schema(app)['sections'])
        with self.assertRaises(OriginationError):
            save_document_fields(application_id=app.pk, document_key='dynamic_support', actor=self.officer,
                payload={'visit_phone': 'invalid'}, expected_revision=app.revision, request_id='bad-phone')
        app = save_document_fields(application_id=app.pk, document_key='dynamic_support', actor=self.officer,
            payload={'visit_note': 'Synthetic visit note', 'visit_phone': '0700000000', 'visit_location': 'Synthetic place'},
            expected_revision=app.revision, request_id='save-placed-fields')
        app = self.select(app, [], request_id='remove-dynamic')
        self.assertNotIn('visit_location', {item['key'] for item in application_input_schema(app)['fields']})
        with self.assertRaises(OriginationError):
            save_document_fields(application_id=app.pk, document_key='dynamic_support', actor=self.officer,
                payload={'visit_note': 'Cannot edit removed document'}, expected_revision=app.revision, request_id='edit-removed')
        app = self.select(app, [str(support.pk)], request_id='restore-dynamic')
        document = next(row for row in serialize_packet(app)['documents'] if row['key'] == 'dynamic_support')
        self.assertEqual(document['field_payload']['visit_note'], 'Synthetic visit note')
        self.assertEqual(document['missing_fields'], [])

    def test_failed_restart_keeps_source_and_completed_retry_ignores_later_catalogue_changes(self):
        app = self.application()
        app.form_payload = {'loan_amount': '27000'}
        app.save(update_fields=['form_payload'])
        alternative = self._template(family='alternate_main', name='Alternative Main LAF')
        args = dict(application_id=app.pk, officer=self.officer, primary_template_id=str(alternative.pk),
            supporting_template_ids=[], expected_revision=app.revision,
            expected_catalogue_revision=document_choices(app)['catalogue_revision'], client_request_id='blank-restart')
        with patch('origination.services.loan_origination._record_event', side_effect=OriginationError('Synthetic write failure')):
            with self.assertRaises(OriginationError):
                restart_application_with_main_laf(**args)
        app.refresh_from_db()
        self.assertEqual(app.status, 'draft')
        self.assertEqual(LoanOriginationApplication.objects.count(), 1)
        new, replayed = restart_application_with_main_laf(**args)
        self.assertFalse(replayed)
        self.assertNotIn('loan_amount', new.form_payload)
        self.assertFalse(new.requirement_evidence_files.exists())
        new.form_payload = {'loan_amount': '31000'}
        new.save(update_fields=['form_payload'])
        OriginationDocumentTemplate.objects.filter(pk=alternative.pk).update(status='retired')
        self.definition.is_active = False
        self.definition.save(update_fields=['is_active'])
        retry, replayed = restart_application_with_main_laf(**args)
        self.assertTrue(replayed)
        self.assertEqual(retry.pk, new.pk)
        self.assertEqual(retry.form_payload, {'loan_amount': '31000'})
        with self.assertRaises(OriginationConflict):
            restart_application_with_main_laf(**{**args, 'supporting_template_ids': ['different']})

    def test_old_restart_client_must_confirm_blank_restart(self):
        from origination.views import portal_origination_restart
        app = self.application()
        request = RequestFactory().post('/', data=json.dumps({'revision': app.revision}), content_type='application/json')
        request.origination_user = self.officer
        with patch('origination.views._capability_error', return_value=None), \
             patch('origination.views._application_access_error', return_value=None):
            response = portal_origination_restart(request, str(app.pk))
        self.assertEqual(response.status_code, 428)
        app.refresh_from_db()
        self.assertEqual(app.status, 'draft')

    def test_plan_reconciliation_keeps_admin_excluded_optional_people_excluded(self):
        from origination.services.origination_signing_plans import reconcile_document_plan
        app = self.application()
        app.signing_policy_snapshot = 'all_required'
        config = {'role': 'officer', 'participant_key': 'officer', 'required': True, 'slots': []}
        old = OriginationSigningParticipant.objects.create(application=app, role='officer',
            participant_key='officer', configuration=config, staff_user=self.officer)
        app.signing_plan = {'participants': [str(old.pk)]}
        optional = {'role': 'witness', 'participant_key': 'optional_witness', 'slots': []}
        required = {'role': 'guarantor', 'participant_key': 'new_guarantor', 'required': True, 'slots': []}
        with patch('origination.services.origination_signing_plans.enabled', return_value=True), \
             patch('origination.services.origination_signing_plans.candidates', return_value={'officer': config, 'optional_witness': optional, 'new_guarantor': required}), \
             patch('origination.services.origination_signing_plans.default_choices', return_value=[{'participant_key': 'optional_witness'}, {'participant_key': 'new_guarantor'}]):
            reconcile_document_plan(app, {'officer', 'optional_witness'})
        self.assertEqual(set(app.signing_participants.filter(pk__in=app.signing_plan['participants']).values_list('participant_key', flat=True)), {'officer', 'new_guarantor'})


@skipUnless(connection.vendor == 'postgresql', 'Row locks require PostgreSQL.')
class DocumentSelectionConcurrencyTests(TransactionTestCase):
    setUp = ManageDocumentsTests.setUp
    _template = fixtures.OriginationDocumentCatalogueTests._template
    application = ManageDocumentsTests.application

    def test_two_selection_writes_allow_one_revision_winner_and_no_duplicate_attachment(self):
        app = self.application()
        support = self._template(family='concurrent_support', name='Concurrent support', role='supporting', schema={'fields': []})
        token = document_choices(app)['catalogue_revision']
        barrier = Barrier(2)

        def select(index):
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=self.officer.pk)
                barrier.wait(timeout=15)
                select_documents(application_id=app.pk, actor=actor, expected_revision=1,
                    request_id=f'concurrent-{index}', supporting_template_ids=[str(support.pk)], expected_catalogue_revision=token)
                return 'saved'
            except OriginationConflict:
                return 'conflict'
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(pool.map(select, range(2)), ['saved', 'conflict'])
        app.refresh_from_db()
        self.assertEqual(app.revision, 2)
        self.assertEqual(app.packet_documents.filter(template=support).count(), 1)
