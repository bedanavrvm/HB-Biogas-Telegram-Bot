from __future__ import annotations

import hashlib
import json
import logging
from decimal import Decimal

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone

from core.models import JawabuFarmerMaster, PaymentDocument
from core.services.payment_documents import (
    PaymentTemplateError,
    create_payment_document,
    payment_readiness,
)
from core.services.jawabu_validation import format_repayment_day
from payments.models import (
    PaymentBatch,
    PaymentBatchCase,
    PaymentBatchEvent,
    PaymentCaseReview,
    PaymentSequenceEvent,
    PaymentSequenceState,
)


logger = logging.getLogger(__name__)


class PaymentBatchError(ValueError):
    def __init__(self, message, *, code='payment_batch_invalid', status=400):
        super().__init__(message)
        self.code = code
        self.status = status


EDITABLE_STATUSES = {
    PaymentBatch.STATUS_DRAFT,
    PaymentBatch.STATUS_IN_REVIEW,
    PaymentBatch.STATUS_REVIEW_COMPLETE,
    PaymentBatch.STATUS_AWAITING_SCAN,
}


def _digest(payload) -> str:
    encoded = json.dumps(payload, cls=DjangoJSONEncoder, sort_keys=True, separators=(',', ':')).encode()
    return hashlib.sha256(encoded).hexdigest()


def _normalize_payment_mode(value) -> str:
    mode = str(value or '').strip().upper()
    if mode not in dict(PaymentBatchCase.MODE_CHOICES):
        raise PaymentBatchError('Choose Loan - Jawabu or Cash for every selected case.')
    return mode


def case_payment_digest(farmer: JawabuFarmerMaster, payment_mode: str = '') -> str:
    """Bind a review to all values that can change the payment row or eligibility."""
    return _digest({
        'farmer_id': str(farmer.pk),
        'payment_mode': str(payment_mode or '').strip().upper(),
        'workflow_revision': farmer.workflow_revision,
        'customer_no': farmer.customer_no,
        'customer_name': farmer.customer_name,
        'imab_customer_name': farmer.imab_customer_name,
        'primary_phone': farmer.primary_phone,
        'secondary_phone': farmer.secondary_phone,
        'branch': farmer.branch,
        'system_branch': farmer.system_branch,
        'loan_officer': farmer.system_loan_officer or farmer.jbl_officer,
        'order_number': farmer.order_number,
        'invoice_number': farmer.invoice_number,
        'balance_due': farmer.balance_due,
        'discount': farmer.discount,
        'deposit_paid_hbg': farmer.deposit_paid_hbg,
        'deposit_paid_jbl': farmer.system_deposit_paid_jbl,
        'preferred_repayment_day': format_repayment_day(farmer.repayment_day or farmer.repayment_date),
        # Retain the legacy source text in the review digest so an out-of-band
        # correction cannot be hidden merely because the typed day is stale.
        'preferred_repayment_source': farmer.repayment_date,
        'repayment_tenor_months': farmer.repayment_tenor_months,
        'repayment_tenor': farmer.repayment_tenor,
        'payment_product': farmer.payment_product,
        'product_version_id': str(farmer.product_version_id or ''),
        'final_decision': farmer.final_decision,
        'final_decided_at': farmer.final_decided_at,
    })


def _record(batch, action: str, *, actor=None, request_id: str = '', metadata=None):
    if request_id:
        existing = PaymentBatchEvent.objects.filter(request_id=request_id).first()
        if existing:
            return existing
    return PaymentBatchEvent.objects.create(
        batch=batch, action=action, actor=actor, request_id=request_id,
        revision=batch.revision, metadata=metadata or {},
    )


def _replayed_batch(request_id: str, *, action: str, batch_id=None, metadata=None):
    if not request_id:
        return None
    event = PaymentBatchEvent.objects.filter(request_id=request_id).select_related('batch').first()
    if not event:
        return None
    expected_metadata = metadata or {}
    if (
        event.action != action
        or (batch_id is not None and str(event.batch_id) != str(batch_id))
        or any(event.metadata.get(key) != value for key, value in expected_metadata.items())
    ):
        raise PaymentBatchError('This request key was already used for a different payment change.')
    return event.batch


