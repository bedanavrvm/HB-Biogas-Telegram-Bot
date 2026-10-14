"""Synthetic period, projection, scope and frozen-delivery regressions."""
import base64
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.test import SimpleTestCase, TestCase

from core.services.complaint_timing import NAIROBI
from .complaint_reports import comparison_window, complaint_email_projection, _history_windows, _delta
from .rendering import build_payload


def stamp(value):
    return datetime.fromisoformat(value).replace(tzinfo=NAIROBI)


def synthetic_case(index, reported='2026-09-10T09:00', resolved=None, *, hours=24, target=True,
                   branch='Training', category='Maintenance', age='over_14', response=None, reopened=()):
    end = stamp(resolved) if resolved else None
    return SimpleNamespace(pk=index, complaint_status='Closed' if end else 'Open',
        branch_region=branch, complaint_category=category,
        complaint_control=SimpleNamespace(category_id=None, branch_ref_id=None),
        complaint_timing={'reported_at': stamp(reported), 'resolved_at': end, 'closures': [end] if end else [],
            'reopened': list(reopened), 'response_at': stamp(response) if response else None,
            'resolution_hours': hours if end else None, 'hb_response_hours': 6 if response else None,
            'on_time': target if end else None, 'age_bucket': age, 'elapsed_seconds': 17 * 86400})


class PeriodTests(SimpleTestCase):
    def test_completed_calendar_periods_and_leap_year(self):
        for first, last, prior, prior_end in [
            ('2024-03-01', '2024-03-31', '2024-02-01', '2024-03-01'),
            ('2026-04-01', '2026-06-30', '2026-01-01', '2026-04-01'),
            ('2026-01-01', '2026-12-31', '2025-01-01', '2026-01-01'),
            ('2026-10-05', '2026-10-11', '2026-09-28', '2026-10-05'),
            ('2026-10-05', '2026-10-05', '2026-10-04', '2026-10-05'),
            ('2026-10-03', '2026-10-05', '2026-09-30', '2026-10-03'),
        ]:
            result = comparison_window({'date_from': first, 'date_to': last}, now=stamp('2027-02-01T00:00'))
            self.assertEqual(result[2].date().isoformat(), prior)
            self.assertEqual(result[3].date().isoformat(), prior_end)

    def test_partial_month_caps_common_elapsed_time(self):
        start, end, previous, prior_end, label = comparison_window(
            {'date_from': '2026-03-01', 'date_to': '2026-03-31'}, now=stamp('2026-03-30T12:00'))
        self.assertEqual(end - start, prior_end - previous)
        self.assertEqual(end, stamp('2026-03-29T00:00'))
        self.assertIn('equal elapsed', label)

    def test_explicit_custom_range_is_not_reinterpreted_as_calendar_month(self):
        result = comparison_window({'date_from': '2026-03-01', 'date_to': '2026-03-31', 'date_mode': 'custom'}, now=stamp('2026-04-02T00:00'))
        self.assertEqual(result[1] - result[0], result[3] - result[2])
        self.assertEqual(result[2], stamp('2026-01-29T00:00'))

    def test_nairobi_today_not_utc_today(self):
        result = comparison_window({}, now=datetime.fromisoformat('2026-03-31T22:00:00+00:00'))
        self.assertEqual(result[0], stamp('2026-04-01T00:00'))
        self.assertEqual(result[2], stamp('2026-03-31T00:00'))

    def test_future_period_has_no_inverted_date_range(self):
        result = comparison_window({'date_from': '2027-01-01', 'date_to': '2027-01-31'}, now=stamp('2026-10-12T12:00'))
        self.assertEqual(result[0], result[1])
        self.assertEqual(result[2], result[3])
        self.assertIn('has not started', result[4])

    def test_partial_year_keeps_all_months_without_technical_markers(self):
        windows, unit = _history_windows(stamp('2026-01-01T00:00'), stamp('2026-12-17T12:00'))
        self.assertEqual(len(windows), 12)
        self.assertEqual(unit, 'month')
        self.assertEqual(windows[-1][1], stamp('2026-12-17T12:00'))
        self.assertFalse(any('*' in window[2] for window in windows))

    def test_count_duration_percentage_and_missing_baselines(self):
        self.assertEqual(_delta('Reported', 7, 5), {'text': '+2 vs previous', 'tone': 'muted'})
        self.assertEqual(_delta('Resolved on time (%)', 75, 50)['text'], '+25 pp vs previous')
        self.assertEqual(_delta('Median resolution (hours)', 23, 49)['tone'], 'good')
        self.assertIn('1d 2h', _delta('Median resolution (hours)', 23, 49)['text'])
        self.assertEqual(_delta('Reported', 2, 0)['text'], 'No previous activity')
        self.assertEqual(_delta('Resolved on time (%)', 25, 0)['text'], '+25 pp vs previous')
        self.assertEqual(_delta('Median HB response (hours)', 1, 0)['text'], '+1h vs previous')
        self.assertEqual(_delta('Median HB response (hours)', None, 3)['text'], 'Comparison unavailable')


