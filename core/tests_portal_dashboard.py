from datetime import date, timedelta
from unittest.mock import patch
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from core.models import DurableJobRunnerHeartbeat, IntegrationOperation, InvoiceIdentityReview, InvoiceUploadBatch, JawabuFarmerMaster, ParsedInvoice
from core.services.portal_dashboard import dashboard_payload
from core.services.jawabu_case360 import record_pipeline_event


class PortalActionDashboardTests(TestCase):
    def test_mixed_grants_do_not_borrow_view_scope_for_visit_actions(self):
        self.farmer('Assigned visit', 'Nakuru')
        self.farmer('View only', 'Ruiru')
        user = get_user_model().objects.create_user(username='inbox-mixed-synthetic')
        grants = [
            SimpleNamespace(pk=1, role='JBL_OFFICER', branch='Nakuru', product='', group_configuration_id=None, group_configuration=None),
            SimpleNamespace(pk=2, role='OPERATIONS_ADMIN', branch='Ruiru', product='', group_configuration_id=None, group_configuration=None),
        ]
        capabilities = {'portal.dashboard.view', 'portal.jbl_queue.view', 'portal.jbl_visit.write'}
        with patch('core.services.portal_dashboard.effective_capability_keys', return_value=capabilities):
            payload = dashboard_payload(user, access={'grants': grants})
        self.assertEqual(payload['notification_count'], 1)
        self.assertEqual([row['label'] for row in payload['notification_items']], ['Assigned visit'])
        self.assertEqual(payload['home']['queues'][0]['count'], 1)

    def test_payment_batch_is_one_task_not_one_per_member(self):
        from core.models import GroupSheetConfiguration
        from payments.models import PaymentBatch, PaymentBatchCase
        from core.services.portal_dashboard import _payment_review_home
        group = GroupSheetConfiguration.objects.create(group_id='inbox-training', sheet_id='training')
        batch = PaymentBatch.objects.create(group_configuration=group, status=PaymentBatch.STATUS_IN_REVIEW)
        for index in range(3):
            PaymentBatchCase.objects.create(batch=batch, farmer=self.farmer(f'Payment training {index}', 'Nakuru'),
                                           payment_mode='LOAN-JAWABU', case_digest='synthetic')
        actions, queue = _payment_review_home(None, {}, {'portal.payment.review'})
        self.assertEqual(len(actions), 1)
        self.assertEqual(queue['count'], 1)
        self.assertEqual(actions[0]['detail'], '3 case decisions needed')
        self.assertEqual(actions[0]['key'], f'payment_review:{batch.pk}')

    def test_each_failed_operation_has_a_reachable_notification(self):
        for index in range(3):
            IntegrationOperation.objects.create(
                integration=IntegrationOperation.INTEGRATION_GOOGLE_SHEETS,
                operation_type='training_sync', source_model='Training', source_id=str(index),
                deduplication_key=f'inbox-training-failure-{index}',
                status=IntegrationOperation.STATUS_DEAD_LETTER, last_error_code='network',
            )
        payload = dashboard_payload(None, access={})
        self.assertEqual(payload['notification_count'], 3)
        self.assertEqual(len({row['key'] for row in payload['notification_items']}), 3)
        self.assertTrue(all(row['kind'] == 'system' and row['url'] for row in payload['notification_items']))

    def test_invalid_sync_source_does_not_break_home(self):
        IntegrationOperation.objects.create(
            integration=IntegrationOperation.INTEGRATION_GOOGLE_SHEETS,
            operation_type='training_sync', source_model='JawabuFarmerMaster',
            source_id='invalid-or-deleted', deduplication_key='inbox-invalid-source',
            status=IntegrationOperation.STATUS_DEAD_LETTER, last_error_code='network',
        )
        self.assertEqual(dashboard_payload(None, access={})['notification_count'], 1)

    def test_import_versions_are_one_worklist_task(self):
        from uuid import uuid4
        from core.models import JawabuFarmerUploadBatch
        from core.services.portal_dashboard import _import_review_home
        worklist = uuid4()
        for version in (1, 2):
            JawabuFarmerUploadBatch.objects.create(
                worklist_id=worklist, version_number=version,
                import_kind='farmers', status='pending_review', is_current_version=True,
                source_filename=f'training-v{version}.csv',
            )
        actions, queues = _import_review_home(None, {}, {'portal.farmup.view'})
        self.assertEqual(len(actions), 1)
        self.assertEqual(queues[0]['count'], 1)
        self.assertEqual(actions[0]['label'], 'training-v2.csv')

    def test_inbox_pages_cover_every_counted_task_without_sampling(self):
        for index in range(23):
            self.farmer(f'Training farmer {index:02}', 'Nakuru')
        self.farmer('Outside branch', 'Ruiru')
        seen = []
        for page in (1, 2, 3):
            payload = dashboard_payload(None, access={'branches': ['Nakuru']}, notification_page=page)
            self.assertEqual(payload['notification_count'], 23)
            self.assertEqual(payload['notification_pagination']['page'], page)
            self.assertEqual(payload['notification_pagination']['pages'], 3)
            self.assertEqual(len(payload['notification_items']), 10 if page < 3 else 3)
            seen.extend(item['key'] for item in payload['notification_items'])
        self.assertEqual(len(set(seen)), 23)
        for page in ('invalid', 999):
            payload = dashboard_payload(None, access={'branches': ['Nakuru']}, notification_page=page)
            self.assertIn(payload['notification_pagination']['page'], (1, 3))

    def test_empty_inbox_has_zero_range_and_no_items(self):
        payload = dashboard_payload(None, access={})
        self.assertEqual(payload['notification_count'], 0)
        self.assertEqual(payload['notification_items'], [])
        self.assertEqual(payload['notification_pagination']['start'], 0)
        self.assertEqual(payload['notification_pagination']['end'], 0)

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
        queued = next(item for item in dashboard_payload(None, access={})['attention'] if item['key'] == key)
        self.assertEqual(queued['action']['type'], 'publication_wake')
        self.assertFalse(queued['url'])
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

    def test_origination_capability_does_not_add_portal_home_content(self):
        user = get_user_model().objects.create_user(username='origination-home', password='unused')
        capabilities = {'portal.dashboard.view', 'portal.origination.signing.staff'}
        with patch('core.services.portal_dashboard.effective_capability_keys', return_value=capabilities):
            payload = dashboard_payload(user, access={'roles': ['BM'], 'grants': []})

        self.assertEqual(payload['notification_count'], 0)
        self.assertEqual(payload['notification_items'], [])
        self.assertEqual(payload['home']['actions'], [])
        self.assertEqual(payload['home']['queues'], [])
        self.assertEqual(payload['home']['shortcuts'], [])

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
