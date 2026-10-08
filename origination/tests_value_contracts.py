"""Synthetic contract tests: never call Telegram, Sheets, Drive or signing APIs."""
from copy import deepcopy
import hashlib
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase, TestCase, override_settings

from origination.models import LoanOriginationApplication, OriginationApplicationDocument, OriginationDataField, OriginationDocumentTemplate, OriginationProductDefinition
from origination.services.loan_origination import OriginationError, preview_context, save_application_fields, serialize_application
from origination.services.origination_documents import _frozen_document_context, document_context, packet_signers, save_document_fields, select_documents
from origination.services.origination_value_contracts import (
    ValueContractError, application_input_schema, build_packet_contract,
    normalize_changes, resolve_values, upgrade_schema, validate_contract,
    calculated_totals, schema_with_mapped_values,
)


def field(key, *, source='entered', binding='', subject='applicant', scope='application', type='text', required=False):
    return {'key': key, 'label': key.replace('_', ' ').title(), 'type': type,
            'required': required, 'section_key': 'applicant',
            'source_type': 'user_input' if source == 'entered' else 'system',
            'value_contract': {'version': 2, 'definition': 'Synthetic ' + key,
                               'subject': subject, 'scope': scope, 'source': source,
                               'binding': binding, 'unit': '', 'period': ''}}


def schema(*fields):
    return {'value_contract_version': 2, 'sections': [{'key': 'applicant', 'label': 'Applicant'}], 'fields': list(fields)}


