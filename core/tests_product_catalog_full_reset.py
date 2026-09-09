from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from core.models import (
    AccessGrant,
    ComplianceAuditEvent,
    OriginationDocumentProductEligibility,
    OriginationDocumentTemplate,
    Product,
    ProductAlias,
    ProductAvailability,
    ProductFee,
    ProductVersion,
    SpinCreditRequest,
    TatTrackerCase,
)
from core.services.access_grant_governance import governed_access_grant_mutation
from core.services.product_catalog_full_reset import (
    ProductCatalogFullResetError,
    preview_full_product_catalog_reset,
    reset_full_product_catalog,
)


@override_settings(
    SECURE_SSL_REDIRECT=False,
    SESSION_COOKIE_SECURE=False,
    CSRF_COOKIE_SECURE=False,
)
class ProductCatalogFullResetTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.root = User.objects.create_superuser(
            'product-reset-root', 'product-reset-root@example.test', 'password',
        )
        self.staff = User.objects.create_user('product-reset-staff', is_staff=True)

    def make_product(self, code, *, version_status=ProductVersion.STATUS_DRAFT):
        product = Product.objects.create(name=code.replace('_', ' ').title(), code=code)
        version = ProductVersion.objects.create(
            product=product, version=1,
            min_amount=Decimal('1000'), max_amount=Decimal('100000'),
        )
        if version_status != ProductVersion.STATUS_DRAFT:
            ProductVersion.objects.filter(pk=version.pk).update(status=version_status)
            version.refresh_from_db()
        return product, version

    def make_template(self, key):
        return OriginationDocumentTemplate.objects.create(
            document_type=key,
            name=key.replace('_', ' ').title(),
            version=1,
            source_filename=f'{key}.pdf',
            source_sha256='a' * 64,
            source_byte_size=100,
            page_count=1,
            created_by=self.root,
        )

    def test_preview_and_reset_delete_unused_drafts_and_tombstone_history(self):
        unused, unused_version = self.make_product('unused_draft')
        ProductAlias.objects.create(product=unused, alias='Unused draft alias')
        ProductFee.objects.create(
            product_version=unused_version,
            key='fee', label='Fee', fixed_amount=Decimal('100'),
        )

        connected, connected_version = self.make_product('connected_product')
        SpinCreditRequest.objects.create(
            group_id='product-reset-test', request_type='spin',
            product=connected, product_version=connected_version,
        )
        ProductAvailability.objects.create(
            product=connected, workflow='spin_credit_analysis', channel='portal',
        )
        template = self.make_template('connected_supporting_document')
        OriginationDocumentProductEligibility.objects.create(
            template=template, product=connected, created_by=self.root,
        )
        with governed_access_grant_mutation('product reset test setup'):
            grant = AccessGrant.objects.create(
                user=self.staff, workflow='spin_credit_analysis', role='CA',
                product=connected.code, product_ref=connected,
            )

        legacy, legacy_version = self.make_product(
            'legacy_product', version_status=ProductVersion.STATUS_PUBLISHED,
        )
        legacy_text, legacy_text_version = self.make_product('legacy_text_product')
        legacy_case = TatTrackerCase.objects.create(
            group_id='legacy-product-reset-test',
            case_id='LEGACY-PRODUCT-001',
            product_key=legacy_text.code,
            product_label=legacy_text.name,
            client_name='Legacy Product Client',
            branch='Nakuru',
        )

        preview = preview_full_product_catalog_reset()
        tombstone_ids = {item['id'] for item in preview['tombstone_products']}
        self.assertIn(str(connected.pk), tombstone_ids)
        self.assertIn(str(legacy.pk), tombstone_ids)
        self.assertIn(str(legacy_text.pk), tombstone_ids)
        self.assertNotIn(str(unused.pk), tombstone_ids)
        self.assertIn(str(unused.pk), preview['deletable_product_ids'])

        result = reset_full_product_catalog(
            actor=self.root,
            reason='Clear synthetic product catalogue data.',
            request_id='product-full-reset-1',
        )

        self.assertFalse(result['replayed'])
        self.assertFalse(Product.objects.filter(pk=unused.pk).exists())
        self.assertFalse(ProductVersion.objects.filter(pk=unused_version.pk).exists())
        self.assertFalse(ProductFee.objects.filter(product_version_id=unused_version.pk).exists())
        for product in (connected, legacy, legacy_text):
            product.refresh_from_db()
            self.assertFalse(product.active)
        self.assertTrue(ProductVersion.objects.filter(pk=connected_version.pk).exists())
        self.assertTrue(ProductVersion.objects.filter(pk=legacy_version.pk).exists())
        self.assertTrue(ProductVersion.objects.filter(pk=legacy_text_version.pk).exists())
        self.assertTrue(SpinCreditRequest.objects.filter(product=connected).exists())
        self.assertTrue(TatTrackerCase.objects.filter(pk=legacy_case.pk).exists())
        self.assertTrue(OriginationDocumentTemplate.objects.filter(pk=template.pk).exists())
        self.assertFalse(ProductAvailability.objects.filter(product=connected).exists())
        self.assertFalse(OriginationDocumentProductEligibility.objects.filter(product=connected).exists())
        grant.refresh_from_db()
        self.assertFalse(grant.active)
        self.assertIsNone(grant.product_ref_id)
        self.assertTrue(ComplianceAuditEvent.objects.filter(
            action='product.tombstoned', subject_id=str(connected.pk),
        ).exists())
        reset_event = ComplianceAuditEvent.objects.get(
            deduplication_key='product-catalog:full-reset:product-full-reset-1',
        )
        self.assertFalse(reset_event.metadata['operational_records_deleted'])
        self.assertTrue(reset_event.metadata['historical_references_tombstoned'])

        replay = reset_full_product_catalog(
            actor=self.root,
            reason='Clear synthetic product catalogue data.',
            request_id='product-full-reset-1',
        )
        self.assertTrue(replay['replayed'])

    def test_non_superuser_is_rejected(self):
        self.make_product('protected_product')
        with self.assertRaisesRegex(ProductCatalogFullResetError, 'Superuser'):
            reset_full_product_catalog(
                actor=self.staff,
                reason='Unauthorized cleanup.',
                request_id='product-reset-denied',
            )
        self.assertTrue(Product.objects.filter(code='protected_product').exists())

    def test_reset_rolls_back_if_one_product_delete_fails(self):
        first, _version = self.make_product('rollback_one')
        second, _version = self.make_product('rollback_two')
        from core.services import product_catalog_full_reset

        real_delete = product_catalog_full_reset.delete_product_family
        calls = 0

        def fail_second_delete(**kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError('Injected product reset failure')
            return real_delete(**kwargs)

        with patch.object(
            product_catalog_full_reset,
            'delete_product_family',
            side_effect=fail_second_delete,
        ):
            with self.assertRaisesRegex(RuntimeError, 'Injected product reset failure'):
                reset_full_product_catalog(
                    actor=self.root,
                    reason='Verify transactional rollback.',
                    request_id='product-reset-rollback',
                )
        self.assertEqual(Product.objects.filter(pk__in=[first.pk, second.pk]).count(), 2)
        self.assertFalse(ComplianceAuditEvent.objects.filter(
            deduplication_key='product-catalog:full-reset:product-reset-rollback',
        ).exists())

    @override_settings(PRODUCT_CATALOG_FULL_RESET_ENABLED=False)
    def test_admin_endpoint_is_disabled_by_default(self):
        self.client.force_login(self.root)
        self.assertEqual(
            self.client.get(reverse('admin:core_product_full_reset')).status_code,
            403,
        )

    @override_settings(PRODUCT_CATALOG_FULL_RESET_ENABLED=True)
    def test_admin_confirmation_and_navigation_are_superuser_only(self):
        product, _version = self.make_product('admin_reset_product')
        url = reverse('admin:core_product_full_reset')

        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(url).status_code, 403)

        self.client.force_login(self.root)
        response = self.client.get(url)
        self.assertContains(response, 'RESET ALL PRODUCT DATA')
        self.assertContains(response, 'tombstone')
        response = self.client.get(reverse('admin:core_product_changelist'))
        self.assertContains(response, 'Reset product catalogue')

        response = self.client.post(url, {
            'confirmation': 'RESET PRODUCTS',
            'reason': 'Wrong confirmation must not delete.',
            'request_id': 'wrong-product-confirmation',
        })
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Product.objects.filter(pk=product.pk).exists())

        response = self.client.post(url, {
            'confirmation': 'RESET ALL PRODUCT DATA',
            'reason': 'Clear unused synthetic product.',
            'request_id': 'admin-product-reset-success',
        })
        self.assertRedirects(response, url)
        self.assertFalse(Product.objects.filter(pk=product.pk).exists())

        from core.admin_navigation import get_admin_navigation

        request = RequestFactory().get('/admin/')
        request.user = self.staff
        item = next(
            item
            for group in get_admin_navigation(request)
            for item in group.get('items', [])
            if item.get('title') == 'Reset product catalogue'
        )
        self.assertFalse(item['permission'](request))
