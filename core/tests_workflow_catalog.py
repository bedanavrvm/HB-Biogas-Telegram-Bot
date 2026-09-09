import json
from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model
from django.core.checks import run_checks
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import (
    GroupSheetConfiguration,
    OperationalLocation,
    ParsedMessage,
    Product,
    ProductAvailability,
    ProductTatConfiguration,
    ProductVersion,
)
from core.services.workflow_catalog import (
    MODE_CATALOG_PLUS_HISTORY,
    MODE_CATALOG_WITH_LEGACY_ENVIRONMENT,
    MODE_GROUP_CATALOG_SCOPE,
    RESOLUTION_MODES,
    SCOPE_CATALOG,
    SCOPE_SELECTED,
    apply_catalog_scope,
    resolve_workflow_catalog,
    scope_selection,
)
from core.services.workflow_presets import defaults_for_preset
from core.services.tat_tracker import product_by_key, serialize_product


@override_settings(SECURE_SSL_REDIRECT=False, TAT_TRACKER_BRANCH_CHOICES='')
class WorkflowCatalogResolutionTest(TestCase):
    def setUp(self):
        self.branch = OperationalLocation.objects.create(
            location_type='branch', name='Resolver Branch', code='RESOLVER-BRANCH',
            sort_order=900,
        )
        self.retired_branch = OperationalLocation.objects.create(
            location_type='branch', name='Retired Resolver Branch', code='RETIRED-RESOLVER-BRANCH',
            active=False, sort_order=901,
        )
        self.product = Product.objects.create(
            name='Resolver Product', code='resolver_product', sort_order=900,
        )
        self.version = ProductVersion.objects.create(
            product=self.product, version=1,
            min_amount=Decimal('12345.00'), max_amount=Decimal('98765.00'),
        )
        ProductTatConfiguration.objects.create(
            product_version=self.version, sheet_name='Resolver', case_prefix='RSLV',
            remarks_col=8, status_col=9, tat_start_col=10,
            stage_columns={'created': 4},
            stages=[{
                'key': 'created', 'label': 'Created', 'column': 4,
                'role': 'BRO', 'kind': 'timestamp',
            }],
            stage_tat_columns=[],
        )
        ProductVersion.objects.filter(pk=self.version.pk).update(status=ProductVersion.STATUS_PUBLISHED)
        self.version.refresh_from_db()

    def test_tat_amount_limits_are_loaded_from_the_active_product_version(self):
        configured_product = product_by_key(self.product.code)

        self.assertEqual(configured_product.min_amount, Decimal('12345.00'))
        self.assertEqual(configured_product.max_amount, Decimal('98765.00'))
        self.assertEqual(
            {
                key: value
                for key, value in serialize_product(configured_product).items()
                if key in {'min_amount', 'max_amount'}
            },
            {'min_amount': '12345.00', 'max_amount': '98765.00'},
        )

    def test_every_supported_workflow_has_one_named_resolution_mode(self):
        self.assertEqual(RESOLUTION_MODES, {
            'tat_tracker': 'group_catalog_scope',
            'spin_credit_analysis': 'group_catalog_scope',
            'loan_origination': 'availability_access_scope',
            'jawabu_portal': 'availability_access_scope',
            'order_approval': 'catalog_with_legacy_environment',
            'complaint_cases': 'catalog_plus_history',
            'fca': 'source_data_mapping',
            'fca_review': 'source_data_mapping',
        })

    def test_legacy_arrays_are_named_selected_restrictions(self):
        workflow = {
            'type': 'tat_tracker',
            'branches': [self.branch.name],
            'products': [self.product.code],
        }

        result = resolve_workflow_catalog(
            'tat_tracker', type('Config', (), {'workflow': workflow, 'group_id': ''})(),
        )

        self.assertEqual(result['resolution_mode'], MODE_GROUP_CATALOG_SCOPE)
        self.assertEqual(result['branch_scope_mode'], SCOPE_SELECTED)
        self.assertEqual(result['product_scope_mode'], SCOPE_SELECTED)
        self.assertEqual(result['effective_branches'], [self.branch.name])
        self.assertEqual(result['effective_products'], [self.product.code])

    def test_guided_scope_round_trip_preserves_unknown_keys(self):
        original = {
            'type': 'tat_tracker',
            'future_integration': {'enabled': True, 'revision': 7},
            'branches': [self.branch.name],
        }

        updated = apply_catalog_scope(
            original,
            branch_mode=SCOPE_CATALOG,
            branches=[],
            product_mode=SCOPE_SELECTED,
            products=[self.product.code],
        )

        self.assertEqual(updated['future_integration'], original['future_integration'])
        self.assertNotIn('branches', updated)
        self.assertEqual(updated['products'], [self.product.code])
        self.assertEqual(scope_selection(updated, 'branches')[0], SCOPE_CATALOG)

    def test_retired_and_unknown_values_have_specific_warning_codes(self):
        workflow = {
            'type': 'tat_tracker',
            'branches': [self.retired_branch.name, 'Never Catalogued'],
            'products': [self.product.code],
        }

        result = resolve_workflow_catalog(
            'tat_tracker', type('Config', (), {'workflow': workflow, 'group_id': ''})(),
        )

        warning_codes = {item['code'] for item in result['warnings']}
        self.assertIn('retired_branch', warning_codes)
        self.assertIn('unknown_legacy_value', warning_codes)

    def test_unavailable_selected_combination_has_a_named_reason(self):
        other_branch = OperationalLocation.objects.create(
            location_type='branch', name='Coverage Only Branch', code='COVERAGE-ONLY-BRANCH',
            sort_order=902,
        )
        ProductAvailability.objects.create(
            product=self.product, branch=other_branch,
            workflow='tat_tracker', channel='portal',
        )
        workflow = apply_catalog_scope(
            {'type': 'tat_tracker'},
            branch_mode=SCOPE_SELECTED, branches=[self.branch.name],
            product_mode=SCOPE_SELECTED, products=[self.product.code],
        )

        result = resolve_workflow_catalog(
            'tat_tracker', type('Config', (), {'workflow': workflow, 'group_id': ''})(),
        )

        warning = next(
            item for item in result['warnings']
            if item['code'] == 'unavailable_branch_product'
        )
        self.assertEqual(warning['value'], f'{self.product.code} / {self.branch.name}')

    def test_complaint_history_is_retained_but_named_historical_only(self):
        group = GroupSheetConfiguration.objects.create(
            group_id='-100-workflow-history', display_name='Complaint history',
            sheet_id='history-sheet', workflow={'type': 'case'},
        )
        from core.tests import create_parsed_case
        create_parsed_case(
            'workflow-history-1', group_id=group.group_id,
            branch_region='Closed Historical Branch',
        )

        result = resolve_workflow_catalog('complaint_cases', group)

        self.assertEqual(result['resolution_mode'], MODE_CATALOG_PLUS_HISTORY)
        self.assertIn('Closed Historical Branch', result['effective_branches'])
        warning = next(item for item in result['warnings'] if item['value'] == 'Closed Historical Branch')
        self.assertEqual(warning['code'], 'historical_branch_only')

    @override_settings(ORDER_APPROVAL_BRANCH_CHOICES='Legacy North,Legacy South')
    def test_order_environment_override_is_visible_and_named(self):
        result = resolve_workflow_catalog('order_approval')

        self.assertEqual(result['resolution_mode'], MODE_CATALOG_WITH_LEGACY_ENVIRONMENT)
        self.assertEqual(result['effective_branches'], ['Legacy North', 'Legacy South'])
        self.assertEqual(result['warnings'][0]['code'], 'legacy_environment_override')

    @override_settings(ORDER_APPROVAL_BRANCH_CHOICES='Legacy North,Legacy South')
    def test_order_environment_override_emits_a_deprecation_system_check(self):
        warnings = run_checks()

        self.assertIn('core.W001', {item.id for item in warnings})

    def test_new_tat_preset_uses_explicit_catalogue_mode_without_arrays(self):
        workflow = defaults_for_preset('tat_tracker')['workflow']

        self.assertNotIn('branches', workflow)
        self.assertNotIn('products', workflow)
        self.assertEqual(workflow['catalog_scope']['branches']['mode'], SCOPE_CATALOG)
        self.assertEqual(workflow['catalog_scope']['products']['mode'], SCOPE_CATALOG)