class ProjectionTests(SimpleTestCase):
    now = stamp('2026-10-12T12:00')
    filters = {'date_from': '2026-09-01', 'date_to': '2026-09-30'}

    def project(self, cases, preset='complaints', filters=None):
        with patch('core.services.complaint_register._apply_report_filters', return_value=object()), \
             patch('report_delivery.complaint_reports.timed_cases', return_value=iter(cases)):
            return complaint_email_projection(object(), filters or self.filters, preset=preset, now=self.now)

    def test_summary_separates_period_activity_from_older_backlog(self):
        cases = [synthetic_case(1, resolved='2026-09-11T09:00'),
                 synthetic_case(2, reported='2026-08-20T09:00'), synthetic_case(3)]
        result = self.project(cases)
        self.assertEqual(result['summary']['Reported'], 2)
        self.assertEqual(result['summary']['Resolved in period'], 1)
        self.assertEqual(result['summary']['Open now'], 2)
        self.assertEqual(result['summary']['Resolved on time (%)'], 100)
        self.assertEqual(len(result['email_sections']), 6)
        self.assertEqual(sum(section['presentation'] == 'chart' for section in result['email_sections']), 3)

    def test_monthly_graph_includes_first_and_last_days_only_inside_selection(self):
        cases = [synthetic_case(index, reported=reported) for index, reported in enumerate([
            '2026-08-31T23:59', '2026-09-01T00:00', '2026-09-30T23:59', '2026-10-01T00:00'])]
        result = self.project(cases)
        chart = result['email_sections'][0]
        self.assertEqual(result['summary']['Reported'], 2)
        self.assertEqual(len(chart['labels']), 30)
        self.assertEqual(chart['datasets'][0]['values'], [1] + [0] * 28 + [1])
        self.assertNotIn('bucket', chart['context'])
        self.assertIn('per day', chart['context'])

    def test_closures_reopened_and_targets_have_distinct_denominators(self):
        cases = [synthetic_case(i, resolved='2026-09-11T09:00', target=target)
                 for i, target in enumerate([True, False, None])]
        cases[0].complaint_timing['closures'].append(stamp('2026-09-12T09:00'))
        cases[0].complaint_timing['reopened'] = [stamp('2026-09-11T10:00'), stamp('2026-09-12T10:00')]
        result = self.project(cases, 'cmp_tat')
        self.assertEqual(result['summary']['Resolved on time (%)'], 50)
        self.assertEqual(result['summary']['Reopened in period'], 1)
        targets = result['email_sections'][2]
        self.assertEqual(dict(zip(targets['labels'], targets['datasets'][0]['values'])), {'On time': 1, 'Late': 1, 'No target': 1})
        summary = self.project(cases)
        self.assertEqual(summary['summary']['Resolved in period'], 3)

    def test_comment_response_is_not_resolution_and_samples_are_visible(self):
        result = self.project([synthetic_case(1, response='2026-09-11T09:00')])
        self.assertEqual(result['summary']['Resolved in period'], 0)
        self.assertEqual(result['summary']['Median HB response (hours)'], 6)
        self.assertEqual(result['metric_notes']['Median HB response (hours)'], '1 first HB response')

    def test_top_five_plus_other_reconciles_without_repeated_graph(self):
        result = self.project([synthetic_case(i, category=f'Type {i}', branch=f'Branch {i}') for i in range(10)])
        for section in result['email_sections'][2:4]:
            self.assertEqual(len(section['labels']), 6)
            self.assertEqual(section['labels'][-1], 'Other')
            self.assertEqual(sum(section['datasets'][0]['values']), 10)

    def test_open_follow_up_is_current_and_has_no_period_comparison(self):
        result = self.project([synthetic_case(1, reported='2026-01-01T09:00'), synthetic_case(2, age=None)], 'cmp_open')
        self.assertEqual(result['summary']['Open now'], 2)
        self.assertEqual(result['summary']['Over 14 days'], 1)
        self.assertEqual(result['summary']['No HB response'], 2)
        self.assertIn('Current snapshot', result['comparison']['label'])
        self.assertTrue(result['notices'])

    def test_empty_missing_timing_and_zero_baseline_are_honest(self):
        for preset in ['complaints', 'cmp_tat', 'cmp_open']:
            result = self.project([], preset)
            self.assertNotIn('Needs details', result['summary'])
            self.assertNotIn('NaN', str(result))
        result = self.project([])
        self.assertIsNone(result['summary']['Resolved on time (%)'])
        self.assertIsNone(result['summary']['Median resolution (hours)'])

    def test_unsafe_chart_filter_disables_comparison_without_changing_workbook(self):
        result = self.project([], filters={**self.filters, 'metric': 'hb_response', 'date_basis': 'response'})
        self.assertEqual(result['comparison']['metrics'], {})
        self.assertIn('exact selected filters', ' '.join(result['notices']))

    def test_all_report_types_render_plaintext_and_at_most_two_graphs(self):
        for preset in ['complaints', 'cmp_tat', 'cmp_open']:
            result = self.project([synthetic_case(1, resolved='2026-09-11T09:00', response='2026-09-10T15:00')], preset)
            snapshot = {**result, 'preset': preset, 'period': {'from': '2026-09-01', 'to': '2026-09-30'},
                        'run_at': self.now.isoformat(), 'total_rows': 1, 'rows': [],
                        'xlsx_content': base64.b64encode(b'synthetic').decode(), 'applied_filters': self.filters}
            payload = build_payload(snapshot, 'synthetic@example.invalid', {})
            self.assertLessEqual(payload['html'].count('class="report-graph"'), 2)
            self.assertNotIn('Breakdown</h2>', payload['html'])
            if preset != 'cmp_open':
                self.assertIn(result['email_sections'][0]['title'], payload['text'])
            else:
                self.assertNotIn('Open-case age', payload['html'])  # No open cases: omit the empty chart.
            self.assertNotIn('customer_name', payload['html'])
            self.assertIn('max-width:900px', payload['html'])

    def test_follow_up_headlines_stay_compact_without_repeated_snapshot_labels(self):
        from .rendering import email_context
        result = self.project([synthetic_case(1)], 'cmp_open')
        context = email_context({**result, 'preset': 'cmp_open', 'run_at': self.now.isoformat(),
                                 'total_rows': 1, 'rows': [], 'applied_filters': self.filters})
        self.assertEqual(context['headline'][-1]['value'], '17.0 days')
        self.assertFalse(context['headline'][-1]['long_value'])
        self.assertEqual(context['comparison_label'], '')


