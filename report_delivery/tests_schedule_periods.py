"""Calendar cadence and complete, readable email history regressions."""
from datetime import datetime, time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase
from PIL import ImageDraw

from .complaint_reports import _history_windows
from .email_charts import chart_png
from .models import ReportSchedule
from .services import completed_period, latest_occurrence, next_occurrence, period_boundary


EAT = ZoneInfo('Africa/Nairobi')


class CalendarCadenceTests(SimpleTestCase):
    def test_yearly_is_a_supported_schedule_choice(self):
        self.assertIn('yearly', dict(ReportSchedule._meta.get_field('frequency').choices))

    def test_yearly_uses_full_previous_calendar_year(self):
        schedule = SimpleNamespace(frequency='yearly', send_time=time(8))
        now = datetime(2025, 10, 12, 12, tzinfo=EAT)
        boundary = period_boundary(schedule, now)
        self.assertEqual(boundary, datetime(2025, 1, 1, 8, tzinfo=EAT))
        self.assertEqual(completed_period(schedule, boundary), {'from': '2024-01-01', 'to': '2024-12-31'})
        self.assertEqual(next_occurrence(schedule, now), datetime(2026, 1, 1, 8, tzinfo=EAT))

    def test_yearly_before_send_time_and_nairobi_new_year(self):
        schedule = SimpleNamespace(frequency='yearly', send_time=time(8))
        early = datetime(2025, 12, 31, 22, tzinfo=ZoneInfo('UTC'))  # January 1, 01:00 EAT
        self.assertEqual(latest_occurrence(schedule, early), datetime(2025, 1, 1, 8, tzinfo=EAT))
        self.assertEqual(next_occurrence(schedule, early), datetime(2026, 1, 1, 8, tzinfo=EAT))
        self.assertEqual(completed_period(schedule, period_boundary(schedule, early)),
                         {'from': '2025-01-01', 'to': '2025-12-31'})


class HistoryChartTests(SimpleTestCase):
    def test_month_shows_every_day_not_partial_week_buckets(self):
        start = datetime(2026, 9, 1, tzinfo=EAT)
        end = datetime(2026, 10, 1, tzinfo=EAT)
        windows, unit = _history_windows(start, end)
        self.assertEqual(unit, 'day')
        self.assertEqual(len(windows), 30)
        self.assertEqual(windows[0][0], start)
        self.assertEqual(windows[-1][1], end)
        self.assertFalse(any('*' in label for _, _, label in windows))

    def test_year_shows_all_twelve_months_without_discarding_early_months(self):
        start = datetime(2024, 1, 1, tzinfo=EAT)
        end = datetime(2025, 1, 1, tzinfo=EAT)
        windows, unit = _history_windows(start, end)
        self.assertEqual(unit, 'month')
        self.assertEqual(len(windows), 12)
        self.assertEqual(windows[0][0], start)
        self.assertEqual(windows[-1][1], end)
        self.assertEqual(windows[1][1].day, 1)

    def test_full_month_line_chart_renders_without_dropping_points(self):
        original = ImageDraw.Draw
        drawings = []

        def record(image):
            draw = MagicMock(wraps=original(image))
            drawings.append(draw)
            return draw

        with patch('report_delivery.email_charts.ImageDraw.Draw', side_effect=record):
            self.assertIsNotNone(chart_png({'type': 'line', 'labels': [f'{day:02d}-09-26' for day in range(1, 31)],
                'datasets': [{'label': 'Reported (complaints)', 'values': list(range(30))}]}))
        self.assertEqual(drawings[-1].ellipse.call_count, 30)

    def test_small_count_axis_has_whole_numbers_not_fractions_of_a_complaint(self):
        original = ImageDraw.Draw
        drawings = []

        def record(image):
            draw = MagicMock(wraps=original(image))
            drawings.append(draw)
            return draw

        with patch('report_delivery.email_charts.ImageDraw.Draw', side_effect=record):
            self.assertIsNotNone(chart_png({'type': 'line', 'unit': 'complaints',
                'labels': ['01-09-26', '02-09-26'], 'datasets': [{'label': 'Reported', 'values': [0, 1]}]}))
        axis_labels = [call.args[1] for call in drawings[-1].text.call_args_list if call.kwargs.get('anchor') == 'rm']
        self.assertGreaterEqual(len(axis_labels), 4)
        self.assertTrue(all(label.isdigit() for label in axis_labels))

    def test_line_chart_draws_horizontal_and_vertical_grid_with_axes(self):
        original = ImageDraw.Draw
        drawings = []

        def record(image):
            draw = MagicMock(wraps=original(image))
            drawings.append(draw)
            return draw

        with patch('report_delivery.email_charts.ImageDraw.Draw', side_effect=record):
            png = chart_png({'type': 'line', 'labels': ['01-09-26', '15-09-26', '30-09-26'],
                'datasets': [{'label': 'Reported (complaints)', 'values': [0, 5, 10]}]})
        self.assertIsNotNone(png)
        segments = [call.args[0] for call in drawings[-1].line.call_args_list]
        self.assertGreaterEqual(sum(x1 == x2 and abs(y2 - y1) > 50 for x1, y1, x2, y2 in segments), 3)
        self.assertGreaterEqual(sum(y1 == y2 and abs(x2 - x1) > 50 for x1, y1, x2, y2 in segments), 4)