def _active_memberships(batch):
    return batch.case_memberships.filter(is_active=True).select_related('farmer', 'review').order_by('added_at')


def _refresh_batch_digest(batch):
    values = [
        {
            'farmer_id': str(item.farmer_id),
            'payment_mode': item.payment_mode,
            'digest': case_payment_digest(item.farmer, item.payment_mode),
        }
        for item in _active_memberships(batch)
    ]
    batch.batch_digest = _digest({
        'payment_number': batch.payment_number,
        'cases': values,
    })


def _supersede_document(batch):
    if not batch.current_document_id:
        return
    document = PaymentDocument.objects.select_for_update().get(pk=batch.current_document_id)
    if document.status in {'awaiting_scan', 'final'}:
        document.status = 'superseded'
        document.validation_summary = {
            **(document.validation_summary or {}),
            'superseded_at': timezone.now().isoformat(),
            'superseded_by_batch_revision': batch.revision + 1,
        }
        document.save(update_fields=['status', 'validation_summary', 'updated_at'])
    batch.current_document = None
    batch.confirmed_by = None
    batch.confirmed_at = None


def _invalidate_current_reviews(batch):
    """Invalidate approvals when the reviewed batch context itself changes."""
    invalidated = []
    for membership in _active_memberships(batch):
        review = getattr(membership, 'review', None)
        if not review or review.decision == PaymentCaseReview.DECISION_PENDING:
            continue
        invalidated.append({
            'farmer_id': str(membership.farmer_id),
            'decision': review.decision,
            'comment': review.comment,
            'reviewed_digest': review.reviewed_digest,
        })
        review.decision = PaymentCaseReview.DECISION_PENDING
        review.comment = ''
        review.reviewed_digest = ''
        review.reviewed_by = None
        review.reviewed_at = None
        review.revision += 1
        review.save()
    return invalidated


def _invalidate_membership_review(membership):
    review = getattr(membership, 'review', None)
    if not review or review.decision == PaymentCaseReview.DECISION_PENDING:
        return []
    evidence = [{
        'farmer_id': str(membership.farmer_id),
        'decision': review.decision,
        'comment': review.comment,
        'reviewed_digest': review.reviewed_digest,
    }]
    review.decision = PaymentCaseReview.DECISION_PENDING
    review.comment = ''
    review.reviewed_digest = ''
    review.reviewed_by = None
    review.reviewed_at = None
    review.revision += 1
    review.save()
    return evidence


def _require_revision(batch, expected_revision):
    if expected_revision is None:
        raise PaymentBatchError('Refresh the payment batch before making this change.')
    try:
        expected = int(expected_revision)
    except (TypeError, ValueError) as exc:
        raise PaymentBatchError('The payment batch revision is invalid. Refresh and retry.') from exc
    if expected != batch.revision:
        raise PaymentBatchError('This payment batch changed while you were working. Refresh to see the latest cases.')


@transaction.atomic
def create_batch(*, group_configuration, actor=None, request_id: str = '') -> PaymentBatch:
    replayed = _replayed_batch(
        request_id, action='created',
        metadata={'group_configuration_id': group_configuration.pk},
    )
    if replayed:
        return replayed
    batch = PaymentBatch.objects.create(group_configuration=group_configuration, created_by=actor)
    _refresh_batch_digest(batch)
    batch.save(update_fields=['batch_digest', 'updated_at'])
    _record(
        batch, 'created', actor=actor, request_id=request_id,
        metadata={'group_configuration_id': group_configuration.pk},
    )
    return batch


