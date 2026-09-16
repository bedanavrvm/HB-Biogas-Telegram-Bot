"""Invoice/applicant identity verification and controlled invoice-name changes."""
from __future__ import annotations

import re
import uuid
import hashlib
import json

from django.db import transaction
from django.utils import timezone

from core.models import (
    InvoiceIdentityReview,
    InvoiceNameChangeBatch,
    InvoiceNameChangeItem,
    InvoiceNameChangeLetterArtifact,
    InvoiceUploadBatch,
    JawabuCustomer,
    JawabuDataQualityIssue,
    JawabuFarmerMaster,
    JawabuHouseholdRelationship,
    JawabuRelatedPerson,
    ParsedInvoice,
)
from core.services.identifiers import normalize_kenyan_phone, normalize_national_id


def _record_case_event(farmer, *, action: str, actor: str, request_id: str, metadata: dict) -> None:
    from core.services.jawabu_case360 import record_pipeline_event
    record_pipeline_event(
        farmer,
        action=action,
        stage_key='invoice',
        actor=actor,
        request_id=request_id,
        source='invoice_identity',
        metadata=metadata,
    )


def normalize_person_name(value: str) -> str:
    return ' '.join(re.sub(r'[^A-Z0-9]+', ' ', str(value or '').upper()).split())


def invoice_identity(invoice: ParsedInvoice) -> dict:
    return {
        'name': str(invoice.customer_name or '').strip(),
        'national_id': str(invoice.customer_id or '').strip(),
        'phone': str(invoice.customer_phone or '').strip(),
        'normalized_name': normalize_person_name(invoice.customer_name),
        'normalized_national_id': normalize_national_id(invoice.customer_id),
        'normalized_phone': normalize_kenyan_phone(invoice.customer_phone),
    }


def applicant_identity(farmer: JawabuFarmerMaster) -> dict:
    name = str(farmer.imab_customer_name or farmer.customer_name or '').strip()
    return {
        'name': name,
        'national_id': str(farmer.national_id or '').strip(),
        'phone': str(farmer.primary_phone or '').strip(),
        'normalized_name': normalize_person_name(name),
        'normalized_national_id': normalize_national_id(farmer.national_id),
        'normalized_phone': normalize_kenyan_phone(farmer.primary_phone),
    }


def discrepancy_codes(invoice: ParsedInvoice, farmer: JawabuFarmerMaster) -> list[str]:
    supplied = invoice_identity(invoice)
    expected = applicant_identity(farmer)
    codes: list[str] = []
    if not supplied['normalized_national_id'] or not expected['normalized_national_id']:
        codes.append('national_id_missing')
    elif supplied['normalized_national_id'] != expected['normalized_national_id']:
        codes.append('national_id_mismatch')
    if supplied['normalized_name'] != expected['normalized_name']:
        codes.append('name_variance')
    if supplied['normalized_phone'] and expected['normalized_phone'] and supplied['normalized_phone'] != expected['normalized_phone']:
        codes.append('phone_mismatch')
    return codes


def ensure_identity_review(
    invoice: ParsedInvoice,
    farmer: JawabuFarmerMaster,
    *,
    client_request_id: str = '',
) -> InvoiceIdentityReview | None:
    """Create the single pending review required by a material identity variance."""
    codes = discrepancy_codes(invoice, farmer)
    # Name spelling and phone differences are useful context, but a matching
    # national ID is sufficient to continue. Only missing/different IDs create
    # a workflow gate.
    if not any(code in {'national_id_missing', 'national_id_mismatch'} for code in codes):
        return None
    client_request_id = str(client_request_id or '').strip()
    if client_request_id:
        prior = InvoiceIdentityReview.objects.filter(client_request_id=client_request_id).first()
        if prior:
            if prior.invoice_id != invoice.id:
                raise ValueError('That retry key belongs to another invoice identity review.')
            return prior
    existing = invoice.identity_reviews.filter(status=InvoiceIdentityReview.STATUS_PENDING).first()
    if existing:
        if existing.farmer_id == farmer.id:
            existing.discrepancy_codes = codes
            existing.invoice_identity = invoice_identity(invoice)
            existing.applicant_identity = applicant_identity(farmer)
            existing.save(update_fields=[
                'discrepancy_codes', 'invoice_identity', 'applicant_identity', 'updated_at',
            ])
            return existing
        existing.status = InvoiceIdentityReview.STATUS_CANCELLED
        existing.decision_note = 'Invoice was rematched to another applicant.'
        existing.decided_by = 'system'
        existing.decided_at = timezone.now()
        existing.save(update_fields=['status', 'decision_note', 'decided_by', 'decided_at', 'updated_at'])
    return InvoiceIdentityReview.objects.create(
        invoice=invoice,
        farmer=farmer,
        discrepancy_codes=codes,
        invoice_identity=invoice_identity(invoice),
        applicant_identity=applicant_identity(farmer),
        client_request_id=client_request_id,
    )


