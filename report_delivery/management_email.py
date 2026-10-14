"""Compact presentation over frozen aggregate facts; no queries or disclosure expansion."""
from datetime import date, datetime
from decimal import Decimal

HIGHER_IS_BETTER = {
    'Resolved in period': True, 'Resolved': True, 'Completed actions': True,
    'Resolved on time (%)': True, 'Within or near target (%)': True,
    'Median resolution (hours)': False, 'Median HB response (hours)': False,
    'Median TAT (minutes)': False, 'Reopened in period': False,
    'Over target': False, 'Stalled cases': False,
}
LABELS = {'Median HB response': 'First response', 'No HB response': 'No response yet',
          'Reopened in period': 'Complaints reopened', 'Complaints received': 'Reported'}


def date_range(first, last):
    a, b = date.fromisoformat(str(first)[:10]), date.fromisoformat(str(last)[:10])
    if a == b:
        return f'{a.day} {a:%b %Y}'
    left = f'{a.day} {a:%b}'
    if a.year != b.year:
        left += f' {a.year}'
    return f'{left} - {b.day} {b:%b %Y}'


def compact_date_range(first, last):
    """Short, unambiguous stamps that fit paired periods on a phone."""
    a, b = date.fromisoformat(str(first)[:10]), date.fromisoformat(str(last)[:10])
    if a == b:
        return f'{a.day} {a:%b %y}'
    if (a.year, a.month) == (b.year, b.month):
        return f'{a.day}-{b.day} {b:%b %y}'
    left = f'{a.day} {a:%b}' + (f' {a:%y}' if a.year != b.year else '')
    return f'{left}-{b.day} {b:%b %y}'


def _complaint_summary(snapshot, facts):
    reported = snapshot['summary'].get('Reported', 0)
    period = snapshot.get('period') or {}
    filters = snapshot.get('applied_filters') or {}
    first, last = period.get('from') or filters.get('date_from'), period.get('to') or filters.get('date_to')
    scope = 'during the selected period'
    if first and last:
        a, b = date.fromisoformat(first), date.fromisoformat(last)
        if a.day == 1 and a.month == b.month and a.year == b.year:
            from calendar import monthrange
            if b.day == monthrange(b.year, b.month)[1]:
                scope = f'in {a:%B %Y}'
    summary = f'{_count(reported, "new complaint")} {"was" if reported == 1 else "were"} reported {scope}.'
    if 'reported_resolved' in facts:
        same, older, other = facts['reported_resolved'], facts['older_resolved'], facts.get('other_resolved', 0)
        summary += f' {same} of these {"was" if same == 1 else "were"} resolved in the same period'
        additions = []
        if older:
            additions.append(_count(older, 'older complaint'))
        if other:
            additions.append(_count(other, 'other complaint'))
        if additions:
            summary += ', along with ' + ' and '.join(additions)
        summary += '.'
    else:
        # Historical snapshots never acquire invented cohort intersections.
        resolved = facts.get('resolved', 0)
        summary += f' {_count(resolved)} {"was" if resolved == 1 else "were"} resolved {scope}; this total can include older complaints.'
    reopened = facts.get('resolved_now_reopened', 0)
    if reopened:
        summary += f' {_count(reopened, "resolved complaint")} {"has" if reopened == 1 else "have"} since reopened.'
    opened = facts.get('open', 0)
    summary += f' {_count(opened)} {"remains" if opened == 1 else "remain"} open overall, including {facts.get("late_open", 0)} overdue.'
    return summary


def duration(label, value):
    if value is None:
        return '—'
    number = Decimal(str(value))
    if not number.is_finite() or number < 0:
        return '—'
    if label.endswith(' (minutes)'):
        number /= 60
    if number == 0:
        return '0 hours'
    if number < 1:
        return 'Under 1 hour'
    if ('resolution' in label.lower() or label == 'Oldest open (hours)') and number >= 24:
        return f'{number / 24:,.1f} days'
    return f'{number:,.1f} hours'


def _count(n, singular='complaint'):
    return f'{n} {singular}' + ('' if n == 1 else 's')


