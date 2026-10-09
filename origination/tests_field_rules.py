"""Synthetic scalar/repeating contracts and immutable choice display boundaries."""
from copy import deepcopy
from datetime import timedelta
import uuid

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from origination.services.loan_origination import apply_choice_display_values, validate_form_payload
from origination.services.origination_field_rules import merge_rules, validate_rules
from origination.services.origination_country_choices import country_options, reviewed_spec, reviewed_structure


class OriginationFieldRuleTests(SimpleTestCase):
    def check(self, field, value, valid, complete=True):
        field = {'key': 'test_field', **field}
        result = validate_form_payload({'fields': [field]}, {field['key']: value}, require_complete=complete)
        self.assertEqual(result.valid, valid, result.errors)

    def test_scalar_rules_are_applied_to_supplied_draft_values(self):
        for kind, rules, good, bad in (
            ('text', {'format': 'email'}, 'synthetic+tag@example.test', 'not an email'),
            ('number', {'integer': True, 'min': '0'}, '2', '2.5'),
            ('number', {'decimal_places': 2}, '1.25', '1.251'),
            ('date', {'no_future': True}, timezone.localdate().isoformat(), (timezone.localdate() + timedelta(days=1)).isoformat()),
            ('text', {'max_length': 3}, 'abc', 'abcd'),
        ):
            with self.subTest(kind=kind, rules=rules):
                self.check({'type': kind, 'validation': rules}, good, True, complete=False)
                self.check({'type': kind, 'validation': rules}, bad, False, complete=False)

    def test_blank_optional_and_false_and_zero_are_not_confused(self):
        self.check({'type': 'text', 'validation': {'format': 'email'}}, '', True)
        self.check({'type': 'text', 'required': True}, '', True, complete=False)
        self.check({'type': 'text', 'required': True}, '   ', False)
        self.check({'type': 'boolean', 'required': True}, False, True)
        self.check({'type': 'number', 'required': True, 'validation': {'integer': True}}, 0, True)
        self.check({'type': 'number'}, True, False)
        self.check({'type': 'money'}, '-10', True)
        self.check({'type': 'number','validation':{'integer':True}}, '1,200', True)
        for value in ('NaN', 'Infinity', '-Infinity'):
            self.check({'type': 'number'}, value, False)

    def test_every_child_control_uses_scalar_rules(self):
        for column, bad in (
            ({'type': 'text', 'validation': {'format': 'email'}}, 'bad'),
            ({'type': 'number', 'validation': {'integer': True}}, '1.2'),
            ({'type': 'choice', 'options': [{'code':'ke', 'label':'Kenya'}]}, 'ug'),
            ({'type': 'date', 'validation': {'max_date':'2026-01-01'}}, '2026-02-01'),
            ({'type': 'boolean'}, 'yes'),
        ):
            field = {'type':'repeating_group', 'structure':{'max_items':3, 'columns':[{'key':'cell', **column}]}}
            self.check(field, [{'row_id':str(uuid.uuid4()), 'cell':bad}], False, complete=False)

    def test_only_active_country_choices_are_selectable(self):
        options = country_options()
        self.assertEqual(len(options), 249)
        self.assertEqual([option['code'] for option in options if option['active']], ['ke'])
        self.assertEqual(len({option['code'] for option in options}), len(options))
        field = {'type':'choice', 'options':options}
        self.check(field, 'ke', True)
        self.check(field, 'ug', False)
        spec = reviewed_spec({'key':'applicant_nationality', 'type':'text'})
        self.assertEqual(spec['key'], 'applicant_nationality_country')
        self.assertEqual(spec['type'], 'choice')

    def test_pdf_choice_display_does_not_change_canonical_values(self):
        schema = {'fields':[{'key':'nationality', 'type':'choice', 'options':[{'code':'ke', 'label':'Kenya'}]}]}
        payload = {'nationality':'ke'}
        context = apply_choice_display_values(deepcopy(payload), schema)
        self.assertEqual(payload['nationality'], 'ke')
        self.assertEqual(context['nationality'], 'Kenya')
        self.assertEqual(context['_canonical_values']['nationality'], 'ke')
        schema = {'fields':[{'key':'people', 'type':'repeating_group', 'structure':{'columns':schema['fields']}}]}
        values = {'people':[{'nationality':'ke', 'row_id':'synthetic'}]}
        context = apply_choice_display_values(deepcopy(values), schema)
        self.assertEqual(context['people'][0]['nationality'], 'Kenya')
        self.assertEqual(context['_canonical_values']['people'], values['people'])
        self.assertEqual(apply_choice_display_values(context, schema)['_canonical_values']['people'], values['people'])

    def test_shared_limits_intersect_and_contradictions_fail(self):
        self.assertEqual(merge_rules({'min':'1','max':'10'}, {'min':'3','max':'7','integer':True}), {'min':'3','max':'7','integer':True})
        with self.assertRaises(ValueError):
            merge_rules({'min':'10'}, {'max':'5'})
        with self.assertRaises(ValueError):
            merge_rules({'parent_field':'applicant_county'}, {'parent_field':'guarantor_county'})

    def test_repeated_seed_rules_do_not_mutate_canonical_structure(self):
        original = {'max_items':3,'columns':[{'key':'year_of_purchase','type':'number','validation':{'min':'1900'}}]}
        spec = reviewed_spec({'key':'assets','type':'repeating_group','structure':original})
        self.assertEqual(spec['structure'], original)
        reviewed = reviewed_structure(spec['structure'])
        self.assertTrue(reviewed['columns'][0]['validation']['integer'])
        self.assertNotIn('integer', original['columns'][0]['validation'])

    def test_shared_documents_combine_required_and_limits(self):
        from origination.tests_value_contracts import field, schema
        from origination.services.origination_value_contracts import build_packet_contract
        optional = {**field('applicant_email'),'validation':{'format':'email','max_length':254}}
        required = {**field('applicant_email',required=True),'validation':{'format':'email','max_length':80}}
        primary = {**schema(optional),'input_rules_version':1}
        result = build_packet_contract(primary, [{'key':'guarantee','schema':schema(required)}])
        combined = result['fields']['applicant_email']
        self.assertTrue(combined['required'])
        self.assertEqual(combined['required_by'], ['guarantee'])
        self.assertEqual(combined['validation']['max_length'], 80)
        self.assertFalse(optional['required'])
        legacy = build_packet_contract(schema(optional), [{'key':'guarantee','schema':schema(required)}])
        self.assertEqual(legacy['fields']['applicant_email']['validation']['max_length'],254)

    def test_legacy_frozen_repeat_codes_stay_unchanged(self):
        from types import SimpleNamespace
        from origination.services.origination_documents import _frozen_document_context
        document = SimpleNamespace(schema_snapshot={'fields':[{'key':'rows','type':'repeating_group',
            'structure':{'columns':[{'key':'country','type':'choice','options':[{'code':'ke','label':'Kenya'}]}]}}]},
            completed_at=timezone.now(), application=None)
        context = {'rows':[{'country':'ke'}]}
        frozen = _frozen_document_context(document,context)
        self.assertEqual(frozen['rows'],context['rows'])

    def test_pdf_displays_labels_dates_zero_and_false(self):
        from io import BytesIO
        from pypdf import PdfReader
        from core.tests_origination_templates import synthetic_pdf
        from core.services.partnership_laf_preview import render_template
        context = apply_choice_display_values({'country':'ke','date':'2026-10-09','count':0,'answer':False},
            {'fields':[{'key':'country','type':'choice','options':[{'code':'ke','label':'Kenya'}]}]})
        context['_date_fields'] = ['date']
        config = {'document_type':'synthetic','version':1,'field_overlay_manifest':{'fields':{
            key:{'context_key':key,'page_number':1,'value_format':'date_dmy_short' if key == 'date' else '',
                 'box':{'x':50,'y':700-index*40,'width':200,'height':25}}
            for index,key in enumerate(['country','date','count','answer'])}}}
        pdf = render_template(synthetic_pdf(),config,context)
        text = PdfReader(BytesIO(pdf)).pages[0].extract_text()
        for expected in ['Kenya','09/10/2026','0','No']:
            self.assertIn(expected,text)
        import os
        if os.environ.get('ORIGINATION_FIELD_QA_ARTIFACTS') == '1':
            from pathlib import Path
            from core.services.partnership_laf_preview import render_pdf_page
            folder = Path('test-results/origination-field-validation')
            folder.mkdir(parents=True,exist_ok=True)
            (folder / 'synthetic-fields.pdf').write_bytes(pdf)
            png,_ = render_pdf_page(pdf,page_number=1)
            (folder / 'synthetic-fields.png').write_bytes(png)

    def test_primary_location_uses_applicant_pair_not_other_people(self):
        from origination.services.loan_origination import _location_field_keys
        fields = [{'key':'applicant_county','type':'county'},
                  {'key':'applicant_area','type':'sub_county','validation':{'parent_field':'applicant_county'}},
                  {'key':'guarantor_county','type':'county'},
                  {'key':'guarantor_area','type':'sub_county','validation':{'parent_field':'guarantor_county'}}]
        self.assertEqual(_location_field_keys({'fields':fields}), {'county':'applicant_county','sub_county':'applicant_area'})
        legacy = deepcopy(fields)
        for field in legacy: field.pop('validation',None)
        self.assertEqual(_location_field_keys({'fields':legacy}), {'county':'guarantor_county','sub_county':'guarantor_area'})

    def test_invalid_authoring_metadata_is_rejected(self):
        for kind, rules in (('text', {'integer':True}), ('date', {'no_future':'yes'}), ('number', {'decimal_places':-1}),
                            ('money', {'min':'NaN'}), ('text', {'min':1}), ('number', {'max_length':4}),
                            ('number', {'min_date':'2026-01-01'})):
            with self.subTest(rules=rules), self.assertRaises(ValueError):
                validate_rules({'type':kind, 'validation':rules})