def identity_gate(invoice: ParsedInvoice, farmer: JawabuFarmerMaster) -> dict:
    from core.services.invoice_parser import official_requisition_eligibility

    match_eligibility = official_requisition_eligibility(farmer)
    codes = discrepancy_codes(invoice, farmer)
    material_codes = [code for code in codes if code in {'national_id_missing', 'national_id_mismatch'}]
    reviews = invoice.identity_reviews.filter(farmer=farmer).order_by('-created_at')
    latest = reviews.first()
    open_change = invoice.name_change_requests.filter(
        status__in=['draft', 'awaiting_replacement'],
    ).select_related('batch', 'review').first()
    latest_change = open_change or invoice.name_change_requests.select_related('batch', 'review').order_by('-created_at').first()
    if not match_eligibility['eligible']:
        blocker = match_eligibility['code']
    elif open_change and open_change.review.status == InvoiceIdentityReview.STATUS_PENDING:
        blocker = 'invoice_identity_verification_pending'
    elif open_change:
        blocker = 'invoice_name_change_pending'
    elif not material_codes:
        blocker = ''
    elif latest and latest.status == InvoiceIdentityReview.STATUS_SAME_PERSON:
        blocker = ''
    elif latest and latest.status == InvoiceIdentityReview.STATUS_DIFFERENT_PERSON:
        blocker = 'invoice_name_change_required'
    elif latest and latest.status == InvoiceIdentityReview.STATUS_FLAGGED:
        blocker = 'invoice_identity_flagged'
    else:
        blocker = 'invoice_identity_verification_pending'
    if not match_eligibility['eligible']:
        presentation_status = 'Invalid match - no finalized order'
    elif latest_change:
        if latest_change.status == 'completed':
            presentation_status = 'Corrected'
        elif latest_change.status in {'cancelled', 'withdrawn'}:
            presentation_status = 'Cancelled'
        elif latest_change.status == 'awaiting_replacement':
            presentation_status = 'Waiting for corrected invoice'
        elif latest_change.batch_id and latest_change.batch.letter_artifacts.exists():
            presentation_status = 'Letter ready'
        else:
            presentation_status = 'Correction required'
    elif 'national_id_mismatch' in material_codes:
        presentation_status = 'Correction required'
    elif 'national_id_missing' in material_codes:
        presentation_status = 'Correction required'
    else:
        presentation_status = 'Matched'
    return {
        'discrepancy_codes': codes,
        'requires_verification': bool(material_codes),
        'blocker': blocker,
        'review': serialize_review(latest) if latest else None,
        'name_change': serialize_name_change_item(latest_change) if latest_change else None,
        'status_label': presentation_status,
        'invoice_identity': invoice_identity(invoice),
        'applicant_identity': applicant_identity(farmer),
        'lead_identity': {
            'name': farmer.lead_name or farmer.customer_name,
            'national_id': farmer.lead_national_id or farmer.national_id,
            'phone': farmer.lead_primary_phone or farmer.primary_phone,
        },
        'match_eligibility': match_eligibility,
    }


def serialize_review(review: InvoiceIdentityReview | None) -> dict | None:
    if not review:
        return None
    return {
        'id': str(review.id),
        'status': review.status,
        'discrepancy_codes': review.discrepancy_codes or [],
        # Specialist escalation notes are intentionally not part of the
        # general invoice projection. The authorized detail endpoint adds
        # them back for invoice-identity managers only.
        'decision_note': '' if review.status == InvoiceIdentityReview.STATUS_FLAGGED else review.decision_note,
        'decided_by': review.decided_by,
        'decided_at': review.decided_at.isoformat() if review.decided_at else None,
        'created_at': review.created_at.isoformat() if review.created_at else None,
    }


def serialize_name_change_item(item: InvoiceNameChangeItem | None) -> dict | None:
    if not item:
        return None
    batch = item.batch
    latest = batch.letter_artifacts.order_by('-version').first() if batch else None
    from core.services.invoice_name_change_letters import letter_batch_readiness, serialize_artifact
    readiness = letter_batch_readiness(batch) if batch and batch.status == 'draft' else {
        'ready': False, 'blockers': [], 'row_count': batch.items.count() if batch else 0,
    }
    now = timezone.now()
    age_days = max(0, (now.date() - item.updated_at.date()).days) if item.updated_at else 0
    return {
        'id': str(item.id),
        'batch_id': str(item.batch_id or ''),
        'batch_reference': batch.reference if batch else '',
        'batch_status': batch.status if batch else '',
        'batch_row_count': readiness['row_count'],
        'letter_readiness': {
            'ready': readiness['ready'], 'blockers': readiness['blockers'],
        },
        'latest_letter': serialize_artifact(latest),
        'status': item.status,
        'replacement_invoice_id': str(item.replacement_invoice_id or ''),
        'original_invoice_id': str(item.original_invoice_id),
        'original_invoice_no': item.original_invoice.invoice_no,
        'farmer_id': str(item.farmer_id),
        'applicant_name': str(item.requested_identity.get('name') or item.farmer.customer_name or ''),
        'invoice_holder_name': str(item.original_identity.get('name') or ''),
        'relationship_type': item.relationship.relationship_type,
        'explanation': item.relationship.attestation_note,
        'age_days': age_days,
        'closed_reason': item.closed_reason,
        'hb_communication_reference': item.hb_communication_reference,
        'follow_up_of': str(item.follow_up_of_id or ''),
        'revision': item.revision,
        'created_at': item.created_at.isoformat() if item.created_at else None,
        'updated_at': item.updated_at.isoformat() if item.updated_at else None,
    }


class InvoiceCorrectionConflict(ValueError):
    """The invoice/application changed after the detail screen was loaded."""


class InvoiceIdentityWorkflowError(ValueError):
    """Reviewed invoice-identity failure safe to expose through the Mini App."""

    def __init__(self, code: str, message: str, *, status: int = 409):
        super().__init__(message)
        self.code = code
        self.status = status


