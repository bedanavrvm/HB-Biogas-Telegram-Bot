"""Synthetic regressions for Portal role views and negative decision routing."""
from datetime import timedelta
from inspect import unwrap
import json
from unittest.mock import patch
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import TestCase, SimpleTestCase, RequestFactory
from django.utils import timezone

from core.models import JawabuFarmerMaster
from core.services.jawabu_pipeline import (
    credit_queue, deferred_queue, reappraisal_required_queue, set_credit_decision,
    current_workflow_state, is_reappraisal_required,
)
from core.services.portal_navigation import get_portal_nav_items


class PortalRoleNavigationTests(SimpleTestCase):
    def test_read_only_orders_are_not_labelled_as_preparation(self):
        with patch('core.services.workflow_capabilities.effective_capability_keys',
                   return_value={'portal.requisition.view'}):
            item = next(item for item in get_portal_nav_items(object()) if item['key'] == 'requisition')
        self.assertEqual(item['label'], 'Orders')

    def test_order_writer_keeps_preparation_destination(self):
        with patch('core.services.workflow_capabilities.effective_capability_keys',
                   return_value={'portal.requisition.view', 'portal.requisition.write'}):
            item = next(item for item in get_portal_nav_items(object()) if item['key'] == 'requisition')
        self.assertEqual(item['label'], 'Prepare Orders')

    def test_credit_replay_does_not_revalidate_already_resolved_voice(self):
        from core.api.portal_views import portal_set_credit_decision
        farmer = SimpleNamespace(pk='synthetic-case', refresh_from_db=lambda: None)
        request = RequestFactory().post('/synthetic/', data=json.dumps({
            'decision':'Rejected', 'reason_code':'r01', 'workflow_revision':1,
            'request_id':'synthetic-credit-replay', 'voice_transcription_id':'synthetic-voice',
        }), content_type='application/json')
        request.portal_user = SimpleNamespace(pk=1, username='synthetic-user')
        with patch('core.models.JawabuFarmerMaster.objects.get', return_value=farmer), \
             patch('core.api.portal_views._portal_approval_authority_error', return_value=None), \
             patch('core.api.portal_views._portal_sender_from_request', return_value='Synthetic user'), \
             patch('core.api.portal_views._portal_request_id', return_value='synthetic-credit-replay'), \
             patch('core.services.jawabu_case360.event_request_already_processed', return_value=True), \
             patch('core.services.jawabu_pipeline.set_credit_decision', return_value=(True,'')), \
             patch('core.services.jawabu_pipeline.farmer_to_card', return_value={}), \
             patch('core.api.portal_views._portal_publication_payload', return_value={}), \
             patch('core.services.portal_voice.validate_transcription_reference', side_effect=ValueError('Already resolved.')) as validate, \
             patch('core.services.portal_voice.resolve_transcription') as resolve:
            response = unwrap(portal_set_credit_decision)(request, 'synthetic-case')
        self.assertEqual(response.status_code, 200)
        validate.assert_not_called()
        resolve.assert_not_called()


