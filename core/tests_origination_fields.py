from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from core.models import (
    LoanOriginationApplication,
    OriginationDataField,
    OriginationDataFieldEvent,
    OriginationDocumentTemplate,
    OriginationFieldReviewIssue,
    OriginationProductDefinition,
    OriginationReportingValue,
)
from core.services.loan_origination import (
    prepare_signing_package,
    preview_context,
    validate_form_payload,
)
from core.services.origination_fields import (
    OriginationFieldConflict,
    OriginationFieldError,
    attach_data_field,
    bind_compatible_schema_fields,
    catalogue_for_product,
    correct_draft_data_field_type,
    create_data_field,
    masked_reporting_value,
    project_reporting_values,
    resolve_review_issue,
    snapshot_form_schema,
)
from core.services.origination_templates import clone_product_version


class OriginationDataFieldCatalogueTests(TestCase):
    def setUp(self):
        self.superuser = get_user_model().objects.create_superuser(
            'catalogue-root', 'catalogue@example.test', 'x',
        )
        self.officer = get_user_model().objects.create_user(
            'field-officer', 'officer@example.test', 'x',
        )
        self.product = OriginationProductDefinition.objects.create(
            product_key='catalogue-test', name='Catalogue Test', version=1,
            form_schema={
                '_revision': 0,
                'sections': [{'key': 'applicant', 'label': 'Applicant'}],
                'fields': [],
            },
            signer_rules=[{
                'role': 'borrower', 'required': True,
                'slots': [{'key': 'signature', 'type': 'signature', 'required': True}],
            }],
            document_type='catalogue-test',
            lifecycle_status=OriginationProductDefinition.STATUS_DRAFT,
            created_by=self.superuser,
        )

    def test_create_is_idempotent_and_key_is_immutable(self):
        field, replayed = create_data_field(
            payload={
                'label': 'Customer National ID', 'key': 'customer_national_id_test',
                'type': 'national_id', 'aliases': ['Applicant ID', 'ID Number'],
                'sensitivity': 'pii',
            },
            actor=self.superuser,
        )
        duplicate, replayed_duplicate = create_data_field(
            payload={
                'label': 'ID Number', 'key': 'customer_national_id_test',
                'type': 'national_id',
            },
            actor=self.superuser,
        )

        self.assertFalse(replayed)
        self.assertTrue(replayed_duplicate)
        self.assertEqual(duplicate.pk, field.pk)
        self.assertEqual(field.sensitivity, OriginationDataField.SENSITIVITY_PII)
        self.assertEqual(field.events.filter(action='created').count(), 1)
        field.key = 'changed_key'
        with self.assertRaisesMessage(ValidationError, 'immutable'):
            field.save()
        with self.assertRaises(OriginationFieldConflict):
            create_data_field(
                payload={
                    'label': 'Conflicting ID', 'key': 'customer_national_id_test',
                    'type': 'money',
                },
                actor=self.superuser,
            )

    def test_superuser_can_correct_type_across_draft_contracts(self):
        field, _ = create_data_field(
            payload={
                'label': 'Applicant ID', 'key': 'applicant_id_type_correction_test',
                'type': 'number', 'sensitivity': 'pii',
            },
            actor=self.superuser,
        )
        product, _ = attach_data_field(
            product=self.product, data_field=field,
            presentation={
                'section_key': 'applicant',
                'validation': {'min': 1, 'max': 99999999},
            },
            actor=self.superuser, expected_schema_revision=0,
        )
        template = OriginationDocumentTemplate.objects.create(
            product_definition=product, document_type=product.document_type,
            document_key='supporting_id', document_role='supporting',
            name='Supporting ID', version=1, source_filename='support.pdf',
            source_sha256='c' * 64, source_byte_size=100, page_count=1,
            form_schema={
                'fields': [{
                    'data_field_id': str(field.pk), 'key': field.key,
                    'type': 'number', 'validation': {'min': 1},
                }],
            },
            placement_config={}, created_by=self.superuser,
        )

        summary = correct_draft_data_field_type(
            data_field=field, new_type=OriginationDataField.TYPE_NATIONAL_ID,
            choice_options=[], structure_schema={}, actor=self.superuser,
        )

        field.refresh_from_db()
        product.refresh_from_db()
        template.refresh_from_db()
        self.assertEqual(field.data_type, OriginationDataField.TYPE_NATIONAL_ID)
        self.assertEqual(product.form_schema['fields'][0]['type'], 'national_id')
        self.assertEqual(product.form_schema['fields'][0]['validation'], {})
        self.assertEqual(template.form_schema['fields'][0]['type'], 'national_id')
        self.assertEqual(summary, {'product_schemas': 1, 'template_schemas': 1})

    def test_type_correction_is_blocked_after_application_snapshot(self):
        field, _ = create_data_field(
            payload={
                'label': 'Frozen Applicant ID', 'key': 'frozen_applicant_id_test',
                'type': 'number', 'sensitivity': 'pii',
            },
            actor=self.superuser,
        )
        product, _ = attach_data_field(
            product=self.product, data_field=field,
            presentation={'section_key': 'applicant'}, actor=self.superuser,
            expected_schema_revision=0,
        )
        LoanOriginationApplication.objects.create(
            reference_number='ORG-FROZEN-TYPE', product_definition=product,
            officer=self.officer, branch='Nairobi',
            schema_snapshot=snapshot_form_schema(product.form_schema),
        )

        with self.assertRaisesMessage(OriginationFieldError, 'application schema snapshots'):
            correct_draft_data_field_type(
                data_field=field, new_type=OriginationDataField.TYPE_NATIONAL_ID,
                choice_options=[], structure_schema={}, actor=self.superuser,
            )
        field.refresh_from_db()
        self.assertEqual(field.data_type, OriginationDataField.TYPE_NUMBER)

    def test_admin_shows_frozen_type_error_without_server_error(self):
        field, _ = create_data_field(
            payload={
                'label': 'Admin Frozen ID', 'key': 'admin_frozen_id_test',
                'type': 'number', 'sensitivity': 'pii',
            },
            actor=self.superuser,
        )
        product, _ = attach_data_field(
            product=self.product, data_field=field,
            presentation={'section_key': 'applicant'}, actor=self.superuser,
            expected_schema_revision=0,
        )
        LoanOriginationApplication.objects.create(
            reference_number='ORG-ADMIN-FROZEN-TYPE', product_definition=product,
            officer=self.officer, branch='Nairobi',
            schema_snapshot=snapshot_form_schema(product.form_schema),
        )
        self.client.force_login(self.superuser)

        response = self.client.post(
            reverse('admin:core_originationdatafield_change', args=[field.pk]),
            {
                'label': field.label, 'aliases': '[]', 'category': field.category,
                'data_type': OriginationDataField.TYPE_NATIONAL_ID,
                'source_type': field.source_type, 'sensitivity': field.sensitivity,
                'masking_policy': field.masking_policy,
                'reporting_use': field.reporting_use, 'help_text': '',
                'choice_options': '[]', 'active': 'on', '_save': 'Save',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'This type is frozen')
        field.refresh_from_db()
        self.assertEqual(field.data_type, OriginationDataField.TYPE_NUMBER)

    def test_admin_corrects_draft_only_type_and_records_audit(self):
        field, _ = create_data_field(
            payload={
                'label': 'Draft Applicant ID', 'key': 'draft_applicant_id_admin_test',
                'type': 'number', 'sensitivity': 'pii',
            },
            actor=self.superuser,
        )
        product, _ = attach_data_field(
            product=self.product, data_field=field,
            presentation={'section_key': 'applicant'}, actor=self.superuser,
            expected_schema_revision=0,
        )
        self.client.force_login(self.superuser)

        response = self.client.post(
            reverse('admin:core_originationdatafield_change', args=[field.pk]),
            {
                'label': field.label, 'aliases': '[]', 'category': field.category,
                'data_type': OriginationDataField.TYPE_NATIONAL_ID,
                'source_type': field.source_type, 'sensitivity': field.sensitivity,
                'masking_policy': field.masking_policy,
                'reporting_use': field.reporting_use, 'help_text': '',
                'choice_options': '[]', 'active': 'on', '_save': 'Save',
            },
        )

        self.assertEqual(response.status_code, 302)
        field.refresh_from_db()
        product.refresh_from_db()
        self.assertEqual(field.data_type, OriginationDataField.TYPE_NATIONAL_ID)
        self.assertEqual(product.form_schema['fields'][0]['type'], 'national_id')
        event = field.events.filter(action='updated').latest('occurred_at')
        self.assertIn('data_type', event.metadata['changed_fields'])
        self.assertEqual(event.metadata['draft_contracts_updated']['product_schemas'], 1)

    def test_admin_can_change_future_governance_without_rewriting_snapshot(self):
        field, _ = create_data_field(
            payload={
                'label': 'Applicant note', 'key': 'applicant_note_governance_test',
                'type': 'text', 'sensitivity': 'pii', 'help_text': 'Original guidance',
            },
            actor=self.superuser,
        )
        product, _ = attach_data_field(
            product=self.product, data_field=field,
            presentation={'section_key': 'applicant'}, actor=self.superuser,
            expected_schema_revision=0,
        )
        application = LoanOriginationApplication.objects.create(
            reference_number='ORG-GOVERNANCE-SNAPSHOT', product_definition=product,
            officer=self.officer, branch='Nairobi',
            schema_snapshot=snapshot_form_schema(product.form_schema),
        )
        self.client.force_login(self.superuser)

        response = self.client.post(
            reverse('admin:core_originationdatafield_change', args=[field.pk]),
            {
                'label': field.label, 'aliases': '[]', 'category': field.category,
                'data_type': field.data_type, 'source_type': field.source_type,
                'sensitivity': OriginationDataField.SENSITIVITY_INTERNAL,
                'masking_policy': OriginationDataField.MASK_NONE,
                'reporting_use': field.reporting_use,
                'help_text': 'Guidance for future forms',
                'choice_options': '[]', 'active': 'on', '_save': 'Save',
            },
        )

        self.assertEqual(response.status_code, 302)
        field.refresh_from_db()
        application.refresh_from_db()
        self.assertEqual(field.sensitivity, OriginationDataField.SENSITIVITY_INTERNAL)
        self.assertEqual(field.help_text, 'Guidance for future forms')
        frozen = application.schema_snapshot['fields'][0]
        self.assertEqual(frozen['sensitivity'], OriginationDataField.SENSITIVITY_PII)
        self.assertEqual(frozen['help_text'], 'Original guidance')

    def test_catalogue_exposes_seeded_fields_not_only_four_system_placeholders(self):
        catalogue = catalogue_for_product(self.product)

        self.assertGreater(len(catalogue), 4)
        self.assertIn('applicant_id_number', {item['key'] for item in catalogue})
        self.assertIn('loan_amount', {item['key'] for item in catalogue})
        self.assertIn('reference_number', {item['key'] for item in catalogue})

    def test_choice_codes_are_global_while_product_uses_subset_and_labels(self):
        field, _ = create_data_field(
            payload={
                'label': 'Marital status', 'key': 'marital_status_test',
                'type': 'choice',
                'choice_options': ['Single', 'Married', 'Separated'],
            },
            actor=self.superuser,
        )
        product, replayed = attach_data_field(
            product=self.product, data_field=field,
            presentation={
                'section_key': 'applicant', 'label': 'Civil status',
                'required': True, 'width': 'half',
                'options': [
                    {'code': 'married', 'label': 'Married / customary'},
                    {'code': 'single', 'label': 'Single'},
                ],
            },
            actor=self.superuser, expected_schema_revision=0,
        )
        spec = product.form_schema['fields'][0]

        self.assertFalse(replayed)
        self.assertEqual(spec['key'], 'marital_status_test')
        self.assertEqual(spec['label'], 'Civil status')
        self.assertEqual(
            spec['options'],
            [
                {'code': 'married', 'label': 'Married / customary'},
                {'code': 'single', 'label': 'Single'},
            ],
        )
        self.assertTrue(validate_form_payload(
            product.form_schema, {'marital_status_test': 'married'}, require_complete=True,
        ).valid)
        invalid = validate_form_payload(
            product.form_schema, {'marital_status_test': 'separated'}, require_complete=True,
        )
        self.assertEqual(invalid.errors['marital_status_test'], 'Choose an available option.')

        application = LoanOriginationApplication.objects.create(
            reference_number='ORG-CATALOGUE-CHOICE', product_definition=product,
            officer=self.officer, branch='Nairobi',
            form_payload={'marital_status_test': 'married'},
            schema_snapshot=snapshot_form_schema(product.form_schema),
        )
        self.assertEqual(preview_context(application)['marital_status_test'], 'Married / customary')

    def test_attach_retry_is_idempotent_even_with_stale_schema_revision(self):
        field, _ = create_data_field(
            payload={'label': 'Farm acreage', 'key': 'farm_acreage_test', 'type': 'number'},
            actor=self.superuser,
        )
        product, first_replay = attach_data_field(
            product=self.product, data_field=field,
            presentation={'section_key': 'applicant'}, actor=self.superuser,
            expected_schema_revision=0,
        )
        retried, second_replay = attach_data_field(
            product=product, data_field=field,
            presentation={'section_key': 'applicant'}, actor=self.superuser,
            expected_schema_revision=0,
        )

        self.assertFalse(first_replay)
        self.assertTrue(second_replay)
        self.assertEqual(len(retried.form_schema['fields']), 1)
        self.assertEqual(field.events.filter(action='attached').count(), 1)

    def test_successor_legacy_conflict_has_a_required_review_exit(self):
        canonical, _ = create_data_field(
            payload={'label': 'Existing concept', 'key': 'legacy_collision_test', 'type': 'text'},
            actor=self.superuser,
        )
        self.product.form_schema['fields'] = [{
            'key': 'legacy_collision_test', 'label': 'Old numeric meaning',
            'type': 'money', 'section_key': 'applicant',
        }]
        self.product.lifecycle_status = OriginationProductDefinition.STATUS_PUBLISHED
        self.product.is_active = True
        self.product.save(update_fields=['form_schema', 'lifecycle_status', 'is_active'])

        clone = clone_product_version(self.product, actor=self.superuser)
        issue = clone.field_review_issues.get()
        self.assertEqual(issue.reason, 'type_conflict')
        self.assertEqual(issue.suggested_field, canonical)
        self.assertEqual(issue.status, OriginationFieldReviewIssue.STATUS_OPEN)

        resolve_review_issue(
            issue=issue, status=OriginationFieldReviewIssue.STATUS_ACCEPTED,
            resolution_field=None, notes='Historical vendor field awaiting a replacement LAF.',
            actor=self.superuser,
        )
        issue.refresh_from_db()
        self.assertEqual(issue.status, OriginationFieldReviewIssue.STATUS_ACCEPTED)
        self.assertTrue(clone.events.filter(action='legacy_field_accepted').exists())

    def test_reporting_projection_is_typed_snapshot_driven_and_idempotent(self):
        amount, _ = create_data_field(
            payload={
                'label': 'Requested amount', 'key': 'requested_amount_reporting_test',
                'type': 'money', 'sensitivity': 'financial',
                'reporting_use': 'metric', 'export_allowed': True,
            },
            actor=self.superuser,
        )
        restricted, _ = create_data_field(
            payload={
                'label': 'Restricted note', 'key': 'restricted_note_reporting_test',
                'type': 'text', 'sensitivity': 'restricted',
                'reporting_use': 'filter',
            },
            actor=self.superuser,
        )
        product, _ = attach_data_field(
            product=self.product, data_field=amount,
            presentation={'section_key': 'applicant'}, actor=self.superuser,
            expected_schema_revision=0,
        )
        product, _ = attach_data_field(
            product=product, data_field=restricted,
            presentation={'section_key': 'applicant'}, actor=self.superuser,
            expected_schema_revision=1,
        )
        application = LoanOriginationApplication.objects.create(
            reference_number='ORG-CATALOGUE-REPORT', product_definition=product,
            officer=self.officer, branch='Nairobi', status=LoanOriginationApplication.STATUS_REVIEWED,
            revision=3,
            form_payload={
                amount.key: '125000.50', restricted.key: 'Never project this value',
            },
            schema_snapshot=snapshot_form_schema(product.form_schema),
            signer_rules_snapshot=product.signer_rules,
        )

        with patch('core.services.compliance_audit.record_event'):
            package, replayed = prepare_signing_package(
                application_id=application.pk, actor=self.superuser,
                expected_revision=3, request_id='report-freeze-1',
            )
            repeated, replayed_again = prepare_signing_package(
                application_id=application.pk, actor=self.superuser,
                expected_revision=3, request_id='report-freeze-1',
            )

        self.assertFalse(replayed)
        self.assertTrue(replayed_again)
        self.assertEqual(repeated.pk, package.pk)
        self.assertFalse(application.reporting_values.filter(data_field=restricted).exists())
        row = OriginationReportingValue.objects.get(application=application, data_field=amount)
        self.assertEqual(row.decimal_value, Decimal('125000.5000'))
        self.assertEqual(row.sensitivity, 'financial')
        self.assertNotEqual(masked_reporting_value(row), Decimal('125000.5000'))
        self.assertEqual(
            masked_reporting_value(row, allow_sensitive_export=True),
            Decimal('125000.5000'),
        )
        projected_count = project_reporting_values(application)
        self.assertEqual(projected_count, application.reporting_values.count())
        self.assertEqual(
            application.reporting_values.filter(application=application).values('data_field').distinct().count(),
            projected_count,
        )

    def test_mapper_can_create_attach_and_reuse_a_custom_field(self):
        template = OriginationDocumentTemplate.objects.create(
            product_definition=self.product, document_type=self.product.document_type,
            name='Catalogue test LAF', version=1, source_filename='test.pdf',
            source_sha256='a' * 64, source_byte_size=100, page_count=1,
            placement_config={}, created_by=self.superuser,
        )
        self.client.force_login(self.superuser)
        url = reverse(
            'admin:core_originationdocumenttemplate_calibration_field', args=[template.pk],
        )
        body = {
            'schema_revision': 0,
            'create_field': {
                'label': 'Applicant trading name', 'key': 'trading_name_mapper_test',
                'type': 'text', 'sensitivity': 'pii',
                'aliases': ['Business name'],
            },
            'presentation': {
                'section_key': 'applicant', 'label': 'Trading name',
                'required': True, 'width': 'full',
            },
        }
        response = self.client.post(url, body, content_type='application/json')
        retry = self.client.post(url, body, content_type='application/json')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(retry.status_code, 200)
        self.assertFalse(response.json()['replayed'])
        self.assertTrue(retry.json()['replayed'])
        self.product.refresh_from_db()
        self.assertEqual(len(self.product.form_schema['fields']), 1)
        field = OriginationDataField.objects.get(key='trading_name_mapper_test')
        self.assertEqual(field.events.filter(action='created').count(), 1)
        self.assertEqual(field.events.filter(action='attached').count(), 1)
        self.assertNotIn('Trading name', str(list(OriginationDataFieldEvent.objects.values_list('metadata', flat=True))))

        staff = get_user_model().objects.create_user(
            'catalogue-staff', 'staff@example.test', 'x', is_staff=True,
        )
        self.client.force_login(staff)
        forbidden = self.client.post(url, body, content_type='application/json')
        self.assertEqual(forbidden.status_code, 403)
