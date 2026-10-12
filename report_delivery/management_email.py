"""Decision-first presentation over frozen facts; no queries or disclosure expansion."""
from datetime import date, datetime
from decimal import Decimal


# None means volume, not a judgement about whether more work is good or bad.
HIGHER_IS_BETTER = {
    'Resolved in period': True, 'Resolved': True, 'Completed actions': True,
    'Resolved on time (%)': True, 'Within or near target (%)': True,
    'Median resolution (hours)': False, 'Median HB response (hours)': False,
    'Median TAT (minutes)': False, 'Reopened in period': False,
    'Over target': False, 'Stalled cases': False,
}


def date_range(first, last):
    a, b = date.fromisoformat(str(first)[:10]), date.fromisoformat(str(last)[:10])
    if a == b:
        return f'{a.day} {a:%b %Y}'
    left = f'{a.day} {a:%b}'
    if a.year != b.year:
        left += f' {a.year}'
    return f'{left} - {b.day} {b:%b %Y}'


def duration(label, value):
    if value is None:
        return '—'
    number = Decimal(str(value))
    if not number.is_finite() or number < 0:
        return '—'
    if 'resolution' in label.lower() or label == 'Oldest open (hours)':
        number /= 24
        return '<0.1 days' if 0 < number < Decimal('.1') else f'{number:,.1f} days'
    if label.endswith(' (minutes)'):
        number /= 60
    return '<0.1 hours' if 0 < number < Decimal('.1') else f'{number:,.1f} hours'


