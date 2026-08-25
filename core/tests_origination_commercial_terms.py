from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

from core.models import (
    LoanOriginationApplication,
    OriginationApplicationEvent,
    OriginationProductDefinition,
    Product,
    ProductFee,
    ProductVersion,
)
from core.services.loan_origination import save_application_fields, submit_for_review
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
            'repayment_tenor_unit': 'month',
            'contract_currency': 'kes',
            'contract_interest_rate_percent': '0',
            'contract_interest_method': 'flat',
            'contract_interest_rate_period': 'annual',
            'contract_repayment_frequency': 'monthly',
            'installment_count': '5',
            'installment_amount': '100.00',
            'final_installment_amount': '100.00',
            'financed_principal_amount': '500.00',
            'total_interest_amount': '0.00',
            'total_repayment_amount': '500.00',
            'financed_fee_total': '0.00',
            'upfront_fee_total': '0.00',
            'loan_fees': [],
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

    def test_schema_merge_is_idempotent_and_uses_officer_inputs(self):
        fields = ensure_commercial_catalogue(actor=self.superuser)
        second = merge_commercial_contract(self.schema, fields=fields)
        self.assertEqual(second, self.schema)
        self.assertTrue(commercial_contract_enabled(second))
        attached = {item['key']: item for item in second['fields']}
        self.assertTrue(attached['installment_amount']['required'])
        self.assertEqual(attached['installment_amount']['source_type'], 'user_input')
        self.assertNotIn('repayment_period', attached)

    def test_validation_accepts_consistent_terms_and_preserves_entered_values(self):
        application = self.application()
        result = validate_commercial_terms(application)
        self.assertTrue(result['ready'], result['findings'])
        self.assertEqual(result['entered_terms']['installment_amount'], '100.00')
        self.assertEqual(result['expected_quote']['installment_amount'], '100.00')

    def test_internal_arithmetic_cannot_be_waived(self):
        application = self.application(payload=self.payload(total_repayment_amount='510.00'))
        result = validate_commercial_terms(application)
        codes = {item['code'] for item in result['blocking_findings']}
        self.assertIn('total_repayment_inconsistent', codes)
        with self.assertRaisesMessage(ValueError, 'internally inconsistent'):
            approve_commercial_exception(
                application=application, actor=self.superuser,
                reason='Test exception', approval_reference='APPROVAL-1',
            )

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

    def test_fee_rows_keep_policy_identity_but_amount_is_officer_entered(self):
        ProductFee.objects.create(
            product_version=self.version, key='processing_fee', label='Processing Fee',
            fee_type=ProductFee.TYPE_FIXED, fixed_amount='10.00',
            collection_mode=ProductFee.COLLECTION_UPFRONT, mandatory=True,
        )
        payload = self.payload(
            upfront_fee_total='11.00',
            loan_fees=[{
                'fee_key': 'processing_fee', 'fee_label': 'Processing Fee',
                'collection_mode': 'upfront', 'amount': '11.00',
            }],
        )
        result = validate_commercial_terms(self.application(payload=payload))
        codes = {item['code'] for item in result['blocking_findings']}
        self.assertIn('upfront_fee_policy_mismatch', codes)
        self.assertIn('fee_processing_fee_amount_mismatch', codes)
        self.assertNotIn('upfront_fee_total_inconsistent', codes)

        payload['loan_fees'][0]['collection_mode'] = 'financed'
        identity_result = validate_commercial_terms(self.application(payload=payload))
        identity_codes = {item['code'] for item in identity_result['blocking_findings']}
        self.assertIn('fee_processing_fee_identity_mismatch', identity_codes)
        with self.assertRaisesMessage(ValueError, 'internally inconsistent'):
            approve_commercial_exception(
                application=self.application(payload=payload), actor=self.superuser,
                reason='Cannot waive fee identity', approval_reference='APPROVAL-FEE-ID',
            )

    def test_policy_exception_is_exact_and_revision_bound(self):
        application = self.application(payload=self.payload(contract_interest_rate_percent='1'))
        before = validate_commercial_terms(application)
        self.assertEqual(before['policy_mismatch_codes'], ['interest_rate_policy_mismatch'])
        exception = approve_commercial_exception(
            application=application, actor=self.superuser,
            reason='Approved negotiated pricing', approval_reference='MD-2026-001',
        )
        self.assertEqual(exception.covered_mismatch_codes, ['interest_rate_policy_mismatch'])
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

    def test_submit_freezes_valid_exception_but_later_edit_would_invalidate_it(self):
        application = self.application(payload=self.payload(contract_interest_rate_percent='1'))
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
        application = self.application(payload=self.payload(contract_interest_rate_percent='1'))
        approve_commercial_exception(
            application=application, actor=self.superuser,
            reason='Approved negotiated pricing', approval_reference='MD-2026-003',
        )
        self.assertTrue(validate_commercial_terms(application)['ready'])
        saved = save_application_fields(
            application_id=application.pk, actor=self.officer,
            payload=self.payload(contract_interest_rate_percent='1'),
            expected_revision=application.revision, request_id='commercial-save-after-exception',
        )
        readiness = saved.product_quote_snapshot['commercial_validation']
        self.assertFalse(readiness['ready'])
        self.assertIsNone(readiness['exception'])
        self.assertEqual(
            [item['code'] for item in readiness['blocking_findings']],
            ['interest_rate_policy_mismatch'],
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
