import uuid

from django.conf import settings
from django.db import models


class PaymentSequenceState(models.Model):
    """Group-scoped source of truth for the next official payment number."""

    id = models.BigAutoField(primary_key=True, db_comment='Internal payment-sequence state identifier.')
    group_configuration = models.OneToOneField(
        'core.GroupSheetConfiguration', on_delete=models.PROTECT,
        related_name='payment_sequence', db_comment='Jawabu group governed by this payment sequence.',
    )
    next_number = models.PositiveBigIntegerField(db_comment='Next official payment number available for allocation.')
    revision = models.PositiveBigIntegerField(default=1, db_comment='Optimistic concurrency revision.')
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+', db_comment='Staff user responsible for the latest sequence mutation.',
    )
    adjustment_reason = models.TextField(blank=True, default='', db_comment='Reason for the latest manual adjustment.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='When this sequence state was created.')
    updated_at = models.DateTimeField(auto_now=True, db_comment='When this sequence state was last changed.')

    class Meta:
        db_table = 'payment_sequence_state'
        db_table_comment = 'Group-scoped allocator for official consecutive payment numbers.'


class PaymentBatch(models.Model):
    STATUS_DRAFT = 'draft'
    STATUS_IN_REVIEW = 'in_review'
    STATUS_REVIEW_COMPLETE = 'review_complete'
    STATUS_AWAITING_SCAN = 'awaiting_scan'
    STATUS_COMPLETED = 'completed'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'), (STATUS_IN_REVIEW, 'In Head of Rural review'),
        (STATUS_REVIEW_COMPLETE, 'Review complete'),
        (STATUS_AWAITING_SCAN, 'Awaiting signed scan'),
        (STATUS_COMPLETED, 'Completed'), (STATUS_CANCELLED, 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Immutable payment batch identifier.')
    group_configuration = models.ForeignKey(
        'core.GroupSheetConfiguration', on_delete=models.PROTECT, related_name='payment_batches',
        db_comment='Jawabu workflow configuration owning this batch.',
    )
    payment_number = models.PositiveBigIntegerField(null=True, blank=True, db_comment='Official immutable number allocated only when a fully reviewed workbook is generated.')
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True, db_comment='Current server-controlled payment batch lifecycle state.')
    revision = models.PositiveBigIntegerField(default=1, db_comment='Optimistic concurrency revision for all batch mutations.')
    batch_digest = models.CharField(max_length=64, blank=True, default='', db_comment='SHA-256 binding of case modes, number, membership, and case payment data.')
    current_document = models.ForeignKey(
        'core.PaymentDocument', null=True, blank=True, on_delete=models.PROTECT,
        related_name='governed_payment_batches', db_comment='Latest generated workbook for this batch revision.',
    )
    receipt_batch = models.OneToOneField(
        'PaymentReceiptBatch', null=True, blank=True, on_delete=models.PROTECT,
        related_name='payment_batch',
        db_comment='Optional invoice receipt bundle from which this governed payment batch was prepared.',
    )
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', db_comment='Staff user who opened the batch.')
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', db_comment='Staff user who first submitted the batch for review.')
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', db_comment='Staff user who generated the current reviewed workbook.')
    completed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', db_comment='Staff user whose accepted scan completed the batch.')
    submitted_at = models.DateTimeField(null=True, blank=True, db_comment='When the batch was first submitted for Head of Rural review.')
    confirmed_at = models.DateTimeField(null=True, blank=True, db_comment='When the current workbook was generated from approved cases.')
    completed_at = models.DateTimeField(null=True, blank=True, db_comment='When the exact signed scan was accepted and the batch locked.')
    cancellation_reason = models.TextField(blank=True, default='', db_comment='Required operational reason when an unfinished batch is cancelled.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='When the payment batch was opened.')
    updated_at = models.DateTimeField(auto_now=True, db_comment='When the payment batch last changed.')

    class Meta:
        db_table = 'payment_batch'
        db_table_comment = 'Authoritative editable payment batch; completed only after an exact signed scan is accepted.'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['group_configuration', 'payment_number'],
                condition=models.Q(payment_number__isnull=False), name='unique_group_payment_number',
            ),
        ]
        indexes = [models.Index(fields=['group_configuration', 'status'], name='payment_batch_group_status_idx')]


