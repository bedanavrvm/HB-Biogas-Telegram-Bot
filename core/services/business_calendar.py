"""Shared official JBL business-hours calculations.

The service deliberately has no workflow state or notification side effects.
It is the one place that turns an elapsed timestamp range into official staff
optional business-hours time so Portal and TAT cannot drift in that secondary view.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.utils import timezone

from core.models import BusinessCalendarHoliday


NAIROBI = ZoneInfo('Africa/Nairobi')
BUSINESS_DAY_START = time(hour=8)
BUSINESS_DAY_END = time(hour=17)
BUSINESS_WEEKDAYS = frozenset({0, 1, 2, 3, 4})


def active_holiday_dates(*, start: date | None = None, end: date | None = None) -> set[date]:
    """Return active holiday dates once per calculation range."""
    queryset = BusinessCalendarHoliday.objects.filter(active=True)
    if start:
        queryset = queryset.filter(date__gte=start)
    if end:
        queryset = queryset.filter(date__lte=end)
    return set(queryset.values_list('date', flat=True))


def _nairobi_datetime(value: datetime) -> datetime:
    if timezone.is_naive(value):
        value = timezone.make_aware(value, NAIROBI)
    return value.astimezone(NAIROBI)


def business_minutes_between(
    start: datetime | None,
    end: datetime | None,
    *,
    holidays: set[date] | None = None,
) -> Decimal | None:
    """Calculate Mon-Fri 08:00-17:00 Nairobi minutes, excluding holidays."""
    if not start or not end:
        return None
    local_start = _nairobi_datetime(start)
    local_end = _nairobi_datetime(end)
    if local_end <= local_start:
        return Decimal('0.00')

    holiday_dates = holidays
    if holiday_dates is None:
        holiday_dates = active_holiday_dates(start=local_start.date(), end=local_end.date())

    total_seconds = Decimal('0')
    current_date = local_start.date()
    while current_date <= local_end.date():
        if current_date.weekday() in BUSINESS_WEEKDAYS and current_date not in holiday_dates:
            day_start = datetime.combine(current_date, BUSINESS_DAY_START, tzinfo=NAIROBI)
            day_end = datetime.combine(current_date, BUSINESS_DAY_END, tzinfo=NAIROBI)
            window_start = max(local_start, day_start)
            window_end = min(local_end, day_end)
            if window_end > window_start:
                total_seconds += Decimal(str((window_end - window_start).total_seconds()))
        current_date += timedelta(days=1)
    return (total_seconds / Decimal('60')).quantize(Decimal('0.01'))


def wall_clock_minutes_between(start: datetime | None, end: datetime | None) -> Decimal | None:
    if not start or not end:
        return None
    if timezone.is_naive(start):
        start = timezone.make_aware(start, NAIROBI)
    if timezone.is_naive(end):
        end = timezone.make_aware(end, NAIROBI)
    seconds = max(Decimal('0'), Decimal(str((end - start).total_seconds())))
    return (seconds / Decimal('60')).quantize(Decimal('0.01'))


def subtract_business_minutes(
    value: Decimal | None,
    excluded_seconds: Decimal | int | float = Decimal('0'),
) -> Decimal | None:
    """Apply the already-approved deferred/reappraisal exclusion safely."""
    if value is None:
        return None
    excluded = (Decimal(str(excluded_seconds or 0)) / Decimal('60')).quantize(Decimal('0.01'))
    return max(Decimal('0.00'), value - excluded).quantize(Decimal('0.01'))


def hybrid_tat_minutes(
    start: datetime | None,
    end: datetime | None,
    *,
    excluded_seconds: Decimal | int | float = Decimal('0'),
    holidays: set[date] | None = None,
) -> dict[str, Decimal | None]:
    """Return backwards-compatible wall-clock plus official SLA measures."""
    wall_clock = wall_clock_minutes_between(start, end)
    business = business_minutes_between(start, end, holidays=holidays)
    excluded = (Decimal(str(excluded_seconds or 0)) / Decimal('60')).quantize(Decimal('0.01'))
    return {
        'wall_clock_minutes': wall_clock,
        'business_minutes': business,
        'excluded_minutes': excluded,
        'sla_minutes': subtract_business_minutes(business, excluded_seconds),
    }
