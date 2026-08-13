from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import (
    ComplianceAuditChainState,
    ComplianceAuditEvent,
    JawabuFarmerMaster,
    OperationalLocation,
    Product,
    ProductAlias,
    ProductAvailability,
    ProductCustomAttribute,
    ProductFee,
    ProductMappingIssue,
    ProductRequirement,
    ProductVersion,
    ProductVersionEvent,
    SpinCreditRequest,
)
from core.services.product_catalog import (
    ProductCatalogError,
    active_product_version,
    missing_product_requirements,
    product_is_available,
    publish_product_version,
    resolve_product,
    resolve_product_mapping_issue,
    validate_custom_values,
)
from core.services.product_quotes import calculate_product_quote


class ProductCatalogTests(TestCase):
    def setUp(self):
        self.superuser = get_user_model().objects.create_superuser(
            username='product-admin',
            email='product-admin@example.test',
            password='test-password',
        )
        self.staff = get_user_model().objects.create_user(
            username='product-staff', password='test-password', is_staff=True,
        )
        ComplianceAuditChainState.objects.get_or_create(singleton=1)
        self.product = Product.objects.create(
            name='Growth Loan', code='Growth Loan', category='loan',
        )
        self.version = ProductVersion.objects.create(
            product=self.product,
            version=1,
            currency='kes',
            min_amount=Decimal('10000'),
            max_amount=Decimal('100000'),
            min_tenor=3,
            max_tenor=12,
            tenor_unit=ProductVersion.TENOR_MONTH,
            interest_method=ProductVersion.INTEREST_FLAT,
            interest_rate=Decimal('12'),
            interest_rate_period=ProductVersion.RATE_ANNUAL,
            repayment_frequency=ProductVersion.REPAYMENT_MONTHLY,
            effective_from=timezone.localdate(),
            created_by=self.superuser,
        )

    def test_product_identity_is_normalized_and_code_is_stable(self):
        self.assertEqual(self.product.code, 'growth_loan')
        self.product.code = 'replacement-code'
        with self.assertRaises(ValidationError):
            self.product.save()

    def test_alias_resolution_and_unknown_value_staging(self):
        ProductAlias.objects.create(product=self.product, alias='GL Facility')
        self.assertEqual(resolve_product('gl facility'), self.product)

        request = SpinCreditRequest.objects.create(
            group_id='test-group', loan_product='Unmapped External Product',
        )

        issue = ProductMappingIssue.objects.get(
            source_model='SpinCreditRequest', source_record_id=str(request.pk), status='open',
        )
        resolved = resolve_product_mapping_issue(
            issue, product=self.product, actor=self.superuser,
        )
        request.refresh_from_db()
        self.assertEqual(resolved.status, ProductMappingIssue.STATUS_RESOLVED)
        self.assertEqual(request.product, self.product)
        self.assertEqual(request.loan_product, self.product.name)
        self.assertTrue(
            ComplianceAuditEvent.objects.filter(
                action='global_product.mapping_resolved', subject_id=str(issue.pk),
            ).exists()
        )

    def test_only_superuser_can_publish_and_publication_is_audited(self):
        with self.assertRaises(ProductCatalogError):
            publish_product_version(version=self.version, actor=self.staff)

        published = publish_product_version(version=self.version, actor=self.superuser)

        self.assertEqual(published.status, ProductVersion.STATUS_PUBLISHED)
        self.assertEqual(active_product_version(self.product), published)
        self.assertTrue(ProductVersionEvent.objects.filter(
            product_version=published, action='published', actor=self.superuser,
        ).exists())
        self.assertTrue(ComplianceAuditEvent.objects.filter(
            action='global_product.version_published', subject_id=str(published.pk),
        ).exists())

    def test_superuser_can_open_the_visual_product_admin_builder(self):
        self.client.force_login(self.superuser)

        product_response = self.client.get(reverse('admin:core_product_change', args=[self.product.pk]))
        version_response = self.client.get(reverse('admin:core_productversion_change', args=[self.version.pk]))

        self.assertEqual(product_response.status_code, 200)
        self.assertContains(product_response, 'Terms versions')
        self.assertEqual(version_response.status_code, 200)
        self.assertContains(version_response, 'Product fees')
        self.assertContains(version_response, 'Product requirements')
        self.assertContains(version_response, 'Product custom attributes')

    def test_published_terms_are_immutable_and_successor_closes_period(self):
        first = publish_product_version(version=self.version, actor=self.superuser)
        first.interest_rate = Decimal('13')
        with self.assertRaises(ValidationError):
            first.save()

        successor_date = timezone.localdate() + timedelta(days=30)
        second = ProductVersion.objects.create(
            product=self.product,
            version=2,
            min_amount=Decimal('15000'),
            max_amount=Decimal('120000'),
            min_tenor=3,
            max_tenor=18,
            interest_rate=Decimal('10'),
            effective_from=successor_date,
            supersedes=first,
            created_by=self.superuser,
        )
        second = publish_product_version(version=second, actor=self.superuser)
        first.refresh_from_db()

        self.assertEqual(second.status, ProductVersion.STATUS_SCHEDULED)
        self.assertEqual(first.effective_to, successor_date - timedelta(days=1))
        self.assertEqual(active_product_version(self.product), first)
        self.assertEqual(active_product_version(self.product, on_date=successor_date), second)

    def test_availability_is_global_until_assignments_restrict_it(self):
        branch_a = OperationalLocation.objects.create(location_type='branch', name='Branch A')
        branch_b = OperationalLocation.objects.create(location_type='branch', name='Branch B')
        self.assertTrue(product_is_available(
            self.product, branch=branch_b, workflow='loan_origination', channel='portal',
        ))
        ProductAvailability.objects.create(
            product=self.product, branch=branch_a,
            workflow='loan_origination', channel='portal',
        )
        self.assertTrue(product_is_available(
            self.product, branch=branch_a, workflow='loan_origination', channel='portal',
        ))
        self.assertFalse(product_is_available(
            self.product, branch=branch_b, workflow='loan_origination', channel='portal',
        ))
        self.assertFalse(product_is_available(
            self.product, branch=branch_a, workflow='spin_credit_analysis', channel='portal',
        ))

    def test_decimal_quote_applies_financed_and_upfront_fees(self):
        ProductFee.objects.create(
            product_version=self.version,
            key='insurance', label='Insurance', fee_type=ProductFee.TYPE_PERCENTAGE,
            percentage=Decimal('1'), calculation_basis=ProductFee.BASIS_PRINCIPAL,
            collection_mode=ProductFee.COLLECTION_FINANCED,
        )
        ProductFee.objects.create(
            product_version=self.version,
            key='processing', label='Processing', fee_type=ProductFee.TYPE_FIXED,
            fixed_amount=Decimal('500'), collection_mode=ProductFee.COLLECTION_UPFRONT,
        )

        quote = calculate_product_quote(
            self.version, amount='20,000', tenor='6',
        )

        self.assertEqual(quote['financed_principal'], '20200.00')
        self.assertEqual(quote['interest'], '1212.00')
        self.assertEqual(quote['total_repayment'], '21412.00')
        self.assertEqual(quote['final_installment_amount'], '3568.65')
        self.assertEqual(quote['upfront_fees'], '500.00')
        self.assertEqual(quote['installment_count'], 6)

    def test_stage_requirements_and_typed_custom_values(self):
        ProductRequirement.objects.create(
            product_version=self.version,
            key='consent', label='Customer consent',
            requirement_type=ProductRequirement.TYPE_CHECKBOX,
            workflow='loan_origination', enforcement_stage='review',
        )
        ProductCustomAttribute.objects.create(
            product_version=self.version,
            key='sector', label='Sector',
            attribute_type=ProductCustomAttribute.TYPE_CHOICE,
            required=True, options=['Retail', 'Farming'],
            workflow_visibility=['loan_origination'],
        )

        missing = missing_product_requirements(
            self.version, workflow='loan_origination', stage='review', evidence={},
        )
        self.assertEqual([item['key'] for item in missing], ['consent'])
        self.assertEqual(validate_custom_values(
            self.version, {'sector': 'Unknown'}, workflow='loan_origination',
        ), {'sector': 'Select an approved value for Sector.'})
        self.assertEqual(validate_custom_values(
            self.version, {'sector': 'Retail'}, workflow='loan_origination',
        ), {})

    def test_payment_readiness_applies_jawabu_payment_requirements(self):
        ProductRequirement.objects.create(
            product_version=self.version,
            key='payment_consent',
            label='Payment consent',
            requirement_type=ProductRequirement.TYPE_CHECKBOX,
            workflow='jawabu_portal',
            enforcement_stage='payment',
        )
        farmer = JawabuFarmerMaster.objects.create(
            customer_name='Catalogue Farmer',
            national_id='12345678',
            status='active',
            product=self.product,
            product_version=self.version,
        )

        from core.services.payment_documents import payment_readiness

        readiness = payment_readiness(farmer_ids=[str(farmer.pk)])

        self.assertEqual(readiness['ready_count'], 0)
        self.assertIn('Payment consent', readiness['blocked'][0]['missing'])
