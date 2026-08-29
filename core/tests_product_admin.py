from datetime import timedelta

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.utils import timezone

from core.models import (
    AccessGrant,
    ComplianceAuditEvent,
    EmergencyAccessGrant,
    JawabuApprovalDelegation,
    OriginationDocumentTemplate,
    OriginationDocumentTemplateEvent,
    OriginationProductDefinition,
    OriginationProductDefinitionEvent,
    Product,
    ProductAlias,
    ProductFee,
    ProductMappingIssue,
    ProductVersion,
    ProductVersionEvent,
    SpinCreditRequest,
)
from core.services.access_grant_governance import governed_access_grant_mutation
from core.services.product_deletion import (
    ProductDeletionError,
    REVIEWED_ORIGINATION_DEFINITION_RELATION_ACCESSORS,
    REVIEWED_ORIGINATION_TEMPLATE_RELATION_ACCESSORS,
    REVIEWED_PRODUCT_RELATION_ACCESSORS,
    REVIEWED_PRODUCT_VERSION_RELATION_ACCESSORS,
    delete_product_family,
)


class ProductAdminDeletionTests(TestCase):
    def setUp(self):
        self.root = get_user_model().objects.create_superuser(
            'product-delete-root', 'root@example.test', 'password',
        )
        self.request = RequestFactory().post('/admin/core/product/')
        self.request.user = self.root
        self.model_admin = admin.site._registry[Product]

    def test_every_direct_product_relationship_has_a_reviewed_deletion_policy(self):
        reviewed = (
            (Product, REVIEWED_PRODUCT_RELATION_ACCESSORS),
            (ProductVersion, REVIEWED_PRODUCT_VERSION_RELATION_ACCESSORS),
            (
                OriginationProductDefinition,
                REVIEWED_ORIGINATION_DEFINITION_RELATION_ACCESSORS,
            ),
            (
                OriginationDocumentTemplate,
                REVIEWED_ORIGINATION_TEMPLATE_RELATION_ACCESSORS,
            ),
        )
        for model, expected in reviewed:
            with self.subTest(model=model.__name__):
                actual = {
                    relation.get_accessor_name()
                    for relation in model._meta.related_objects
                }
                self.assertEqual(actual, expected)

    def test_superuser_can_select_and_delete_an_unused_product(self):
        product = Product.objects.create(name='Unused Product', code='unused_product')
        ProductAlias.objects.create(product=product, alias='Unused alias')
        product_id = product.pk

        self.assertTrue(self.model_admin.has_delete_permission(self.request, product))
        self.assertIn('delete_selected', self.model_admin.get_actions(self.request))
        self.model_admin.delete_queryset(
            self.request, Product.objects.filter(pk=product_id),
        )

        self.assertFalse(Product.objects.filter(pk=product_id).exists())
        event = ComplianceAuditEvent.objects.get(
            action='product.deleted', subject_id=str(product_id),
        )
        self.assertEqual(event.actor, self.root)
        self.assertEqual(event.before_values['code'], 'unused_product')
        self.assertEqual(event.before_values['delete_counts']['aliases'], 1)

    def test_product_deletion_request_is_idempotent(self):
        product = Product.objects.create(name='Retry Product', code='retry_product')
        product_id = product.pk
        request_id = 'product-delete-retry-1'

        first = delete_product_family(
            product_id=product_id,
            actor=self.root,
            request_id=request_id,
        )
        replay = delete_product_family(
            product_id=product_id,
            actor=self.root,
            request_id=request_id,
        )

        self.assertFalse(first.get('replayed', False))
        self.assertTrue(replay['replayed'])
        self.assertEqual(
            ComplianceAuditEvent.objects.filter(
                deduplication_key=f'product-delete:{product_id}:{request_id}',
            ).count(),
            1,
        )

    def test_product_owned_configuration_is_deleted_and_history_links_are_detached(self):
        product = Product.objects.create(name='Configured Product', code='configured_product')
        product_id = product.pk
        version = ProductVersion.objects.create(product=product, version=1)
        ProductFee.objects.create(
            product_version=version,
            key='processing_fee',
            label='Processing fee',
            fixed_amount='100.00',
        )
        version_event = ProductVersionEvent.objects.create(
            product_version=version,
            action='draft_created',
            actor=self.root,
            metadata={'source': 'test'},
        )
        definition = OriginationProductDefinition.objects.create(
            product_version=version,
            product_key=product.code,
            name=product.name,
            document_type='laf',
        )
        definition_event = OriginationProductDefinitionEvent.objects.create(
            product_definition=definition,
            action='draft_created',
            actor=self.root,
        )
        template = OriginationDocumentTemplate.objects.create(
            product_definition=definition,
            document_type='configured_product_laf',
            name='Configured Product LAF',
            version=1,
            source_filename='configured-product.pdf',
            source_sha256='a' * 64,
            source_byte_size=100,
            page_count=1,
            created_by=self.root,
        )
        template_event = OriginationDocumentTemplateEvent.objects.create(
            template=template,
            action='uploaded',
            actor=self.root,
        )
        issue = ProductMappingIssue.objects.create(
            raw_value='Configured Product',
            normalized_value='configured_product',
            source_workflow='test',
            source_model='Example',
            source_record_id='1',
            status=ProductMappingIssue.STATUS_RESOLVED,
            product=product,
        )
        with governed_access_grant_mutation('product deletion test setup'):
            grant = AccessGrant.objects.create(
                user=self.root,
                workflow='tat_tracker',
                role='IT',
                product=product.code,
                product_ref=product,
            )
        emergency = EmergencyAccessGrant.objects.create(
            user=self.root,
            workflow='tat_tracker',
            role='IT',
            product=product.code,
            product_ref=product,
            reason='Test emergency',
            activated_by=self.root,
            expires_at=timezone.now() + timedelta(hours=1),
        )
        delegation = JawabuApprovalDelegation.objects.create(
            delegate=self.root,
            gate=JawabuApprovalDelegation.GATE_CREDIT,
            product=product.code,
            product_ref=product,
            reason='Test coverage',
            authorized_by=self.root,
            expires_at=timezone.now() + timedelta(days=1),
        )

        self.model_admin.delete_queryset(
            self.request, Product.objects.filter(pk=product.pk),
        )

        self.assertFalse(Product.objects.filter(pk=product_id).exists())
        self.assertFalse(ProductVersion.objects.filter(pk=version.pk).exists())
        self.assertFalse(OriginationProductDefinition.objects.filter(pk=definition.pk).exists())
        self.assertFalse(OriginationDocumentTemplate.objects.filter(pk=template.pk).exists())
        issue.refresh_from_db()
        grant.refresh_from_db()
        emergency.refresh_from_db()
        delegation.refresh_from_db()
        self.assertIsNone(issue.product_id)
        self.assertIsNone(grant.product_ref_id)
        self.assertFalse(grant.active)
        self.assertIsNone(emergency.product_ref_id)
        self.assertIsNotNone(emergency.revoked_at)
        self.assertIsNone(delegation.product_ref_id)
        self.assertIsNotNone(delegation.revoked_at)
        event = ComplianceAuditEvent.objects.get(
            action='product.deleted', subject_id=str(product_id),
        )
        captured = event.before_values['configuration_snapshot']
        self.assertEqual(
            captured['product_version_events'][0]['id'], str(version_event.pk),
        )
        self.assertEqual(
            captured['origination_definition_events'][0]['id'], str(definition_event.pk),
        )
        self.assertEqual(
            captured['document_template_events'][0]['id'], str(template_event.pk),
        )
        self.assertTrue(event.after_values['drive_files_untouched'])

    def test_operational_records_block_product_family_deletion(self):
        product = Product.objects.create(name='Used Product', code='used_product')
        version = ProductVersion.objects.create(product=product, version=1)
        SpinCreditRequest.objects.create(
            group_id='test-group',
            request_type='spin',
            product=product,
            product_version=version,
        )

        _deleted, _counts, _permissions, protected = self.model_admin.get_deleted_objects(
            [product], self.request,
        )
        self.assertTrue(any('SPIN request' in item for item in protected))
        with self.assertRaises(ProductDeletionError):
            self.model_admin.delete_queryset(
                self.request, Product.objects.filter(pk=product.pk),
            )

        self.assertTrue(Product.objects.filter(pk=product.pk).exists())
        self.assertTrue(ProductVersion.objects.filter(pk=version.pk).exists())

    def test_non_superuser_cannot_delete_products(self):
        ordinary = get_user_model().objects.create_user('product-editor', is_staff=True)
        self.request.user = ordinary

        self.assertFalse(self.model_admin.has_delete_permission(self.request))
        self.assertNotIn('delete_selected', self.model_admin.get_actions(self.request))