@transaction.atomic
def update_case_mode(batch_id, farmer_id, *, payment_mode: str, expected_revision, actor=None, request_id=''):
    mode = _normalize_payment_mode(payment_mode)
    replayed = _replayed_batch(
        request_id, action='case_mode_changed', batch_id=batch_id,
        metadata={'farmer_id': str(farmer_id), 'payment_mode': mode},
    )
    if replayed:
        return replayed
    batch = PaymentBatch.objects.select_for_update().get(pk=batch_id)
    _require_revision(batch, expected_revision)
    if batch.status not in EDITABLE_STATUSES:
        raise PaymentBatchError('This completed or cancelled payment batch cannot be changed.')
    membership = PaymentBatchCase.objects.select_for_update().select_related('farmer').filter(
        batch=batch, farmer_id=farmer_id, is_active=True,
    ).first()
    if not membership:
        raise PaymentBatchError('This case is not currently in the payment batch.')
    if membership.payment_mode == mode:
        return batch
    _supersede_document(batch)
    invalidated = _invalidate_membership_review(membership)
    membership.payment_mode = mode
    membership.case_digest = case_payment_digest(membership.farmer, mode)
    membership.save(update_fields=['payment_mode', 'case_digest', 'updated_at'])
    batch.status = PaymentBatch.STATUS_IN_REVIEW if batch.payment_number else PaymentBatch.STATUS_DRAFT
    batch.revision += 1
    _refresh_batch_digest(batch)
    batch.save()
    _record(
        batch, 'case_mode_changed', actor=actor, request_id=request_id,
        metadata={
            'farmer_id': str(farmer_id), 'payment_mode': mode,
            'invalidated_reviews': invalidated,
        },
    )
    return batch


@transaction.atomic
def add_cases(batch_id, *, farmer_ids, payment_modes, expected_revision, actor=None, request_id=''):
    ids = list(dict.fromkeys(str(value) for value in farmer_ids if str(value).strip()))
    if not ids:
        raise PaymentBatchError('Select one or more cases to add.')
    raw_modes = {str(key): value for key, value in payment_modes.items()} if isinstance(payment_modes, dict) else {}
    modes = {}
    for farmer_id in ids:
        modes[farmer_id] = _normalize_payment_mode(raw_modes.get(farmer_id))
    replayed = _replayed_batch(
        request_id, action='cases_added', batch_id=batch_id,
        metadata={'farmer_ids': sorted(ids), 'payment_modes': {key: modes[key] for key in sorted(modes)}},
    )
    if replayed:
        return replayed
    batch = PaymentBatch.objects.select_for_update().get(pk=batch_id)
    _require_revision(batch, expected_revision)
    if batch.status not in EDITABLE_STATUSES:
        raise PaymentBatchError('Cases cannot be added to a completed or cancelled payment batch.')
    farmers = list(JawabuFarmerMaster.objects.select_for_update().filter(pk__in=ids))
    if len(farmers) != len(ids):
        raise PaymentBatchError('One or more selected cases could not be found.')
    other = PaymentBatchCase.objects.filter(
        farmer_id__in=ids, is_active=True,
        batch__status__in=list(EDITABLE_STATUSES),
    ).exclude(batch=batch).select_related('batch').first()
    if other:
        label = other.batch.payment_number or 'draft'
        raise PaymentBatchError(f'One selected case is already in Payment {label}.')
    readiness = payment_readiness('PAYMENT-DRAFT', farmer_ids=ids)
    if readiness['blocked_count']:
        reasons = ', '.join(dict.fromkeys(
            reason for item in readiness['blocked'] for reason in (item.get('missing') or [])
        ))
        raise PaymentBatchError(f'Resolve these payment details first: {reasons}.')
    _supersede_document(batch)
    invalidated = _invalidate_current_reviews(batch)
    for farmer in farmers:
        mode = modes[str(farmer.pk)]
        digest = case_payment_digest(farmer, mode)
        membership, created = PaymentBatchCase.objects.get_or_create(
            batch=batch, farmer=farmer,
            defaults={'case_digest': digest, 'payment_mode': mode, 'added_by': actor},
        )
        if not created:
            membership.is_active = True
            membership.case_digest = digest
            membership.payment_mode = mode
            membership.added_by = actor
            membership.added_at = timezone.now()
            membership.removed_by = None
            membership.removed_at = None
            membership.removed_reason = ''
            membership.save()
        review, _ = PaymentCaseReview.objects.get_or_create(membership=membership)
        if review.reviewed_digest != digest:
            review.decision = PaymentCaseReview.DECISION_PENDING
            review.comment = ''
            review.reviewed_digest = ''
            review.reviewed_by = None
            review.reviewed_at = None
            review.revision += 1
            review.save()
        # A payment selection is also a useful repair trigger for the
        # canonical Master Data projection. Publication remains asynchronous
        # and reads the latest farmer revision when it runs.
        from core.services.portal_publication import reserve_farmer_publication
        reserve_farmer_publication(
            farmer,
            request_id=f'payment-batch:{batch.id}:{farmer.id}:{batch.revision + 1}',
            requested_by=actor,
            requested_by_label=getattr(actor, 'get_full_name', lambda: '')() or getattr(actor, 'username', ''),
            required_capability='portal.payment.prepare',
            deduplication_namespace='payment-batch',
        )
    batch.status = PaymentBatch.STATUS_IN_REVIEW if batch.payment_number else PaymentBatch.STATUS_DRAFT
    batch.revision += 1
    _refresh_batch_digest(batch)
    batch.save()
    _record(
        batch, 'cases_added', actor=actor, request_id=request_id,
        metadata={
            'count': len(ids), 'farmer_ids': sorted(ids),
            'payment_modes': {key: modes[key] for key in sorted(modes)},
            'invalidated_reviews': invalidated,
        },
    )
    return batch


