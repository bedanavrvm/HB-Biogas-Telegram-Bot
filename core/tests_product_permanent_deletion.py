import hashlib
from datetime import timedelta
from unittest.mock import patch
from unittest import skipUnless

from django.contrib import admin
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import connection, close_old_connections
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import ComplianceAuditChainState, ComplianceAuditEvent, Product, ProductVersion, SpinCreditRequest
from core.services.product_deletion import ProductDeletionError
from core.services.product_permanent_deletion import (
    delete_selected_products_permanently, preview_permanent_product_deletion,
)
from core import tests_origination_god_mode as god_mode_fixture
from origination.models import (
    LoanOriginationApplication, OriginationApplicationDocument, OriginationDocumentProductEligibility,
    OriginationDocumentTemplate, OriginationOtpChallenge, OriginationProductDefinition,
    OriginationSignerSession, OriginationSigningPackage,
)
from origination.services.origination_esign import OriginationSigningProblem, resolve_session


@override_settings(ORIGINATION_PRODUCT_FAMILY_PURGE_ENABLED=True)
class PermanentProductDeletionTests(TestCase):
    def setUp(self):
        ComplianceAuditChainState.objects.get_or_create(singleton=1)
        # Reuse the existing synthetic deep graph (corrections, evidence,
        # signatures, packets and shared catalogue documents).
        god_mode_fixture.OriginationGodModeTests.setUp(self)
        self.root = self.superuser
        self.target_id = self.global_product.pk
        self.token = 'synthetic-deleted-signing-link'
        self.session = OriginationSignerSession.objects.create(
            package=self.signing_package, signer_role='borrower',
            token_hash=hashlib.sha256(self.token.encode()).hexdigest(),
            token_expires_at=timezone.now() + timedelta(days=1),
            created_by=self.root,
        )

    def delete(self, ids=None, key='permanent-selected-test'):
        return delete_selected_products_permanently(product_ids=ids or [self.target_id], actor=self.root, request_id=key)

    def test_published_product_and_deep_origination_graph_are_physically_deleted(self):
        ProductVersion.objects.filter(pk=self.global_product_version.pk).update(status='published')
        original_application_id = self.application.pk
        self.delete()
        self.assertFalse(Product.objects.filter(pk=self.target_id).exists())
        self.assertFalse(LoanOriginationApplication.objects.filter(pk=original_application_id).exists())
        self.assertFalse(OriginationSignerSession.objects.filter(pk=self.session.pk).exists())
        self.assertFalse(OriginationSigningPackage.objects.filter(pk=self.signing_package.pk).exists())
        self.assertTrue(self.supporting_template.__class__.objects.filter(pk=self.supporting_template.pk).exists())
        self.assertTrue(self.data_field.__class__.objects.filter(pk=self.data_field.pk).exists())
        self.assertTrue(OriginationProductDefinition.objects.filter(pk=self.draft_product.pk).exists())
        self.assertTrue(ComplianceAuditEvent.objects.filter(action='product.selection_permanently_deleted').exists())
        with self.assertRaises(OriginationSigningProblem) as problem:
            resolve_session(self.token)
        self.assertEqual(problem.exception.status, 404)

    def test_replay_is_bound_to_actor_and_exact_selection(self):
        first = self.delete()
        self.assertTrue(self.delete()['replayed'])
        self.assertEqual(first['products_deleted'], 1)
        other = Product.objects.create(code='other_selection', name='Other selection')
        with self.assertRaises(ProductDeletionError):
            self.delete([other.pk])
        another_root = get_user_model().objects.create_superuser('another-root', 'root2@example.test', 'password')
        with self.assertRaises(ProductDeletionError):
            delete_selected_products_permanently(product_ids=[self.target_id], actor=another_root, request_id='permanent-selected-test')

    def test_background_jobs_for_deleted_records_are_cancelled_without_external_calls(self):
        from types import SimpleNamespace
        from origination.services.origination_dispatch import _perform
        package_id, session_id = self.signing_package.pk, self.session.pk
        self.delete()
        with patch('origination.services.origination_esign.archive_signed_package') as archive, patch(
            'origination.services.origination_esign._send_sms',
        ) as sms, patch('core.services.telegram_launchers.telegram_api_call') as telegram:
            for kind, source_id in [('origination_approved_archive', package_id),
                                    ('origination_withdrawal_sms', session_id),
                                    ('origination_approval_alert', package_id)]:
                result = _perform(SimpleNamespace(operation_type=kind, source_id=source_id))
                self.assertEqual(result, {'cancelled': True})
        archive.assert_not_called()
        sms.assert_not_called()
        telegram.assert_not_called()

    def test_other_workflow_blocker_prevents_entire_selection(self):
        other = Product.objects.create(code='spin_protected', name='SPIN protected')
        SpinCreditRequest.objects.create(group_id='synthetic-test', request_type='spin', product=other)
        with self.assertRaisesMessage(ProductDeletionError, 'SPIN request'):
            self.delete([self.target_id, other.pk])
        self.assertTrue(Product.objects.filter(pk=self.target_id).exists())
        self.assertTrue(LoanOriginationApplication.objects.filter(pk=self.application.pk).exists())
        self.assertFalse(ComplianceAuditEvent.objects.filter(action='product.selection_permanently_deleted').exists())

    def test_failure_in_second_family_rolls_back_first_family_and_application_purge(self):
        other = Product.objects.create(code='atomic_other', name='Atomic other')
        from core.services.product_permanent_deletion import delete_product_family
        def fail_second(**kwargs):
            if kwargs['product_id'] == other.pk:
                raise ProductDeletionError('synthetic later failure')
            return delete_product_family(**kwargs)
        with patch('core.services.product_permanent_deletion.delete_product_family', side_effect=fail_second):
            with self.assertRaises(ProductDeletionError):
                self.delete([self.target_id, other.pk])
        self.assertTrue(Product.objects.filter(pk=self.target_id).exists())
        self.assertTrue(OriginationSignerSession.objects.filter(pk=self.session.pk).exists())

    def test_shared_legacy_pdf_and_outside_frozen_application_are_preserved(self):
        outside = LoanOriginationApplication.objects.create(reference_number='ORG-OUTSIDE',
                                                            product_definition=self.draft_product, officer=self.root)
        frozen = OriginationApplicationDocument.objects.create(application=outside, template=self.template,
                                                               document_key='primary', name='Outside frozen document',
                                                               document_role='primary', inclusion_mode='required')
        self.delete()
        self.template.refresh_from_db()
        self.assertIsNone(self.template.product_definition_id)
        self.assertTrue(OriginationApplicationDocument.objects.filter(pk=frozen.pk).exists())
        self.assertTrue(LoanOriginationApplication.objects.filter(pk=outside.pk).exists())

    def test_shared_pdf_eligibility_to_other_product_is_retained(self):
        other = Product.objects.create(code='shared_other', name='Shared other')
        eligibility = OriginationDocumentProductEligibility.objects.create(template=self.template, product=other)
        self.delete()
        self.assertTrue(OriginationDocumentProductEligibility.objects.filter(pk=eligibility.pk).exists())
        self.template.refresh_from_db()
        self.assertIsNone(self.template.product_definition_id)

    def test_outside_history_link_is_precise_blocker(self):
        outside = LoanOriginationApplication.objects.create(reference_number='ORG-REPLACEMENT',
                                                            product_definition=self.draft_product, officer=self.root,
                                                            supersedes_application=self.application)
        with self.assertRaisesMessage(ProductDeletionError, 'history link'):
            self.delete()
        outside.refresh_from_db()
        self.assertEqual(outside.supersedes_application_id, self.application.pk)

    def test_empty_invalid_and_missing_selection_fail_safely(self):
        for ids in ([], ['not-an-id'], [-1], [True], [1.9], [99999999]):
            with self.assertRaises(ProductDeletionError):
                delete_selected_products_permanently(product_ids=ids, actor=self.root, request_id='invalid-selection')

    def test_server_enforces_gate_and_superuser(self):
        with override_settings(ORIGINATION_PRODUCT_FAMILY_PURGE_ENABLED=False):
            with self.assertRaises(PermissionDenied):
                self.delete()
        with self.assertRaises(PermissionDenied):
            delete_selected_products_permanently(product_ids=[self.target_id], actor=self.staff, request_id='denied')

    def test_preview_is_read_only_and_requires_no_note(self):
        result = preview_permanent_product_deletion(product_ids=[self.target_id], actor=self.root)
        self.assertEqual(result['applications'], 1)
        self.assertEqual(result['blockers'], [])
        self.assertTrue(Product.objects.filter(pk=self.target_id).exists())

    def test_admin_one_confirmation_then_deletion_without_note(self):
        self.client.force_login(self.root)
        url = reverse('admin:core_product_changelist')
        payload = {'action': 'delete_selected_products_permanently', ACTION_CHECKBOX_NAME: [str(self.target_id)],
                   'index': '0', 'select_across': '0'}
        confirmation = self.client.post(url, payload, secure=True)
        self.assertEqual(confirmation.status_code, 200)
        self.assertContains(confirmation, 'This cannot be undone')
        self.assertNotContains(confirmation, 'textarea')
        payload.update({'selection_token': confirmation.context_data['selection_token'],
                        'request_id': confirmation.context_data['request_id'], 'confirm_permanent_delete': '1'})
        response = self.client.post(url, payload, secure=True)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Product.objects.filter(pk=self.target_id).exists())

    def test_admin_selection_tampering_does_not_delete(self):
        self.client.force_login(self.root)
        url = reverse('admin:core_product_changelist')
        payload = {'action': 'delete_selected_products_permanently', ACTION_CHECKBOX_NAME: [str(self.target_id)], 'index': '0'}
        confirmation = self.client.post(url, payload, secure=True)
        payload.update({'selection_token': confirmation.context_data['selection_token'], 'request_id': 'tampered',
                        'confirm_permanent_delete': '1'})
        self.assertEqual(self.client.post(url, payload, secure=True).status_code, 400)
        self.assertTrue(Product.objects.filter(pk=self.target_id).exists())

    def test_admin_action_hidden_when_gate_disabled_and_removal_has_honest_label(self):
        request = RequestFactory().get('/admin/core/product/')
        request.user = self.root
        model_admin = admin.site._registry[Product]
        self.assertIn('Delete selected products permanently', model_admin.get_actions(request)['delete_selected_products_permanently'][2])
        self.assertIn('retain connected history', model_admin.get_actions(request)['delete_selected'][2])
        with override_settings(ORIGINATION_PRODUCT_FAMILY_PURGE_ENABLED=False):
            self.assertNotIn('delete_selected_products_permanently', model_admin.get_actions(request))


