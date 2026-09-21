"""Invoice-delivery reconciliation used to build governed payment batches.

The invoice parser retains evidence per PDF.  This module adds the operational
unit staff actually receive from HomeBiogas: one delivery which may contain
many PDFs and many invoices.  It deliberately never changes a completed
payment batch.
"""
from __future__ import annotations

from collections import Counter

from django.db import transaction

from core.models import JawabuFarmerMaster, ParsedInvoice
from core.services.identifiers import normalize_national_id
from core.services.invoice_identity import identity_gate, normalize_person_name
from core.services.invoice_parser import clean_phone, official_requisition_eligibility
from payments.models import PaymentBatch, PaymentReceiptBatch, PaymentReceiptItem


class PaymentReceiptError(ValueError):
    pass


def _linked_batch(receipt: PaymentReceiptBatch):
    try:
        return receipt.payment_batch
    except PaymentBatch.DoesNotExist:
        return None


def _candidate_for(invoice: ParsedInvoice, farmers: list[JawabuFarmerMaster]):
    """Return one likely case for a held invoice without treating it as paid.

    An invoice can legitimately name the FarmUp lead while SysUp establishes a
    different borrower.  Lead identifiers are therefore useful only to find
    the case and open a correction hold; the payment gate still compares the
    invoice against the contractual borrower.
    """
    invoice_id = normalize_national_id(invoice.customer_id)
    invoice_name = normalize_person_name(invoice.customer_name)
    invoice_phone = clean_phone(invoice.customer_phone)
    matches = []
    for farmer in farmers:
        identities = (
            (farmer.national_id, farmer.imab_customer_name or farmer.customer_name, farmer.primary_phone),
            (farmer.lead_national_id, farmer.lead_name, farmer.lead_primary_phone),
        )
        for national_id, name, phone in identities:
            if invoice_id and invoice_id == normalize_national_id(national_id):
                matches.append(farmer)
                break
            if invoice_name and invoice_name == normalize_person_name(name):
                matches.append(farmer)
                break
            if invoice_phone and invoice_phone == clean_phone(phone):
                matches.append(farmer)
                break
    unique = {farmer.pk: farmer for farmer in matches}
    return next(iter(unique.values())) if len(unique) == 1 else None


def _item_disposition(invoice: ParsedInvoice | None, farmer: JawabuFarmerMaster | None):
    if invoice is None:
        return PaymentReceiptItem.STATUS_PARSE_FAILED, None, 'No usable invoice was parsed from this source file.'
    if invoice.status == 'ignored':
        return PaymentReceiptItem.STATUS_IGNORED, farmer, 'This invoice was intentionally ignored.'
    farmer = farmer or invoice.matched_farmer or invoice.proposed_farmer
    if not farmer:
        return PaymentReceiptItem.STATUS_REVIEW, None, invoice.review_notes or 'No unique case was found for this invoice.'
    gate = identity_gate(invoice, farmer)
    discrepancy = set(gate.get('discrepancy_codes') or [])
    # A receipt batch applies the agreed stricter rule: a present name or ID
    # difference is a correction hold, even if a legacy invoice match exists.
    if {'national_id_mismatch', 'name_variance'} & discrepancy:
        return PaymentReceiptItem.STATUS_NAME_CHANGE, farmer, 'Invoice holder differs from the committed loan applicant. Request a corrected invoice.'
    if 'national_id_missing' in discrepancy:
        return PaymentReceiptItem.STATUS_REVIEW, farmer, 'The invoice holder or loan applicant national ID is missing.'
    if gate.get('blocker'):
        return PaymentReceiptItem.STATUS_REVIEW, farmer, str(gate.get('message') or invoice.review_notes or 'This invoice is not ready for payment.')
    if invoice.status == 'matched' and invoice.matched_farmer_id == farmer.id:
        return PaymentReceiptItem.STATUS_MATCHED, farmer, ''
    return PaymentReceiptItem.STATUS_REVIEW, farmer, invoice.review_notes or 'Confirm this invoice against the contractual borrower.'


def _refresh_status(receipt: PaymentReceiptBatch):
    statuses = set(receipt.items.values_list('status', flat=True))
    if _linked_batch(receipt):
        wanted = PaymentReceiptBatch.STATUS_PAYMENT_CREATED
    elif statuses and statuses <= {PaymentReceiptItem.STATUS_MATCHED, PaymentReceiptItem.STATUS_IGNORED}:
        wanted = PaymentReceiptBatch.STATUS_RECONCILED
    else:
        wanted = PaymentReceiptBatch.STATUS_OPEN
    if receipt.status != wanted:
        receipt.status = wanted
        receipt.revision += 1
        receipt.save(update_fields=['status', 'revision', 'updated_at'])


