from datetime import date

from django.test import SimpleTestCase

from core.services.report_periods import calendar_period
from core.services.tat_reporting import _chart_payload, _filters


class ReportPeriodTests(SimpleTestCase):
    def test_open_and_completed_calendar_periods(self):
        today = date(2026, 10, 7)
        for mode, values, expected in [
            ('month', {'month': '2024-02'}, (date(2024, 2, 1), date(2024, 2, 29))),
            ('quarter', {'year': '2026', 'quarter': '3'}, (date(2026, 7, 1), date(2026, 9, 30))),
            ('quarter', {'year': '2026', 'quarter': '4'}, (date(2026, 10, 1), today)),
            ('year', {'year': '2025'}, (date(2025, 1, 1), date(2025, 12, 31))),
            ('year', {'year': '2026'}, (date(2026, 1, 1), today)),
        ]:
            with self.subTest(mode=mode, values=values):
                self.assertEqual(calendar_period(mode, values, today), expected)

    def test_invalid_periods_are_rejected(self):
        for mode, values in [('quarter', {'quarter': 5}), ('quarter', {'quarter': 0}), ('year', {'year': 0}),
                             ('month', {'month': '2026-13'}), ('invalid', {})]:
            with self.subTest(mode=mode, values=values), self.assertRaises(ValueError):
                calendar_period(mode, values, date(2026, 10, 7))

    def test_any_time_does_not_exclude_backdated_imported_actions(self):
        filters = _filters({'date_mode': 'all', 'granularity': 'day'})
        self.assertEqual(filters['date_from'], date.min)
        self.assertEqual(filters['granularity'], 'day')

    def test_any_time_still_bounds_actual_chart_points(self):
        with self.assertRaisesRegex(ValueError, 'coarser time grouping'):
            _chart_payload('trend', '', 'completed_actions', '', list(range(367)), [], applied_filters=[])

    def test_tat_chart_units_match_source_values(self):
        for chart, basis, metric, unit in [
            ('trend', 'completed_actions', None, 'actions'),
            ('backlog_age', 'current_cases', None, 'cases'),
            ('tat_percentiles', 'completed_actions', None, 'minutes'),
            ('case_progression', 'case', None, 'minutes'),
            ('sla_compliance', 'completed_actions', None, 'percent'),
            ('explorer', 'current_cases', 'load_per_assignee', 'cases_per_assignee'),
            ('explorer', 'completed_actions', 'duration', 'minutes'),
            ('explorer', 'completed_actions', 'correction_rate', 'percent'),
        ]:
            with self.subTest(chart=chart, metric=metric):
                payload = _chart_payload(chart, '', basis, '', [], [],
                                         applied_filters=[], extras={'metric': metric})
                self.assertEqual(payload['unit'], unit)
