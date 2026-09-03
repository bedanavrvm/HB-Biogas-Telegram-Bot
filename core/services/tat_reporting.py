"""Scoped, read-only TAT reporting and audited exports."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_CEILING
from io import BytesIO
from math import ceil

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.models import (
    AccessGrant, GroupSheetConfiguration, TatTrackerCase, WorkflowTatDailyMetric,
    WorkflowTatMetricRebuildRequest, TatResponsibilityAssignment,
)
from core.services.tat_presentation import presentation_settings
from core.services.tat_tracker import (
    TAT_COMPLETED_STATUSES, calculated_tat_seconds, minutes_between, next_action,
    overall_tat_end, parse_iso_datetime, product_for_case, stage_completed_at,
    stage_target_minutes_for_case, stage_tat_minutes,
)
from core.services.workflow_data_mode import operational_tat_cases


SORT_FIELDS = {
    'case_id', 'client_name', 'group', 'branch', 'product_label', 'status', 'current_stage',
    'responsible_role', 'created_at', 'finished_at', 'elapsed_minutes',
    'target_minutes', 'variance_minutes', 'sla_state',
}
TERMINAL = set(TAT_COMPLETED_STATUSES)


def _scope_query(actor):
    if actor.is_active and actor.is_superuser:
        return Q()
    grants = AccessGrant.objects.filter(user=actor, workflow='tat_tracker', active=True).select_related('group_configuration')
    query = Q(pk__in=[])
    for grant in grants:
        part = Q()
        scoped = False
        if grant.group_configuration_id:
            part &= Q(group_id=str(grant.group_configuration.group_id))
            scoped = True
        if grant.branch:
            part &= Q(branch__iexact=grant.branch)
            scoped = True
        if grant.product:
            part &= Q(product_key__iexact=grant.product)
            scoped = True
        if not scoped:
            return Q()
        query |= part
    return query


def scoped_cases(actor):
    return operational_tat_cases(
        TatTrackerCase.objects.filter(is_deleted=False).filter(_scope_query(actor))
    ).select_related('product', 'product_version').prefetch_related('events')


def _parse_date(value, *, default):
    try:
        return date.fromisoformat(str(value or ''))
    except ValueError:
        return default


def _filters(payload):
    today = timezone.localdate()
    date_to = _parse_date(payload.get('date_to'), default=today)
    date_from = _parse_date(payload.get('date_from'), default=date_to - timedelta(days=29))
    if date_from > date_to:
        raise ValueError('Start date must be on or before end date.')
    if (date_to - date_from).days > 3652:
        raise ValueError('Choose a reporting period of 10 years or less.')
    granularity = str(payload.get('granularity') or 'month').lower()
    if granularity not in {'day', 'week', 'month', 'year'}:
        raise ValueError('Choose Day, Week, Month, or Year grouping.')
    bucket_estimate = {
        'day': (date_to - date_from).days + 1,
        'week': ceil(((date_to - date_from).days + 1) / 7),
        'month': (date_to.year - date_from.year) * 12 + date_to.month - date_from.month + 1,
        'year': date_to.year - date_from.year + 1,
    }[granularity]
    if bucket_estimate > 366:
        raise ValueError('This grouping would create more than 366 chart points. Choose a coarser time grouping.')
    return {
        'view': 'performance' if payload.get('view') == 'performance' else 'current',
        'group': str(payload.get('group') or '').strip(),
        'branch': str(payload.get('branch') or '').strip(),
        'product': str(payload.get('product') or '').strip(),
        'stage': str(payload.get('stage') or '').strip(),
        'role': str(payload.get('role') or '').strip().upper(),
        'status': str(payload.get('status') or '').strip(),
        'sla_state': str(payload.get('sla_state') or '').strip(),
        'search': str(payload.get('search') or '').strip(),
        'date_from': date_from, 'date_to': date_to, 'granularity': granularity,
    }


def _filtered_cases(actor, filters):
    qs = scoped_cases(actor)
    if filters['group']:
        qs = qs.filter(group_id=filters['group'])
    if filters['branch']:
        qs = qs.filter(branch__iexact=filters['branch'])
    if filters['product']:
        qs = qs.filter(product_key__iexact=filters['product'])
    if filters['status']:
        qs = qs.filter(status__iexact=filters['status'])
    if filters['search']:
        term = filters['search']
        qs = qs.filter(Q(case_id__icontains=term) | Q(client_name__icontains=term) | Q(branch__icontains=term) | Q(product_label__icontains=term))
    return list(qs)


def _case_target(case, product, stage=None, *, config=None):
    if stage is not None:
        config = config or GroupSheetConfiguration.objects.filter(group_id=case.group_id).first()
        return stage_target_minutes_for_case(case, (config.workflow if config else {}), product, stage)
    values = []
    for item in (case.stage_target_snapshots or {}).values():
        try:
            value = Decimal(str((item or {}).get('target_minutes')))
        except Exception:
            continue
        if value > 0:
            values.append(value)
    return sum(values, Decimal('0')) if values else None


def _case_row(case, *, include_people=False, now=None):
    now = now or timezone.now()
    product = product_for_case(case)
    config = GroupSheetConfiguration.objects.filter(group_id=case.group_id).only('display_name', 'workflow').first()
    stage = next_action(case)
    finished_at = overall_tat_end(case, now=case.updated_at) if case.status in TERMINAL else None
    if stage:
        elapsed = stage_tat_minutes(case, stage, now=now)
        target = _case_target(case, product, stage, config=config)
        role = stage.role
        stage_label = stage.label
    else:
        seconds = calculated_tat_seconds(case, now=finished_at or now)
        elapsed = Decimal(seconds) / Decimal('60') if seconds is not None else None
        target = _case_target(case, product, config=config)
        role = ''
        stage_label = case.current_stage or ('Finished' if case.status in TERMINAL else '')
    variance = elapsed - target if elapsed is not None and target is not None else None
    if target is None or target <= 0 or elapsed is None:
        sla_state = 'target_unavailable'
    elif elapsed > target:
        sla_state = 'overdue'
    else:
        ratio = Decimal(presentation_settings()['near_target_percent']) / Decimal('100')
        sla_state = 'near_target' if elapsed >= target * ratio else 'within_target'
    row = {
        'case_id': case.case_id, 'client_name': case.client_name,
        'group': (config.display_name if config else '') or 'TAT Tracker',
        'branch': case.branch or '', 'product_label': case.product_label or case.product_key,
        'status': case.status, 'current_stage': stage_label, 'responsible_role': role,
        'current_stage_key': stage.key if stage else str(case.current_stage or ''),
        'created_at': case.created_at.isoformat(),
        'finished_at': finished_at.isoformat() if finished_at else '',
        'elapsed_minutes': float(elapsed) if elapsed is not None else None,
        'target_minutes': float(target) if target is not None else None,
        'variance_minutes': float(variance) if variance is not None else None,
        'sla_state': sla_state,
    }
    if include_people:
        if stage:
            assignment = TatResponsibilityAssignment.objects.filter(
                group_configuration__group_id=case.group_id, active=True,
                branch__iexact=case.branch, role__iexact=stage.role,
            ).filter(Q(product_key='') | Q(product_key__iexact=case.product_key)).filter(
                Q(stage_key='') | Q(stage_key=stage.key),
            ).select_related('primary_user').order_by('-stage_key', '-product_key').first()
            if assignment and assignment.primary_user:
                row['responsible_person'] = assignment.primary_user.get_full_name() or assignment.primary_user.get_username()
            else:
                row['responsible_person'] = ''
        else:
            event = next((event for event in case.events.all() if event.stage_key == case.current_stage), None)
            row['responsible_person'] = event.actor_name if event else ''
    return row


def _eligible_rows(actor, filters, *, include_people=False):
    rows = []
    for case in _filtered_cases(actor, filters):
        row = _case_row(case, include_people=include_people)
        if filters['view'] == 'current' and case.status in TERMINAL:
            continue
        if filters['view'] == 'performance':
            if case.status not in TERMINAL or not row['finished_at']:
                continue
            finished_date = datetime.fromisoformat(row['finished_at']).date()
            if not filters['date_from'] <= finished_date <= filters['date_to']:
                continue
        if filters['view'] == 'performance' and (filters['stage'] or filters['role']):
            samples = _stage_samples([case], filters, include_people=include_people)
            if not samples:
                continue
            sample = samples[0]
            row.update(current_stage_key=sample['stage_key'], current_stage=sample['stage'], responsible_role=sample['role'], elapsed_minutes=sample['elapsed_minutes'], target_minutes=sample['target_minutes'], variance_minutes=sample['variance_minutes'], sla_state=sample['sla_state'])
            if include_people:
                row['responsible_person'] = sample['person']
        else:
            if filters['stage'] and filters['stage'].casefold() != str(row['current_stage_key']).casefold():
                continue
            if filters['role'] and row['responsible_role'].upper() != filters['role']:
                continue
        if filters['sla_state'] and row['sla_state'] != filters['sla_state']:
            continue
        rows.append(row)
    return rows


def _stage_samples(cases, filters, *, include_people=False):
    samples = []
    for case in cases:
        try:
            product = product_for_case(case)
        except ValueError:
            continue
        config = GroupSheetConfiguration.objects.filter(group_id=case.group_id).first()
        workflow = config.workflow if config else {}
        for stage in product.stages:
            if filters['stage'] and stage.key.casefold() != filters['stage'].casefold():
                continue
            if filters['role'] and stage.role.upper() != filters['role']:
                continue
            completed = stage_completed_at(case, stage)
            if not completed:
                continue
            completed_date = timezone.localdate(completed)
            if not filters['date_from'] <= completed_date <= filters['date_to']:
                continue
            elapsed = stage_tat_minutes(case, stage, now=completed)
            target = stage_target_minutes_for_case(case, workflow, product, stage)
            variance = elapsed - target if elapsed is not None and target is not None else None
            if not target or target <= 0 or elapsed is None:
                sla_state = 'target_unavailable'
            elif elapsed > target:
                sla_state = 'overdue'
            else:
                ratio = Decimal(presentation_settings()['near_target_percent']) / Decimal('100')
                sla_state = 'near_target' if elapsed >= target * ratio else 'within_target'
            event = next((item for item in case.events.all() if item.stage_key == stage.key), None)
            samples.append({
                'case_id': case.case_id, 'stage_key': stage.key, 'stage': stage.label,
                'role': stage.role, 'person': event.actor_name if include_people and event else '',
                'completed_at': completed.isoformat(),
                'elapsed_minutes': float(elapsed) if elapsed is not None else None,
                'target_minutes': float(target) if target is not None else None,
                'variance_minutes': float(variance) if variance is not None else None,
                'sla_state': sla_state,
            })
    return samples


def _percentile(values, percentile):
    values = sorted(Decimal(str(value)) for value in values if value is not None)
    if not values:
        return None
    index = max(0, ceil(len(values) * percentile) - 1)
    return float(values[index].quantize(Decimal('0.01')))


def _bucket_label(value, granularity):
    if granularity == 'day':
        return value.isoformat()
    if granularity == 'week':
        return (value - timedelta(days=value.weekday())).isoformat()
    if granularity == 'year':
        return date(value.year, 1, 1).isoformat()
    return date(value.year, value.month, 1).isoformat()


def report_summary(actor, payload, *, include_people=False):
    filters = _filters(payload)
    all_cases = _filtered_cases(actor, filters)
    rows = _eligible_rows(actor, filters, include_people=include_people)
    scope_cases = list(scoped_cases(actor))
    stages = set(); roles = set()
    for case in scope_cases:
        try:
            for stage in product_for_case(case).stages:
                stages.add((stage.key, stage.label)); roles.add(stage.role)
        except ValueError:
            continue
    group_names = dict(GroupSheetConfiguration.objects.filter(
        group_id__in={case.group_id for case in scope_cases},
    ).values_list('group_id', 'display_name'))
    options = {
        'groups': sorted({
            (case.group_id, group_names.get(case.group_id) or 'TAT Tracker')
            for case in scope_cases
        }),
        'branches': sorted({case.branch for case in scope_cases if case.branch}),
        'products': sorted({(case.product_key, case.product_label or case.product_key) for case in scope_cases}),
        'stages': sorted(stages), 'roles': sorted(role for role in roles if role),
    }
    stage_samples = _stage_samples(all_cases, filters, include_people=include_people) if filters['view'] == 'performance' else []
    by_stage = Counter((item['stage'] for item in stage_samples) if stage_samples else (row['current_stage'] or 'Unassigned' for row in rows))
    by_role = Counter((item['role'] for item in stage_samples) if stage_samples else (row['responsible_role'] or 'Unassigned' for row in rows))
    latest_metrics = WorkflowTatDailyMetric.objects.filter(workflow='tat_tracker').filter(_metric_scope_q(actor))
    latest_metrics = _filter_metric_queryset(latest_metrics, filters)
    latest = latest_metrics.order_by('-metric_date').first()
    scoped_case_ids = scoped_cases(actor).values_list('pk', flat=True)
    scoped_rebuilds = WorkflowTatMetricRebuildRequest.objects.filter(
        Q(case__isnull=True) | Q(case_id__in=scoped_case_ids),
    )
    pending_rebuilds = scoped_rebuilds.filter(status__in=['pending', 'processing']).count()
    failed_rebuilds = scoped_rebuilds.filter(status='failed', attempts__gte=3).count()
    common = {
        'view': filters['view'], 'filters': options,
        'by_stage': [{'label': key, 'count': value} for key, value in by_stage.most_common()],
        'by_role': [{'label': key, 'count': value} for key, value in by_role.most_common()],
        'freshness': {
            'latest_snapshot': latest.metric_date.isoformat() if latest else '',
            'pending_rebuilds': pending_rebuilds,
            'failed_rebuilds': failed_rebuilds,
            'near_target_percent': presentation_settings()['near_target_percent'],
            'presentation_revision': presentation_settings()['revision'],
        },
    }
    if filters['view'] == 'current':
        states = Counter(row['sla_state'] for row in rows)
        common['metrics'] = {
            'active': len(rows), 'near_target': states['near_target'],
            'overdue': states['overdue'],
            'stalled': sum(row['status'] == 'Stalled' for row in rows),
            'target_unavailable': states['target_unavailable'],
        }
        if filters['search'] or filters['status'] or filters['sla_state']:
            common['trend'] = []
            common['trend_notice'] = 'Historical workload is unavailable for text, status, or SLA filters because snapshots do not store case-level details.'
        else:
            daily = WorkflowTatDailyMetric.objects.filter(
                workflow='tat_tracker', metric_grain='current_leaf',
                metric_date__range=(filters['date_from'], filters['date_to']),
            ).filter(_metric_scope_q(actor))
            daily = _filter_metric_queryset(daily, filters)
            daily_totals = defaultdict(lambda: Counter())
            for item in daily:
                daily_totals[item.metric_date]['active'] += item.active_count
                daily_totals[item.metric_date]['near_target'] += item.near_target_count
                daily_totals[item.metric_date]['overdue'] += item.overdue_count
            # Workload is a point-in-time measure. For coarser grouping use
            # the latest available snapshot in each bucket, never a sum of
            # daily balances (which would inflate the apparent queue).
            trend = {}
            for metric_date, values in sorted(daily_totals.items()):
                trend[_bucket_label(metric_date, filters['granularity'])] = values
            common['trend'] = [{'label': key, **dict(value)} for key, value in sorted(trend.items())]
    else:
        terminal_rows = rows
        elapsed = [row['elapsed_minutes'] for row in terminal_rows]
        valid = [row for row in terminal_rows if row['sla_state'] != 'target_unavailable']
        met = sum(row['sla_state'] != 'overdue' for row in valid)
        outcomes = Counter(row['status'] for row in terminal_rows)
        created = sum(filters['date_from'] <= timezone.localdate(case.created_at) <= filters['date_to'] for case in all_cases)
        common['metrics'] = {
            'created': created, 'finished': len(terminal_rows), 'disbursed': outcomes['Disbursed'],
            'rejected': outcomes['Rejected'], 'declined': outcomes['Declined'],
            'sla_met': met, 'sla_sample': len(valid),
            'sla_met_percent': round((met * 100 / len(valid)), 1) if valid else None,
            'median_tat_minutes': _percentile(elapsed, .5), 'p90_tat_minutes': _percentile(elapsed, .9),
            'target_unavailable': len(terminal_rows) - len(valid),
        }
        trend = defaultdict(lambda: Counter())
        for case in all_cases:
            created_date = timezone.localdate(case.created_at)
            if filters['date_from'] <= created_date <= filters['date_to']:
                trend[_bucket_label(created_date, filters['granularity'])]['created'] += 1
        for row in terminal_rows:
            finished_date = datetime.fromisoformat(row['finished_at']).date()
            bucket = trend[_bucket_label(finished_date, filters['granularity'])]
            bucket['finished'] += 1
            bucket['disbursed'] += int(row['status'] == 'Disbursed')
            if row['sla_state'] != 'target_unavailable':
                bucket['sla_sample'] += 1
                bucket['sla_met'] += int(row['sla_state'] != 'overdue')
        common['trend'] = [
            {'label': key, **dict(value), 'sla_met_percent': round(value['sla_met'] * 100 / value['sla_sample'], 1) if value['sla_sample'] else None}
            for key, value in sorted(trend.items())
        ]
    if include_people:
        common['by_person'] = [
            {'label': key, 'count': value}
            for key, value in Counter(
                (item.get('person') or 'Unassigned' for item in stage_samples)
                if stage_samples else (row.get('responsible_person') or 'Unassigned' for row in rows)
            ).most_common()
        ]
    return common


def _metric_scope_q(actor):
    from core.models import WORKFLOW_DATA_MODE_PILOT, WORKFLOW_DATA_MODE_PRODUCTION
    from core.services.workflow_data_mode import WORKFLOW_TAT, mode_snapshot
    snapshot = mode_snapshot(WORKFLOW_TAT)
    operational = Q(data_mode=WORKFLOW_DATA_MODE_PRODUCTION)
    if snapshot.mode == WORKFLOW_DATA_MODE_PILOT:
        operational |= Q(data_mode=WORKFLOW_DATA_MODE_PILOT, pilot_cycle_id=snapshot.pilot_cycle_id)
    if actor.is_active and actor.is_superuser:
        return operational
    query = Q(pk__in=[])
    for grant in AccessGrant.objects.filter(user=actor, workflow='tat_tracker', active=True).select_related('group_configuration'):
        part = Q()
        scoped = False
        if grant.group_configuration_id:
            part &= Q(group_id=str(grant.group_configuration.group_id))
            scoped = True
        if grant.branch:
            part &= Q(branch__iexact=grant.branch)
            scoped = True
        if grant.product:
            part &= Q(product_key__iexact=grant.product)
            scoped = True
        if not scoped:
            return operational
        query |= part
    return operational & query


def _filter_metric_queryset(qs, filters):
    if filters['group']:
        qs = qs.filter(group_id=filters['group'])
    if filters['branch']:
        qs = qs.filter(branch__iexact=filters['branch'])
    if filters['product']:
        qs = qs.filter(product_key__iexact=filters['product'])
    if filters['stage']:
        qs = qs.filter(stage_key__iexact=filters['stage'])
    if filters['role']:
        qs = qs.filter(responsible_role__iexact=filters['role'])
    return qs


def report_cases(actor, payload, *, include_people=False):
    filters = _filters(payload)
    rows = _eligible_rows(actor, filters, include_people=include_people)
    sort = str(payload.get('sort') or '-created_at')
    descending = sort.startswith('-')
    key = sort.lstrip('-')
    if key not in SORT_FIELDS:
        raise ValueError('This report column cannot be sorted.')
    rows.sort(key=lambda row: (row.get(key) is None, row.get(key) or ''), reverse=descending)
    try:
        page = max(1, int(payload.get('page') or 1))
        page_size = max(1, min(100, int(payload.get('page_size') or 25)))
    except (TypeError, ValueError):
        raise ValueError('Page and page size must be valid numbers.')
    start = (page - 1) * page_size
    return {'results': rows[start:start + page_size], 'count': len(rows), 'page': page, 'page_size': page_size}


def export_report_xlsx(actor, payload, *, include_people=False, request_id=''):
    # Exports are allowed to exceed the API page cap, while retaining a hard operational limit.
    filters = _filters(payload)
    rows = _eligible_rows(actor, filters, include_people=include_people)
    if len(rows) > 10000:
        raise ValueError('More than 10,000 cases match. Narrow the filters before downloading.')
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    headers = ['Reference', 'Customer', 'TAT Group', 'Branch', 'Product', 'Status', 'Stage', 'Responsible Role', 'Created', 'Finished', 'Elapsed Minutes', 'Target Minutes', 'Variance Minutes', 'SLA State']
    keys = ['case_id', 'client_name', 'group', 'branch', 'product_label', 'status', 'current_stage', 'responsible_role', 'created_at', 'finished_at', 'elapsed_minutes', 'target_minutes', 'variance_minutes', 'sla_state']
    if include_people:
        headers.append('Responsible Person'); keys.append('responsible_person')
    workbook = Workbook(); sheet = workbook.active; sheet.title = 'TAT Report'; sheet.append(headers)
    for cell in sheet[1]:
        cell.font = Font(bold=True, color='FFFFFF'); cell.fill = PatternFill('solid', fgColor='245B8A')
    for row in rows:
        values = []
        for key in keys:
            value = row.get(key, '')
            if isinstance(value, str) and value[:1] in {'=', '+', '-', '@'}:
                value = "'" + value
            if key in {'created_at', 'finished_at'} and value:
                value = datetime.fromisoformat(value).strftime('%d-%m-%y %H:%M')
            values.append(value)
        sheet.append(values)
    output = BytesIO(); workbook.save(output)
    from core.services.compliance_audit import record_event
    record_event(
        workflow='tat_tracker', action='tat.report.exported', category='data_export', origin='human',
        subject_type='tat_report', subject_id=str(filters['view']), actor=actor, authority_user=actor,
        deduplication_key=f'tat-report-export:{actor.pk}:{request_id}', before_values={}, after_values={},
        metadata={'view': filters['view'], 'filters': {key: str(value) for key, value in filters.items()}, 'fields': headers, 'row_count': len(rows)},
        sensitive=False,
    )
    return output.getvalue(), len(rows)


def enqueue_metric_rebuild(case, correction_revision, affected_dates):
    valid = [item for item in affected_dates if item]
    start = min(valid) if valid else timezone.localdate()
    end = timezone.localdate()
    return WorkflowTatMetricRebuildRequest.objects.get_or_create(
        request_key=f'case:{case.pk}:{correction_revision}',
        defaults={'case': case, 'correction_revision': correction_revision, 'date_from': start, 'date_to': end, 'next_date': start},
    )[0]


@transaction.atomic
def replace_metric_date(metric_date):
    from core.services.workflow_sla import collect_tat_daily_metrics, record_tat_daily_metrics
    metrics = collect_tat_daily_metrics(metric_date=metric_date)
    WorkflowTatDailyMetric.objects.filter(workflow='tat_tracker', metric_date=metric_date).delete()
    return record_tat_daily_metrics(metrics, metric_date=metric_date)


def process_metric_rebuilds(*, max_days=31):
    processed = 0
    while processed < max_days:
        with transaction.atomic():
            request = WorkflowTatMetricRebuildRequest.objects.select_for_update().filter(
                Q(status__in=['pending', 'processing']) | Q(status='failed', attempts__lt=3),
                next_date__lte=models_f('date_to'),
            ).first()
            if not request:
                break
            request.status = 'processing'; request.save(update_fields=['status', 'updated_at'])
            metric_date = request.next_date
        try:
            replace_metric_date(metric_date)
        except Exception as exc:
            WorkflowTatMetricRebuildRequest.objects.filter(pk=request.pk).update(
                status='failed', attempts=models_f('attempts') + 1,
                last_error=str(exc)[:500],
            )
            continue
        processed += 1
        next_date = metric_date + timedelta(days=1)
        updates = {'next_date': next_date, 'last_error': '', 'attempts': 0}
        if next_date > request.date_to:
            updates.update(status='complete', completed_at=timezone.now())
        else:
            updates['status'] = 'pending'
        WorkflowTatMetricRebuildRequest.objects.filter(pk=request.pk).update(**updates)
    return processed


def models_f(field):
    from django.db.models import F
    return F(field)