@transaction.atomic
def remove_case(batch_id, farmer_id, *, reason: str, expected_revision, actor=None, request_id=''):
    reason = str(reason or '').strip()
    if not reason:
        raise PaymentBatchError('Give a reason for removing this case from the payment batch.')
    replayed = _replayed_batch(
        request_id, action='case_removed', batch_id=batch_id,
        metadata={'farmer_id': str(farmer_id), 'reason': reason},
    )
    if replayed:
        return replayed
    batch = PaymentBatch.objects.select_for_update().get(pk=batch_id)
    _require_revision(batch, expected_revision)
    if batch.status not in EDITABLE_STATUSES:
        raise PaymentBatchError('Cases cannot be removed from a completed or cancelled payment batch.')
    membership = PaymentBatchCase.objects.select_for_update().filter(batch=batch, farmer_id=farmer_id, is_active=True).first()
    if not membership:
        raise PaymentBatchError('This case is not currently in the payment batch.')
    _supersede_document(batch)
    membership.is_active = False
    membership.removed_by = actor
    membership.removed_at = timezone.now()
    membership.removed_reason = reason
    membership.save()
    invalidated = _invalidate_current_reviews(batch)
    batch.status = PaymentBatch.STATUS_IN_REVIEW if batch.payment_number else PaymentBatch.STATUS_DRAFT
    batch.revision += 1
    _refresh_batch_digest(batch)
    batch.save()
    _record(
        batch, 'case_removed', actor=actor, request_id=request_id,
        metadata={
            'farmer_id': str(farmer_id), 'reason': reason,
            'invalidated_reviews': invalidated,
        },
    )
    return batch


@transaction.atomic
def submit_for_review(batch_id, *, expected_revision, actor=None, request_id=''):
    replayed = _replayed_batch(request_id, action='submitted_for_review', batch_id=batch_id)
    if replayed:
        return replayed
    batch = PaymentBatch.objects.select_for_update().select_related('group_configuration').get(pk=batch_id)
    _require_revision(batch, expected_revision)
    if batch.status not in EDITABLE_STATUSES:
        raise PaymentBatchError('This payment batch cannot be submitted for review.')
    if not batch.case_memberships.filter(is_active=True).exists():
        raise PaymentBatchError('Add at least one ready case before submitting this payment batch.')
    if batch.payment_number is None:
        sequence, _ = PaymentSequenceState.objects.select_for_update().get_or_create(
            group_configuration=batch.group_configuration, defaults={'next_number': 1, 'updated_by': actor},
        )
        number = sequence.next_number
        sequence.next_number += 1
        sequence.revision += 1
        sequence.updated_by = actor
        sequence.save()
        PaymentSequenceEvent.objects.create(
            sequence=sequence, batch=batch, action='allocated', number_before=number,
            number_after=sequence.next_number, revision_after=sequence.revision,
            actor=actor, reason='Allocated on first Head of Rural review submission.',
            request_id=f'{request_id}:sequence' if request_id else '',
        )
        batch.payment_number = number
    batch.status = PaymentBatch.STATUS_IN_REVIEW
    batch.submitted_by = actor
    batch.submitted_at = batch.submitted_at or timezone.now()
    batch.revision += 1
    _refresh_batch_digest(batch)
    batch.save()
    _record(batch, 'submitted_for_review', actor=actor, request_id=request_id)
    return batch


