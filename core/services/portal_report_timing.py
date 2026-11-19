"""Report timing shares Portal stages; imported dates remain explicit estimates."""
from datetime import datetime, time
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from core.services.jawabu_case360 import calculate_case_tat

NAIROBI = ZoneInfo('Africa/Nairobi')


def _stamp(value):
    if value is None:
        return None
    return value if isinstance(value, datetime) else datetime.combine(value, time.min, NAIROBI)


def report_timing(record, *, now, events, hb_events, targets, holidays, approvals=None):
    from core.services.report_provenance import external_timing
    events = list(events)
    external_fields, external_position = external_timing(events)
    historical = record.report_historical
    if historical:
        dates = {'application_imported': record.hbg_visit_date, 'jbl_visit_completed': record.jbl_visit_date,
                 'credit_decision_recorded': record.credit_decided_at, 'final_decision_recorded': record.final_decided_at}
        action = getattr(record, 'homebiogas_action', None)
        if action:
            dates.update(installation_completed=action.installation_date, commissioning_completed=action.commissioning_date)
        # No signed handover date is inferred from an assigned order number.
        events = [SimpleNamespace(action=key, occurred_at=_stamp(value), new_values={}, metadata={})
                  for key, value in dates.items() if value]
        hb_events = []
    stages = calculate_case_tat(record, now=now, events=events, hb_events=hb_events,
        targets=targets, holidays=holidays, approvals=approvals)['stages']
    for index, stage in enumerate(stages):
        stage['historical'] = historical
        stage['precision'] = 'date' if historical else 'timestamp'
        if historical:
            stage['running'] = False
            # Incomplete imported stages never accrue live SLA time.
            if not stage['completed_at']:
                stage['minutes'] = stage['elapsed_seconds'] = None
            stage['target_basis'] = 'current_target_estimate' if stage['target_minutes'] else 'unavailable'
        external = index == 1 and bool(external_fields & {'hbg_visit_date', 'jbl_visit_date'})
        boundary = external_position and not stage['completed_at'] and (
            not stage['started_at'] or stage['started_at'] <= external_position.occurred_at.isoformat())
        if external or boundary:
            stage['externally_reported'] = True
            stage['target_basis'] = 'unavailable'
            stage['target_minutes'] = None
            stage['minutes'] = stage['elapsed_seconds'] = None
            stage['running'] = False
    return {'stages': stages}