SENT_CORRECTION_EVENT_ACTION = 'invoice_name_change_sent_corrected'


class RelatedPersonIdentityConflict(ValueError):
    """More than one related-person row claims the same normalized ID."""

    def __init__(self, message: str, *, farmer_id=None):
        super().__init__(message)
        self.farmer_id = farmer_id


def _open_quality_issue(farmer: JawabuFarmerMaster, *, message: str) -> None:
    JawabuDataQualityIssue.objects.update_or_create(
        farmer=farmer,
        field_name='household_identity',
        code='duplicate_related_person_national_id',
        defaults={'severity': 'error', 'message': message, 'active': True, 'resolved_at': None},
    )


def _exact_related_people(normalized_id: str) -> list[JawabuRelatedPerson]:
    if not normalized_id:
        return []
    return [
        person for person in JawabuRelatedPerson.objects.select_for_update().exclude(national_id='')
        if normalize_national_id(person.national_id) == normalized_id
    ]


def _exact_customer(normalized_id: str) -> JawabuCustomer | None:
    if not normalized_id:
        return None
    matches = [
        customer for customer in JawabuCustomer.objects.select_for_update().exclude(national_id='')
        if normalize_national_id(customer.national_id) == normalized_id
    ]
    return matches[0] if len(matches) == 1 else None


def _reuse_or_create_related_person(
    farmer: JawabuFarmerMaster, *, actor: str, full_name: str,
    national_id: str, phone: str,
) -> JawabuRelatedPerson:
    normalized_id = normalize_national_id(national_id)
    if not normalized_id:
        raise ValueError('The invoice holder national ID is required before requesting a correction.')
    matches = _exact_related_people(normalized_id)
    if len(matches) > 1:
        _open_quality_issue(
            farmer,
            message='Several household-person records use the invoice holder national ID. Resolve them before continuing.',
        )
        raise RelatedPersonIdentityConflict(
            'Several household records match this national ID. An administrator must resolve them before continuing.',
            farmer_id=farmer.id,
        )
    if matches:
        return matches[0]
    return JawabuRelatedPerson.objects.create(
        linked_customer=_exact_customer(normalized_id),
        full_name=str(full_name or '').strip(),
        national_id=normalized_id,
        primary_phone=normalize_kenyan_phone(phone),
        created_by=actor,
    )


@transaction.atomic
def reconcile_related_person_for_customer(
    customer: JawabuCustomer, *, farmer: JawabuFarmerMaster | None = None,
) -> JawabuRelatedPerson | None:
    """Link exactly one national-ID match; phone is deliberately never used."""
    normalized_id = normalize_national_id(customer.national_id)
    matches = _exact_related_people(normalized_id)
    if len(matches) > 1:
        issue_farmer = farmer or customer.applications.order_by('-updated_at').first()
        if issue_farmer:
            _open_quality_issue(
                issue_farmer,
                message='Several household-person records match the new customer national ID; none was linked automatically.',
            )
        return None
    if len(matches) == 1:
        person = matches[0]
        if person.linked_customer_id not in {None, customer.id}:
            issue_farmer = farmer or customer.applications.order_by('-updated_at').first()
            if issue_farmer:
                _open_quality_issue(
                    issue_farmer,
                    message='The matching household-person record is already linked to another customer.',
                )
            return None
        if person.linked_customer_id is None:
            person.linked_customer = customer
            person.save(update_fields=['linked_customer', 'updated_at'])
        return person
    return None


@transaction.atomic
def _start_invoice_correction_locked(
    invoice: ParsedInvoice,
    *,
    actor: str,
    relationship_type: str,
    explanation: str,
    confirmed: bool,
    expected_invoice_revision: int,
    expected_application_revision: int,
    client_request_id: str,
) -> InvoiceNameChangeItem:
    """Create the complete single-invoice correction request in one action."""
    request_id = str(client_request_id or '').strip()
    if not request_id:
        raise ValueError('A retry key is required to request a corrected invoice safely.')
    prior = InvoiceNameChangeItem.objects.select_related('original_invoice').filter(client_request_id=request_id).first()
    if prior:
        if prior.original_invoice_id != invoice.id:
            raise InvoiceCorrectionConflict('That retry key belongs to another invoice correction.')
        return prior
    # Lock the invoice without joining its nullable matched_farmer relation.
    # PostgreSQL rejects FOR UPDATE against the nullable side of an outer join.
    invoice = ParsedInvoice.objects.select_for_update().get(pk=invoice.pk)
    if not invoice.matched_farmer_id:
        raise ValueError('Match the invoice to an applicant first.')
    farmer = JawabuFarmerMaster.objects.select_for_update().get(pk=invoice.matched_farmer_id)
    from core.services.invoice_parser import require_official_requisition
    require_official_requisition(farmer, lock=True)
    if int(expected_invoice_revision or 0) != int(invoice.revision):
        raise InvoiceCorrectionConflict('This invoice changed while you were reviewing it. Refresh and try again.')
    if int(expected_application_revision or 0) != int(farmer.workflow_revision):
        raise InvoiceCorrectionConflict('This applicant changed while you were reviewing it. Refresh and try again.')
    invoice_id = normalize_national_id(invoice.customer_id)
    applicant_id = normalize_national_id(farmer.national_id)
    if not invoice_id or not applicant_id:
        raise ValueError('Both the invoice holder and applicant national IDs are required before requesting a correction.')
    if invoice_id == applicant_id:
        raise ValueError('The national IDs match, so a corrected-invoice request is not needed.')
    if relationship_type not in {'spouse', 'household_member'}:
        raise ValueError('Choose Spouse or Other relative / household member.')
    explanation = str(explanation or '').strip()
    if relationship_type == 'household_member' and not explanation:
        raise ValueError('Explain the relationship when choosing Other relative / household member.')
    if not confirmed:
        raise ValueError('Confirm that the invoice belongs to the named household person.')
    review = ensure_identity_review(invoice, farmer)
    if review is None:
        raise ValueError('A corrected-invoice request is not needed for this invoice.')
    if review.status == InvoiceIdentityReview.STATUS_PENDING:
        decide_identity_review(
            review,
            outcome=InvoiceIdentityReview.STATUS_DIFFERENT_PERSON,
            actor=actor,
            note=explanation or 'Invoice holder confirmed as the applicant spouse.',
        )
    item = create_name_change(
        review,
        actor=actor,
        relationship_type=relationship_type,
        related_name=invoice.customer_name,
        related_national_id=invoice.customer_id,
        related_phone=invoice.customer_phone,
        attestation_note=explanation or 'Invoice holder confirmed as the applicant spouse.',
        evidence_reference=f'invoice:{invoice.id}',
        client_request_id=request_id,
    )
    invoice.revision += 1
    invoice.save(update_fields=['revision', 'updated_at'])
    return item


