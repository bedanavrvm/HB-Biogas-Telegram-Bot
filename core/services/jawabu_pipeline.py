"""
JBL Pipeline queue service.

Provides pure-Django queryset helpers for each pipeline stage, plus the
write functions that advance a farmer record through the workflow. The
credit decision gate is enforced here (server-side) so it is impossible
to bypass via direct API calls.

Stage overview:
  Stage 1 — HB imports farmer via CSV upload          → sign_date populated
  Stage 2 — JBL officer logs site visit               → jbl_visit_date populated
  Stage 3 — Credit analyst records decision            → credit_decision set
  Stage 4 — Admin assigns requisition / order number  → order_number set (GATED)
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from django.conf import settings
from django.utils import timezone
from django.db import transaction
from django.db.models import F, Q

from core.models import JawabuFarmerMaster, JawabuPipelineEvent
from core.services.workflow_transitions import next_workflow_revision, validate_workflow_revision

JBL_MEDIA_CATEGORIES = {
    'LAF': 'LAF document',
    'JBL_VISIT_PHOTO': 'JBL visit photo',
}
JBL_FORWARD_EVIDENCE_CATEGORIES = ('LAF', 'JBL_VISIT_PHOTO')
JBL_SCHEDULING_STATUS = 'JBL to Schedule Visit'

logger = logging.getLogger(__name__)

# ── Approved statuses that signal a client may move to credit review ──────────
JBL_FORWARD_STATUSES = frozenset({
    'Approved',
    'Awaiting Analysis',
})

CREDIT_APPROVED = 'Approved'
CREDIT_TERMINAL = frozenset({'Approved', 'Rejected', 'Deferred', 'Exemption Approved'})
CREDIT_RECORDED_DECISIONS = CREDIT_TERMINAL
FINAL_DECISION_APPROVED = 'Approved'
FINAL_DECISION_TERMINAL = frozenset({'Approved', 'Rejected', 'Deferred'})


class JawabuWorkflowState:
    """Canonical owner of the next operational step for an application."""

    JBL_VISIT = 'jbl_visit'
    CREDIT = 'credit'
    FINAL_REVIEW = 'final_review'
    ORDER = 'order'
    ORDERED = 'ordered'
    DEFERRED = 'deferred'
    REJECTED = 'rejected'
    WITHDRAWN = 'withdrawn'


JAWABU_TERMINAL_STATES = frozenset({
    JawabuWorkflowState.REJECTED,
    JawabuWorkflowState.WITHDRAWN,
    JawabuWorkflowState.ORDERED,
})


def infer_workflow_state(farmer: JawabuFarmerMaster) -> str:
    """Derive a safe initial state for pre-integrity historical records."""
    if farmer.deferred_until:
        return JawabuWorkflowState.DEFERRED
    if farmer.order_number:
        return JawabuWorkflowState.ORDERED
    if farmer.final_decision == 'Approved':
        return JawabuWorkflowState.ORDER
    if farmer.final_decision == 'Rejected':
        return JawabuWorkflowState.REJECTED
    if farmer.final_decision == 'Deferred':
        return JawabuWorkflowState.DEFERRED
    if farmer.credit_decision == 'Rejected':
        return JawabuWorkflowState.REJECTED
    if farmer.credit_decision == 'Deferred':
        return JawabuWorkflowState.DEFERRED
    if farmer.credit_decision in {'Approved', 'Exemption Approved'}:
        return JawabuWorkflowState.FINAL_REVIEW
    if farmer.jbl_visit_status in {'Rejected by JBL'}:
        return JawabuWorkflowState.REJECTED
    if farmer.jbl_visit_status in {'Opted for Cash', 'Opted for other Partner'}:
        return JawabuWorkflowState.WITHDRAWN
    if farmer.jbl_visit_date:
        return JawabuWorkflowState.CREDIT
    return JawabuWorkflowState.JBL_VISIT


def current_workflow_state(farmer: JawabuFarmerMaster) -> str:
    return str(farmer.workflow_state or infer_workflow_state(farmer))


def current_pipeline_state_label(farmer: JawabuFarmerMaster) -> str:
    """Return the concise, staff-facing owner/status for Master Data.

    This is deliberately derived from canonical Django state and immutable
    pipeline events.  Visit/credit/final-decision columns retain the detailed
    historical decision; this label answers only what happens next.
    """
    if is_reappraisal_required(farmer):
        return 'Reappraisal Required'

    state = current_workflow_state(farmer)
    deferred_labels = {
        'jbl_visit': 'Deferred — JBL Visit',
        'credit': 'Deferred — Credit',
        'final': 'Deferred — Head of Rural Review',
        'order': 'Deferred — Order',
        'payment': 'Deferred — Payment',
    }
    if state == JawabuWorkflowState.DEFERRED or farmer.deferred_until:
        return deferred_labels.get(str(farmer.deferred_stage or ''), 'Deferred')

    visit_status = str(farmer.jbl_visit_status or '').strip()
    if visit_status == 'Rejected by JBL':
        return 'Rejected by JBL'
    if visit_status == 'Opted for Cash':
        return 'Closed — Opted for Cash'
    if visit_status == 'Opted for other Partner':
        return 'Closed — Other Partner'
    if state == JawabuWorkflowState.REJECTED:
        if farmer.final_decision == 'Rejected':
            return 'Rejected — Head of Rural Review'
        if farmer.credit_decision == 'Rejected':
            return 'Rejected — Credit'
        return 'Rejected'
    if state == JawabuWorkflowState.WITHDRAWN:
        return 'Withdrawn'

    if farmer.pipeline_events.filter(action='payment_finalized').exists():
        return 'Payment Finalized'
    if farmer.order_number:
        invoice_matched = farmer.parsed_invoices.filter(
            status='matched', matched_farmer=farmer,
        ).exists()
        if invoice_matched:
            return 'Payment Processing'
        return 'Ordered — Awaiting Invoice'

    if state == JawabuWorkflowState.ORDER:
        return 'Ready for Order'
    if state == JawabuWorkflowState.FINAL_REVIEW:
        return 'Awaiting Head of Rural Review'
    if state == JawabuWorkflowState.CREDIT:
        return 'Awaiting Credit Analysis'

    if visit_status == 'Rescheduled':
        return 'JBL Visit Rescheduled'
    if visit_status == 'Deferred / On Hold':
        return 'Deferred — JBL Visit'
    if not farmer.hbg_visit_date and not farmer.sign_date:
        return 'Awaiting HBG Visit'
    return 'Awaiting JBL Visit'


def _advance_state(
    farmer: JawabuFarmerMaster,
    state: str,
    *,
    before_state: str | None = None,
) -> tuple[str, int, int]:
    """Set state entry time only when responsibility actually changes.

    Callers snapshot ``before_state`` before changing decision fields. Those
    fields can themselves influence historical-state inference, so inferring
    after mutation would corrupt the transition audit trail.
    """
    before_state = before_state or current_workflow_state(farmer)
    revision_before, revision_after = next_workflow_revision(farmer)
    farmer.workflow_state = state
    if state != before_state or farmer.workflow_state_entered_at is None:
        farmer.workflow_state_entered_at = timezone.now()
    return before_state, revision_before, revision_after


def _is_actionable_at_stage(
    farmer: JawabuFarmerMaster,
    state: str,
    *,
    deferred_stage: str,
) -> bool:
    """Allow a stage owner to resume only its own non-expired deferral.

    The comparison deliberately uses the canonical persisted state rather than
    the fields being submitted. This prevents a direct API request from
    skipping a team merely by supplying a plausible downstream decision.
    """
    current_state = current_workflow_state(farmer)
    return current_state == state or (
        current_state == JawabuWorkflowState.DEFERRED
        and farmer.deferred_stage == deferred_stage
    )


def _wrong_stage_message(farmer: JawabuFarmerMaster, expected_state: str) -> str:
    return (
        f"This case is currently with {current_workflow_state(farmer).replace('_', ' ')}. "
        f"It must be at {expected_state.replace('_', ' ')} before this action can be recorded."
    )


def is_reappraisal_required(farmer: JawabuFarmerMaster, *, today=None) -> bool:
    today = today or timezone.localdate()
    return bool(farmer.deferred_until and today >= farmer.deferred_until)


def _set_deferral(farmer: JawabuFarmerMaster, stage: str, actor: str, request_id: str = '') -> None:
    now = timezone.now()
    farmer.deferred_at = now
    farmer.deferred_stage = stage
    farmer.deferred_until = timezone.localdate(now) + timedelta(days=90)
    from core.services.jawabu_case360 import record_pipeline_event
    record_pipeline_event(
        farmer, action='deferral_started', stage_key=stage, actor=actor,
        request_id=f'{request_id}:deferred' if request_id else '',
        new_values={'deferred_until': farmer.deferred_until.isoformat()},
    )


def _clear_deferral(farmer: JawabuFarmerMaster, actor: str = '', request_id: str = '') -> None:
    prior_stage = farmer.deferred_stage
    prior_until = farmer.deferred_until
    farmer.deferred_at = None
    farmer.deferred_stage = ''
    farmer.deferred_until = None
    if prior_stage:
        from core.services.jawabu_case360 import record_pipeline_event
        record_pipeline_event(
            farmer, action='deferral_ended', stage_key=prior_stage, actor=actor,
            request_id=f'{request_id}:deferral-ended' if request_id else '',
            old_values={'deferred_until': prior_until.isoformat() if prior_until else None},
        )


def reappraisal_required_queue():
    return JawabuFarmerMaster.objects.filter(
        status='active', deferred_until__lte=timezone.localdate(),
    ).order_by('deferred_until', 'customer_name')


# ── Queue filters ─────────────────────────────────────────────────────────────

def jbl_visit_queue(search: str = ''):
    """
    Stage 2 queue — farmers HB has visited but JBL has not yet called on.

    Filter: HBG Visit Date present AND JBL Visit Date absent.
    """
    qs = JawabuFarmerMaster.objects.filter(
        jbl_visit_date__isnull=True,
        status='active',
    ).filter(Q(hbg_visit_date__isnull=False) | ~Q(sign_date=''))
    search = str(search or '').strip()
    if search:
        qs = qs.filter(
            Q(customer_name__icontains=search)
            | Q(national_id__icontains=search)
            | Q(primary_phone__icontains=search)
            | Q(customer_no__icontains=search)
            | Q(county__icontains=search)
            | Q(branch__icontains=search)
        )
    # The operational hand-off starts with the oldest HBG visit. County is
    # not a workflow ordering key and caused records to appear out of sequence.
    return qs.order_by(F('hbg_visit_date').asc(nulls_last=True), 'sign_date', 'customer_name')



def credit_queue():
    """
    Stage 3 queue - JBL/BRO analysis after a JBL visit.

    Filter: JBL Visit Date present AND Credit Analysis empty or Pending.
    This is still a BRO-facing queue; it is not the Head of Rural gate.
    """
    return JawabuFarmerMaster.objects.filter(
        jbl_visit_date__isnull=False,
        status='active',
    ).exclude(
        Q(credit_decision__in=CREDIT_TERMINAL)
        & ~Q(imab_created='')
        & ~Q(customer_no='')
    ).order_by('jbl_visit_date', 'customer_name')


def final_review_queue():
    """
    Stage 4 queue - Head of Rural final review.

    Filter: BRO/JBL visit done, Credit Analysis set, Final Decision not terminal.
    """
    return JawabuFarmerMaster.objects.filter(
        jbl_visit_date__isnull=False,
        status='active',
    ).exclude(
        credit_decision='',
    ).exclude(
        imab_created='',
    ).exclude(
        customer_no='',
    ).exclude(
        final_decision__in=FINAL_DECISION_TERMINAL,
    ).order_by('credit_decided_at', 'jbl_visit_date', 'customer_name')


def requisition_queue():
    """
    Stage 5 queue - Head of Rural approved, order number not yet assigned.

    Filter: final_decision = Approved AND order_number empty.
    """
    return JawabuFarmerMaster.objects.filter(
        final_decision=FINAL_DECISION_APPROVED,
        order_number='',
        status='active',
    ).order_by('final_decided_at', 'customer_name')


def deferred_queue():
    """
    Deferred / flagged cases - credit not moving forward or final review blocked.
    """
    return JawabuFarmerMaster.objects.filter(
        status='active',
    ).filter(
        Q(final_decision__in=['Rejected', 'Deferred']) |
        Q(credit_decision__in=['Rejected', 'Deferred']) |
        Q(jbl_visit_status__in=['Rejected by JBL', 'Cancelled', 'Client Withdrew', 'Opted for Cash'])
    ).exclude(deferred_until__lte=timezone.localdate()).order_by('-updated_at')

def all_cases(search: str = '', county: str = '', branch: str = ''):
    """
    Full farmer list with optional search, county, and branch filters.
    Aggregates across all groups.
    """
    qs = JawabuFarmerMaster.objects.all()
    if county:
        qs = qs.filter(county__iexact=county)
    if branch:
        qs = qs.filter(branch__iexact=branch)
    if search:
        from django.db.models import Q
        qs = qs.filter(
            Q(customer_name__icontains=search) |
            Q(primary_phone__icontains=search) |
            Q(national_id__icontains=search)
        )
    return qs.order_by('county', 'customer_name')


# ── Queue counts (dashboard) ──────────────────────────────────────────────────


def pipeline_counts() -> dict[str, int]:
    """Return queue counts for all stages - drives the portal dashboard."""
    return {
        'jbl_queue': jbl_visit_queue().count(),
        'credit_queue': credit_queue().count(),
        'final_review_queue': final_review_queue().count(),
        'requisition_queue': requisition_queue().count(),
        'deferred': deferred_queue().count() + reappraisal_required_queue().count(),
        'reappraisal_required': reappraisal_required_queue().count(),
        'total': all_cases().count(),
    }

@transaction.atomic
def log_jbl_visit(
    farmer: JawabuFarmerMaster,
    *,
    visit_date: date,
    officer: str,
    visit_status: str,
    comment: str = '',
    sender: str = '',
    latitude: float | None = None,
    longitude: float | None = None,
    location_unavailable_reason: str = '',
    require_visit_evidence: bool = False,
    county: str | None = None,
    sub_county: str | None = None,
    village: str | None = None,
    request_id: str = '',
    expected_revision: int | None = None,
    actor_user=None,
) -> tuple[bool, str]:
    """
    Record that a JBL officer has visited the farmer (Stage 2 advance).

    Returns (success, error_message).
    """
    from core.services.jawabu_case360 import event_request_already_processed
    # A retry is safe even when a newer action has subsequently changed the
    # record; it must return the prior success rather than masquerade as a
    # stale update conflict.
    source_farmer = farmer
    locked = JawabuFarmerMaster.objects.select_for_update().get(pk=farmer.pk)
    if event_request_already_processed(locked, request_id):
        source_farmer.refresh_from_db()
        return True, ''
    validate_workflow_revision(locked, expected_revision)
    farmer = locked
    if not _is_actionable_at_stage(farmer, JawabuWorkflowState.JBL_VISIT, deferred_stage='jbl_visit'):
        return False, _wrong_stage_message(farmer, JawabuWorkflowState.JBL_VISIT)
    # Validate status value
    valid_statuses = {choice[0] for choice in JawabuFarmerMaster.JBL_VISIT_STATUS_CHOICES}
    if visit_status and visit_status not in valid_statuses:
        return False, f"Invalid JBL visit status: '{visit_status}'"
    if visit_status == JBL_SCHEDULING_STATUS:
        return False, 'Choose the outcome of the JBL visit before logging it.'

    # HBG is always the first field visit in this workflow. Reject a JBL
    # visit dated before that hand-off instead of allowing the timeline to
    # become chronologically impossible.
    from core.services.jawabu_validation import parse_business_date
    hbg_visit_date = farmer.hbg_visit_date or parse_business_date(farmer.sign_date)
    jbl_visit_date = visit_date if isinstance(visit_date, date) else parse_business_date(visit_date)
    if hbg_visit_date and jbl_visit_date and jbl_visit_date < hbg_visit_date:
        return False, 'JBL visit date cannot be earlier than the HBG visit date.'
    if jbl_visit_date is None:
        return False, 'A valid JBL visit date is required.'
    visit_date = jbl_visit_date

    # A forward visit is only meaningful when the required evidence exists.
    # The upload endpoint is idempotent, so callers can safely upload first
    # and retry this transition without creating duplicate files.
    if require_visit_evidence and visit_status in JBL_FORWARD_STATUSES:
        from core.services.jawabu_approvals import JawabuApprovalError, require_visit_evidence
        try:
            require_visit_evidence(farmer)
        except JawabuApprovalError as exc:
            return False, str(exc)
        has_location = latitude is not None and longitude is not None
        if not has_location and not str(location_unavailable_reason or '').strip():
            return False, 'Capture the visit location or explain why location was unavailable before forwarding the case.'

    prior_state = current_workflow_state(farmer)
    farmer.jbl_visit_date = visit_date
    farmer.jbl_officer = str(officer or sender or '').strip()
    farmer.jbl_visit_status = visit_status
    farmer.jbl_visit_comment = str(comment or '').strip()

    if visit_status == 'Deferred / On Hold':
        _set_deferral(farmer, 'jbl_visit', sender or officer, request_id)
        next_state = JawabuWorkflowState.DEFERRED
    elif farmer.deferred_stage == 'jbl_visit':
        _clear_deferral(farmer, sender or officer, request_id)
        next_state = JawabuWorkflowState.CREDIT if visit_status in JBL_FORWARD_STATUSES else JawabuWorkflowState.JBL_VISIT
    elif visit_status == 'Rejected by JBL':
        next_state = JawabuWorkflowState.REJECTED
    elif visit_status in {'Opted for Cash', 'Opted for other Partner'}:
        next_state = JawabuWorkflowState.WITHDRAWN
    elif visit_status in JBL_FORWARD_STATUSES:
        next_state = JawabuWorkflowState.CREDIT
    else:
        next_state = JawabuWorkflowState.JBL_VISIT

    from_state, revision_before, revision_after = _advance_state(
        farmer,
        next_state,
        before_state=prior_state,
    )

    update_fields = [
        'jbl_visit_date', 'jbl_officer', 'jbl_visit_status',
        'jbl_visit_comment', 'updated_at',
        'deferred_at', 'deferred_stage', 'deferred_until',
        'workflow_state', 'workflow_state_entered_at', 'workflow_revision',
    ]

    if county is not None:
        farmer.county = str(county or '').strip()
        update_fields.append('county')
    if sub_county is not None:
        farmer.sub_county = str(sub_county or '').strip()
        update_fields.append('sub_county')
    if village is not None:
        farmer.village = str(village or '').strip()
        update_fields.append('village')

    if latitude is not None and longitude is not None:
        from core.services.jawabu_validation import parse_coordinate
        latitude_value = parse_coordinate(latitude, latitude=True)
        longitude_value = parse_coordinate(longitude, latitude=False)
        if latitude_value is None or longitude_value is None:
            return False, 'Coordinates are outside valid latitude/longitude ranges.'
        farmer.latitude = latitude
        farmer.longitude = longitude
        farmer.latitude_value = latitude_value
        farmer.longitude_value = longitude_value
        farmer.gps_link = f"https://maps.google.com/?q={latitude},{longitude}"
        update_fields.extend(['latitude', 'longitude', 'latitude_value', 'longitude_value', 'gps_link'])

    farmer.save(update_fields=update_fields)
    if visit_status in JBL_FORWARD_STATUSES:
        from core.services.jawabu_approvals import invalidate_material_approvals
        invalidate_material_approvals(
            farmer=farmer,
            changed_fields={'jbl_visit_date', 'jbl_visit_status'},
            actor=actor_user,
            reason='JBL visit evidence or visit details were updated after approval.',
        )
    from core.services.jawabu_case360 import record_pipeline_event
    record_pipeline_event(
        farmer, action='jbl_visit_completed', stage_key='jbl_visit', actor=sender or officer,
        request_id=request_id,
        new_values={
            'visit_date': visit_date.isoformat(),
            'status': visit_status,
            'comment': str(comment or '').strip(),
        },
        actor_user=actor_user,
        transition_code='jawabu.jbl_visit.record',
        from_state=from_state,
        to_state=next_state,
        revision_before=revision_before,
        revision_after=revision_after,
    )
    logger.info(
        'JBL visit logged for farmer %s by %s: %s (coordinates: %s, %s)',
        farmer.id, sender or officer, visit_status, latitude, longitude,
    )
    # External register publication is reserved with this committed workflow
    # change and attempted separately by the Mini App.
    from core.services.portal_publication import reserve_farmer_publication
    reserve_farmer_publication(
        farmer, request_id=request_id, requested_by=actor_user,
        requested_by_label=sender or officer,
    )
    source_farmer.refresh_from_db()
    return True, ''


@transaction.atomic
def preflight_jbl_visit_completion(
    farmer: JawabuFarmerMaster,
    *,
    visit_date: date,
    visit_status: str,
    latitude: float | None = None,
    longitude: float | None = None,
    location_unavailable_reason: str = '',
    expected_revision: int | None = None,
    request_id: str = '',
) -> tuple[bool, str, bool]:
    """Validate a visit-completion payload before Drive receives any evidence.

    Drive objects cannot participate in a database transaction.  This narrow
    preflight therefore rejects invalid/stale submissions before external work,
    while ``log_jbl_visit`` repeats the checks after upload to close races.
    """
    from core.services.jawabu_case360 import event_request_already_processed
    from core.services.jawabu_validation import parse_business_date, parse_coordinate

    locked = JawabuFarmerMaster.objects.select_for_update().get(pk=farmer.pk)
    if event_request_already_processed(locked, request_id):
        return True, '', True
    validate_workflow_revision(locked, expected_revision)
    if not _is_actionable_at_stage(locked, JawabuWorkflowState.JBL_VISIT, deferred_stage='jbl_visit'):
        return False, _wrong_stage_message(locked, JawabuWorkflowState.JBL_VISIT), False
    if visit_status not in {choice[0] for choice in JawabuFarmerMaster.JBL_VISIT_STATUS_CHOICES}:
        return False, f"Invalid JBL visit status: '{visit_status}'", False
    if visit_status == JBL_SCHEDULING_STATUS:
        return False, 'Choose the outcome of the JBL visit before logging it.', False
    hbg_visit_date = locked.hbg_visit_date or parse_business_date(locked.sign_date)
    normalized_date = visit_date if isinstance(visit_date, date) else parse_business_date(visit_date)
    if normalized_date is None:
        return False, 'A valid JBL visit date is required.', False
    if hbg_visit_date and normalized_date < hbg_visit_date:
        return False, 'JBL visit date cannot be earlier than the HBG visit date.', False
    if visit_status in JBL_FORWARD_STATUSES:
        has_location = latitude is not None and longitude is not None
        if not has_location and not str(location_unavailable_reason or '').strip():
            return False, 'Capture the visit location or explain why location was unavailable before forwarding the case.', False
        if has_location and (
            parse_coordinate(latitude, latitude=True) is None
            or parse_coordinate(longitude, latitude=False) is None
        ):
            return False, 'Coordinates are outside valid latitude/longitude ranges.', False
    return True, '', False


def complete_jbl_visit(
    farmer: JawabuFarmerMaster,
    *,
    categorized_files: dict[str, list],
    visit_date: date,
    officer: str,
    visit_status: str,
    comment: str = '',
    sender: str = '',
    latitude: float | None = None,
    longitude: float | None = None,
    location_unavailable_reason: str = '',
    county: str | None = None,
    sub_county: str | None = None,
    village: str | None = None,
    request_id: str = '',
    expected_revision: int | None = None,
    actor_user=None,
) -> tuple[bool, str, dict[str, Any]]:
    """Safely complete a JBL visit from one validated multipart submission.

    The request is retry-safe by the normal pipeline event request key.  If a
    Drive upload succeeds but the final transition cannot be written, the
    response explicitly says that evidence is retained and the visit was not
    logged; a retry reuses stored content hashes instead of duplicating files.
    """
    categories = {
        str(category or '').strip().upper(): list(files or [])
        for category, files in (categorized_files or {}).items()
        if files
    }
    for category, files in categories.items():
        if category not in JBL_MEDIA_CATEGORIES:
            return False, 'Choose a valid visit media category.', {'evidence_saved': False}
        validation_error = _validate_jbl_media_files(files, category)
        if validation_error:
            return False, validation_error, {'evidence_saved': False}

    # A forward visit needs both pieces of evidence.  Check the request and
    # the case's already-linked evidence before touching Drive: an Android
    # file picker can retain a visual filename while omitting that file from
    # the multipart request after an activity switch.
    if visit_status in JBL_FORWARD_STATUSES:
        from core.services.jawabu_approvals import visit_evidence_status

        existing_evidence = visit_evidence_status(farmer)
        missing_categories = [
            category for category in JBL_FORWARD_EVIDENCE_CATEGORIES
            if not categories.get(category) and not existing_evidence.get(category)
        ]
        if missing_categories:
            missing_labels = ', '.join(JBL_MEDIA_CATEGORIES[category] for category in missing_categories)
            return False, (
                'Select the required visit evidence in this submission before forwarding: '
                f'{missing_labels}. Nothing has been uploaded.'
            ), {
                'evidence_saved': False,
                'visit_logged': False,
                'missing_evidence': missing_categories,
            }

    ok, error, already_completed = preflight_jbl_visit_completion(
        farmer,
        visit_date=visit_date,
        visit_status=visit_status,
        latitude=latitude,
        longitude=longitude,
        location_unavailable_reason=location_unavailable_reason,
        expected_revision=expected_revision,
        request_id=request_id,
    )
    if not ok:
        return False, error, {'evidence_saved': False}
    if already_completed:
        farmer.refresh_from_db()
        return True, '', {'already_completed': True, 'evidence_saved': True, 'stored_count': 0}

    if categories:
        uploaded_ok, upload_error, upload_result = append_jbl_media_uploads(
            farmer,
            categorized_files=categories,
            sender=sender,
            actor_user=actor_user,
            captured_at=timezone.now(),
            capture_latitude=latitude,
            capture_longitude=longitude,
            location_unavailable_reason=location_unavailable_reason,
        )
        upload_result = upload_result or {}
        if not uploaded_ok or upload_result.get('errors'):
            return False, upload_error or 'Visit evidence upload is incomplete. The visit was not logged.', {
                **upload_result,
                'evidence_saved': bool(upload_result.get('stored_count')),
                'visit_logged': False,
            }
    else:
        upload_result = {'stored_count': 0, 'skipped_count': 0, 'warnings': [], 'errors': []}

    try:
        transition_ok, transition_error = log_jbl_visit(
            farmer,
            visit_date=visit_date,
            officer=officer,
            visit_status=visit_status,
            comment=comment,
            sender=sender,
            latitude=latitude,
            longitude=longitude,
            location_unavailable_reason=location_unavailable_reason,
            require_visit_evidence=True,
            county=county,
            sub_county=sub_county,
            village=village,
            request_id=request_id,
            expected_revision=expected_revision,
            actor_user=actor_user,
        )
    except ValueError as exc:
        transition_ok, transition_error = False, str(exc)
    if not transition_ok:
        return False, transition_error or 'Visit could not be logged.', {
            **upload_result,
            'evidence_saved': bool(upload_result.get('stored_count')),
            'visit_logged': False,
        }
    farmer.refresh_from_db()
    return True, '', {
        **upload_result,
        'evidence_saved': True,
        'visit_logged': True,
        'already_completed': False,
    }


@transaction.atomic
def set_credit_decision(
    farmer: JawabuFarmerMaster,
    *,
    decision: str,
    imab_created: str = '',
    customer_no: str = '',
    reason_code: str = '',
    sender: str = '',
    request_id: str = '',
    expected_revision: int | None = None,
    actor_user=None,
    access: dict | None = None,
) -> tuple[bool, str]:
    """
    Record the credit analyst's decision (Stage 3 advance).

    Returns (success, error_message).
    """
    from core.services.jawabu_case360 import event_request_already_processed
    source_farmer = farmer
    farmer = JawabuFarmerMaster.objects.select_for_update().get(pk=farmer.pk)
    if event_request_already_processed(farmer, request_id):
        source_farmer.refresh_from_db()
        return True, ''
    validate_workflow_revision(farmer, expected_revision)
    if not _is_actionable_at_stage(farmer, JawabuWorkflowState.CREDIT, deferred_stage='credit'):
        return False, _wrong_stage_message(farmer, JawabuWorkflowState.CREDIT)
    if is_reappraisal_required(farmer):
        return False, 'This deferral has expired. Fresh preappraisal and visit records are required.'
    prior_state = current_workflow_state(farmer)
    valid_decisions = {choice[0] for choice in JawabuFarmerMaster.CREDIT_DECISION_CHOICES}
    if decision not in valid_decisions:
        return False, f"Invalid credit decision: '{decision}'. Must be one of: {', '.join(sorted(valid_decisions))}"
    if decision == 'Pending':
        return False, 'Pending is the initial credit state and cannot be selected as an analyst decision.'

    imab_created = str(imab_created or '').strip()
    customer_no = str(customer_no or '').strip()
    if customer_no and not customer_no.isdigit():
        return False, 'CUSTOMER NO must contain digits only.'
    if decision in CREDIT_RECORDED_DECISIONS:
        if imab_created != 'Yes':
            return False, 'Customer must be created in IMAB before the case can reach Head of Rural review.'
        if not customer_no:
            return False, 'CUSTOMER NO is required once the customer is created in IMAB.'

    from core.services.jawabu_identity import JawabuIdentityConflict, set_customer_number
    try:
        set_customer_number(farmer, customer_no)
    except JawabuIdentityConflict as exc:
        return False, str(exc)

    farmer.credit_decision = decision
    farmer.imab_created = imab_created
    farmer.customer_no = customer_no
    farmer.credit_decided_by = str(sender or '').strip()
    farmer.credit_decided_at = timezone.now()
    if decision == 'Deferred':
        _set_deferral(farmer, 'credit', sender, request_id)
        next_state = JawabuWorkflowState.DEFERRED
    elif farmer.deferred_stage == 'credit':
        _clear_deferral(farmer, sender, request_id)
        if decision in {'Approved', 'Exemption Approved'}:
            next_state = JawabuWorkflowState.FINAL_REVIEW
        else:
            next_state = JawabuWorkflowState.REJECTED
    elif decision in {'Approved', 'Exemption Approved'}:
        next_state = JawabuWorkflowState.FINAL_REVIEW
    else:
        next_state = JawabuWorkflowState.REJECTED
    from_state, revision_before, revision_after = _advance_state(
        farmer,
        next_state,
        before_state=prior_state,
    )
    farmer.save(update_fields=[
        'credit_decision', 'imab_created', 'customer_no',
        'credit_decided_by', 'credit_decided_at', 'updated_at',
        'deferred_at', 'deferred_stage', 'deferred_until',
        'workflow_state', 'workflow_state_entered_at', 'workflow_revision',
    ])
    from core.services.jawabu_approvals import JawabuApprovalError, record_approval
    try:
        record_approval(
            farmer=farmer,
            gate='credit',
            decision=decision,
            reason_code=reason_code,
            actor=actor_user,
            actor_label=sender,
            access=access,
        )
    except JawabuApprovalError as exc:
        transaction.set_rollback(True)
        return False, str(exc)
    from core.services.jawabu_case360 import record_pipeline_event
    record_pipeline_event(
        farmer, action='credit_decision_recorded', stage_key='credit', actor=sender,
        request_id=request_id,
        new_values={'decision': decision, 'imab_created': imab_created, 'customer_no': customer_no, 'reason_code': reason_code},
        actor_user=actor_user,
        transition_code='jawabu.credit.record_decision',
        from_state=from_state,
        to_state=next_state,
        revision_before=revision_before,
        revision_after=revision_after,
    )
    logger.info(
        'Credit decision %s set for farmer %s by %s',
        decision, farmer.id, sender,
    )
    from core.services.portal_publication import reserve_farmer_publication
    reserve_farmer_publication(
        farmer, request_id=request_id, requested_by=actor_user,
        requested_by_label=sender,
    )

    source_farmer.refresh_from_db()
    return True, ''



@transaction.atomic
def set_final_decision(
    farmer: JawabuFarmerMaster,
    *,
    final_decision: str,
    decision_comment: str = '',
    reason_code: str = '',
    repayment_date: str | None = None,
    repayment_tenor: str | None = None,
    sender: str = '',
    request_id: str = '',
    expected_revision: int | None = None,
    actor_user=None,
    access: dict | None = None,
) -> tuple[bool, str]:
    """
    Record Head of Rural final decision. Approved records enter the order queue.

    Returns (success, error_message).
    """
    from core.services.jawabu_case360 import event_request_already_processed
    source_farmer = farmer
    farmer = JawabuFarmerMaster.objects.select_for_update().get(pk=farmer.pk)
    if event_request_already_processed(farmer, request_id):
        source_farmer.refresh_from_db()
        return True, ''
    validate_workflow_revision(farmer, expected_revision)
    if not _is_actionable_at_stage(farmer, JawabuWorkflowState.FINAL_REVIEW, deferred_stage='final'):
        return False, _wrong_stage_message(farmer, JawabuWorkflowState.FINAL_REVIEW)
    if is_reappraisal_required(farmer):
        return False, 'This deferral has expired. Fresh preappraisal and visit records are required.'
    prior_state = current_workflow_state(farmer)
    valid_decisions = {choice[0] for choice in JawabuFarmerMaster.FINAL_DECISION_CHOICES}
    if final_decision not in valid_decisions:
        return False, f"Invalid final decision: '{final_decision}'. Must be one of: {', '.join(sorted(valid_decisions))}"
    if final_decision == 'Under Review':
        return False, 'Under Review is the initial state and cannot be selected as a final decision.'

    if not farmer.jbl_visit_date:
        return False, 'Cannot set final decision before the JBL/BRO visit is logged.'
    if not farmer.credit_decision:
        return False, 'Cannot set final decision before Credit Analysis is completed.'
    if not farmer.imab_created or not farmer.customer_no:
        return False, 'Cannot set final decision before IS CUSTOMER CREATED ON IMAB and CUSTOMER NO are completed in the credit stage.'
    from core.services.jawabu_approvals import JawabuApprovalError, require_effective_approval
    try:
        require_effective_approval(farmer, 'credit')
    except JawabuApprovalError as exc:
        return False, str(exc)

    from core.services.jawabu_validation import parse_repayment_day, parse_tenor_months
    repayment_day = parse_repayment_day(repayment_date) if repayment_date is not None else farmer.repayment_day
    tenor_months = parse_tenor_months(repayment_tenor) if repayment_tenor is not None else farmer.repayment_tenor_months
    if repayment_date and repayment_day is None:
        return False, 'Repayment day must be between 1 and 31.'
    if repayment_tenor and tenor_months is None:
        return False, 'Repayment tenor must be 1 to 120 months.'

    old_decision = farmer.final_decision
    farmer.final_decision = final_decision
    farmer.final_decision_comment = str(decision_comment or '').strip()
    farmer.final_decided_by = str(sender or '').strip()
    farmer.final_decided_at = timezone.now()
    if final_decision == 'Deferred':
        _set_deferral(farmer, 'final', sender, request_id)
        next_state = JawabuWorkflowState.DEFERRED
    elif farmer.deferred_stage == 'final':
        _clear_deferral(farmer, sender, request_id)
        next_state = JawabuWorkflowState.ORDER if final_decision == FINAL_DECISION_APPROVED else (JawabuWorkflowState.REJECTED if final_decision == 'Rejected' else JawabuWorkflowState.FINAL_REVIEW)
    elif final_decision == FINAL_DECISION_APPROVED:
        next_state = JawabuWorkflowState.ORDER
    elif final_decision == 'Rejected':
        next_state = JawabuWorkflowState.REJECTED
    else:
        next_state = JawabuWorkflowState.FINAL_REVIEW
    from_state, revision_before, revision_after = _advance_state(
        farmer,
        next_state,
        before_state=prior_state,
    )

    update_fields = [
        'final_decision', 'final_decision_comment', 'final_decided_by',
        'final_decided_at', 'updated_at',
        'deferred_at', 'deferred_stage', 'deferred_until',
        'workflow_state', 'workflow_state_entered_at', 'workflow_revision',
    ]
    if repayment_date is not None:
        farmer.repayment_date = str(repayment_date or '').strip()
        farmer.repayment_day = repayment_day
        update_fields.extend(['repayment_date', 'repayment_day'])
    if repayment_tenor is not None:
        farmer.repayment_tenor = str(repayment_tenor or '').strip()
        farmer.repayment_tenor_months = tenor_months
        update_fields.extend(['repayment_tenor', 'repayment_tenor_months'])

    farmer.save(update_fields=update_fields)
    from core.services.jawabu_approvals import record_approval
    try:
        record_approval(
            farmer=farmer,
            gate='final_review',
            decision=final_decision,
            reason_code=reason_code,
            comment=decision_comment,
            actor=actor_user,
            actor_label=sender,
            access=access,
        )
    except JawabuApprovalError as exc:
        transaction.set_rollback(True)
        return False, str(exc)
    from core.services.jawabu_case360 import record_pipeline_event
    record_pipeline_event(
        farmer, action='final_decision_recorded', stage_key='final_review', actor=sender,
        request_id=request_id,
        old_values={'decision': old_decision}, new_values={'decision': final_decision, 'reason_code': reason_code},
        actor_user=actor_user,
        transition_code='jawabu.final_review.record_decision',
        from_state=from_state,
        to_state=next_state,
        revision_before=revision_before,
        revision_after=revision_after,
    )
    logger.info(
        'Final decision %s set for farmer %s by %s',
        final_decision, farmer.id, sender,
    )
    from core.services.portal_publication import reserve_farmer_publication
    reserve_farmer_publication(
        farmer, request_id=request_id, requested_by=actor_user,
        requested_by_label=sender,
    )

    if final_decision == FINAL_DECISION_APPROVED and old_decision != FINAL_DECISION_APPROVED:
        _notify_final_approved(farmer)

    source_farmer.refresh_from_db()
    return True, ''



@transaction.atomic
def return_for_rework(
    farmer: JawabuFarmerMaster,
    *,
    target_state: str,
    reason: str,
    sender: str = '',
    request_id: str = '',
    expected_revision: int | None = None,
    actor_user=None,
) -> tuple[bool, str]:
    """Return a live case to an earlier accountable team with an audit reason.

    Rework is intentionally narrow. It cannot silently reopen an ordered case
    or bypass the decision records that establish the downstream workflow.
    """
    from core.services.jawabu_case360 import event_request_already_processed, record_pipeline_event

    source_farmer = farmer
    farmer = JawabuFarmerMaster.objects.select_for_update().get(pk=farmer.pk)
    if event_request_already_processed(farmer, request_id):
        source_farmer.refresh_from_db()
        return True, ''
    validate_workflow_revision(farmer, expected_revision)
    reason = str(reason or '').strip()
    if not reason:
        return False, 'Explain why this case is being returned for rework.'
    if farmer.order_number:
        return False, 'An ordered case cannot be returned for rework. Use the controlled correction process instead.'

    from_state = current_workflow_state(farmer)
    target_state = str(target_state or '').strip()
    update_fields = ['workflow_state', 'workflow_state_entered_at', 'workflow_revision', 'updated_at']
    old_values: dict[str, str] = {}
    new_values: dict[str, str] = {}
    if from_state == JawabuWorkflowState.CREDIT and target_state == JawabuWorkflowState.JBL_VISIT:
        old_values = {'credit_decision': farmer.credit_decision}
        farmer.credit_decision = 'Pending'
        farmer.credit_decided_by = ''
        farmer.credit_decided_at = None
        farmer.final_decision = ''
        farmer.final_decision_comment = ''
        farmer.final_decided_by = ''
        farmer.final_decided_at = None
        update_fields.extend([
            'credit_decision', 'credit_decided_by', 'credit_decided_at',
            'final_decision', 'final_decision_comment', 'final_decided_by', 'final_decided_at',
        ])
        transition_code = 'jawabu.credit.return_to_jbl_visit'
        stage_key = 'credit'
    elif from_state == JawabuWorkflowState.FINAL_REVIEW and target_state == JawabuWorkflowState.CREDIT:
        old_values = {'final_decision': farmer.final_decision}
        farmer.final_decision = ''
        farmer.final_decision_comment = ''
        farmer.final_decided_by = ''
        farmer.final_decided_at = None
        update_fields.extend(['final_decision', 'final_decision_comment', 'final_decided_by', 'final_decided_at'])
        transition_code = 'jawabu.final_review.return_to_credit'
        stage_key = 'final_review'
    else:
        return False, 'This return route is not permitted from the case’s current workflow state.'

    # An explicit rework request takes ownership away from a paused decision;
    # any future deferral must be recorded by the receiving stage again.
    if farmer.deferred_stage:
        _clear_deferral(farmer, sender, request_id)
        update_fields.extend(['deferred_at', 'deferred_stage', 'deferred_until'])
    prior_state, revision_before, revision_after = _advance_state(
        farmer,
        target_state,
        before_state=from_state,
    )
    new_values = {'returned_to': target_state}
    farmer.save(update_fields=list(dict.fromkeys(update_fields)))
    record_pipeline_event(
        farmer,
        action='returned_for_rework',
        stage_key=stage_key,
        actor=sender,
        request_id=request_id,
        old_values=old_values,
        new_values=new_values,
        actor_user=actor_user,
        transition_code=transition_code,
        from_state=prior_state,
        to_state=target_state,
        reason=reason,
        revision_before=revision_before,
        revision_after=revision_after,
    )
    from core.services.portal_publication import reserve_farmer_publication
    reserve_farmer_publication(
        farmer, request_id=request_id, requested_by=actor_user,
        requested_by_label=sender,
    )
    source_farmer.refresh_from_db()
    return True, ''



def _validate_jbl_media_files(uploaded_files: list, media_category: str) -> str:
    """Apply the narrow Portal evidence taxonomy before Drive is called."""
    allowed_laf = {'.pdf', '.jpg', '.jpeg', '.png'}
    allowed_photo = {'.jpg', '.jpeg', '.png', '.webp'}
    allowed = allowed_laf if media_category == 'LAF' else allowed_photo
    minimum_bytes = 4 * 1024
    maximum_bytes = max(1, int(getattr(settings, 'MEDIA_MAX_FILE_SIZE_MB', 20) or 20)) * 1024 * 1024
    for file_obj in uploaded_files or []:
        filename = str(getattr(file_obj, 'name', '') or '').strip()
        chunks = filename.lower().rsplit('.', 1)
        extension = f'.{chunks[-1]}' if len(chunks) == 2 else ''
        if extension not in allowed:
            label = 'a PDF or image' if media_category == 'LAF' else 'an image'
            return f'{JBL_MEDIA_CATEGORIES[media_category]} must be {label}.'
        size = getattr(file_obj, 'size', None)
        if size is not None and int(size) < minimum_bytes:
            return f'{filename or JBL_MEDIA_CATEGORIES[media_category]} is too small to be reliable visit evidence.'
        if size is not None and int(size) > maximum_bytes:
            maximum_mb = maximum_bytes // (1024 * 1024)
            return f'{filename or JBL_MEDIA_CATEGORIES[media_category]} is larger than the {maximum_mb} MB evidence limit.'
    return ''


def append_jbl_media_links(
    farmer: JawabuFarmerMaster,
    *,
    uploaded_files: list,
    sender: str = '',
    media_category: str = 'LAF',
    actor_user=None,
    captured_at=None,
    capture_latitude=None,
    capture_longitude=None,
    location_unavailable_reason: str = '',
) -> tuple[bool, str, dict[str, Any]]:
    """Upload JBL visit media to Drive, append links to farmer/order sheet, and audit uploads."""
    if not uploaded_files:
        return False, 'No files were uploaded.', {}
    media_category = str(media_category or 'LAF').strip().upper()
    if media_category not in JBL_MEDIA_CATEGORIES:
        return False, 'Choose a valid visit media category.', {
            'categories': [{'value': key, 'label': label} for key, label in JBL_MEDIA_CATEGORIES.items()],
        }
    validation_error = _validate_jbl_media_files(uploaded_files, media_category)
    if validation_error:
        return False, validation_error, {}
    # The case reference remains the immutable attachment/audit key. Drive is
    # access-controlled for this workflow, so staff can locate both evidence
    # types in the one customer National-ID folder they expect operationally.
    client_national_id = str(farmer.national_id or '').strip()
    if not client_national_id:
        return False, 'A client National ID is required before visit evidence can be stored.', {}
    storage_key = f'case-{farmer.pk}'

    group_config = _jawabu_group_config()
    if not group_config:
        return False, 'Jawabu workflow group configuration was not found.', {}

    from core.services.order_approval import hash_uploaded_file, store_uploaded_files_for_order

    # Hashes are calculated before storage for a category-local duplicate
    # check.  The generic uploader then reuses an existing Drive object where
    # possible, while these Portal rows preserve the case linkage/audit trail.
    file_hashes = [(file_obj, hash_uploaded_file(file_obj)[0]) for file_obj in uploaded_files]
    content_hashes = {content_hash for _file_obj, content_hash in file_hashes}
    existing_hashes = set(
        farmer.media_attachments.filter(
            file_type=media_category,
            upload_status='success',
            content_hash__in=content_hashes,
        ).values_list('content_hash', flat=True)
    )
    pending_files = [
        file_obj for file_obj, content_hash in file_hashes
        if content_hash not in existing_hashes
    ]
    if not pending_files:
        category_count = farmer.media_attachments.filter(
            file_type=media_category,
            upload_status='success',
        ).count()
        return True, '', {
            'stored_count': 0,
            'skipped_count': len(uploaded_files),
            'warnings': [],
            'links': [],
            'media_count': len([line for line in str(farmer.jbl_media_urls or '').splitlines() if line.strip()]),
            'media_category': media_category,
            'media_categories': {media_category: category_count},
            'duplicate_hashes_reused': len(existing_hashes),
        }

    uploaded = store_uploaded_files_for_order(
        group_config=group_config,
        uploaded_files=pending_files,
        sender=sender,
        received_at=timezone.now(),
        business_key_value=storage_key,
        order_update=None,
        media_category=media_category,
        workflow_key='Jawabu/JBL Visits',
        # Both controlled evidence categories belong in the same client ID
        # folder. The case UUID remains the immutable attachment key above.
        record_type='ID',
        record_key=client_national_id,
        business_key_type='case_reference',
        storage_reference_value=client_national_id,
        storage_reference_prefix='ID',
        jawabu_farmer=farmer,
        captured_at=captured_at,
        capture_latitude=capture_latitude,
        capture_longitude=capture_longitude,
        capture_location_unavailable_reason=location_unavailable_reason,
    )
    if uploaded.links:
        from core.models import MediaAttachment
        linked_rows = MediaAttachment.objects.filter(
            jawabu_farmer__isnull=True,
            business_key_type='case_reference',
            business_key_value=storage_key,
            file_type=media_category,
            upload_status='success',
            content_hash__in=content_hashes,
        )
        linked_rows.update(
            jawabu_farmer=farmer,
            captured_at=captured_at,
            capture_latitude=capture_latitude,
            capture_longitude=capture_longitude,
            capture_location_unavailable_reason=str(location_unavailable_reason or '').strip(),
        )
        existing = [line.strip() for line in str(farmer.jbl_media_urls or '').splitlines() if line.strip()]
        for link in uploaded.links:
            if link and link not in existing:
                existing.append(link)
        # Evidence links are part of the published case representation.  Give
        # them a new revision so a completed publication for an older revision
        # cannot suppress the register update for newly attached media.
        revision_before, revision_after = next_workflow_revision(farmer)
        farmer.jbl_media_urls = '\n'.join(existing)
        farmer.save(update_fields=['jbl_media_urls', 'workflow_revision', 'updated_at'])
        from core.services.jawabu_approvals import invalidate_material_approvals
        invalidate_material_approvals(
            farmer=farmer,
            changed_fields={'jbl_media'},
            reason=f'{JBL_MEDIA_CATEGORIES[media_category]} was uploaded or linked after approval.',
        )
        from core.services.jawabu_case360 import record_pipeline_event
        record_pipeline_event(
            farmer,
            action='jbl_media_uploaded',
            stage_key='jbl_visit',
            actor=sender,
            new_values={
                'category': media_category,
                'stored_count': uploaded.stored_count,
                'duplicate_hashes_reused': len(existing_hashes),
            },
            actor_user=actor_user,
            transition_code='jawabu.jbl_visit.media_uploaded',
            from_state=current_workflow_state(farmer),
            to_state=current_workflow_state(farmer),
            revision_before=revision_before,
            revision_after=revision_after,
        )
        from core.services.portal_publication import reserve_farmer_publication
        reserve_farmer_publication(
            farmer, requested_by=actor_user, requested_by_label=sender,
        )

    from core.models import MediaAttachment
    category_rows = (
        MediaAttachment.objects.filter(
            jawabu_farmer=farmer,
            upload_status='success',
        )
        .values_list('file_type', flat=True)
    )
    category_counts: dict[str, int] = {}
    for category in category_rows:
        category_counts[str(category)] = category_counts.get(str(category), 0) + 1

    if not uploaded.links and uploaded.warnings:
        return False, 'No media files were stored. ' + ' '.join(uploaded.warnings), {
            'stored_count': uploaded.stored_count,
            'skipped_count': uploaded.skipped_count,
            'warnings': uploaded.warnings,
            'links': uploaded.links,
        }

    return True, '', {
        'stored_count': uploaded.stored_count,
        'skipped_count': uploaded.skipped_count,
        'warnings': uploaded.warnings,
        'links': uploaded.links,
        'media_count': len([line for line in str(farmer.jbl_media_urls or '').splitlines() if line.strip()]),
        'media_category': media_category,
        'media_categories': category_counts,
        'duplicate_hashes_reused': len(existing_hashes),
    }


def append_jbl_media_uploads(
    farmer: JawabuFarmerMaster,
    *,
    categorized_files: dict[str, list],
    sender: str = '',
    actor_user=None,
    captured_at=None,
    capture_latitude=None,
    capture_longitude=None,
    location_unavailable_reason: str = '',
) -> tuple[bool, str, dict[str, Any]]:
    """Store LAF and JBL-visit media categories in one visit-form update.

    The Drive/storage primitive remains category-specific so folder routing
    and audit records stay correct. This orchestration layer simply runs the
    selected categories independently and reports partial success explicitly.
    """
    categories = {
        str(category or '').strip().upper(): list(files or [])
        for category, files in (categorized_files or {}).items()
        if files
    }
    if not categories:
        return False, 'No files were uploaded.', {}

    stored_count = 0
    skipped_count = 0
    links: list[str] = []
    warnings: list[str] = []
    errors: list[dict[str, Any]] = []
    media_categories: dict[str, int] = {}
    category_results: dict[str, dict[str, Any]] = {}
    successful_categories = 0

    for category, files in categories.items():
        ok, error, result = append_jbl_media_links(
            farmer,
            uploaded_files=files,
            sender=sender,
            media_category=category,
            actor_user=actor_user,
            captured_at=captured_at,
            capture_latitude=capture_latitude,
            capture_longitude=capture_longitude,
            location_unavailable_reason=location_unavailable_reason,
        )
        result = result or {}
        category_results[category] = {
            'ok': ok,
            'stored_count': result.get('stored_count', 0),
            'skipped_count': result.get('skipped_count', 0),
            'warnings': result.get('warnings', []),
            'links': result.get('links', []),
        }
        if ok:
            successful_categories += 1
            stored_count += int(result.get('stored_count') or 0)
            skipped_count += int(result.get('skipped_count') or 0)
            links.extend(result.get('links') or [])
            warnings.extend(result.get('warnings') or [])
            media_categories.update(result.get('media_categories') or {})
        else:
            errors.append({'category': category, 'error': error or 'Media upload failed.'})

    payload = {
        'stored_count': stored_count,
        'skipped_count': skipped_count,
        'warnings': warnings,
        'links': links,
        'media_count': len([line for line in str(farmer.jbl_media_urls or '').splitlines() if line.strip()]),
        'media_category': 'multiple' if len(categories) > 1 else next(iter(categories)),
        'media_categories': media_categories,
        'category_results': category_results,
        'errors': errors,
        'partial': bool(errors and successful_categories),
    }
    if not successful_categories:
        messages = '; '.join(f"{item['category']}: {item['error']}" for item in errors)
        return False, messages or 'No media files were stored.', payload
    return True, '', payload


@transaction.atomic
def assign_order(
    farmer: JawabuFarmerMaster,
    *,
    order_number: str,
    requisition_date: date | None = None,
    repayment_date: str | None = None,
    repayment_tenor: str | None = None,
    sender: str = '',
    request_id: str = '',
    expected_revision: int | None = None,
    actor_user=None,
) -> tuple[bool, str]:
    """
    Assign an order number and requisition date.

    GATE: Final Decision must be Approved. Returns (success, error_message).
    """
    from core.services.jawabu_case360 import event_request_already_processed
    source_farmer = farmer
    farmer = JawabuFarmerMaster.objects.select_for_update().get(pk=farmer.pk)
    if event_request_already_processed(farmer, request_id):
        source_farmer.refresh_from_db()
        return True, ''
    validate_workflow_revision(farmer, expected_revision)
    if farmer.final_decision != FINAL_DECISION_APPROVED:
        return (
            False,
            f"Cannot assign order - Final Decision is '{farmer.final_decision or 'not set'}', "
            f"not Approved. Complete Head of Rural final review first."
        )
    from core.services.jawabu_approvals import JawabuApprovalError, require_effective_approval
    try:
        require_effective_approval(farmer, 'final_review')
    except JawabuApprovalError as exc:
        return False, str(exc)
    if not _is_actionable_at_stage(farmer, JawabuWorkflowState.ORDER, deferred_stage='order'):
        return False, _wrong_stage_message(farmer, JawabuWorkflowState.ORDER)
    prior_state = current_workflow_state(farmer)

    order_number = str(order_number or '').strip()
    if not order_number:
        return False, 'Order number is required.'

    from core.services.jawabu_validation import parse_business_date, parse_repayment_day, parse_tenor_months
    requested_requisition_date = requisition_date
    if requested_requisition_date is None:
        requested_requisition_date = timezone.localdate()
    elif not isinstance(requested_requisition_date, date):
        requested_requisition_date = parse_business_date(requested_requisition_date)
    if requested_requisition_date is None:
        return False, 'A valid requisition date is required.'

    # An order number identifies one operational batch. Enforce this at the
    # service boundary as well as in the portal preview so imports, scripts, and
    # retries cannot silently split one order across different dates.
    existing_dates = set(
        JawabuFarmerMaster.objects.select_for_update().filter(order_number=order_number)
        .exclude(pk=farmer.pk)
        .exclude(requisition_date__isnull=True)
        .values_list('requisition_date', flat=True)
    )
    if existing_dates and requested_requisition_date not in existing_dates:
        labels = ', '.join(sorted(value.strftime('%d-%B-%Y') for value in existing_dates))
        return False, (
            f'Order number {order_number} already has requisition date {labels}. '
            'Use the same date for this order or choose a new order number.'
        )

    repayment_day = parse_repayment_day(repayment_date) if repayment_date is not None else farmer.repayment_day
    tenor_months = parse_tenor_months(repayment_tenor) if repayment_tenor is not None else farmer.repayment_tenor_months
    if repayment_date and repayment_day is None:
        return False, 'Repayment day must be between 1 and 31.'
    if repayment_tenor and tenor_months is None:
        return False, 'Repayment tenor must be 1 to 120 months.'

    farmer.order_number = order_number
    farmer.requisition_date = requested_requisition_date
    from_state, revision_before, revision_after = _advance_state(
        farmer,
        JawabuWorkflowState.ORDERED,
        before_state=prior_state,
    )
    update_fields = [
        'order_number', 'requisition_date', 'updated_at',
        'workflow_state', 'workflow_state_entered_at', 'workflow_revision',
    ]
    if repayment_date is not None:
        farmer.repayment_date = str(repayment_date or '').strip()
        farmer.repayment_day = repayment_day
        update_fields.extend(['repayment_date', 'repayment_day'])
    if repayment_tenor is not None:
        farmer.repayment_tenor = str(repayment_tenor or '').strip()
        farmer.repayment_tenor_months = tenor_months
        update_fields.extend(['repayment_tenor', 'repayment_tenor_months'])
    farmer.save(update_fields=update_fields)
    from core.services.jawabu_case360 import record_pipeline_event
    record_pipeline_event(
        farmer, action='order_assigned', stage_key='order', actor=sender,
        request_id=request_id,
        new_values={'order_number': order_number, 'requisition_date': farmer.requisition_date.isoformat()},
        actor_user=actor_user,
        transition_code='jawabu.order.assign',
        from_state=from_state,
        to_state=JawabuWorkflowState.ORDERED,
        revision_before=revision_before,
        revision_after=revision_after,
    )
    logger.info(
        'Order %s assigned to farmer %s by %s',
        order_number, farmer.id, sender,
    )
    from core.services.portal_publication import reserve_farmer_publication
    reserve_farmer_publication(
        farmer, request_id=request_id, requested_by=actor_user,
        requested_by_label=sender,
    )
    source_farmer.refresh_from_db()
    return True, ''

def farmer_to_card(farmer: JawabuFarmerMaster) -> dict[str, Any]:
    """Compact farmer representation for queue cards in the portal Mini App."""
    from core.services.jawabu_validation import normalize_date_text

    hbg_visit_date = farmer.hbg_visit_date
    if hbg_visit_date is None and farmer.sign_date:
        from core.services.jawabu_validation import parse_business_date
        hbg_visit_date = parse_business_date(farmer.sign_date)
    from core.services.jawabu_approvals import approval_payload, visit_evidence_status

    return {
        'id': str(farmer.id),
        'workflow_state': current_workflow_state(farmer),
        'current_pipeline_state': current_pipeline_state_label(farmer),
        'workflow_revision': int(farmer.workflow_revision or 1),
        'customer_id': str(farmer.customer_id or ''),
        'unit_number': farmer.unit_number,
        'customer_name': farmer.customer_name,
        'national_id': farmer.national_id,
        'primary_phone': farmer.primary_phone,
        'county': farmer.county,
        'sub_county': farmer.sub_county,
        'village': farmer.village,
        'branch': farmer.branch,
        'hb_sales_person': farmer.hb_sales_person,
        # Keep the legacy text field for compatibility, but never expose a
        # spreadsheet text marker such as ``'15-May-2026`` to the Mini App.
        'sign_date': normalize_date_text(farmer.sign_date),
        'hbg_visit_date': hbg_visit_date.isoformat() if hbg_visit_date else None,
        # Stage 2
        'jbl_visit_date': farmer.jbl_visit_date.isoformat() if farmer.jbl_visit_date else None,
        'jbl_officer': farmer.jbl_officer,
        'jbl_visit_status': farmer.jbl_visit_status,
        'jbl_visit_comment': farmer.jbl_visit_comment,
        # Stage 3
        'credit_decision': farmer.credit_decision or 'Pending',
        'imab_created': farmer.imab_created,
        'customer_no': farmer.customer_no,
        'imab_customer_name': farmer.imab_customer_name,
        'system_branch': farmer.system_branch,
        'system_loan_officer': farmer.system_loan_officer,
        'system_deposit_paid_jbl': str(farmer.system_deposit_paid_jbl) if farmer.system_deposit_paid_jbl is not None else None,
        'repayment_date': farmer.repayment_date,
        'repayment_tenor': farmer.repayment_tenor,
        'payment_product': farmer.payment_product,
        'credit_decided_by': farmer.credit_decided_by,
        'credit_decided_at': (
            farmer.credit_decided_at.isoformat() if farmer.credit_decided_at else None
        ),
        # Stage 4 - Head of Rural final review
        'final_decision': farmer.final_decision,
        'final_decision_comment': farmer.final_decision_comment,
        'final_decided_by': farmer.final_decided_by,
        'final_decided_at': (
            farmer.final_decided_at.isoformat() if farmer.final_decided_at else None
        ),
        'deferred_at': farmer.deferred_at.isoformat() if farmer.deferred_at else None,
        'deferred_stage': farmer.deferred_stage,
        'deferred_until': farmer.deferred_until.isoformat() if farmer.deferred_until else None,
        'reappraisal_required': is_reappraisal_required(farmer),
        # Stage 5
        'requisition_date': farmer.requisition_date.isoformat() if farmer.requisition_date else None,
        'order_number': farmer.order_number,
        # Stage 7 — Invoice
        'invoice_number': farmer.invoice_number,
        'invoice_date': farmer.invoice_date.isoformat() if farmer.invoice_date else None,
        'invoice_amount': str(farmer.invoice_amount) if farmer.invoice_amount is not None else None,
        'discount': str(farmer.discount) if farmer.discount is not None else None,
        'payment': str(farmer.payment) if farmer.payment is not None else None,
        'balance_due': str(farmer.balance_due) if farmer.balance_due is not None else None,
        # Meta
        'pipeline_stage': _pipeline_stage(farmer),
        'updated_at': farmer.updated_at.isoformat(),
        'latitude': farmer.latitude,
        'longitude': farmer.longitude,
        'jbl_media_urls': farmer.jbl_media_urls,
        'jbl_media_count': len([line for line in str(farmer.jbl_media_urls or '').splitlines() if line.strip()]),
        'visit_evidence': visit_evidence_status(farmer),
        'approvals': approval_payload(farmer),
    }


def _pipeline_stage(farmer: JawabuFarmerMaster) -> int:
    """
    Returns the current pipeline stage number (1-7).
    Stage 7 means an invoice has been uploaded for this farmer.
    """
    if is_reappraisal_required(farmer):
        return 1
    if farmer.invoice_number:
        return 7
    if farmer.order_number:
        return 5
    if farmer.final_decision == FINAL_DECISION_APPROVED:
        return 5  # Head of Rural approved, awaiting order/requisition batching.
    if farmer.final_decision:
        return 4
    if farmer.credit_decision and farmer.imab_created and farmer.customer_no:
        return 4  # BRO analysis complete, awaiting Head of Rural review.
    if farmer.credit_decision:
        return 3  # BRO analysis started but IMAB/customer number is still incomplete.
    if farmer.jbl_visit_date:
        return 3
    if farmer.sign_date:
        return 2
    return 1


# ── Google Sheets Sync & Notifications ────────────────────────────────────────


def _sheet_number(value):
    if value is None:
        return ''
    from decimal import Decimal, InvalidOperation
    if not hasattr(value, 'to_integral_value'):
        try:
            value = Decimal(str(value).replace(',', '').strip())
        except (InvalidOperation, ValueError):
            return value
    if value == value.to_integral_value():
        return int(value)
    return float(value)


def _sheet_cell_value(value: Any):
    """Return a JSON-safe Google Sheets cell value without changing local data.

    Django Decimal fields are deliberately retained as ``Decimal`` until the
    external Sheets boundary.  gspread serializes update payloads as JSON, so
    allowing one through here would make an otherwise valid workflow write
    fail after its local validation has completed.
    """
    from decimal import Decimal

    if value is None:
        return ''
    if isinstance(value, Decimal):
        return _sheet_number(value)
    if isinstance(value, datetime):
        return _datetime_text(value)
    if isinstance(value, date):
        return _date_text(value)
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def sync_farmer_to_master_sheet(
    farmer: JawabuFarmerMaster,
    *,
    force_date_columns: bool = False,
) -> bool:
    """
    Sync a farmer's updated pipeline fields to the master Google sheet.

    Also records a LiveSheetRecordChange audit entry for traceability.
    """
    from django.conf import settings
    from core.models import GroupSheetConfiguration, LiveSheetRecordChange
    from core.services.group_config import GroupRegistry
    from core.services.sheets import GoogleSheetsService
    from core.services.jawabu_master import (
        add_master_index_row,
        header_lookup_from_headers,
        build_master_existing_index,
        find_master_row_number,
        first_existing_header,
        master_date_column_indexes,
        set_header_value,
        update_master_sheet_row,
        normalize_header,
    )
    from core.services.sheet_publication import aliases_for

    group_config = None
    # 1. Try GroupRegistry (loaded from settings at startup)
    from core.services.jawabu import is_jawabu_workflow
    for config in GroupRegistry.get_instance().list_groups().values():
        if is_jawabu_workflow(config):
            group_config = config
            break

    # 2. Fallback: query DB directly (covers test environments and admin-only configs)
    if not group_config:
        from core.models import GroupSheetConfiguration
        from core.services.group_config import GroupConfig
        db_config = GroupSheetConfiguration.objects.filter(enabled=True).first()
        if db_config:
            workflow = db_config.workflow or {}
            if workflow.get('type') == 'jawabu' or workflow.get('master_sync_enabled'):
                group_config = GroupConfig(
                    group_id=db_config.group_id,
                    sheet_id=db_config.sheet_id,
                    sheet_name=db_config.sheet_name or '',
                    enabled=db_config.enabled,
                    workflow=workflow,
                )

    if not group_config:
        logger.warning("No group configuration found for sync of farmer %s", farmer.id)
        return False

    workflow = getattr(group_config, 'workflow', None) or {}
    if not workflow.get('master_sync_enabled'):
        logger.info("Master sheet sync is disabled for group %s", group_config.group_id)
        return False

    sheet_id = str(workflow.get('master_sheet_id') or getattr(group_config, 'sheet_id', '') or '').strip()
    sheet_name = str(workflow.get('master_sheet_name') or 'Master Data').strip()
    header_row = int(workflow.get('master_header_row') or 3)
    data_start_row = int(workflow.get('master_data_start_row') or header_row + 2)

    if not sheet_id or not sheet_name:
        logger.warning("Master sheet config incomplete for group %s", group_config.group_id)
        return False

    try:
        service = GoogleSheetsService.get_instance(sheet_id=sheet_id, sheet_name=sheet_name)
        if not service.is_available():
            logger.warning("Google Sheets service unavailable for master sync")
            return False
        sheet = service._sheet

        headers = list(sheet.row_values(header_row))
        header_lookup = header_lookup_from_headers(headers)
        cleaned = {
            'duplicate_key': farmer.duplicate_key,
            'national_id': farmer.national_id,
            'primary_phone': farmer.primary_phone,
        }
        # A successful publication already records the canonical sheet row.
        # Reuse that immutable audit pointer (and verify its identifiers) so a
        # routine case edit does not repeatedly download the entire register.
        # The full-sheet lookup remains only as a safe fallback for legacy
        # records that have never been published by Django.
        candidate_rows = []
        record_keys = [
            str(value).strip() for value in (
                farmer.duplicate_key, farmer.national_id, farmer.primary_phone,
            ) if str(value or '').strip()
        ]
        if record_keys:
            candidate_rows.extend(
                LiveSheetRecordChange.objects.filter(
                    sheet_id=sheet_id,
                    sheet_tab=sheet_name,
                    record_key__in=record_keys,
                ).order_by('-created_at').values_list('row_number', flat=True)[:3]
            )
        if getattr(farmer, 'source_row_number', None):
            candidate_rows.append(farmer.source_row_number)

        row_number = 0
        row_values = None
        for candidate in dict.fromkeys(int(value) for value in candidate_rows if value):
            if candidate < data_start_row:
                continue
            candidate_values = list(sheet.row_values(candidate))
            candidate_index = {}
            add_master_index_row(candidate_index, candidate, candidate_values, header_lookup)
            if find_master_row_number(cleaned, candidate_index) == candidate:
                row_number = candidate
                row_values = candidate_values
                break

        values = None
        if not row_number:
            values = sheet.get_all_values()
            existing = build_master_existing_index(values, header_lookup, data_start_row)
            row_number = find_master_row_number(cleaned, existing)
        if not row_number:
            logger.warning("Farmer %s not found in master sheet rows", farmer.id)
            return False

        # Get row values and pad if needed
        if row_values is None:
            row_values = list(values[row_number - 1]) if row_number - 1 < len(values) else []
        if len(row_values) < len(headers):
            row_values.extend([''] * (len(headers) - len(row_values)))

        # Update pipeline fields
        now_text = timezone.now().strftime('%d-%B-%Y %H:%M')
        changes = {}

        from core.services.jawabu_validation import normalize_date_text, parse_business_date
        hbg_visit_date = farmer.hbg_visit_date or parse_business_date(farmer.sign_date)
        def candidates(field_name, *fallback):
            return list(dict.fromkeys((*aliases_for('jawabu_master', field_name), *fallback)))

        pipeline_fields = {
            'unit_number': (candidates('unit_number', 'Unit Number'), farmer.unit_number),
            'customer_name': (candidates('customer_name', 'Customer Name'), farmer.customer_name),
            'national_id': (candidates('national_id', 'National ID'), farmer.national_id),
            'primary_phone': (candidates('primary_phone', 'Primary Phone'), farmer.primary_phone),
            'secondary_phone': (candidates('secondary_phone', 'Secondary Phone'), farmer.secondary_phone),
            'branch': (candidates('branch', 'Branch'), farmer.branch),
            'hbg_visit_date': (
                candidates('hbg_visit_date', 'Sign Date', 'Sign Date__2'),
                normalize_date_text(hbg_visit_date) if hbg_visit_date else '',
            ),
            'jbl_visit_date': (candidates('jbl_visit_date'), farmer.jbl_visit_date.strftime('%d-%B-%Y') if farmer.jbl_visit_date else ''),
            'jbl_officer': (candidates('jbl_officer'), farmer.jbl_officer),
            'jbl_visit_status': (candidates('jbl_visit_status'), farmer.jbl_visit_status),
            'current_pipeline_state': (candidates('current_pipeline_state'), current_pipeline_state_label(farmer)),
            'jbl_visit_comment': (candidates('jbl_visit_comment'), farmer.jbl_visit_comment),
            'hbg_visit_comment': (candidates('hbg_visit_comment'), farmer.comments),
            'county': (candidates('county'), farmer.county),
            'sub_county': (candidates('sub_county'), farmer.sub_county),
            'ward': (candidates('ward'), farmer.ward),
            'village': (candidates('village'), farmer.village),
            'landmark': (candidates('landmark'), farmer.landmark),
            'lead_source': (candidates('lead_source'), farmer.lead_source),
            'hbg_contract_name': (candidates('hbg_contract_name'), farmer.hbg_contract_name),
            'contract_type': (candidates('contract_type'), farmer.contract_type),
            'installation_status': (candidates('installation_status'), farmer.installation_status),
            'hb_sales_person': (candidates('hb_sales_person'), farmer.hb_sales_person),
            'actual_receipts_currency': (candidates('actual_receipts_currency'), farmer.actual_receipts_currency),
            'credit_decision': (candidates('credit_decision'), farmer.credit_decision),
            'credit_decided_by': (['Credit Decided By', 'Credit Analyst'], farmer.credit_decided_by),
            'credit_decided_at': (['Credit Decided At', 'Credit Decision Date'], _datetime_text(farmer.credit_decided_at)),
            'imab_created': (candidates('imab_created'), farmer.imab_created),
            'customer_no': (candidates('customer_no'), farmer.customer_no),
            'imab_customer_name': (candidates('imab_customer_name'), farmer.imab_customer_name),
            'system_branch': (candidates('system_branch'), farmer.system_branch),
            'system_loan_officer': (candidates('system_loan_officer'), farmer.system_loan_officer),
            'system_deposit_paid_jbl': (candidates('system_deposit_paid_jbl'), _sheet_number(farmer.system_deposit_paid_jbl)),
            'deposit_paid_hbg': (candidates('deposit_paid_hbg'), _sheet_number(farmer.deposit_paid_hbg if farmer.deposit_paid_hbg is not None else farmer.actual_receipts)),
            'repayment_date': (candidates('repayment_date'), farmer.repayment_date),
            'repayment_day': (candidates('repayment_day'), farmer.repayment_day),
            'repayment_tenor': (candidates('repayment_tenor'), farmer.repayment_tenor),
            'repayment_tenor_months': (candidates('repayment_tenor_months'), farmer.repayment_tenor_months),
            'payment_product': (candidates('payment_product'), farmer.payment_product),
            'deferred_stage': (candidates('deferred_stage'), farmer.deferred_stage),
            'deferred_until': (candidates('deferred_until'), _date_text(farmer.deferred_until)),
            'jbl_media_urls': (candidates('jbl_media_urls'), farmer.jbl_media_urls),
            'payment_call_up_comment': (candidates('payment_call_up_comment'), farmer.final_decision_comment),
            'final_decision': (candidates('final_decision'), farmer.final_decision),
            'final_decided_by': (candidates('final_decided_by'), farmer.final_decided_by),
            'final_decided_at': (candidates('final_decided_at'), _datetime_text(farmer.final_decided_at)),
            'requisition_date': (candidates('requisition_date'), _date_text(farmer.requisition_date)),
            'order_number': (candidates('order_number'), farmer.order_number),
            'latitude': (candidates('latitude'), str(farmer.latitude) if farmer.latitude is not None else ''),
            'longitude': (candidates('longitude'), str(farmer.longitude) if farmer.longitude is not None else ''),
            'gps_link': (candidates('gps_link'), farmer.gps_link or ''),
            'invoice_number': (candidates('invoice_number'), farmer.invoice_number),
            'invoice_date': (candidates('invoice_date'), _date_text(farmer.invoice_date)),
            'invoice_amount': (candidates('invoice_amount', 'Total Amount'), _sheet_number(farmer.invoice_amount)),
            'discount': (candidates('discount'), _sheet_number(farmer.discount)),
            'payment': (candidates('payment'), _sheet_number(farmer.payment)),
            'balance_due': (candidates('balance_due'), _sheet_number(farmer.balance_due)),
        }

        for field_name, (candidates, new_val) in pipeline_fields.items():
            header = first_existing_header(header_lookup, candidates)
            if header:
                idx = header_lookup[normalize_header(header)] - 1
                current_val = row_values[idx] if idx < len(row_values) else ''
                is_date_field = field_name in {'hbg_visit_date', 'jbl_visit_date'}
                if force_date_columns and is_date_field and new_val:
                    # A text-looking date may already compare equal while still
                    # being stored as text in Sheets.  Force a USER_ENTERED
                    # rewrite during the one-off repair command.
                    set_header_value(row_values, header_lookup, header, new_val)
                    changes.setdefault(header, {'before': current_val, 'after': new_val})
                elif str(current_val).strip() != str(new_val).strip():
                    set_header_value(row_values, header_lookup, header, new_val)
                    changes[header] = {'before': current_val, 'after': new_val}

        if changes:
            set_header_value(row_values, header_lookup, 'Last Updated At', now_text)
            update_master_sheet_row(
                sheet,
                row_number,
                row_values,
                date_indexes=master_date_column_indexes(headers),
            )

            # Create LiveSheetRecordChange audit entry
            LiveSheetRecordChange.objects.create(
                group_configuration=GroupSheetConfiguration.objects.filter(group_id=group_config.group_id).first(),
                group_id=group_config.group_id,
                sheet_id=sheet_id,
                sheet_tab=sheet_name,
                row_number=row_number,
                record_key=farmer.duplicate_key or farmer.national_id or farmer.primary_phone,
                action='update',
                changed_by='portal',
                changes=changes,
                status='success',
            )
            logger.info("Synced farmer %s changes to master sheet row %s: %s", farmer.id, row_number, changes)
        return True
    except Exception as exc:
        logger.error("Failed to sync farmer %s to master sheet: %s", farmer.id, exc, exc_info=True)
        return False



def _jawabu_group_config():
    """Return the enabled Jawabu workflow group config, if one exists."""
    from core.models import GroupSheetConfiguration
    from core.services.group_config import GroupConfig, GroupRegistry
    from core.services.jawabu import is_jawabu_workflow

    for config in GroupRegistry.get_instance().list_groups().values():
        if is_jawabu_workflow(config):
            return config

    db_config = GroupSheetConfiguration.objects.filter(enabled=True).first()
    if db_config:
        workflow = db_config.workflow or {}
        if workflow.get('type') in {'jawabu', 'jawabu_homebiogas'} or workflow.get('master_sync_enabled'):
            return GroupConfig(
                group_id=db_config.group_id,
                sheet_id=db_config.sheet_id,
                sheet_name=db_config.sheet_name or '',
                enabled=db_config.enabled,
                workflow=workflow,
            )
    return None


def _date_text(value) -> str:
    return value.strftime('%d-%B-%Y') if value else ''


def _datetime_text(value) -> str:
    return value.strftime('%d-%B-%Y %H:%M') if value else ''


def sync_farmer_to_internal_order_sheet(farmer: JawabuFarmerMaster) -> bool:
    """
    Optionally sync the pipeline record to the separate internal Order Sheet.

    Master Data remains the source/pipeline register. This downstream sync is
    enabled per Jawabu workflow with internal_order_sync_enabled and writes to a
    separate spreadsheet so Head of Rural/order staff can filter the order view.
    JBL-side location/GPS fields on the farmer record are treated as the latest
    source and are allowed to overwrite older Master Data location values.
    """
    from core.models import GroupSheetConfiguration, LiveSheetRecordChange
    from core.services.sheets import GoogleSheetsService
    from core.services.jawabu_master import (
        col_letter,
        first_existing_header,
        header_lookup_from_headers,
        master_date_column_indexes,
        normalize_header,
        set_header_value,
        write_master_date_cells,
    )
    from core.services.sheet_publication import aliases_for

    group_config = _jawabu_group_config()
    if not group_config:
        return False
    workflow = getattr(group_config, 'workflow', None) or {}
    if not workflow.get('internal_order_sync_enabled'):
        return False

    sheet_id = str(workflow.get('internal_order_sheet_id') or '').strip()
    sheet_name = str(workflow.get('internal_order_sheet_name') or 'Orders').strip()
    try:
        header_row = max(int(workflow.get('internal_order_header_row') or 2), 1)
    except (TypeError, ValueError):
        header_row = 2
    try:
        data_start_row = max(int(workflow.get('internal_order_data_start_row') or header_row + 1), header_row + 1)
    except (TypeError, ValueError):
        data_start_row = header_row + 1
    if not sheet_id or not sheet_name:
        logger.warning('Internal order sync enabled but sheet ID/tab is incomplete.')
        return False

    try:
        service = GoogleSheetsService.get_instance(sheet_id=sheet_id, sheet_name=sheet_name)
        if not service.is_available():
            logger.warning('Google Sheets service unavailable for internal order sync')
            return False
        sheet = service._sheet
        headers = list(sheet.row_values(header_row))
        header_lookup = header_lookup_from_headers(headers)
        record_keys = [
            str(value).strip() for value in (
                farmer.duplicate_key, farmer.national_id, farmer.primary_phone,
            ) if str(value or '').strip()
        ]
        candidate_rows = []
        if record_keys:
            candidate_rows = list(
                LiveSheetRecordChange.objects.filter(
                    sheet_id=sheet_id,
                    sheet_tab=sheet_name,
                    record_key__in=record_keys,
                ).order_by('-created_at').values_list('row_number', flat=True)[:3]
            )
        row_number = 0
        row_values = None
        for candidate in dict.fromkeys(int(value) for value in candidate_rows if value):
            if candidate < data_start_row:
                continue
            candidate_values = list(sheet.row_values(candidate))
            if _internal_order_row_matches(candidate_values, header_lookup, farmer):
                row_number = candidate
                row_values = candidate_values
                break

        values = None
        if not row_number:
            values = sheet.get_all_values()
            row_number = _find_internal_order_row(values, header_lookup, data_start_row, farmer)
        created = False
        if row_number:
            if row_values is None:
                row_values = list(values[row_number - 1]) if row_number - 1 < len(values) else []
        else:
            row_number = max(len(values) + 1, data_start_row)
            row_values = []
            created = True

        if len(row_values) < len(headers):
            row_values.extend([''] * (len(headers) - len(row_values)))

        current_record_id = _first_value(row_values, header_lookup, ['ORDER RECORD ID', 'Record ID'])
        if not current_record_id and values is None:
            # Older rows without their immutable record key need one safe
            # fallback scan before a new key can be allocated.
            values = sheet.get_all_values()
        record_id = current_record_id or _next_internal_order_record_id(values or [], header_lookup, workflow)
        now_text = timezone.now().strftime('%d-%B-%Y %H:%M')
        changes = {}

        def candidates(field_name, *fallback):
            return list(dict.fromkeys((*aliases_for('internal_order', field_name), *fallback)))

        def put(candidates: list[str], value):
            header = first_existing_header(header_lookup, candidates)
            if not header:
                return
            value = _sheet_cell_value(value)
            idx = header_lookup[normalize_header(header)] - 1
            current = row_values[idx] if 0 <= idx < len(row_values) else ''
            if str(current or '').strip() != str(value or '').strip():
                set_header_value(row_values, header_lookup, header, value)
                changes[header] = {'before': current, 'after': value}

        put(candidates('order_record_id'), record_id)
        put(candidates('order_number'), farmer.order_number)
        put(candidates('requisition_date'), _date_text(farmer.requisition_date))
        put(candidates('hbg_visit_date'), _date_text(farmer.hbg_visit_date))
        put(candidates('jbl_visit_date'), _date_text(farmer.jbl_visit_date))
        put(candidates('customer_name'), farmer.customer_name)
        put(candidates('branch'), farmer.branch)
        put(candidates('system_branch'), farmer.system_branch)
        put(candidates('national_id'), farmer.national_id)
        put(candidates('primary_phone'), farmer.primary_phone)
        put(candidates('secondary_phone'), farmer.secondary_phone)
        put(candidates('county'), farmer.county)
        put(candidates('sub_county'), farmer.sub_county)
        put(candidates('ward'), farmer.ward)
        put(candidates('village'), farmer.village)
        put(candidates('landmark'), farmer.landmark or farmer.village)
        put(candidates('gps_link'), farmer.gps_link)
        put(candidates('latitude'), farmer.latitude)
        put(candidates('longitude'), farmer.longitude)
        put(candidates('jbl_officer'), farmer.jbl_officer)
        put(candidates('system_loan_officer'), farmer.system_loan_officer)
        put(candidates('hb_sales_person'), farmer.hb_sales_person)
        put(
            candidates('deposit_paid_hbg'),
            farmer.deposit_paid_hbg if farmer.deposit_paid_hbg is not None else farmer.actual_receipts,
        )
        put(candidates('system_deposit_paid_jbl'), farmer.system_deposit_paid_jbl if farmer.system_deposit_paid_jbl is not None else 0)
        put(candidates('hbg_visit_comment'), farmer.comments)
        put(candidates('jbl_visit_comment'), farmer.jbl_visit_comment)
        put(candidates('current_pipeline_state'), current_pipeline_state_label(farmer))
        put(candidates('credit_decision'), farmer.credit_decision)
        put(candidates('imab_created'), farmer.imab_created)
        put(candidates('customer_no'), farmer.customer_no)
        put(candidates('repayment_date'), farmer.repayment_date)
        put(candidates('repayment_tenor'), farmer.repayment_tenor)
        put(candidates('payment_product'), farmer.payment_product)
        put(candidates('payment_call_up_comment'), farmer.final_decision_comment)
        put(candidates('final_decision'), farmer.final_decision)
        put(candidates('jbl_media_urls'), farmer.jbl_media_urls)
        put(candidates('deferred_stage'), farmer.deferred_stage)
        put(candidates('deferred_until'), _date_text(farmer.deferred_until))
        put(candidates('final_decided_by'), farmer.final_decided_by)
        put(candidates('final_decided_at'), _datetime_text(farmer.final_decided_at))
        put(['Duplicate Key'], farmer.duplicate_key)
        put(['Last Updated At'], now_text)

        if not changes:
            return True
        end_col = col_letter(max(len(headers), len(row_values)))
        sheet.update(f'A{row_number}:{end_col}{row_number}', [row_values], value_input_option='RAW')
        write_master_date_cells(
            sheet,
            [(row_number, row_values)],
            master_date_column_indexes(headers),
        )
        LiveSheetRecordChange.objects.create(
            group_configuration=GroupSheetConfiguration.objects.filter(group_id=group_config.group_id).first(),
            group_id=group_config.group_id,
            sheet_id=sheet_id,
            sheet_tab=sheet_name,
            row_number=row_number,
            record_key=farmer.duplicate_key or farmer.national_id or farmer.primary_phone,
            action='create' if created else 'update',
            changed_by='portal',
            changes=changes,
            status='success',
        )
        logger.info('Synced farmer %s to internal order sheet row %s: %s', farmer.id, row_number, changes)
        return True
    except Exception as exc:
        logger.error('Failed to sync farmer %s to internal order sheet: %s', farmer.id, exc, exc_info=True)
        return False


def _find_internal_order_row(values: list[list[str]], header_lookup: dict[str, int], data_start_row: int, farmer: JawabuFarmerMaster) -> int:
    for row_number in range(data_start_row, len(values) + 1):
        row = values[row_number - 1]
        if _internal_order_row_matches(row, header_lookup, farmer):
            return row_number
    return 0


def _internal_order_row_matches(row: list[str], header_lookup: dict[str, int], farmer: JawabuFarmerMaster) -> bool:
    """Match one controlled internal-order row without downloading the tab."""
    national_id = str(farmer.national_id or '').strip()
    primary_phone = str(farmer.primary_phone or '').strip()
    duplicate_key = str(farmer.duplicate_key or '').strip()
    row_id = _first_value(row, header_lookup, ['ID NUMBER', 'National ID'])
    row_phone = _first_value(row, header_lookup, ['CONTACTS / PRIMARY', 'Primary Phone', 'First Phone Number'])
    row_duplicate = _first_value(row, header_lookup, ['Duplicate Key'])
    return bool(
        (duplicate_key and row_duplicate == duplicate_key)
        or (national_id and primary_phone and row_id == national_id and row_phone == primary_phone)
        or (national_id and row_id == national_id)
        or (primary_phone and row_phone == primary_phone)
    )


def _first_value(row_values: list, header_lookup: dict[str, int], candidates: list[str]) -> str:
    from core.services.jawabu_master import normalize_header
    for header in candidates:
        index = header_lookup.get(normalize_header(header), 0) - 1
        if 0 <= index < len(row_values):
            value = str(row_values[index] or '').strip()
            if value:
                return value
    return ''


def _next_internal_order_record_id(values: list[list[str]], header_lookup: dict[str, int], workflow: dict) -> str:
    import re
    from core.services.jawabu_master import normalize_header
    prefix = str(workflow.get('internal_order_record_id_prefix') or 'JBL').strip() or 'JBL'
    index = header_lookup.get(normalize_header('ORDER RECORD ID'), 0) - 1
    max_number = 0
    if index >= 0:
        pattern = re.compile(rf'^{re.escape(prefix)}-(\d+)$', re.IGNORECASE)
        for row in values:
            if index >= len(row):
                continue
            match = pattern.match(str(row[index] or '').strip())
            if match:
                max_number = max(max_number, int(match.group(1)))
    return f'{prefix}-{max_number + 1}'

def _notify_final_approved(farmer: JawabuFarmerMaster) -> None:
    """Notify the Telegram group when Head of Rural approves a record for order."""
    from django.conf import settings
    import requests

    # Find the group ID configured with jawabu workflow
    from core.services.group_config import GroupRegistry
    from core.services.jawabu import is_jawabu_workflow
    chat_id = None
    for config in GroupRegistry.get_instance().list_groups().values():
        if is_jawabu_workflow(config):
            chat_id = config.group_id
            break

    chat_id = chat_id or getattr(settings, 'TELEGRAM_DEFAULT_CHAT_ID', None)
    bot_token = getattr(settings, 'TELEGRAM_BOT_TOKEN', None)
    if not chat_id or not bot_token:
        return

    text = (
        f"🎉 *Final Decision Approved* for:\n"
        f"👤 *Farmer:* {farmer.customer_name or 'Unknown'}\n"
        f"🆔 *ID:* {farmer.national_id or '—'}\n"
        f"📞 *Phone:* {farmer.primary_phone or '—'}\n"
        f"📍 *County:* {farmer.county or '—'}\n\n"
        f"This record is ready for order batching in the Pipeline Portal!"
    )
    url = f'https://api.telegram.org/bot{bot_token}/sendMessage'
    try:
        requests.post(
            url,
            data={'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'},
            timeout=5,
        )
    except Exception as exc:
        logger.warning("Failed to send final approval notification to Telegram: %s", exc)
