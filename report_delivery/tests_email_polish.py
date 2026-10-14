"""Synthetic presentation regressions; no database or provider calls."""
from copy import deepcopy
from io import BytesIO
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from PIL import Image, ImageDraw

from .complaint_reports import complaint_email_projection
from .email_charts import chart_png
from .rendering import build_payload, email_context
from .tests_complaint_reports import stamp, synthetic_case


class EmailPolishTests(SimpleTestCase):
    def snapshot(self, cases, preset='complaints'):
        filters = {'date_from': '2026-10-05', 'date_to': '2026-10-11'}
        with patch('core.services.complaint_register._apply_report_filters', return_value=object()), patch(
            'report_delivery.complaint_reports.timed_cases', return_value=iter(cases)
        ):
            projection = complaint_email_projection(object(), filters, preset=preset, now=stamp('2026-10-12T12:00'))
        return {**projection, 'preset': preset, 'run_at': '2026-10-12T12:00:00+03:00',
                'total_rows': len(cases), 'rows': [], 'applied_filters': filters, 'xlsx_content': 'c3ludGhldGlj'}

    def test_daily_outlier_is_explained_without_changing_period_median(self):
        cases = [synthetic_case(i, reported='2026-10-05T09:00', resolved='2026-10-05T09:06', hours=.1) for i in range(4)]
        cases.append(synthetic_case(5, reported='2026-10-03T09:00', resolved='2026-10-11T09:00', hours=192, target=False))
        context = email_context(self.snapshot(cases, 'cmp_tat'))
        median = next(item for item in context['headline'] if item['label'] == 'Median resolution')
        self.assertEqual(median['value'], 'Under 1 hour')
        self.assertTrue(any('8.0 days' in item['text'] and '4 complaints resolved within 24 hours' in item['text'] for item in context['attention']))
        self.assertEqual(context['headline'][0]['label'], 'Resolved on time')
        self.assertIn('full period', context['graph_sections'][0]['context'])
        self.assertNotIn('overview_graph', context)

    def test_target_denominator_percent_and_absolute_colour(self):
        cases = [synthetic_case(i, resolved='2026-10-06T09:00', target=target)
                 for i, target in enumerate([True, True, False, None, None])]
        context = email_context(self.snapshot(cases))
        metric = next(item for item in context['headline'] if item['label'] == 'Resolved on time')
        self.assertEqual(metric['value'], '67%')
        self.assertEqual(metric['ink'], '#a36b08')
        self.assertIn('3 of 5', context['eligibility_note'])
        self.assertIn('2 without a target', context['eligibility_note'])
        self.assertNotIn('Based on', str(context['headline']))

    def test_each_report_has_distinct_panels_and_no_duplicate_images(self):
        cases = [synthetic_case(1, resolved='2026-10-06T09:00', response='2026-10-05T12:00'), synthetic_case(2)]
        for preset in ('complaints', 'cmp_tat', 'cmp_open'):
            with self.subTest(preset=preset):
                snapshot = self.snapshot(cases, preset)
                before = deepcopy(snapshot)
                payload = build_payload(snapshot, 'synthetic@example.invalid', {})
                context = email_context(snapshot)
                self.assertLessEqual(len(context['graph_sections']), 2)
                titles = [panel['title'] for panel in context['graph_sections'] + context['table_sections']]
                self.assertEqual(len(titles), len(set(titles)))
                attachments = [item for item in payload['attachments'] if item.get('content_id', '').startswith('jawabu-report-chart')]
                for item in attachments:
                    self.assertEqual(payload['html'].count('src="cid:' + item['content_id'] + '"'), 1)
                self.assertEqual(snapshot, before)
                self.assertNotIn('<a ', payload['html'])
                if preset == 'cmp_open':
                    self.assertEqual(payload['html'].count('>Open-case age</h2>'), 1)

    def test_all_small_types_have_one_note_instead_of_repeated_ratings(self):
        cases = [synthetic_case(i, resolved='2026-10-06T09:00', category=f'Type {i}') for i in range(3)]
        context = email_context(self.snapshot(cases, 'cmp_tat'))
        table = context['top_table']
        self.assertEqual(table['display_headers'], ['Cases'])
        self.assertIn('Too few to rate', table['context'])
        self.assertTrue(all(len(row['values']) == 1 for row in table['rows']))

    def test_chart_punctuation_and_bounds_and_daily_bars(self):
        chart = {'title': 'Open-case age', 'type': 'bar', 'labels': ['Under 3 days', '3–7 days', '8–14 days', 'Over 14 days'],
                 'datasets': [{'label': 'Complaints', 'values': [1, 2, 3, 4]}], 'unit': 'complaints'}
        with patch('report_delivery.email_charts._wrap', wraps=__import__('report_delivery.email_charts', fromlist=['_wrap'])._wrap) as wrap:
            image = Image.open(BytesIO(chart_png(chart)))
        self.assertEqual(image.size, (840, 440))
        self.assertTrue(any(call.args[1] == '3-7 days' for call in wrap.call_args_list))
        daily = {**chart, 'temporal': True, 'labels': [f'{i} Oct' for i in range(1, 32)],
                 'datasets': [{'label': 'Complaints', 'values': [0] * 15 + [1] + [0] * 15}]}
        self.assertIsNotNone(chart_png(daily))

    def test_missing_and_zero_comparisons_are_distinct(self):
        snapshot = self.snapshot([synthetic_case(1)])
        snapshot['comparison']['metrics'] = {}
        context = email_context(snapshot)
        self.assertTrue(all(item['comparison_line'] == 'No earlier data yet' for item in context['headline']))
        snapshot['comparison']['metrics']['Reported'] = {'paired_values': {'current': 6, 'previous': 0}}
        metric = email_context(snapshot)['headline'][0]
        self.assertIn('Was 0', metric['comparison_line'])
        self.assertIn('6 more', metric['comparison_line'])

    def test_missing_timing_is_not_misrepresented_as_a_missing_target(self):
        cases = [synthetic_case(i, resolved='2026-10-06T09:00', target=True) for i in range(5)]
        cases[3].complaint_timing['resolution_hours'] = None
        cases[4].complaint_status = 'Open'
        context = email_context(self.snapshot(cases))
        self.assertIn('3 of 5', context['eligibility_note'])
        self.assertIn('2 without usable resolution timing or no longer closed', context['eligibility_note'])
        self.assertNotIn('without a target', context['eligibility_note'])

    def test_absolute_rate_colour_is_separate_from_improvement(self):
        snapshot = self.snapshot([synthetic_case(1, resolved='2026-10-06T09:00', target=True)])
        snapshot['summary']['Resolved on time (%)'] = 67
        snapshot['comparison']['metrics']['Resolved on time (%)'] = {'paired_values': {'current': 67, 'previous': 50}}
        metric = next(item for item in email_context(snapshot)['headline'] if item['label'] == 'Resolved on time')
        self.assertEqual(metric['ink'], '#a36b08')
        self.assertEqual(metric['comparison_ink'], '#17643b')
        self.assertEqual(metric['status'], 'Better')

    def test_email_table_limits_do_not_drop_the_remaining_plaintext_figures(self):
        cases = [synthetic_case(i, reported='2026-10-05T09:00', category=f'Type {i}') for i in range(8)]
        snapshot = self.snapshot(cases)
        context = email_context(snapshot)
        table = context['top_table']
        self.assertEqual(len(table['rows_display']), 5)
        self.assertEqual(len(table['rows']), 6)
        payload = build_payload(snapshot, 'synthetic@example.invalid', {})
        self.assertIn('Other: Complaints 3', payload['text'])

    def test_failed_chart_is_not_paired_with_a_successful_chart(self):
        cases = [synthetic_case(1, resolved='2026-10-06T09:00', response='2026-10-05T12:00'), synthetic_case(2)]
        snapshot = self.snapshot(cases)
        from .email_charts import chart_png as real_chart_png
        def fail_one(chart):
            return None if chart['title'] == 'On-time vs late' else real_chart_png(chart)
        with patch('report_delivery.email_charts.chart_png', side_effect=fail_one), patch('report_delivery.rendering.render_to_string', wraps=__import__('django.template.loader', fromlist=['render_to_string']).render_to_string) as render:
            build_payload(snapshot, 'synthetic@example.invalid', {})
        context = render.call_args_list[0].args[1]
        self.assertEqual(len(context['fallback_sections']), 1)
        self.assertTrue(all(section.get('graph') for pair in context['graph_pairs'] for section in pair))

    def test_charts_do_not_draw_text_outside_the_image(self):
        original = ImageDraw.Draw
        for chart in [
            {'type': 'bar', 'unit': 'complaints', 'labels': ['Under 3 days', '3–7 days', '8–14 days', 'Over 14 days'],
             'datasets': [{'label': 'Complaints', 'values': [0, 2, None, 4]}]},
            {'type': 'line', 'unit': 'days', 'labels': ['5 October 2026', '6 October 2026', '7 October 2026'],
             'datasets': [{'label': 'Days', 'values': [.1, None, 8]}]},
        ]:
            drawings = []
            def record(image):
                draw = MagicMock(wraps=original(image))
                drawings.append((image, draw))
                return draw
            with patch('report_delivery.email_charts.ImageDraw.Draw', side_effect=record):
                self.assertIsNotNone(chart_png(chart))
            image, draw = drawings[-1]
            for call in draw.text.call_args_list:
                bounds = original(image).textbbox(call.args[0], call.args[1], font=call.kwargs['font'], anchor=call.kwargs.get('anchor'))
                self.assertGreaterEqual(min(bounds[:2]), 0)
                self.assertLessEqual(bounds[2], image.width)
                self.assertLessEqual(bounds[3], image.height)