def start_invoice_correction(invoice: ParsedInvoice, **kwargs) -> InvoiceNameChangeItem:
    """Persist a visible issue even when an ambiguous exact-ID match rolls back."""
    try:
        return _start_invoice_correction_locked(invoice, **kwargs)
    except RelatedPersonIdentityConflict as exc:
        if exc.farmer_id:
            farmer = JawabuFarmerMaster.objects.filter(pk=exc.farmer_id).first()
            if farmer:
                _open_quality_issue(
                    farmer,
                    message='Several household-person records use the invoice holder national ID. Resolve them before continuing.',
                )
        raise


@transaction.atomic
def decide_identity_review(review: InvoiceIdentityReview, *, outcome: str, actor: str, note: str) -> InvoiceIdentityReview:
    review = InvoiceIdentityReview.objects.select_for_update().select_related('invoice', 'farmer').get(pk=review.pk)
    if review.status != InvoiceIdentityReview.STATUS_PENDING:
        if review.status == outcome:
            return review
        raise ValueError('This identity review has already been decided.')
    if outcome not in {
        InvoiceIdentityReview.STATUS_SAME_PERSON,
        InvoiceIdentityReview.STATUS_DIFFERENT_PERSON,
        InvoiceIdentityReview.STATUS_INSUFFICIENT,
        InvoiceIdentityReview.STATUS_FLAGGED,
        InvoiceIdentityReview.STATUS_CANCELLED,
    }:
        raise ValueError('Unsupported identity review outcome.')
    note = str(note or '').strip()
    if not note:
        raise ValueError('A verification note is required.')
    invoice_id = normalize_national_id(review.invoice.customer_id)
    applicant_id = normalize_national_id(review.farmer.national_id)
    if outcome == InvoiceIdentityReview.STATUS_SAME_PERSON and invoice_id and applicant_id and invoice_id != applicant_id:
        raise ValueError('Different national IDs cannot be confirmed as the same person. Correct the parsing or confirm a different person.')
    if outcome == InvoiceIdentityReview.STATUS_DIFFERENT_PERSON and (
        not invoice_id or not applicant_id or invoice_id == applicant_id
    ):
        raise ValueError('A change of invoice name requires two present, different national IDs.')
    review.status = outcome
    review.decision_note = note
    review.decided_by = str(actor or '').strip()
    review.decided_at = timezone.now()
    review.save(update_fields=['status', 'decision_note', 'decided_by', 'decided_at', 'updated_at'])
    from core.services.invoice_parser import record_invoice_event
    record_invoice_event(
        review.invoice, 'note', actor=actor, note=f'Invoice identity review: {review.get_status_display()}. {note}',
        metadata={'identity_review_id': str(review.id), 'outcome': outcome},
    )
    _record_case_event(
        review.farmer,
        action='invoice_identity_verified',
        actor=actor,
        request_id=f'invoice-identity-review:{review.id}',
        metadata={'invoice_id': str(review.invoice_id), 'review_id': str(review.id), 'outcome': outcome},
    )
    return review