@transaction.atomic
def create_receipt_batch(*, group_configuration, uploads, actor=None, request_id: str = ''):
    """Create or replay a source bundle from already parsed invoice PDFs."""
    request_id = str(request_id or '').strip()
    if request_id:
        existing = PaymentReceiptBatch.objects.select_for_update().filter(request_id=request_id).first()
        if existing:
            return existing, True
    uploads = list(uploads)
    if not uploads:
        raise PaymentReceiptError('At least one invoice PDF is required.')
    receipt = PaymentReceiptBatch.objects.create(
        group_configuration=group_configuration, request_id=request_id, created_by=actor,
    )
    farmers = list(JawabuFarmerMaster.objects.filter(status='active').order_by('customer_name'))
    for upload in uploads:
        invoices = list(upload.invoices.select_related('matched_farmer', 'proposed_farmer').order_by('page', 'created_at'))
        if not invoices:
            PaymentReceiptItem.objects.create(
                receipt_batch=receipt, source_upload=upload,
                status=PaymentReceiptItem.STATUS_PARSE_FAILED,
                reason=upload.error or 'No usable invoice was parsed from this source file.',
            )
            continue
        for invoice in invoices:
            farmer = invoice.matched_farmer or invoice.proposed_farmer or _candidate_for(invoice, farmers)
            status, farmer, reason = _item_disposition(invoice, farmer)
            PaymentReceiptItem.objects.create(
                receipt_batch=receipt, source_upload=upload, invoice=invoice,
                farmer=farmer, status=status, reason=reason,
            )
    _refresh_status(receipt)
    return receipt, False


def serialize_receipt_batch(receipt: PaymentReceiptBatch, *, include_items: bool = False) -> dict:
    items = receipt.items.select_related('invoice', 'farmer', 'source_upload', 'replacement_invoice').order_by('created_at')
    counts = Counter(items.values_list('status', flat=True))
    data = {
        'id': str(receipt.pk), 'status': receipt.status,
        'status_label': receipt.get_status_display(), 'revision': receipt.revision,
        'payment_batch_id': str(getattr(_linked_batch(receipt), 'pk', '') or ''),
        'created_at': receipt.created_at.isoformat(),
        'counts': {status: int(counts.get(status, 0)) for status, _label in PaymentReceiptItem.STATUS_CHOICES},
        'total_count': sum(counts.values()),
    }
    if include_items:
        data['items'] = [
            {
                'id': str(item.pk), 'status': item.status, 'status_label': item.get_status_display(),
                'reason': item.reason, 'source_filename': item.source_upload.original_filename,
                'invoice_id': str(item.invoice_id or ''), 'replacement_invoice_id': str(item.replacement_invoice_id or ''),
                'invoice_no': item.invoice.invoice_no if item.invoice_id else '',
                'invoice_date': item.invoice.invoice_date.isoformat() if item.invoice_id and item.invoice.invoice_date else '',
                'invoice_holder_name': item.invoice.customer_name if item.invoice_id else '',
                'invoice_holder_id': item.invoice.customer_id if item.invoice_id else '',
                'invoice_amount': str(item.invoice.balance_due) if item.invoice_id and item.invoice.balance_due is not None else '',
                'farmer_id': str(item.farmer_id or ''),
                'lead_name': item.farmer.lead_name if item.farmer_id else '',
                'lead_national_id': item.farmer.lead_national_id if item.farmer_id else '',
                'applicant_name': (item.farmer.imab_customer_name or item.farmer.customer_name) if item.farmer_id else '',
                'applicant_national_id': item.farmer.national_id if item.farmer_id else '',
            }
            for item in items
        ]
    return data