class FieldEditingAndLocationTests(TestCase):
    def setUp(self):
        from django.contrib.auth import get_user_model
        self.actor = get_user_model().objects.create_superuser('synthetic-rules-admin', password='test-only')

    def test_rule_removal_is_saved_and_retry_does_not_increment_revision(self):
        from origination.models import OriginationDocumentTemplate, OriginationDataField, OriginationProductDefinition, LoanOriginationApplication
        from origination.services.origination_fields import edit_template_field, OriginationFieldConflict, OriginationFieldError
        field = OriginationDataField.objects.create(key='synthetic_email', label='Email', data_type='text')
        template = OriginationDocumentTemplate.objects.create(
            name='Synthetic document', document_type='synthetic_rules', version=1,
            source_filename='synthetic.pdf', source_sha256='a'*64, source_byte_size=100,
            page_count=1, form_schema={'_revision':1,'fields':[
                {'key':field.key, 'type':'text','required':True,'validation':{'format':'email','max_length':40}}
            ]}, created_by=self.actor)
        original_snapshot = deepcopy(template.form_schema)
        product = OriginationProductDefinition.objects.create(product_key='synthetic_rules',name='Synthetic rules',version=1)
        application = LoanOriginationApplication.objects.create(
            reference_number='ORG-SYNTHETIC-RULES',product_definition=product,officer=self.actor,
            branch='Synthetic',schema_snapshot=original_snapshot,form_payload={field.key:'synthetic@example.test'})
        args = dict(template=template,key=field.key,action='update',presentation={'required':False,'validation':{}},
                    actor=self.actor,expected_schema_revision=1,request_id='synthetic-clear-rules')
        updated = edit_template_field(**args)
        self.assertFalse(updated.form_schema['fields'][0]['required'])
        self.assertEqual(updated.form_schema['fields'][0]['validation'], {})
        self.assertTrue(original_snapshot['fields'][0]['required'])
        application.refresh_from_db()
        self.assertEqual(application.schema_snapshot,original_snapshot)
        self.assertEqual(edit_template_field(**args).form_schema['_revision'], 2)
        with self.assertRaises(OriginationFieldConflict):
            edit_template_field(**{**args,'request_id':'different-request'})
        template.status = 'active'
        template.save(update_fields=['status'])
        with self.assertRaises(OriginationFieldError):
            edit_template_field(**{**args,'expected_schema_revision':2,'request_id':'published-edit'})

    def test_reseeding_preserves_country_activation_and_existing_snapshot(self):
        from origination.services.origination_main_laf_seeds import DEFINITIONS, _ensure_fields, build_form_schema
        definition = next(item for item in DEFINITIONS if item.key == 'invoice_finance')
        fields = _ensure_fields(definition, actor=self.actor)
        nationality = fields['applicant_nationality_country']
        first_schema = build_form_schema(definition, fields)
        snapshot = deepcopy(first_schema)
        for option in nationality.choice_options:
            if option['code'] == 'ug': option['active'] = True
        nationality.save()
        fields = _ensure_fields(definition, actor=self.actor)
        current = build_form_schema(definition, fields)
        options = lambda schema: next(field for field in schema['fields'] if field['key'] == nationality.key)['options']
        self.assertEqual([item['code'] for item in options(snapshot)], ['ke'])
        self.assertEqual({item['code'] for item in options(current)}, {'ke','ug'})

    def test_bound_county_subcounty_is_checked_on_direct_payloads(self):
        from core.models import OperationalLocation
        county = OperationalLocation.objects.create(code='TEST-COUNTY-1',name='Synthetic County 1',location_type='county')
        other = OperationalLocation.objects.create(code='TEST-COUNTY-2',name='Synthetic County 2',location_type='county')
        sub = OperationalLocation.objects.create(code='TEST-SUB-1',name='Synthetic Sub-county',location_type='sub_county',parent=county)
        schema = {'fields':[{'key':'county','type':'county'}, {'key':'area','type':'sub_county','validation':{'parent_field':'county'}}]}
        for values, valid in (({'county':county.code,'area':sub.code},True),
                              ({'county':other.code,'area':sub.code},False),
                              ({'area':sub.code},False), ({},True)):
            self.assertEqual(validate_form_payload(schema,values,require_complete=False).valid, valid)
