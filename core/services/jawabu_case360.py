"""Case 360 timeline and TAT projection for the Jawabu Portal Mini App."""

from __future__ import annotations

from datetime import date, datetime, timedelta
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
from core.services.business_calendar import business_minutes_between, wall_clock_minutes_between
from core.services.jawabu_validation import parse_business_date, parse_money, validation_warnings
from core.services.workflow_escalations import latest_escalation
from core.services.workflow_timeline import jawabu_case_timeline


MILESTONES = (
    ('application_imported', 'Intake completed'),
    ('jbl_visit_completed', 'JBL visit completed'),
    ('credit_decision_recorded', 'Credit decision recorded'),
    ('final_decision_recorded', 'Final decision recorded'),
    ('order_assigned', 'Order assigned'),
    ('invoice_confirmed', 'Invoice confirmed'),
    ('payment_finalized', 'Payment finalized'),
)


def _case_date(value: Any) -> str | None:
    parsed = value if isinstance(value, date) else parse_business_date(value)
    return parsed.strftime('%d-%B-%Y') if parsed else None


def _case_datetime(value: Any) -> str | None:
    if not value:
        return None
    if isinstance(value, datetime):
        displayed = timezone.localtime(value) if timezone.is_aware(value) else value
        return displayed.strftime('%d-%B-%Y %H:%M')
    parsed = parse_business_date(value)
    return parsed.strftime('%d-%B-%Y') if parsed else None


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


def _deferral_intervals(events, start, end) -> list[tuple[datetime, datetime]]:
    """Return only the formally approved deferred/reappraisal exclusions."""
    intervals: list[tuple[datetime, datetime]] = []
    deferred_at = None
    for event in events:
        at = event.occurred_at
        if event.action in {'deferral_started', 'deferred'}:
            deferred_at = max(at, start) if at < end else None
        elif event.action in {'deferral_ended', 'reappraisal_restarted'} and deferred_at:
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
    total_business_minutes = Decimal('0')
    total_sla_minutes = Decimal('0')
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
                    'minutes': None, 'wall_clock_minutes': None,
                    'business_minutes': None, 'sla_minutes': None,
                    'excluded_deferred_minutes': '0', 'excluded_business_minutes': '0',
                    'target_minutes': None, 'status': '',
                })
                continue
            end_at = end_event.occurred_at if end_event else (terminal_at or now)
            intervals = _deferral_intervals(current_events, start_event.occurred_at, end_at)
            excluded_seconds = _excluded_deferral_seconds(current_events, start_event.occurred_at, end_at)
            raw_wall_clock_minutes = wall_clock_minutes_between(start_event.occurred_at, end_at) or Decimal('0')
            raw_business_minutes = business_minutes_between(start_event.occurred_at, end_at) or Decimal('0')
            excluded_business_minutes = sum(
                (business_minutes_between(interval_start, interval_end) or Decimal('0') for interval_start, interval_end in intervals),
                Decimal('0'),
            )
            minutes = max(Decimal('0'), raw_wall_clock_minutes - (excluded_seconds / Decimal('60'))).quantize(Decimal('0.01'))
            business_minutes = raw_business_minutes.quantize(Decimal('0.01'))
            sla_minutes = max(Decimal('0'), business_minutes - excluded_business_minutes).quantize(Decimal('0.01'))
            excluded = (excluded_seconds / Decimal('60')).quantize(Decimal('0.01'))
            total_minutes += minutes
            total_business_minutes += business_minutes
            total_sla_minutes += sla_minutes
            if end_event:
                complete_stage_count += 1
        else:
            business_minutes = None
            sla_minutes = None
            excluded_business_minutes = Decimal('0')
        stage_key = f'{start_action}_to_{end_action}'
        target = (targets.get('stages') or {}).get(stage_key)
        stages.append({
            'key': stage_key,
            'label': f'{start_label} to {end_label}',
            'started_at': start_event.occurred_at.isoformat() if start_event else None,
            'completed_at': end_event.occurred_at.isoformat() if end_event else None,
            # ``minutes`` is the historical wall-clock-compatible value.
            # New consumers must use ``sla_minutes`` for official status.
            'minutes': str(minutes) if minutes is not None else None,
            'wall_clock_minutes': str(minutes) if minutes is not None else None,
            'business_minutes': str(business_minutes) if business_minutes is not None else None,
            'sla_minutes': str(sla_minutes) if sla_minutes is not None else None,
            'excluded_deferred_minutes': str(excluded),
            'excluded_business_minutes': str(excluded_business_minutes),
            'target_minutes': str(target) if target not in (None, '') else None,
            'status': _sla_status(sla_minutes, target),
        })
    overall_target = targets.get('overall')
    return {
        'tracking_started_at': next((e.occurred_at.isoformat() for e in events if e.action == 'tracking_started'), None),
        'current_cycle_started_at': application_events[-1].occurred_at.isoformat() if application_events else None,
        'previous_cycle_count': max(0, len(application_events) - 1),
        'historical_timestamps_available': bool(milestone_events.get('application_imported')),
        'total_minutes': str(total_minutes) if milestone_events else None,
        'wall_clock_minutes': str(total_minutes) if milestone_events else None,
        'business_minutes': str(total_business_minutes) if milestone_events else None,
        'sla_minutes': str(total_sla_minutes) if milestone_events else None,
        'excluded_deferred_minutes': str(sum(Decimal(stage['excluded_deferred_minutes']) for stage in stages)),
        'excluded_business_minutes': str(sum(Decimal(stage['excluded_business_minutes']) for stage in stages)),
        'target_minutes': str(overall_target) if overall_target not in (None, '') else None,
        'status': _sla_status(total_sla_minutes if milestone_events else None, overall_target),
        'completed_stage_count': complete_stage_count,
        'stages': stages,
    }


