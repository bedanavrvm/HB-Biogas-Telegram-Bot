"""Synthetic decision-first email facts, interpretation and disclosure boundaries."""
import base64
from copy import deepcopy
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.test import SimpleTestCase, override_settings

from .complaint_reports import complaint_email_projection
from .rendering import build_payload, email_context
from .tests_complaint_reports import synthetic_case, stamp


@override_settings(APP_BASE_URL='https://local-app.example.invalid')
class ManagementEmailTests(SimpleTestCase):
    def snapshot(self, preset='complaints'):
        cases = [synthetic_case(i, reported='2026-10-05T09:00', resolved='2026-10-11T09:00', hours=166, target=False) for i in range(3)]
        cases += [synthetic_case(10+i, reported='2026-09-28T09:00', resolved='2026-10-04T09:00', hours=48, target=i < 2) for i in range(4)]
        for case in cases:
            case.complaint_control.sla_target_hours = 72
        filters = {'date_from': '2026-10-05', 'date_to': '2026-10-11', 'branch': 'Training', 'group_id': '-100000000'}
        with patch('core.services.complaint_register._apply_report_filters', return_value=object()), patch('report_delivery.complaint_reports.timed_cases', return_value=iter(cases)):
            projection = complaint_email_projection(object(), filters, preset=preset, now=stamp('2026-10-12T12:00'))
        return {**projection, 'preset': preset, 'period': {'from': '2026-10-05', 'to': '2026-10-11'},
                'applied_filters': filters, 'run_at': '2026-10-12T12:00:00+03:00',
                'rows': [], 'total_rows': 3, 'exported_rows': 3, 'xlsx_content': base64.b64encode(b'synthetic').decode()}

    def test_computed_verdict_previous_counts_target_and_low_volume(self):
        context = email_context(self.snapshot())
        self.assertIn('3 complaints resolved; 0 of 3', context['verdict'])
        self.assertIn('previously 2 of 4', context['verdict'])
        self.assertIn('6.9 days; target 3.0 days', context['verdict'])
        self.assertIn('n=3 · low volume', context['verdict'])
        self.assertEqual(context['period'], '5 Oct - 11 Oct 2026')
        self.assertEqual(context['previous_period'], '28 Sep - 4 Oct 2026')

    def test_zero_rate_is_worse_lower_duration_is_better_volume_is_neutral(self):
        snapshot = self.snapshot()
        context = email_context(snapshot)
        metric = next(item for item in context['headline'] if item['label'] == 'Resolved on time')
        self.assertEqual(metric['ink'], '#b42318')
        self.assertEqual(metric['previous'], '50.0%')
        self.assertEqual(metric['change'], '▼ 50.0 pts · Worse')
        snapshot['comparison']['metrics']['Median resolution (hours)']['paired_values'] = {'current': 24, 'previous': 48}
        context = email_context(snapshot)
        self.assertEqual(next(item for item in context['metrics'] if item['label'] == 'Median resolution')['status'], 'Better')
        self.assertEqual(context['headline'][0]['status'], 'Change')

    def test_attention_links_keep_scope_and_do_not_contain_identity_or_tokens(self):
        snapshot = self.snapshot()
        snapshot['applied_filters'].update(search='private customer text', init_data='private-auth', token='secret')
        context = email_context(snapshot)
        self.assertIn('3 of 3 measured resolutions late (100%)', context['attention'][0]['text'])
        params = parse_qs(urlsplit(context['attention'][0]['url']).query)
        self.assertEqual(params['metric'], ['late'])
        self.assertEqual(params['branch'], ['Training'])
        self.assertEqual(params['date_basis'], ['resolved'])
        self.assertNotIn('private', context['report_url'])
        self.assertNotIn('secret', context['report_url'])
        with override_settings(APP_BASE_URL='javascript:alert(1)'):
            self.assertEqual(email_context(snapshot)['report_url'], '')

    def test_only_one_chart_top_five_and_no_empty_bucket_tables(self):
        snapshot = self.snapshot('cmp_tat')
        before = deepcopy(snapshot)
        payload = build_payload(snapshot, 'management@example.invalid', {})
        self.assertEqual(len([a for a in payload['attachments'] if a.get('content_id', '').startswith('jawabu-report-chart')]), 1)
        self.assertNotIn('Open-case age', payload['html'])
        self.assertNotIn('Resolution targets</h2>', payload['html'])
        self.assertIn('3 of 3 measured resolutions late (100%)', payload['html'])
        self.assertIn('max-width:600px', payload['html'])
        self.assertLess(payload['html'].index('Needs attention'), payload['html'].index('Resolution time</h2>'))
        self.assertLess(payload['html'].index('attached Excel'), payload['html'].index('Needs attention'))
        self.assertEqual(snapshot, before)
        self.assertEqual(payload['attachments'][0]['content'], before['xlsx_content'])

    def test_single_case_type_suppresses_median_and_mixed_targets_are_honest(self):
        snapshot = self.snapshot('cmp_tat')
        snapshot['management']['targets_hours'] = ['24', '72']
        section = snapshot['email_sections'][-1]
        section['datasets'][1]['values'] = [1]
        context = email_context(snapshot)
        self.assertEqual(context['top_table']['rows'][0]['values'][0], 'n/a (low volume)')
        self.assertIn('Targets vary: 1.0 days - 3.0 days', context['headline'][0]['target'])
        self.assertFalse(any('Longest median' in item['text'] for item in context['attention']))

    def test_current_open_snapshot_has_no_invented_previous_value(self):
        context = email_context(self.snapshot('cmp_open'))
        self.assertTrue(all(item['previous'] == 'Not available' for item in context['headline']))
        self.assertEqual(context['period'], 'Current snapshot')
        self.assertEqual(context['previous_period'], '')

    def test_partial_comparison_does_not_compare_full_headline_with_shorter_previous_window(self):
        snapshot = self.snapshot()
        snapshot['management'].update(comparison_cutoff='2026-10-10T00:00:00+03:00',
                                      comparison_on_time=0, comparison_target_count=2)
        context = email_context(snapshot)
        self.assertIn('For equal elapsed time: 0 of 2 within target, previously 2 of 4', context['verdict'])
        self.assertNotIn('(previously', context['verdict'])
        self.assertIn('matching elapsed window', context['headline'][0]['comparison_scope'])

    def test_positive_short_duration_never_rounds_to_a_false_zero(self):
        from .management_email import duration
        self.assertEqual(duration('Median resolution (hours)', 1), '<0.1 days')
        self.assertEqual(duration('Median TAT (minutes)', 1), '<0.1 hours')
        self.assertEqual(duration('Median resolution (hours)', 0), '0.0 days')
