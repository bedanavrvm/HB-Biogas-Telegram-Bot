"""Read-only email projections over the existing complaint timing facts.

No customer facts are added to the email body. The caller supplies the authorized
queryset and captures this projection and its workbook in one database snapshot.
"""
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.utils import timezone

from core.services.complaint_timing import AGE_BUCKETS, NAIROBI, median_hours, timed_cases


def month_start_shift(day, months):
    index = day.year * 12 + day.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def comparison_window(filters, *, now):
    """Half-open Nairobi windows; partial periods compare equal elapsed time."""
    local = now.astimezone(NAIROBI)
    if not filters.get('date_from') or not filters.get('date_to'):
        start = datetime.combine(local.date(), time.min, NAIROBI)
        return start, local, start - timedelta(days=1), local - timedelta(days=1), 'Today vs yesterday'
    first, last = date.fromisoformat(filters['date_from']), date.fromisoformat(filters['date_to'])
    start = datetime.combine(first, time.min, NAIROBI)
    end = datetime.combine(last + timedelta(days=1), time.min, NAIROBI)
    custom = filters.get('date_mode') == 'custom'
    if not custom and first.day == 1 and end.day == 1 and end.month == 1 and first.month == 1 and end.year == first.year + 1:
        previous = start.replace(year=start.year - 1)
    elif not custom and first.day == 1 and end.day == 1 and (end.year * 12 + end.month - first.year * 12 - first.month) in {1, 3}:
        months = end.year * 12 + end.month - first.year * 12 - first.month
        previous = datetime.combine(month_start_shift(first, -months), time.min, NAIROBI)
    else:
        previous = start - (end - start)
    if local <= start:
        return start, start, previous, previous, 'Selected period has not started; comparison unavailable.'
    cutoff = min(end, local)
    # A future selection has no observed elapsed time, not negative activity.
    elapsed = max(timedelta(0), cutoff - start)
    if local < end:
        elapsed = min(elapsed, start - previous)
        cutoff, previous_end = start + elapsed, previous + elapsed
    else:
        previous_end = start
    label = f'{start:%d-%m-%y} to {cutoff - timedelta(microseconds=1):%d-%m-%y} vs {previous:%d-%m-%y} to {previous_end - timedelta(microseconds=1):%d-%m-%y}'
    if local < end:
        label += f' · equal elapsed time, through {cutoff:%d-%m-%y %H:%M} EAT'
    return start, cutoff, previous, previous_end, label


def _in(stamp, start, end):
    return stamp is not None and start <= stamp < end


def _stats(cases, start, end):
    reported, closed, reopened = set(), set(), set()
    resolution, response, categories = [], [], defaultdict(list)
    on_time = late = no_target = 0
    targets = set()
    for case in cases:
        facts = case.complaint_timing
        if _in(facts['reported_at'], start, end):
            reported.add(case.pk)
        if any(_in(stamp, start, end) for stamp in facts['closures']):
            closed.add(case.pk)
        if any(_in(stamp, start, end) for stamp in facts['reopened']):
            reopened.add(case.pk)
        if case.complaint_status == 'Closed' and _in(facts['resolved_at'], start, end) and facts['resolution_hours'] is not None:
            value = facts['resolution_hours']
            resolution.append(value)
            categories[_category(case)].append(value)
            target = getattr(case.complaint_control, 'sla_target_hours', None)
            if target and target > 0:
                targets.add(str(target))
            if facts['on_time'] is True:
                on_time += 1
            elif facts['on_time'] is False:
                late += 1
            else:
                no_target += 1
        if _in(facts['response_at'], start, end) and facts['hb_response_hours'] is not None:
            response.append(facts['hb_response_hours'])
    return {'Reported': len(reported), 'Resolved in period': len(closed),
            'Reopened in period': len(reopened), 'Median resolution (hours)': median_hours(resolution),
            'Median HB response (hours)': median_hours(response),
            'Resolved on time (%)': round(on_time * 100 / (on_time + late), 1) if on_time + late else None,
            'resolution_count': len(resolution), 'response_count': len(response),
            'on_time': on_time, 'late': late, 'no_target': no_target,
            'categories': categories, 'targets': sorted(targets, key=Decimal)}


def _category(case):
    control = case.complaint_control
    return control.category.label if control.category_id else case.complaint_category or 'Not provided'


