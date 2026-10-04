"""Server-owned Portal insights; bucket selections never accept ORM expressions."""
from collections import defaultdict
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.db.models import Prefetch, Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from core.models import JawabuPipelineEvent
from core.services.jawabu_pipeline import current_workflow_state, JAWABU_TERMINAL_STATES
from core.services.jawabu_case360 import calculate_case_tat, _tat_targets

NAIROBI = ZoneInfo('Africa/Nairobi')
STAGES = {'jbl_visit': 'Awaiting visit', 'credit': 'Credit analysis', 'final_review': 'Final review',
          'order': 'Ready for order', 'ordered': 'Ordered', 'deferred': 'On hold',
          'rejected': 'Rejected', 'withdrawn': 'Withdrawn'}


def prepare(preset, supplied, queryset):
    from core.services.portal_reporting import PortalReportingError
    if preset not in {'pipeline', 'outcomes', 'finance'}:
        raise PortalReportingError('Choose Pipeline, Outcomes, or Orders & finance.')
    if not isinstance(supplied, dict):
        raise PortalReportingError('Choose valid report filters.')
    allowed = {'branch', 'county', 'product', 'search', 'stage', 'date_mode', 'month', 'from', 'to',
               'granularity', 'chart_key', 'bucket_key', 'series_key'}
    if set(supplied) - allowed or any(not isinstance(v, (str, int)) or isinstance(v, bool) for v in supplied.values()):
        raise PortalReportingError('Choose valid report filters.')
    filters = {key: str(value).strip() for key, value in supplied.items() if value != ''}
    mode = filters.get('date_mode') or ('custom' if filters.get('from') or filters.get('to') else 'all' if preset == 'pipeline' else 'month')
    if mode not in {'all', 'month', 'custom'}:
        raise PortalReportingError('Choose Any Time, Specific Month, or Custom Range.')
    today = timezone.localtime(timezone.now(), NAIROBI).date()
    period = None
    if mode == 'month':
        try:
            start = parse_date((filters.get('month') or today.strftime('%Y-%m')) + '-01')
        except ValueError:
            start = None
        if start is None:
            raise PortalReportingError('Choose a valid month.')
        end = start.replace(day=monthrange(start.year, start.month)[1])
        # The current month reports through today, matching the existing contract.
        end = min(end, today) if start.year == today.year and start.month == today.month else end
        filters['month'] = start.strftime('%Y-%m')
    elif mode == 'custom':
        try:
            start = parse_date(filters.get('from') or '')
            end = parse_date(filters.get('to') or '')
        except ValueError:
            start = end = None
        if not start or not end or start > end:
            raise PortalReportingError('Choose a valid start and end date.')
    if mode != 'all':
        period = {'from': start.isoformat(), 'to': end.isoformat()}
        filters.update(period)
    else:
        for key in ('from', 'to', 'month'):
            filters.pop(key, None)
    filters['date_mode'] = mode
    grouping = filters.get('granularity', 'month')
    if grouping not in {'day', 'week', 'month', 'year'}:
        raise PortalReportingError('Choose Day, Week, Month or Year.')
    filters['granularity'] = grouping
    choices = {key: list(queryset.exclude(**{field: ''}).order_by(field).values_list(field, flat=True).distinct()[:100])
               for key, field in [('branches', 'branch'), ('counties', 'county'), ('products', 'product__code')]}
    # Null products are not filter choices.
    choices['products'] = [value for value in choices['products'] if value]
    for key in ('branch', 'county'):
        if filters.get(key):
            queryset = queryset.filter(**{key + '__iexact': filters[key]})
    if filters.get('product'):
        queryset = queryset.filter(product__code__iexact=filters['product'])
    if filters.get('search'):
        term = filters['search'][:120]
        match = Q(customer_name__icontains=term)
        reference = term.upper().removeprefix('JBL-')
        if reference.isdigit() and len(reference) <= 19 and int(reference) <= 9223372036854775807:
            match |= Q(case_reference_number=int(reference))
        queryset = queryset.filter(match)
    if filters.get('stage') and filters['stage'] not in STAGES:
        raise PortalReportingError('Choose a valid pipeline stage.')
    return queryset, filters, period, choices


