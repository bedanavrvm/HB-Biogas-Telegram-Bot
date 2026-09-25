from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.core.exceptions import ValidationError

from core.models import WorkflowRoleCapability
from core.services.tat_presentation import REPORT_PANEL_ORDER, validate_report_panel_order
from core.services.tat_reporting import _heatmap_dimension_labels, _stage_columns_for_rows
from core.services.access_control import create_capability_request
from core.services.workflow_capabilities import (
    default_enabled_capability_keys, dependency_closure, effective_capability_keys,
)


class TatReportPresentationPolicyTests(SimpleTestCase):
    def test_stage_labels_follow_loan_cycle_not_alphabetical_or_frequency(self):
        rows = [
            {'current_stage': 'Credit', 'current_stage_key': 'credit', '_stage_columns': [
                {'key': 'intake', 'label': 'Intake', 'order': 0},
                {'key': 'visit', 'label': 'Visit', 'order': 1},
                {'key': 'credit', 'label': 'Credit', 'order': 2},
            ]},
            {'current_stage': 'Intake', 'current_stage_key': 'intake', '_stage_columns': [
                {'key': 'intake', 'label': 'Intake', 'order': 0},
                {'key': 'visit', 'label': 'Visit', 'order': 1},
                {'key': 'credit', 'label': 'Credit', 'order': 2},
            ]},
        ]
        self.assertEqual(
            _heatmap_dimension_labels(rows, 'stage', sample=False), ['Intake', 'Credit'],
        )
        self.assertEqual(
            [item['key'] for item in _stage_columns_for_rows(rows)],
            ['intake', 'visit', 'credit'],
        )

    def test_global_panel_order_requires_every_panel_once(self):
        self.assertEqual(validate_report_panel_order(list(reversed(REPORT_PANEL_ORDER))), list(reversed(REPORT_PANEL_ORDER)))
        for invalid in ([], list(REPORT_PANEL_ORDER[:-1]), [*REPORT_PANEL_ORDER[:-1], REPORT_PANEL_ORDER[0]]):
            with self.assertRaisesMessage(ValueError, 'exactly once'):
                validate_report_panel_order(invalid)

    def test_panel_grant_includes_whole_report_and_target_signals_defaults_to_it(self):
        self.assertIn('tat.reports.view', dependency_closure('tat_tracker', {'tat.reports.insight.heatmap'}))
        self.assertIn('tat.reports.insight.heatmap', default_enabled_capability_keys('tat_tracker', 'MANAGEMENT'))
        self.assertNotIn('tat.reports.insight.target_review_signals', default_enabled_capability_keys('tat_tracker', 'MANAGEMENT'))
        self.assertIn('tat.reports.insight.target_review_signals', default_enabled_capability_keys('tat_tracker', 'IT'))


class TatReportInsightAccessTests(TestCase):
    def test_non_it_cannot_gain_target_signals_from_a_stale_policy_row(self):
        user = get_user_model().objects.create_user(username='tat-report-insight-test')
        for key in ('tat.home.view', 'tat.reports.view', 'tat.reports.insight.heatmap',
                    'tat.reports.insight.target_review_signals'):
            WorkflowRoleCapability.objects.update_or_create(
                workflow='tat_tracker', role='MANAGEMENT', capability_key=key,
                defaults={'effect': 'allow', 'enabled': True},
            )
        enabled = effective_capability_keys(user, 'tat_tracker', access={'roles': ['MANAGEMENT']})
        self.assertIn('tat.reports.insight.heatmap', enabled)
        self.assertNotIn('tat.reports.insight.target_review_signals', enabled)

    def test_matrix_rejects_non_it_target_signal_grant(self):
        requester = get_user_model().objects.create_superuser(
            username='tat-report-policy-admin', email='admin@example.invalid', password='test-pass-1234',
        )
        with self.assertRaisesMessage(ValidationError, 'restricted to IT'):
            create_capability_request(
                requester=requester, workflow='tat_tracker', role='MANAGEMENT',
                capability_keys={'tat.reports.insight.target_review_signals'},
                reason='Restrict this insight to the technical team.',
            )