def serialize_case360(farmer: JawabuFarmerMaster) -> dict[str, Any]:
    validation = validation_warnings(farmer)
    timeline_projection = jawabu_case_timeline(farmer)
    invoice = ParsedInvoice.objects.filter(matched_farmer=farmer, status='matched').order_by('-updated_at').first()
    requisition = (
        RequisitionBatch.objects.filter(order_number=farmer.order_number)
        .order_by('-updated_at', '-version')
        .first()
        if farmer.order_number else None
    )
    payment_documents = _payment_documents_for_farmer(farmer)
    payment_comment = _payment_comment_for_farmer(farmer, payment_documents)
    payments = _latest_payment_documents(
        [document for document in payment_documents if document.status == 'final']
    )
    return {
        'sections': {
            'identity': {'customer_name': farmer.customer_name, 'system_name': farmer.imab_customer_name, 'national_id': farmer.national_id, 'primary_phone': farmer.primary_phone, 'secondary_phone': farmer.secondary_phone, 'customer_no': farmer.customer_no, 'unit_number': farmer.unit_number},
            # Ward is retained for source/import compatibility, but is not a
            # captured or used field in the staff-facing case history.
            'intake': {'hbg_visit_date': _case_date(farmer.hbg_visit_date or farmer.sign_date), 'county': farmer.county, 'constituency': farmer.sub_county, 'village': farmer.village, 'branch': farmer.branch, 'lead_source': farmer.lead_source, 'hb_sales_person': farmer.hb_sales_person, 'deposit_paid_hbg': _case_amount(farmer.deposit_paid_hbg if farmer.deposit_paid_hbg is not None else farmer.actual_receipts)},
            'jbl_visit': {'visit_date': _case_date(farmer.jbl_visit_date), 'officer': farmer.jbl_officer, 'system_loan_officer': farmer.system_loan_officer or farmer.jbl_officer, 'status': farmer.jbl_visit_status, 'comment': farmer.jbl_visit_comment, 'gps_link': farmer.gps_link},
            'credit': {'decision': farmer.credit_decision, 'decided_by': farmer.credit_decided_by, 'decided_at': _case_datetime(farmer.credit_decided_at), 'imab_created': farmer.imab_created, 'customer_no': farmer.customer_no},
            'final_review': {'decision': farmer.final_decision, 'comment': farmer.final_decision_comment, 'payment_comment': payment_comment, 'decided_by': farmer.final_decided_by, 'decided_at': _case_datetime(farmer.final_decided_at), 'repayment_day': farmer.repayment_day, 'tenor_months': farmer.repayment_tenor_months},
            'order': {'order_number': farmer.order_number, 'requisition_date': _case_date(farmer.requisition_date), 'payment_product': farmer.payment_product},
            'invoice': {'number': farmer.invoice_number, 'date': _case_date(farmer.invoice_date), 'amount': _case_amount(farmer.invoice_amount), 'discount': _case_amount(farmer.discount), 'payment': _case_amount(farmer.payment), 'balance_due': _case_amount(farmer.balance_due)},
        },
        'timeline': timeline_projection['entries'],
        'related_cases': timeline_projection['related_cases'],
        'tat': calculate_case_tat(farmer),
        'escalation': latest_escalation('jawabu_pipeline', str(farmer.pk)),
        'validation': validation,
        'documents': {
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