@transaction.atomic
def review_case(batch_id, farmer_id, *, decision: str, comment: str, expected_revision, actor=None, request_id=''):
    decision = str(decision or '').strip().lower()
    if decision not in {PaymentCaseReview.DECISION_APPROVED, PaymentCaseReview.DECISION_RETURNED}:
        raise PaymentBatchError('Choose Approve or Return for correction.')
    comment = str(comment or '').strip()
    if not comment:
        raise PaymentBatchError('Enter a Head of Rural comment for this case.')
    replayed = _replayed_batch(
        request_id, action='case_reviewed', batch_id=batch_id,
        metadata={'farmer_id': str(farmer_id), 'decision': decision, 'comment': comment},
    )
    if replayed:
        return replayed
    batch = PaymentBatch.objects.select_for_update().get(pk=batch_id)
    _require_revision(batch, expected_revision)
    if batch.status not in {PaymentBatch.STATUS_IN_REVIEW, PaymentBatch.STATUS_REVIEW_COMPLETE}:
        raise PaymentBatchError('This payment batch is not awaiting Head of Rural review.')
    membership = PaymentBatchCase.objects.select_for_update().select_related('farmer').filter(
        batch=batch, farmer_id=farmer_id, is_active=True,
    ).first()
    if not membership:
        raise PaymentBatchError('This case is not currently in the payment batch.')
    digest = case_payment_digest(membership.farmer, membership.payment_mode)
    review, _ = PaymentCaseReview.objects.select_for_update().get_or_create(membership=membership)
    review.decision = decision
    review.comment = comment
    review.reviewed_digest = digest
    review.reviewed_by = actor
    review.reviewed_at = timezone.now()
    review.revision += 1
    review.save()
    membership.case_digest = digest
    membership.save(update_fields=['case_digest', 'updated_at'])
    active = list(_active_memberships(batch))
    all_approved = all(
        hasattr(item, 'review')
        and item.review.decision == PaymentCaseReview.DECISION_APPROVED
        and item.review.reviewed_digest == case_payment_digest(item.farmer, item.payment_mode)
        for item in active
    )
    batch.status = PaymentBatch.STATUS_REVIEW_COMPLETE if active and all_approved else PaymentBatch.STATUS_IN_REVIEW
    batch.confirmed_by = None
    batch.confirmed_at = None
    batch.revision += 1
    _refresh_batch_digest(batch)
    batch.save()
    _record(
        batch, 'case_reviewed', actor=actor, request_id=request_id,
        metadata={'farmer_id': str(farmer_id), 'decision': decision, 'comment': comment},
    )
    return batch