class ComplaintScheduleTests(TestCase):
    def setUp(self):
        from core.models import AccessGrant, GroupSheetConfiguration
        self.actor = get_user_model().objects.create_user(username='synthetic-complaint-email-it')
        self.denied = get_user_model().objects.create_user(username='synthetic-no-email-access')
        self.group = GroupSheetConfiguration.objects.create(group_id='synthetic-email-complaints')
        AccessGrant.objects.create(user=self.actor, workflow='complaint_cases', role='IT', group_configuration=self.group, branch='Training')

    def test_all_three_presets_save_send_and_keep_scope_idempotently(self):
        from .settings import save_configuration, settings_action
        from .services import queue_schedule
        for preset in ['complaints', 'cmp_tat', 'cmp_open']:
            values = {'id': str(uuid.uuid4()), 'group_configuration': self.group.pk, 'title': preset,
                      'preset': preset, 'branch': 'Training', 'frequency': 'monthly', 'active': True,
                      'send_time': '08:00', 'recipients': ['synthetic@example.invalid']}
            schedule = save_configuration(self.actor, 'complaint_cases', values)
            with self.assertRaises(PermissionDenied):
                save_configuration(self.denied, 'complaint_cases', values)
            with self.assertRaises(PermissionDenied):
                save_configuration(self.actor, 'complaint_cases', {**values, 'branch': ''})
            key = str(uuid.uuid4())
            first = queue_schedule(schedule.pk, actor=self.actor, request_key=key)
            self.assertEqual([d.pk for d in first], [d.pk for d in queue_schedule(schedule.pk, actor=self.actor, request_key=key)])
            self.assertEqual(first[0].configuration['preset'], preset)
        with patch('report_delivery.dispatch.wake_deliveries'):
            choices = settings_action(self.actor, 'complaint_cases', {'action': 'list'})['preset_options']
        self.assertEqual([c['label'] for c in choices], ['Summary', 'Turnaround performance', 'Open-case follow-up'])

    def test_focused_scheduled_workbooks_include_older_cases_but_not_other_scopes(self):
        from core.models import RawMessage, ProcessedMessage, ParsedMessage, ComplaintCaseControl
        from .settings import save_configuration
        from .sources import capture_workflow_report
        for index, (group, branch, closed) in enumerate([
            (self.group.group_id, 'Training', False), (self.group.group_id, 'Training', True),
            (self.group.group_id, 'Other branch', False), ('other-synthetic-group', 'Training', False),
        ]):
            raw = RawMessage.objects.create(telegram_message_id=f'email-scope-{index}', content='Synthetic')
            processed = ProcessedMessage.objects.create(raw_message=raw, message_hash=f'email-scope-{index}')
            case = ParsedMessage.objects.create(processed_message=processed, message_id=f'email-scope-{index}',
                group_id=group, branch_region=branch, customer_name=f'Synthetic {index}',
                timestamp=stamp('2026-08-01T09:00'), raw_message='', complaint_status='Closed' if closed else 'Open',
                date_resolved=stamp('2026-09-10T09:00') if closed else None)
            ComplaintCaseControl.objects.create(parsed_message=case, reference_number=f'CMP-TEST-{index}',
                                               sla_started_at=case.timestamp)
        for preset, expected_name in [('cmp_open', 'Synthetic 0'), ('cmp_tat', 'Synthetic 1')]:
            schedule = save_configuration(self.actor, 'complaint_cases', {
                'id': str(uuid.uuid4()), 'group_configuration': self.group.pk, 'title': preset,
                'preset': preset, 'branch': 'Training', 'frequency': 'monthly',
                'recipients': ['synthetic@example.invalid'], 'active': False})
            snapshot = capture_workflow_report(schedule, {'period': {'from': '2026-09-01', 'to': '2026-09-30'}})
            self.assertEqual(snapshot['total_rows'], 1)
            self.assertEqual([row['customer_name'] for row in snapshot['rows']], [expected_name])
            if preset == 'cmp_tat':
                self.assertEqual(snapshot['summary']['Median resolution (hours)'], 960)
        schedule.preset, schedule.frequency = 'complaints', 'yearly'
        with patch('report_delivery.complaint_reports.timezone.now', return_value=stamp('2027-01-02T12:00')):
            snapshot = capture_workflow_report(schedule, {'period': {'from': '2026-01-01', 'to': '2026-12-31'}})
        self.assertEqual(snapshot['total_rows'], 2)
        self.assertEqual({row['customer_name'] for row in snapshot['rows']}, {'Synthetic 0', 'Synthetic 1'})
        self.assertEqual(snapshot['summary']['Reported'], 2)
        self.assertEqual(len(snapshot['charts'][0]['labels']), 12)
        self.assertEqual(snapshot['applied_filters']['date_mode'], 'year')