def _day(value):
    if isinstance(value, str):
        value = parse_datetime(value) or parse_date(value)
    if hasattr(value, 'hour'):
        return timezone.localtime(value, NAIROBI).date()
    return value


def _bucket(value, grouping):
    value = _day(value)
    if grouping == 'week':
        value -= timedelta(days=value.weekday())
    return value.isoformat() if grouping in {'day', 'week'} else value.strftime('%Y-%m' if grouping == 'month' else '%Y')


def _percentile(values, percent):
    values = sorted(values)
    position = Decimal(len(values) - 1) * Decimal(str(percent))
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def _bucket_label(key, grouping):
    if grouping == 'year':
        return key
    day = date.fromisoformat(key + '-01' if grouping == 'month' else key)
    return day.strftime('%b %Y') if grouping == 'month' else ('Week of ' if grouping == 'week' else '') + day.strftime('%d %b %Y')


def insights(preset, queryset, filters, period):
    """Return full-scope aggregates and private bucket membership for drill-down."""
    from hb_operations.models import HomeBiogasActionEvent
    from core.services.portal_reporting import PortalReportingError
    now = timezone.now()
    targets = _tat_targets() if preset != 'finance' else {}
    from core.services.business_calendar import active_holiday_dates
    holidays = active_holiday_dates() if preset != 'finance' else set()
    group = filters['granularity']
    charts, membership, measures, cohort = {}, defaultdict(set), defaultdict(dict), set()
    states, totals, counts = defaultdict(int), defaultdict(lambda: Decimal('0')), defaultdict(int)

    def within(value):
        day = _day(value)
        return day is not None and (not period or date.fromisoformat(period['from']) <= day <= date.fromisoformat(period['to']))

    def add(key, title, bucket, label, record, *, value=1, series='Cases', kind='bar', context='', unit='cases'):
        chart = charts.setdefault(key, {'id': key, 'title': title, 'type': kind, 'unit': unit,
                                      'context': context, 'buckets': {}, 'series': {}})
        chart['buckets'][bucket] = label
        values = chart['series'].setdefault(series, defaultdict(lambda: Decimal('0')))
        values[bucket] += Decimal(str(value))
        membership[(key, bucket, series)].add(record.pk)

    events = JawabuPipelineEvent.objects.order_by('occurred_at', 'created_at')
    query = queryset.select_related('product').order_by('pk')
    if preset != 'finance':
        query = query.prefetch_related(Prefetch('pipeline_events', queryset=events, to_attr='_report_events'))
    # Django fetches the prefetched pipeline events per chunk. HB events are
    # fetched once per chunk too, and the immutable target context once per run.
    iterator = iter(query.iterator(chunk_size=200))
    while True:
        batch = []
        for _ in range(200):
            record = next(iterator, None)
            if record is None:
                break
            batch.append(record)
        if not batch:
            break
        hb = defaultdict(list)
        if preset != 'finance':
            for event in HomeBiogasActionEvent.objects.filter(
                action__farmer_id__in=[r.pk for r in batch],
                event_type__in=['order.released_to_hb', 'installation.progressed', 'commissioning.completed'],
            ).select_related('action').order_by('created_at', 'pk'):
                hb[event.action.farmer_id].append(event)
        for record in batch:
            state = current_workflow_state(record)
            if preset == 'pipeline' and (not within(record.created_at) or filters.get('stage') and state != filters['stage']):
                continue
            timing = calculate_case_tat(record, now=now, events=record._report_events, hb_events=hb[record.pk], targets=targets, holidays=holidays) if preset != 'finance' else {}
            completed = [s for s in timing.get('stages', []) if s.get('completed_at') and within(s['completed_at'])]
            facts = [('Visits', record.jbl_visit_date, record.jbl_visit_status, 'visits'),
                     ('Credit decisions', record.credit_decided_at, record.credit_decision, 'credit'),
                     ('Final decisions', record.final_decided_at, record.final_decision, 'final')]
            relevant = [fact for fact in facts if within(fact[1])]
            if preset == 'outcomes' and not (relevant or completed):
                continue
            if preset == 'finance' and not (within(record.requisition_date) or within(record.invoice_date)):
                continue
            cohort.add(record.pk)
            states[state] += 1
            for location in ('branch', 'county'):
                label = getattr(record, location) or 'Not recorded'
                add(location, f'Cases by {location}', label, label, record)
            if preset == 'pipeline':
                add('stages', 'Cases by pipeline stage', state, STAGES.get(state, state), record)
                add('received', 'Cases received over time', _bucket(record.created_at, group), _bucket(record.created_at, group), record, kind='line', context='Received date • current cases in scope')
                if state not in JAWABU_TERMINAL_STATES | {'deferred'}:
                    running = [s for s in timing.get('stages', []) if s.get('running') and s.get('minutes') is not None]
                    minutes = Decimal(running[-1]['minutes']) if running else None
                    age = 'unavailable' if minutes is None else 'under_1' if minutes < 1440 else '1_7' if minutes < 10080 else '7_30' if minutes < 43200 else '30_plus'
                    label = {'unavailable': 'Timing unavailable', 'under_1': 'Under 1 day', '1_7': '1–7 days', '7_30': '7–30 days', '30_plus': '30+ days'}[age]
                    add('age', 'Current-stage backlog age', age, label, record, context='Elapsed days • approved holds excluded')
            elif preset == 'outcomes':
                for series, at, decision, key in relevant:
                    counts[series] += 1
                    bucket = _bucket(at, group)
                    add('activity', 'Visits and decisions over time', bucket, bucket, record, series=series, kind='line', context='Each milestone uses its own recorded date')
                    add(key, {'visits': 'Visit outcomes', 'credit': 'Credit decisions', 'final': 'Final decisions'}[key], decision or 'Not recorded', decision or 'Not recorded', record)
                has_timing = False
                for stage in completed:
                    key, label = stage['key'], stage['label']
                    if stage.get('minutes') is None or not stage.get('started_at') or parse_datetime(stage['started_at']) > parse_datetime(stage['completed_at']):
                        continue
                    has_timing = True
                    hours = Decimal(stage['minutes']) / 60
                    measures[key].setdefault('values', []).append(hours)
                    measures[key]['label'] = label
                    membership[('duration', key, 'Median')].add(record.pk)
                    membership[('duration', key, 'P90')].add(record.pk)
                    if stage.get('target_minutes') and Decimal(stage['target_minutes']) > 0:
                        outcome = 'Late' if hours * 60 > Decimal(stage['target_minutes']) else 'On time'
                        add('sla', 'Completed stages against target', key, label, record, series=outcome, context='Completed stages • their recorded targets')
                    else:
                        counts['Target unavailable'] += 1
                if not has_timing:
                    counts['Timing unavailable'] += 1
            else:
                for field in ('invoice_amount', 'payment', 'balance_due', 'deposit_paid_hbg', 'system_deposit_paid_jbl'):
                    totals[field] += getattr(record, field) or Decimal('0')
                counts['Invoices'] += bool(record.invoice_number)
                if record.order_number:
                    measures['orders'][record.order_number] = True
                for series, at in [('Orders', record.requisition_date), ('Invoices', record.invoice_date)]:
                    if within(at):
                        bucket = _bucket(at, group)
                        add('activity', 'Order and invoice activity', bucket, bucket, record, series=series, kind='line', context='Case milestones • not unique workbook counts')
                if within(record.invoice_date):
                    bucket = _bucket(record.invoice_date, group)
                    add('invoice_trend', 'Invoice value over time', bucket, bucket, record, value=record.invoice_amount or 0, series='Invoice value', kind='line', unit='KES')
                for location in ('branch', 'county'):
                    label = getattr(record, location) or 'Not recorded'
                    for series, field in [('Invoice value', 'invoice_amount'), ('Recorded payments', 'payment'), ('Outstanding balance', 'balance_due')]:
                        add('finance_' + location, f'Financial comparison by {location}', label, label, record, value=getattr(record, field) or 0, series=series, unit='KES', context='Current recorded values for cases with order/invoice activity in this period')
    if preset == 'outcomes' and measures:
        for key, item in measures.items():
            for series, fraction in [('Median', '.5'), ('P90', '.9')]:
                chart = charts.setdefault('duration', {'id': 'duration', 'title': 'Completed-stage turnaround', 'type': 'bar', 'unit': 'hours', 'context': 'Elapsed time • approved holds excluded • completed in the selected period', 'buckets': {}, 'series': {}})
                chart['buckets'][key] = item['label']
                chart['series'].setdefault(series, {})[key] = _percentile(item['values'], fraction)
                chart.setdefault('sample_counts', {})[key] = len(item['values'])
    output = []
    expected = {'pipeline': [('stages', 'Cases by pipeline stage'), ('received', 'Cases received over time'), ('age', 'Current-stage backlog age'), ('branch', 'Cases by branch'), ('county', 'Cases by county')],
                'outcomes': [('activity', 'Visits and decisions over time'), ('visits', 'Visit outcomes'), ('credit', 'Credit decisions'), ('final', 'Final decisions'), ('duration', 'Completed-stage turnaround'), ('sla', 'Completed stages against target'), ('branch', 'Cases by branch'), ('county', 'Cases by county')],
                'finance': [('activity', 'Order and invoice activity'), ('invoice_trend', 'Invoice value over time'), ('finance_branch', 'Financial comparison by branch'), ('finance_county', 'Financial comparison by county')]}
    for key, title in expected[preset]:
        chart = charts.get(key) or {'id': key, 'title': title, 'type': 'bar', 'unit': 'hours' if key == 'duration' else 'KES' if key.startswith('finance_') or key == 'invoice_trend' else 'cases', 'context': '', 'buckets': {}, 'series': {}}
        bucket_labels = chart.pop('buckets')
        buckets = sorted(bucket_labels)
        # Full labels remain in the payload; chart tick shortening is presentation only.
        labels = [bucket_labels[b] for b in buckets]
        if chart['type'] == 'line':
            labels = [_bucket_label(b, group) for b in buckets]
        if key == 'age':
            names = {'under_1': 'Under 1 day', '1_7': '1–7 days', '7_30': '7–30 days', '30_plus': '30+ days', 'unavailable': 'Timing unavailable'}
            buckets.sort(key=lambda b: list(names).index(b))
            labels = [names[b] for b in buckets]
        series = chart.pop('series')
        chart.update(bucket_keys=buckets, labels=labels, datasets=[{'key': name, 'label': name, 'values': [str(values.get(b, 0)) for b in buckets]} for name, values in series.items()])
        chart['values'] = chart['datasets'][0]['values'] if chart['datasets'] else []
        output.append(chart)
    full_count = len(cohort)
    selection = filters.get('chart_key')
    if selection:
        token = (selection, filters.get('bucket_key', ''), filters.get('series_key', ''))
        valid = any(c['id'] == token[0] and token[1] in c['bucket_keys'] and any(d['key'] == token[2] for d in c['datasets']) for c in output)
        if not valid:
            raise PortalReportingError('That chart selection is unavailable. Clear the selection and try again.')
        cohort &= membership[token]
    elif filters.get('bucket_key') or filters.get('series_key'):
        raise PortalReportingError('Choose a valid chart selection.')
    if preset == 'pipeline':
        summary = {'Cases in scope': full_count, 'Awaiting visit': states['jbl_visit'], 'Credit analysis': states['credit'], 'Ready for order': states['order']}
    elif preset == 'outcomes':
        summary = {'Cases with activity': full_count, **{key: counts[key] for key in ('Visits', 'Credit decisions', 'Final decisions')},
                   'Cases without timing': counts['Timing unavailable'], 'Stages without target': counts['Target unavailable']}
    else:
        summary = {'Official orders': len(measures['orders']), 'Invoices': counts['Invoices'], 'Invoice amount': str(totals['invoice_amount']), 'Recorded payments': str(totals['payment']), 'Outstanding balance': str(totals['balance_due']), 'HBG deposit': str(totals['deposit_paid_hbg']), 'LGF balance': str(totals['system_deposit_paid_jbl'])}
    return queryset.filter(pk__in=cohort), output, summary