def _comparison_period(facts):
    if not facts.get('previous_from'):
        return 'the previous period'
    start, end = (date.fromisoformat(facts[key]) for key in ('previous_from', 'previous_to'))
    days = (end - start).days + 1
    if start.month == 1 and start.day == 1 and end.month == 12 and end.day == 31:
        return 'last year'
    if start.day == 1 and end.month != start.month and 89 <= days <= 92:
        return 'last quarter'
    if start.day == 1 and start.month == end.month and days >= 28:
        return 'last month'
    return 'last week' if days == 7 else 'yesterday' if days == 1 else 'the previous period'


def _metric(label, item, snapshot, facts):
    item = dict(item)
    value = snapshot['summary'][label]
    item['label'] = LABELS.get(item['label'], item['label'])
    if label.endswith((' (hours)', ' (minutes)')):
        item['value'] = duration(label, value)
        item['duration_value'] = True
    elif label.endswith(' (%)') and value is not None:
        item['value'] = f'{Decimal(str(value)):,.0f}%'
    if '(KES)' in label and value is not None:
        number = Decimal(str(value))
        if number.is_finite() and abs(number) >= 1000000:
            item['exact_value'] = item['value']
            scale, suffix = (Decimal(1000000000), 'B') if abs(number) >= 1000000000 else (Decimal(1000000), 'M')
            item['value'] = f'{number / scale:,.1f}{suffix}'
    item.update(ink='#243244', previous='Not available', change='', status='', note='', target='',
                comparison=None, comparison_scope='', comparison_ink='#526173',
                comparison_line='Current snapshot' if snapshot['preset'] == 'cmp_open' else 'No earlier data yet')
    if value is not None:
        if label in {'Resolved in period', 'Resolved', 'Disbursed'} and value > 0:
            item['ink'] = '#17643b'
        elif label == 'Reopened in period' and value > 0:
            item['ink'] = '#b42318'
        elif label == 'Resolved on time (%)':
            item['ink'] = '#17643b' if value >= 80 else '#a36b08' if value >= 60 else '#b42318'
    paired = snapshot.get('comparison', {}).get('metrics', {}).get(label, {}).get('paired_values')
    if paired and paired.get('previous') is not None and paired.get('current') is not None:
        previous, current = Decimal(str(paired['previous'])), Decimal(str(paired['current']))
        diff = current - previous
        item['previous'] = (duration(label, previous) if label.endswith((' (hours)', ' (minutes)')) else
                            f'{previous:,.0f}%' if label.endswith(' (%)') else f'{previous:,.0f}')
        direction = HIGHER_IS_BETTER.get(label)
        item['status'] = 'Unchanged' if not diff else 'Change' if direction is None else 'Better' if (diff > 0) == direction else 'Worse'
        item['comparison_ink'] = '#17643b' if item['status'] == 'Better' else '#b42318' if item['status'] == 'Worse' else '#526173'
        arrow = '▲' if diff > 0 else '▼' if diff < 0 else '•'
        if not diff:
            change = 'Unchanged'
        elif label.endswith(' (%)'):
            change = f'{arrow} {abs(diff):,.0f} pts {"higher" if diff > 0 else "lower"}'
        elif label.endswith((' (hours)', ' (minutes)')):
            change = f'{arrow} {duration(label, abs(diff))} {"longer" if diff > 0 else "quicker"}'
        else:
            change = f'{arrow} {abs(diff):,.0f} {"more" if diff > 0 else "fewer"}'
        item['change'] = change
        item['comparison_line'] = f'Was {item["previous"]} {_comparison_period(facts)} · {change}'
        if facts.get('comparison_cutoff'):
            item['comparison_line'] = f'Matched window: was {item["previous"]} · {change}'
    item['long_value'] = len(item['value']) > 18
    return item