def generate_reviewed_workbook(batch_id, *, expected_revision, actor=None, actor_label='', request_id=''):
    replayed = _replayed_batch(request_id, action='workbook_generated', batch_id=batch_id)
    if replayed:
        return replayed
    # Validate and snapshot under a short lock. Workbook generation includes a
    # Drive publication and must never hold database locks during that network
    # operation.
    stale_case_ids = []
    with transaction.atomic():
        batch = PaymentBatch.objects.select_for_update().get(pk=batch_id)
        _require_revision(batch, expected_revision)
        if batch.status != PaymentBatch.STATUS_REVIEW_COMPLETE:
            raise PaymentBatchError('Every current case must be approved before generating the payment workbook.')
        memberships = list(_active_memberships(batch))
        stale_case_ids = [
            str(item.farmer_id)
            for item in memberships
            if not hasattr(item, 'review')
            or item.review.decision != PaymentCaseReview.DECISION_APPROVED
            or item.review.reviewed_digest != case_payment_digest(item.farmer, item.payment_mode)
        ]
        if stale_case_ids:
            invalidated = _invalidate_current_reviews(batch)
            batch.status = PaymentBatch.STATUS_IN_REVIEW
            batch.confirmed_by = None
            batch.confirmed_at = None
            batch.revision += 1
            _refresh_batch_digest(batch)
            batch.save()
            _record(
                batch, 'reviews_invalidated', actor=actor,
                metadata={'farmer_ids': stale_case_ids, 'invalidated_reviews': invalidated},
            )
        else:
            comments = {str(item.farmer_id): item.review.comment for item in memberships}
            case_payment_modes = {str(item.farmer_id): item.payment_mode for item in memberships}
            farmer_ids = list(comments)
            generation_revision = batch.revision
            generation_digest = batch.batch_digest
            payment_number = batch.payment_number
    if stale_case_ids:
        raise PaymentBatchError('Payment details changed after review. Head of Rural must review the changed cases again.')
    # The legacy document model remains the immutable binary artifact store;
    # workflow ownership now lives exclusively on PaymentBatch.
    try:
        document = create_payment_document(
            f'PAYMENT-{payment_number}', str(payment_number),
            actor=actor_label, status='awaiting_scan', farmer_ids=farmer_ids,
            case_call_up_comments=comments, case_payment_modes=case_payment_modes,
        )
    except PaymentTemplateError as exc:
        logger.warning(
            'Payment workbook template rejected: batch=%s payment=%s reason=%s',
            batch_id, payment_number, str(exc),
        )
        raise PaymentBatchError(
            str(exc), code='payment_workbook_template_invalid', status=400,
        ) from exc
    except Exception as exc:
        logger.exception(
            'Payment workbook publication failed: batch=%s payment=%s',
            batch_id, payment_number,
        )
        raise PaymentBatchError(
            'The payment workbook could not be published. The batch is unchanged; retry shortly. '
            'If it continues, share the error reference with IT.',
            code='payment_workbook_publication_failed', status=503,
        ) from exc
    conflict = False
    with transaction.atomic():
        replayed = _replayed_batch(request_id, action='workbook_generated', batch_id=batch_id)
        if replayed:
            document.status = 'superseded'
            document.save(update_fields=['status', 'updated_at'])
            return replayed
        batch = PaymentBatch.objects.select_for_update().get(pk=batch_id)
        if (
            batch.revision != generation_revision
            or batch.batch_digest != generation_digest
            or batch.status != PaymentBatch.STATUS_REVIEW_COMPLETE
        ):
            conflict = True
        else:
            batch.current_document = document
            batch.status = PaymentBatch.STATUS_AWAITING_SCAN
            batch.confirmed_by = actor
            batch.confirmed_at = timezone.now()
            batch.revision += 1
            _refresh_batch_digest(batch)
            batch.save()
            _record(batch, 'workbook_generated', actor=actor, request_id=request_id, metadata={'document_id': str(document.id)})
            return batch
    if conflict:
        document.status = 'superseded'
        document.validation_summary = {
            **(document.validation_summary or {}),
            'superseded_at': timezone.now().isoformat(),
            'reason': 'Payment batch changed while the workbook was being generated.',
        }
        document.save(update_fields=['status', 'validation_summary', 'updated_at'])
        raise PaymentBatchError('The payment batch changed while the workbook was being generated. Refresh and generate it again.')