@transaction.atomic
def create_name_change(
    review: InvoiceIdentityReview,
    *,
    actor: str,
    relationship_type: str,
    related_name: str,
    related_national_id: str,
    related_phone: str,
    attestation_note: str,
    evidence_reference: str,
    client_request_id: str = '',
    batch: InvoiceNameChangeBatch | None = None,
) -> InvoiceNameChangeItem:
    review = InvoiceIdentityReview.objects.select_for_update().select_related('invoice', 'farmer').get(pk=review.pk)
    if review.status != InvoiceIdentityReview.STATUS_DIFFERENT_PERSON:
        raise ValueError('Confirm the invoice belongs to a different person before starting this workflow.')
    request_id = str(client_request_id or '').strip()
    if request_id:
        prior = InvoiceNameChangeItem.objects.filter(client_request_id=request_id).first()
        if prior:
            if prior.review_id != review.id:
                raise ValueError('That retry key belongs to another invoice-name-change request.')
            return prior
    if hasattr(review, 'name_change_item'):
        raise InvoiceCorrectionConflict('A correction request already exists for this invoice. Refresh to see its current status.')
    related_name = str(related_name or '').strip()
    attestation_note = str(attestation_note or '').strip()
    evidence_reference = str(evidence_reference or '').strip()
    if not related_name or not attestation_note:
        raise ValueError('Related person name and relationship confirmation are required.')
    person = _reuse_or_create_related_person(
        review.farmer,
        actor=actor,
        full_name=related_name,
        national_id=related_national_id,
        phone=related_phone,
    )
    relationship, _ = JawabuHouseholdRelationship.objects.get_or_create(
        farmer=review.farmer,
        related_person=person,
        relationship_type=relationship_type if relationship_type in {'spouse', 'household_member'} else 'spouse',
        status=JawabuHouseholdRelationship.STATUS_CONFIRMED,
        defaults={
            'attestation_note': attestation_note,
            'evidence_reference': evidence_reference,
            'confirmed_by': actor,
        },
    )
    if batch:
        batch = InvoiceNameChangeBatch.objects.select_for_update().get(pk=batch.pk)
        if batch.status != 'draft':
            raise ValueError('Cases can only be added to a draft change letter.')
    else:
        batch_id = uuid.uuid4()
        batch = InvoiceNameChangeBatch.objects.create(
            id=batch_id,
            reference=f'COIN-{timezone.localdate():%Y%m%d}-{str(batch_id)[:8].upper()}',
            created_by=actor,
            client_request_id=f'{request_id}:batch' if request_id else '',
        )
    item = InvoiceNameChangeItem.objects.create(
        batch=batch,
        review=review,
        farmer=review.farmer,
        relationship=relationship,
        original_invoice=review.invoice,
        original_identity=review.invoice_identity,
        requested_identity=review.applicant_identity,
        client_request_id=request_id,
    )
    _record_case_event(
        review.farmer,
        action='invoice_name_change_started',
        actor=actor,
        request_id=f'invoice-name-change:{item.id}',
        metadata={
            'invoice_id': str(review.invoice_id), 'item_id': str(item.id),
            'batch_id': str(batch.id) if batch else '',
        },
    )
    return item


@transaction.atomic
def assemble_name_change_batch(
    items: list[InvoiceNameChangeItem], *, actor: str, client_request_id: str = '',
) -> tuple[InvoiceNameChangeBatch, list[dict]]:
    """Atomically place currently-ready requests into one governed letter batch."""
    request_id = str(client_request_id or '').strip()
    if request_id:
        prior = InvoiceNameChangeBatch.objects.filter(client_request_id=request_id).first()
        if prior:
            return prior, []
    item_ids = sorted({str(item.pk) for item in items if item and item.pk})
    # Keep nullable ``batch`` off the locked query. PostgreSQL rejects
    # FOR UPDATE when select_related() introduces a LEFT OUTER JOIN.
    locked = list(
        InvoiceNameChangeItem.objects.select_for_update().select_related('farmer', 'review')
        .filter(pk__in=item_ids).order_by('created_at')
    )
    conflicts = []
    ready = []
    for item in locked:
        if item.status != 'draft' or item.batch_id or item.review.status != InvoiceIdentityReview.STATUS_DIFFERENT_PERSON:
            conflicts.append({
                'item_id': str(item.id),
                'applicant_name': item.requested_identity.get('name') or item.farmer.customer_name,
                'reason': (
                    'already_batched' if item.batch_id
                    else 'identity_reverification_required'
                    if item.review.status != InvoiceIdentityReview.STATUS_DIFFERENT_PERSON
                    else f'not_ready:{item.status}'
                ),
                'batch_id': str(item.batch_id or ''),
                'batch_reference': item.batch.reference if item.batch_id else '',
            })
        else:
            ready.append(item)
    if conflicts:
        raise NameChangeBatchConflict(conflicts)
    if len(ready) != len(item_ids) or not ready:
        raise ValueError('Select at least one ready invoice-name-change request.')
    batch_id = uuid.uuid4()
    batch = InvoiceNameChangeBatch.objects.create(
        id=batch_id,
        reference=f'COIN-{timezone.localdate():%Y%m%d}-{str(batch_id)[:8].upper()}',
        created_by=actor,
        client_request_id=request_id,
    )
    for item in ready:
        item.batch = batch
        item.revision += 1
        item.save(update_fields=['batch', 'revision', 'updated_at'])
        _record_case_event(
            item.farmer, action='invoice_name_change_batched', actor=actor,
            request_id=f'invoice-name-change-batched:{batch.id}:{item.id}',
            metadata={'item_id': str(item.id), 'batch_id': str(batch.id)},
        )
    return batch, []


class NameChangeBatchConflict(ValueError):
    def __init__(self, conflicts: list[dict]):
        super().__init__('One or more selected requests changed before the batch was created.')
        self.conflicts = conflicts


def _refresh_batch_terminal_status(batch: InvoiceNameChangeBatch | None) -> None:
    if not batch:
        return
    statuses = set(batch.items.values_list('status', flat=True))
    if not statuses and batch.status == 'draft':
        target = 'cancelled'
    elif statuses and statuses <= {'cancelled'}:
        target = 'cancelled'
    elif statuses and statuses <= {'withdrawn'}:
        target = 'withdrawn'
    elif statuses and statuses <= {'completed', 'cancelled', 'withdrawn'}:
        target = 'completed'
    else:
        return
    if batch.status != target:
        batch.status = target
        batch.revision += 1
        batch.save(update_fields=['status', 'revision', 'updated_at'])


