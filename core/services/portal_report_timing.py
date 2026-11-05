"""Report timing uses activity dates, never a legacy import's execution time."""
from datetime import datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from core.services.jawabu_case360 import calculate_case_tat, MILESTONES, _excluded_deferral_seconds

NAIROBI = ZoneInfo('Africa/Nairobi')


def _stamp(value):
    if value is None:
        return None
    return value if isinstance(value, datetime) else datetime.combine(value, time.min, NAIROBI)


def report_timing(record, *, now, events, hb_events, targets, holidays):
    historical = record.report_historical
    stages = [] if historical else calculate_case_tat(record, now=now, events=events,
        hb_events=hb_events, targets=targets, holidays=holidays)['stages']
    # Only documented adjacent milestones form historical stage durations.
    dates = {'application_imported': record.hbg_visit_date, 'jbl_visit_completed': record.jbl_visit_date,
             'credit_decision_recorded': record.credit_decided_at, 'final_decision_recorded': record.final_decided_at,
             'order_assigned': record.requisition_date}
    action = getattr(record, 'homebiogas_action', None)
    if action:
        dates.update(installation_completed=action.installation_date, commissioning_completed=action.commissioning_date)
    pairs = list(zip(MILESTONES, MILESTONES[1:]))
    for index, ((start, label), (end, end_label)) in enumerate(pairs):
        key = f'{start}_to_{end}'
        stage = {} if historical else stages[index]
        if historical or index == 0 and dates.get(start) and dates.get(end):
            first, last = _stamp(dates.get(start)), _stamp(dates.get(end))
            valid = bool(first and last and first <= last <= now)
            stage.update(key=key, label='HBG visit to JBL visit' if index == 0 else f'{label} to {end_label}',
                started_at=first.isoformat() if first else None, completed_at=last.isoformat() if last else None,
                minutes=str(Decimal(str((last-first).total_seconds())) / 60) if valid else None,
                precision='date' if not isinstance(dates.get(start), datetime) or not isinstance(dates.get(end), datetime) else 'timestamp',
                running=bool(first and first <= now and not last))
            if stage['running']:
                stage['minutes'] = str(Decimal(str((now-first).total_seconds())) / 60)
            if not historical and valid:
                excluded = _excluded_deferral_seconds(events, first, last)
                stage['minutes'] = str(max(Decimal('0'), Decimal(stage['minutes']) - excluded / 60))
            if historical:
                stage['target_minutes'] = (targets.get('stages') or {}).get(key)
                stages.append(stage)
        first = parse_datetime(stage['started_at']) if stage.get('started_at') else None
        last = parse_datetime(stage['completed_at']) if stage.get('completed_at') else now
        if not first or not last or first > last or last > now:
            stage['minutes'] = None
        start_event = next((event for event in reversed(events) if event.action == start), None)
        metadata = (getattr(start_event, 'metadata', None) or {}).get('tat_target_snapshot') or (getattr(start_event, 'new_values', None) or {}).get('tat_target_snapshot') or {}
        captured = not historical and metadata.get('stage_key') == key and metadata.get('target_minutes') is not None
        stage['target_basis'] = 'captured' if captured else 'current_target_estimate' if stage.get('target_minutes') else 'unavailable'
        stage.setdefault('precision', 'timestamp')
        stage['historical'] = historical
    return {'stages': stages}