class PortalNegativeDecisionTests(TestCase):
    def make_case(self, **kwargs):
        values = dict(customer_name='Synthetic role test', status='active',
                      workflow_state='credit', jbl_visit_date=timezone.localdate(),
                      jbl_visit_status='Visited, Awaiting Credit Analysis')
        values.update(kwargs)
        return JawabuFarmerMaster.objects.create(**values)

    @patch('core.services.portal_publication.reserve_farmer_publication')
    def test_negative_decisions_do_not_require_imab_and_leave_credit_queue(self, publication):
        for decision, code, state in [('Rejected', 'r01', 'rejected'),
                                      ('Deferred / On Hold', 'd01', 'deferred')]:
            with self.subTest(decision=decision):
                farmer = self.make_case()
                ok, error = set_credit_decision(farmer, decision=decision, reason_code=code)
                self.assertTrue(ok, error)
                self.assertEqual(farmer.workflow_state, state)
                self.assertFalse(credit_queue().filter(pk=farmer.pk).exists())
                self.assertTrue(deferred_queue().filter(pk=farmer.pk).exists())

    @patch('core.services.portal_publication.reserve_farmer_publication')
    def test_negative_decision_preserves_existing_system_identity(self, publication):
        farmer = self.make_case(imab_created='Yes', customer_no='90001')
        ok, error = set_credit_decision(farmer, decision='Rejected', reason_code='r01')
        self.assertTrue(ok, error)
        self.assertEqual((farmer.imab_created, farmer.customer_no), ('Yes', '90001'))

    def test_review_card_retains_numeric_and_legacy_repayment_terms(self):
        from core.services.jawabu_pipeline import farmer_to_card
        for fields in [
            {'repayment_day':15, 'repayment_tenor_months':24},
            {'repayment_date':'15TH', 'repayment_tenor':'24 months'},
            {'repayment_date':'2026-05-15', 'repayment_tenor':'24 months'},
        ]:
            with self.subTest(fields=fields):
                card = farmer_to_card(self.make_case(**fields), include_detail_metadata=False)
                self.assertEqual(card['repayment_day'], 15)
                self.assertEqual(card['repayment_tenor_months'], 24)

    @patch('core.services.jawabu_pipeline._validate_farmer_product_configuration',
           return_value='Complete approval evidence')
    @patch('core.services.portal_publication.reserve_farmer_publication')
    def test_negative_decision_is_not_blocked_by_approval_evidence(self, publication, validation):
        farmer = self.make_case()
        ok, error = set_credit_decision(farmer, decision='Deferred / On Hold', reason_code='d02')
        self.assertTrue(ok, error)
        validation.assert_not_called()

    def test_approval_still_requires_imab(self):
        ok, error = set_credit_decision(self.make_case(), decision='Approved')
        self.assertFalse(ok)
        self.assertIn('IMAB', error)

    def test_resolved_negative_legacy_credit_rows_do_not_stay_in_credit_queue(self):
        for decision in ['Rejected', 'Deferred / On Hold']:
            farmer = self.make_case(credit_decision=decision)
            self.assertFalse(credit_queue().filter(pk=farmer.pk).exists())

    def test_current_outcome_controls_revisit_not_stale_history(self):
        stale = timezone.now() - timedelta(days=80)
        for outcome in ['Opted for Cash', 'Opted for Other Partner']:
            farmer = self.make_case(workflow_state='withdrawn', jbl_visit_status=outcome,
                                    credit_decision='Deferred / On Hold', deferred_at=stale,
                                    deferred_until=timezone.localdate() - timedelta(days=1))
            self.assertFalse(deferred_queue().filter(pk=farmer.pk).exists())
            self.assertFalse(reappraisal_required_queue().filter(pk=farmer.pk).exists())
        progressed = self.make_case(workflow_state='order', final_decision='Approved',
                                    credit_decision='Deferred / On Hold')
        self.assertFalse(deferred_queue().filter(pk=progressed.pk).exists())

    def test_expired_deferral_does_not_hide_rejected_cases(self):
        farmer = self.make_case(workflow_state='rejected', credit_decision='Rejected',
                                deferred_at=timezone.now() - timedelta(days=80),
                                deferred_until=timezone.localdate() - timedelta(days=1))
        self.assertTrue(deferred_queue().filter(pk=farmer.pk).exists())
        self.assertFalse(reappraisal_required_queue().filter(pk=farmer.pk).exists())
        self.assertFalse(is_reappraisal_required(farmer))

    def test_legacy_withdrawal_and_progression_ignore_old_hold_dates(self):
        for fields, expected in [
            ({'jbl_visit_status': 'Opted for Cash', 'credit_decision': 'Deferred / On Hold'}, 'withdrawn'),
            ({'jbl_visit_status': 'Opted for Other Partner', 'credit_decision': 'Deferred / On Hold'}, 'withdrawn'),
            ({'final_decision': 'Rejected'}, 'rejected'),
            ({'order_number': '123'}, 'ordered'),
        ]:
            with self.subTest(expected=expected):
                farmer = self.make_case(workflow_state='', deferred_until=timezone.localdate()-timedelta(days=1), **fields)
                self.assertEqual(current_workflow_state(farmer), expected)
                self.assertFalse(is_reappraisal_required(farmer))
                self.assertEqual(deferred_queue().filter(pk=farmer.pk).exists(), expected == 'rejected')

    @patch('core.services.jawabu_identity.set_customer_number')
    @patch('core.services.portal_publication.reserve_farmer_publication')
    def test_negative_decision_never_mutates_identity_and_replay_is_idempotent(self, publication, identity):
        farmer = self.make_case(imab_created='Yes', customer_no='90001')
        for _ in range(2):
            ok, error = set_credit_decision(farmer, decision='Rejected', reason_code='r01',
                                            request_id='synthetic-credit-reject', expected_revision=1)
            self.assertTrue(ok, error)
        identity.assert_not_called()
        self.assertEqual(farmer.pipeline_events.filter(action='credit_decision_recorded').count(), 1)

    def test_revisit_status_and_options_use_only_authorized_branches(self):
        from core.api.portal_views import _portal_queue_queryset, _portal_queue_filter_options
        deferred = self.make_case(workflow_state='deferred', branch='Nakuru', county='Nakuru')
        rejected = self.make_case(workflow_state='rejected', branch='Nakuru', county='Embu')
        self.make_case(workflow_state='rejected', branch='Ruiru', county='Kiambu')
        request = RequestFactory().get('/api/portal/deferred/', {'status':'rejected','county':'Embu'})
        request.portal_user = get_user_model().objects.create_user(username='synthetic-revisit-user')
        request.portal_access = {'grants':[SimpleNamespace(pk=1,role='JBL_OFFICER',branch='Nakuru',product='',group_configuration_id=None,group_configuration=None)]}
        qs, _ = _portal_queue_queryset('deferred', request)
        self.assertEqual(list(qs.values_list('pk',flat=True)), [rejected.pk])
        options = _portal_queue_filter_options(request, 'deferred')
        self.assertEqual(options['status'], ['deferred','rejected'])
        self.assertEqual(options['branch'], ['Nakuru'])
        self.assertEqual(options['county'], ['Embu','Nakuru'])
        request.GET = request.GET.copy()
        request.GET['status'] = 'deferred'
        request.GET.pop('county')
        qs, _ = _portal_queue_queryset('deferred', request)
        self.assertEqual(list(qs.values_list('pk',flat=True)), [deferred.pk])
