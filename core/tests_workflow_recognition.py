from datetime import datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from core.models import JawabuFarmerMaster, JawabuPipelineEvent
from core.services.workflow_recognition import (
    MINIMUM_RANKED_SAMPLE,
    ON_TIME_SLA_STATES,
    _accumulate_tat_sample,
    _empty_tat_counts,
    _score_rows,
    portal_performance_payload,
    tat_recognition_payload,
)


class WorkflowRecognitionScoreTests(SimpleTestCase):
    def test_near_target_completion_is_still_on_time(self):
        self.assertIn('within_target', ON_TIME_SLA_STATES)
        self.assertIn('near_target', ON_TIME_SLA_STATES)
        self.assertNotIn('overdue', ON_TIME_SLA_STATES)

    def test_small_samples_are_visible_but_not_ranked(self):
        rows = _score_rows([
            {'label': 'BRO A', 'completed': MINIMUM_RANKED_SAMPLE - 1, 'on_time_rate': 100},
            {'label': 'BRO B', 'completed': MINIMUM_RANKED_SAMPLE, 'on_time_rate': 80},
        ], quality_key='on_time_rate', volume_key='completed')

        by_label = {row['label']: row for row in rows}
        self.assertFalse(by_label['BRO A']['ranked'])
        self.assertIsNone(by_label['BRO A']['rank'])
        self.assertTrue(by_label['BRO B']['ranked'])
        self.assertEqual(by_label['BRO B']['rank'], 1)

    def test_equal_balanced_results_share_a_rank(self):
        rows = _score_rows([
            {'label': 'Team A', 'visits_completed': 20, 'credit_ready': 18, 'credit_conversion': 90},
            {'label': 'Team B', 'visits_completed': 20, 'credit_ready': 18, 'credit_conversion': 90},
        ], quality_key='credit_conversion', volume_key='visits_completed', success_key='credit_ready')

        self.assertEqual([row['rank'] for row in rows], [1, 1])
        self.assertEqual([row['score'] for row in rows], [69.9, 69.9])

    def test_score_does_not_change_when_a_higher_volume_row_is_visible(self):
        base = {'label': 'Team A', 'completed': 20, 'on_time': 16, 'on_time_rate': 80}
        alone = _score_rows(
            [dict(base)], quality_key='on_time_rate', volume_key='completed', success_key='on_time',
        )[0]['score']
        together = _score_rows([
            dict(base),
            {'label': 'Team B', 'completed': 200, 'on_time': 160, 'on_time_rate': 80},
        ], quality_key='on_time_rate', volume_key='completed', success_key='on_time')

        self.assertEqual(next(row['score'] for row in together if row['label'] == 'Team A'), alone)

    def test_people_rank_only_against_the_same_cohort(self):
        rows = _score_rows([
            {'label': 'A', 'cohort': 'Branch 1', 'completed': 20, 'on_time': 16, 'on_time_rate': 80},
            {'label': 'B', 'cohort': 'Branch 1', 'completed': 20, 'on_time': 18, 'on_time_rate': 90},
            {'label': 'C', 'cohort': 'Branch 2', 'completed': 20, 'on_time': 10, 'on_time_rate': 50},
        ], quality_key='on_time_rate', volume_key='completed', success_key='on_time', rank_group_key='cohort')

        by_label = {row['label']: row for row in rows}
        self.assertEqual(by_label['B']['rank'], 1)
        self.assertEqual(by_label['A']['rank'], 2)
        self.assertEqual(by_label['C']['rank'], 1)

    def test_target_unavailable_is_excluded_from_score_and_eligibility_sample(self):
        counts = _empty_tat_counts()
        _accumulate_tat_sample(counts, {
            'sla_state': 'target_unavailable', 'elapsed_minutes': 12, 'corrected': False,
        }, attribution_fallback=False)
        _accumulate_tat_sample(counts, {
            'sla_state': 'near_target', 'elapsed_minutes': 10, 'corrected': True,
        }, attribution_fallback=True)

        self.assertEqual(counts['completed_total'], 2)
        self.assertEqual(counts['completed'], 1)
        self.assertEqual(counts['on_time'], 1)
        self.assertEqual(counts['excluded_target_unavailable'], 1)
        self.assertEqual(counts['corrected'], 1)
        self.assertEqual(counts['attribution_fallback'], 1)


class PortalRecognitionProjectionTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='recognition-superuser', is_active=True, is_superuser=True,
        )
        self.farmer = JawabuFarmerMaster.objects.create(
            customer_name='Recognition Case', branch='Branch A',
            jbl_visit_status='Visited, Awaiting Credit Analysis',
        )

    def _event(self, when, status):
        return JawabuPipelineEvent.objects.create(
            farmer=self.farmer, action='jbl_visit_completed', stage_key='jbl_visit',
            actor='Recognition User', actor_user=self.user, occurred_at=when,
            new_values={'status': status},
        )

    def test_first_accepted_completion_owns_period_and_current_correction_updates_quality(self):
        self._event(
            timezone.make_aware(datetime(2026, 8, 5, 9, 0)),
            'Deferred / On Hold',
        )
        self._event(
            timezone.make_aware(datetime(2026, 9, 2, 9, 0)),
            'Visited, Awaiting Credit Analysis',
        )

        august = portal_performance_payload(self.user, period='2026-08')
        september = portal_performance_payload(self.user, period='2026-09')

        self.assertEqual(august['team_rows'][0]['visits_completed'], 1)
        self.assertEqual(august['team_rows'][0]['credit_ready'], 1)
        self.assertEqual(september['team_rows'], [])
        self.assertEqual(august['result_status'], 'live_provisional')


class TatRecognitionPresentationTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='tat-recognition-user', first_name='Mary', last_name='Wanjiku',
        )

    def _sample(self, *, role='BRO', branch='Embu', product='Standard', sla_state='within_target'):
        return {
            'group_id': '-100tat', 'case_id': f'case-{role}-{branch}-{product}',
            'stage_key': 'bro_review', 'role': role, 'branch': branch,
            'product': product, 'product_key': product.lower(),
            'person_user_id': str(self.user.pk), 'person': 'Mary Wanjiku',
            'sla_state': sla_state, 'elapsed_minutes': 60, 'corrected': False,
        }

    @patch('core.services.tat_reporting._metric_scope_q', return_value=Q())
    @patch('core.services.tat_reporting._stage_samples')
    def test_ordinary_payload_is_structured_without_technical_methodology(self, stage_samples, _scope):
        stage_samples.return_value = [self._sample() for _ in range(20)]

        payload = tat_recognition_payload(self.user, period='2026-09', include_people=False)

        row = payload['team_rows'][0]
        self.assertEqual((row['role'], row['branch'], row['product']), ('BRO', 'Embu', 'Standard'))
        self.assertTrue(row['ranked'])
        self.assertEqual(row['rank'], 1)
        self.assertEqual(row['on_time_rate'], 100.0)
        self.assertTrue(row['key'].startswith('cohort-'))
        self.assertNotIn('-100tat', row['key'])
        self.assertFalse(payload['technical_details_visible'])
        self.assertIsNone(payload['methodology'])
        self.assertEqual(payload['people_rows'], [])
        self.assertNotIn('formula', payload)

    @patch('core.services.tat_reporting._metric_scope_q', return_value=Q())
    @patch('core.services.tat_reporting._stage_samples')
    def test_management_payload_keeps_multiple_cohorts_and_one_audit_summary(self, stage_samples, _scope):
        stage_samples.return_value = (
            [self._sample() for _ in range(20)]
            + [self._sample(role='CA', branch='Nakuru', product='HOCC') for _ in range(19)]
            + [self._sample(role='CA', branch='Nakuru', product='HOCC', sla_state='target_unavailable')]
        )

        payload = tat_recognition_payload(self.user, period='2026-09', include_people=True)

        self.assertEqual(len(payload['personal_rows']), 2)
        by_role = {row['role']: row for row in payload['personal_rows']}
        self.assertTrue(by_role['BRO']['ranked'])
        self.assertFalse(by_role['CA']['ranked'])
        self.assertEqual(by_role['CA']['completed'], 19)
        self.assertEqual(by_role['CA']['excluded_target_unavailable'], 1)
        self.assertTrue(payload['technical_details_visible'])
        self.assertTrue(payload['people_visible'])
        self.assertIn('Wilson', payload['methodology']['score_method'])
        self.assertEqual(payload['methodology']['excluded_target_unavailable'], 1)
