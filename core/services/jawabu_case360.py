"""Case 360 timeline and TAT projection for the Jawabu Portal Mini App."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from django.db import IntegrityError
from django.utils import timezone

from core.models import (
    GroupSheetConfiguration,
    JawabuFarmerMaster,
    JawabuHouseholdRelationship,
    JawabuPipelineEvent,
    ParsedInvoice,
    PaymentDocument,
    RequisitionBatch,
)
from core.services.business_calendar import business_minutes_between, wall_clock_minutes_between
from core.services.jawabu_validation import parse_business_date, parse_money, validation_warnings
from core.services.workflow_escalations import latest_escalation
from core.services.workflow_timeline import jawabu_case_timeline


MILESTONES = (
    ('application_imported', 'Intake'),
    ('jbl_visit_completed', 'JBL Visit'),
    ('credit_decision_recorded', 'Credit Decision'),
    ('final_decision_recorded', 'Final Decision'),
    ('hb_order_released', 'Order Assigned/Sent to HB'),
    ('installation_completed', 'HB Installation'),
    ('commissioning_completed', 'HB Commissioning'),
)

# The target is frozen at the point a stage starts.  Changing Settings is
# therefore prospective: it improves the next case/stage without quietly
# rewriting a staff member's historical TAT result.
TAT_STAGE_START_ACTIONS = {
    start: f'{start}_to_{end}'
    for (start, _label), (end, _next_label) in zip(MILESTONES, MILESTONES[1:])
}


def _case_date(value: Any) -> str | None:
    parsed = value if isinstance(value, date) else parse_business_date(value)
    return parsed.strftime('%d-%m-%Y') if parsed else None


def _case_datetime(value: Any) -> str | None:
    if not value:
        return None
    if isinstance(value, datetime):
        displayed = timezone.localtime(value) if timezone.is_aware(value) else value
        return displayed.strftime('%d-%m-%Y %H:%M')
    parsed = parse_business_date(value)
    return parsed.strftime('%d-%m-%Y') if parsed else None


def _case_amount(value: Any) -> str | None:
    amount = value if isinstance(value, Decimal) else parse_money(value)
    if amount is None:
        return None
    text = format(amount, 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def _payment_documents_for_farmer(farmer: JawabuFarmerMaster) -> list[PaymentDocument]:
    """Resolve payment snapshots linked to this application.

    Payment batches selected in the Mini App use a ``PAYMENT-*`` scope rather
    than the customer's order number, so matching only on ``order_number``
    would make the payment comment disappear from Case History.  The immutable
    payment snapshot stores the selected farmer IDs; use those first and keep
    the order-number fallback for older documents.
    """
    farmer_id = str(farmer.id)
    documents = []
    if farmer.order_number:
        documents.extend(PaymentDocument.objects.filter(
            status__in=['final', 'pending_review'],
            order_number=farmer.order_number,
        ).order_by('-created_at'))
    seen = {document.id for document in documents}
    documents.extend(PaymentDocument.objects.filter(
        status__in=['final', 'pending_review'],
    ).exclude(pk__in=seen).order_by('-created_at')[:200])
    matched = []
    for document in documents:
        selected_ids = {str(value) for value in (document.farmer_ids or []) if value}
        rows = (document.validation_summary or {}).get('preview_rows') or []
        row_match = any(str((row or {}).get('farmer_id') or '') == farmer_id for row in rows)
        if farmer_id not in selected_ids and not row_match and document.order_number != farmer.order_number:
            continue
        matched.append(document)
    return matched


def _latest_payment_documents(documents: list[PaymentDocument]) -> list[PaymentDocument]:
    """Return one latest payment artifact per payment/order scope.

    PaymentDocument rows are append-only audit artifacts. Case Documents is a
    current-record view, so it must not expose every historical final workbook
    as if it were a separate live document.
    """
    latest: dict[tuple[str, str], PaymentDocument] = {}
    ordered = sorted(
        documents,
        key=lambda document: (
            int(document.version or 0),
            document.finalized_at or document.updated_at or document.created_at,
        ),
        reverse=True,
    )
    for document in ordered:
        scope = (
            str(document.payment_number or '').strip(),
            str(document.order_number or '').strip(),
        )
        latest.setdefault(scope, document)
    return list(latest.values())


def _payment_comment_for_farmer(
    farmer: JawabuFarmerMaster,
    documents: list[PaymentDocument] | None = None,
) -> str:
    farmer_id = str(farmer.id)
    source_documents = documents if documents is not None else _payment_documents_for_farmer(farmer)
    for document in source_documents:
        comments = document.case_call_up_comments or {}
        comment = str(comments.get(farmer_id) or '').strip()
        if not comment:
            # Older final documents only stored one payment COL comment.  It is
            # still a payment comment, not the order/requisition comment.
            comment = str(document.call_up_comments or '').strip()
        if comment:
            return comment
    return ''


def event_request_already_processed(farmer: JawabuFarmerMaster, request_id: str) -> bool:
    return bool(request_id) and farmer.pipeline_events.filter(request_id=request_id).exists()


def record_pipeline_event(
    farmer: JawabuFarmerMaster,
    *,
    action: str,
    stage_key: str = '',
    actor: str = '',
    actor_telegram_id: str = '',
    source: str = 'portal',
    request_id: str = '',
    old_values: dict | None = None,
    new_values: dict | None = None,
    metadata: dict | None = None,
    occurred_at=None,
    actor_user=None,
    authority_user=None,
    transition_code: str = '',
    from_state: str = '',
    to_state: str = '',
    reason: str = '',
    revision_before: int | None = None,
    revision_after: int | None = None,
) -> JawabuPipelineEvent:
    event_metadata = dict(metadata or {})
    stage_target_key = TAT_STAGE_START_ACTIONS.get(action)
    if stage_target_key and 'tat_target_snapshot' not in event_metadata:
        target = portal_tat_target_for_stage(stage_target_key)
        if target is not None:
            event_metadata['tat_target_snapshot'] = {
                'stage_key': stage_target_key,
                'target_minutes': target,
            }
    if action == 'application_imported' and 'tat_overall_target_snapshot' not in event_metadata:
        overall_target = portal_tat_overall_target()
        if overall_target is not None:
            event_metadata['tat_overall_target_snapshot'] = {'target_minutes': overall_target}
    values = {
        'action': action,
        'stage_key': stage_key,
        'actor': str(actor or ''),
        'actor_telegram_id': str(actor_telegram_id or ''),
        'source': source,
        'request_id': str(request_id or ''),
        'old_values': old_values or {},
        'new_values': new_values or {},
        'metadata': event_metadata,
        'occurred_at': occurred_at or timezone.now(),
        'actor_user': actor_user,
        # Delegation is intentionally not enabled yet. Keeping a separate
        # authority field means the audit shape is ready without pretending a
        # clicker and accountable decision-maker are always interchangeable.
        'authority_user': authority_user or actor_user,
        'transition_code': str(transition_code or ''),
        'from_state': str(from_state or ''),
        'to_state': str(to_state or ''),
        'reason': str(reason or ''),
        'revision_before': revision_before,
        'revision_after': revision_after,
    }
    if values['request_id']:
        try:
            event, _created = JawabuPipelineEvent.objects.get_or_create(
                farmer=farmer,
                request_id=values['request_id'],
                defaults=values,
            )
        except IntegrityError:
            event = JawabuPipelineEvent.objects.get(farmer=farmer, request_id=values['request_id'])
    else:
        event = JawabuPipelineEvent.objects.create(farmer=farmer, **values)

    # Project the existing operational event into the shared, hash-chained
    # compliance ledger. The source-event key keeps Telegram retries idempotent.
    from core.services.compliance_audit import record_event

    record_event(
        workflow='portal',
        action=f'portal.{event.action}',
        category='workflow_transition' if event.transition_code else 'workflow',
        origin='system' if event.source in {'system', 'farmup', 'sheet_sync'} else 'human',
        subject_type='jawabu_farmer',
        subject_id=str(farmer.pk),
        customer_reference=str(getattr(farmer, 'customer_no', '') or ''),
        actor=event.actor_user,
        authority_user=event.authority_user,
        actor_label=event.actor,
        request_id=event.request_id,
        source_model='JawabuPipelineEvent',
        source_event_id=str(event.pk),
        deduplication_key=f'portal:JawabuPipelineEvent:{event.pk}',
        before_values=event.old_values,
        after_values=event.new_values,
        metadata={
            **(event.metadata or {}),
            'stage_key': event.stage_key,
            'transition_code': event.transition_code,
            'from_state': event.from_state,
            'to_state': event.to_state,
            'reason': event.reason,
            'revision_before': event.revision_before,
            'revision_after': event.revision_after,
            'source': event.source,
        },
        sensitive=bool(event.old_values or event.new_values),
        occurred_at=event.occurred_at,
    )
    return event


def _portal_tat_configuration():
    for config in GroupSheetConfiguration.objects.filter(enabled=True).order_by('pk'):
        workflow = config.workflow or {}
        if workflow.get('type') in {'jawabu', 'jawabu_homebiogas'} or workflow.get('master_sync_enabled'):
            return config
    return None


def _tat_targets() -> dict[str, Any]:
    config = _portal_tat_configuration()
    return ((config.workflow or {}).get('jawabu_tat_targets_minutes') or {}) if config else {}


def _portal_tat_stage_definitions() -> list[dict[str, str]]:
    return [
        {'key': f'{start}_to_{end}', 'label': end_label}
        for (start, start_label), (end, end_label) in zip(MILESTONES, MILESTONES[1:])
    ]


def portal_tat_target_settings_payload(config) -> dict[str, Any]:
    targets = ((config.workflow or {}).get('jawabu_tat_targets_minutes') or {})
    stage_targets = targets.get('stages') or {}
    return {'overall_minutes': targets.get('overall'), 'stages': [
        {**definition, 'target_minutes': stage_targets.get(definition['key'])}
        for definition in _portal_tat_stage_definitions()
    ]}


def save_portal_tat_target_settings(config, payload: object, *, actor=None) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get('stages') or {}, dict):
        raise ValueError('TAT targets must contain a stage-target object.')
    supplied = payload.get('stages') or {}
    allowed = {item['key'] for item in _portal_tat_stage_definitions()}
    if set(supplied) - allowed:
        raise ValueError('An unknown Portal TAT stage was supplied.')
    stages = {}
    for key, raw in supplied.items():
        if raw in (None, ''):
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError('Each target must be a whole number of minutes.') from exc
        if value < 1:
            raise ValueError('Each target must be at least one minute.')
        stages[key] = value
    raw_overall = payload.get('overall_minutes')
    if raw_overall in (None, ''):
        overall = None
    else:
        try:
            overall = int(raw_overall)
        except (TypeError, ValueError) as exc:
            raise ValueError('Overall target must be a whole number of minutes.') from exc
        if overall < 1:
            raise ValueError('Overall target must be at least one minute.')
    from django.db import transaction
    from core.services.compliance_audit import record_event
    with transaction.atomic():
        locked = GroupSheetConfiguration.objects.select_for_update().get(pk=config.pk)
        workflow = dict(locked.workflow or {})
        before = workflow.get('jawabu_tat_targets_minutes') or {}
        updated = {'overall': overall, 'stages': stages}
        workflow['jawabu_tat_targets_minutes'] = updated
        locked.workflow = workflow
        locked.save(update_fields=['workflow', 'updated_at'])
        record_event(workflow='portal', action='portal.tat_targets.updated', category='configuration', origin='human', subject_type='group_sheet_configuration', subject_id=str(locked.pk), actor=actor, actor_label=(actor.get_full_name() or actor.get_username()) if actor else '', before_values=before, after_values=updated, sensitive=False)
    return portal_tat_target_settings_payload(locked)


def portal_tat_target_for_stage(stage_key: str) -> int | None:
    value = (_tat_targets().get('stages') or {}).get(stage_key)
    try:
        return int(value) if value not in (None, '') else None
    except (TypeError, ValueError):
        return None


def portal_tat_overall_target() -> int | None:
    value = _tat_targets().get('overall')
    try:
        return int(value) if value not in (None, '') else None
    except (TypeError, ValueError):
        return None


def _frozen_target(start_event, stage_key: str, fallback: Any) -> Any:
    """Prefer the audited target captured when this stage began."""
    metadata = getattr(start_event, 'metadata', None) or {}
    values = getattr(start_event, 'new_values', None) or {}
    snapshot = metadata.get('tat_target_snapshot') or values.get('tat_target_snapshot') or {}
    if snapshot.get('stage_key') == stage_key and snapshot.get('target_minutes') not in (None, ''):
        return snapshot['target_minutes']
    return fallback


def _deferral_intervals(events, start, end) -> list[tuple[datetime, datetime]]:
    """Return only the formally approved deferred/reappraisal exclusions."""
    intervals: list[tuple[datetime, datetime]] = []
    deferred_at = None
    for event in events:
        at = event.occurred_at
        if event.action in {'deferral_started', 'deferred', 'case_withdrawn'}:
            deferred_at = max(at, start) if at < end else None
        elif event.action in {'deferral_ended', 'reappraisal_restarted', 'withdrawal_resumed'} and deferred_at:
            overlap_end = min(at, end)
            if overlap_end > deferred_at:
                intervals.append((deferred_at, overlap_end))
            deferred_at = None
    if deferred_at and end > deferred_at:
        intervals.append((deferred_at, end))
    return intervals


def _excluded_deferral_seconds(events, start, end) -> Decimal:
    return sum(
        (Decimal(str((interval_end - interval_start).total_seconds())) for interval_start, interval_end in _deferral_intervals(events, start, end)),
        Decimal('0'),
    )


def _sla_status(minutes: Decimal | None, target: Any) -> str:
    if minutes is None or target in (None, ''):
        return 'not_configured' if target in (None, '') else ''
    try:
        target_value = Decimal(str(target))
    except Exception:
        return 'not_configured'
    if target_value <= 0:
        return 'not_configured'
    if minutes > target_value:
        return 'over'
    if minutes >= target_value * Decimal('0.8'):
        return 'near'
    return 'within'


def calculate_case_tat(farmer: JawabuFarmerMaster, *, now=None, events=None, hb_events=None, targets=None, holidays=None, approvals=None) -> dict[str, Any]:
    """Seven ordered stages, one active clock, immutable source events."""
    now = now or timezone.now()
    events = sorted(list(farmer.pipeline_events.all()) if events is None else list(events), key=lambda e: e.occurred_at)
    applications = [e for e in events if e.action == 'application_imported' and e.occurred_at <= now]
    cycle_start = applications[-1].occurred_at if applications else None
    current = [e for e in events if (not cycle_start or e.occurred_at >= cycle_start) and e.occurred_at <= now]
    targets = _tat_targets() if targets is None else targets
    actions = [key for key, _ in MILESTONES]
    milestones, restarts = {}, {}
    terminal_at = None
    held = False
    for event in current:
        values = event.new_values or {}
        action = event.action
        if action in {'deferral_started', 'deferred', 'case_withdrawn'}:
            held = True
        elif action in {'deferral_ended', 'reappraisal_restarted', 'withdrawal_resumed'}:
            held = False
            terminal_at = None
        if action == 'returned_for_rework':
            index = {'jbl_visit': 1, 'credit': 2, 'final_review': 3}.get(values.get('returned_to'))
            if index:
                for key in actions[index:]:
                    milestones.pop(key, None)
                restarts[index] = event
                terminal_at = None
        if action == 'order_cancelled':
            for key in actions[4:]:
                milestones.pop(key, None)
            restarts[4] = event
        if action in actions:
            # Rescheduling/holds are outcomes within JBL Visit, not advancement.
            if action == 'jbl_visit_completed' and values.get('status') not in (None, '', 'Visited, Awaiting Credit Analysis', 'Approved'):
                continue_milestone = False
            elif action in {'credit_decision_recorded', 'final_decision_recorded'} and values.get('decision') not in (None, '', 'Approved'):
                continue_milestone = False
            else:
                continue_milestone = True
            if continue_milestone:
                milestones[action] = event
        if (action in {'credit_decision_recorded', 'final_decision_recorded'} and values.get('decision') == 'Rejected'
                or action in {'jbl_visit_completed', 'jbl_outcome_recorded'} and values.get('status') in {'Rejected by JBL', 'Cancelled', 'Client Withdrew', 'Opted for Cash', 'Opted for Other Partner'}
                or action == 'case_withdrawn'):
            terminal_at = event.occurred_at
    from hb_operations.models import HomeBiogasActionEvent
    hb_events = list(HomeBiogasActionEvent.objects.filter(action__farmer=farmer,
        event_type__in=['order.released_to_hb', 'installation.progressed', 'commissioning.completed'])
        .order_by('created_at', 'pk')) if hb_events is None else list(hb_events)
    hb_actions = {'order.released_to_hb': 'hb_order_released', 'installation.progressed': 'installation_completed',
                  'commissioning.completed': 'commissioning_completed'}
    for event in sorted(hb_events, key=lambda e: e.created_at):
        if event.created_at > now or cycle_start and event.created_at < cycle_start:
            continue
        action = hb_actions.get(event.event_type)
        values = event.new_values or {}
        if not action or action == 'installation_completed' and values.get('installation_status') != 'installed' or action == 'commissioning_completed' and values.get('commissioning_status') != 'commissioned':
            continue
        milestones[action] = SimpleNamespace(occurred_at=event.created_at, new_values=values,
            metadata={'tat_target_snapshot': values.get('tat_target_snapshot')})
    hb_action = getattr(farmer, 'homebiogas_action', None)
    known_completion = -1
    if hb_action:
        if hb_action.commissioning_status == 'commissioned':
            known_completion = 6
        else:
            milestones.pop('commissioning_completed', None)
        if hb_action.installation_status == 'installed':
            known_completion = max(known_completion, 5)
        else:
            milestones.pop('installation_completed', None)
    state = farmer.workflow_state
    canonical = {'jbl_visit': 1, 'credit': 2, 'final_review': 3, 'order': 4}.get(state)
    if state == 'deferred':
        canonical = {'jbl_visit': 1, 'credit': 2, 'final': 3}.get(farmer.deferred_stage)
    if approvals is None:
        from core.models import JawabuApprovalRecord
        approvals = list(JawabuApprovalRecord.objects.filter(farmer=farmer, payment_document__isnull=True,
            gate__in=['credit', 'final_review']).order_by('-decided_at', '-created_at')) if getattr(farmer, 'pk', None) else []
    seen_gates = set()
    if not getattr(farmer, 'order_number', ''):
        for approval in approvals:
            if approval.gate in seen_gates:
                continue
            seen_gates.add(approval.gate)
            if approval.status in {'invalidated', 'expired', 'conditions_pending'} or approval.expires_at and approval.expires_at <= now:
                index = {'credit': 2, 'final_review': 3}[approval.gate]
                canonical = min(canonical, index) if canonical is not None else index
                at = approval.invalidated_at or approval.expires_at
                if at:
                    restarts[index] = SimpleNamespace(occurred_at=at, metadata={})
    if canonical is not None:
        for key in actions[canonical:]:
            milestones.pop(key, None)
    highest = max((actions.index(key) for key in milestones), default=-1)
    highest = max(highest, known_completion)
    active = canonical if canonical is not None else max(1, highest + 1)
    if state == 'ordered':
        active = max(4, highest + 1)
    if state == 'legacy_review':
        active = len(actions)
    paused = held or state in {'deferred', 'withdrawn'}
    stopped = terminal_at is not None or state in {'rejected', 'withdrawn'} or highest == 6
    from core.services.report_provenance import external_timing
    external_fields, external_position = external_timing(current)
    invalid = set()
    previous_at = None
    for action in actions:
        event = milestones.get(action)
        if event:
            if previous_at and event.occurred_at < previous_at:
                invalid.add(action)
            previous_at = max(previous_at, event.occurred_at) if previous_at else event.occurred_at

    def timing(start, end):
        empty = dict(minutes=None, wall_clock_minutes=None, elapsed_seconds=None, business_minutes=None,
            sla_minutes=None, excluded_deferred_minutes='0', excluded_business_minutes='0')
        if not start or not end or start > end or end > now:
            return empty
        excluded = _excluded_deferral_seconds(current, start, end)
        seconds = max(Decimal('0'), Decimal(str((end - start).total_seconds())) - excluded)
        minutes = (seconds / 60).quantize(Decimal('0.01'))
        business = business_minutes_between(start, end, holidays=holidays) or Decimal('0')
        excluded_business = sum((business_minutes_between(a, b, holidays=holidays) or Decimal('0')
            for a, b in _deferral_intervals(current, start, end)), Decimal('0'))
        return dict(minutes=str(minutes), wall_clock_minutes=str(minutes), elapsed_seconds=int(seconds),
            business_minutes=str(business.quantize(Decimal('0.01'))), sla_minutes=str(minutes),
            excluded_deferred_minutes=str((excluded / 60).quantize(Decimal('0.01'))),
            excluded_business_minutes=str(excluded_business.quantize(Decimal('0.01'))))

    stages = []
    for index, (action, label) in enumerate(MILESTONES):
        end_event = milestones.get(action)
        start_event = (restarts.get(index) or milestones.get(actions[index - 1])) if index else None
        start = start_event.occurred_at if start_event else None
        end = end_event.occurred_at if end_event else None
        key = f'{actions[index - 1]}_to_{action}' if index else 'intake'
        completed = (index < active if state != 'legacy_review' else index <= highest) or end_event is not None
        stage_state = 'completed' if completed else 'pending'
        if index == active and not stopped:
            stage_state = 'paused' if paused else 'in_progress'
        elif index == active and stopped:
            stage_state = 'stopped'
        boundary = bool(external_position and not end and start and start <= external_position.occurred_at)
        measure_end = end if completed else terminal_at or now if index == active else None
        if index == active and (state in {'rejected', 'withdrawn'} and not terminal_at or paused and not held):
            measure_end = None
        valid_pair = index and action not in invalid and actions[index - 1] not in invalid
        values = timing(start, measure_end) if valid_pair and not boundary else timing(None, None)
        if index == 1 and external_fields & {'hbg_visit_date', 'jbl_visit_date'}:
            values = timing(None, None)
        running = bool(stage_state == 'in_progress' and values['elapsed_seconds'] is not None)
        if values['minutes'] is None and stage_state == 'in_progress':
            stage_state = 'timing_unavailable'
        target = _frozen_target(start_event, key, (targets.get('stages') or {}).get(key)) if start_event else None
        snapshot = (getattr(start_event, 'metadata', None) or {}).get('tat_target_snapshot') or {}
        stages.append(dict(key=key, label=label, stage_state=stage_state, started_at=start.isoformat() if start else None,
            completed_at=end.isoformat() if end else None, calculated_at=now.isoformat(), running=running,
            target_minutes=str(target) if target not in (None, '') else None,
            target_seconds=int(Decimal(str(target)) * 60) if target not in (None, '') else None,
            status=_sla_status(Decimal(values['minutes']), target) if values['minutes'] is not None else '',
            target_basis='captured' if snapshot.get('stage_key') == key else 'current_target_estimate' if target else 'unavailable',
            timing_note='Timing unavailable' if index and values['minutes'] is None and stage_state != 'pending' else '', **values))
    application = milestones.get('application_imported')
    finish = milestones.get('commissioning_completed')
    overall_end = finish.occurred_at if finish else terminal_at or now
    overall = timing(application.occurred_at if application else None,
                     None if state in {'rejected', 'withdrawn'} and not terminal_at or paused and not held or highest == 6 and not finish else overall_end)
    snapshot = (getattr(application, 'metadata', None) or {}).get('tat_overall_target_snapshot') or {}
    overall_target = snapshot.get('target_minutes', targets.get('overall'))
    return dict(tracking_started_at=next((e.occurred_at.isoformat() for e in events if e.action == 'tracking_started'), None),
        current_cycle_started_at=cycle_start.isoformat() if cycle_start else None,
        previous_cycle_count=max(0, len(applications) - 1), historical_timestamps_available=bool(application),
        total_minutes=overall['minutes'], **overall, calculated_at=now.isoformat(),
        running=any(row['running'] for row in stages), active_stage_key=stages[active]['key'] if active < len(stages) else None,
        target_minutes=str(overall_target) if overall_target else None,
        target_seconds=int(Decimal(str(overall_target)) * 60) if overall_target else None,
        status=_sla_status(Decimal(overall['minutes']), overall_target) if overall['minutes'] is not None else '',
        completed_stage_count=sum(row['stage_state'] == 'completed' for row in stages), stages=stages)


def serialize_case360(farmer: JawabuFarmerMaster) -> dict[str, Any]:
    from core.services.jawabu_pipeline import credit_decision_label, current_pipeline_state_label, current_workflow_state
    from core.services.jawabu_case_reference import display_case_reference
    validation = validation_warnings(farmer)
    timeline_projection = jawabu_case_timeline(farmer)
    invoice = ParsedInvoice.objects.filter(matched_farmer=farmer, status='matched').order_by('-updated_at').first()
    from requisitions.services import order_for_farmer
    requisition = order_for_farmer(farmer) if farmer.order_number else None
    payment_documents = _payment_documents_for_farmer(farmer)
    payment_comment = _payment_comment_for_farmer(farmer, payment_documents)
    payments = _latest_payment_documents(
        [document for document in payment_documents if document.status == 'final']
    )
    household_relationships = list(farmer.household_relationships.select_related(
        'related_person', 'related_person__linked_customer',
    ).order_by('-created_at'))
    incoming_household_relationships = []
    if farmer.customer_id:
        incoming_household_relationships = list(
            JawabuHouseholdRelationship.objects.select_related('farmer', 'related_person')
            .filter(related_person__linked_customer_id=farmer.customer_id)
            .exclude(farmer=farmer)
            .order_by('-created_at')
        )
    invoice_name_changes = farmer.invoice_name_changes.select_related(
        'batch', 'original_invoice', 'replacement_invoice',
    ).order_by('-created_at')
    from hb_operations.models import HomeBiogasAction
    hb_action = HomeBiogasAction.objects.filter(farmer=farmer).first()
    return {
        'case_reference': display_case_reference(farmer),
        'farmer_id': str(farmer.pk),
        'workflow_revision': int(farmer.workflow_revision or 1),
        'deferred_stage': farmer.deferred_stage,
        # The current canonical state, rather than historical non-empty
        # fields, owns the case-progress strip. A returned JBL visit can still
        # retain an earlier credit decision for audit without appearing to be
        # simultaneously in two stages.
        'workflow_state': current_workflow_state(farmer),
        'withdrawn_stage': farmer.withdrawn_stage,
        'current_pipeline_state': current_pipeline_state_label(farmer),
        'sections': {
            'identity': {'customer_name': farmer.customer_name, 'system_name': farmer.imab_customer_name, 'national_id': farmer.national_id, 'primary_phone': farmer.primary_phone, 'secondary_phone': farmer.secondary_phone, 'customer_no': farmer.customer_no, 'unit_number': farmer.unit_number, 'lead_name': farmer.lead_name, 'lead_national_id': farmer.lead_national_id, 'lead_primary_phone': farmer.lead_primary_phone},
            # Ward is retained for source/import compatibility, but is not a
            # captured or used field in the staff-facing case history.
            'intake': {'hbg_visit_date': _case_date(farmer.hbg_visit_date or farmer.sign_date), 'county': farmer.county, 'constituency': farmer.sub_county, 'village': farmer.village, 'branch': farmer.branch, 'lead_source': farmer.lead_source, 'hb_sales_person': farmer.hb_sales_person, 'deposit_paid_hbg': _case_amount(farmer.deposit_paid_hbg if farmer.deposit_paid_hbg is not None else farmer.actual_receipts)},
            'jbl_visit': {'visit_date': _case_date(farmer.jbl_visit_date), 'next_visit_date': _case_date(farmer.jbl_next_visit_date), 'officer': farmer.jbl_officer, 'system_loan_officer': farmer.system_loan_officer or farmer.jbl_officer, 'status': farmer.jbl_visit_status, 'comment': farmer.jbl_visit_comment, 'gps_link': farmer.gps_link},
            'credit': {'decision': farmer.credit_decision, 'decision_label': credit_decision_label(farmer), 'decided_by': farmer.credit_decided_by, 'decided_at': _case_datetime(farmer.credit_decided_at), 'imab_created': farmer.imab_created, 'customer_no': farmer.customer_no},
            'final_review': {'decision': farmer.final_decision, 'comment': farmer.final_decision_comment, 'payment_comment': payment_comment, 'decided_by': farmer.final_decided_by, 'decided_at': _case_datetime(farmer.final_decided_at), 'repayment_day': farmer.repayment_day, 'tenor_months': farmer.repayment_tenor_months},
            'order': {'order_number': farmer.order_number, 'requisition_date': _case_date(farmer.requisition_date), 'payment_product': farmer.payment_product},
            'homebiogas': {
                'released_at': _case_datetime(hb_action.created_at) if hb_action else '',
                'installation_status': hb_action.installation_status if hb_action else '',
                'installation_date': _case_date(hb_action.installation_date) if hb_action else '',
                'commissioning_status': hb_action.commissioning_status if hb_action else '',
                'commissioning_date': _case_date(hb_action.commissioning_date) if hb_action else '',
            },
            'invoice': {'number': farmer.invoice_number, 'date': _case_date(farmer.invoice_date), 'amount': _case_amount(farmer.invoice_amount), 'discount': _case_amount(farmer.discount), 'payment': _case_amount(farmer.payment), 'balance_due': _case_amount(farmer.balance_due)},
        },
        'household_relationships': [{
                'id': str(relationship.id),
                'relationship_type': relationship.relationship_type,
                'status': relationship.status,
                'name': relationship.related_person.full_name,
                'national_id': relationship.related_person.national_id,
                'phone': relationship.related_person.primary_phone,
                'linked_customer_id': str(relationship.related_person.linked_customer_id or ''),
                'direction': 'from_applicant',
                'linked_application_id': '',
                'confirmed_by': relationship.confirmed_by,
                'confirmed_at': _case_datetime(relationship.confirmed_at),
        } for relationship in household_relationships] + [{
                'id': str(relationship.id),
                'relationship_type': relationship.relationship_type,
                'status': relationship.status,
                'name': relationship.farmer.customer_name,
                'national_id': relationship.farmer.national_id,
                'phone': relationship.farmer.primary_phone,
                'linked_customer_id': str(farmer.customer_id),
                'direction': 'to_applicant',
                'linked_application_id': str(relationship.farmer_id),
                'confirmed_by': relationship.confirmed_by,
                'confirmed_at': _case_datetime(relationship.confirmed_at),
        } for relationship in incoming_household_relationships],
        'invoice_name_changes': [{
                'id': str(item.id),
                'batch_reference': item.batch.reference,
                'status': item.status,
                'original_invoice': item.original_invoice.invoice_no,
                'replacement_invoice': item.replacement_invoice.invoice_no if item.replacement_invoice_id else '',
                'created_at': _case_datetime(item.created_at),
                'completed_at': _case_datetime(item.completed_at),
        } for item in invoice_name_changes],
        'timeline': timeline_projection['entries'],
        'related_cases': timeline_projection['related_cases'],
        'tat': calculate_case_tat(farmer),
        'escalation': latest_escalation('jawabu_pipeline', str(farmer.pk)),
        'validation': validation,
        'documents': {
            'farmer_id': str(farmer.pk),
            'visit_media_count': len([url for url in farmer.jbl_media_urls.splitlines() if url.strip()]),
            'items': [item for item in [
                {
                    'id': str(requisition.pk),
                    'kind': 'requisition',
                    'name': requisition.filename,
                    'mime_type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                    'preview_url': '',
                    'open_url': requisition.drive_url,
                    'version': requisition.version,
                    'generated_at': _case_datetime(requisition.updated_at),
                } if requisition and requisition.drive_url else None,
                {
                    'id': str(invoice.batch_id),
                    'kind': 'invoice',
                    'name': invoice.batch.original_filename,
                    'mime_type': 'application/pdf',
                    'preview_url': f'/api/portal/farmers/{farmer.pk}/documents/invoice/{invoice.batch_id}/preview/',
                    'open_url': f'/api/portal/farmers/{farmer.pk}/documents/invoice/{invoice.batch_id}/open/',
                    'prepare_external': True,
                } if invoice and invoice.batch.drive_url else None,
            ] if item] + [{
                'id': str(item.pk),
                'kind': 'payment',
                'name': item.filename,
                'mime_type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                'preview_url': '',
                'open_url': item.drive_url,
                'version': item.version,
                'status': item.status,
                'generated_at': _case_datetime(item.finalized_at or item.updated_at or item.created_at),
            } for item in payments if item.drive_url],
            'visit_media': [url.strip() for url in farmer.jbl_media_urls.splitlines() if url.strip()],
            'requisition': {
                'name': requisition.filename,
                'url': requisition.drive_url,
                'version': requisition.version,
                'generated_at': _case_datetime(requisition.updated_at),
            } if requisition and requisition.drive_url else None,
            'invoice': {'name': invoice.batch.original_filename, 'url': invoice.batch.drive_url} if invoice and invoice.batch.drive_url else None,
            'payments': [{
                'name': item.filename,
                'url': item.drive_url,
                'version': item.version,
                'status': item.status,
                'generated_at': _case_datetime(item.finalized_at or item.updated_at or item.created_at),
            } for item in payments if item.drive_url],
        },
    }