@transaction.atomic
def cancel_batch(batch_id, *, reason: str, expected_revision, actor=None, request_id=''):
    reason = str(reason or '').strip()
    if not reason:
        raise PaymentBatchError('Give a reason for cancelling this payment batch.')
    replayed = _replayed_batch(
        request_id, action='cancelled', batch_id=batch_id, metadata={'reason': reason},
    )
    if replayed:
        return replayed
    batch = PaymentBatch.objects.select_for_update().get(pk=batch_id)
    _require_revision(batch, expected_revision)
    if batch.status == PaymentBatch.STATUS_COMPLETED:
        raise PaymentBatchError('A completed payment batch cannot be cancelled.')
    if batch.status == PaymentBatch.STATUS_CANCELLED:
        return batch
    _supersede_document(batch)
    batch.status = PaymentBatch.STATUS_CANCELLED
    batch.cancellation_reason = reason
    batch.revision += 1
    batch.save()
    _record(batch, 'cancelled', actor=actor, request_id=request_id, metadata={'reason': reason})
    return batch


@transaction.atomic
def adjust_sequence(
    *, group_configuration, next_number, reason: str, actor=None,
    request_id='', expected_revision=None,
):
    """Explicit IT/Operations repair; allocated payment numbers are never reused."""
    reason = str(reason or '').strip()
    if not reason:
        raise PaymentBatchError('Give a reason for changing the next payment number.')
    try:
        requested = int(next_number)
    except (TypeError, ValueError) as exc:
        raise PaymentBatchError('Enter a valid next payment number.') from exc
    if requested < 1:
        raise PaymentBatchError('The next payment number must be 1 or higher.')
    sequence, _ = PaymentSequenceState.objects.select_for_update().get_or_create(
        group_configuration=group_configuration, defaults={'next_number': 1, 'updated_by': actor},
    )
    if request_id:
        replay = PaymentSequenceEvent.objects.filter(request_id=request_id).first()
        if replay:
            if replay.number_after != requested or replay.reason != reason:
                raise PaymentBatchError('This request key was already used for a different payment-number change.')
            return sequence
    if expected_revision is not None:
        try:
            expected = int(expected_revision)
        except (TypeError, ValueError) as exc:
            raise PaymentBatchError('The payment-number revision is invalid. Refresh and retry.') from exc
        if expected != sequence.revision:
            raise PaymentBatchError('The payment number changed while you were working. Refresh and retry.')
    highest = PaymentBatch.objects.filter(
        group_configuration=group_configuration, payment_number__isnull=False,
    ).order_by('-payment_number').values_list('payment_number', flat=True).first() or 0
    if requested <= highest:
        raise PaymentBatchError(f'The next payment number must be higher than the allocated number {highest}.')
    before = sequence.next_number
    sequence.next_number = requested
    sequence.revision += 1
    sequence.updated_by = actor
    sequence.adjustment_reason = reason
    sequence.save()
    PaymentSequenceEvent.objects.create(
        sequence=sequence, action='adjusted', number_before=before, number_after=requested,
        revision_after=sequence.revision, actor=actor, reason=reason, request_id=request_id,
    )
    return sequence


