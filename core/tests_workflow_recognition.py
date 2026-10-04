from datetime import date, datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.db.models import Q
from django.test import SimpleTestCase, TestCase, TransactionTestCase
from django.utils import timezone

from core.models import (
    AccessGrant,
    DocumentPhysicalSignoff,
    JawabuFarmerMaster,
    JawabuPipelineEvent,
    RequisitionBatch,
    TatTrackerCase,
)
from hb_operations.models import HomeBiogasAction, HomeBiogasActionEvent
from core.services.workflow_recognition import (
    MINIMUM_RANKED_SAMPLE,
    ON_TIME_SLA_STATES,
    _accumulate_tat_sample,
    _empty_tat_counts,
    _score_rows,
    _recognition_period,
    _apply_live_rank_movement,
    portal_performance_payload,
    tat_recognition_payload,
)
from core.services.portal_recognition import _aggregate as portal_aggregate, _event_milestone as portal_event_milestone, portal_recognition_payload


class TatRecognitionMovementTests(TestCase):
    def setUp(self):
        self.viewer = get_user_model().objects.create_user(
            username='recognition-movement-viewer', is_superuser=True, is_active=True,
        )
        self.options = dict(
            group_id='movement-group', scope_key='production', period_kind='month',
            period_key='2026-09', view='people', role='', product='', branch='',
        )

    def apply(self, rows, at, **overrides):
        records = [dict(item) for item in rows]
        _apply_live_rank_movement(self.viewer, rows=records, observed_at=at,
                                  **{**self.options, **overrides})
        return {row['key']: row['movement'] for row in records}

    def test_live_rank_movement_survives_reopen_and_unchanged_refresh(self):
        first = [
            {'key': 'a', 'rank': 1, 'score': 80, 'completed': 2, 'on_time_rate': 100},
            {'key': 'b', 'rank': 2, 'score': 70, 'completed': 2, 'on_time_rate': 90},
        ]
        start = timezone.now()
        self.assertEqual(self.apply(first, start)['a']['direction'], 'none')
        changed = [dict(first[0], rank=2), dict(first[1], rank=1, score=82)]
        result = self.apply(changed, start + timedelta(seconds=1))
        self.assertEqual(result['a'], {'direction': 'down', 'places': 1})
        self.assertEqual(result['b'], {'direction': 'up', 'places': 1})
        self.assertEqual(self.apply(changed, start + timedelta(seconds=2)), result)

    def test_ties_new_entries_and_filter_scope(self):
        start = timezone.now()
        first = [{'key': 'a', 'rank': 1, 'score': 80, 'completed': 2, 'on_time_rate': 100}]
        self.apply(first, start)
        tied = [dict(first[0]), {'key': 'b', 'rank': 1, 'score': 80, 'completed': 2, 'on_time_rate': 100}]
        result = self.apply(tied, start + timedelta(seconds=1))
        self.assertEqual(result['a']['direction'], 'same')
        self.assertEqual(result['b']['direction'], 'new')
        filtered = self.apply(tied, start + timedelta(seconds=2), role='BRO')
        self.assertEqual(filtered['a']['direction'], 'none')
        self.assertEqual(filtered['b']['direction'], 'none')

    def test_stale_request_cannot_replace_newer_rank(self):
        from tat_recognition.models import TatRecognitionLiveStanding

        start = timezone.now()
        original = [{'key': 'a', 'rank': 1, 'score': 80, 'completed': 2, 'on_time_rate': 100}]
        changed = [dict(original[0], rank=2, score=60)]
        self.apply(original, start)
        self.apply(changed, start + timedelta(seconds=2))
        self.apply(original, start + timedelta(seconds=1))
        self.assertEqual(TatRecognitionLiveStanding.objects.get().ranks['a'], 2)

    def test_expired_checkpoints_are_cleaned_on_demand(self):
        from tat_recognition.models import TatRecognitionLiveStanding

        start = timezone.now()
        self.apply([], start)
        TatRecognitionLiveStanding.objects.update(expires_at=start - timedelta(days=1))
        self.apply([], start + timedelta(seconds=1), branch='Nakuru')
        self.assertEqual(TatRecognitionLiveStanding.objects.count(), 1)


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


class PortalPerformanceRedesignTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='portal-performance-owner', is_active=True, is_superuser=True,
        )
        AccessGrant.objects.create(user=self.user, workflow='jawabu_portal', role='JBL_OFFICER', active=True)

    def fact(self, index, *, branch='Embu', stage='jbl_visit_completed'):
        return {
            'case_id': str(index), 'person_id': str(self.user.pk),
            'person': 'Portal Officer', 'stage': stage, 'branch': branch, 'product': 'HB',
        }

    def test_hb_events_use_event_type_not_the_foreign_key_named_action(self):
        from types import SimpleNamespace
        parent = SimpleNamespace(pk='action-id')
        self.assertEqual(portal_event_milestone(SimpleNamespace(
            action=parent, event_type='order.released_to_hb', new_values={},
        )), 'order.released_to_hb')
        self.assertEqual(portal_event_milestone(SimpleNamespace(
            action=parent, event_type='installation.progressed',
            new_values={'installation_status': 'installed'},
        )), 'installation_completed')
        self.assertEqual(portal_event_milestone(SimpleNamespace(
            action=parent, event_type='commissioning.completed',
            new_values={'commissioning_status': 'commissioned'},
        )), 'commissioning_completed')

    def test_one_person_across_branches_is_one_row_and_points_are_additive(self):
        facts = [self.fact(index, branch='Embu' if index % 2 else 'Nakuru') for index in range(1, 21)]
        facts += [self.fact(index, stage='credit_decision_recorded') for index in range(1, 6)]
        people = portal_aggregate(facts, key_name='person')
        branches = portal_aggregate(facts, key_name='branch')
        self.assertEqual(len(people), 1)
        self.assertEqual((people[0]['points'], people[0]['cases'], people[0]['visits']), (25, 20, 20))
        self.assertEqual(sum(row['points'] for row in branches), 25)

    def test_empty_period_has_no_score_or_named_rows_when_restricted(self):
        result = portal_recognition_payload(self.user, period='2026-09', include_people=False)
        self.assertEqual(result['view'], 'branches')
        self.assertIsNone(result['personal'])
        self.assertEqual(result['rows'], [])
        self.assertEqual(result['pages'], 1)

    def test_rejected_audited_visit_counts_once_and_approved_credit_adds_a_point(self):
        farmer = JawabuFarmerMaster.objects.create(customer_name='Portal result', branch='Embu')
        for day in (4, 5):
            JawabuPipelineEvent.objects.create(
                farmer=farmer, action='jbl_visit_completed', stage_key='jbl_visit',
                actor='Portal Officer', actor_user=self.user,
                occurred_at=timezone.make_aware(datetime(2026, 9, day, 10)),
                new_values={'status': 'Rejected by JBL'},
            )
        JawabuPipelineEvent.objects.create(
            farmer=farmer, action='credit_decision_recorded', stage_key='credit',
            actor='Analyst', actor_user=self.user,
            occurred_at=timezone.make_aware(datetime(2026, 9, 7, 10)),
            new_values={'decision': 'Approved'},
        )
        result = portal_recognition_payload(self.user, period='2026-09', include_people=True)
        self.assertEqual(result['personal']['points'], 2)
        self.assertEqual(result['personal']['visits'], 1)
        JawabuPipelineEvent.objects.create(
            farmer=farmer, action='returned_for_rework', stage_key='credit',
            actor='Reviewer', actor_user=self.user,
            occurred_at=timezone.make_aware(datetime(2026, 9, 8, 10)),
        )
        corrected = portal_recognition_payload(self.user, period='2026-09', include_people=True)
        self.assertEqual(corrected['personal']['points'], 1)
        JawabuPipelineEvent.objects.create(
            farmer=farmer, action='returned_for_rework', stage_key='jbl_visit',
            actor='Reviewer', actor_user=self.user,
            occurred_at=timezone.make_aware(datetime(2026, 9, 9, 10)),
        )
        self.assertEqual(portal_recognition_payload(
            self.user, period='2026-09', include_people=True,
        )['personal']['points'], 1)

    def test_each_milestone_belongs_to_its_own_month(self):
        farmer = JawabuFarmerMaster.objects.create(customer_name='Cross-month result', branch='Embu')
        JawabuPipelineEvent.objects.create(
            farmer=farmer, action='jbl_visit_completed', stage_key='jbl_visit',
            actor='Portal Officer', actor_user=self.user,
            occurred_at=timezone.make_aware(datetime(2026, 8, 29, 10)),
        )
        JawabuPipelineEvent.objects.create(
            farmer=farmer, action='credit_decision_recorded', stage_key='credit',
            actor='Analyst', actor_user=self.user,
            occurred_at=timezone.make_aware(datetime(2026, 9, 2, 10)),
            new_values={'decision': 'Exemption Approved'},
        )
        august = portal_recognition_payload(self.user, period='2026-08', include_people=True)
        september = portal_recognition_payload(self.user, period='2026-09', include_people=True)
        self.assertEqual(august['personal']['points'], 1)
        self.assertEqual(september['personal']['points'], 1)
        self.assertEqual(september['personal']['visits'], 0)

    def test_technical_visit_does_not_steal_officer_case_credit(self):
        technician = get_user_model().objects.create_user(username='technical-visitor', is_active=True)
        farmer = JawabuFarmerMaster.objects.create(customer_name='Officer-owned case', branch='Embu')
        for day, actor in ((1, technician), (2, self.user)):
            JawabuPipelineEvent.objects.create(
                farmer=farmer, action='jbl_visit_completed', stage_key='jbl_visit',
                actor=actor.get_username(), actor_user=actor,
                occurred_at=timezone.make_aware(datetime(2026, 9, day, 10)),
            )
        result = portal_recognition_payload(self.user, period='2026-09', include_people=True)
        self.assertEqual(result['personal']['points'], 1)
        self.assertEqual(result['rows'][0]['label'], self.user.get_username())

    def test_signed_order_installation_and_commissioning_add_case_points(self):
        farmer = JawabuFarmerMaster.objects.create(customer_name='Installed case', branch='Embu')
        JawabuPipelineEvent.objects.create(
            farmer=farmer, action='jbl_visit_completed', stage_key='jbl_visit',
            actor='Officer', actor_user=self.user,
            occurred_at=timezone.make_aware(datetime(2026, 9, 1, 10)),
        )
        batch = RequisitionBatch.objects.create(
            order_number='1801', version=1, farmer_ids=[str(farmer.pk)], farmer_count=1,
            filename='order.xlsx', file_content=b'workbook',
        )
        signoff = DocumentPhysicalSignoff.objects.create(
            document_type='requisition', requisition_batch=batch, source_version=1,
            source_filename='order.xlsx', source_content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            source_checksum='a' * 64, source_file_content=b'workbook',
            scan_filename='signed.pdf', scan_content_type='application/pdf',
            scan_size=4, scan_checksum='b' * 64, scan_file_content=b'scan',
            status=DocumentPhysicalSignoff.STATUS_SIGNED_APPROVED, attested_complete=True,
            uploaded_by=self.user, approved_by=self.user,
        )
        action = HomeBiogasAction.objects.create(
            farmer=farmer, source_requisition_batch=batch, source_signoff=signoff,
            source_order_number='1801', source_requisition_version=1,
        )
        for day, event_type, values in (
            (2, 'order.released_to_hb', {}),
            (3, 'installation.progressed', {'installation_status': 'installed'}),
            (4, 'commissioning.completed', {'commissioning_status': 'commissioned'}),
        ):
            event = HomeBiogasActionEvent.objects.create(
                action=action, event_type=event_type, revision=day, new_values=values,
            )
            HomeBiogasActionEvent.objects.filter(pk=event.pk).update(
                created_at=timezone.make_aware(datetime(2026, 9, day, 10)),
            )
        result = portal_recognition_payload(self.user, period='2026-09', include_people=True)
        self.assertEqual(result['personal']['points'], 4)
        self.assertEqual(result['personal']['milestones'][-1]['count'], 1)

    def test_settled_snapshot_does_not_rewrite_after_later_rework(self):
        from portal_recognition.models import PortalRecognitionPeriodSnapshot
        farmer = JawabuFarmerMaster.objects.create(customer_name='Settled result', branch='Embu')
        JawabuPipelineEvent.objects.create(
            farmer=farmer, action='jbl_visit_completed', stage_key='jbl_visit',
            actor='Portal Officer', actor_user=self.user,
            occurred_at=timezone.make_aware(datetime(2020, 8, 5, 10)),
        )
        first = portal_recognition_payload(self.user, period='2020-08', include_people=True)
        self.assertTrue(first['final'])
        self.assertEqual(first['personal']['points'], 1)
        self.assertEqual(first['score_policy_version'], 2)
        self.assertEqual(PortalRecognitionPeriodSnapshot.objects.count(), 1)
        JawabuPipelineEvent.objects.create(
            farmer=farmer, action='returned_for_rework', stage_key='jbl_visit',
            actor='Reviewer', actor_user=self.user,
            occurred_at=timezone.make_aware(datetime(2020, 8, 7, 10)),
        )
        second = portal_recognition_payload(self.user, period='2020-08', include_people=True)
        self.assertEqual(second['personal']['points'], 1)
        self.assertEqual(second['captured_at'], first['captured_at'])

    def test_portal_performance_grant_does_not_borrow_another_branch(self):
        viewer = get_user_model().objects.create_user(username='embu-performance-viewer', is_active=True)
        AccessGrant.objects.create(user=viewer, workflow='jawabu_portal', role='BUSINESS_ADMIN',
                                   branch='EMBU', active=True)
        AccessGrant.objects.create(user=viewer, workflow='jawabu_portal', role='JBL_OFFICER',
                                   branch='EMBU', active=True)
        for branch in ('EMBU', 'NAKURU'):
            farmer = JawabuFarmerMaster.objects.create(customer_name=f'{branch} case', branch=branch)
            JawabuPipelineEvent.objects.create(
                farmer=farmer, action='jbl_visit_completed', stage_key='jbl_visit',
                actor='Viewer', actor_user=viewer,
                occurred_at=timezone.make_aware(datetime(2026, 9, 6, 10)),
            )
        result = portal_recognition_payload(viewer, period='2026-09', include_people=True)
        self.assertEqual(result['personal']['points'], 1)
        self.assertEqual(result['filter_options']['branches'], ['EMBU'])


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
    def test_live_people_payload_persists_rank_direction_without_exposing_keys(self, stage_samples, _scope):
        mine = self._sample(case_suffix='-mine')
        other = self._sample(person_user_id=888, person='Other Staff',
                             sla_state='overdue', case_suffix='-other')
        stage_samples.return_value = [mine, other]
        options = dict(period='2026-09', group_id='-100tat', include_people=True, view='people')
        first = tat_recognition_payload(self.user, **options)
        self.assertEqual(first['standings']['rows'][0]['movement']['direction'], 'none')
        stage_samples.return_value = [
            {**mine, 'sla_state': 'overdue'},
            {**other, 'sla_state': 'within_target'},
        ]
        changed = tat_recognition_payload(self.user, **options)
        by_name = {row['label']: row for row in changed['standings']['rows']}
        self.assertEqual(by_name['You']['movement'], {'direction': 'down', 'places': 1})
        self.assertEqual(by_name['Other Staff']['movement'], {'direction': 'up', 'places': 1})
        self.assertNotIn('key', by_name['Other Staff'])
        self.assertEqual(tat_recognition_payload(self.user, **options)['standings']['rows'][0]['movement'],
                         {'direction': 'up', 'places': 1})

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
        self.assertEqual(payload['overall_stage_highlights'], [])
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
        self.assertEqual(payload['overall_stage_highlights'], unfiltered['overall_stage_highlights'])
        self.assertEqual(len(payload['overall_stage_highlights']), 2)
        self.assertEqual({item['completed'] for item in payload['overall_stage_highlights']}, {19, 20})
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
