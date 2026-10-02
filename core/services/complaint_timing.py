"""Read-only complaint timing facts shared by reports and case presentation.

Targets use elapsed calendar time. History reads are batched, never one query
per complaint. No current staff grants are used to guess historical HB roles.
"""
from collections import defaultdict
from itertools import islice
from statistics import median
from zoneinfo import ZoneInfo

from django.utils import timezone

from core.models import CaseUpdate, ComplianceAuditEvent

NAIROBI = ZoneInfo('Africa/Nairobi')
AGE_BUCKETS = (
    ('under_3', 'Under 3 days', 0, 3),
    ('3_7', '3–7 days', 3, 8),
    ('8_14', '8–14 days', 8, 15),
    ('over_14', 'Over 14 days', 15, None),
)


def case_timing(control, case, *, now=None):
    now = now or timezone.now()
    start = control.sla_started_at or case.timestamp or case.created_at
    closed = case.complaint_status == 'Closed'
    end = case.date_resolved if closed else now
    seconds = (end - start).total_seconds() if start and end else None
    if seconds is not None and (seconds < 0 or end > now):
        seconds = None
    target = control.sla_target_hours
    resolution = seconds / 3600 if closed and seconds is not None else None
    return {
        'elapsed_seconds': seconds,
        'resolution_hours': resolution,
        'on_time': (seconds <= target * 3600) if closed and seconds is not None and target and target > 0 else None,
    }


def hydrate_timing(cases, *, now=None):
    """Attach facts to a bounded list, with two history queries per batch."""
    now = now or timezone.now()
    updates = list(CaseUpdate.objects.filter(parsed_message_id__in=[case.pk for case in cases])
                   .order_by('created_at', 'pk').values('id', 'parsed_message_id', 'created_at',
                       'old_status', 'new_status', 'source', 'client_request_id'))
    evidence = dict(ComplianceAuditEvent.objects.filter(
        workflow='complaint_cases', source_model='CaseUpdate',
        source_event_id__in=[str(item['id']) for item in updates],
    ).values_list('source_event_id', 'metadata'))
    histories = defaultdict(list)
    for item in updates:
        histories[item['parsed_message_id']].append(item)
    for case in cases:
        start = case.complaint_control.sla_started_at or case.timestamp or case.created_at
        facts = case_timing(case.complaint_control, case, now=now)
        closures, reopened, responses, seen = [], [], [], set()
        for item in histories[case.pk]:
            stamp = item['created_at']
            if not start or stamp < start or stamp > now:
                continue
            key = item['client_request_id'] or str(item['id'])
            if key in seen:
                continue
            seen.add(key)
            closing = item['new_status'] == 'Closed' and item['old_status'] != 'Closed' and item['source'] != 'mini_app_comment'
            if closing:
                closures.append(stamp)
            if item['old_status'] == 'Closed' and item['new_status'] == 'Reopened':
                reopened.append(stamp)
            metadata = evidence.get(str(item['id']), {}) or {}
            hb = metadata.get('actor_affiliation') == 'HB' or (
                'actor_affiliation' not in metadata and metadata.get('actor_role') == 'HB_STAFF')
            if hb and (closing or item['source'] == 'mini_app_comment'):
                responses.append(stamp)
        # Old imported cases may have a final date but no state history.
        if not closures and case.complaint_status == 'Closed' and facts['resolution_hours'] is not None:
            closures.append(case.date_resolved)
        facts.update({
            'reported_at': case.timestamp or case.created_at, 'resolved_at': case.date_resolved,
            'closures': closures, 'reopened': reopened,
            'first_resolution_hours': (closures[0] - start).total_seconds() / 3600 if closures else None,
            'response_at': responses[0] if responses else None,
            'hb_response_hours': (responses[0] - start).total_seconds() / 3600 if responses else None,
            'age_bucket': next((key for key, _label, low, high in AGE_BUCKETS
                if facts['elapsed_seconds'] is not None and facts['elapsed_seconds'] >= low * 86400
                and (high is None or facts['elapsed_seconds'] < high * 86400)), None),
        })
        case.complaint_timing = facts
    return cases


def timed_cases(queryset, *, now=None):
    now = now or timezone.now()
    iterator = (queryset if queryset.ordered else queryset.order_by('pk')).iterator(chunk_size=500)
    while batch := list(islice(iterator, 500)):
        yield from hydrate_timing(batch, now=now)


def median_hours(values):
    values = [value for value in values if value is not None]
    return round(median(values), 2) if values else None


def period_bucket(stamp, granularity):
    stamp = stamp.astimezone(NAIROBI)
    if granularity == 'week':
        from datetime import timedelta
        stamp -= timedelta(days=stamp.weekday())
    return stamp.strftime({'day': '%Y-%m-%d', 'week': '%Y-%m-%d', 'month': '%Y-%m', 'year': '%Y'}[granularity])