def _prepare_sections(context):
    """Each panel has one identity and one display role, independent of its title."""
    sections = []
    for original in context['breakdowns']:
        chart = {**original, 'rows': [{**row, 'values': list(row['values']),
                                     'cells': [dict(cell) for cell in row['cells']]} for row in original['rows']]}
        definition = {**chart['definition'], 'datasets': [dict(series) for series in chart['definition']['datasets']]}
        raw_title = chart['title']
        chart['key'] = raw_title
        chart['title'] = {'HB response time': 'First-response time'}.get(raw_title, raw_title)
        labels = []
        for row in chart['rows']:
            try:
                day = datetime.strptime(str(row['label']), '%d-%m-%y')
                row['label'] = f'{day.day} {day:%b %Y}'
            except ValueError:
                pass
            row['label'] = str(row['label']).replace('–', '-').replace('—', '-')
            labels.append(row['label'])
        definition.update(labels=labels, title=chart['title'])
        if raw_title in {'Resolution time', 'HB response time', 'First-response time'}:
            resolution = raw_title == 'Resolution time'
            definition.update(unit='days' if resolution else 'hours', temporal=True)
            definition['datasets'] = [{**series, 'label': 'Days' if resolution else 'Hours',
                'values': [float(Decimal(str(value)) / (24 if resolution else 1)) if value is not None else None
                           for value in series['values']]} for series in definition['datasets']]
            for i, row in enumerate(chart['rows']):
                row['values'] = [duration('Median resolution (hours)' if resolution else 'First response (hours)',
                                         series['values'][i] if i < len(series['values']) else None)
                                 for series in original['definition']['datasets']]
                row['cells'] = [{'label': 'Median time', 'value': value} for value in row['values']]
            chart['context'] = ('Median resolution time by date; the tile covers the full period.' if resolution else
                                'Median wait for the first HomeBiogas response, by response date.')
        if raw_title == 'Reported vs resolved':
            definition['temporal'] = True
            definition.update(type='line' if len(labels) > 1 else 'bar', colors=['#2481cc', '#168354'])
            chart['context'] = 'Complaints reported and resolved by date. Resolutions include older complaints.'
        elif raw_title in {'On-time vs late', 'Response coverage'}:
            definition.update(type='doughnut', colors=[
                '#168354' if label in {'On time', 'Response recorded'} else '#d14343' for label in labels])
            chart['context'] = ('Resolved complaints with a recorded target; no-target cases excluded.' if raw_title == 'On-time vs late'
                                else 'First recorded HomeBiogas response on currently open complaints.')
        elif raw_title == 'Open-case age':
            definition.update(type='bar', colors=['#2481cc', '#168354', '#d49a16', '#d14343'])
        elif raw_title in {'Resolution time', 'HB response time', 'First-response time'}:
            definition.update(type='line' if len(labels) > 1 else 'bar',
                              colors=['#2481cc' if raw_title == 'Resolution time' else '#168354'])
        chart['definition'] = definition
        chart['label_header'] = ('Target result' if raw_title == 'On-time vs late' else
                                 'Response' if raw_title == 'Response coverage' else
                                 'Age' if raw_title == 'Open-case age' else
                                 'Branch' if 'branch' in raw_title.lower() else
                                 'Complaint type' if 'type' in raw_title.lower() or 'categor' in raw_title.lower() else 'Period')
        chart['display_headers'] = [{'No HB response': 'No response yet'}.get(header, header) for header in chart['headers']]
        chart['rows_display'] = chart['rows'][:5]
        chart['accessible_summary'] = '; '.join(f"{row['label']}: " + ', '.join(f"{cell['label']} {cell['value']}" for cell in row['cells']) for row in chart['rows'])
        if definition.get('temporal'):
            measured = [row for row in chart['rows'] if any(cell['value'] not in {'—', '0'} for cell in row['cells'])]
            last = measured[-1] if measured else chart['rows'][-1]
            chart['visible_summary'] = f"{last['label']}: " + ', '.join(f"{cell['label']} {cell['value']}" for cell in last['cells'])
        else:
            chart['visible_summary'] = '; '.join(f"{row['label']}: {', '.join(row['values'])}" for row in chart['rows'][:5])
        sections.append(chart)
    return sections