class ValueResolutionTests(SimpleTestCase):
    def test_legacy_is_not_reinterpreted(self):
        self.assertEqual(build_packet_contract({'fields': []}, []), {'version': 1, 'fields': {}, 'documents': {}})

    def test_mixed_value_setups_are_rejected_in_both_directions(self):
        for main, support in [({'fields': []}, schema()), (schema(), {'fields': []})]:
            with self.assertRaises(ValueContractError):
                build_packet_contract(main, [{'key': 'support', 'schema': support}])

    def test_ambiguous_paper_meanings_remain_repair_tasks(self):
        for key in ['enterprise_net_income', 'household_net_income', 'supplier_code']:
            upgraded = upgrade_schema({'fields': [{'key': key, 'label': key, 'source_type': 'user_input'}]})
            self.assertEqual(upgraded['fields'][0]['value_contract'], {})

    def test_identity_does_not_invent_financial_totals(self):
        from origination.services.origination_value_contracts import calculated_totals
        result = calculated_totals({'business_name': 'Synthetic Business', 'household_location': 'Synthetic Place'})
        self.assertEqual(result['business_total_income'], '')
        self.assertEqual(result['household_total_income'], '')

    def test_incomplete_financial_inputs_do_not_imply_a_surplus(self):
        result = calculated_totals({'business_sales_amount': '100.10', 'household_rent_expense': '20.20'})
        self.assertEqual(result['business_total_income'], '100.10')
        self.assertEqual(result['business_total_expenses'], '')
        self.assertEqual(result['business_net_surplus'], '')
        self.assertEqual(result['household_total_income'], '')
        self.assertEqual(result['household_total_expenses'], '20.20')
        self.assertEqual(result['household_net_surplus'], '')
        result = calculated_totals({'business_sales_amount': '100.10', 'business_rent_expense': 0})
        self.assertEqual(result['business_net_surplus'], '100.10')

    def test_one_shared_value_and_separate_document_values(self):
        contract = build_packet_contract(schema(field('applicant_name')), [
            {'key': key, 'schema': schema(field('applicant_name'), field('visit_notes', scope='document'))}
            for key in ['visit', 'assessment']])
        resolved = resolve_values(contract, {'applicant_name': 'Synthetic Applicant'}, quote={}, system={}, workflow={},
                                  document_values={'visit': {'visit_notes': 'One'}, 'assessment': {'visit_notes': 'Two'}})
        self.assertEqual(resolved['values'], {'applicant_name': 'Synthetic Applicant'})
        self.assertEqual(resolved['documents']['visit'], {'visit_notes': 'One'})
        self.assertEqual(resolved['documents']['assessment'], {'visit_notes': 'Two'})

    def test_subject_scope_and_type_conflicts_are_rejected(self):
        for change in [{'subject': 'guarantor_1'}, {'scope': 'document'}, {'type': 'money'}]:
            with self.subTest(change=change), self.assertRaises(ValueContractError):
                build_packet_contract(schema(field('name')), [{'key': 'support', 'schema': schema(field('name', **change))}])

    def test_generated_values_cannot_be_posted(self):
        contract = build_packet_contract(schema(field('approved', source='workflow', binding='workflow.approved_amount')), [])
        with self.assertRaises(ValueContractError) as caught:
            normalize_changes(contract, {'approved': '999'}, {})
        self.assertIn('approved', caught.exception.errors)

    def test_request_is_not_approval_disbursement_or_receipt(self):
        contract = build_packet_contract(schema(field('loan_amount', type='money'), *[
            field(key, source='workflow', binding='workflow.' + binding)
            for key, binding in [('approved', 'approved_amount'), ('advanced', 'disbursed_amount'), ('received', 'received_amount'), ('visited', 'visit_date')]]), [])
        result = resolve_values(contract, {'loan_amount': '100000'}, quote={}, system={'visit_date': '2026-10-08'}, workflow={})
        self.assertEqual(result['values']['loan_amount'], '100000')
        for key in ['approved', 'advanced', 'received', 'visited']:
            self.assertEqual(result['values'][key], '')
            self.assertEqual(result['availability'][key]['status'], 'waiting_for_event')

    def test_zero_quote_value_is_present_and_decimal_totals_are_exact(self):
        contract = build_packet_contract(schema(
            field('interest', source='calculated', binding='quote.total_interest_amount'),
            field('income', source='calculated', binding='total.business_total_income')), [])
        result = resolve_values(contract, {'business_sales_amount': '0.10', 'business_other_income_lines': [{'amount': '0.20'}]},
                                quote={'interest': '0'}, system={}, workflow={})
        self.assertEqual(result['values'], {'interest': '0', 'income': '0.30'})
        self.assertEqual(result['availability']['interest']['status'], 'present')

    def test_executable_and_unreviewed_bindings_rejected(self):
        for binding in ['eval(payload)', 'system.deponent_full_name', 'workflow.unknown']:
            with self.assertRaises(ValueContractError):
                validate_contract(field('x', source='calculated', binding=binding)['value_contract'])

    def test_repeat_capacity_uses_smallest_document_capacity(self):
        main = field('assets', type='repeating_group')
        main['structure'] = {'min_items': 0, 'max_items': 4, 'columns': [{'key': 'description', 'type': 'text'}]}
        support = deepcopy(main)
        support['structure']['max_items'] = 2
        contract = build_packet_contract(schema(main), [{'key': 'support', 'schema': schema(support)}])
        self.assertEqual(contract['fields']['assets']['structure']['max_items'], 2)

    def test_layout_capacity_and_captured_generated_schema_are_respected(self):
        assets = field('assets', type='repeating_group')
        assets['structure'] = {'min_items': 1, 'max_items': 10, 'columns': [{'key': 'description', 'type': 'text'}]}
        config = {'field_overlay_manifest': {'fields': {
            'table': {'context_key': 'assets', 'render_as': 'repeating_table', 'rows': 2},
            'total': {'context_key': 'total_interest_amount'}}}}
        mapped = schema_with_mapped_values(schema(assets), config, captured_system=[{
            'key': 'total_interest_amount', 'type': 'money', 'source_type': 'system'}])
        self.assertEqual(mapped['fields'][0]['structure']['max_items'], 2)
        self.assertEqual(assets['structure']['max_items'], 10)
        self.assertEqual(mapped['fields'][1]['type'], 'money')
        self.assertEqual(mapped['fields'][1]['value_contract']['binding'], 'quote.total_interest_amount')
        config['field_overlay_manifest']['fields']['table']['rows'] = -1
        with self.assertRaises(ValueContractError):
            schema_with_mapped_values(schema(assets), config)

    def test_upgrade_is_explicit_and_does_not_mutate_source(self):
        original = {'fields': [{'key': 'approval_amount', 'type': 'money', 'source_type': 'user_input'}]}
        upgraded = upgrade_schema(original)
        self.assertNotIn('value_contract_version', original)
        self.assertEqual(upgraded['fields'][0]['source_type'], 'system')
        self.assertEqual(upgraded['fields'][0]['value_contract']['binding'], 'workflow.approved_amount')

    def test_frozen_context_uses_only_exact_document_identity(self):
        document = SimpleNamespace(pk='one', field_payload={'name': 'Changed'})
        frozen = {'_value_contract_version': 2, '_document_contexts': {'one': {'name': 'Frozen'}}}
        self.assertEqual(_frozen_document_context(document, frozen), {'name': 'Frozen'})
        with self.assertRaises(OriginationError):
            _frozen_document_context(SimpleNamespace(pk='two'), frozen)

    def test_person_reuse_requires_explicit_link_and_detaches_as_copy(self):
        contract = build_packet_contract(schema(*[
            field(role + suffix, subject=role) for role in ['spouse', 'guarantor_1']
            for suffix in ['_name', '_id_number', '_phone']]), [])
        initial = {'spouse_name': 'Synthetic Person', 'spouse_id_number': '12345678', 'spouse_phone': '0712345678'}
        unlinked, _ = normalize_changes(contract, {}, initial)
        self.assertNotIn('guarantor_1_name', unlinked)
        linked, _ = normalize_changes(contract, {'_person_role_bindings': {'guarantor_1': 'spouse'}}, initial)
        self.assertEqual(linked['guarantor_1_name'], linked['spouse_name'])
        updated, _ = normalize_changes(contract, {'spouse_name': 'Changed'}, linked)
        self.assertEqual(updated['guarantor_1_name'], 'Changed')
        detached, _ = normalize_changes(contract, {'_person_role_bindings': {}}, updated)
        independent, _ = normalize_changes(contract, {'spouse_name': 'Another'}, detached)
        self.assertEqual(independent['guarantor_1_name'], 'Changed')

    def test_person_links_reject_cycles_self_guarantees_and_target_edits(self):
        contract = build_packet_contract(schema(*[
            field(role + suffix, subject=role) for role in ['spouse', 'guarantor_1']
            for suffix in ['_name', '_id_number', '_phone']]), [])
        for links in [{'guarantor_1': 'guarantor_1'}, {'guarantor_1': 'applicant'}, {'officer': 'spouse'}]:
            with self.subTest(links=links), self.assertRaises(ValueContractError):
                normalize_changes(contract, {'_person_role_bindings': links}, {})
        linked, _ = normalize_changes(contract, {'_person_role_bindings': {'guarantor_1': 'spouse'}}, {'spouse_name': 'One'})
        with self.assertRaises(ValueContractError):
            normalize_changes(contract, {'guarantor_1_name': 'Different'}, linked)

    def test_v2_renderer_refuses_to_silently_drop_repeating_rows(self):
        from core.tests_origination_templates import synthetic_pdf
        from core.services.partnership_laf_preview import render_template, PartnershipLafPreviewError
        config = {'field_overlay_manifest': {'fields': {'assets': {'context_key': 'assets', 'page_number': 1,
            'render_as': 'repeating_table', 'rows': 1, 'box': {'x': 10, 'y': 10, 'width': 100, 'height': 30},
            'columns': [{'key': 'description'}]}}}}
        values = {'assets': [{'description': 'One'}, {'description': 'Two'}]}
        self.assertTrue(render_template(synthetic_pdf(), config, values).startswith(b'%PDF'))
        with self.assertRaises(PartnershipLafPreviewError):
            render_template(synthetic_pdf(), config, {**values, '_value_contract_version': 2})

    def test_v2_renderer_refuses_to_truncate_long_text(self):
        from core.tests_origination_templates import synthetic_pdf
        from core.services.partnership_laf_preview import render_template, PartnershipLafPreviewError
        config = {'field_overlay_manifest': {'fields': {'name': {'context_key': 'name', 'page_number': 1,
            'box': {'x': 10, 'y': 10, 'width': 10, 'height': 30}}}}}
        with self.assertRaises(PartnershipLafPreviewError):
            render_template(synthetic_pdf(), config, {'name': 'Synthetic long applicant name', '_value_contract_version': 2})