@skipUnless(connection.vendor == 'postgresql', 'Requires real PostgreSQL row locks.')
@override_settings(ORIGINATION_PRODUCT_FAMILY_PURGE_ENABLED=True)
class ConcurrentPermanentProductDeletionTests(TransactionTestCase):
    def test_concurrent_identical_confirmations_delete_once_and_replay_once(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        ComplianceAuditChainState.objects.get_or_create(singleton=1)
        actor = get_user_model().objects.create_superuser('concurrent-delete-root', password='synthetic')
        product = Product.objects.create(code='concurrent-delete', name='Concurrent deletion test')
        barrier = Barrier(2)
        def run():
            close_old_connections()
            try:
                current_actor = get_user_model().objects.get(pk=actor.pk)
                barrier.wait(timeout=15)
                return delete_selected_products_permanently(
                    product_ids=[product.pk], actor=current_actor, request_id='concurrent-confirmation')
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = [future.result(timeout=30) for future in [pool.submit(run), pool.submit(run)]]
        self.assertEqual(sum(bool(item.get('replayed')) for item in results), 1)
        self.assertFalse(Product.objects.filter(pk=product.pk).exists())
        self.assertEqual(ComplianceAuditEvent.objects.filter(action='product.selection_permanently_deleted').count(), 1)
