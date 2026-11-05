"""Withdrawal transition contracts against the real signed Portal API."""
import json
import uuid
from datetime import timedelta
from types import SimpleNamespace

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import JawabuFarmerMaster
from core.services.jawabu_pipeline import deferred_queue, current_pipeline_state_label, is_reappraisal_required
from core.tests_telegram_authentication import BOT_TOKEN
from portal_legacy.tests import LegacyHTTPMixin


@override_settings(TELEGRAM_BOT_TOKEN=BOT_TOKEN, PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True,
                   SECURE_SSL_REDIRECT=False, REQUIRE_MINIAPP_IDEMPOTENCY_KEY=True)
class PortalWithdrawalTests(LegacyHTTPMixin, TestCase):
    def case(self, stage='credit', **values):
        return JawabuFarmerMaster.objects.create(group_configuration=self.group, customer_name='SYNTHETIC CLIENT',
            source='jawabu_office_lead', workflow_state=stage, **values)

    def change(self, farmer, action='withdraw', *, note='Client requested a pause.', key=None, revision=None):
        return self.client.post(reverse('portal_case_withdrawal', args=[farmer.pk]),
            json.dumps({'action': action, 'reason': note, 'workflow_revision': revision or farmer.workflow_revision}),
            content_type='application/json', HTTP_X_REQUEST_ID=key or str(uuid.uuid4()), **self.headers)

    def test_each_stage_withdraws_and_resumes_same_case_once(self):
        for stage in ['jbl_visit', 'credit', 'final_review', 'order']:
            with self.subTest(stage=stage):
                farmer = self.case(stage)
                key = str(uuid.uuid4())
                response = self.change(farmer, key=key)
                self.assertEqual(response.status_code, 200, response.content)
                farmer.refresh_from_db()
                self.assertEqual((farmer.workflow_state, farmer.withdrawn_stage), ('withdrawn', stage))
                self.assertIn(farmer, deferred_queue())
                self.assertTrue(current_pipeline_state_label(farmer).startswith('Withdrawn — '))
                self.assertEqual(self.change(farmer, key=key).status_code, 200)
                self.assertEqual(farmer.pipeline_events.filter(action='case_withdrawn').count(), 1)
                self.assertEqual(self.change(farmer, key=key, note='Different payload').status_code, 400)
                self.assertEqual(self.change(farmer, 'resume').status_code, 200)
                farmer.refresh_from_db()
                self.assertEqual((farmer.workflow_state, farmer.withdrawn_stage), (stage, ''))
                self.assertFalse(is_reappraisal_required(farmer))
                self.assertEqual(farmer.pipeline_events.filter(action='withdrawal_resumed').count(), 1)

    def test_invalid_stale_and_unrelated_authority_cannot_change_state(self):
        farmer = self.case()
        self.assertEqual(self.change(farmer, note='').status_code, 400)
        self.assertEqual(self.change(farmer, revision=99).status_code, 409)
        self.staff('JBL_OFFICER')
        self.assertEqual(self.change(farmer).status_code, 403)
        farmer.refresh_from_db()
        self.assertEqual(farmer.workflow_state, 'credit')
        self.assertFalse(farmer.pipeline_events.exists())

    def test_existing_order_and_finance_evidence_are_not_rewritten(self):
        for values in [{'order_number': 'HB-TEST'}, {'invoice_number': 'INV-TEST'}]:
            farmer = self.case('order', **values)
            self.assertEqual(self.change(farmer).status_code, 400)
            farmer.refresh_from_db()
            self.assertEqual(farmer.workflow_state, 'order')
            self.assertFalse(farmer.pipeline_events.exists())

    def test_changed_revision_queues_status_and_comment_for_sheet_publication(self):
        from core.models import IntegrationOperation
        from core.services.jawabu_pipeline import master_projection_fields
        self.group.workflow = {**self.group.workflow, 'master_sync_enabled': True}
        self.group.save(update_fields=['workflow'])
        farmer = self.case()
        self.assertEqual(self.change(farmer).status_code, 200)
        farmer.refresh_from_db()
        operation = IntegrationOperation.objects.get(source_id=str(farmer.pk))
        self.assertEqual(operation.metadata['workflow_revision'], farmer.workflow_revision)
        projection = master_projection_fields(farmer)
        self.assertEqual(projection['current_pipeline_state'][1], 'Withdrawn — Credit Analysis')
        self.assertIn('Client requested a pause.', projection['case_comment_history'][1])

    def test_resuming_an_old_hold_has_no_deferral_deadline_or_queue_dead_end(self):
        farmer = self.case('deferred', deferred_stage='credit', credit_decision='Deferred / On Hold',
            deferred_at=timezone.now()-timedelta(days=120), deferred_until=timezone.localdate()-timedelta(days=60))
        self.assertEqual(self.change(farmer).status_code, 200)
        farmer.refresh_from_db()
        self.assertIsNone(farmer.deferred_until)
        self.assertEqual(self.change(farmer, 'resume').status_code, 200)
        farmer.refresh_from_db()
        from core.services.jawabu_pipeline import credit_queue
        self.assertIn(farmer, credit_queue())
        self.assertFalse(is_reappraisal_required(farmer))

    def test_withdrawal_pauses_measured_clock_without_resetting_original_intake(self):
        from core.services.jawabu_case360 import calculate_case_tat
        farmer = self.case('withdrawn', withdrawn_stage='credit')
        now = timezone.now()
        def event(action, days):
            return SimpleNamespace(action=action, occurred_at=now-timedelta(days=days), new_values={}, metadata={})
        events = [event('application_imported', 4), event('case_withdrawn', 3)]
        paused = calculate_case_tat(farmer, now=now, events=events, hb_events=[], targets={}, holidays=[])
        self.assertFalse(paused['running'])
        self.assertEqual(paused['stages'][0]['elapsed_seconds'], 86400)
        events.extend([event('withdrawal_resumed', 1), event('jbl_visit_completed', 0)])
        farmer.workflow_state = 'credit'
        resumed = calculate_case_tat(farmer, now=now, events=events, hb_events=[], targets={}, holidays=[])
        self.assertEqual(resumed['stages'][0]['elapsed_seconds'], 172800)

    def test_existing_rejected_and_deferred_summaries_keep_their_stage(self):
        from core.services.portal_decisions import decision_context
        for state, decision in [('deferred', 'Deferred / On Hold'), ('rejected', 'Rejected')]:
            farmer = self.case(state, deferred_stage='credit', credit_decision=decision)
            context = decision_context(farmer, {})
            self.assertEqual(context['outcome'], state.title())
            self.assertEqual(context['stage'], 'credit')
            self.assertEqual(context['stage_label'], 'Credit analysis')