class PacketValueSaveTests(TestCase):
    def setUp(self):
        self.officer = get_user_model().objects.create_user('synthetic-contract-officer')
        self.other = get_user_model().objects.create_user('synthetic-contract-other')
        self.primary = schema(field('applicant_name'), field('loan_amount', type='money'))
        self.product = OriginationProductDefinition.objects.create(product_key='synthetic-values', name='Synthetic Values', version=1,
            form_schema=self.primary, signer_rules=[], document_type='synthetic-values')
        self.application = LoanOriginationApplication.objects.create(product_definition=self.product, officer=self.officer,
            schema_snapshot=self.primary, branch='Synthetic branch', form_payload={'applicant_name': 'Original'})
        self.document = OriginationApplicationDocument.objects.create(application=self.application, document_key='visit',
            document_role='supporting', name='Synthetic visit', selected=True, applicable=True,
            schema_snapshot=schema(field('applicant_name'), field('extra_shared'), field('visit_notes', scope='document'),
                                   field('visited', source='workflow', binding='workflow.visit_date')))
        audit = patch('core.services.compliance_audit.record_event')
        audit.start(); self.addCleanup(audit.stop)
        locations = patch('core.services.location_catalog.validate_location_selection', return_value=(None, None, None))
        locations.start(); self.addCleanup(locations.stop)

    def save(self, payload, key='synthetic-save'):
        return save_document_fields(application_id=self.application.pk, document_key='visit', actor=self.officer,
                                    payload=payload, expected_revision=self.application.revision, request_id=key)

    def test_support_save_updates_shared_values_once_and_keeps_local_values_local(self):
        saved = self.save({'applicant_name': 'Changed', 'extra_shared': 'Shared', 'visit_notes': 'Local'})
        self.document.refresh_from_db()
        self.assertEqual(saved.form_payload, {'applicant_name': 'Changed', 'extra_shared': 'Shared'})
        self.assertEqual(self.document.field_payload, {'visit_notes': 'Local'})
        self.assertEqual(saved.revision, self.application.revision + 1)
        self.assertEqual(document_context(saved, self.document)['applicant_name'], 'Changed')

    def test_retry_does_not_duplicate_or_advance_revision(self):
        first = self.save({'visit_notes': 'Local'})
        replay = self.save({'visit_notes': 'Local'})
        self.assertEqual(first.revision, replay.revision)
        self.assertEqual(replay.events.filter(action='supporting_document_saved').count(), 1)
        with self.assertRaises(OriginationError): self.save({'visit_notes': 'Different retry'})

    def test_unchanged_save_preserves_preview_and_revision(self):
        self.document.field_payload = {'visit_notes': 'Saved'}
        self.document.previewed_application_revision = self.application.revision
        self.document.save(update_fields=['field_payload', 'previewed_application_revision'])
        saved = self.save({'visit_notes': 'Saved'}, key='unchanged')
        self.document.refresh_from_db()
        self.assertEqual(saved.revision, self.application.revision)
        self.assertEqual(self.document.previewed_application_revision, self.application.revision)
        replay = self.save({'visit_notes': 'Saved'}, key='unchanged')
        self.assertEqual(replay.revision, saved.revision)

    def test_application_can_save_support_only_shared_fields(self):
        saved = save_application_fields(application_id=self.application.pk, actor=self.officer,
            payload={'extra_shared': 'Shared'}, expected_revision=self.application.revision, request_id='main-extra')
        self.assertEqual(saved.form_payload['applicant_name'], 'Original')
        self.assertEqual(saved.form_payload['extra_shared'], 'Shared')
        keys = [f['key'] for f in application_input_schema(saved)['fields']]
        self.assertEqual(keys.count('applicant_name'), 1)
        self.assertNotIn('visited', keys)

    def test_generated_post_and_other_officer_fail_without_mutation(self):
        with self.assertRaises(OriginationError): self.save({'visited': '2026-10-08'})
        with self.assertRaises(OriginationError):
            save_document_fields(application_id=self.application.pk, document_key='visit', actor=self.other,
                payload={'visit_notes': 'Unauthorized'}, expected_revision=self.application.revision, request_id='other')
        self.document.refresh_from_db()
        self.assertEqual(self.document.field_payload, {})

    def test_preview_does_not_invent_visit_or_money_events(self):
        context = preview_context(self.application)
        self.assertNotIn('amount_advanced', context)
        self.assertEqual(context['visited'], '')
        self.assertNotIn('home_visit_completed_date', context)

    def test_mapped_generated_values_use_frozen_quote_not_posted_values(self):
        self.application.template_configuration_snapshot = {'field_overlay_manifest': {'fields': {
            'interest': {'context_key': 'total_interest_amount'}}}}
        self.application.product_quote_snapshot = {'interest': '0'}
        self.assertEqual(preview_context(self.application)['total_interest_amount'], '0')

    def test_repeat_capacity_is_enforced_before_save(self):
        assets = field('assets', type='repeating_group')
        assets['structure'] = {'min_items': 0, 'max_items': 1, 'columns': [{'key': 'description', 'type': 'text'}]}
        self.document.schema_snapshot = schema(assets)
        self.document.save(update_fields=['schema_snapshot'])
        with self.assertRaises(OriginationError):
            self.save({'assets': [{'description': 'One'}, {'description': 'Two'}]})
        self.application.refresh_from_db()
        self.assertEqual(self.application.form_payload, {'applicant_name': 'Original'})

    def test_invalid_local_value_rolls_back_shared_change_and_audit(self):
        self.document.schema_snapshot = schema(field('applicant_name'), field('visit_amount', type='money', scope='document'))
        self.document.save(update_fields=['schema_snapshot'])
        with self.assertRaises(OriginationError):
            self.save({'applicant_name': 'Must roll back', 'visit_amount': 'not money'})
        self.application.refresh_from_db()
        self.document.refresh_from_db()
        self.assertEqual(self.application.form_payload, {'applicant_name': 'Original'})
        self.assertEqual(self.document.field_payload, {})
        self.assertFalse(self.application.events.exists())

    def test_person_links_survive_database_normalization_and_partial_saves(self):
        self.application.schema_snapshot = schema(*[
            field(role + suffix, subject=role) for role in ['spouse', 'guarantor_1']
            for suffix in ['_name', '_id_number', '_phone']])
        self.application.form_payload = {'spouse_name': 'Synthetic Person', 'spouse_id_number': '12345678', 'spouse_phone': '0712345678'}
        self.application.save(update_fields=['schema_snapshot', 'form_payload'])
        self.document.schema_snapshot = schema()
        self.document.save(update_fields=['schema_snapshot'])
        linked = save_application_fields(application_id=self.application.pk, actor=self.officer,
            payload={'_person_role_bindings': {'guarantor_1': 'spouse'}}, expected_revision=self.application.revision, request_id='link')
        updated = save_application_fields(application_id=self.application.pk, actor=self.officer,
            payload={'spouse_name': 'Updated'}, expected_revision=linked.revision, request_id='link-edit')
        self.assertEqual(updated.form_payload['guarantor_1_name'], 'Updated')
        self.assertEqual(updated.form_payload['_person_role_bindings'], {'guarantor_1': 'spouse'})

    def test_document_signer_identity_cannot_be_silently_overwritten(self):
        self.document.schema_snapshot = schema(field('witness_name', scope='document'))
        self.document.field_payload = {'witness_name': 'Synthetic One'}
        self.document.signer_rules_snapshot = [{'role': 'witness', 'identity_fields': {'name': 'witness_name'}}]
        self.document.save(update_fields=['schema_snapshot', 'field_payload', 'signer_rules_snapshot'])
        self.assertEqual(packet_signers(self.application)[0]['identity']['name'], 'Synthetic One')
        OriginationApplicationDocument.objects.create(application=self.application, document_key='another',
            document_role='supporting', name='Another synthetic document', selected=True,
            schema_snapshot=self.document.schema_snapshot, field_payload={'witness_name': 'Synthetic Two'},
            signer_rules_snapshot=self.document.signer_rules_snapshot)
        with self.assertRaisesRegex(OriginationError, 'different people'):
            packet_signers(self.application)

    def test_global_published_meaning_is_a_field_error_and_stays_immutable(self):
        definition = field('applicant_name')['value_contract']
        catalogue_field = OriginationDataField.objects.create(key='applicant_name', label='Applicant', data_type='text', value_contract=definition)
        catalogue_field.value_contract = {**definition, 'subject': 'guarantor_1'}
        with self.assertRaises(ValidationError) as caught:
            catalogue_field.full_clean()
        self.assertIn('value_contract', caught.exception.message_dict)
        with self.assertRaises(ValidationError):
            catalogue_field.save()
        catalogue_field.refresh_from_db()
        self.assertEqual(catalogue_field.value_contract, definition)

    def test_deselection_retains_values_without_soft_locking_the_main_form(self):
        saved = self.save({'extra_shared': 'Keep this'})
        self.document.inclusion_mode = 'optional'
        self.document.save(update_fields=['inclusion_mode'])
        deselected = select_documents(application_id=self.application.pk, actor=self.officer,
            selected_keys=[], expected_revision=saved.revision, request_id='deselect')
        updated = save_application_fields(application_id=self.application.pk, actor=self.officer,
            payload={'applicant_name': 'Changed'}, expected_revision=deselected.revision, request_id='after-deselect')
        self.assertEqual(updated.form_payload['extra_shared'], 'Keep this')
        self.assertNotIn('extra_shared', [f['key'] for f in application_input_schema(updated)['fields']])
        restored = select_documents(application_id=self.application.pk, actor=self.officer,
            selected_keys=['visit'], expected_revision=updated.revision, request_id='reselect')
        self.document.refresh_from_db()
        self.assertEqual(document_context(restored, self.document)['extra_shared'], 'Keep this')

    def test_selection_retry_binds_actor_and_document_choices(self):
        self.document.inclusion_mode = 'optional'
        self.document.save(update_fields=['inclusion_mode'])
        selected = select_documents(application_id=self.application.pk, actor=self.officer,
            selected_keys=['visit'], expected_revision=self.application.revision, request_id='selection-retry')
        replay = select_documents(application_id=self.application.pk, actor=self.officer,
            selected_keys=['visit'], expected_revision=self.application.revision, request_id='selection-retry')
        self.assertEqual(replay.revision, selected.revision)
        for actor, keys in [(self.other, ['visit']), (self.officer, [])]:
            with self.assertRaises(OriginationError):
                select_documents(application_id=self.application.pk, actor=actor,
                    selected_keys=keys, expected_revision=selected.revision, request_id='selection-retry')

    def test_deselected_financial_inputs_do_not_leak_into_active_totals(self):
        self.application.schema_snapshot = schema(
            field('business_sales_amount', type='money'),
            field('income', source='calculated', binding='total.business_total_income'))
        self.application.form_payload = {'business_sales_amount': '100', 'business_other_income_lines': [{'amount': '20'}]}
        self.application.save(update_fields=['schema_snapshot', 'form_payload'])
        self.document.schema_snapshot = schema(field('business_other_income_lines', type='repeating_group'))
        self.document.inclusion_mode = 'optional'
        self.document.save(update_fields=['schema_snapshot', 'inclusion_mode'])
        self.assertEqual(preview_context(self.application)['income'], '120')
        deselected = select_documents(application_id=self.application.pk, actor=self.officer,
            selected_keys=[], expected_revision=self.application.revision, request_id='remove-financial-inputs')
        self.assertEqual(deselected.form_payload['business_other_income_lines'], [{'amount': '20'}])
        self.assertEqual(preview_context(deselected)['income'], '100')
        restored = select_documents(application_id=self.application.pk, actor=self.officer,
            selected_keys=['visit'], expected_revision=deselected.revision, request_id='restore-financial-inputs')
        self.assertEqual(preview_context(restored)['income'], '120')

    def test_deselection_detaches_unavailable_role_but_keeps_its_identity_copy(self):
        self.application.schema_snapshot = schema(*[
            field('spouse' + suffix, subject='spouse') for suffix in ['_name', '_id_number', '_phone']])
        self.application.form_payload = {'spouse_name': 'Synthetic Person', 'spouse_id_number': '12345678', 'spouse_phone': '0712345678'}
        self.application.save(update_fields=['schema_snapshot', 'form_payload'])
        self.document.schema_snapshot = schema(*[
            field('guarantor_1' + suffix, subject='guarantor_1') for suffix in ['_name', '_id_number', '_phone']])
        self.document.inclusion_mode = 'optional'
        self.document.save(update_fields=['schema_snapshot', 'inclusion_mode'])
        linked = save_application_fields(application_id=self.application.pk, actor=self.officer,
            payload={'_person_role_bindings': {'guarantor_1': 'spouse'}}, expected_revision=self.application.revision, request_id='link-before-deselect')
        deselected = select_documents(application_id=self.application.pk, actor=self.officer,
            selected_keys=[], expected_revision=linked.revision, request_id='detach-deselected')
        self.assertEqual(deselected.form_payload['_person_role_bindings'], {})
        self.assertEqual(deselected.form_payload['guarantor_1_name'], 'Synthetic Person')
        self.assertEqual(deselected.events.get(request_id='detach-deselected').after_values['detached_person_roles'], ['guarantor_1'])

    def test_masked_serialization_does_not_add_resolved_pii(self):
        result = serialize_application(self.application, include_payload=True, presentation='masked')
        self.assertNotIn('resolved_values', result)
        self.assertEqual(result['document_packet']['documents'][0]['resolved_values'], {})