@transaction.atomic
def create_payment_batch_from_receipt(*, receipt_id, payment_modes, expected_revision, actor=None, request_id=''):
    """Build the governed payable membership from one invoice delivery.

    Unmatched and ignored items remain held. A matched applicant whose
    invoice-holder name is awaiting correction remains traceable to this
    delivery and is included with a visible advisory; signed-scan acceptance
    still defines finality.
    """
    from payments.services import PaymentBatchError, add_cases, create_batch

    receipt = PaymentReceiptBatch.objects.select_for_update().select_related('group_configuration').get(pk=receipt_id)
    if int(expected_revision) != receipt.revision:
        raise PaymentReceiptError('This invoice batch changed while you were working. Refresh it before creating payment.')
    existing_batch = _linked_batch(receipt)
    if existing_batch:
        return existing_batch, True
    payable = list(receipt.items.select_for_update().filter(
        status__in=(
            PaymentReceiptItem.STATUS_MATCHED,
            PaymentReceiptItem.STATUS_NAME_CHANGE,
        ),
        farmer__isnull=False,
    ))
    if not payable:
        raise PaymentReceiptError('This invoice batch has no reconciled invoices ready for payment.')
    farmer_ids = [str(item.farmer_id) for item in payable]
    if len(set(farmer_ids)) != len(farmer_ids):
        raise PaymentReceiptError('More than one invoice in this delivery is matched to the same case. Resolve the duplicate first.')
    batch = create_batch(group_configuration=receipt.group_configuration, actor=actor, request_id=f'{request_id}:batch' if request_id else '')
    batch.receipt_batch = receipt
    batch.save(update_fields=['receipt_batch', 'updated_at'])
    # Loan - Jawabu is the operational default. The payment workspace exposes
    # Cash as an explicit per-case switch, so an invoice delivery must not
    # fail merely because the caller omitted the default for one row.
    supplied_modes = payment_modes if isinstance(payment_modes, dict) else {}
    effective_payment_modes = {
        str(item.farmer_id): supplied_modes.get(str(item.farmer_id), 'LOAN-JAWABU')
        for item in payable
    }
    try:
        add_cases(
            batch.pk, farmer_ids=farmer_ids, payment_modes=effective_payment_modes,
            expected_revision=batch.revision, actor=actor, request_id=f'{request_id}:cases' if request_id else '',
        )
    except PaymentBatchError as exc:
        raise PaymentReceiptError(str(exc)) from exc
    batch.refresh_from_db()
    receipt.status = PaymentReceiptBatch.STATUS_PAYMENT_CREATED
    receipt.revision += 1
    receipt.save(update_fields=['status', 'revision', 'updated_at'])
    return batch, False


@transaction.atomic
def attach_replacement(*, item_id, invoice_id, expected_revision, actor=None):
    # Use the same lock order as invoice-name-change confirmation: invoice,
    # receipt item, then optional payment batch.  This prevents a correction
    # submitted from the Invoice screen racing a direct receipt update.
    item_probe = PaymentReceiptItem.objects.select_related('receipt_batch').get(pk=item_id)
    invoice = ParsedInvoice.objects.select_for_update().filter(pk=invoice_id).first()
    if not invoice:
        raise PaymentReceiptError('The corrected invoice was not found.')
    item = PaymentReceiptItem.objects.select_for_update().select_related('receipt_batch').get(pk=item_probe.pk)
    receipt = item.receipt_batch
    # Lock the optional linked batch separately: selecting the nullable
    # reverse relation would otherwise recreate PostgreSQL's forbidden
    # ``FOR UPDATE`` outer-join shape.
    linked_batch = PaymentBatch.objects.select_for_update().filter(receipt_batch=receipt).first()
    if linked_batch and linked_batch.status == PaymentBatch.STATUS_COMPLETED:
        raise PaymentReceiptError('This payment batch is signed and completed. Keep the correction as evidence and use a new payment batch.')
    if int(expected_revision) != receipt.revision:
        raise PaymentReceiptError('This invoice batch changed while you were working. Refresh it before attaching the corrected invoice.')
    farmer = item.farmer or invoice.matched_farmer or invoice.proposed_farmer
    status, farmer, reason = _item_disposition(invoice, farmer)
    item.replacement_invoice = invoice
    item.farmer = farmer
    item.status = status
    item.reason = reason
    item.save(update_fields=['replacement_invoice', 'farmer', 'status', 'reason', 'updated_at'])
    if linked_batch:
        # The evidence behind an unsigned payment changed.  Keep existing
        # membership intact (an explicitly matched replacement may be added
        # through the governed payment action) but invalidate any workbook or
        # Head-of-Rural review that was made from the earlier evidence.
        from payments.services import _invalidate_current_reviews, _refresh_batch_digest, _status_after_edit, _supersede_document

        _supersede_document(linked_batch)
        invalidated = _invalidate_current_reviews(linked_batch)
        linked_batch.status = _status_after_edit(linked_batch)
        linked_batch.revision += 1
        _refresh_batch_digest(linked_batch)
        linked_batch.save()
        # Use the existing batch event ledger so this evidence correction is
        # visible beside the batch it affected.
        from payments.services import _record
        _record(
            linked_batch, 'receipt_invoice_replaced', actor=actor,
            metadata={
                'receipt_item_id': str(item.pk), 'replacement_invoice_id': str(invoice.pk),
                'invalidated_reviews': invalidated,
            },
        )
    receipt.revision += 1
    receipt.save(update_fields=['revision', 'updated_at'])
    _refresh_status(receipt)
    return item
