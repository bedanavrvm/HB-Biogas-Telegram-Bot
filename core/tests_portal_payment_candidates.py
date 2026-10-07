"""Synthetic payment search coverage, including unavailable and scoped cases."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from core.api.portal_views import portal_payment_candidates
from core.models import AccessGrant, GroupSheetConfiguration, JawabuFarmerMaster, JawabuPipelineEvent, Product
from payments.models import PaymentBatch, PaymentBatchCase
from payments.services import PaymentBatchError, add_cases


@override_settings(PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=False, SECURE_SSL_REDIRECT=False)
class PortalPaymentCandidateTests(TestCase):
    def setUp(self):
        self.group = GroupSheetConfiguration.objects.create(group_id='qa-payment-search', sheet_id='synthetic', workflow={'type': 'jawabu'})
        self.batch = PaymentBatch.objects.create(group_configuration=self.group)

    def farmer(self, name, **kwargs):
        return JawabuFarmerMaster.objects.create(customer_name=name, group_configuration=self.group,
            national_id='99999999', primary_phone='254700000000', **kwargs)

    def search(self, **params):
        # Auth-disabled local fixtures have no import grants; scoped tests below
        # exercise the real group authorization with complete AccessGrant tuples.
        with patch('core.api.portal_views._portal_import_group_ids', return_value=None):
            return self.client.get(reverse('portal_payment_candidates'), {'include_all': '1', 'batch_id': str(self.batch.pk), **params})

    def test_search_includes_unmatched_inactive_and_paid_with_reasons(self):
        unmatched = self.farmer('Training unmatched', status='active')
        closed = self.farmer('Training inactive', status='inactive')
        paid = self.farmer('Training paid', status='active')
        JawabuPipelineEvent.objects.create(farmer=paid, action='payment_finalized')
        response = self.search()
        self.assertEqual(response.status_code, 200)
        rows = {row['farmer_id']: row for row in response.json()['results']}
        self.assertIn('No matched invoice', rows[str(unmatched.pk)]['unavailable_reason'])
        self.assertEqual(rows[str(closed.pk)]['unavailable_reason'], 'Case is no longer active')
        self.assertEqual(rows[str(paid.pk)]['unavailable_reason'], 'Already paid')
        self.assertTrue(all(not row['selectable'] for row in rows.values()))

    @patch('core.services.portal_payment_candidates.payment_readiness')
    def test_ready_current_other_completed_and_cancelled_memberships(self, readiness):
        farmers = [self.farmer(f'Training {i}', status='active') for i in range(5)]
        readiness.return_value = {'ready': [{'farmer_id': str(f.pk), 'customer_name': f.customer_name, 'missing': []} for f in farmers], 'blocked': []}
        for farmer, batch in zip(farmers[:4], [self.batch, *[PaymentBatch.objects.create(group_configuration=self.group, status=status) for status in ['draft', 'completed', 'cancelled']]]):
            PaymentBatchCase.objects.create(batch=batch, farmer=farmer, payment_mode='LOAN-JAWABU')
        rows = {row['farmer_id']: row for row in self.search().json()['results']}
        self.assertEqual([rows[str(f.pk)]['availability'] for f in farmers], ['included', 'assigned', 'paid', 'ready', 'ready'])
        self.assertEqual([rows[str(f.pk)]['selectable'] for f in farmers], [False, False, False, True, True])

    def test_pagination_search_and_explicit_group_boundary(self):
        JawabuFarmerMaster.objects.bulk_create([JawabuFarmerMaster(customer_name=f'Training {i:03}', group_configuration=self.group, case_reference_number=i+1) for i in range(265)])
        other_group = GroupSheetConfiguration.objects.create(group_id='qa-other-group', sheet_id='synthetic')
        JawabuFarmerMaster.objects.create(customer_name='Outside', group_configuration=other_group)
        response = self.search(page=14).json()
        self.assertEqual(response['pagination']['total'], 265)
        self.assertEqual(len(response['results']), 5)
        self.assertEqual(self.search(search='Training 264').json()['results'][0]['customer_name'], 'Training 264')

    def test_invalid_or_missing_batch_is_not_found(self):
        for value in ('bad-uuid', ''):
            self.assertEqual(self.search(batch_id=value).status_code, 404)

    def test_inactive_case_cannot_be_added_through_the_api_service(self):
        farmer = self.farmer('Training closed', status='inactive')
        with self.assertRaisesMessage(PaymentBatchError, 'Only active'):
            add_cases(self.batch.pk, farmer_ids=[str(farmer.pk)], payment_modes={str(farmer.pk): 'LOAN-JAWABU'}, expected_revision=1)
        self.assertFalse(self.batch.case_memberships.exists())

    def scoped_request(self, user, grants, **params):
        request = RequestFactory().get('/api/portal/payments/candidates/', {'include_all': '1', 'batch_id': str(self.batch.pk), **params})
        request.portal_user = user
        request.portal_access = {'grants': grants, 'roles': [g.role for g in grants], 'branches': [], 'products': []}
        return portal_payment_candidates(request)

    def test_previously_paid_case_cannot_be_added_through_the_api_service(self):
        farmer = self.farmer('Training paid')
        JawabuPipelineEvent.objects.create(farmer=farmer, action='payment_finalized')
        with self.assertRaisesMessage(PaymentBatchError, 'already been paid'):
            add_cases(self.batch.pk, farmer_ids=[str(farmer.pk)], payment_modes={str(farmer.pk): 'LOAN-JAWABU'}, expected_revision=1)
        self.assertFalse(self.batch.case_memberships.exists())

    def test_view_only_actor_cannot_use_preparation_search(self):
        user = get_user_model().objects.create_user(username='qa-view-only')
        grant = AccessGrant.objects.create(user=user, workflow='jawabu_portal', role='BUSINESS_ADMIN')
        self.assertEqual(self.scoped_request(user, [grant]).status_code, 403)

    def test_mixed_grants_do_not_borrow_view_scope_for_search(self):
        import json
        user = get_user_model().objects.create_user(username='qa-operations')
        product_a = Product.objects.create(code='QA-A', name='Training A')
        product_b = Product.objects.create(code='QA-B', name='Training B')
        grants = [AccessGrant.objects.create(user=user, workflow='jawabu_portal', role=role, branch=branch, product=product,
                                            group_configuration=self.group) for role, branch, product in
                  [('OPERATIONS_ADMIN', 'Embu', product_a.code), ('BUSINESS_ADMIN', 'Nakuru', product_b.code)]]
        allowed = self.farmer('Allowed', branch='Embu', product=product_a)
        self.farmer('View only', branch='Nakuru', product=product_b)
        self.farmer('Crossed scope', branch='Embu', product=product_b)
        response = self.scoped_request(user, grants)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row['farmer_id'] for row in json.loads(response.content)['results']], [str(allowed.pk)])

    def test_empty_batch_from_other_group_cannot_borrow_a_view_grant(self):
        user = get_user_model().objects.create_user(username='qa-groups')
        other = GroupSheetConfiguration.objects.create(group_id='qa-prepare-group', sheet_id='synthetic')
        grants = [AccessGrant.objects.create(user=user, workflow='jawabu_portal', role=role, group_configuration=group)
                  for role, group in [('OPERATIONS_ADMIN', other), ('BUSINESS_ADMIN', self.group)]]
        self.assertEqual(self.scoped_request(user, grants).status_code, 404)