@transaction.atomic
def close_name_change(
    item: InvoiceNameChangeItem, *, actor: str, reason: str,
    hb_communication_reference: str = '', withdraw: bool = False,
) -> InvoiceNameChangeItem:
    item = InvoiceNameChangeItem.objects.select_for_update().select_related('farmer').get(pk=item.pk)
    prior_batch = (
        InvoiceNameChangeBatch.objects.select_for_update().get(pk=item.batch_id)
        if item.batch_id else None
    )
    reason = str(reason or '').strip()
    communication = str(hb_communication_reference or '').strip()
    if not reason:
        raise ValueError('A reason is required.')
    if withdraw:
        if not prior_batch or prior_batch.status not in {'sent_to_hb', 'awaiting_replacements'}:
            raise ValueError('Only a request whose letter was sent to HB can be withdrawn.')
        if not communication:
            raise ValueError('The HB communication reference is required for withdrawal.')
        target = 'withdrawn'
        action = 'invoice_name_change_withdrawn'
    else:
        if item.status != 'draft' or (prior_batch and prior_batch.status != 'draft'):
            raise ValueError('Only an unsent request can be cancelled.')
        target = 'cancelled'
        action = 'invoice_name_change_cancelled'
    if item.status == target:
        return item
    item.status = target
    item.closed_reason = reason
    item.hb_communication_reference = communication
    item.closed_by = str(actor or '').strip()
    item.closed_at = timezone.now()
    if not withdraw:
        # An unsent draft is a mutable assembly. Removing the cancelled item
        # keeps the remaining batch usable; any generated artifact becomes
        # non-current through its source fingerprint and remains auditable.
        item.batch = None
    item.revision += 1
    item.save(update_fields=[
        'status', 'closed_reason', 'hb_communication_reference', 'closed_by',
        'closed_at', 'batch', 'revision', 'updated_at',
    ])
    _record_case_event(
        item.farmer, action=action, actor=actor,
        request_id=f'{action}:{item.id}:{item.revision}',
        metadata={'item_id': str(item.id), 'reason': reason, 'hb_reference': communication},
    )
    _refresh_batch_terminal_status(prior_batch)
    return item


@transaction.atomic
def create_name_change_follow_up(
    item: InvoiceNameChangeItem, *, actor: str, client_request_id: str = '',
) -> InvoiceNameChangeItem:
    item = InvoiceNameChangeItem.objects.select_for_update().select_related(
        'review', 'review__invoice', 'farmer', 'relationship',
    ).get(pk=item.pk)
    if item.status not in {'cancelled', 'withdrawn'}:
        raise ValueError('Only a cancelled or withdrawn request can start a follow-up.')
    request_id = str(client_request_id or '').strip()
    if request_id:
        prior = InvoiceNameChangeItem.objects.filter(client_request_id=request_id).first()
        if prior:
            return prior
    review = InvoiceIdentityReview.objects.create(
        invoice=item.review.invoice,
        farmer=item.farmer,
        status=InvoiceIdentityReview.STATUS_PENDING,
        discrepancy_codes=item.review.discrepancy_codes,
        invoice_identity=item.review.invoice_identity,
        applicant_identity=item.review.applicant_identity,
        decision_note=f'Follow-up to {item.id}. Identity must be re-verified before batching.',
        decided_by='',
        decided_at=None,
    )
    follow_up = InvoiceNameChangeItem.objects.create(
        review=review,
        farmer=item.farmer,
        relationship=item.relationship,
        original_invoice=item.original_invoice,
        original_identity=item.original_identity,
        requested_identity=item.requested_identity,
        follow_up_of=item,
        client_request_id=request_id,
    )
    _record_case_event(
        item.farmer, action='invoice_name_change_follow_up_started', actor=actor,
        request_id=f'invoice-name-change-follow-up:{follow_up.id}',
        metadata={'item_id': str(follow_up.id), 'follow_up_of': str(item.id)},
    )
    return follow_up


@transaction.atomic
def mark_name_change_sent(
    batch: InvoiceNameChangeBatch, *, actor: str, sent_reference: str,
    artifact: InvoiceNameChangeLetterArtifact | None = None,
    letter_reference: str = '',
) -> InvoiceNameChangeBatch:
    batch = InvoiceNameChangeBatch.objects.select_for_update().get(pk=batch.pk)
    artifact_id = getattr(artifact, 'pk', None)
    if batch.status != 'draft':
        if (
            batch.status in {'awaiting_replacements', 'completed'}
            and (not artifact_id or batch.sent_artifact_id == artifact_id)
            and batch.sent_reference == str(sent_reference or '').strip()
        ):
            return batch
        raise ValueError('Only a draft change letter can be marked sent.')
    if not str(sent_reference or '').strip():
        raise ValueError('The HB send reference is required.')
    update_fields = [
        'letter_file_reference', 'letter_checksum', 'sent_reference', 'sent_by',
        'sent_at', 'status', 'updated_at',
    ]
    if artifact_id:
        artifact = InvoiceNameChangeLetterArtifact.objects.select_for_update().select_related('batch').get(pk=artifact_id)
        if artifact.batch_id != batch.id:
            raise ValueError('The generated letter does not belong to this batch.')
        if not artifact.file_content:
            raise ValueError('Generate the corrected-invoice letter before recording it as sent.')
        from core.services.invoice_name_change_letters import artifact_is_current
        if not artifact_is_current(artifact):
            raise ValueError('The batch changed after this letter was generated. Generate a new version first.')
        batch.sent_artifact = artifact
        # Drive is an optional publication copy. The immutable local artifact
        # is sufficient to send and remains available through an authorized,
        # short-lived download link.
        batch.letter_file_reference = artifact.drive_url or f'local-artifact:{artifact.id}'
        batch.letter_checksum = artifact.checksum
        update_fields.append('sent_artifact')
    else:
        if not batch.legacy_manual_letter_allowed:
            raise ValueError('Generate the governed DOCX letter before recording it as sent.')
        if not str(letter_reference or '').strip():
            raise ValueError('The legacy letter evidence reference is required.')
        batch.letter_file_reference = str(letter_reference).strip()
    batch.sent_reference = str(sent_reference).strip()
    batch.sent_by = str(actor or '').strip()
    batch.sent_at = timezone.now()
    batch.status = 'awaiting_replacements'
    batch.save(update_fields=update_fields)
    batch.items.filter(status='draft').update(status='awaiting_replacement', updated_at=timezone.now())
    for item in batch.items.select_related('farmer').all():
        _record_case_event(
            item.farmer,
            action='invoice_name_change_letter_sent',
            actor=actor,
            request_id=f'invoice-name-change-sent:{batch.id}:{item.id}',
            metadata={'item_id': str(item.id), 'batch_id': str(batch.id), 'sent_reference': batch.sent_reference},
        )
    return batch