def _branch(case):
    control = case.complaint_control
    return control.branch_ref.name if control.branch_ref_id else case.branch_region or 'Not provided'


def _section(title, labels, datasets, *, kind='rows', context='', unit='complaints'):
    return {'title': title, 'labels': list(labels), 'datasets': datasets, 'type': 'line',
            'presentation': kind, 'context': context, 'unit': unit}


def _counts(title, counts, *, context='', top=False):
    items = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0].casefold()))
    if top and len(items) > 5:
        items = items[:5] + [('Other (remaining)' if any(key == 'Other' for key, _ in items[:5]) else 'Other', sum(value for _, value in items[5:]))]
    return _section(title, [key for key, _ in items],
                    [{'label': 'Complaints', 'values': [value for _, value in items]}], context=context)


def _history_windows(start, end):
    days = (end - start).total_seconds() / 86400
    unit = 'day' if days <= 31 else 'month' if days <= 366 else 'year'
    # Cover the entire selection. Thin axis labels in the renderer, never facts.
    # Months show days; quarters/years show calendar months, not clipped weeks.
    cursor = start
    windows = []
    while cursor < end:
        if unit == 'month':
            next_day = month_start_shift(cursor.date(), 1)
            following = datetime.combine(next_day, time.min, NAIROBI)
        elif unit == 'year':
            following = datetime(cursor.year + 1, 1, 1, tzinfo=NAIROBI)
        else:
            following = datetime.combine(cursor.date() + timedelta(days=1), time.min, NAIROBI)
        stop = min(following, end)
        label = cursor.strftime('%d-%m-%y')
        windows.append((cursor, stop, label))
        cursor = following
    return windows, unit


def _delta(label, current, previous):
    if current is None or previous is None:
        return {'text': 'Comparison unavailable', 'tone': 'muted'}
    # A measured 0% or immediate response is a valid baseline, not no activity.
    if previous == 0 and not label.endswith(('(hours)', '(%)')):
        return {'text': 'No previous activity', 'tone': 'muted'}
    change = Decimal(str(current)) - Decimal(str(previous))
    sign = '+' if change > 0 else '−' if change < 0 else ''
    if label.endswith('(hours)'):
        minutes = int(abs(change) * 60)
        days, rest = divmod(minutes, 1440)
        hours, mins = divmod(rest, 60)
        value = ' '.join(part for part in [f'{days}d' if days else '', f'{hours}h' if hours else '', f'{mins}m' if mins else ''] if part) or '0m'
        tone = 'good' if change < 0 else 'bad' if change > 0 else 'muted'
    else:
        value = f'{abs(change):,.1f}'.rstrip('0').rstrip('.') if label.endswith('(%)') else f'{abs(change):,.0f}'
        value += ' pp' if label.endswith('(%)') else ''
        tone = ('good' if change > 0 else 'bad' if change < 0 else 'muted') if label.endswith('(%)') else 'muted'
    return {'text': f'{sign}{value} vs previous', 'tone': tone}


