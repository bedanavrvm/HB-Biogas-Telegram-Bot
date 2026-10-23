"""Synthetic placement-driven forms, without provider or catalogue lookups."""
from copy import deepcopy
from types import SimpleNamespace as N

from django.test import SimpleTestCase, TestCase
from unittest.mock import patch

from origination.services.origination_value_contracts import (
    application_input_schema, packet_contract, project_document_schema,
)
from origination.tests_value_contracts import field, schema


def layout(*keys):
    return {'field_overlay_manifest': {'fields': {
        str(index): {'context_key': key, 'page_number': 1,
                     'box': {'x': 10, 'y': 10, 'width': 100, 'height': 20}}
        for index, key in enumerate(keys)
    }}}


class Rows(list):
    def all(self):
        return self


def application(main, configuration, *documents, status='draft'):
    return N(schema_snapshot=main, template_configuration_snapshot=configuration,
             signer_rules_snapshot=[], product_terms_snapshot={}, status=status,
             packet_documents=Rows(documents), events=N(filter=lambda **kw: N(exists=lambda: False)))


class FormProjectionTests(SimpleTestCase):
    def test_unplaced_required_fields_and_empty_sections_disappear(self):
        source = schema(field('purpose', required=True), field('notes', required=True))
        source['sections'].append({'key': 'empty', 'label': 'Empty'})
        before = deepcopy(source)
        result = project_document_schema(source, layout('purpose'))
        self.assertEqual([item['key'] for item in result['fields']], ['purpose'])
        self.assertEqual([item['key'] for item in result['sections']], ['applicant'])
        self.assertEqual(source, before)

    def test_editable_application_without_any_placement_does_not_fall_back_to_full_schema(self):
        source = schema(field('purpose'), field('guarantor_phone'))
        self.assertEqual(application_input_schema(application(source, {}))['fields'], [])

    def test_invalid_and_duplicate_placements_do_not_create_inputs(self):
        config = layout('purpose', 'purpose', 'notes')
        config['field_overlay_manifest']['fields']['2']['box']['width'] = 0
        result = project_document_schema(schema(field('purpose'), field('notes')), config)
        self.assertEqual([item['key'] for item in result['fields']], ['purpose'])

    def test_unplaced_identity_and_signer_contact_never_become_inputs(self):
        source = schema(field('applicant_full_name'), field('applicant_phone'),
                        field('guarantor_name'), field('guarantor_phone'), field('notes'))
        result = project_document_schema(source, layout(), signer_rules=[{
            'role': 'guarantor_1', 'identity_fields': {'name': 'guarantor_name', 'phone': 'guarantor_phone'},
        }])
        self.assertEqual(result['fields'], [])
        self.assertEqual(result['sections'], [])

    def test_calculations_do_not_make_unplaced_dependencies_visible(self):
        source = schema(field('business_sales_amount', type='money'), field('business_other_income_lines'),
                        field('business_rent_expense', type='money'), field('notes'),
                        field('business_total_income', source='calculated', binding='total.business_total_income'))
        result = project_document_schema(source, layout('business_total_income'))
        self.assertEqual({item['key'] for item in result['fields']},
                         {'business_total_income'})

    def test_unplaced_lending_inputs_and_generated_fields_are_not_inputs(self):
        source = schema(field('loan_amount', type='money'), field('repayment_tenor', type='number'), field('notes'),
                        field('total_interest_amount', source='calculated', binding='quote.total_interest_amount'))
        source['commercial_contract_version'] = 2
        app = application(source, layout('total_interest_amount'))
        result = application_input_schema(app)
        self.assertEqual(result['fields'], [])
        self.assertEqual(result['sections'], [])

    def test_repeating_table_uses_placed_row_capacity_without_changing_original(self):
        rows = field('people', type='repeating_group')
        rows['structure'] = {'min_items': 0, 'max_items': 10, 'columns': [{'key': 'name', 'type': 'text'}]}
        config = layout('people')
        config['field_overlay_manifest']['fields']['0'].update(render_as='repeating_table', rows=2)
        result = project_document_schema(schema(rows), config)
        self.assertEqual(result['fields'][0]['structure']['max_items'], 2)
        self.assertEqual(rows['structure']['max_items'], 10)

    def test_unplaced_parent_and_identity_fields_have_no_visibility_exception(self):
        from origination.services.origination_value_contracts import annotate_form_fields
        county = field('county', type='county')
        location = field('sub_county', type='sub_county')
        location['validation'] = {'parent_field': 'county'}
        source = schema(county, location, field('notes'))
        result = project_document_schema(source, layout('sub_county'))
        self.assertEqual({item['key'] for item in result['fields']}, {'sub_county'})
        annotated = annotate_form_fields([{'key': 'applicant_full_name'}, {'key': 'notes'}], schema(field('applicant_full_name'), field('notes')))
        self.assertEqual(annotated[0]['form_essential_reason'], '')
        self.assertEqual(annotated[1]['form_essential_reason'], '')

    def test_unfinished_repeating_placement_does_not_break_editor_metadata(self):
        from origination.services.origination_value_contracts import annotate_form_fields
        rows = field('rows', type='repeating_group')
        rows['structure'] = {'min_items': 2, 'max_items': 3, 'columns': []}
        config = layout('rows')
        config['field_overlay_manifest']['fields']['0'].update(render_as='repeating_table', rows=1)
        self.assertEqual(len(annotate_form_fields([{'key': 'rows'}], schema(rows), configuration=config)), 1)

    def test_selected_supporting_fields_are_shared_once_and_deselection_removes_them(self):
        main = schema(field('purpose'), field('shared_note', required=True))
        support = N(document_key='support', selected=True, applicable=True, document_role='supporting',
                    schema_snapshot=schema(field('shared_note'), field('private_note', scope='document'), field('unused')),
                    signer_rules_snapshot=[], template_snapshot={'configuration': layout('shared_note', 'private_note')})
        app = application(main, layout('purpose'), support)
        self.assertEqual({item['key'] for item in application_input_schema(app)['fields']}, {'purpose', 'shared_note'})
        contract = packet_contract(app)
        self.assertFalse(contract['fields']['shared_note']['required'])
        self.assertEqual(set(contract['documents']['support']), {'private_note'})
        support.selected = False
        self.assertEqual({item['key'] for item in application_input_schema(app)['fields']}, {'purpose'})

    def test_old_submitted_forms_keep_original_interpretation(self):
        source = schema(field('purpose'), field('notes'))
        app = application(source, layout('purpose'), status='partially_signed')
        self.assertEqual({item['key'] for item in application_input_schema(app)['fields']}, {'purpose', 'notes'})
        app.schema_snapshot = {**source, 'form_projection_version': 1}
        del app._form_projection_version
        self.assertEqual({item['key'] for item in application_input_schema(app)['fields']}, {'purpose'})

    def test_submitted_version_one_keeps_signer_inputs_but_editable_forms_use_placement_only(self):
        source = schema(field('purpose'), field('guarantor_phone'))
        source['form_projection_version'] = 1
        app = application(source, layout('purpose'), status='partially_signed')
        app.signer_rules_snapshot = [{'role': 'guarantor_1', 'identity_fields': {'phone': 'guarantor_phone'}}]
        self.assertEqual({item['key'] for item in application_input_schema(app)['fields']}, {'purpose', 'guarantor_phone'})
        app.status = 'correction_required'
        self.assertEqual({item['key'] for item in application_input_schema(app)['fields']}, {'purpose'})

    def test_legacy_draft_uses_its_captured_layout_without_value_contract_conversion(self):
        source = {'sections': [{'key': 'applicant', 'label': 'Applicant'}],
                  'fields': [{'key': key, 'type': 'text', 'required': True, 'section_key': 'applicant'}
                             for key in ['purpose', 'notes']]}
        result = application_input_schema(application(source, layout('purpose')))
        self.assertNotIn('value_contract_version', result)
        self.assertEqual([item['key'] for item in result['fields']], ['purpose'])