def serialize_batch(batch: PaymentBatch, *, include_cases=True):
    memberships = list(_active_memberships(batch))
    cases = []
    counts = {'total': len(memberships), 'approved': 0, 'returned': 0, 'pending': 0, 'changed': 0}
    total = Decimal('0')
    mode_counts = {value: 0 for value, _label in PaymentBatchCase.MODE_CHOICES}
    for item in memberships:
        review = getattr(item, 'review', None)
        digest = case_payment_digest(item.farmer, item.payment_mode)
        mode_counts[item.payment_mode] = mode_counts.get(item.payment_mode, 0) + 1
        changed = bool(review and review.reviewed_digest and review.reviewed_digest != digest)
        decision = PaymentCaseReview.DECISION_PENDING if changed or not review else review.decision
        counts[decision if decision in {'approved', 'returned', 'pending'} else 'pending'] += 1
        counts['changed'] += int(changed)
        if item.farmer.balance_due is not None:
            total += item.farmer.balance_due
        if include_cases:
            cases.append({
                'farmer_id': str(item.farmer_id),
                'customer_name': item.farmer.customer_name,
                'national_id': item.farmer.national_id,
                'invoice_number': item.farmer.invoice_number,
                'order_number': item.farmer.order_number,
                'amount': str(item.farmer.balance_due or ''),
                'preferred_repayment_date': format_repayment_day(
                    item.farmer.repayment_day or item.farmer.repayment_date
                ),
                'payment_mode': item.payment_mode,
                'payment_mode_label': item.get_payment_mode_display(),
                'decision': decision,
                'comment': review.comment if review else '',
                'changed_since_review': changed,
            })
    activity = []
    signed_scan_url = ''
    if include_cases:
        for event in batch.events.select_related('actor').order_by('-created_at', '-pk')[:20]:
            actor = event.actor
            activity.append({
                'action': event.action,
                'actor': (actor.get_full_name() or actor.get_username()) if actor else 'System',
                'created_at': event.created_at.isoformat(),
                'revision': event.revision,
            })
        if batch.current_document_id:
            from core.models import DocumentPhysicalSignoff

            signed_scan_url = (
                DocumentPhysicalSignoff.objects.filter(
                    payment_document_id=batch.current_document_id,
                    status=DocumentPhysicalSignoff.STATUS_SIGNED_APPROVED,
                )
                .order_by('-approved_at', '-created_at')
                .values_list('drive_url', flat=True)
                .first()
                or ''
            )
    mode_labels = dict(PaymentBatchCase.MODE_CHOICES)
    payment_mode_summary = ' · '.join(
        f'{count} {mode_labels[mode]}' for mode, count in mode_counts.items() if count
    ) or 'No cases'
    return {
        'id': str(batch.pk), 'payment_number': batch.payment_number,
        'payment_mode_summary': payment_mode_summary, 'payment_mode_counts': mode_counts,
        'status': batch.status, 'status_label': batch.get_status_display(),
        'revision': batch.revision, 'counts': counts, 'total_amount': str(total),
        'cases': cases, 'activity': activity, 'current_document_id': str(batch.current_document_id or ''),
        'current_document_url': batch.current_document.drive_url if batch.current_document_id else '',
        'current_document_download_url': f'/api/portal/payments/batches/{batch.pk}/workbook/' if batch.current_document_id else '',
        'signed_scan_url': signed_scan_url,
        'cancellation_reason': batch.cancellation_reason,
        'created_at': batch.created_at.isoformat(), 'submitted_at': batch.submitted_at.isoformat() if batch.submitted_at else None,
        'completed_at': batch.completed_at.isoformat() if batch.completed_at else None,
    }


@transaction.atomic
def complete_batch_for_document(document, *, actor=None, request_id=''):
    batch = PaymentBatch.objects.select_for_update().filter(current_document=document).first()
    if not batch:
        return None
    if batch.status == PaymentBatch.STATUS_COMPLETED:
        return batch
    if batch.status != PaymentBatch.STATUS_AWAITING_SCAN:
        raise PaymentBatchError('This workbook is no longer the current payment batch version.')
    document.status = 'completed'
    document.finalized_by = getattr(actor, 'get_full_name', lambda: '')() or getattr(actor, 'username', '')
    document.finalized_at = timezone.now()
    document.save(update_fields=['status', 'finalized_by', 'finalized_at', 'updated_at'])
    batch.status = PaymentBatch.STATUS_COMPLETED
    batch.completed_by = actor
    batch.completed_at = timezone.now()
    batch.revision += 1
    batch.save()
    from core.services.jawabu_case360 import record_pipeline_event
    for item in _active_memberships(batch):
        record_pipeline_event(
            item.farmer, action='payment_finalized', stage_key='payment',
            actor=document.finalized_by, request_id=f'payment-batch:{batch.id}:{item.farmer_id}',
            source='payment_batch',
            new_values={'payment_number': str(batch.payment_number), 'payment_mode': item.payment_mode},
            metadata={'payment_batch_id': str(batch.id), 'payment_document_id': str(document.id)},
            actor_user=actor,
        )
    _record(batch, 'signed_scan_accepted', actor=actor, request_id=request_id, metadata={'document_id': str(document.id)})
    return batch
