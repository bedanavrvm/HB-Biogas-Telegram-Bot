from datetime import date, datetime
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.db.models import Q
from django.test import SimpleTestCase, TestCase, TransactionTestCase
from django.utils import timezone

from core.models import AccessGrant, JawabuFarmerMaster, JawabuPipelineEvent, TatTrackerCase
from core.services.workflow_recognition import (
    MINIMUM_RANKED_SAMPLE,
    ON_TIME_SLA_STATES,
    _accumulate_tat_sample,
    _empty_tat_counts,
    _score_rows,
    _recognition_period,
    portal_performance_payload,
    tat_recognition_payload,
)


class WorkflowRecognitionScoreTests(SimpleTestCase):
    def test_calendar_quarter_boundaries_are_unambiguous(self):
        self.assertEqual(_recognition_period('quarter', '2026-Q1')[:3], (
            date(2026, 1, 1), date(2026, 3, 31), '2026-Q1',
        ))
        self.assertEqual(_recognition_period('quarter', '2026-Q2')[:3], (
            date(2026, 4, 1), date(2026, 6, 30), '2026-Q2',
        ))
        self.assertEqual(_recognition_period('year', '2026')[:3], (
            date(2026, 1, 1), date(2026, 12, 31), '2026',
        ))
        with timezone.override('Africa/Nairobi'):
            q1_start, q1_end, *_ = _recognition_period('quarter', '2026-Q1')
            q2_start, q2_end, *_ = _recognition_period('quarter', '2026-Q2')
            last_q1 = timezone.localdate(datetime.fromisoformat('2026-03-31T20:59:00+00:00'))
            first_q2 = timezone.localdate(datetime.fromisoformat('2026-03-31T21:00:00+00:00'))
        self.assertTrue(q1_start <= last_q1 <= q1_end)
        self.assertFalse(q1_start <= first_q2 <= q1_end)
        self.assertTrue(q2_start <= first_q2 <= q2_end)

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

    def _sample(
        self, *, role='BRO', branch='Embu', product='Standard',
        sla_state='within_target', person_user_id=None, person='Mary Wanjiku', case_suffix='',
        person_roles='',
    ):
        return {
            'group_id': '-100tat', 'case_id': f'case-{role}-{branch}-{product}{case_suffix}',
            'stage_key': 'bro_review', 'role': role, 'branch': branch,
            'product': product, 'product_key': product.lower(),
            'person_user_id': str(person_user_id or self.user.pk), 'person': person,
            'person_roles': person_roles,
            'sla_state': sla_state, 'elapsed_minutes': 60, 'corrected': False,
        }

    @patch('core.services.tat_reporting._metric_scope_q', return_value=Q())
    @patch('core.services.tat_reporting._stage_samples')
    def test_ordinary_payload_is_structured_without_technical_methodology(self, stage_samples, _scope):
        stage_samples.return_value = [self._sample() for _ in range(20)]

        payload = tat_recognition_payload(
            self.user, period='2026-09', include_people=False, view='personal',
        )

        row = payload['personal_result']
        self.assertEqual(payload['contract_version'], 3)
        self.assertEqual(payload['selected'], {
            'role': '', 'role_label': '',
            'product': '', 'product_label': '', 'branch': '',
        })
        self.assertEqual(payload['overall_result']['completed'], 20)
        self.assertEqual(payload['slice_result']['share_of_overall'], 100.0)
        self.assertEqual((row['role'], row['branch'], row['product']), ('BRO', 'Embu', 'Standard'))
        self.assertTrue(row['ranked'])
        self.assertEqual(row['rank'], 1)
        self.assertEqual(row['label'], 'You')
        self.assertEqual(row['on_time_rate'], 100.0)
        self.assertNotIn('key', row)
        self.assertFalse(payload['technical_details_visible'])
        self.assertIsNone(payload['methodology'])
        self.assertEqual(payload['standings']['rows'], [])
        self.assertEqual(payload['role_options'], [
            {'key': '', 'label': 'All roles'}, {'key': 'BRO', 'label': 'BRO'},
        ])
        self.assertNotIn('formula', payload)

    @patch('core.services.tat_reporting._metric_scope_q', return_value=Q())
    @patch('core.services.tat_reporting._stage_samples')
    def test_management_payload_keeps_multiple_cohorts_and_one_audit_summary(self, stage_samples, _scope):
        stage_samples.return_value = (
            [self._sample() for _ in range(20)]
            + [self._sample(role='CA', branch='Nakuru', product='HOCC') for _ in range(19)]
            + [self._sample(role='CA', branch='Nakuru', product='HOCC', sla_state='target_unavailable')]
        )

        payload = tat_recognition_payload(
            self.user, period='2026-09', include_people=True,
            role='CA', product='hocc', view='personal',
        )
        unfiltered = tat_recognition_payload(
            self.user, period='2026-09', include_people=True, view='personal',
        )

        self.assertEqual({item['key'] for item in payload['role_options']}, {'', 'BRO', 'CA'})
        self.assertEqual(payload['selected']['role'], 'CA')
        self.assertEqual(payload['selected']['product'], 'hocc')
        self.assertEqual(payload['overall_result'], unfiltered['overall_result'])
        self.assertEqual(payload['slice_result']['completed'], 19)
        self.assertEqual(payload['overall_result']['completed'], 39)
        self.assertTrue(payload['personal_result']['ranked'])
        self.assertEqual(payload['personal_result']['completed'], 19)
        self.assertNotIn('excluded_target_unavailable', payload['personal_result'])
        self.assertTrue(payload['technical_details_visible'])
        self.assertTrue(payload['people_visible'])
        self.assertIn('Wilson', payload['methodology']['score_method'])
        self.assertEqual(payload['methodology']['excluded_target_unavailable'], 1)

    @patch('core.services.tat_reporting._metric_scope_q', return_value=Q())
    @patch('core.services.tat_reporting._stage_samples')
    def test_people_aggregate_once_by_staff_id_before_scoring_and_filtering(self, stage_samples, _scope):
        stage_samples.return_value = (
            [self._sample(role='BRO', branch='Embu', product='Standard', case_suffix=f'-bro-{number}') for number in range(20)]
            + [self._sample(role='CA', branch='Nakuru', product='HOCC', case_suffix=f'-ca-{number}') for number in range(20)]
            + [self._sample(role='BRO', branch='Embu', product='Standard', person_user_id=888,
                            person='Mary Wanjiku', case_suffix=f'-other-{number}') for number in range(20)]
        )
        overall = tat_recognition_payload(self.user, period='2026-09', include_people=True, view='people')
        self.assertEqual(overall['standings']['total'], 2)
        self.assertEqual(overall['standings']['eligible_count'], 2)
        own = next(row for row in overall['standings']['rows'] if row['is_current_user'])
        self.assertEqual(own['completed'], 40)
        self.assertEqual((own['role_count'], own['product_count'], own['branch_count']), (2, 2, 2))
        self.assertEqual(overall['overall_result']['completed'], 40)

        filtered = tat_recognition_payload(
            self.user, period='2026-09', include_people=True, view='people',
            role='BRO', product='standard', branch='Embu',
        )
        self.assertEqual(filtered['standings']['total'], 2)
        self.assertEqual(filtered['overall_result'], overall['overall_result'])
        self.assertEqual(next(row for row in filtered['standings']['rows'] if row['is_current_user'])['completed'], 20)
        self.assertEqual(filtered['slice_result']['completed'], 20)

    @patch('core.services.tat_reporting._metric_scope_q', return_value=Q())
    @patch('core.services.tat_reporting._stage_samples')
    def test_ordinary_people_are_anonymous_and_limited_to_ten_per_page(self, stage_samples, _scope):
        peers = []
        for peer_number in range(1, 13):
            peers.extend(self._sample(
                person_user_id=1000 + peer_number, person=f'Private Person {peer_number}',
                case_suffix=f'-peer-{peer_number}-{sample_number}',
            ) for sample_number in range(20))
        stage_samples.return_value = [
            self._sample(case_suffix=f'-self-{sample_number}') for sample_number in range(20)
        ] + peers

        payload = tat_recognition_payload(
            self.user, period='2026-09', include_people=False, view='people', page=2,
        )

        self.assertEqual(payload['standings']['page_size'], 10)
        self.assertEqual(payload['standings']['page'], 2)
        self.assertEqual(payload['standings']['pages'], 2)
        self.assertEqual(payload['standings']['total'], 13)
        self.assertLessEqual(len(payload['standings']['rows']), 10)
        labels = [row['label'] for row in payload['standings']['rows']]
        self.assertFalse(any(label.startswith('Private Person') for label in labels))
        self.assertTrue(all(label == 'You' or label.startswith('Peer ') for label in labels))
        if payload['standings']['current_user_row']:
            self.assertEqual(payload['standings']['current_user_row']['label'], 'You')
        first_page = tat_recognition_payload(
            self.user, period='2026-09', include_people=False, view='people', page=1,
        )
        self.assertEqual(sum(row['label'] == 'You' for row in first_page['standings']['rows']), 1)
        self.assertIsNone(first_page['standings']['current_user_row'])

    @patch('core.services.tat_reporting._metric_scope_q', return_value=Q())
    @patch('core.services.tat_reporting._stage_samples')
    def test_ordinary_standings_exclude_unrelated_role_product_cohorts(self, stage_samples, _scope):
        stage_samples.return_value = [
            self._sample(case_suffix=f'-self-{number}') for number in range(20)
        ] + [
            self._sample(
                role='CA', product='HOCC', person_user_id=98765,
                person='Other Staff', case_suffix=f'-peer-{number}',
            ) for number in range(20)
        ]

        personal_view = tat_recognition_payload(self.user, period='2026-09', view='people')
        management_view = tat_recognition_payload(self.user, period='2026-09', view='people', include_people=True)
        self.assertEqual({row['role'] for row in personal_view['standings']['rows']}, {'BRO'})
        self.assertEqual({row['role'] for row in management_view['standings']['rows']}, {'BRO', 'CA'})

    @patch('core.services.tat_reporting._metric_scope_q', return_value=Q())
    @patch('core.services.tat_reporting._stage_samples')
    def test_singleton_role_has_numbered_standing(self, stage_samples, _scope):
        stage_samples.return_value = [
            self._sample(case_suffix='-single')
        ]

        payload = tat_recognition_payload(
            self.user, period='2026-09', include_people=False, view='people',
        )

        self.assertFalse(payload['standings']['has_competition'])
        self.assertEqual(payload['standings']['eligible_count'], 1)
        self.assertEqual(payload['standings']['rows'][0]['rank'], 1)
        self.assertTrue(payload['standings']['rows'][0]['ranked'])

    @patch('core.services.tat_reporting._metric_scope_q', return_value=Q())
    @patch('core.services.tat_reporting._stage_samples')
    def test_small_samples_have_numbered_people_standings(self, stage_samples, _scope):
        stage_samples.return_value = [
            self._sample(case_suffix='-self'),
            self._sample(person_user_id=888, person='Mary Wanjiku', case_suffix='-peer'),
        ]
        payload = tat_recognition_payload(
            self.user, period='2026-09', include_people=True, view='people',
        )
        self.assertEqual(payload['minimum_ranked_sample'], 1)
        self.assertEqual(payload['minimum_personal_best_sample'], MINIMUM_RANKED_SAMPLE)
        self.assertEqual(payload['standings']['total'], 2)
        self.assertEqual({row['rank'] for row in payload['standings']['rows']}, {1})
        self.assertTrue(all(row['ranked'] for row in payload['standings']['rows']))

    @patch('core.services.tat_reporting._metric_scope_q', return_value=Q())
    @patch('core.services.tat_reporting._stage_samples')
    def test_unassigned_it_override_counts_for_process_but_not_personal_ranking(self, stage_samples, _scope):
        stage_samples.return_value = [
            self._sample(person_roles='IT', case_suffix=f'-{sample_number}')
            for sample_number in range(20)
        ]

        payload = tat_recognition_payload(
            self.user, period='2026-09', include_people=True,
            role='BRO', product='standard', view='people',
        )

        self.assertIsNone(payload['personal_result'])
        self.assertEqual(payload['role_summary']['completed'], 20)
        self.assertEqual(payload['standings']['rows'], [])
        self.assertEqual(payload['methodology']['attribution_fallback'], 20)

    @patch('core.services.workflow_recognition.timezone.localdate', side_effect=lambda value=None: timezone.localtime(value).date() if value is not None else date(2026, 9, 29))
    @patch('core.services.tat_reporting._stage_samples')
    def test_people_use_month_actions_but_branches_require_created_and_resolved_cohort(self, stage_samples, _today):
        self.user.is_superuser = True
        self.user.save(update_fields=['is_superuser'])
        def case(reference, created, finished, branch):
            row = TatTrackerCase.objects.create(
                group_id='-100tat', case_id=reference, product_key='standard',
                client_name='Synthetic case', branch=branch, status='Disbursed',
                stage_values={'disbursement': finished.isoformat()},
            )
            TatTrackerCase.objects.filter(pk=row.pk).update(created_at=created)
            return row

        case('same-month', timezone.make_aware(datetime(2026, 9, 1)), timezone.make_aware(datetime(2026, 9, 20)), 'Embu')
        case('cross-month', timezone.make_aware(datetime(2026, 8, 30)), timezone.make_aware(datetime(2026, 9, 5)), 'Nakuru')

        def samples(cases, filters, **_kwargs):
            result = []
            for item in cases:
                result.append(self._sample(branch=item.branch, case_suffix=item.case_id) | {
                    'case_id': item.case_id, 'completed_at': '2026-09-15T12:00:00+03:00',
                })
                if item.case_id == 'same-month':
                    result.append(self._sample(role='CA', branch=item.branch, product='HOCC',
                                               case_suffix=f'{item.case_id}-ca') | {
                        'case_id': item.case_id, 'completed_at': '2026-09-16T12:00:00+03:00',
                    })
            return result

        stage_samples.side_effect = samples
        payload = tat_recognition_payload(self.user, group_id='-100tat', period='2026-09', view='branches')
        self.assertEqual(payload['overall_result']['completed'], 3)
        self.assertEqual([row['branch'] for row in payload['standings']['rows']], ['Embu'])
        self.assertEqual(payload['standings']['rows'][0]['completed'], 2)
        self.assertEqual(payload['standings']['rows'][0]['role_count'], 2)
        self.assertEqual(payload['standings']['rows'][0]['product_count'], 2)
        self.assertEqual(payload['standings']['rows'][0]['rank'], 1)
        self.assertEqual(payload['standings']['rows'][0]['within_target'], 2)
        self.assertEqual(payload['standings']['rows'][0]['near_target'], 0)
        self.assertEqual(payload['standings']['rows'][0]['over_target'], 0)

    @patch('core.services.tat_reporting._stage_samples')
    def test_first_post_window_view_freezes_final_period(self, stage_samples):
        from tat_recognition.models import TatRecognitionPeriodSnapshot

        self.user.is_superuser = True
        self.user.save(update_fields=['is_superuser'])
        stage_samples.return_value = [self._sample(case_suffix=f'-{index}') for index in range(20)]
        first = tat_recognition_payload(self.user, group_id='-100tat', period='2025-01')
        self.assertEqual(first['result_status'], 'final')
        self.assertEqual(first['overall_result']['completed'], 20)
        self.assertEqual(TatRecognitionPeriodSnapshot.objects.count(), 1)
        frozen = TatRecognitionPeriodSnapshot.objects.get()
        with self.assertRaisesMessage(ValueError, 'cannot be changed'):
            frozen.save(update_fields=['facts'])

        self.user.is_superuser = False
        self.user.save(update_fields=['is_superuser'])
        AccessGrant.objects.create(
            user=self.user, workflow='tat_tracker', role='BRO', branch='Embu', product='standard',
        )

        stage_samples.return_value = []
        second = tat_recognition_payload(self.user, group_id='-100tat', period='2025-01')
        self.assertEqual(second['overall_result'], first['overall_result'])
        self.assertEqual(second['captured_at'], first['captured_at'])
        self.assertEqual(TatRecognitionPeriodSnapshot.objects.count(), 1)

    @patch('core.services.tat_reporting._stage_samples', return_value=[])
    def test_settlement_window_ends_after_thirty_full_days(self, _stage_samples):
        from tat_recognition.models import TatRecognitionPeriodSnapshot

        self.user.is_superuser = True
        self.user.save(update_fields=['is_superuser'])
        with patch('core.services.workflow_recognition.timezone.localdate', return_value=date(2026, 10, 30)):
            live = tat_recognition_payload(self.user, group_id='-100tat', period='2026-09')
        self.assertEqual(live['result_status'], 'live_provisional')
        self.assertFalse(TatRecognitionPeriodSnapshot.objects.exists())
        with patch('core.services.workflow_recognition.timezone.localdate', return_value=date(2026, 10, 31)):
            final = tat_recognition_payload(self.user, group_id='-100tat', period='2026-09')
        self.assertEqual(final['result_status'], 'final')
        self.assertTrue(TatRecognitionPeriodSnapshot.objects.exists())


@skipUnless(connection.vendor == 'postgresql', 'Concurrent snapshot capture requires PostgreSQL.')
class TatRecognitionConcurrentSnapshotTests(TransactionTestCase):
    def test_two_first_views_capture_one_final_snapshot(self):
        from tat_recognition.models import TatRecognitionPeriodSnapshot

        actor = get_user_model().objects.create_user(
            username='recognition-concurrent-superuser', is_active=True, is_superuser=True,
        )
        barrier = Barrier(2)

        def samples(*_args, **_kwargs):
            barrier.wait(timeout=15)
            return []

        def load():
            close_old_connections()
            try:
                return tat_recognition_payload(actor, group_id='-100tat', period='2025-01')
            finally:
                close_old_connections()

        with patch('core.services.tat_reporting._stage_samples', side_effect=samples):
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [pool.submit(load) for _ in range(2)]
                results = [future.result(timeout=30) for future in futures]
        self.assertEqual(TatRecognitionPeriodSnapshot.objects.count(), 1)
        self.assertEqual(results[0]['captured_at'], results[1]['captured_at'])