def matches_timing(case, filters, date_from, date_to):
    facts = case.complaint_timing
    metric = filters.get('metric') or ''
    basis = filters.get('date_basis') or 'reported'
    if metric == 'open_age':
        if case.complaint_status == 'Closed' or facts['age_bucket'] != filters.get('metric_value'):
            return False
    if metric in {'resolution', 'on_time', 'late'} and facts['resolution_hours'] is None:
        return False
    if metric in {'on_time', 'late'} and facts['on_time'] is not (metric == 'on_time'):
        return False
    if metric == 'hb_response' and facts['hb_response_hours'] is None:
        return False
    dates = {
        'reported': [facts['reported_at']], 'resolved': [facts['resolved_at']] if case.complaint_status == 'Closed' else [],
        'response': [facts['response_at']], 'closures': facts['closures'], 'reopened': facts['reopened'],
    }[basis]
    return any(stamp is not None and (date_from is None or stamp >= date_from)
               and (date_to is None or stamp <= date_to) for stamp in dates)


def timing_summary(cases, *, date_from=None, date_to=None, granularity='month', now=None):
    """Aggregate no-PII chart payloads from shared, already-filtered facts."""
    now = now or timezone.now()
    def within(stamp):
        return stamp is not None and stamp <= now and (date_from is None or stamp >= date_from) and (date_to is None or stamp <= date_to)
    activity, resolutions, responses, reopenings = defaultdict(lambda: {'received': 0, 'resolved': 0}), defaultdict(list), defaultdict(list), defaultdict(set)
    categories, ages = defaultdict(list), {key: 0 for key, *_ in AGE_BUCKETS}
    on_time = late = resolution_excluded = response_excluded = age_excluded = 0
    resolution_values, response_values = [], []
    for case in cases:
        facts = case.complaint_timing
        if within(facts['reported_at']):
            activity[period_bucket(facts['reported_at'], granularity)]['received'] += 1
            if case.complaint_status != 'Closed':
                if facts['age_bucket']:
                    ages[facts['age_bucket']] += 1
                else:
                    age_excluded += 1
            if facts['hb_response_hours'] is None:
                response_excluded += 1
        for stamp in facts['closures']:
            if within(stamp):
                activity[period_bucket(stamp, granularity)]['resolved'] += 1
        for stamp in facts['reopened']:
            if within(stamp):
                reopenings[period_bucket(stamp, granularity)].add(case.pk)
        if case.complaint_status == 'Closed' and within(facts['resolved_at']):
            value = facts['resolution_hours']
            if value is None:
                resolution_excluded += 1
            else:
                resolution_values.append(value)
                resolutions[period_bucket(facts['resolved_at'], granularity)].append(value)
                label = case.complaint_control.category.label if case.complaint_control.category_id else case.complaint_category or 'Not provided'
                categories[label].append(value)
                if facts['on_time'] is True:
                    on_time += 1
                elif facts['on_time'] is False:
                    late += 1
        if within(facts['response_at']) and facts['hb_response_hours'] is not None:
            response_values.append(facts['hb_response_hours'])
            responses[period_bucket(facts['response_at'], granularity)].append(facts['hb_response_hours'])
        if case.complaint_status == 'Closed' and facts['resolved_at'] is None:
            resolution_excluded += 1
    def trend(rows):
        return [{'label': label, 'hours': median_hours(values), 'count': len(values)} for label, values in sorted(rows.items())]
    return {
        'calculated_at': now.isoformat(),
        'timing': {
            'median_resolution_hours': median_hours(resolution_values), 'resolution_count': len(resolution_values),
            'resolution_excluded': resolution_excluded, 'median_response_hours': median_hours(response_values),
            'response_count': len(response_values), 'response_unavailable': response_excluded,
            'on_time': on_time, 'late': late,
            'on_time_percent': round(on_time * 100 / (on_time + late), 1) if on_time + late else None,
            'target_unavailable': len(resolution_values) - on_time - late, 'age_unavailable': age_excluded,
        },
        'activity': [{'label': label, **counts} for label, counts in sorted(activity.items())],
        'open_age': [{'key': key, 'label': label, 'count': ages[key]} for key, label, *_ in AGE_BUCKETS],
        'resolution_trend': trend(resolutions), 'response_trend': trend(responses),
        'resolution_by_category': [{'label': label, 'hours': median_hours(values), 'count': len(values)}
            for label, values in sorted(categories.items(), key=lambda item: (-median(item[1]), item[0]))],
        'reopenings': [{'label': label, 'count': len(ids)} for label, ids in sorted(reopenings.items())],
    }
