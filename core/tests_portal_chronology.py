from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase

from core.models import JawabuFarmerMaster
from core.services.jawabu_case360 import calculate_case_tat
from core.services.portal_search import case_search


class PortalChronologyTests(SimpleTestCase):
    def setUp(self):
        self.start = datetime(2026, 11, 1, tzinfo=timezone.utc)
        self.case = SimpleNamespace(workflow_state='', deferred_stage='')

    def event(self, action, hours, **values):
        return SimpleNamespace(action=action, occurred_at=self.start + timedelta(hours=hours), new_values=values, metadata={})

    def tat(self, events, hb=(), hours=12):
        return calculate_case_tat(self.case, events=events, hb_events=hb, targets={}, holidays=set(), now=self.start + timedelta(hours=hours))

    def test_alternative_visit_outcomes_are_not_an_extra_stage_or_clock(self):
        events = [self.event('application_imported', 0), self.event('jbl_visit_completed', 1),
                  self.event('credit_decision_recorded', 2, decision='Approved')]
        tat = self.tat(events)
        self.assertEqual([s['label'] for s in tat['stages']], ['Intake', 'JBL Visit', 'Credit Decision',
            'Final Decision', 'Order Assigned/Sent to HB', 'HB Installation', 'HB Commissioning'])
        self.assertEqual([s['label'] for s in tat['stages'] if s['running']], ['Final Decision'])
        self.assertEqual(tat['stages'][2]['minutes'], '60.00')

    def test_rescheduled_no_visit_stays_in_visit_and_has_no_credit_clock(self):
        tat = self.tat([self.event('application_imported', 0), self.event('jbl_outcome_recorded', 2, status='Rescheduled')])
        self.assertEqual([s['label'] for s in tat['stages'] if s['running']], ['JBL Visit'])
        self.assertEqual(tat['stages'][2]['stage_state'], 'pending')

    def test_missing_visit_timestamp_cannot_leave_visit_running_after_credit(self):
        self.case.workflow_state = 'final_review'
        tat = self.tat([self.event('application_imported', 0), self.event('credit_decision_recorded', 3)])
        self.assertEqual(tat['stages'][1]['stage_state'], 'completed')
        self.assertEqual(tat['stages'][1]['timing_note'], 'Timing unavailable')
        self.assertEqual([s['label'] for s in tat['stages'] if s['running']], ['Final Decision'])

    def test_order_assignment_waits_for_handover(self):
        events = [self.event('application_imported', 0), self.event('final_decision_recorded', 3), self.event('order_assigned', 5)]
        tat = self.tat(events)
        self.assertEqual([s['label'] for s in tat['stages'] if s['running']], ['Order Assigned/Sent to HB'])
        self.assertEqual(tat['stages'][5]['stage_state'], 'pending')

    def test_handover_installation_commissioning_and_payment(self):
        events = [self.event('application_imported', 0), self.event('payment_finalized', 4)]
        def hb(kind, hours, **values):
            return SimpleNamespace(event_type=kind, created_at=self.start + timedelta(hours=hours), new_values=values)
        release = hb('order.released_to_hb', 5)
        installed = hb('installation.progressed', 7, installation_status='installed')
        finished = hb('commissioning.completed', 9, commissioning_status='commissioned')
        tat = self.tat(events, [release])
        self.assertEqual([s['label'] for s in tat['stages'] if s['running']], ['HB Installation'])
        tat = self.tat(events, [release, installed, finished])
        self.assertFalse(tat['running'])
        self.assertEqual(tat['elapsed_seconds'], 9 * 3600)

    def test_deferral_freezes_then_resumes_same_stage(self):
        events = [self.event('application_imported', 0), self.event('deferral_started', 2)]
        first = self.tat(events, hours=6)
        later = self.tat(events, hours=9)
        self.assertFalse(first['running'])
        self.assertEqual(first['elapsed_seconds'], later['elapsed_seconds'])
        events.append(self.event('deferral_ended', 10))
        self.assertTrue(self.tat(events)['stages'][1]['running'])

    def test_rework_invalidates_old_downstream_milestones(self):
        self.case.workflow_state = 'credit'
        events = [self.event('application_imported', 0), self.event('jbl_visit_completed', 1),
                  self.event('credit_decision_recorded', 2), self.event('final_decision_recorded', 3),
                  self.event('returned_for_rework', 5, returned_to='credit')]
        tat = self.tat(events)
        self.assertEqual([s['label'] for s in tat['stages'] if s['running']], ['Credit Decision'])
        self.assertEqual(tat['stages'][2]['elapsed_seconds'], 7 * 3600)
        self.assertEqual(tat['stages'][3]['stage_state'], 'pending')

    def test_rejection_stops_at_its_outcome(self):
        self.case.workflow_state = 'rejected'
        tat = self.tat([self.event('application_imported', 0), self.event('jbl_outcome_recorded', 2, status='Rejected by JBL')])
        self.assertFalse(tat['running'])
        self.assertEqual(tat['elapsed_seconds'], 7200)

    def test_backwards_milestones_do_not_produce_a_live_clock(self):
        self.case.workflow_state = 'final_review'
        tat = self.tat([self.event('application_imported', 0), self.event('credit_decision_recorded', 1),
                        self.event('jbl_visit_completed', 2)])
        self.assertFalse(any(s['running'] for s in tat['stages']))

    def test_unknown_terminal_or_pause_time_never_accrues_elapsed_time(self):
        for state in ['rejected', 'withdrawn', 'deferred']:
            self.case.workflow_state = state
            self.case.deferred_stage = 'jbl_visit'
            tat = self.tat([self.event('application_imported', 0)])
            self.assertIsNone(tat['elapsed_seconds'])
            self.assertIsNone(tat['stages'][1]['elapsed_seconds'])
            self.assertFalse(tat['running'])

    def test_unreviewed_legacy_does_not_mark_unreached_stages_complete(self):
        self.case.workflow_state = 'legacy_review'
        tat = self.tat([self.event('application_imported', 0)])
        self.assertEqual(tat['stages'][6]['stage_state'], 'pending')
        self.assertFalse(tat['running'])

    def test_ordered_without_old_events_waits_for_handover_and_known_commissioning_stops(self):
        self.case.workflow_state = 'ordered'
        tat = self.tat([])
        self.assertEqual(tat['stages'][1]['stage_state'], 'completed')
        self.assertEqual(tat['stages'][4]['stage_state'], 'timing_unavailable')
        self.case.homebiogas_action = SimpleNamespace(installation_status='installed', commissioning_status='commissioned')
        tat = self.tat([])
        self.assertTrue(all(s['stage_state'] == 'completed' for s in tat['stages']))
        self.assertFalse(tat['running'])
        self.assertIsNone(tat['elapsed_seconds'])

    def test_invalidated_credit_does_not_show_final_as_completed(self):
        self.case.workflow_state = 'order'
        events = [self.event('application_imported', 0), self.event('jbl_visit_completed', 1),
                  self.event('credit_decision_recorded', 2), self.event('final_decision_recorded', 3)]
        approval = SimpleNamespace(gate='credit', status='invalidated', expires_at=None,
                                   invalidated_at=self.start + timedelta(hours=5))
        tat = calculate_case_tat(self.case, events=events, hb_events=[], targets={}, holidays=set(),
            approvals=[approval], now=self.start + timedelta(hours=12))
        self.assertEqual([s['label'] for s in tat['stages'] if s['running']], ['Credit Decision'])
        self.assertEqual(tat['stages'][3]['stage_state'], 'pending')