class ChosenDocumentMeaningTests(TestCase):
    def setUp(self):
        from core.tests_origination_document_catalogue import OriginationDocumentCatalogueTests
        OriginationDocumentCatalogueTests.setUp(self)

    def template(self, **kwargs):
        from core.tests_origination_document_catalogue import OriginationDocumentCatalogueTests
        return OriginationDocumentCatalogueTests._template(self, **kwargs)

    def test_commercial_merge_preserves_exact_reviewed_meanings(self):
        from origination.services.origination_document_catalogue import main_laf_contract
        document_schema = upgrade_schema(self.schema)
        amount = next(f for f in document_schema['fields'] if f['key'] == 'loan_amount')
        amount['value_contract'].update(definition='Requested amount in this reviewed document.', unit='KES', period='per application')
        main = self.template(family='reviewed_main', name='Reviewed synthetic Main', schema=document_schema)
        actual, reasons = main_laf_contract(self.definition, main)
        self.assertEqual(reasons, [])
        self.assertEqual(next(f for f in actual['fields'] if f['key'] == 'loan_amount')['value_contract'], amount['value_contract'])

    def test_optional_legacy_support_does_not_hide_a_new_main(self):
        from origination.services.origination_document_catalogue import catalogue_for_product, validate_document_combination
        main = self.template(family='new_main', name='New Main', schema=upgrade_schema(self.schema))
        support = self.template(family='old_support', name='Old support', role='supporting', schema={'fields': []})
        catalogue = catalogue_for_product(self.definition)
        self.assertTrue(catalogue['ready'])
        self.assertEqual(catalogue['supporting_documents'][0]['compatible_main_ids'], [])
        with self.assertRaises(OriginationError):
            validate_document_combination(main, [support])

    def test_publication_refuses_required_future_event_and_missing_legal_role(self):
        from origination.services.origination_document_catalogue import validate_catalogue_publication
        support = self.template(family='future_event', name='Future event', role='supporting',
            schema=schema(field('received', source='workflow', binding='workflow.received_amount', required=True)))
        support.published_configuration_revision.configuration = {'field_overlay_manifest': {'fields': {}}}
        with self.assertRaisesRegex(OriginationError, 'later workflow event'):
            validate_catalogue_publication(support)
        support.form_schema = {**schema(), 'required_signer_roles': ['asset_owner']}
        with self.assertRaisesRegex(OriginationError, 'asset owner'):
            validate_catalogue_publication(support)

    def test_selection_rejects_layout_with_too_few_rows_before_creation(self):
        from origination.services.origination_document_catalogue import validate_document_combination
        main = self.template(family='capacity_main', name='Capacity Main', schema=upgrade_schema(self.schema))
        assets = field('assets', type='repeating_group')
        assets['structure'] = {'min_items': 3, 'max_items': 10, 'columns': [{'key': 'description', 'type': 'text'}]}
        support = self.template(family='capacity_support', name='Capacity support', role='supporting', schema=schema(assets))
        support.published_configuration_revision.configuration = {'field_overlay_manifest': {'fields': {
            'assets': {'context_key': 'assets', 'render_as': 'repeating_table', 'rows': 2}}}}
        with self.assertRaisesRegex(OriginationError, 'enough rows'):
            validate_document_combination(main, [support])


