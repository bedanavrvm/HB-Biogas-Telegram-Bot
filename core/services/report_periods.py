"""Calendar report periods, independent of each workflow's cohort semantics."""
from calendar import monthrange
from datetime import date


def calendar_period(mode, values, today):
    """Inclusive Nairobi dates; an open period ends today, a past one in full."""
    year_value = values.get('year')
    year = int(today.year if year_value in (None, '') else year_value)
    if not 1900 <= year <= 9998:
        raise ValueError('Choose a valid year.')
    if mode == 'month':
        start = date.fromisoformat(str(values.get('month') or today.strftime('%Y-%m')) + '-01')
        if not 1900 <= start.year <= 9998:
            raise ValueError('Choose a valid month.')
        end = start.replace(day=monthrange(start.year, start.month)[1])
    elif mode == 'quarter':
        quarter_value = values.get('quarter')
        quarter = int(((today.month - 1) // 3 + 1) if quarter_value in (None, '') else quarter_value)
        if not 1 <= quarter <= 4:
            raise ValueError('Choose a quarter from 1 to 4.')
        start = date(year, quarter * 3 - 2, 1)
        month = quarter * 3
        end = date(year, month, monthrange(year, month)[1])
    elif mode == 'year':
        start, end = date(year, 1, 1), date(year, 12, 31)
    else:
        raise ValueError('Choose a valid calendar period.')
    return start, today if start <= today <= end else end
