"""Case 360 timeline and TAT projection for the Jawabu Portal Mini App."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.db import IntegrityError
from django.utils import timezone

from core.models import (
    GroupSheetConfiguration,
    JawabuFarmerMaster,
    JawabuPipelineEvent,
    ParsedInvoice,
    PaymentDocument,
    RequisitionBatch,
)
from core.services.jawabu_validation import validation_warnings


MILESTONES = (
    ('application_imported', 'Intake completed'),
    ('jbl_visit_completed', 'JBL visit completed'),
    ('credit_decision_recorded', 'Credit decision recorded'),
    ('final_decision_recorded', 'Final decision recorded'),
    ('order_assigned', 'Order assigned'),
    ('invoice_confirmed', 'Invoice confirmed'),
    ('payment_finalized', 'Payment finalized'),
)


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
) -> JawabuPipelineEvent:
    values = {
        'action': action,
        'stage_key': stage_key,
        'actor': str(actor or ''),
        'actor_telegram_id': str(actor_telegram_id or ''),
        'source': source,
        'request_id': str(request_id or ''),
        'old_values': old_values or {},
        'new_values': new_values or {},
        'metadata': metadata or {},
        'occurred_at': occurred_at or timezone.now(),
    }
    if values['request_id']:
        try:
            event, _created = JawabuPipelineEvent.objects.get_or_create(
                farmer=farmer,
                request_id=values['request_id'],
                defaults=values,
            )
            return event
        except IntegrityError:
            return JawabuPipelineEvent.objects.get(farmer=farmer, request_id=values['request_id'])
    return JawabuPipelineEvent.objects.create(farmer=farmer, **values)


def _tat_targets() -> dict[str, Any]:
    for config in GroupSheetConfiguration.objects.filter(enabled=True):
        workflow = config.workflow or {}
        if workflow.get('type') in {'jawabu', 'jawabu_homebiogas'} or workflow.get('master_sync_enabled'):
            return workflow.get('jawabu_tat_targets_minutes') or {}
    return {}


def _excluded_deferral_seconds(events, start, end) -> Decimal:
    seconds = Decimal('0')
    deferred_at = None
    for event in events:
        at = event.occurred_at
        if event.action in {'deferral_started', 'deferred'}:
            deferred_at = max(at, start) if at < end else None
        elif event.action in {'deferral_ended', 'reappraisal_restarted'} and deferred_at:
            overlap_end = min(at, end)
            if overlap_end > deferred_at:
                seconds += Decimal(str((overlap_end - deferred_at).total_seconds()))
            deferred_at = None
    if deferred_at and end > deferred_at:
        seconds += Decimal(str((end - deferred_at).total_seconds()))
    return seconds


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


def calculate_case_tat(farmer: JawabuFarmerMaster, *, now=None) -> dict[str, Any]:
    now = now or timezone.now()
    events = list(farmer.pipeline_events.order_by('occurred_at', 'created_at'))
    # A new-unit application starts a fresh TAT cycle. Older events remain in the
    # timeline for audit, but must not be paired with milestones in the new cycle.
    application_events = [event for event in events if event.action == 'application_imported']
    current_events = events
    if application_events:
        current_cycle_started_at = application_events[-1].occurred_at
        current_events = [event for event in events if event.occurred_at >= current_cycle_started_at]
    targets = _tat_targets()
    milestone_events = {}
    for event in current_events:
        if event.action in dict(MILESTONES):
            milestone_events[event.action] = event
    terminal_at = None
    for event in current_events:
        values = event.new_values or {}
        if (
            event.action == 'credit_decision_recorded' and values.get('decision') in {'Rejected'}
            or event.action == 'final_decision_recorded' and values.get('decision') in {'Rejected'}
            or event.action == 'jbl_visit_completed' and values.get('status') in {'Rejected by JBL', 'Cancelled', 'Client Withdrew', 'Opted for Cash'}
            or event.action == 'payment_finalized'
        ):
            terminal_at = event.occurred_at

    stages = []
    total_minutes = Decimal('0')
    complete_stage_count = 0
    for index in range(len(MILESTONES) - 1):
        start_action, start_label = MILESTONES[index]
        end_action, end_label = MILESTONES[index + 1]
        start_event = milestone_events.get(start_action)
        end_event = milestone_events.get(end_action)
        minutes = None
        excluded = Decimal('0')
        if start_event:
            if not end_event and terminal_at and start_event.occurred_at >= terminal_at:
                stages.append({
                    'key': f'{start_action}_to_{end_action}', 'label': f'{start_label} to {end_label}',
                    'started_at': start_event.occurred_at.isoformat(), 'completed_at': None,
                    'minutes': None, 'excluded_deferred_minutes': '0',
                    'target_minutes': None, 'status': '',
                })
                continue
            end_at = end_event.occurred_at if end_event else (terminal_at or now)
            excluded_seconds = _excluded_deferral_seconds(current_events, start_event.occurred_at, end_at)
            elapsed_seconds = max(Decimal('0'), Decimal(str((end_at - start_event.occurred_at).total_seconds())) - excluded_seconds)
            minutes = (elapsed_seconds / Decimal('60')).quantize(Decimal('0.01'))
            excluded = (excluded_seconds / Decimal('60')).quantize(Decimal('0.01'))
            total_minutes += minutes
            if end_event:
                complete_stage_count += 1
        stage_key = f'{start_action}_to_{end_action}'
        target = (targets.get('stages') or {}).get(stage_key)
        stages.append({
            'key': stage_key,
            'label': f'{start_label} to {end_label}',
            'started_at': start_event.occurred_at.isoformat() if start_event else None,
            'completed_at': end_event.occurred_at.isoformat() if end_event else None,
            'minutes': str(minutes) if minutes is not None else None,
            'excluded_deferred_minutes': str(excluded),
            'target_minutes': str(target) if target not in (None, '') else None,
            'status': _sla_status(minutes, target),
        })
    overall_target = targets.get('overall')
    return {
        'tracking_started_at': next((e.occurred_at.isoformat() for e in events if e.action == 'tracking_started'), None),
        'current_cycle_started_at': application_events[-1].occurred_at.isoformat() if application_events else None,
        'previous_cycle_count': max(0, len(application_events) - 1),
        'historical_timestamps_available': bool(milestone_events.get('application_imported')),
        'total_minutes': str(total_minutes) if milestone_events else None,
        'excluded_deferred_minutes': str(sum(Decimal(stage['excluded_deferred_minutes']) for stage in stages)),
        'target_minutes': str(overall_target) if overall_target not in (None, '') else None,
        'status': _sla_status(total_minutes if milestone_events else None, overall_target),
        'completed_stage_count': complete_stage_count,
        'stages': stages,
    }


def serialize_case360(farmer: JawabuFarmerMaster) -> dict[str, Any]:
    validation = validation_warnings(farmer)
    events = farmer.pipeline_events.order_by('occurred_at', 'created_at')
    invoice = ParsedInvoice.objects.filter(matched_farmer=farmer, status='matched').order_by('-updated_at').first()
    requisition = RequisitionBatch.objects.filter(order_number=farmer.order_number).first() if farmer.order_number else None
    payments = PaymentDocument.objects.filter(order_number=farmer.order_number, status='final').order_by('-version') if farmer.order_number else PaymentDocument.objects.none()
    return {
        'sections': {
            'identity': {'customer_name': farmer.customer_name, 'national_id': farmer.national_id, 'primary_phone': farmer.primary_phone, 'secondary_phone': farmer.secondary_phone, 'customer_no': farmer.customer_no, 'unit_number': farmer.unit_number},
            'intake': {'hbg_visit_date': farmer.hbg_visit_date.isoformat() if farmer.hbg_visit_date else farmer.sign_date, 'county': farmer.county, 'constituency': farmer.sub_county, 'ward': farmer.ward, 'village': farmer.village, 'branch': farmer.branch, 'lead_source': farmer.lead_source, 'hb_sales_person': farmer.hb_sales_person, 'deposit_paid_hbg': str(farmer.deposit_paid_hbg) if farmer.deposit_paid_hbg is not None else farmer.actual_receipts},
            'jbl_visit': {'visit_date': farmer.jbl_visit_date.isoformat() if farmer.jbl_visit_date else None, 'officer': farmer.jbl_officer, 'status': farmer.jbl_visit_status, 'comment': farmer.jbl_visit_comment, 'gps_link': farmer.gps_link},
            'credit': {'decision': farmer.credit_decision, 'decided_by': farmer.credit_decided_by, 'decided_at': farmer.credit_decided_at.isoformat() if farmer.credit_decided_at else None, 'imab_created': farmer.imab_created, 'customer_no': farmer.customer_no},
            'final_review': {'decision': farmer.final_decision, 'comment': farmer.final_decision_comment, 'decided_by': farmer.final_decided_by, 'decided_at': farmer.final_decided_at.isoformat() if farmer.final_decided_at else None, 'repayment_day': farmer.repayment_day, 'tenor_months': farmer.repayment_tenor_months},
            'order': {'order_number': farmer.order_number, 'requisition_date': farmer.requisition_date.isoformat() if farmer.requisition_date else None, 'payment_product': farmer.payment_product},
            'invoice': {'number': farmer.invoice_number, 'date': farmer.invoice_date.isoformat() if farmer.invoice_date else None, 'amount': str(farmer.invoice_amount) if farmer.invoice_amount is not None else None, 'discount': str(farmer.discount) if farmer.discount is not None else None, 'payment': str(farmer.payment) if farmer.payment is not None else None, 'balance_due': str(farmer.balance_due) if farmer.balance_due is not None else None},
        },
        'timeline': [{
            'id': str(event.id), 'action': event.action, 'stage': event.stage_key,
            'actor': event.actor, 'source': event.source,
            'old_values': event.old_values, 'new_values': event.new_values,
            'metadata': event.metadata, 'occurred_at': event.occurred_at.isoformat(),
        } for event in events],
        'tat': calculate_case_tat(farmer),
        'validation': validation,
        'documents': {
            'visit_media': [url.strip() for url in farmer.jbl_media_urls.splitlines() if url.strip()],
            'requisition': {'name': requisition.filename, 'url': requisition.drive_url} if requisition and requisition.drive_url else None,
            'invoice': {'name': invoice.batch.original_filename, 'url': invoice.batch.drive_url} if invoice and invoice.batch.drive_url else None,
            'payments': [{'name': item.filename, 'url': item.drive_url, 'version': item.version} for item in payments if item.drive_url],
        },
    }