class FormProjectionSaveTests(TestCase):
    def setUp(self):
        from origination.tests_value_contracts import PacketValueSaveTests
        PacketValueSaveTests.setUp(self)
        self.application.schema_snapshot = schema(field('purpose', required=True), field('unused', required=True))
        self.application.template_configuration_snapshot = layout('purpose')
        self.application.form_payload = {'purpose': 'Original', 'unused': 'Retain this answer'}
        self.application.save(update_fields=['schema_snapshot', 'template_configuration_snapshot', 'form_payload'])
        self.document.schema_snapshot = schema(field('visit_notes', scope='document'), field('unused_local', scope='document', required=True))
        self.document.template_snapshot = {'configuration': layout('visit_notes')}
        self.document.field_payload = {'unused_local': 'Recoverable answer'}
        self.document.save(update_fields=['schema_snapshot', 'template_snapshot', 'field_payload'])

    def save(self, payload, request_id='projection-save'):
        from origination.services.loan_origination import save_application_fields
        return save_application_fields(application_id=self.application.pk, actor=self.officer, payload=payload,
                                       expected_revision=self.application.revision, request_id=request_id)

    def test_active_save_preserves_inactive_answers_and_is_idempotent(self):
        saved = self.save({'purpose': 'Updated'})
        self.assertEqual(saved.form_payload['unused'], 'Retain this answer')
        self.assertEqual(self.save({'purpose': 'Updated'}).revision, saved.revision)
        self.assertTrue(saved.events.filter(metadata__form_projection_version=2).exists())

    def test_prefetched_form_compilation_needs_no_per_field_database_queries(self):
        from origination.models import LoanOriginationApplication
        loaded = LoanOriginationApplication.objects.prefetch_related('packet_documents').get(pk=self.application.pk)
        with self.assertNumQueries(0):
            application_input_schema(loaded)

    def test_hidden_field_edits_are_rejected_without_losing_answers(self):
        from origination.services.loan_origination import OriginationError
        with self.assertRaises(OriginationError):
            self.save({'unused': 'Not allowed'})
        self.application.refresh_from_db()
        self.assertEqual(self.application.form_payload['unused'], 'Retain this answer')

    def test_deselected_financial_document_cannot_supply_stale_calculation_inputs(self):
        from origination.services.loan_origination import preview_context
        self.application.schema_snapshot = schema(field('purpose'),
            field('business_total_income', source='calculated', binding='total.business_total_income'))
        self.application.template_configuration_snapshot = layout('purpose', 'business_total_income')
        self.application.form_payload['business_sales_amount'] = '999'
        self.application.save(update_fields=['schema_snapshot', 'template_configuration_snapshot', 'form_payload'])
        self.document.schema_snapshot = schema(field('business_sales_amount', type='money'))
        self.document.template_snapshot = {'configuration': layout('business_sales_amount')}
        self.document.selected = False
        self.document.save(update_fields=['schema_snapshot', 'template_snapshot', 'selected'])
        self.assertEqual(preview_context(self.application)['business_total_income'], '')

    def test_existing_person_link_cannot_expose_unplaced_source_details(self):
        people = [field(role + suffix, subject=role) for role in ['spouse', 'guarantor_1']
                  for suffix in ['_name', '_national_id', '_phone']]
        self.application.schema_snapshot = schema(field('purpose'), *people)
        self.application.template_configuration_snapshot = layout('purpose', 'guarantor_1_name')
        self.application.form_payload.update(spouse_name='Synthetic spouse', spouse_national_id='00000000', spouse_phone='0700000000',
                                              _person_role_bindings={'guarantor_1': 'spouse'})
        self.application.save(update_fields=['schema_snapshot', 'template_configuration_snapshot', 'form_payload'])
        keys = {item['key'] for item in application_input_schema(self.application)['fields']}
        self.assertEqual(keys, {'purpose', 'guarantor_1_name'})
        saved = self.save({'purpose': 'Updated', 'guarantor_1_name': 'Placed name'})
        self.assertEqual(saved.form_payload['guarantor_1_name'], 'Placed name')
        self.assertEqual(saved.form_payload['spouse_name'], 'Synthetic spouse')

    def test_inactive_existing_person_link_neither_blocks_saves_nor_creates_values(self):
        self.application.form_payload['_person_role_bindings'] = {'guarantor_1': 'spouse'}
        self.application.save(update_fields=['form_payload'])
        saved = self.save({'purpose': 'Updated'})
        self.assertNotIn('guarantor_1_name', saved.form_payload)
        self.assertEqual(saved.form_payload['_person_role_bindings'], {'guarantor_1': 'spouse'})

    def test_other_officer_cannot_save(self):
        from origination.services.loan_origination import save_application_fields, OriginationError
        with self.assertRaises(OriginationError):
            save_application_fields(application_id=self.application.pk, actor=self.other, payload={'purpose': 'No'},
                                    expected_revision=self.application.revision, request_id='not-owner')

    def test_hidden_location_answers_do_not_erase_captured_location_references(self):
        from core.models import OperationalLocation
        county = OperationalLocation.objects.create(code='PROJECTION-COUNTY', name='Training county', location_type='county')
        sub_county = OperationalLocation.objects.create(code='PROJECTION-SUB', name='Training sub-county', location_type='sub_county', parent=county)
        self.application.county_ref, self.application.sub_county_ref = county, sub_county
        self.application.save(update_fields=['county_ref', 'sub_county_ref'])
        saved = self.save({'purpose': 'Updated'})
        self.assertEqual(saved.county_ref_id, county.pk)
        self.assertEqual(saved.sub_county_ref_id, sub_county.pk)

    def test_projection_retained_after_submission_without_rewriting_snapshots(self):
        saved = self.save({'purpose': 'Updated'})
        saved.status = 'signing_pending'
        saved.save(update_fields=['status'])
        saved.refresh_from_db()
        self.assertEqual([item['key'] for item in application_input_schema(saved)['fields']], ['purpose'])
        self.assertEqual(saved.schema_snapshot, self.application.schema_snapshot)
        self.assertEqual(saved.template_configuration_snapshot, layout('purpose'))

    def test_serialization_and_document_preview_ignore_unplaced_required_fields(self):
        from origination.services.loan_origination import serialize_application
        from origination.services.origination_documents import mark_document_previewed
        result = serialize_application(self.application, actor=self.officer)
        self.assertEqual(result['form_projection_version'], 1)
        self.assertEqual(set(result['form_payload']), {'purpose'})
        support = next(row for row in result['document_packet']['documents'] if row['key'] == 'visit')
        self.assertEqual([item['key'] for item in support['schema']['fields']], ['visit_notes'])
        self.assertEqual(support['missing_fields'], [])
        mark_document_previewed(self.application, 'visit')

    def test_support_save_preserves_inactive_local_answers_and_rejects_changes(self):
        from origination.services.origination_documents import save_document_fields
        from origination.services.loan_origination import OriginationError
        saved = save_document_fields(application_id=self.application.pk, actor=self.officer, document_key='visit',
            payload={'visit_notes': 'Visible'}, expected_revision=self.application.revision, request_id='visible-support')
        self.document.refresh_from_db()
        self.assertEqual(self.document.field_payload, {'visit_notes': 'Visible', 'unused_local': 'Recoverable answer'})
        with self.assertRaises(OriginationError):
            save_document_fields(application_id=saved.pk, actor=self.officer, document_key='visit',
                payload={'unused_local': 'No'}, expected_revision=saved.revision, request_id='hidden-support')

    def test_legacy_save_and_context_use_same_projection(self):
        from origination.services.loan_origination import preview_context
        self.application.schema_snapshot.pop('value_contract_version')
        self.application.save(update_fields=['schema_snapshot'])
        saved = self.save({'purpose': 'Updated'})
        self.assertEqual(saved.form_payload['unused'], 'Retain this answer')
        self.assertNotIn('unused', preview_context(saved))

    def test_legacy_support_save_keeps_inactive_answers_out_of_context(self):
        from origination.services.origination_documents import save_document_fields, document_context
        self.application.schema_snapshot.pop('value_contract_version')
        self.application.save(update_fields=['schema_snapshot'])
        self.document.schema_snapshot.pop('value_contract_version')
        self.document.save(update_fields=['schema_snapshot'])
        saved = save_document_fields(application_id=self.application.pk, actor=self.officer, document_key='visit',
            payload={'visit_notes': 'Visible'}, expected_revision=self.application.revision, request_id='legacy-support')
        self.document.refresh_from_db()
        self.assertEqual(self.document.field_payload['unused_local'], 'Recoverable answer')
        self.assertNotIn('unused_local', document_context(saved, self.document))

    def test_submission_does_not_require_hidden_fields_and_captures_adoption(self):
        from origination.services.loan_origination import submit_for_review
        self.document.previewed_application_revision = self.application.revision
        self.document.save(update_fields=['previewed_application_revision'])
        self.application.primary_previewed_revision = self.application.revision
        self.application.save(update_fields=['primary_previewed_revision'])
        submitted = submit_for_review(application_id=self.application.pk, actor=self.officer,
            expected_revision=self.application.revision, request_id='submit-visible')
        self.assertEqual(submitted.status, 'ready_for_review')
        self.assertTrue(submitted.events.filter(action='submitted_for_review', metadata__form_projection_version=2).exists())
        self.assertEqual([item['key'] for item in application_input_schema(submitted)['fields']], ['purpose'])

    def test_submission_still_requires_visible_required_fields(self):
        from origination.services.loan_origination import submit_for_review, OriginationError
        self.application.form_payload = {'unused': 'Hidden'}
        self.application.save(update_fields=['form_payload'])
        with self.assertRaises(OriginationError) as caught:
            submit_for_review(application_id=self.application.pk, actor=self.officer,
                expected_revision=self.application.revision, request_id='submit-empty-visible')
        self.assertIn('purpose', caught.exception.errors)

    def test_correction_does_not_mistake_hidden_answers_for_removed_locked_fields(self):
        self.application = self.save({'purpose': 'Original'})
        self.application.status = 'correction_required'
        self.application.save(update_fields=['status'])
        targets = {'field': {'purpose'}, 'requirement': set(), 'document_field': set()}
        with patch('origination.services.loan_origination.correction_targets', return_value=targets):
            saved = self.save({'purpose': 'Corrected'}, request_id='correct-visible')
        self.assertEqual(saved.form_payload['purpose'], 'Corrected')
        self.assertEqual(saved.form_payload['unused'], 'Retain this answer')

    def test_document_correction_keeps_inactive_local_answers_for_both_contracts(self):
        from origination.services.origination_documents import save_document_fields
        self.application = self.save({'purpose': 'Original'})
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                if legacy:
                    self.application.schema_snapshot.pop('value_contract_version')
                    self.document.schema_snapshot.pop('value_contract_version')
                    self.document.save(update_fields=['schema_snapshot'])
                self.application.status = 'correction_required'
                self.application.save(update_fields=['status', 'schema_snapshot'])
                targets = {'field': set(), 'requirement': set(), 'document_field': {'visit.visit_notes'}}
                with patch('origination.services.loan_origination.correction_targets', return_value=targets):
                    saved = save_document_fields(application_id=self.application.pk, actor=self.officer, document_key='visit',
                        payload={'visit_notes': 'Corrected' + str(legacy)}, expected_revision=self.application.revision,
                        request_id='correct-document-' + str(legacy))
                self.application = saved
                self.document.refresh_from_db()
                self.assertEqual(self.document.field_payload['unused_local'], 'Recoverable answer')