class PaymentReceiptBatch(models.Model):
    """One received HomeBiogas invoice delivery, reconciled as a unit.

    This is deliberately separate from ``InvoiceUploadBatch``: the latter is
    evidence for one uploaded PDF while a real HB delivery can contain one
    combined PDF or several files and must yield one payment preparation run.
    """

    STATUS_OPEN = 'open'
    STATUS_RECONCILED = 'reconciled'
    STATUS_PAYMENT_CREATED = 'payment_created'
    STATUS_CHOICES = [
        (STATUS_OPEN, 'Reconciling'),
        (STATUS_RECONCILED, 'Ready for payment'),
        (STATUS_PAYMENT_CREATED, 'Payment batch created'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Immutable invoice delivery identifier.')
    group_configuration = models.ForeignKey(
        'core.GroupSheetConfiguration', on_delete=models.PROTECT, related_name='payment_receipt_batches',
        db_comment='Jawabu workflow configuration which received this invoice delivery.',
    )
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_OPEN, db_index=True, db_comment='Server-controlled reconciliation state for this invoice delivery.')
    revision = models.PositiveBigIntegerField(default=1, db_comment='Optimistic concurrency revision for reconciliation changes.')
    request_id = models.CharField(max_length=128, blank=True, default='', db_index=True, db_comment='Idempotency key for the source upload request.')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', db_comment='Staff member who received the invoice delivery.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='When the invoice delivery was received.')
    updated_at = models.DateTimeField(auto_now=True, db_comment='When reconciliation was last changed.')

    class Meta:
        db_table = 'payment_receipt_batch'
        db_table_comment = 'Authoritative multi-file HomeBiogas invoice delivery reconciled as one payment source.'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['request_id'], condition=~models.Q(request_id=''), name='payment_receipt_batch_request_unique'),
        ]
        indexes = [models.Index(fields=['group_configuration', 'status'], name='payrcpt_group_status_idx')]