class PortalWordSearchTests(TestCase):
    def test_name_words_are_order_independent_without_cross_field_matches(self):
        wanted = JawabuFarmerMaster.objects.create(customer_name='Juliet Kawira Mutegi', lead_name='Mary Ann Smith')
        JawabuFarmerMaster.objects.create(customer_name='Juliet Other', county='Mutegi')
        for term in ['Juliet Mutegi', 'mutegi juliet', '  Kawira  JULIET ', 'Smith Mary']:
            with self.subTest(term=term):
                self.assertEqual(list(JawabuFarmerMaster.objects.filter(case_search(term, fields=('county',))).values_list('pk', flat=True)), [wanted.pk])
        self.assertFalse(JawabuFarmerMaster.objects.filter(case_search('Juliet Unknown')).exists())


class PortalDecisionChronologyTests(TestCase):
    def test_future_upstream_dates_block_decisions_without_publication(self):
        from django.utils import timezone as django_timezone
        from unittest.mock import patch
        from core.services.jawabu_pipeline import set_credit_decision, set_final_decision
        case = JawabuFarmerMaster.objects.create(customer_name='Synthetic chronology', workflow_state='credit',
            jbl_visit_date=django_timezone.localdate() + timedelta(days=1))
        with patch('core.services.portal_publication.reserve_farmer_publication') as publish:
            ok, error = set_credit_decision(case, decision='Approved', imab_created='Yes', customer_no='SYNTHETIC', sender='Synthetic')
            self.assertFalse(ok)
            self.assertIn('cannot precede', error)
            case.workflow_state = 'final_review'
            case.credit_decided_at = django_timezone.now() + timedelta(hours=1)
            case.save(update_fields=['workflow_state', 'credit_decided_at'])
            ok, error = set_final_decision(case, final_decision='Approved', sender='Synthetic')
            self.assertFalse(ok)
            self.assertIn('cannot precede', error)
            publish.assert_not_called()