@transaction.atomic
def correct_sent_name_change(
    item: InvoiceNameChangeItem,
    *,
    actor: str,
    reason: str,
    relationship_type: str,
    explanation: str,
    expected_revision: int,
    client_request_id: str,
) -> InvoiceNameChangeItem:
    """Explicitly reopen a sent request while preserving every old artifact."""
    item = InvoiceNameChangeItem.objects.select_for_update().select_related(
        'relationship', 'farmer',
    ).get(pk=item.pk)
    batch = (
        InvoiceNameChangeBatch.objects.select_for_update().get(pk=item.batch_id)
        if item.batch_id else None
    )
    request_id = str(client_request_id or '').strip()
    if not request_id:
        raise ValueError('A retry key is required to correct a sent request safely.')
    payload_digest = hashlib.sha256(json.dumps({
        'item_id': str(item.id),
        'reason': str(reason or '').strip(),
        'relationship_type': str(relationship_type or '').strip(),
        'explanation': str(explanation or '').strip(),
        'expected_revision': int(expected_revision or 0),
    }, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()
    replay_event = item.farmer.pipeline_events.filter(
        request_id=request_id,
        action=SENT_CORRECTION_EVENT_ACTION,
    ).first()
    if replay_event:
        if str((replay_event.metadata or {}).get('payload_digest') or '') != payload_digest:
            raise InvoiceCorrectionConflict('That retry key was already used for a different correction.')
        return item
    if int(expected_revision or 0) != int(item.revision):
        raise InvoiceCorrectionConflict('This correction changed while you were reviewing it. Refresh and try again.')
    if item.status != 'awaiting_replacement' or not batch or batch.status != 'awaiting_replacements':
        raise ValueError('Only a sent request that is waiting for a corrected invoice can be corrected.')
    reason = str(reason or '').strip()
    explanation = str(explanation or '').strip()
    if not reason:
        raise ValueError('Explain why the sent request needs to be corrected.')
    if relationship_type not in {'spouse', 'household_member'}:
        raise ValueError('Choose Spouse or Other relative / household member.')
    if relationship_type == 'household_member' and not explanation:
        raise ValueError('Explain the relationship when choosing Other relative / household member.')
    old_artifact_id = str(batch.sent_artifact_id or '')
    old_sent_reference = batch.sent_reference
    item.relationship.relationship_type = relationship_type
    item.relationship.attestation_note = explanation or item.relationship.attestation_note
    item.relationship.save(update_fields=['relationship_type', 'attestation_note'])
    item.status = 'draft'
    item.revision += 1
    item.save(update_fields=['status', 'revision', 'updated_at'])
    batch.status = 'draft'
    batch.sent_artifact = None
    batch.letter_file_reference = ''
    batch.letter_checksum = ''
    batch.sent_reference = ''
    batch.sent_by = ''
    batch.sent_at = None
    batch.revision += 1
    batch.save(update_fields=[
        'status', 'sent_artifact', 'letter_file_reference', 'letter_checksum',
        'sent_reference', 'sent_by', 'sent_at', 'revision', 'updated_at',
    ])
    _record_case_event(
        item.farmer,
        action=SENT_CORRECTION_EVENT_ACTION,
        actor=actor,
        request_id=request_id,
        metadata={
            'item_id': str(item.id), 'reason': reason,
            'superseded_artifact_id': old_artifact_id,
            'superseded_sent_reference': old_sent_reference,
            'payload_digest': payload_digest,
        },
    )
    return item


@transaction.atomic
def confirm_replacement(
    item: InvoiceNameChangeItem,
    replacement: ParsedInvoice,
    *,
    actor: str,
    verification_note: str = '',
) -> InvoiceNameChangeItem:
    item = InvoiceNameChangeItem.objects.select_for_update().get(pk=item.pk)
    batch = (
        InvoiceNameChangeBatch.objects.select_for_update().get(pk=item.batch_id)
        if item.batch_id else None
    )
    farmer = JawabuFarmerMaster.objects.select_for_update().get(pk=item.farmer_id)
    from core.services.invoice_parser import require_official_requisition
    eligibility = require_official_requisition(farmer, lock=True)
    invoice_ids = sorted({item.original_invoice_id, replacement.pk}, key=str)
    locked_invoices = {
        invoice.pk: invoice
        for invoice in ParsedInvoice.objects.select_for_update().filter(pk__in=invoice_ids).order_by('pk')
    }
    original = locked_invoices[item.original_invoice_id]
    replacement = locked_invoices[replacement.pk]
    if item.status != 'awaiting_replacement' or not batch or batch.status != 'awaiting_replacements':
        if item.status == 'completed' and item.replacement_invoice_id == replacement.id:
            return item
        raise InvoiceIdentityWorkflowError(
            'replacement_request_not_ready',
            'This request is not waiting for a corrected invoice. Refresh the invoice record.',
        )
    if replacement.pk == item.original_invoice_id:
        raise InvoiceIdentityWorkflowError(
            'replacement_invoice_conflict', 'The original invoice cannot replace itself.',
        )
    if replacement.matched_farmer_id and replacement.matched_farmer_id != farmer.id:
        raise InvoiceIdentityWorkflowError(
            'replacement_invoice_conflict',
            'This invoice is already matched to another applicant.',
        )
    if replacement.status not in {'draft', 'unmatched', 'ambiguous', 'ignored', 'matched'}:
        raise InvoiceIdentityWorkflowError(
            'replacement_invoice_conflict', 'Select an available corrected invoice.',
        )
    upload_batch = InvoiceUploadBatch.objects.select_for_update().get(pk=replacement.batch_id)
    upload_order = str(upload_batch.order_number or '').strip()
    if upload_order and upload_order != eligibility['order_number']:
        raise InvoiceIdentityWorkflowError(
            'replacement_invoice_order_mismatch',
            'This corrected invoice was uploaded for a different order.',
        )
    expected_id = normalize_national_id(farmer.national_id)
    replacement_id = normalize_national_id(replacement.customer_id)
    if not replacement_id:
        raise InvoiceIdentityWorkflowError(
            'replacement_invoice_identity_mismatch',
            'The corrected invoice has no usable national ID.',
        )
    if replacement_id != expected_id:
        raise InvoiceIdentityWorkflowError(
            'replacement_invoice_identity_mismatch',
            'The corrected invoice national ID does not match the applicant.',
        )
    expected_name = normalize_person_name(applicant_identity(farmer)['name'])
    replacement_name = normalize_person_name(replacement.customer_name)
    if not replacement_name or replacement_name != expected_name:
        raise InvoiceIdentityWorkflowError(
            'replacement_invoice_identity_mismatch',
            'The corrected invoice name does not match the applicant.',
        )
    codes = discrepancy_codes(replacement, farmer)
    verification_note = str(verification_note or '').strip()
    if 'phone_mismatch' in codes and not verification_note:
        raise InvoiceIdentityWorkflowError(
            'replacement_invoice_verification_note_required',
            'Explain the phone-number difference before confirming this corrected invoice.',
            status=400,
        )
    if len(verification_note) > 500:
        raise InvoiceIdentityWorkflowError(
            'replacement_invoice_verification_note_required',
            'Keep the phone-number verification note to 500 characters or fewer.',
            status=400,
        )
    from core.services.invoice_parser import _apply_invoice_to_farmer, record_invoice_event
    _apply_invoice_to_farmer(farmer, replacement)
    replacement.status = 'matched'
    replacement.matched_farmer = farmer
    replacement.matched_order_number = farmer.order_number or ''
    replacement.revision += 1
    replacement.save(update_fields=['status', 'matched_farmer', 'matched_order_number', 'revision', 'updated_at'])
    original.status = 'superseded'
    original.revision += 1
    original.save(update_fields=['status', 'revision', 'updated_at'])
    item.replacement_invoice = replacement
    item.status = 'completed'
    item.completed_by = str(actor or '').strip()
    item.completed_at = timezone.now()
    item.revision += 1
    item.save(update_fields=['replacement_invoice', 'status', 'completed_by', 'completed_at', 'revision', 'updated_at'])
    record_invoice_event(original, 'note', actor=actor, note='Superseded by corrected invoice.', metadata={'replacement_invoice_id': str(replacement.id)})
    record_invoice_event(replacement, 'matched', actor=actor, note=str(verification_note or '').strip(), metadata={'name_change_item_id': str(item.id)})
    _record_case_event(
        farmer,
        action='invoice_name_change_completed',
        actor=actor,
        request_id=f'invoice-name-change-completed:{item.id}',
        metadata={
            'item_id': str(item.id),
            'original_invoice_id': str(original.id),
            'replacement_invoice_id': str(replacement.id),
        },
    )
    if codes:
        replacement_review = ensure_identity_review(replacement, farmer)
        if replacement_review:
            decide_identity_review(
                replacement_review,
                outcome=InvoiceIdentityReview.STATUS_SAME_PERSON,
                actor=actor,
                note=str(verification_note or '').strip(),
            )
    from core.services.invoice_parser import refresh_invoice_batch_counts
    refresh_invoice_batch_counts(original.batch)
    if replacement.batch_id != original.batch_id:
        refresh_invoice_batch_counts(replacement.batch)
    if not batch.items.filter(status__in=['draft', 'awaiting_replacement']).exists():
        batch.status = 'completed'
        batch.save(update_fields=['status', 'updated_at'])
    return item
