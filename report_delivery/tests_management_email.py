"""Synthetic decision-first email facts, interpretation and disclosure boundaries."""
import base64
from copy import deepcopy
from unittest.mock import patch

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

    def test_counts_target_and_plain_sample_wording(self):
        context = email_context(self.snapshot())
        resolution = next(item for item in context['headline'] if item['label'] == 'Median resolution')
        self.assertEqual(resolution['value'], '6.9 days')
        self.assertIn('Target 3.0 days', context['eligibility_note'])
        self.assertEqual(resolution['note'], '')
        self.assertEqual(context['period'], '5 Oct - 11 Oct 2026')
        self.assertEqual(context['previous_period'], '28 Sep - 4 Oct 2026')

    def test_zero_rate_is_worse_lower_duration_is_better_volume_is_neutral(self):
        snapshot = self.snapshot()
        context = email_context(snapshot)
        metric = next(item for item in context['headline'] if item['label'] == 'Resolved on time')
        self.assertEqual(metric['ink'], '#b42318')
        self.assertEqual(metric['previous'], '50%')
        self.assertEqual(metric['change'], '▼ 50 pts lower')
        self.assertEqual(metric['status'], 'Worse')
        snapshot['comparison']['metrics']['Median resolution (hours)']['paired_values'] = {'current': 24, 'previous': 48}
        context = email_context(snapshot)
        self.assertEqual(next(item for item in context['metrics'] if item['label'] == 'Median resolution')['status'], 'Better')
        self.assertEqual(context['headline'][0]['status'], 'Change')

    def test_email_has_no_app_links_intro_or_sample_jargon(self):
        snapshot = self.snapshot()
        snapshot['applied_filters'].update(search='private customer text', init_data='private-auth', token='secret')
        context = email_context(snapshot)
        self.assertIn('3 of 3 complaints resolved late (100%)', context['attention'][0]['text'])
        self.assertEqual(context['report_url'], '')
        payload = build_payload(snapshot, 'management@example.invalid', {})
        for content in (payload['html'], payload['text']):
            for forbidden in ('Open in app', 'View in app', 'local-app.example.invalid', 'n=3', 'low volume', '3 complaints resolved;'):
                self.assertNotIn(forbidden, content)
        self.assertNotIn('<a ', payload['html'])

    def test_complementary_charts_top_five_and_no_empty_age_tables(self):
        snapshot = self.snapshot('cmp_tat')
        before = deepcopy(snapshot)
        payload = build_payload(snapshot, 'management@example.invalid', {})
        self.assertEqual(len([a for a in payload['attachments'] if a.get('content_id', '').startswith('jawabu-report-chart')]), 1)
        self.assertNotIn('Open-case age', payload['html'])
        self.assertNotIn('Resolution targets</h2>', payload['html'])
        self.assertIn('3 of 3 complaints resolved late (100%)', payload['html'])
        self.assertIn('max-width:900px', payload['html'])
        self.assertLess(payload['html'].index('Needs attention'), payload['html'].index('Resolution time</h2>'))
        self.assertLess(payload['html'].index('attached Excel'), payload['html'].index('Needs attention'))
        self.assertEqual(snapshot, before)
        self.assertEqual(payload['attachments'][0]['content'], before['xlsx_content'])

    def test_single_case_type_suppresses_median_and_mixed_targets_are_honest(self):
        snapshot = self.snapshot('cmp_tat')
        snapshot['management']['targets_hours'] = ['24', '72']
        section = next(section for section in snapshot['email_sections'] if section['title'] == 'Slowest complaint types')
        section['datasets'][1]['values'] = [1]
        context = email_context(snapshot)
        self.assertEqual(context['top_table']['display_headers'], ['Cases'])
        self.assertIn('Too few to rate', context['top_table']['context'])
        self.assertIn('Targets vary: 1.0 days - 3.0 days', context['eligibility_note'])
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
        self.assertIn('Matched window', context['headline'][0]['comparison_line'])
        self.assertIn('10 Oct 2026', context['notices'][-1])

    def test_positive_short_duration_never_rounds_to_a_false_zero(self):
        from .management_email import duration
        self.assertEqual(duration('Median resolution (hours)', 1), '1.0 hours')
        self.assertEqual(duration('Median resolution (hours)', 2), '2.0 hours')
        self.assertEqual(duration('Median TAT (minutes)', 1), 'Under 1 hour')
        self.assertEqual(duration('Median resolution (hours)', 0), '0 hours')

    def cohort_snapshot(self, cases):
        filters = {'date_from': '2026-10-01', 'date_to': '2026-10-31'}
        with patch('core.services.complaint_register._apply_report_filters', return_value=object()), \
                patch('report_delivery.complaint_reports.timed_cases', return_value=iter(cases)):
            projection = complaint_email_projection(object(), filters, now=stamp('2026-11-02T12:00'))
        return {**projection, 'preset': 'complaints', 'period': {'from': '2026-10-01', 'to': '2026-10-31'},
                'applied_filters': filters, 'run_at': '2026-11-02T12:00:00+03:00',
                'rows': [], 'total_rows': 6, 'xlsx_content': base64.b64encode(b'synthetic').decode()}

    def test_summary_reconciles_new_complaints_older_resolutions_and_current_backlog(self):
        cases = [synthetic_case(i, reported='2026-10-05T09:00',
                                resolved='2026-10-11T09:00' if i < 2 else None) for i in range(6)]
        cases += [synthetic_case(10+i, reported='2026-09-05T09:00',
                                 resolved='2026-10-11T09:00' if i < 3 else None) for i in range(4)]
        snapshot = self.cohort_snapshot(cases)
        self.assertEqual(snapshot['management']['reported_resolved'], 2)
        self.assertEqual(snapshot['management']['older_resolved'], 3)
        summary = email_context(snapshot)['summary_sentence']
        self.assertIn('6 new complaints were reported', summary)
        self.assertIn('2 of these were resolved', summary)
        self.assertIn('3 older complaints', summary)
        self.assertIn('5 complaints remain open overall', summary)

    def test_same_period_closure_is_distinct_and_current_reopening_is_explicit(self):
        case = synthetic_case(1, reported='2026-10-05T09:00', resolved='2026-10-11T09:00')
        case.complaint_timing['closures'].append(stamp('2026-10-12T09:00'))
        case.complaint_status = 'Reopened'
        case.complaint_timing['reopened'] = [stamp('2026-10-13T09:00')]
        snapshot = self.cohort_snapshot([case])
        self.assertEqual(snapshot['management']['reported_resolved'], 1)
        self.assertEqual(snapshot['management']['resolved_now_reopened'], 1)
        self.assertEqual(snapshot['management']['open'], 1)
        self.assertIn('has since reopened', email_context(snapshot)['summary_sentence'])

    def test_following_month_resolution_is_not_attributed_to_reporting_month(self):
        snapshot = self.cohort_snapshot([synthetic_case(1, reported='2026-10-31T23:59', resolved='2026-11-01T00:00')])
        self.assertEqual(snapshot['management']['reported_resolved'], 0)
        self.assertEqual(snapshot['management']['resolved'], 0)

    def test_summary_pairs_activity_with_doughnut_not_attention(self):
        context = email_context(self.snapshot())
        self.assertEqual([chart['title'] for chart in context['graph_sections']], ['Reported vs resolved', 'On-time vs late'])
        self.assertEqual([chart['definition']['type'] for chart in context['graph_sections']], ['line', 'doughnut'])
        self.assertEqual(len(context['graph_pairs'][0]), 2)
        payload = build_payload(self.snapshot(), 'management@example.invalid', {})
        self.assertIn('class="attention-section"', payload['html'])
        attention = payload['html'].split('class="attention-section"', 1)[1].split('</table>', 1)[0]
        self.assertNotIn('class="report-graph"', attention)

    def test_unrestricted_subject_has_no_scope_suffix_and_timestamp_is_in_brand(self):
        snapshot = self.snapshot()
        snapshot['applied_filters'].pop('branch')
        payload = build_payload(snapshot, 'management@example.invalid', {})
        self.assertNotIn('All approved cases', payload['subject'])
        self.assertFalse(payload['subject'].endswith(' / '))
        brand = payload['html'].split('class="brand-name', 1)[1].split('</td>', 1)[0]
        self.assertIn('Data as of', brand)
        stamp = payload['html'].split('class="report-stamp"', 1)[1].split('</p>', 1)[0]
        self.assertNotIn('Data as of', stamp)
        self.assertNotIn('<br>', stamp)

    def test_doughnut_renders_semantic_colors_and_rejects_empty_totals(self):
        from io import BytesIO
        from PIL import Image
        from .email_charts import chart_png
        chart = {'type': 'doughnut', 'labels': ['On time', 'Late'], 'unit': 'complaints',
                 'datasets': [{'label': 'Complaints', 'values': [3, 2]}], 'colors': ['#168354', '#d14343']}
        png = chart_png(chart)
        self.assertIsNotNone(png)
        colors = Image.open(BytesIO(png)).convert('RGB').getcolors(840 * 440)
        self.assertTrue(any(color == (22, 131, 84) for _, color in colors))
        self.assertTrue(any(color == (209, 67, 67) for _, color in colors))
        chart['datasets'][0]['values'] = [0, 0]
        self.assertIsNone(chart_png(chart))

    def test_reconciled_counts_cover_period_edges_unknown_dates_and_missing_targets(self):
        cases = [synthetic_case(1, reported='2026-10-01T00:00', resolved='2026-10-31T23:59', target=None),
                 synthetic_case(2, reported='2026-09-30T23:59', resolved='2026-10-01T00:00'),
                 synthetic_case(3, reported='2026-10-31T23:59', resolved='2026-11-01T00:00'),
                 synthetic_case(4, reported='2026-09-01T09:00', resolved='2026-10-05T09:00')]
        cases[3].complaint_timing['reported_at'] = None
        snapshot = self.cohort_snapshot(cases)
        facts = snapshot['management']
        self.assertEqual((facts['reported_resolved'], facts['older_resolved'], facts['other_resolved']), (1, 1, 1))
        self.assertEqual(sum(facts[key] for key in ('reported_resolved', 'older_resolved', 'other_resolved')), facts['resolved'])
        self.assertIn('1 other complaint', email_context(snapshot)['summary_sentence'])

    def test_historical_snapshot_does_not_invent_same_period_intersection(self):
        snapshot = self.snapshot()
        for key in ('reported_resolved', 'older_resolved', 'other_resolved', 'resolved_now_reopened'):
            snapshot['management'].pop(key, None)
        summary = email_context(snapshot)['summary_sentence']
        self.assertNotIn('of these were resolved', summary)
        self.assertIn('this total can include older complaints', summary)

    def test_chart_axes_are_distinct_from_grid_and_units_remain_explicit(self):
        from io import BytesIO
        from PIL import Image
        from .email_charts import AXIS, GRID, chart_png
        for kind in ('bar', 'line'):
            chart = {'type': kind, 'temporal': kind == 'line', 'unit': 'complaints',
                     'labels': ['1 Oct', '2 Oct'], 'datasets': [{'label': 'Reported', 'values': [0, 3]}]}
            png = chart_png(chart)
            colors = dict((color, count) for count, color in Image.open(BytesIO(png)).convert('RGB').getcolors(840 * 440))
            from PIL import ImageColor
            self.assertGreater(colors.get(ImageColor.getrgb(AXIS), 0), 1500)
            self.assertGreater(colors.get(ImageColor.getrgb(GRID), 0), 500)

    def test_compositions_single_category_invalid_and_missing_values(self):
        from .email_charts import chart_png
        chart = {'type': 'doughnut', 'unit': 'complaints', 'labels': ['On time', 'Late'],
                 'datasets': [{'label': 'Complaints', 'values': [3, 0]}]}
        self.assertIsNotNone(chart_png(chart))
        for values in ([0, 0], [-1, 2], [None, 2], ['NaN', 2]):
            chart['datasets'][0]['values'] = values
            self.assertIsNone(chart_png(chart))

    def test_empty_target_and_zero_duration_have_honest_displays(self):
        snapshot = self.cohort_snapshot([])
        payload = build_payload(snapshot, 'management@example.invalid', {})
        self.assertIn('No resolved complaints with a recorded target.', payload['html'])
        self.assertNotIn('NaN', payload['html'])
        snapshot = self.snapshot('cmp_tat')
        chart = snapshot['email_sections'][0]
        chart['datasets'][0]['values'] = [0] * len(chart['labels'])
        context = email_context(snapshot)
        self.assertFalse(context['graph_sections'][0].get('empty_message'))