def present(snapshot, context):
    facts = snapshot.get('management', {})
    metrics = {label: _metric(label, item, snapshot, facts) for label, item in zip(snapshot['summary'], context['metrics'])}
    keys = list(metrics)
    if snapshot['preset'] == 'complaints' and 'Reported' in metrics:
        keys = [key for key in ('Reported', 'Resolved in period', 'Resolved on time (%)', 'Median resolution (hours)') if key in metrics]
    elif snapshot['preset'] == 'cmp_tat':
        keys = [key for key in ('Resolved on time (%)', 'Median resolution (hours)', 'Median HB response (hours)', 'Reopened in period') if key in metrics]
    elif snapshot['preset'] == 'tat':
        preferred = ('Completed actions', 'Completed cases', 'Active cases', 'Stalled cases', 'Within or near target (%)', 'Median TAT (minutes)', 'Disbursed')
        keys = [key for key in preferred if key in metrics] or keys
    headline = [metrics[key] for key in keys[:4]]
    attention = []
    if not facts:
        attention += [{'text': f'{metrics[key]["value"]} {metrics[key]["label"].lower()}.'}
                      for key in ('Over target', 'Stalled cases', 'No target available') if snapshot['summary'].get(key)]
    rated = facts.get('on_time', 0) + facts.get('late', 0)
    if facts.get('late') and snapshot['preset'] != 'cmp_open':
        attention.append({'text': f'{facts["late"]} of {rated} complaints resolved late ({facts["late"] * 100 / rated:.0f}%).'})
    longest = facts.get('longest_resolution_hours')
    if longest is not None and facts.get('resolution_hours') is not None and longest > facts['resolution_hours'] and longest >= 24:
        text = f'Longest resolution: {duration("Median resolution (hours)", longest)}.'
        if facts.get('within_24_hours'):
            text += f' {_count(facts["within_24_hours"])} resolved within 24 hours.'
        attention.append({'text': text})
    if facts.get('late_open'):
        attention.append({'text': f'{_count(facts["late_open"], "open complaint")} {"is" if facts["late_open"] == 1 else "are"} overdue.'})
    if facts.get('no_response'):
        attention.append({'text': f'{_count(facts["no_response"], "open complaint")} {"has" if facts["no_response"] == 1 else "have"} no response yet.'})
    eligibility = ''
    if facts and snapshot['preset'] != 'cmp_open':
        resolved = facts.get('resolved', 0)
        eligibility = (f'{rated} of {resolved} resolved complaints could be rated against a target.' if resolved else
                       'No complaints were resolved during this period.')
        omissions = []
        if facts.get('no_target'):
            omissions.append(f'{facts["no_target"]} without a target')
        missing = max(0, resolved - facts.get('resolution_count', rated + facts.get('no_target', 0)))
        if missing:
            omissions.append(f'{missing} without usable resolution timing or no longer closed')
        if omissions:
            eligibility += ' Excluded: ' + '; '.join(omissions) + '.'
        targets = facts.get('targets_hours', [])
        if targets:
            eligibility += (' Target ' + duration('Median resolution (hours)', targets[0]) if len(targets) == 1 else
                            ' Targets vary: ' + duration('Median resolution (hours)', targets[0]) + ' - ' + duration('Median resolution (hours)', targets[-1])) + '.'
    sections = _prepare_sections(context)
    choices = {
        'complaints': (('Reported vs resolved', 'On-time vs late'), ('Complaint types', 'Complaint categories', 'Complaints by branch')),
        'cmp_tat': (('Resolution time', 'HB response time'), ('Slowest complaint types',)),
        'cmp_open': (('Open-case age', 'Response coverage'), ('Open cases by branch', 'Overdue complaints by type')),
    }
    graph_titles, table_titles = choices.get(snapshot['preset'], ((), ())) if snapshot.get('email_sections') else ((), ())
    by_key = {section['key']: section for section in sections}
    graphs = [by_key[key] for key in graph_titles if key in by_key]
    tables = [by_key[key] for key in table_titles if key in by_key]
    if not graph_titles:
        graphs = [section for section in sections if section['presentation'] == 'chart'][:1]
        tables = [section for section in sections if section not in graphs][:1]
    visible_graphs = []
    for section in graphs:
        measured = any(value is not None and (value != 0 or section['definition'].get('unit') in {'hours', 'days'})
                       for series in section['definition']['datasets'] for value in series['values'])
        if not measured and section['key'] in {'On-time vs late', 'Response coverage', 'Resolution time', 'HB response time'}:
            section['empty_message'] = {
                'On-time vs late': 'No resolved complaints with a recorded target.',
                'Response coverage': 'No open complaints to compare.',
                'Resolution time': 'No resolution times recorded during this period.',
                'HB response time': 'No first responses recorded during this period.',
            }[section['key']]
        if measured or section.get('empty_message'):
            visible_graphs.append(section)
    graphs = visible_graphs
    for table in tables:
        table['rows'] = [row for row in table['rows'] if any(value not in {'0', '—'} for value in row['values'])]
        table['context'] = {'Complaint types': 'Complaints reported in the selected period, by type.',
                            'Complaint categories': 'Complaints reported in the selected period, by type.',
                            'Complaints by branch': 'Complaints reported in the selected period, by branch.',
                            'Open cases by branch': 'Currently open complaints, including older cases.',
                            'Overdue complaints by type': 'Currently open complaints beyond their recorded target, by type.',
                            'Slowest complaint types': 'Typical resolution time by complaint type; at least two complaints are needed to rate a type.'}.get(table['key'], table['context'])
        if table['key'] == 'Slowest complaint types':
            for row in table['rows']:
                n = int(Decimal(row['values'][1]))
                row['values'] = [duration('Median resolution (hours)', row['values'][0].replace(',', '')) if n > 1 else 'Too few to rate', str(n)]
            table['display_headers'] = ['Time', 'Cases']
            if table['rows'] and all(row['values'][0] == 'Too few to rate' for row in table['rows']):
                table['display_headers'] = ['Cases']
                table['context'] = 'Too few to rate: each complaint type has only one measured resolution.'
                for row in table['rows']:
                    row['values'] = row['values'][1:]
        table['single_series'] = len(table['display_headers']) == 1
        for row in table['rows']:
            row['cells'] = [{'label': header, 'value': value} for header, value in zip(table['display_headers'], row['values'])]
        table['rows_display'] = table['rows'][:5]
    tables = [table for table in tables if table['rows']]
    summary = ''
    if facts and snapshot['preset'] == 'complaints':
        summary = _complaint_summary(snapshot, facts)
    elif facts and snapshot['preset'] == 'cmp_open':
        n = facts.get('open', 0)
        summary = f'{_count(n)} {"remains" if n == 1 else "remain"} open'
        summary += ', all overdue.' if n and facts.get('late_open') == n else f'; {facts.get("late_open", 0)} overdue.'
        if facts.get('oldest_open_hours') is not None:
            summary += f' The oldest is {duration("Oldest open (hours)", facts["oldest_open_hours"])} old.'
    previous_period = date_range(facts['previous_from'], facts['previous_to']) if facts.get('previous_from') else ''
    context.update(metrics=list(metrics.values()), headline=headline, headline_width=100 // (len(headline) or 1),
                   attention=attention[:4],
                   graph_sections=graphs[:2], table_sections=tables,
                   graph_pairs=[graphs[i:i + 2] for i in range(0, len(graphs), 2)],
                   table_pairs=[tables[i:i + 2] for i in range(0, len(tables), 2)],
                   top_table=tables[0] if tables else None, summary_sentence=summary, eligibility_note=eligibility,
                   text_sections=sections,
                   report_url='', previous_period=previous_period, remaining=[], remaining_rows=[],
                   exceptions_available=bool(facts), roomy_headline=False, breakdowns=sections)
    context['current_snapshot'] = snapshot['preset'] == 'cmp_open'
    period = snapshot.get('period') or {}
    filters = snapshot.get('applied_filters') or {}
    first, last = period.get('from') or filters.get('date_from'), period.get('to') or filters.get('date_to')
    context['period_short'] = compact_date_range(first, last) if first and last and not context['current_snapshot'] else context['period']
    context['previous_period_short'] = compact_date_range(facts['previous_from'], facts['previous_to']) if previous_period else ''
    # Numeric fallback keeps even cross-year comparisons on one narrow row.
    context['period_tiny'] = (f'{date.fromisoformat(first):%d/%m/%y}-{date.fromisoformat(last):%d/%m/%y}'
                              if first and last and not context['current_snapshot'] else context['period'])
    context['previous_period_tiny'] = (f'{date.fromisoformat(facts["previous_from"]):%d/%m/%y}-{date.fromisoformat(facts["previous_to"]):%d/%m/%y}'
                                     if previous_period else '')
    if previous_period:
        context['comparison_label'] = 'vs ' + previous_period
    if facts.get('comparison_cutoff'):
        cutoff = datetime.fromisoformat(facts['comparison_cutoff'])
        context['notices'] = [*context['notices'], f'Comparisons use matching elapsed time through {cutoff.day} {cutoff:%b %Y, %H:%M} EAT; headline values cover the full selection.']