class PaymentReceiptItem(models.Model):
    """One parsed invoice and its payment disposition within a receipt batch."""

    STATUS_MATCHED = 'matched'
    STATUS_NAME_CHANGE = 'name_change'
    STATUS_REVIEW = 'review'
    STATUS_PARSE_FAILED = 'parse_failed'
    STATUS_IGNORED = 'ignored'
    STATUS_CHOICES = [
        (STATUS_MATCHED, 'Matched and payable'),
        (STATUS_NAME_CHANGE, 'Invoice name change required'),
        (STATUS_REVIEW, 'Needs review'),
        (STATUS_PARSE_FAILED, 'Could not parse'),
        (STATUS_IGNORED, 'Ignored'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Immutable receipt-item identifier.')
    receipt_batch = models.ForeignKey(PaymentReceiptBatch, on_delete=models.PROTECT, related_name='items', db_comment='Received invoice delivery containing this item.')
    invoice = models.OneToOneField('core.ParsedInvoice', null=True, blank=True, on_delete=models.PROTECT, related_name='payment_receipt_item', db_comment='Parsed invoice evidence; blank only for a source parse failure.')
    source_upload = models.ForeignKey('core.InvoiceUploadBatch', on_delete=models.PROTECT, related_name='payment_receipt_items', db_comment='Original uploaded PDF evidence for this item.')
    farmer = models.ForeignKey('core.JawabuFarmerMaster', null=True, blank=True, on_delete=models.PROTECT, related_name='payment_receipt_items', db_comment='Proposed or matched contractual borrower.')
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_REVIEW, db_index=True, db_comment='Reconciliation disposition; only matched rows may become payment cases.')
    reason = models.TextField(blank=True, default='', db_comment='Plain-language reason for a held or failed item.')
    replacement_invoice = models.ForeignKey('core.ParsedInvoice', null=True, blank=True, on_delete=models.PROTECT, related_name='+', db_comment='Corrected invoice explicitly attached to this held source invoice.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='When this receipt item was created.')
    updated_at = models.DateTimeField(auto_now=True, db_comment='When this receipt item last changed.')

    class Meta:
        db_table = 'payment_receipt_item'
        db_table_comment = 'Per-invoice payment reconciliation result, including non-payable held rows.'
        constraints = [
            models.UniqueConstraint(fields=['receipt_batch', 'source_upload', 'invoice'], name='payment_receipt_item_source_invoice_unique'),
        ]
        indexes = [models.Index(fields=['receipt_batch', 'status'], name='payrcpt_item_batch_status_idx')]


class PaymentBatchCase(models.Model):
    """Auditable membership of one canonical Portal case in a payment batch."""

    MODE_LOAN_JAWABU = 'LOAN-JAWABU'
    MODE_CASH = 'CASH'
    MODE_CHOICES = [(MODE_LOAN_JAWABU, 'Loan - Jawabu'), (MODE_CASH, 'Cash')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Immutable membership identifier.')
    batch = models.ForeignKey(PaymentBatch, on_delete=models.PROTECT, related_name='case_memberships', db_comment='Authoritative payment batch containing this membership history.')
    farmer = models.ForeignKey('core.JawabuFarmerMaster', on_delete=models.PROTECT, related_name='payment_batch_memberships', db_comment='Canonical Portal case selected for payment.')
    payment_mode = models.CharField(max_length=20, choices=MODE_CHOICES, db_comment='Payment route selected specifically for this case.')
    is_active = models.BooleanField(default=True, db_index=True, db_comment='Whether this case is currently included in the batch.')
    case_digest = models.CharField(max_length=64, db_comment='Current payment-data digest captured when membership or review changed.')
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', db_comment='Staff user who most recently added this case.')
    removed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', db_comment='Staff user who most recently removed this case.')
    removed_reason = models.TextField(blank=True, default='', db_comment='Required reason for the latest removal.')
    added_at = models.DateTimeField(auto_now_add=True, db_comment='When this membership was first created.')
    removed_at = models.DateTimeField(null=True, blank=True, db_comment='When this case was most recently removed.')
    updated_at = models.DateTimeField(auto_now=True, db_comment='When this membership last changed.')

    class Meta:
        db_table = 'payment_batch_case'
        db_table_comment = 'Current and removed case membership for an authoritative payment batch.'
        constraints = [
            models.UniqueConstraint(fields=['batch', 'farmer'], name='unique_payment_batch_case'),
            models.CheckConstraint(
                condition=models.Q(payment_mode__in=['LOAN-JAWABU', 'CASH']),
                name='payment_batch_case_mode_valid',
            ),
        ]
        indexes = [models.Index(fields=['batch', 'is_active'], name='payment_batch_case_active_idx')]


class PaymentCaseReview(models.Model):
    DECISION_PENDING = 'pending'
    DECISION_APPROVED = 'approved'
    DECISION_RETURNED = 'returned'
    DECISION_CHOICES = [
        (DECISION_PENDING, 'Awaiting review'),
        (DECISION_APPROVED, 'Approved'),
        (DECISION_RETURNED, 'Returned'),
    ]

    id = models.BigAutoField(primary_key=True, db_comment='Internal payment case-review identifier.')
    membership = models.OneToOneField(PaymentBatchCase, on_delete=models.PROTECT, related_name='review', db_comment='Case membership whose current values were reviewed.')
    decision = models.CharField(max_length=16, choices=DECISION_CHOICES, default=DECISION_PENDING, db_index=True, db_comment='Current Head of Rural decision for this case.')
    comment = models.TextField(blank=True, default='', db_comment='Required operational review comment for an approve or return decision.')
    reviewed_digest = models.CharField(max_length=64, blank=True, default='', db_comment='Exact case payment-data digest approved or returned by the reviewer.')
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', db_comment='Head of Rural staff user responsible for the current decision.')
    reviewed_at = models.DateTimeField(null=True, blank=True, db_comment='When the current decision was recorded.')
    revision = models.PositiveBigIntegerField(default=1, db_comment='Monotonic review mutation revision.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='When the review record was created.')
    updated_at = models.DateTimeField(auto_now=True, db_comment='When the review record last changed.')

    class Meta:
        db_table = 'payment_case_review'
        db_table_comment = 'Durable per-case Head of Rural payment decision bound to exact case data.'


class PaymentSequenceEvent(models.Model):
    id = models.BigAutoField(primary_key=True, db_comment='Immutable payment-sequence event identifier.')
    sequence = models.ForeignKey(PaymentSequenceState, on_delete=models.PROTECT, related_name='events', db_comment='Sequence state changed by this event.')
    batch = models.ForeignKey(PaymentBatch, null=True, blank=True, on_delete=models.PROTECT, related_name='sequence_events', db_comment='Payment batch receiving an allocation, when applicable.')
    action = models.CharField(max_length=24, db_comment='Allocation or explicit administrative adjustment action.')
    number_before = models.PositiveBigIntegerField(db_comment='Number available before this mutation.')
    number_after = models.PositiveBigIntegerField(db_comment='Number available after this mutation.')
    revision_after = models.PositiveBigIntegerField(db_comment='Sequence revision after this mutation.')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', db_comment='Staff user responsible for this mutation.')
    reason = models.TextField(db_comment='Required human-readable reason for allocation or adjustment.')
    request_id = models.CharField(max_length=128, blank=True, default='', db_index=True, db_comment='Idempotency request identifier; blank only for internal historical operations.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='When this immutable sequence event was recorded.')

    class Meta:
        db_table = 'payment_sequence_event'
        db_table_comment = 'Immutable evidence for every payment-number allocation or adjustment.'
        constraints = [models.UniqueConstraint(fields=['request_id'], condition=~models.Q(request_id=''), name='unique_payment_sequence_request')]


class PaymentBatchEvent(models.Model):
    id = models.BigAutoField(primary_key=True, db_comment='Immutable payment-batch event identifier.')
    batch = models.ForeignKey(PaymentBatch, on_delete=models.PROTECT, related_name='events', db_comment='Payment batch changed by this event.')
    action = models.CharField(max_length=40, db_comment='Stable machine-readable payment batch action.')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', db_comment='Staff user responsible for the action.')
    request_id = models.CharField(max_length=128, blank=True, default='', db_index=True, db_comment='Idempotency request identifier; blank only for internal historical operations.')
    revision = models.PositiveBigIntegerField(db_comment='Batch revision produced by the action.')
    metadata = models.JSONField(default=dict, blank=True, db_comment='Customer-data-minimized action details needed for audit interpretation.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='When this immutable batch event was recorded.')

    class Meta:
        db_table = 'payment_batch_event'
        db_table_comment = 'Append-only customer-data-minimized history of payment batch mutations.'
        ordering = ['created_at', 'pk']
        constraints = [models.UniqueConstraint(fields=['request_id'], condition=~models.Q(request_id=''), name='unique_payment_batch_event_request')]
