from django.test import SimpleTestCase

from core.services.workflow_recognition import MINIMUM_RANKED_SAMPLE, _score_rows


class WorkflowRecognitionScoreTests(SimpleTestCase):
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
            {'label': 'Team A', 'visits_completed': 10, 'credit_conversion': 90},
            {'label': 'Team B', 'visits_completed': 10, 'credit_conversion': 90},
        ], quality_key='credit_conversion', volume_key='visits_completed')

        self.assertEqual([row['rank'] for row in rows], [1, 1])
        self.assertEqual([row['score'] for row in rows], [94.0, 94.0])
