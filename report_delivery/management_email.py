"""Decision-first presentation over frozen facts; no queries or disclosure expansion."""
from datetime import date, datetime
from decimal import Decimal
from urllib.parse import urlencode, urlsplit

from django.conf import settings


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


def report_link(snapshot, extra=None):
    """Ordinary app navigation only. No signed download or authentication token."""
    base = str(getattr(settings, 'APP_BASE_URL', '') or '').rstrip('/')
    parsed = urlsplit(base)
    if parsed.scheme not in {'https', 'http'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        return ''
    preset = snapshot['preset']
    if preset not in {'complaints', 'cmp_tat', 'cmp_open', 'tat'}:
        return base + '/portal/s/reports/'
    filters = snapshot.get('applied_filters', {})
    params = {'view': 'reports'}
    # Only filters understood by the report; never search text, identity or credentials.
    for key in ('branch', 'category', 'status', 'date_from', 'date_to', 'date_basis', 'group_id'):
        if filters.get(key):
            params[key] = filters[key]
    params.update(extra or {})
    if params.get('date_mode') == 'all':
        params.pop('date_from', None)
        params.pop('date_to', None)
    if preset == 'tat':
        params['report_view'] = filters.get('view', 'performance')
        if filters.get('group'):
            params['group_id'] = filters['group']
        if filters.get('product'):
            params['product'] = filters['product']
        return base + '/tat-tracker/?' + urlencode(params)
    return base + '/complaints/?' + urlencode(params)


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
            if n is not None:
                item['note'] = f'n={n}' + (' · low volume' if n < 5 else '')
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
    verdict = '; '.join(f'{item["label"]}: {item["value"]}' for item in headline[:3]) + '.' if headline else 'No cases match this report.'
    attention = []
    if not facts:
        for key in ('Over target', 'Stalled cases', 'No target available'):
            if snapshot['summary'].get(key):
                attention.append({'text': f'{metrics[key]["value"]} {metrics[key]["label"].lower()}.', 'params': {}})
    if facts and snapshot['preset'] != 'cmp_open':
        count = facts.get('on_time', 0) + facts.get('late', 0)
        resolved = facts.get('resolved', 0)
        verdict = f'{resolved} complaint{"s" if resolved != 1 else ""} resolved; '
        verdict += f'{facts.get("on_time", 0)} of {count} measured resolutions within target' if count else 'no measured resolutions with a target'
        if facts.get('previous_target_count') is not None and not facts.get('comparison_cutoff'):
            verdict += f' (previously {facts["previous_on_time"]} of {facts["previous_target_count"]})'
        verdict += '.'
        if facts.get('comparison_cutoff'):
            verdict += f' For equal elapsed time: {facts["comparison_on_time"]} of {facts["comparison_target_count"]} within target, previously {facts["previous_on_time"]} of {facts["previous_target_count"]}.'
        if 'Median resolution (hours)' in metrics and facts.get('resolution_hours') is not None:
            item = metrics['Median resolution (hours)']
            verdict += f' Median resolution {item["value"]}; {item["target"].lower()}.'
        if facts.get('resolution_count', 0) < 5:
            verdict += f' n={facts.get("resolution_count", 0)} · low volume.'
        if facts.get('late'):
            attention.append({'text': f'{facts["late"]} of {count} measured resolutions late ({facts["late"] * 100 / count:.0f}%).', 'params': {'metric': 'late', 'date_basis': 'resolved'}})
        if facts.get('no_target'):
            attention.append({'text': f'{facts["no_target"]} resolved complaint(s) have no target; excluded from the on-time rate.', 'params': {}})
    elif facts:
        verdict = f'{facts.get("open", 0)} complaints currently open; {facts.get("late_open", 0)} beyond their recorded target.'
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
                row['values'] = [duration('Median resolution (hours)', row['values'][0].replace(',', '')) if n > 1 else 'n/a (low volume)', f'n={n}' + (' · low volume' if n < 5 else '')]
            table['display_headers'] = ['Median', 'Sample']
            if table['rows']:
                if table['rows'][0]['values'][0] != 'n/a (low volume)':
                    attention.insert(1, {'text': f'Longest median resolution: {table["rows"][0]["label"]} · {table["rows"][0]["values"][0]}.', 'params': {'category': table['rows'][0]['label'], 'metric': 'resolution', 'date_basis': 'resolved'}})
        table['rows_display'] = table['rows']
        if not table['rows']:
            table = None
    for item in attention:
        item['url'] = report_link(snapshot, item.pop('params'))
    previous_period = date_range(facts['previous_from'], facts['previous_to']) if facts.get('previous_from') else ''
    context.update(metrics=list(metrics.values()), headline=headline, headline_rows=[headline], headline_width=100 // (len(headline) or 1),
                   verdict=verdict, attention=attention[:4], overview_graph=graph, top_table=table,
                   report_url=report_link(snapshot), previous_period=previous_period,
                   remaining=[], remaining_rows=[], exceptions_available=bool(facts),
                   roomy_headline=any(len(item['value']) > 12 for item in headline))
    if previous_period:
        context['comparison_label'] = 'vs ' + previous_period
    if facts.get('comparison_cutoff'):
        cutoff = datetime.fromisoformat(facts['comparison_cutoff'])
        context['notices'] = [*context['notices'], f'Comparisons cover equal elapsed time through {cutoff.day} {cutoff:%b %Y, %H:%M} EAT; headline values cover the full selection.']