@override_settings(ORIGINATION_CONDITIONAL_APPROVAL_ENABLED=True, ORIGINATION_ESIGN_ENABLED=True,
                   AFRICASTALKING_SMS_ENVIRONMENT='sandbox', AFRICASTALKING_USERNAME='sandbox',
                   AFRICASTALKING_API_KEY='synthetic-only', SENTRY_ENVIRONMENT='test')
class SharedValueFreezeTests(TestCase):
    def test_actual_signing_package_freezes_each_document_context_and_zero_quote(self):
        from origination.tests_approval import ApprovalSignatureTests
        from core.tests_origination_templates import synthetic_pdf
        from origination.services.loan_origination import confirm_and_start_conditional_signing
        ApprovalSignatureTests.setUp(self)
        self.package.status = 'cancelled'
        self.package.save(update_fields=['status'])
        primary_schema = schema(field('applicant_name', required=True),
            field('interest', source='calculated', binding='quote.total_interest_amount'))
        rules = self.package.participants_snapshot
        self.application.status = 'draft'
        self.application.schema_snapshot = primary_schema
        self.application.signer_rules_snapshot = rules
        self.application.primary_previewed_revision = 1
        self.application.product_quote_snapshot = {'interest': '0'}
        source = synthetic_pdf()
        configuration = {'field_overlay_manifest': {'fields': {'name': {
            'context_key': 'applicant_name', 'page_number': 1,
            'box': {'x': 40, 'y': 40, 'width': 250, 'height': 25}}}},
            'signature_overlay_manifest': {'slots': {
                f'{rule["role"]}.{rule["slots"][0]["key"]}': {
                    'page_number': 1, 'x': 40, 'y': 90 + index * 90, 'width': 200, 'height': 50}
                for index, rule in enumerate(rules)}}}
        self.application.template_configuration_snapshot = configuration
        self.application.save()
        template = OriginationDocumentTemplate.objects.create(document_type='synthetic-freeze', version=1, name='Synthetic LAF',
            source_sha256=hashlib.sha256(source).hexdigest(), source_byte_size=len(source), page_count=1,
            placement_config=configuration, created_by=self.officer)
        primary = OriginationApplicationDocument.objects.create(application=self.application, template=template,
            document_key='primary', name='Synthetic Main', document_role='primary', selected=True,
            template_snapshot={'sha256': template.source_sha256, 'configuration': configuration},
            schema_snapshot=primary_schema, signer_rules_snapshot=rules)
        support = OriginationApplicationDocument.objects.create(application=self.application, template=template,
            document_key='support', name='Synthetic support', document_role='supporting', selected=True,
            template_snapshot={'sha256': template.source_sha256, 'configuration': {}},
            schema_snapshot=schema(field('applicant_name'), field('notes', scope='document')),
            field_payload={'notes': 'Frozen support notes'}, previewed_application_revision=1)
        with patch('origination.services.origination_templates.load_template_source', return_value=source):
            package, replayed = confirm_and_start_conditional_signing(application_id=self.application.pk,
                actor=self.officer, expected_revision=1, request_id='shared-values-submit')
        self.assertFalse(replayed)
        self.assertEqual(package.context_snapshot['_value_contract_version'], 2)
        frozen_primary = _frozen_document_context(primary, package.context_snapshot)
        frozen_support = _frozen_document_context(support, package.context_snapshot)
        self.assertEqual(frozen_primary['interest'], '0')
        self.assertEqual(frozen_support['applicant_name'], frozen_primary['applicant_name'])
        self.assertEqual(frozen_support['notes'], 'Frozen support notes')
        self.assertNotIn('notes', frozen_primary)
        support.field_payload = {'notes': 'Later mutation must not render'}
        self.application.form_payload = {'applicant_name': 'Later identity'}
        self.assertEqual(_frozen_document_context(support, package.context_snapshot)['notes'], 'Frozen support notes')
        self.assertEqual(_frozen_document_context(primary, package.context_snapshot)['applicant_name'], 'Synthetic Applicant')