@override_settings(SECURE_SSL_REDIRECT=False, TAT_TRACKER_BRANCH_CHOICES='')
class GuidedWorkflowConfigurationAdminTest(TestCase):
    def setUp(self):
        self.branch = OperationalLocation.objects.create(
            location_type='branch', name='Guided Branch', code='GUIDED-BRANCH',
            sort_order=920,
        )
        self.product = Product.objects.create(
            name='Guided Product', code='guided_product', sort_order=920,
        )
        self.group = GroupSheetConfiguration.objects.create(
            group_id='-100-guided-config', display_name='Guided TAT', sheet_id='',
            tat_sheet_projection_enabled=False,
            workflow={
                'type': 'tat_tracker', 'branches': [self.branch.name],
                'products': [self.product.code],
                'future_option': {'must_survive': True},
            },
        )
        self.admin_user = get_user_model().objects.create_superuser(
            username='workflow-admin', email='workflow-admin@example.test', password='password',
        )
        self.client.force_login(self.admin_user)

    def test_preset_form_uses_guided_fields_and_round_trips_unknown_workflow_keys(self):
        from core.admin import GroupSheetConfigurationAdminForm

        unbound = GroupSheetConfigurationAdminForm(instance=self.group)
        self.assertIsInstance(unbound.fields['case_field_headers'], forms.CharField)
        self.assertNotIsInstance(unbound.fields['case_field_headers'], forms.JSONField)
        self.assertIn('manual-json-section', {
            class_name
            for _title, options in __import__('core.admin', fromlist=['GroupSheetConfigurationAdmin']).GroupSheetConfigurationAdmin.fieldsets
            for class_name in options.get('classes', ())
        })

        data = {
            'workflow_preset': 'tat_tracker',
            'group_id': self.group.group_id,
            'display_name': self.group.display_name,
            'enabled': 'on',
            'sheet_id': '',
            'sheet_name': self.group.sheet_name,
            'sheet_schema': '{}',
            'workflow': json.dumps(self.group.workflow),
            'parser_rules': '{}',
            'metadata': '{}',
            'catalog_branch_mode': SCOPE_SELECTED,
            'catalog_branches': [self.branch.name],
            'catalog_product_mode': SCOPE_SELECTED,
            'catalog_products': [self.product.code],
        }
        form = GroupSheetConfigurationAdminForm(data=data, instance=self.group)

        self.assertTrue(form.is_valid(), form.errors)
        generated = form.generated_workflow()
        self.assertEqual(generated['future_option'], {'must_survive': True})
        self.assertEqual(generated['branches'], [self.branch.name])
        self.assertEqual(generated['products'], [self.product.code])

    def test_manual_form_keeps_the_technical_json_escape_hatch(self):
        from core.admin import GroupSheetConfigurationAdminForm

        form = GroupSheetConfigurationAdminForm(
            data={'workflow_preset': 'manual'}, instance=self.group,
        )

        self.assertNotIsInstance(form.fields['workflow'].widget, forms.HiddenInput)

    def test_guided_form_rejects_a_stale_configuration_submission(self):
        from core.admin import GroupSheetConfigurationAdminForm

        expected = self.group.updated_at.isoformat()
        GroupSheetConfiguration.objects.filter(pk=self.group.pk).update(
            display_name='Changed elsewhere', updated_at=timezone.now(),
        )
        form = GroupSheetConfigurationAdminForm(data={
            'workflow_preset': 'tat_tracker',
            'expected_updated_at': expected,
            'group_id': self.group.group_id,
            'display_name': self.group.display_name,
            'enabled': 'on',
            'sheet_id': '',
            'sheet_name': self.group.sheet_name,
            'sheet_schema': '{}',
            'workflow': json.dumps(self.group.workflow),
            'parser_rules': '{}',
            'metadata': '{}',
            'catalog_branch_mode': SCOPE_SELECTED,
            'catalog_branches': [self.branch.name],
            'catalog_product_mode': SCOPE_SELECTED,
            'catalog_products': [self.product.code],
        }, instance=self.group)

        self.assertFalse(form.is_valid())
        self.assertIn('changed in another session', str(form.non_field_errors()))

    def test_mapping_rows_are_structured_and_legacy_json_paste_is_compatible(self):
        from core.admin import _format_mapping_rows, _parse_mapping_rows

        mapping = {'complaint_id': 'Complaint ID', 'message_id': 'Message ID'}
        self.assertEqual(_parse_mapping_rows(_format_mapping_rows(mapping)), mapping)
        self.assertEqual(_parse_mapping_rows(json.dumps(mapping)), mapping)

    def test_configuration_workspace_shows_effective_result_and_reason_codes(self):
        response = self.client.get(reverse('admin:core_workflow_configuration'), secure=True)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Guided TAT')
        self.assertContains(response, MODE_GROUP_CATALOG_SCOPE)
        self.assertContains(response, 'Configure workflow')