def complaint_email_projection(base, filters, *, preset='complaints', now=None):
    """Scope never widens: retain non-date selections; open panels ignore dates only."""
    from core.services.complaint_register import _apply_report_filters
    now = now or timezone.now()
    scoped = _apply_report_filters(base, filters, timing=False)
    cases = list(timed_cases(scoped, now=now))
    selected = cases
    unsafe_selection = bool(filters.get('metric') or filters.get('date_basis', 'reported') != 'reported')
    if unsafe_selection:
        # Chart selections are not safely shiftable. Preserve their exact cohort
        # for activity/timing, but current backlog still uses the named scope.
        selected = list(timed_cases(_apply_report_filters(base, filters), now=now))
    start, end, prior, prior_end, comparison_label = comparison_window(filters, now=now)
    period_start = datetime.combine(date.fromisoformat(filters['date_from']), time.min, NAIROBI) if filters.get('date_from') else None
    period_end = datetime.combine(date.fromisoformat(filters['date_to']) + timedelta(days=1), time.min, NAIROBI) if filters.get('date_to') else None
    # All-time/open-ended headlines keep their full cohort. Comparison is a
    # separately labelled today/yesterday read, not a redefinition of that cohort.
    headline_start = period_start or datetime.min.replace(tzinfo=NAIROBI)
    headline_end = min(period_end, now) if period_end else now
    current, previous = _stats(selected, start, end), _stats(selected, prior, prior_end)
    stats = _stats(selected, headline_start, headline_end)
    open_cases = [case for case in cases if case.complaint_status != 'Closed']
    ages = Counter(case.complaint_timing['age_bucket'] for case in open_cases)
    branch_counts = defaultdict(lambda: [0, 0, 0])
    for case in open_cases:
        values = branch_counts[_branch(case)]
        values[0] += 1
        values[1] += case.complaint_timing['age_bucket'] == 'over_14'
        values[2] += case.complaint_timing['response_at'] is None
    age_section = _counts('Open-case age', {label: ages[key] for key, label, *_ in AGE_BUCKETS}, context='All currently unresolved complaints, including older cases. Age in calendar days.')
    # Preserve the chronological order of the four age buckets.
    age_section['labels'] = [label for _, label, *_ in AGE_BUCKETS]
    age_section['datasets'][0]['values'] = [ages[key] for key, *_ in AGE_BUCKETS]
    if preset == 'cmp_open':
        age_section.update(type='bar', presentation='chart')
        elapsed = [case.complaint_timing['elapsed_seconds'] / 3600 for case in open_cases if case.complaint_timing['elapsed_seconds'] is not None]
        summary = {'Open now': len(open_cases), 'Over 14 days': ages['over_14'],
                   'No HB response': sum(values[2] for values in branch_counts.values()),
                   'Oldest open (hours)': max(elapsed) if elapsed else None}
        branches = sorted(branch_counts, key=lambda key: (-branch_counts[key][0], key.casefold()))
        values = [branch_counts[key] for key in branches]
        if len(branches) > 5:
            branches = branches[:5] + ['Other branches']
            values = values[:5] + [[sum(row[i] for row in values[5:]) for i in range(3)]]
        sections = [age_section, _section('Open cases by branch', branches,
            [{'label': label, 'values': [row[index] for row in values]}
             for index, label in enumerate(['Open', 'Over 14 days', 'No HB response'])], context='14d+: over 14 days. No reply: no HB response recorded. Top five branches + remaining branches.')]
        return {'summary': summary, 'email_sections': sections, 'charts': sections,
                'comparison': {'label': 'Current snapshot · generated now; no historical open-count comparison.'},
                'metric_notes': {}, 'notices': _age_notices(ages),
                'management': {'open': len(open_cases), 'late_open': _late_open(open_cases),
                               'no_response': summary['No HB response']}}
    recent_start = datetime.combine(headline_end.astimezone(NAIROBI).date() - timedelta(days=7), time.min, NAIROBI)
    history_start = period_start if period_start and period_end else max(period_start or recent_start, recent_start)
    windows, unit = _history_windows(history_start, headline_end)
    history = [_stats(selected, a, b) for a, b, _ in windows]
    cadence = {'day': 'Daily', 'month': 'Monthly', 'year': 'Yearly'}[unit]
    history_context = f'{cadence} medians · hours.' if preset == 'cmp_tat' else f'Distinct complaints per {unit}.'
    if period_end and now < period_end and windows:
        history_context += f' Through {headline_end:%d-%m-%y %H:%M} EAT.'
    if preset == 'cmp_tat':
        summary = {key: stats[key] for key in ['Median resolution (hours)', 'Median HB response (hours)', 'Resolved on time (%)', 'Reopened in period']}
        sections = [_section(title, [label for _, _, label in windows],
            [{'label': 'Hours', 'values': [row[key] for row in history]}], kind='chart', context=history_context, unit='hours')
            for title, key in [('Resolution time', 'Median resolution (hours)'), ('HB response time', 'Median HB response (hours)')]]
        sections += [_counts('Resolution targets', {'On time': stats['on_time'], 'Late': stats['late'], 'No target': stats['no_target']}, context=f"{stats['on_time'] + stats['late']} timed resolutions with a target; no-target cases excluded from the rate."),
            _section('Slowest complaint types', list(sorted(stats['categories'], key=lambda key: (-median_hours(stats['categories'][key]), key))[:5]), [])]
        slow = sections[-1]
        slow['datasets'] = [{'label': 'Median hours', 'values': [median_hours(stats['categories'][key]) for key in slow['labels']]},
                            {'label': 'Samples', 'values': [len(stats['categories'][key]) for key in slow['labels']]}]
    else:
        summary = {'Reported': stats['Reported'], 'Resolved in period': stats['Resolved in period'],
                   'Open now': len(open_cases), 'Resolved on time (%)': stats['Resolved on time (%)'],
                   'Median resolution (hours)': stats['Median resolution (hours)'],
                   'Median HB response (hours)': stats['Median HB response (hours)']}
        reported_cases = [case for case in selected if _in(case.complaint_timing['reported_at'], headline_start, headline_end)]
        sections = [_section('Reported vs resolved', [label for _, _, label in windows],
            [{'label': title, 'values': [row[key] for row in history]} for title, key in [('Reported', 'Reported'), ('Resolved', 'Resolved in period')]], kind='chart', context=history_context),
            age_section, _counts('Complaint types', Counter(_category(case) for case in reported_cases), top=True, context='Reported in the selected period · top five + Other.'),
            _counts('Complaints by branch', Counter(_branch(case) for case in reported_cases), top=True, context='Reported in the selected period · top five + Other.')]
    safe_compare = not filters.get('metric') and filters.get('date_basis', 'reported') == 'reported'
    bounded = period_start is not None and period_end is not None
    deltas = {key: _delta(key, current[key], previous[key]) for key in summary if key in current} if safe_compare and bounded else {}
    for key, delta in deltas.items():
        delta['paired_values'] = {'current': current[key], 'previous': previous[key]}
    notices = _age_notices(ages)
    if deltas and end < headline_end:
        notices.append('Headline totals cover the selected dates. Comparisons use the shorter matching window shown below.')
        for key, delta in deltas.items():
            delta['paired_values'] = {'current': current[key], 'previous': previous[key]}
    if not safe_compare:
        notices.append('Previous-period comparison is unavailable for this chart/date selection. Your Excel keeps the exact selected filters.')
    elif not bounded:
        notices.append(f"Today vs yesterday: {current['Reported']} reported vs {previous['Reported']}; {current['Resolved in period']} resolved vs {previous['Resolved in period']}. Headline totals retain the selected date scope.")
    needs = sum(case.complaint_status == 'Review Needed' for case in cases)
    if needs:
        notices.append(f'{needs} complaint(s) need details.')
    result = {'summary': summary, 'email_sections': sections, 'charts': sections,
            'comparison': {'label': comparison_label if safe_compare else 'Comparison unavailable', 'metrics': deltas},
            'metric_notes': {'Median resolution (hours)': f"{stats['resolution_count']} timed resolution{'s' if stats['resolution_count'] != 1 else ''}",
                             'Median HB response (hours)': f"{stats['response_count']} first HB response{'s' if stats['response_count'] != 1 else ''}"},
            'notices': notices,
            'management': {'resolved': stats['Resolved in period'], 'on_time': stats['on_time'],
                'late': stats['late'], 'no_target': stats['no_target'], 'targets_hours': stats['targets'],
                'resolution_count': stats['resolution_count'], 'response_count': stats['response_count'],
                'resolution_hours': stats['Median resolution (hours)'], 'open': len(open_cases),
                'late_open': _late_open(open_cases),
                'previous_on_time': previous['on_time'] if deltas else None,
                'previous_target_count': previous['on_time'] + previous['late'] if deltas else None,
                'comparison_on_time': current['on_time'], 'comparison_target_count': current['on_time'] + current['late'],
                'previous_from': prior.date().isoformat() if deltas else None,
                'previous_to': (prior_end - timedelta(microseconds=1)).date().isoformat() if deltas else None,
                'comparison_cutoff': end.isoformat() if deltas and end < headline_end else None}}
    if preset == 'cmp_tat':
        result['_activity_case_ids'] = [str(case.pk) for case in selected if any(
            _in(stamp, headline_start, headline_end) for stamp in [case.complaint_timing['resolved_at'],
                case.complaint_timing['response_at'], *case.complaint_timing['reopened']])]
    return result


def _age_notices(ages):
    return [f"{ages[None]} open complaint(s) have no recorded start date."] if ages[None] else []


def _late_open(cases):
    return sum(1 for case in cases
               if getattr(case.complaint_control, 'sla_target_hours', None)
               and case.complaint_control.sla_target_hours > 0
               and case.complaint_timing['elapsed_seconds'] is not None
               and case.complaint_timing['elapsed_seconds'] > case.complaint_control.sla_target_hours * 3600)
