import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import (
    LoanOriginationApplication,
    OriginationApplicationEvent,
    OriginationProductDefinition,
    Product,
    ProductFee,
    ProductVersion,
)
from core.services.loan_origination import preview_context, save_application_fields, submit_for_review
from core.api.origination_views import portal_origination_quote_preview
from core.services.origination_commercial_terms import (
    approve_commercial_exception,
    commercial_contract_enabled,
    ensure_commercial_catalogue,
    merge_commercial_contract,
    validate_commercial_terms,
)


class OriginationCommercialTermsTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.officer = users.objects.create_user(username='commercial-officer')
        self.superuser = users.objects.create_superuser(
            username='commercial-superuser', email='commercial@example.test', password='unused',
        )
        self.product = Product.objects.create(code='commercial-test', name='Commercial Test')
        self.version = ProductVersion.objects.create(
            product=self.product, version=1, status=ProductVersion.STATUS_DRAFT,
            currency='KES', min_amount='100.00', max_amount='1000.00',
            min_tenor=1, max_tenor=12, tenor_unit='month',
            interest_method='flat', interest_rate='0', interest_rate_period='annual',
            repayment_frequency='monthly', effective_from=timezone.localdate(),
        )
        fields = ensure_commercial_catalogue(actor=self.superuser)
        self.schema = merge_commercial_contract(
            {
                '_revision': 1,
                'sections': [{'key': 'application', 'label': 'Application'}],
                'fields': [],
            },
            fields=fields,
        )
        self.definition = OriginationProductDefinition.objects.create(
            product_version=self.version, product_key=self.product.code,
            name=self.product.name, version=1, form_schema=self.schema,
            signer_rules=[{'role': 'borrower'}], document_type='commercial_test_laf',
            created_by=self.superuser,
        )

    def payload(self, **overrides):
        values = {
            'loan_amount': '500.00',
            'repayment_tenor': '5',
        }
        values.update(overrides)
        return values

    def application(self, *, payload=None):
        return LoanOriginationApplication.objects.create(
            reference_number=f'ORG-COMM-{LoanOriginationApplication.objects.count() + 1}',
            product_definition=self.definition, product_version=self.version,
            officer=self.officer, schema_snapshot=self.schema,
            signer_rules_snapshot=self.definition.signer_rules,
            product_terms_snapshot={}, form_payload=payload or self.payload(),
        )

    def test_schema_merge_is_idempotent_and_exposes_only_amount_and_tenor(self):
        fields = ensure_commercial_catalogue(actor=self.superuser)
        second = merge_commercial_contract(self.schema, fields=fields)
        self.assertEqual(second, self.schema)
        self.assertTrue(commercial_contract_enabled(second))
        attached = {item['key']: item for item in second['fields']}
        self.assertEqual(set(attached), {'loan_amount', 'repayment_tenor'})
        self.assertEqual(attached['loan_amount']['source_type'], 'user_input')
        self.assertEqual(attached['repayment_tenor']['source_type'], 'user_input')
        catalogue = ensure_commercial_catalogue(actor=self.superuser)
        self.assertEqual(catalogue['installment_amount'].source_type, 'system')
        self.assertEqual(catalogue['contract_interest_method'].source_type, 'system')
        self.assertNotIn('repayment_period', attached)

    def test_validation_calculates_policy_terms_from_two_entered_values(self):
        application = self.application()
        result = validate_commercial_terms(application)
        self.assertTrue(result['ready'], result['findings'])
        self.assertEqual(result['entered_terms'], {
            'loan_amount': '500.00', 'repayment_tenor': '5',
        })
        self.assertEqual(result['expected_quote']['installment_amount'], '100.00')
        self.assertEqual(result['expected_quote']['inputs']['tenor_unit'], 'month')

    def test_derived_values_are_not_accepted_as_officer_authority(self):
        application = self.application(payload=self.payload(total_repayment_amount='1.00'))
        result = validate_commercial_terms(application)
        self.assertTrue(result['ready'])
        self.assertEqual(result['expected_quote']['total_repayment'], '500.00')
        self.assertNotIn('total_repayment_amount', result['entered_terms'])

    def test_invalid_numeric_input_cannot_be_waived(self):
        application = self.application(payload=self.payload(loan_amount='not-money'))
        result = validate_commercial_terms(application)
        self.assertIn(
            'loan_amount_invalid',
            {item['code'] for item in result['blocking_findings']},
        )
        with self.assertRaisesMessage(ValueError, 'internally inconsistent'):
            approve_commercial_exception(
                application=application, actor=self.superuser,
                reason='Invalid exception', approval_reference='APPROVAL-INVALID',
            )

    def test_mandatory_fees_are_automatic_and_optional_fees_are_excluded(self):
        ProductFee.objects.create(
            product_version=self.version, key='processing_fee', label='Processing Fee',
            fee_type=ProductFee.TYPE_FIXED, fixed_amount='10.00',
            collection_mode=ProductFee.COLLECTION_UPFRONT, mandatory=True,
        )
        ProductFee.objects.create(
            product_version=self.version, key='optional_fee', label='Optional Fee',
            fee_type=ProductFee.TYPE_FIXED, fixed_amount='50.00',
            collection_mode=ProductFee.COLLECTION_UPFRONT, mandatory=False,
        )
        result = validate_commercial_terms(
            self.application(), selected_fee_keys=['optional_fee'],
        )
        self.assertTrue(result['ready'], result['findings'])
        self.assertEqual(result['expected_quote']['upfront_fees'], '10.00')
        self.assertEqual(
            [row['key'] for row in result['expected_quote']['fees']],
            ['processing_fee'],
        )

    def test_policy_exception_is_exact_and_revision_bound(self):
        application = self.application(payload=self.payload(loan_amount='1100.00'))
        before = validate_commercial_terms(application)
        self.assertEqual(before['policy_mismatch_codes'], ['loan_amount_policy_mismatch'])
        exception = approve_commercial_exception(
            application=application, actor=self.superuser,
            reason='Approved negotiated pricing', approval_reference='MD-2026-001',
        )
        self.assertEqual(exception.covered_mismatch_codes, ['loan_amount_policy_mismatch'])
        after = validate_commercial_terms(application)
        self.assertTrue(after['ready'], after)
        application.revision += 1
        application.save(update_fields=['revision', 'updated_at'])
        self.assertFalse(validate_commercial_terms(application)['ready'])

    def test_draft_save_records_entered_and_expected_snapshots(self):
        application = self.application(payload={})
        saved = save_application_fields(
            application_id=application.pk, actor=self.officer, payload=self.payload(),
            expected_revision=application.revision, request_id='commercial-save-1',
        )
        event = OriginationApplicationEvent.objects.get(
            application=saved, request_id='commercial-save-1',
        )
        self.assertEqual(saved.form_payload['loan_amount'], '500.00')
        self.assertTrue(saved.product_quote_snapshot['commercial_validation']['ready'])
        self.assertEqual(event.metadata['commercial_terms']['loan_amount'], '500.00')
        self.assertTrue(event.metadata['expected_quote_sha256'])

    def test_policy_derived_values_remain_available_to_pdf_mapping(self):
        application = self.application(payload={})
        saved = save_application_fields(
            application_id=application.pk, actor=self.officer, payload=self.payload(),
            expected_revision=application.revision, request_id='commercial-pdf-context-1',
        )

        context = preview_context(saved)

        self.assertEqual(context['contract_currency'], 'KES')
        self.assertEqual(context['contract_interest_method'], 'flat')
        self.assertEqual(context['contract_repayment_frequency'], 'monthly')
        self.assertEqual(context['installment_amount'], '100.00')
        self.assertEqual(context['total_repayment_amount'], '500.00')
        self.assertEqual(context['repayment_period'], '5 month')

    def test_live_quote_preview_is_revision_checked_and_non_mutating(self):
        application = self.application(payload={})
        original_payload = dict(application.form_payload)
        request = RequestFactory().post(
            '/api/origination/api/applications/example/quote-preview/',
            data=json.dumps({
                'revision': application.revision,
                'loan_amount': '500.00',
                'repayment_tenor': '5',
            }),
            content_type='application/json',
        )
        request.portal_user = self.officer
        request.portal_access = None
        with patch('core.api.origination_views._capability_error', return_value=None), patch(
            'core.api.origination_views._application_access_error', return_value=None,
        ):
            response = portal_origination_quote_preview(request, str(application.pk))
        body = json.loads(response.content)
        application.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body['quote']['installment_amount'], '100.00')
        self.assertEqual(application.revision, 1)
        self.assertEqual(application.form_payload, original_payload)

        stale = RequestFactory().post(
            '/api/origination/api/applications/example/quote-preview/',
            data=json.dumps({
                'revision': 0, 'loan_amount': '500.00', 'repayment_tenor': '5',
            }),
            content_type='application/json',
        )
        stale.portal_user = self.officer
        stale.portal_access = None
        with patch('core.api.origination_views._capability_error', return_value=None), patch(
            'core.api.origination_views._application_access_error', return_value=None,
        ):
            stale_response = portal_origination_quote_preview(stale, str(application.pk))
        self.assertEqual(stale_response.status_code, 409)

    def test_submit_freezes_valid_exception_but_later_edit_would_invalidate_it(self):
        application = self.application(payload=self.payload(loan_amount='1100.00'))
        exception = approve_commercial_exception(
            application=application, actor=self.superuser,
            reason='Approved negotiated pricing', approval_reference='MD-2026-002',
        )
        OriginationApplicationEvent.objects.create(
            application=application, action='document_packet_previewed',
            revision=application.revision, actor=self.officer,
        )
        submitted = submit_for_review(
            application_id=application.pk, actor=self.officer,
            expected_revision=application.revision, request_id='commercial-submit-1',
        )
        self.assertEqual(submitted.status, submitted.STATUS_READY_FOR_REVIEW)
        frozen = submitted.product_quote_snapshot['commercial_validation']['exception']
        self.assertEqual(frozen['id'], str(exception.pk))

    def test_saving_a_new_revision_immediately_invalidates_old_exception_readiness(self):
        application = self.application(payload=self.payload(loan_amount='1100.00'))
        approve_commercial_exception(
            application=application, actor=self.superuser,
            reason='Approved negotiated pricing', approval_reference='MD-2026-003',
        )
        self.assertTrue(validate_commercial_terms(application)['ready'])
        saved = save_application_fields(
            application_id=application.pk, actor=self.officer,
            payload=self.payload(loan_amount='1100.00'),
            expected_revision=application.revision, request_id='commercial-save-after-exception',
        )
        readiness = saved.product_quote_snapshot['commercial_validation']
        self.assertFalse(readiness['ready'])
        self.assertIsNone(readiness['exception'])
        self.assertEqual(
            [item['code'] for item in readiness['blocking_findings']],
            ['loan_amount_policy_mismatch'],
        )

    def test_existing_application_schema_is_not_mutated_when_definition_upgrades(self):
        legacy_schema = {
            '_revision': 1,
            'sections': [{'key': 'application', 'label': 'Application'}],
            'fields': [{'key': 'customer_name', 'label': 'Applicant Name', 'type': 'text'}],
        }
        application = LoanOriginationApplication.objects.create(
            reference_number='ORG-LEGACY-COMM', product_definition=self.definition,
            product_version=self.version, officer=self.officer,
            schema_snapshot=legacy_schema, signer_rules_snapshot=[],
        )
        fields = ensure_commercial_catalogue(actor=self.superuser)
        self.definition.form_schema = merge_commercial_contract(legacy_schema, fields=fields)
        self.definition.save(update_fields=['form_schema', 'updated_at'])
        application.refresh_from_db()
        self.assertEqual(application.schema_snapshot, legacy_schema)
        self.assertFalse(commercial_contract_enabled(application.schema_snapshot))

    def test_admin_can_upgrade_one_linked_draft_commercial_contract(self):
        definition, legacy_schema = self._legacy_linked_definition('admin')
        self.client.force_login(self.superuser)
        change_url = reverse(
            'admin:core_originationproductdefinition_change', args=[definition.pk],
        )

        page = self.client.get(change_url)

        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'Commercial Terms contract v1')
        self.assertContains(page, 'Upgrade Commercial Terms')

        response = self.client.post(reverse(
            'admin:core_originationproductdefinition_upgrade_commercial_terms',
            args=[definition.pk],
        ))

        self.assertRedirects(response, change_url)
        definition.refresh_from_db()
        self.assertNotEqual(definition.form_schema, legacy_schema)
        self.assertTrue(commercial_contract_enabled(definition.form_schema))
        self.assertEqual(definition.form_schema['commercial_contract_version'], 2)
        event = definition.events.get(action='commercial_contract_upgraded')
        self.assertEqual(event.metadata['from_version'], 1)
        self.assertEqual(event.metadata['contract_version'], 2)
        self.assertEqual(event.metadata['source'], 'django_admin')

    def test_admin_commercial_upgrade_does_not_mutate_published_definition(self):
        definition, legacy_schema = self._legacy_linked_definition('published')
        definition.lifecycle_status = definition.STATUS_PUBLISHED
        definition.is_active = True
        definition.save(update_fields=['lifecycle_status', 'is_active', 'updated_at'])
        self.client.force_login(self.superuser)

        response = self.client.post(reverse(
            'admin:core_originationproductdefinition_upgrade_commercial_terms',
            args=[definition.pk],
        ))

        self.assertRedirects(response, reverse(
            'admin:core_originationproductdefinition_change', args=[definition.pk],
        ))
        definition.refresh_from_db()
        self.assertEqual(definition.form_schema, legacy_schema)
        self.assertFalse(definition.events.filter(action='commercial_contract_upgraded').exists())

    def _legacy_linked_definition(self, suffix):
        product = Product.objects.create(
            code=f'commercial-upgrade-{suffix}', name=f'Commercial Upgrade {suffix}',
        )
        version = ProductVersion.objects.create(
            product=product, version=1, status=ProductVersion.STATUS_DRAFT,
            currency='KES', min_amount='100.00', max_amount='1000.00',
            min_tenor=1, max_tenor=12, tenor_unit='month',
            interest_method='flat', interest_rate='0', interest_rate_period='annual',
            repayment_frequency='monthly', effective_from=timezone.localdate(),
        )
        schema = {
            '_revision': 1,
            'sections': [{'key': 'application', 'label': 'Application'}],
            'fields': [{'key': 'applicant_name', 'label': 'Applicant Name', 'type': 'text'}],
        }
        definition = OriginationProductDefinition.objects.create(
            product_version=version, product_key=product.code, name=product.name,
            version=1, form_schema=schema, signer_rules=[{'role': 'borrower'}],
            document_type=f'commercial_upgrade_{suffix}', created_by=self.superuser,
        )
        return definition, schema

    def test_signed_upgrade_manifest_updates_exact_draft_and_not_application_snapshot(self):
        definition, legacy_schema = self._legacy_linked_definition('apply')
        application = LoanOriginationApplication.objects.create(
            reference_number='ORG-COMM-UPGRADE-APP', product_definition=definition,
            product_version=definition.product_version, officer=self.officer,
            schema_snapshot=legacy_schema, signer_rules_snapshot=definition.signer_rules,
        )
        with TemporaryDirectory() as directory:
            manifest = Path(directory) / 'commercial-upgrade.manifest'
            call_command(
                'upgrade_origination_commercial_contract', manifest_out=str(manifest),
                stdout=StringIO(),
            )
            self.assertTrue(manifest.is_file())
            call_command(
                'upgrade_origination_commercial_contract', apply_manifest=str(manifest),
                actor=self.superuser.username, stdout=StringIO(),
            )
        definition.refresh_from_db()
        application.refresh_from_db()
        self.assertTrue(commercial_contract_enabled(definition.form_schema))
        self.assertEqual(application.schema_snapshot, legacy_schema)
        self.assertTrue(definition.events.filter(action='commercial_contract_upgraded').exists())

    def test_signed_upgrade_manifest_aborts_on_draft_drift(self):
        definition, _legacy_schema = self._legacy_linked_definition('drift')
        with TemporaryDirectory() as directory:
            manifest = Path(directory) / 'commercial-upgrade.manifest'
            call_command(
                'upgrade_origination_commercial_contract', manifest_out=str(manifest),
                stdout=StringIO(),
            )
            definition.form_schema = {**definition.form_schema, 'operator_note': 'changed after dry-run'}
            definition.save(update_fields=['form_schema', 'updated_at'])
            with self.assertRaisesMessage(CommandError, 'changed after dry-run'):
                call_command(
                    'upgrade_origination_commercial_contract', apply_manifest=str(manifest),
                    actor=self.superuser.username, stdout=StringIO(),
                )
        definition.refresh_from_db()
        self.assertFalse(commercial_contract_enabled(definition.form_schema))
