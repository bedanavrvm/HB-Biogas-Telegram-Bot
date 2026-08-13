import io
import json

from django.core.management import CommandError, call_command
from django.core.exceptions import ValidationError
from django.test import TestCase

from core.models import JawabuCustomer, JawabuFarmerMaster, OperationalProduct
from core.services.jawabu_data_quality import active_jawabu_quality_report
from core.services.jawabu_validation import canonicalize_farmer, refresh_data_quality_issues
from core.services.access_policies import validate_access_scope


class JawabuDataQualityTests(TestCase):
    def setUp(self):
        OperationalProduct.objects.get_or_create(name='Biogas', defaults={'code': 'biogas', 'active': True})

    def test_non_standard_national_id_is_a_review_issue_not_a_hard_import_error(self):
        farmer = JawabuFarmerMaster.objects.create(
            customer_name='Quality Farmer', national_id='123456', primary_phone='254712345678', status='active',
        )

        errors = canonicalize_farmer(farmer, strict=True)
        refresh_data_quality_issues(farmer)

        self.assertIn('national_id', errors)
        self.assertTrue(farmer.data_quality_issues.filter(code='review_required', active=True).exists())

    def test_quality_report_flags_reference_and_duplicate_identity_issues_without_writing(self):
        first = JawabuFarmerMaster.objects.create(
            customer_name='First', national_id='12345678', primary_phone='254712345678',
            branch='Unknown Branch', county='Unknown County', payment_product='Unknown Product', status='active',
        )
        JawabuFarmerMaster.objects.create(
            customer_name='Second', national_id='12345678', primary_phone='254700000000', status='active',
        )

        report = active_jawabu_quality_report()

        self.assertGreaterEqual(report['finding_count'], 4)
        self.assertIn('unknown_branch', report['by_code'])
        self.assertIn('unknown_county', report['by_code'])
        self.assertIn('unknown_product', report['by_code'])
        self.assertIn('duplicate_active_identity', report['by_code'])
        self.assertTrue(any(item['farmer_id'] == str(first.id) for item in report['findings']))

    def test_audit_command_is_read_only_and_can_fail_strictly(self):
        JawabuFarmerMaster.objects.create(
            customer_name='Needs Review', national_id='123456', primary_phone='254712345678', status='active',
        )
        output = io.StringIO()

        call_command('audit_jawabu_data_quality', stdout=output)

        payload = json.loads(output.getvalue())
        self.assertGreater(payload['active_jawabu']['finding_count'], 0)
        with self.assertRaises(CommandError):
            call_command('audit_jawabu_data_quality', '--strict', stdout=io.StringIO())

    def test_repeat_unit_applications_for_one_customer_are_not_identity_duplicates(self):
        customer = JawabuCustomer.objects.create(
            national_id='12345678', primary_phone='254712345678', customer_no='C-123',
        )
        for unit_number in (1, 2):
            JawabuFarmerMaster.objects.create(
                customer=customer,
                unit_number=unit_number,
                customer_name='Repeat Unit Customer',
                national_id='12345678',
                customer_no='C-123',
                primary_phone='254712345678',
                status='active',
            )

        report = active_jawabu_quality_report()

        self.assertNotIn('duplicate_active_identity', report['by_code'])
        self.assertNotIn('duplicate_active_customer_no', report['by_code'])

    def test_product_codes_are_normalized_to_access_scope_keys(self):
        product = OperationalProduct(name='Micro Asset', code='MICRO ASSET')

        product.clean()

        self.assertEqual(product.code, 'micro_asset')

    def test_tat_access_product_scope_uses_the_controlled_catalog(self):
        # Products are durable catalogue identities once terms have been published.
        OperationalProduct.objects.update(active=False)
        business, _ = OperationalProduct.objects.get_or_create(
            name='Business', defaults={'code': 'business', 'active': True},
        )
        business.active = True
        business.save(update_fields=['active', 'updated_at'])

        role = validate_access_scope(
            workflow='tat_tracker', role='BRO', product='business', branch='', group_configuration=None,
        )

        self.assertEqual(role, 'BRO')
        with self.assertRaises(ValidationError):
            validate_access_scope(
                workflow='tat_tracker', role='BRO', product='kilimo', branch='', group_configuration=None,
            )
