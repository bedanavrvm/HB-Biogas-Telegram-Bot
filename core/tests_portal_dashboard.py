from datetime import date, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from core.models import DurableJobRunnerHeartbeat, IntegrationOperation, InvoiceIdentityReview, InvoiceUploadBatch, JawabuFarmerMaster, ParsedInvoice
from core.services.portal_dashboard import dashboard_payload
from core.services.jawabu_case360 import record_pipeline_event


class PortalActionDashboardTests(TestCase):
    def farmer(self, name, branch, **overrides):
        values = {
            'customer_name': name,
            'national_id': overrides.pop('national_id', ''),
            'primary_phone': overrides.pop('primary_phone', ''),
            'branch': branch,
            'status': 'active',
            'hbg_visit_date': date(2026, 8, 1),
        }
        values.update(overrides)
        return JawabuFarmerMaster.objects.create(**values)

    def test_dashboard_counts_and_recent_cases_are_branch_scoped(self):
        allowed = self.farmer('Allowed farmer', 'Nakuru', national_id='11111111')
        self.farmer('Other branch farmer', 'Ruiru', national_id='22222222')

        payload = dashboard_payload(None, access={'branches': ['Nakuru']})

        self.assertEqual(payload['counts']['jbl_queue'], 1)
        self.assertEqual(payload['counts']['total'], 1)
        self.assertEqual([item['customer_name'] for item in payload['recent_cases']], [allowed.customer_name])
        self.assertEqual(payload['scope']['branches'], ['Nakuru'])

    def test_repaired_publication_clears_old_dashboard_warning(self):
        farmer = self.farmer('Sheet repair', 'Nakuru', national_id='11111111')
        common = {
            'integration': IntegrationOperation.INTEGRATION_GOOGLE_SHEETS,
            'operation_type': 'jawabu_master_publish',
            'source_model': 'JawabuFarmerMaster', 'source_id': str(farmer.pk),
            'metadata': {'workflow_revision': farmer.workflow_revision},
        }
        IntegrationOperation.objects.create(
            **common, deduplication_key='old-failed-publication',
            status=IntegrationOperation.STATUS_DEAD_LETTER, last_error_code='network',
        )
        IntegrationOperation.objects.create(
            **common, deduplication_key='new-successful-publication',
            status=IntegrationOperation.STATUS_SUCCEEDED,
        )
        payload = dashboard_payload(None, access={})
        self.assertFalse(any(item['key'].startswith('integration_failure:') for item in payload['attention']))

    def test_queued_publication_warns_operations_when_scheduler_stops(self):
        farmer = self.farmer('Queued publication', 'Nakuru')
        IntegrationOperation.objects.create(
            integration=IntegrationOperation.INTEGRATION_GOOGLE_SHEETS,
            operation_type='jawabu_master_publish', source_model='JawabuFarmerMaster',
            source_id=str(farmer.pk), deduplication_key='queued-dashboard-test',
        )
        key = 'portal_sheet_scheduler_stale'
        self.assertIn(key, {item['key'] for item in dashboard_payload(None, access={})['attention']})
        self.assertNotIn(key, {item['key'] for item in dashboard_payload(None, access={'branches': ['Nakuru']})['attention']})
        DurableJobRunnerHeartbeat.objects.create(
            runner_key='portal_sheet_publications', status=DurableJobRunnerHeartbeat.STATUS_SUCCEEDED,
        )
        self.assertNotIn(key, {item['key'] for item in dashboard_payload(None, access={})['attention']})

    def test_invoice_identity_attention_does_not_cross_branch_scope(self):
        allowed = self.farmer('Allowed farmer', 'Nakuru', national_id='11111111')
        other = self.farmer('Other farmer', 'Ruiru', national_id='22222222')
        batch = InvoiceUploadBatch.objects.create(original_filename='invoices.pdf')
        for index, farmer in enumerate((allowed, other), start=1):
            invoice = ParsedInvoice.objects.create(
                batch=batch,
                invoice_no=f'INV-{index}',
                customer_name='Different person',
                customer_id=f'9000000{index}',
                matched_farmer=farmer,
                matched_order_number=farmer.order_number,
                status='matched',
            )
            InvoiceIdentityReview.objects.create(invoice=invoice, farmer=farmer)

        payload = dashboard_payload(None, access={'branches': ['Nakuru']})
        attention = {item['key']: item for item in payload['attention']}

        self.assertEqual(attention['invoice_identity']['count'], 1)

    def test_dashboard_keeps_legacy_counts_and_adds_action_contract(self):
        self.farmer('Farmer', 'Nakuru')
        payload = dashboard_payload(None, access={})

        self.assertIn('counts', payload)
        self.assertIn('queues', payload)
        self.assertIn('attention', payload)
        self.assertIn('activity_7d', payload)
        self.assertIn('pipeline_distribution', payload)
        self.assertIn('pipeline', payload)
        self.assertIn('overview', payload)
        self.assertNotIn('deferred', {item['key'] for item in payload['pipeline']})
        self.assertIn('recent_cases', payload)
        self.assertIn('home', payload)
        self.assertTrue(payload['home']['actions'])
        self.assertEqual(payload['home']['actions'][0]['label'], 'Farmer')
        self.assertEqual(payload['notification_count'], 1)

    def test_home_only_access_does_not_expose_general_pipeline(self):
        self.farmer('Private farmer', 'Nakuru')
        user = get_user_model().objects.create_user(username='home-only', password='unused')
        with patch('core.services.portal_dashboard.effective_capability_keys', return_value={'portal.dashboard.view'}):
            payload = dashboard_payload(user, access={'roles': ['BM'], 'grants': []})
        self.assertEqual(payload['home']['actions'], [])
        self.assertEqual(payload['notification_items'], [])
        self.assertEqual(payload['counts'], {})
        self.assertEqual(payload['pipeline'], [])
        self.assertEqual(payload['overview'], {})

    def test_credit_home_only_prompts_for_credit_reappraisal(self):
        today = timezone.localdate()
        self.farmer('Visit reappraisal', 'Nakuru', workflow_state='deferred', deferred_stage='jbl_visit', deferred_until=today)
        self.farmer('Credit reappraisal', 'Nakuru', workflow_state='deferred', deferred_stage='credit', deferred_until=today)
        user = get_user_model().objects.create_superuser(username='credit-home-test', password='unused')
        capabilities = {
            'portal.dashboard.view', 'portal.case.read', 'portal.deferred.view',
            'portal.credit_queue.view', 'portal.credit.write',
        }
        with patch('core.services.portal_dashboard.effective_capability_keys', return_value=capabilities):
            payload = dashboard_payload(user, access={'roles': ['CREDIT_ANALYST']})
        reappraisals = [item['label'] for item in payload['home']['actions'] if 'reappraisal' in item['detail'].lower()]
        self.assertEqual(reappraisals, ['Credit reappraisal'])

    def test_business_metrics_count_only_named_pipeline_outcomes_in_scope(self):
        allowed = self.farmer('Allowed farmer', 'Nakuru')
        other = self.farmer('Other farmer', 'Ruiru')
        now = timezone.now()
        record_pipeline_event(allowed, action='jbl_visit_completed', stage_key='jbl_visit', occurred_at=now)
        record_pipeline_event(allowed, action='credit_decision_recorded', stage_key='credit', occurred_at=now - timedelta(days=2))
        record_pipeline_event(allowed, action='screen_opened', stage_key='credit', occurred_at=now)
        record_pipeline_event(other, action='jbl_visit_completed', stage_key='jbl_visit', occurred_at=now)

        payload = dashboard_payload(None, access={'branches': ['Nakuru']})
        metrics = {item['key']: item for item in payload['business_metrics']}

        self.assertEqual(metrics['visits_completed']['today'], 1)
        self.assertEqual(metrics['visits_completed']['last_7_days'], 1)
        self.assertEqual(metrics['credit_decisions']['today'], 0)
        self.assertEqual(metrics['credit_decisions']['last_7_days'], 1)
        self.assertEqual(metrics['final_decisions']['last_7_days'], 0)
        self.assertEqual(metrics['orders_finalized']['last_7_days'], 0)

    def test_notifications_target_exact_cases_and_exclude_ordinary_deferrals(self):
        actionable = self.farmer('Visit action', 'Nakuru')
        self.farmer(
            'Still deferred', 'Nakuru', workflow_state='deferred',
            deferred_stage='jbl_visit', deferred_until=timezone.localdate() + timedelta(days=1),
        )
        due = self.farmer(
            'Reappraisal action', 'Nakuru', workflow_state='deferred',
            deferred_stage='jbl_visit', deferred_until=timezone.localdate(),
        )

        payload = dashboard_payload(None, access={'branches': ['Nakuru']})
        notifications = {item['farmer_id']: item for item in payload['notification_items'] if item['kind'] == 'case'}

        self.assertIn(str(actionable.pk), notifications)
        self.assertIn(f'focus={actionable.pk}', notifications[str(actionable.pk)]['url'])
        self.assertNotIn('Still deferred', {item['label'] for item in notifications.values()})
        self.assertEqual(notifications[str(due.pk)]['detail'], '60-day deferral ended · reappraisal required')

    def test_new_deferral_uses_sixty_day_policy(self):
        from core.services.jawabu_pipeline import DEFERRAL_MAX_DAYS, _set_deferral

        farmer = self.farmer('Deferred farmer', 'Nakuru')
        _set_deferral(farmer, 'jbl_visit', 'Test User', 'deferral-policy-test')

        self.assertEqual(DEFERRAL_MAX_DAYS, 60)
        self.assertEqual(farmer.deferred_until, timezone.localdate(farmer.deferred_at) + timedelta(days=60))