def present(snapshot, context):
    metrics = {label: dict(item) for label, item in zip(snapshot['summary'], context['metrics'])}
    facts = snapshot.get('management', {})
    for label, item in metrics.items():
        if '(KES)' in label and snapshot['summary'][label] is not None:
            number = Decimal(str(snapshot['summary'][label]))
            if number.is_finite() and abs(number) >= 1000000:
                item['exact_value'] = item['value']
                scale, suffix = (Decimal(1000000000), 'B') if abs(number) >= 1000000000 else (Decimal(1000000), 'M')
                item['value'] = f'{number / scale:,.1f}{suffix}'
        if label.endswith((' (hours)', ' (minutes)')):
            item['value'] = duration(label, snapshot['summary'][label])
        comparison = snapshot.get('comparison', {}).get('metrics', {}).get(label, {})
        paired = comparison.get('paired_values')
        item.update(ink='#243244', background='#ffffff', accent='#2e3480', previous='Not available', change='No comparison', status='')
        if paired and paired.get('previous') is not None and paired.get('current') is not None:
            previous, current = Decimal(str(paired['previous'])), Decimal(str(paired['current']))
            item['previous'] = (duration(label, previous) if label.endswith((' (hours)', ' (minutes)')) else
                                f'{previous:,.1f}%' if label.endswith(' (%)') else f'{previous:,.0f}')
            diff = current - previous
            arrow = '▲' if diff > 0 else '▼' if diff < 0 else '•'
            if label.endswith(' (%)'):
                magnitude = f'{abs(diff):,.1f} pts'
            elif label.endswith((' (hours)', ' (minutes)')):
                magnitude = duration(label, abs(diff))
            else:
                magnitude = f'{abs(diff):,.0f}'
            direction = HIGHER_IS_BETTER.get(label)
            item['status'] = 'Unchanged' if not diff else 'Change' if direction is None else 'Better' if (diff > 0) == direction else 'Worse'
            item['change'] = f'{arrow} {magnitude} · {item["status"]}'
            item['ink'] = '#17643b' if item['status'] == 'Better' else '#b42318' if item['status'] == 'Worse' else '#243244'
            item['comparison_current'] = duration(label, current) if label.endswith((' (hours)', ' (minutes)')) else str(current)
            if facts.get('comparison_cutoff'):
                item['comparison_scope'] = f'Change uses {item["comparison_current"]} for the matching elapsed window.'
            item['comparison'] = {'text': f'Previous: {item["previous"]} · {item["change"]}', 'tone': 'muted'}
        if label in {'Median resolution (hours)', 'Median HB response (hours)', 'Resolved on time (%)'}:
            n = facts.get('resolution_count' if 'resolution' in label.lower() else 'response_count')
            if label == 'Resolved on time (%)':
                n = facts.get('on_time', 0) + facts.get('late', 0) if facts else None
            if n:
                item['note'] = f'Based on {n} complaint' + ('s' if n != 1 else '')
        item['target'] = ''
        if label == 'Median resolution (hours)':
            targets = facts.get('targets_hours', [])
            item['target'] = ('Target ' + duration(label, targets[0]) if len(targets) == 1 else
                              'Targets vary: ' + duration(label, targets[0]) + ' - ' + duration(label, targets[-1]) if targets else 'Target not available')
        # A measured zero success rate is never shown as a positive result.
        if label == 'Resolved on time (%)' and snapshot['summary'][label] == 0 and item['status'] != 'Better':
            item['ink'] = '#b42318'
            if not item['status']:
                item['change'] = '! None within target · no comparison'

    keys = list(metrics)
    if snapshot['preset'] == 'complaints' and 'Reported' in metrics:
        keys = [key for key in ('Reported', 'Resolved in period', 'Resolved on time (%)', 'Median resolution (hours)') if key in metrics]
    elif snapshot['preset'] == 'tat':
        preferred = ('Completed actions', 'Completed cases', 'Active cases', 'Stalled cases', 'Within or near target (%)', 'Median TAT (minutes)', 'Disbursed')
        keys = [key for key in preferred if key in metrics] or keys
    headline = [metrics[key] for key in keys[:4]]
    attention = []
    if not facts:
        for key in ('Over target', 'Stalled cases', 'No target available'):
            if snapshot['summary'].get(key):
                attention.append({'text': f'{metrics[key]["value"]} {metrics[key]["label"].lower()}.', 'params': {}})
    if facts and snapshot['preset'] != 'cmp_open':
        count = facts.get('on_time', 0) + facts.get('late', 0)
        if facts.get('late'):
            attention.append({'text': f'{facts["late"]} of {count} complaints resolved late ({facts["late"] * 100 / count:.0f}%).', 'params': {'metric': 'late', 'date_basis': 'resolved'}})
        if facts.get('no_target'):
            attention.append({'text': f'{facts["no_target"]} resolved complaint(s) have no target; excluded from the on-time rate.', 'params': {}})
    if facts.get('late_open'):
        attention.append({'text': f'{facts["late_open"]} open complaint(s) are past target now. Review open cases.', 'params': {'date_mode': 'all', 'status': 'Open'}})
    if facts.get('no_response'):
        attention.append({'text': f'{facts["no_response"]} open complaint(s) have no HB response.', 'params': {'date_mode': 'all'}})
    if facts.get('open') and snapshot['preset'] == 'complaints':
        attention.append({'text': f'{facts["open"]} complaints currently open, including cases from earlier periods.', 'params': {'date_mode': 'all', 'status': 'Open'}})

    charts = context['breakdowns']
    for chart in charts:
        labels = []
        for row in chart['rows']:
            try:
                day = datetime.strptime(str(row['label']), '%d-%m-%y')
                row['label'] = f'{day.day} {day:%b %Y}'
            except ValueError:
                pass
            labels.append(row['label'])
        chart['definition'] = {**chart['definition'], 'labels': labels}
    graph = next((chart for chart in charts if chart['presentation'] == 'chart'
                  and any(value is not None for series in chart['definition']['datasets'] for value in series.get('values', []))), None)
    if graph:
        definition = graph['definition']
        if graph['title'] == 'Resolution time':
            graph['definition'] = {**definition, 'unit': 'days', 'datasets': [
                {**series, 'label': 'Days', 'values': [float(Decimal(str(value)) / 24) if value is not None else None for value in series['values']]}
                for series in definition['datasets']]}
            graph['context'] = graph['context'].replace('hours', 'days')
            for row in graph['rows']:
                row['cells'] = [{'label': 'Median resolution', 'value': duration('Median resolution (hours)', value.replace(',', '')) if value != '—' else '—'} for value in row['values']]
                row['values'] = [cell['value'] for cell in row['cells']]
        graph['accessible_summary'] = '; '.join(f"{row['label']}: " + ', '.join(f"{cell['label']} {cell['value']}" for cell in row['cells']) for row in graph['rows'])
        graph['rows_display'] = graph['rows'][:5]
    table = next((chart for chart in charts if chart['title'] in {'Slowest complaint types', 'Complaint types', 'Open cases by branch'}), None)
    if table is None:
        table = next((chart for chart in charts if chart is not graph and chart['title'] not in {'Resolution targets', 'Open-case age'}), None)
    if table is None and graph is None:
        table = next(iter(charts), None)
    if table:
        table = {**table, 'rows': [row.copy() for row in table['rows'] if any(value not in {'0', '—'} for value in row['values'])][:5]}
        table['context'] = 'Up to five entries; full detail in Excel.'
        if table['title'] == 'Slowest complaint types':
            for row in table['rows']:
                n = int(Decimal(row['values'][1]))
                row['values'] = [duration('Median resolution (hours)', row['values'][0].replace(',', '')) if n > 1 else 'Not enough complaints', str(n)]
            table['display_headers'] = ['Time', 'Cases']
            if table['rows']:
                if table['rows'][0]['values'][0] != 'Not enough complaints':
                    attention.insert(1, {'text': f'Longest median resolution: {table["rows"][0]["label"]} · {table["rows"][0]["values"][0]}.', 'params': {'category': table['rows'][0]['label'], 'metric': 'resolution', 'date_basis': 'resolved'}})
        table['rows_display'] = table['rows']
        if not table['rows']:
            table = None
    for item in attention:
        item.pop('params', None)
    previous_period = date_range(facts['previous_from'], facts['previous_to']) if facts.get('previous_from') else ''
    context.update(metrics=list(metrics.values()), headline=headline, headline_rows=[headline], headline_width=100 // (len(headline) or 1),
                   attention=attention[:4], overview_graph=graph, top_table=table,
                   report_url='', previous_period=previous_period,
                   remaining=[], remaining_rows=[], exceptions_available=bool(facts),
                   roomy_headline=any(len(item['value']) > 12 for item in headline))
    if previous_period:
        context['comparison_label'] = 'vs ' + previous_period
    if facts.get('comparison_cutoff'):
        cutoff = datetime.fromisoformat(facts['comparison_cutoff'])
        context['notices'] = [*context['notices'], f'Comparisons cover equal elapsed time through {cutoff.day} {cutoff:%b %Y, %H:%M} EAT; headline values cover the full selection.']
