"""
Database models for the biogas telegram bot system.
Provides full traceability and deduplication support.
"""
import uuid
import re
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models.functions import Lower
from django.utils import timezone


def bot_display_name() -> str:
    from django.conf import settings

    return getattr(settings, 'TELEGRAM_BOT_DISPLAY_NAME', 'Telegram Bot')


class RawMessage(models.Model):
    """
    Stores original message data for traceability.
    Never modified after creation - audit trail guarantee.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    telegram_message_id = models.CharField(max_length=255, db_index=True)
    source_telegram_message_id = models.CharField(
        max_length=255,
        blank=True,
        default='',
        db_index=True,
        help_text='Original Telegram message_id before batch splitting.',
    )
    batch_index = models.PositiveIntegerField(null=True, blank=True)
    sender = models.CharField(max_length=255, blank=True, default='')
    content = models.TextField()
    received_at = models.DateTimeField(default=timezone.now)
    has_image = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-received_at']
        indexes = [
            models.Index(fields=['telegram_message_id', 'received_at']),
            models.Index(fields=['source_telegram_message_id', 'received_at']),
        ]

    def __str__(self):
        return f"RawMessage from {self.sender} at {self.received_at}"


class ProcessedMessage(models.Model):
    """
    Tracks which messages have been processed to prevent duplicates.
    message_hash is the deduplication key.
    """
    STATUS_CHOICES = [
        ('success', 'Successfully Processed'),
        ('failed', 'Processing Failed'),
        ('partial', 'Partially Processed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    message_hash = models.CharField(max_length=128, unique=True, db_index=True)
    raw_message = models.ForeignKey(
        RawMessage,
        on_delete=models.CASCADE,
        related_name='processed_records'
    )
    processed_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='success')
    error_message = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-processed_at']

    def __str__(self):
        return f"ProcessedMessage [{self.status}] - {self.message_hash[:12]}..."


class ParsedMessage(models.Model):
    """
    Structured data extracted from raw messages.
    Maps directly to Google Sheets schema.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    processed_message = models.ForeignKey(
        ProcessedMessage,
        on_delete=models.CASCADE,
        related_name='parsed_records'
    )
    
    # Google Sheet fields
    message_id = models.CharField(max_length=128, db_index=True)
    timestamp = models.DateTimeField(null=True, blank=True)
    sender = models.CharField(max_length=255, blank=True, default='')
    raw_message = models.TextField()
    item = models.CharField(max_length=255, blank=True, default='')
    quantity = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    gps_link = models.URLField(max_length=500, blank=True, default='')
    image_flag = models.BooleanField(default=False)
    source = models.CharField(max_length=50, default='telegram bot')
    
    customer_name = models.CharField(max_length=255, blank=True, default='')
    customer_phone = models.CharField(max_length=255, blank=True, default='')
    customer_id = models.CharField(max_length=255, blank=True, default='')
    branch_region = models.CharField(max_length=255, blank=True, default='')
    complaint_category = models.CharField(max_length=255, blank=True, default='')
    complaint_description = models.TextField(blank=True, default='')
    complaint_status = models.CharField(max_length=255, blank=True, default='')
    resolution_details = models.TextField(blank=True, default='')
    date_resolved = models.DateTimeField(null=True, blank=True)
    days_open = models.IntegerField(null=True, blank=True)
    risk_level = models.CharField(max_length=100, blank=True, default='')
    loan_status = models.CharField(max_length=100, blank=True, default='')
    loan_at_risk = models.CharField(max_length=100, blank=True, default='')
    
    # Multi-tenant routing
    group_id = models.CharField(max_length=100, default='default', db_index=True)
    sheet_id = models.CharField(
        max_length=255,
        blank=True,
        default='',
        db_index=True,
        help_text='Google spreadsheet ID this case was last mirrored from/to.',
    )
    sheet_name = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text='Worksheet/tab name this case was last mirrored from/to.',
    )
    
    # Google Sheets sync tracking
    synced_to_sheets = models.BooleanField(default=False)
    synced_at = models.DateTimeField(null=True, blank=True)
    sync_attempts = models.IntegerField(default=0)
    last_sync_error = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        constraints = [
            models.UniqueConstraint(
                fields=['group_id', 'message_id'],
                name='unique_case_message_per_group',
            ),
        ]
        indexes = [
            models.Index(fields=['message_id']),
            models.Index(fields=['group_id', 'sheet_id']),
            models.Index(fields=['synced_to_sheets']),
        ]

    def __str__(self):
        return f"ParsedMessage: {self.item or 'unknown'} by {self.sender}"

    @staticmethod
    def _format_sheet_date(value):
        if not value:
            return ''
        if isinstance(value, str):
            try:
                from dateutil import parser as date_parser
                value = date_parser.parse(value)
            except Exception:
                return value
        return value.strftime('%d/%m/%Y')

    @staticmethod
    def _format_phone(value):
        digits = re.sub(r'\D', '', str(value or ''))
        if digits.startswith('254') and len(digits) == 12:
            return digits
        if digits.startswith('0') and len(digits) == 10 and digits[1] in {'1', '7'}:
            return '254' + digits[1:]
        if len(digits) == 9 and digits[0] in {'1', '7'}:
            return '254' + digits
        return str(value or '')

    def to_sheet_row(self):
        """
        Convert to Google Sheet row format (21 columns).
        
        Column mapping (CRITICAL):
        [0]  Complaint ID (FORMULA - bot leaves blank, different from message_id)
        [1]  message_id (bot dedup key)
        [2]  Date Reported (bot writes)
        [3]  Customer Name (bot writes - CAPITALIZED)
        [4]  Customer ID / Account (bot writes)
        [5]  Phone Number (bot writes)
        [6]  JBL Reported By (bot writes - Telegram sender/tag)
        [7]  Branch / Region (bot writes - best effort)
        [8]  Complaint Category (bot writes - must match dropdown, not description)
        [9]  Complaint Description (bot writes)
        [10] raw_message (bot writes - audit trail)
        [11] gps_link (bot writes)
        [12] image_flag (bot writes - string: "TRUE" or "")
        [13] source (bot writes - "telegram bot")
        [14] Loan Status (HUMAN - dropdown)
        [15] Loan at Risk (HUMAN - dropdown)
        [16] Risk Level (HUMAN)
        [17] Status (HUMAN - dropdown: Open/Closed)
        [18] Resolution Details (HUMAN)
        [19] Date Resolved (HUMAN)
        [20] Days Open (FORMULA - bot should NOT write)
        """
        return [
            '',                                                                          # [0] Complaint ID (blank, different from message_id)
            self.message_id,                                                              # [1] message_id
            self._format_sheet_date(self.timestamp),                                     # [2] Date Reported
            self.customer_name.upper() if self.customer_name else '',                    # [3] Customer Name (CAPITALIZED)
            self.customer_id,                                                             # [4] Customer ID / Account
            self._format_phone(self.customer_phone),                                      # [5] Phone Number
            self.sender or bot_display_name(),                                            # [6] Reported By (message sender)
            self.branch_region,                                                           # [7] Branch / Region
            self.complaint_category,                                                      # [8] Complaint Category
            self.complaint_description,                                                   # [9] Complaint Description
            self.raw_message,                                                             # [10] raw_message
            self.gps_link,                                                                # [11] gps_link
            'TRUE' if self.image_flag else '',                                            # [12] image_flag
            self.source,                                                                  # [13] source
            self.loan_status,                                                             # [14] Loan Status
            self.loan_at_risk,                                                            # [15] Loan at Risk
            self.risk_level,                                                              # [16] Risk Level
            self.complaint_status,                                                        # [17] Status
            self.resolution_details,                                                      # [18] Resolution Details
            self._format_sheet_date(self.date_resolved),                                # [19] Date Resolved
            str(self.days_open) if self.days_open is not None else '',                   # [20] Days Open
        ]


class CaseUpdate(models.Model):
    """Audit trail for chat-driven case status/resolution updates."""

    SYNC_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('success', 'Synced'),
        ('failed', 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    parsed_message = models.ForeignKey(
        ParsedMessage,
        on_delete=models.CASCADE,
        related_name='case_updates',
    )
    group_id = models.CharField(max_length=100, db_index=True)
    updated_by = models.CharField(max_length=255, blank=True, default='')
    telegram_message_id = models.CharField(max_length=255, blank=True, default='')
    reply_to_telegram_message_id = models.CharField(max_length=255, blank=True, default='')

    old_status = models.CharField(max_length=255, blank=True, default='')
    new_status = models.CharField(max_length=255, blank=True, default='')
    resolution_text = models.TextField(blank=True, default='')
    risk_level = models.CharField(max_length=100, blank=True, default='')
    loan_at_risk = models.CharField(max_length=100, blank=True, default='')

    sync_status = models.CharField(
        max_length=20,
        choices=SYNC_STATUS_CHOICES,
        default='pending',
    )
    sync_error = models.TextField(blank=True, default='')
    raw_update_text = models.TextField()
    source = models.CharField(max_length=50, default='telegram')
    client_request_id = models.CharField(max_length=128, blank=True, default='', db_index=True)
    gps_link = models.URLField(max_length=500, blank=True, default='')
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['group_id', 'created_at']),
            models.Index(fields=['telegram_message_id']),
            models.Index(fields=['reply_to_telegram_message_id']),
            models.Index(fields=['parsed_message', 'client_request_id']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['parsed_message', 'client_request_id'],
                condition=~models.Q(client_request_id=''),
                name='unique_complaint_case_update_request',
            ),
        ]

    def __str__(self):
        return f"CaseUpdate {self.parsed_message.message_id}: {self.new_status}"


class ComplaintCaseSequence(models.Model):
    """Durable per-group/year sequence for staff-facing complaint references."""

    group_id = models.CharField(max_length=100, db_index=True)
    year = models.PositiveIntegerField(db_index=True)
    next_number = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['group_id', 'year'], name='unique_complaint_sequence_group_year'),
        ]
        verbose_name = 'Complaint case sequence'
        verbose_name_plural = 'Complaint case sequences'

    def __str__(self):
        return f"{self.group_id} {self.year}: next {self.next_number}"


class ComplaintCaseEvidence(models.Model):
    """Drive-backed, append-only evidence uploaded for a complaint case."""

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('success', 'Uploaded'),
        ('failed', 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    parsed_message = models.ForeignKey(
        ParsedMessage,
        on_delete=models.CASCADE,
        related_name='complaint_evidence',
    )
    case_update = models.ForeignKey(
        CaseUpdate,
        on_delete=models.CASCADE,
        related_name='evidence',
    )
    group_id = models.CharField(max_length=100, db_index=True)
    uploaded_by = models.CharField(max_length=255, blank=True, default='')
    original_filename = models.CharField(max_length=255, blank=True, default='')
    mime_type = models.CharField(max_length=255, blank=True, default='')
    size = models.PositiveIntegerField(null=True, blank=True)
    content_hash = models.CharField(max_length=64, blank=True, default='', db_index=True)
    drive_file_id = models.CharField(max_length=255, blank=True, default='')
    drive_url = models.URLField(max_length=1000, blank=True, default='')
    upload_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    upload_error = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['parsed_message', 'created_at']),
            models.Index(fields=['group_id', 'upload_status']),
        ]

    def __str__(self):
        return f"Complaint evidence {self.original_filename or self.id}"


class OrderApprovalUpdate(models.Model):
    """Audit trail for Telegram-driven order approval BRO updates."""

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('success', 'Synced'),
        ('failed', 'Failed'),
        ('no_match', 'No Matching Row'),
        ('duplicate', 'Duplicate Sheet Rows'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group_id = models.CharField(max_length=100, db_index=True)
    sheet_id = models.CharField(max_length=255, blank=True, default='', db_index=True)
    sheet_tab = models.CharField(max_length=255, blank=True, default='')
    row_number = models.PositiveIntegerField(null=True, blank=True)
    id_number = models.CharField(max_length=255, blank=True, default='', db_index=True)
    sender = models.CharField(max_length=255, blank=True, default='')
    telegram_message_id = models.CharField(max_length=255, blank=True, default='', db_index=True)
    reply_to_telegram_message_id = models.CharField(max_length=255, blank=True, default='')
    raw_text = models.TextField(blank=True, default='')
    parsed_fields = models.JSONField(blank=True, default=dict)
    update_status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
    )
    sync_error = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['group_id', 'created_at']),
            models.Index(fields=['group_id', 'id_number']),
            models.Index(fields=['telegram_message_id']),
        ]

    def __str__(self):
        location = f"{self.sheet_tab}!{self.row_number}" if self.row_number else self.sheet_tab
        return f"OrderApprovalUpdate {self.id_number or 'unknown'} {location}".strip()


class MediaAttachment(models.Model):
    """Audit record for media uploaded from Telegram to external storage."""

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('success', 'Uploaded'),
        ('failed', 'Failed'),
        ('skipped', 'Skipped'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order_update = models.ForeignKey(
        OrderApprovalUpdate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='media_attachments',
    )
    group_id = models.CharField(max_length=100, db_index=True)
    telegram_message_id = models.CharField(max_length=255, blank=True, default='', db_index=True)
    reply_to_telegram_message_id = models.CharField(max_length=255, blank=True, default='')
    telegram_file_id = models.CharField(max_length=255, blank=True, default='', db_index=True)
    sender = models.CharField(max_length=255, blank=True, default='')
    file_type = models.CharField(max_length=50, blank=True, default='')
    original_filename = models.CharField(max_length=255, blank=True, default='')
    mime_type = models.CharField(max_length=255, blank=True, default='')
    size = models.PositiveIntegerField(null=True, blank=True)
    content_hash = models.CharField(max_length=64, blank=True, default='', db_index=True)
    storage_provider = models.CharField(max_length=50, blank=True, default='')
    drive_file_id = models.CharField(max_length=255, blank=True, default='')
    drive_url = models.URLField(max_length=1000, blank=True, default='')
    upload_status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending',
    )
    upload_error = models.TextField(blank=True, default='')
    business_key_type = models.CharField(max_length=100, blank=True, default='')
    business_key_value = models.CharField(max_length=255, blank=True, default='', db_index=True)
    # New Jawabu Portal uploads bind directly to the case rather than relying
    # only on a mutable national-ID business key. Existing workflow uploads
    # remain supported with this relation empty.
    jawabu_farmer = models.ForeignKey(
        'JawabuFarmerMaster', null=True, blank=True,
        on_delete=models.PROTECT, related_name='media_attachments',
    )
    captured_at = models.DateTimeField(null=True, blank=True)
    capture_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    capture_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    capture_location_unavailable_reason = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['group_id', 'created_at']),
            models.Index(fields=['business_key_type', 'business_key_value']),
            models.Index(fields=['telegram_file_id']),
            models.Index(fields=['jawabu_farmer', 'file_type', 'upload_status']),
        ]

    def __str__(self):
        return f"MediaAttachment {self.file_type or 'file'} {self.upload_status}"


class SpinCreditRequest(models.Model):
    """Parsed SPIN / CRB request imported from WhatsApp exports or Mini App forms."""

    REQUEST_TYPE_CHOICES = [
        ('spin_crb', 'SPIN/CRB'),
        ('spin', 'SPIN'),
        ('crb', 'CRB Report'),
    ]
    IMPORT_STATUS_CHOICES = [
        ('imported', 'Imported'),
        ('review_needed', 'Review Needed'),
        ('duplicate', 'Duplicate'),
        ('rejected', 'Rejected'),
        ('failed', 'Failed'),
        ('completed', 'Completed'),
    ]


    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group_id = models.CharField(max_length=100, db_index=True)
    sheet_id = models.CharField(max_length=255, blank=True, default='', db_index=True)
    sheet_name = models.CharField(max_length=255, blank=True, default='')
    row_number = models.PositiveIntegerField(null=True, blank=True)
    public_sequence_year = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    public_sequence_number = models.PositiveIntegerField(null=True, blank=True, db_index=True)

    telegram_message_id = models.CharField(max_length=255, blank=True, default='', db_index=True)
    source_message_hash = models.CharField(max_length=64, blank=True, default='', db_index=True)
    source_chat = models.CharField(max_length=255, blank=True, default='')
    source_filename = models.CharField(max_length=255, blank=True, default='')
    source_message_index = models.PositiveIntegerField(null=True, blank=True)

    request_datetime = models.DateTimeField(null=True, blank=True, db_index=True)
    requested_by = models.CharField(max_length=255, blank=True, default='')
    request_type = models.CharField(max_length=40, choices=REQUEST_TYPE_CHOICES, db_index=True)
    customer_name = models.CharField(max_length=255, blank=True, default='', db_index=True)
    national_id = models.CharField(max_length=100, blank=True, default='', db_index=True)
    raw_id_text = models.CharField(max_length=255, blank=True, default='')
    primary_phone = models.CharField(max_length=50, blank=True, default='', db_index=True)
    secondary_phone = models.CharField(max_length=50, blank=True, default='')
    customer_type = models.CharField(max_length=50, blank=True, default='')
    loan_product = models.CharField(max_length=255, blank=True, default='')
    requested_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    tenor = models.CharField(max_length=100, blank=True, default='')
    business_notes = models.TextField(blank=True, default='')
    code = models.CharField(max_length=255, blank=True, default='')
    attachment_names = models.JSONField(blank=True, default=list)

    raw_message = models.TextField(blank=True, default='')
    parsed_fields = models.JSONField(blank=True, default=dict)
    missing_fields = models.JSONField(blank=True, default=list)
    import_status = models.CharField(max_length=30, choices=IMPORT_STATUS_CHOICES, default='review_needed', db_index=True)
    sync_error = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-request_datetime', '-created_at']
        indexes = [
            models.Index(fields=['group_id', 'request_datetime']),
            models.Index(fields=['group_id', 'public_sequence_year', 'public_sequence_number']),
            models.Index(fields=['group_id', 'national_id', 'primary_phone']),
            models.Index(fields=['group_id', 'import_status']),
            models.Index(fields=['source_message_hash']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['group_id', 'source_message_hash'],
                name='unique_spin_request_source_per_group',
            ),
            models.UniqueConstraint(
                fields=['group_id', 'public_sequence_year', 'public_sequence_number'],
                condition=models.Q(public_sequence_number__isnull=False),
                name='unique_spin_public_sequence_per_group_year',
            ),
        ]
        verbose_name = 'SPIN / CRB request'
        verbose_name_plural = 'SPIN / CRB requests'

    def __str__(self):
        return f"{self.get_request_type_display()} {self.customer_name or self.national_id or self.primary_phone}".strip()


class SpinBatchReviewItem(models.Model):
    """An uncertain WhatsApp batch message retained for staff classification."""

    CATEGORY_CHOICES = [
        ('incomplete', 'Incomplete SPIN request'),
        ('ambiguous', 'Possible SPIN request'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Pending review'),
        ('resolved', 'Resolved to SPIN request'),
        ('rejected', 'Marked not SPIN'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group_id = models.CharField(max_length=100, db_index=True)
    telegram_message_id = models.CharField(max_length=255, blank=True, default='', db_index=True)
    source_message_hash = models.CharField(max_length=64, db_index=True)
    source_filename = models.CharField(max_length=255, blank=True, default='')
    source_message_index = models.PositiveIntegerField(null=True, blank=True)
    source_sender = models.CharField(max_length=255, blank=True, default='')
    source_received_at = models.DateTimeField(null=True, blank=True)
    raw_message = models.TextField()

    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, db_index=True)
    reason = models.TextField(blank=True, default='')
    detected_fields = models.JSONField(blank=True, default=dict)
    candidate_fields = models.JSONField(blank=True, default=dict)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    resolved_request = models.ForeignKey(
        SpinCreditRequest,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='resolved_batch_review_items',
    )
    resolution_fields = models.JSONField(blank=True, default=dict)
    reviewed_by = models.CharField(max_length=255, blank=True, default='')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-source_received_at', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['group_id', 'source_message_hash'],
                name='unique_spin_batch_review_source_per_group',
            ),
        ]
        indexes = [
            models.Index(fields=['group_id', 'status', 'created_at']),
            models.Index(fields=['group_id', 'category', 'status']),
        ]

    def __str__(self):
        return f"{self.get_category_display()} {self.group_id} #{self.source_message_index or 0}"


class SpinRequestSequence(models.Model):
    """Durable per-group/year sequence for staff-facing SPIN references."""

    group_id = models.CharField(max_length=100, db_index=True)
    year = models.PositiveIntegerField(db_index=True)
    next_number = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['group_id', 'year'], name='unique_spin_sequence_group_year'),
        ]
        verbose_name = 'SPIN request sequence'
        verbose_name_plural = 'SPIN request sequences'

    def __str__(self):
        return f"{self.group_id} {self.year}: next {self.next_number}"

class TatTrackerCase(models.Model):
    """Django-owned TAT tracker case mirrored to the live Google workbook."""

    STATUS_CHOICES = [
        ('Active', 'Active'),
        ('Disbursed', 'Disbursed'),
        ('Rejected', 'Rejected'),
        ('Declined', 'Declined'),
        ('Deferred', 'Deferred'),
        ('Stalled', 'Stalled'),
        ('Pending Docs', 'Pending Docs'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group_id = models.CharField(max_length=100, db_index=True)
    sheet_id = models.CharField(max_length=255, blank=True, default='', db_index=True)
    sheet_name = models.CharField(max_length=255, blank=True, default='', db_index=True)
    row_number = models.PositiveIntegerField(null=True, blank=True)
    create_request_id = models.CharField(max_length=128, blank=True, default='', db_index=True)

    case_id = models.CharField(max_length=128, db_index=True)
    product_key = models.CharField(max_length=80, db_index=True)
    product_label = models.CharField(max_length=120, blank=True, default='')
    client_name = models.CharField(max_length=255, db_index=True)
    national_id = models.CharField(max_length=32, blank=True, default='', db_index=True)
    primary_phone = models.CharField(max_length=32, blank=True, default='', db_index=True)
    branch = models.CharField(max_length=120, blank=True, default='', db_index=True)
    bro_name = models.CharField(max_length=255, blank=True, default='')
    amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)

    stage_values = models.JSONField(blank=True, default=dict)
    # Keep the SLA target that was active when each stage began. A later
    # approved policy change must not retroactively alter an in-flight stage.
    stage_target_snapshots = models.JSONField(blank=True, default=dict)
    status = models.CharField(max_length=40, choices=STATUS_CHOICES, default='Active', db_index=True)
    remarks = models.TextField(blank=True, default='')
    current_stage = models.CharField(max_length=120, blank=True, default='', db_index=True)
    workflow_revision = models.PositiveIntegerField(default=1)

    created_by = models.CharField(max_length=255, blank=True, default='')
    created_by_telegram_id = models.CharField(max_length=100, blank=True, default='', db_index=True)
    last_updated_by = models.CharField(max_length=255, blank=True, default='')
    last_synced_at = models.DateTimeField(null=True, blank=True)
    sync_error = models.TextField(blank=True, default='')
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.CharField(max_length=255, blank=True, default='')
    deletion_reason = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['group_id', 'case_id'],
                name='unique_tat_case_id_per_group',
            ),
            models.UniqueConstraint(
                fields=['group_id', 'create_request_id'],
                condition=~models.Q(create_request_id=''),
                name='unique_tat_create_request_per_group',
            ),
        ]
        indexes = [
            models.Index(fields=['group_id', 'status']),
            models.Index(fields=['group_id', 'product_key', 'status']),
            models.Index(fields=['group_id', 'client_name']),
            models.Index(fields=['group_id', 'current_stage']),
            models.Index(fields=['group_id', 'is_deleted']),
        ]
        verbose_name = 'TAT tracker case'
        verbose_name_plural = 'TAT tracker cases'

    def __str__(self):
        return f"{self.case_id} - {self.client_name}"


class TatTrackerEvent(models.Model):
    """Append-only audit event for TAT tracker case creation and stage updates."""

    SOURCE_CHOICES = [
        ('mini_app', 'Mini App'),
        ('telegram', 'Telegram'),
        ('sheet_sync', 'Sheet Sync'),
        ('admin_correction', 'Admin Correction'),
        ('workflow_transition', 'Workflow Transition'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(
        TatTrackerCase,
        on_delete=models.CASCADE,
        related_name='events',
    )
    group_id = models.CharField(max_length=100, db_index=True)
    actor_name = models.CharField(max_length=255, blank=True, default='')
    actor_telegram_id = models.CharField(max_length=100, blank=True, default='', db_index=True)
    actor_role = models.CharField(max_length=80, blank=True, default='')
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='tat_tracker_actions',
    )
    authority_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='tat_tracker_authorized_actions',
    )
    stage_key = models.CharField(max_length=120, blank=True, default='', db_index=True)
    stage_label = models.CharField(max_length=160, blank=True, default='')
    old_value = models.TextField(blank=True, default='')
    new_value = models.TextField(blank=True, default='')
    source = models.CharField(max_length=40, choices=SOURCE_CHOICES, default='mini_app', db_index=True)
    request_id = models.CharField(max_length=128, blank=True, default='', db_index=True)
    transition_code = models.CharField(max_length=120, blank=True, default='', db_index=True)
    from_state = models.CharField(max_length=120, blank=True, default='', db_index=True)
    to_state = models.CharField(max_length=120, blank=True, default='', db_index=True)
    reason = models.TextField(blank=True, default='')
    revision_before = models.PositiveIntegerField(null=True, blank=True)
    revision_after = models.PositiveIntegerField(null=True, blank=True)
    sheet_name = models.CharField(max_length=255, blank=True, default='')
    row_number = models.PositiveIntegerField(null=True, blank=True)
    sync_error = models.TextField(blank=True, default='')
    synced_to_sheet = models.BooleanField(default=False, db_index=True)
    synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['case', 'request_id'],
                condition=~models.Q(request_id=''),
                name='unique_tat_event_request_per_case',
            ),
        ]
        indexes = [
            models.Index(fields=['group_id', 'created_at']),
            models.Index(fields=['group_id', 'stage_key']),
            models.Index(fields=['case', 'created_at']),
        ]
        verbose_name = 'TAT tracker event'
        verbose_name_plural = 'TAT tracker events'

    def __str__(self):
        return f"{self.case.case_id} {self.stage_label or self.stage_key}"


class TatRepairJob(models.Model):
    """Persistent progress for an asynchronous TAT Sheet repair."""

    STATUS_CHOICES = [
        ('queued', 'Queued'),
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('completed_with_errors', 'Completed with errors'),
        ('failed', 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group_configuration = models.ForeignKey(
        'GroupSheetConfiguration',
        on_delete=models.CASCADE,
        related_name='tat_repair_jobs',
    )
    product_key = models.CharField(max_length=80, blank=True, default='', db_index=True)
    case_ids = models.JSONField(blank=True, default=list)
    cursor = models.PositiveIntegerField(default=0)
    total_cases = models.PositiveIntegerField(default=0)
    synced_cases = models.PositiveIntegerField(default=0)
    skipped_unlinked = models.PositiveIntegerField(default=0)
    failures = models.JSONField(blank=True, default=list)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default='queued', db_index=True)
    worker_token = models.UUIDField(null=True, blank=True, editable=False)
    heartbeat_at = models.DateTimeField(null=True, blank=True, db_index=True)
    error = models.TextField(blank=True, default='')
    requested_by = models.CharField(max_length=255, blank=True, default='')
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['status', 'updated_at'])]

    def __str__(self):
        return f"TAT repair {self.id} ({self.status})"

class LiveSheetRecordChange(models.Model):
    """Audit trail for Django admin edits and deletes applied to live sheet rows."""

    ACTION_CHOICES = [
        ('update', 'Updated'),
        ('delete', 'Deleted'),
    ]
    STATUS_CHOICES = [
        ('success', 'Success'),
        ('failed', 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group_configuration = models.ForeignKey(
        'GroupSheetConfiguration',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='live_sheet_changes',
    )
    group_id = models.CharField(max_length=100, db_index=True)
    sheet_id = models.CharField(max_length=255, blank=True, default='', db_index=True)
    sheet_tab = models.CharField(max_length=255, blank=True, default='')
    row_number = models.PositiveIntegerField()
    record_key = models.CharField(max_length=255, blank=True, default='', db_index=True)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    changed_by = models.CharField(max_length=255, blank=True, default='')
    changes = models.JSONField(blank=True, default=dict)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    error = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['group_id', 'created_at']),
            models.Index(fields=['sheet_id', 'sheet_tab']),
            models.Index(fields=['record_key']),
        ]
        verbose_name = 'Live sheet record change'
        verbose_name_plural = 'Live sheet record changes'

    def __str__(self):
        return (
            f"{self.get_action_display()} {self.sheet_tab}!{self.row_number} "
            f"{self.record_key}".strip()
        )


class JawabuVisitRecord(models.Model):
    """Audit/import record for Jawabu HomeBiogas WhatsApp visit exports."""

    IMPORT_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('imported', 'Imported'),
        ('duplicate_review', 'Duplicate Needs Review'),
        ('rejected', 'Rejected'),
        ('failed', 'Failed'),
    ]
    DUPLICATE_STATUS_CHOICES = [
        ('unique', 'Unique'),
        ('possible_duplicate', 'Possible Duplicate'),
        ('confirmed_duplicate', 'Confirmed Duplicate'),
        ('not_duplicate', 'Not Duplicate'),
        ('merged', 'Merged'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group_id = models.CharField(max_length=100, db_index=True)
    sheet_id = models.CharField(max_length=255, blank=True, default='', db_index=True)
    sheet_tab = models.CharField(max_length=255, blank=True, default='')
    row_number = models.PositiveIntegerField(null=True, blank=True)
    telegram_message_id = models.CharField(max_length=255, blank=True, default='', db_index=True)
    source_telegram_message_id = models.CharField(max_length=255, blank=True, default='', db_index=True)
    whatsapp_message_index = models.PositiveIntegerField(null=True, blank=True)
    whatsapp_message_at = models.DateTimeField(null=True, blank=True)
    sender = models.CharField(max_length=255, blank=True, default='')
    national_id = models.CharField(max_length=64, blank=True, default='', db_index=True)
    primary_phone = models.CharField(max_length=32, blank=True, default='', db_index=True)
    duplicate_key = models.CharField(max_length=128, blank=True, default='', db_index=True)
    duplicate_group_id = models.CharField(max_length=128, blank=True, default='', db_index=True)
    duplicate_status = models.CharField(
        max_length=32,
        choices=DUPLICATE_STATUS_CHOICES,
        default='unique',
    )
    import_status = models.CharField(
        max_length=32,
        choices=IMPORT_STATUS_CHOICES,
        default='pending',
    )
    parsed_fields = models.JSONField(blank=True, default=dict)
    raw_text = models.TextField(blank=True, default='')
    sync_error = models.TextField(blank=True, default='')
    review_notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['group_id', 'created_at']),
            models.Index(fields=['group_id', 'duplicate_key']),
            models.Index(fields=['national_id', 'primary_phone']),
            models.Index(fields=['import_status', 'duplicate_status']),
        ]
        verbose_name = 'Jawabu visit record'
        verbose_name_plural = 'Jawabu visit records'

    def __str__(self):
        return (
            f"JawabuVisitRecord {self.national_id or 'no ID'} "
            f"{self.primary_phone or 'no phone'} {self.import_status}"
        )


class JawabuCustomer(models.Model):
    """Canonical Jawabu identity shared by one or more unit applications."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    national_id = models.CharField(max_length=64, blank=True, default='', db_index=True)
    primary_phone = models.CharField(max_length=32, blank=True, default='', db_index=True)
    customer_no = models.CharField(max_length=64, blank=True, default='', db_index=True)
    identity_enforced = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['national_id'], condition=models.Q(identity_enforced=True) & ~models.Q(national_id=''), name='jawabu_customer_unique_national_id'),
            models.UniqueConstraint(fields=['primary_phone'], condition=models.Q(identity_enforced=True) & ~models.Q(primary_phone=''), name='jawabu_customer_unique_primary_phone'),
            models.UniqueConstraint(fields=['customer_no'], condition=models.Q(identity_enforced=True) & ~models.Q(customer_no=''), name='jawabu_customer_unique_customer_no'),
        ]

    def __str__(self):
        return self.national_id or self.primary_phone or self.customer_no or str(self.id)


class JawabuCustomerPhoneHistory(models.Model):
    """Observed customer phone numbers without discarding a previous SIM."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(
        JawabuCustomer, on_delete=models.CASCADE, related_name='phone_history',
    )
    phone = models.CharField(max_length=32, db_index=True)
    source = models.CharField(max_length=40, blank=True, default='', db_index=True)
    is_current = models.BooleanField(default=False, db_index=True)
    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-last_seen_at']
        constraints = [
            models.UniqueConstraint(
                fields=['customer', 'phone'], name='jawabu_unique_customer_phone_history',
            ),
        ]
        indexes = [
            models.Index(fields=['phone', 'is_current']),
        ]
        verbose_name = 'Jawabu customer phone history'
        verbose_name_plural = 'Jawabu customer phone history'

    def __str__(self):
        return f'{self.customer}: {self.phone}'


class JawabuFarmerMaster(models.Model):
    """Clean internal master data for Jawabu farmers used by visit forms."""

    STATUS_CHOICES = [
        ('active', 'Active'),
        ('review_needed', 'Review Needed'),
        ('inactive', 'Inactive'),
    ]

    # Stage 2 Ã¢â‚¬â€ JBL visit status dropdown (aligns with FCAUP_STATUS_VALUES in fca.py)
    JBL_VISIT_STATUS_CHOICES = [
        ('Approved', 'Approved'),
        ('Awaiting Analysis', 'Awaiting Analysis'),
        ('JBL to Schedule Visit', 'JBL to Schedule Visit'),
        ('Rescheduled', 'Rescheduled'),
        ('Deferred / On Hold', 'Deferred / On Hold'),
        ('Rejected by JBL', 'Rejected by JBL'),
        ('Opted for Cash', 'Opted for Cash'),
        ('Opted for other Partner', 'Opted for other Partner'),
    ]

    # Stage 3 Ã¢â‚¬â€ Credit Decision values (master data dropdown)
    CREDIT_DECISION_CHOICES = [
        ('Approved', 'Approved'),
        ('Approved with Conditions', 'Approved with Conditions'),
        ('Rejected', 'Rejected'),
        ('Deferred', 'Deferred'),
        ('Exemption Approved', 'Exemption Approved'),
        ('Pending', 'Pending'),
    ]

    FINAL_DECISION_CHOICES = [
        ('Approved', 'Approved'),
        ('Approved with Conditions', 'Approved with Conditions'),
        ('Rejected', 'Rejected'),
        ('Deferred', 'Deferred'),
        ('Under Review', 'Under Review'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    customer = models.ForeignKey(JawabuCustomer, on_delete=models.PROTECT, null=True, blank=True, related_name='applications')
    unit_number = models.PositiveIntegerField(default=1)
    source = models.CharField(max_length=100, default='jawabu_farmers_csv', db_index=True)
    source_name = models.CharField(max_length=255, blank=True, default='')
    source_row_number = models.PositiveIntegerField(null=True, blank=True)
    source_fingerprint = models.CharField(max_length=64, blank=True, default='', db_index=True)
    external_id = models.CharField(max_length=128, blank=True, default='', db_index=True)

    customer_name = models.CharField(max_length=255, blank=True, default='', db_index=True)
    national_id = models.CharField(max_length=64, blank=True, default='', db_index=True)
    primary_phone = models.CharField(max_length=32, blank=True, default='', db_index=True)
    secondary_phone = models.CharField(max_length=32, blank=True, default='')

    county = models.CharField(max_length=128, blank=True, default='', db_index=True)
    sub_county = models.CharField(max_length=128, blank=True, default='')
    ward = models.CharField(max_length=128, blank=True, default='')
    village = models.CharField(max_length=255, blank=True, default='')
    landmark = models.TextField(blank=True, default='')
    branch = models.CharField(max_length=128, blank=True, default='', db_index=True)

    hbg_contract_name = models.CharField(max_length=128, blank=True, default='', db_index=True)
    lead_source = models.CharField(max_length=128, blank=True, default='', db_index=True)
    contract_type = models.CharField(max_length=128, blank=True, default='')
    installation_status = models.CharField(max_length=128, blank=True, default='', db_index=True)
    actual_receipts_currency = models.CharField(max_length=16, blank=True, default='')
    actual_receipts = models.CharField(max_length=64, blank=True, default='')
    deposit_paid_hbg = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    hb_sales_person = models.CharField(max_length=255, blank=True, default='', db_index=True)
    sign_date = models.CharField(max_length=32, blank=True, default='')
    hbg_visit_date = models.DateField(null=True, blank=True, db_index=True)
    created_date = models.CharField(max_length=32, blank=True, default='')
    comments = models.TextField(blank=True, default='')

    gps_link = models.URLField(max_length=1000, blank=True, default='')
    latitude = models.CharField(max_length=64, blank=True, default='')
    longitude = models.CharField(max_length=64, blank=True, default='')
    latitude_value = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude_value = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)

    # Ã¢â€â‚¬Ã¢â€â‚¬ Stage 2: JBL visit Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
    jbl_visit_date = models.DateField(
        null=True, blank=True, db_index=True,
        help_text='Date the JBL officer visited this farmer.',
    )
    jbl_officer = models.CharField(
        max_length=255, blank=True, default='',
        help_text='Name of the JBL BRO / field officer who conducted the visit.',
    )
    jbl_visit_status = models.CharField(
        max_length=80, blank=True, default='',
        choices=JBL_VISIT_STATUS_CHOICES, db_index=True,
        help_text='Jawabu Comment After Visit Ã¢â‚¬â€ 12-option dropdown set by JBL officer.',
    )
    jbl_visit_comment = models.TextField(
        blank=True, default='',
        help_text='Optional free-text comment from the JBL officer.',
    )

    # Ã¢â€â‚¬Ã¢â€â‚¬ Stage 3: Credit decision Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
    credit_decision = models.CharField(
        max_length=80, blank=True, default='Pending',
        choices=CREDIT_DECISION_CHOICES, db_index=True,
        help_text='Credit Analysis decision from master data dropdown.',
    )
    credit_decided_by = models.CharField(
        max_length=255, blank=True, default='',
        help_text='Telegram sender who set the credit decision.',
    )
    credit_decided_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Timestamp when the credit decision was recorded.',
    )

    imab_created = models.CharField(
        max_length=32, blank=True, default='',
        help_text='Whether the customer has been created on IMAB before Head of Rural review.',
    )
    customer_no = models.CharField(
        max_length=64, blank=True, default='', db_index=True,
        help_text='IMAB customer number required before Head of Rural review.',
    )
    imab_customer_name = models.CharField(
        max_length=255, blank=True, default='',
        help_text='Customer name from the IMAB/system export used for payment documents.',
    )
    system_branch = models.CharField(
        max_length=128, blank=True, default='', db_index=True,
        help_text='Branch from the IMAB/system export used for payment documents.',
    )
    system_loan_officer = models.CharField(
        max_length=255, blank=True, default='',
        help_text='Loan officer from the IMAB/system export; JBL officer is used as fallback.',
    )
    system_deposit_paid_jbl = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text='Deposit paid to JBL from the IMAB/system export.',
    )
    repayment_date = models.CharField(
        max_length=64, blank=True, default='',
        help_text='Repayment date/day captured before order/payment generation.',
    )
    repayment_day = models.PositiveSmallIntegerField(null=True, blank=True)
    repayment_tenor = models.CharField(
        max_length=64, blank=True, default='',
        help_text='Loan tenor captured before order/payment generation.',
    )
    repayment_tenor_months = models.PositiveSmallIntegerField(null=True, blank=True)
    payment_product = models.CharField(
        max_length=128, blank=True, default='',
        help_text='Payment document product value captured before order/payment generation.',
    )

    # Stage 4: Head of Rural final review. This is the order-readiness gate.
    final_decision = models.CharField(
        max_length=80, blank=True, default='',
        choices=FINAL_DECISION_CHOICES, db_index=True,
        help_text='Head of Rural final decision. Approved records are ready for order batching.',
    )
    final_decision_comment = models.TextField(
        blank=True, default='',
        help_text='Head of Rural decision comment shown before order batching.',
    )
    final_decided_by = models.CharField(
        max_length=255, blank=True, default='',
        help_text='Telegram sender who set the final decision.',
    )
    final_decided_at = models.DateTimeField(
        null=True, blank=True,
        help_text='Timestamp when the final decision was recorded.',
    )
    deferred_at = models.DateTimeField(null=True, blank=True, db_index=True)
    deferred_stage = models.CharField(max_length=32, blank=True, default='', db_index=True)
    deferred_until = models.DateField(null=True, blank=True, db_index=True)
    workflow_state = models.CharField(max_length=40, blank=True, default='', db_index=True)
    workflow_state_entered_at = models.DateTimeField(null=True, blank=True)
    workflow_revision = models.PositiveIntegerField(default=1)

    jbl_media_urls = models.TextField(
        blank=True, default='',
        help_text='Drive links for documents/images uploaded during the JBL visit stage.',
    )

    # Ã¢â€â‚¬Ã¢â€â‚¬ Stage 4: Requisition / order Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
    requisition_date = models.DateField(
        null=True, blank=True,
        help_text='Jawabu Requisition Date Ã¢â‚¬â€ only set after Credit Decision = Approved.',
    )
    order_number = models.CharField(
        max_length=128, blank=True, default='', db_index=True,
        help_text='Order No. assigned by admin after credit approval.',
    )

    # Ã¢â€â‚¬Ã¢â€â‚¬ Stage 7: Invoice generation Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬Ã¢â€â‚¬
    invoice_number = models.CharField(max_length=128, blank=True, default='')
    invoice_date = models.DateField(null=True, blank=True)
    invoice_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    discount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    payment = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    balance_due = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    duplicate_key = models.CharField(max_length=255, blank=True, default='', db_index=True)
    status = models.CharField(
        max_length=32,
        choices=STATUS_CHOICES,
        default='active',
        db_index=True,
    )
    cleaning_notes = models.TextField(blank=True, default='')
    raw_data = models.JSONField(blank=True, default=dict)
    last_imported_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['customer_name', 'national_id', 'primary_phone']
        indexes = [
            models.Index(fields=['duplicate_key']),
            models.Index(fields=['national_id', 'primary_phone']),
            models.Index(fields=['customer_name', 'county']),
            models.Index(fields=['hbg_contract_name']),
            models.Index(fields=['hb_sales_person']),
            models.Index(fields=['status', 'updated_at']),
            models.Index(fields=['source', 'source_fingerprint']),
            # Pipeline stage indexes
            models.Index(fields=['jbl_visit_date']),
            models.Index(fields=['credit_decision']),
            models.Index(fields=['customer_no']),
            models.Index(fields=['final_decision']),
            models.Index(fields=['order_number']),
            models.Index(fields=['customer', 'unit_number']),
            models.Index(fields=['deferred_until', 'status']),
        ]
        constraints = [
            models.UniqueConstraint(fields=['customer', 'unit_number'], condition=models.Q(customer__isnull=False), name='jawabu_unique_customer_unit'),
        ]
        verbose_name = 'Jawabu farmer master record'
        verbose_name_plural = 'Jawabu farmer master data'

    def __str__(self):
        label = self.customer_name or self.national_id or self.primary_phone or 'unknown farmer'
        return f"{label} ({self.status})"


class JawabuApprovalDelegation(models.Model):
    """Time-boxed authority to approve one Portal gate for another staff user."""

    GATE_CREDIT = 'credit'
    GATE_FINAL_REVIEW = 'final_review'
    GATE_PAYMENT_REVIEW = 'payment_review'
    GATE_CHOICES = [
        (GATE_CREDIT, 'Credit analysis'),
        (GATE_FINAL_REVIEW, 'Head of Rural final review'),
        (GATE_PAYMENT_REVIEW, 'Head of Rural payment review'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    delegate = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='jawabu_approval_delegations',
    )
    gate = models.CharField(max_length=32, choices=GATE_CHOICES, db_index=True)
    source_role = models.CharField(max_length=80, default='BUSINESS_ADMIN')
    branch = models.CharField(max_length=128, blank=True, default='', db_index=True)
    product = models.CharField(max_length=128, blank=True, default='', db_index=True)
    reason = models.TextField()
    authorized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='authorized_jawabu_approval_delegations',
    )
    starts_at = models.DateTimeField(default=timezone.now, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='revoked_jawabu_approval_delegations',
    )
    revocation_reason = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-starts_at']
        indexes = [models.Index(fields=['delegate', 'gate', 'expires_at'])]
        verbose_name = 'Jawabu approval delegation'
        verbose_name_plural = 'Jawabu approval delegations'

    @property
    def active(self):
        current = timezone.now()
        return self.revoked_at is None and self.starts_at <= current < self.expires_at

    def __str__(self):
        return f'{self.delegate} - {self.get_gate_display()} until {self.expires_at:%d-%b-%Y}'


class JawabuApprovalDelegationEvent(models.Model):
    """Append-only delegation lifecycle evidence."""

    ACTION_CREATED = 'created'
    ACTION_REVOKED = 'revoked'
    ACTION_CHOICES = [(ACTION_CREATED, 'Created'), (ACTION_REVOKED, 'Revoked')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    delegation = models.ForeignKey(JawabuApprovalDelegation, on_delete=models.CASCADE, related_name='events')
    action = models.CharField(max_length=24, choices=ACTION_CHOICES)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    note = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Jawabu approval delegation event'
        verbose_name_plural = 'Jawabu approval delegation events'


class JawabuApprovalRecord(models.Model):
    """Append-only effective/expired/inactivated approval evidence for one case."""

    GATE_CREDIT = JawabuApprovalDelegation.GATE_CREDIT
    GATE_FINAL_REVIEW = JawabuApprovalDelegation.GATE_FINAL_REVIEW
    GATE_PAYMENT_REVIEW = JawabuApprovalDelegation.GATE_PAYMENT_REVIEW
    GATE_CHOICES = JawabuApprovalDelegation.GATE_CHOICES
    DECISION_APPROVED = 'approved'
    DECISION_CONDITIONAL = 'approved_with_conditions'
    DECISION_REJECTED = 'rejected'
    DECISION_DEFERRED = 'deferred'
    DECISION_RETURNED = 'returned_for_rework'
    DECISION_CHOICES = [
        (DECISION_APPROVED, 'Approved'),
        (DECISION_CONDITIONAL, 'Approved with conditions'),
        (DECISION_REJECTED, 'Rejected'),
        (DECISION_DEFERRED, 'Deferred'),
        (DECISION_RETURNED, 'Returned for rework'),
    ]
    STATUS_ACTIVE = 'active'
    STATUS_CONDITIONS_PENDING = 'conditions_pending'
    STATUS_INVALIDATED = 'invalidated'
    STATUS_EXPIRED = 'expired'
    STATUS_SUPERSEDED = 'superseded'
    STATUS_LEGACY = 'legacy'
    STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_CONDITIONS_PENDING, 'Conditions pending'),
        (STATUS_INVALIDATED, 'Invalidated'),
        (STATUS_EXPIRED, 'Expired'),
        (STATUS_SUPERSEDED, 'Superseded'),
        (STATUS_LEGACY, 'Legacy approval'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    farmer = models.ForeignKey(JawabuFarmerMaster, on_delete=models.PROTECT, related_name='approval_records')
    payment_document = models.ForeignKey(
        'PaymentDocument', null=True, blank=True, on_delete=models.PROTECT,
        related_name='case_approval_records',
    )
    gate = models.CharField(max_length=32, choices=GATE_CHOICES, db_index=True)
    decision = models.CharField(max_length=40, choices=DECISION_CHOICES)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_ACTIVE, db_index=True)
    reason_code = models.CharField(max_length=64, blank=True, default='')
    comment = models.TextField(blank=True, default='')
    source_revision = models.PositiveIntegerField(default=1)
    authority_role = models.CharField(max_length=80, blank=True, default='')
    delegation = models.ForeignKey(
        JawabuApprovalDelegation, null=True, blank=True, on_delete=models.PROTECT,
        related_name='approval_records',
    )
    decided_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    decided_by_label = models.CharField(max_length=255, blank=True, default='')
    decided_at = models.DateTimeField(default=timezone.now, db_index=True)
    expires_at = models.DateTimeField(null=True, blank=True, db_index=True)
    invalidated_at = models.DateTimeField(null=True, blank=True)
    invalidated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    invalidation_reason = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-decided_at', '-created_at']
        indexes = [
            models.Index(fields=['farmer', 'gate', 'status']),
            models.Index(fields=['payment_document', 'gate', 'status']),
        ]
        verbose_name = 'Jawabu approval record'
        verbose_name_plural = 'Jawabu approval records'

    def __str__(self):
        return f'{self.farmer} {self.gate}: {self.get_decision_display()}'


class JawabuApprovalCondition(models.Model):
    """A condition that blocks a conditional approval until explicitly cleared."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    approval = models.ForeignKey(JawabuApprovalRecord, on_delete=models.CASCADE, related_name='conditions')
    description = models.CharField(max_length=500)
    satisfied_at = models.DateTimeField(null=True, blank=True)
    satisfied_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    satisfaction_note = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = 'Jawabu approval condition'
        verbose_name_plural = 'Jawabu approval conditions'

    @property
    def satisfied(self):
        return self.satisfied_at is not None


class JawabuMediaAccessEvent(models.Model):
    """Audit every Portal-mediated retrieval of sensitive JBL visit evidence."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    farmer = models.ForeignKey(JawabuFarmerMaster, on_delete=models.PROTECT, related_name='media_access_events')
    attachment = models.ForeignKey(MediaAttachment, on_delete=models.PROTECT, related_name='access_events')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    action = models.CharField(max_length=32, default='view')
    request_id = models.CharField(max_length=128, blank=True, default='', db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['farmer', 'created_at'])]
        verbose_name = 'Jawabu media access event'
        verbose_name_plural = 'Jawabu media access events'


class JawabuPipelineEvent(models.Model):
    """Append-only audit event for Jawabu application state changes."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    farmer = models.ForeignKey(JawabuFarmerMaster, on_delete=models.PROTECT, related_name='pipeline_events')
    action = models.CharField(max_length=40, db_index=True)
    stage_key = models.CharField(max_length=40, blank=True, default='', db_index=True)
    actor = models.CharField(max_length=255, blank=True, default='')
    actor_telegram_id = models.CharField(max_length=100, blank=True, default='', db_index=True)
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='jawabu_pipeline_actions',
    )
    authority_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='jawabu_pipeline_authorized_actions',
    )
    source = models.CharField(max_length=40, blank=True, default='system', db_index=True)
    request_id = models.CharField(max_length=128, blank=True, default='', db_index=True)
    transition_code = models.CharField(max_length=120, blank=True, default='', db_index=True)
    from_state = models.CharField(max_length=120, blank=True, default='', db_index=True)
    to_state = models.CharField(max_length=120, blank=True, default='', db_index=True)
    reason = models.TextField(blank=True, default='')
    revision_before = models.PositiveIntegerField(null=True, blank=True)
    revision_after = models.PositiveIntegerField(null=True, blank=True)
    old_values = models.JSONField(blank=True, default=dict)
    new_values = models.JSONField(blank=True, default=dict)
    metadata = models.JSONField(blank=True, default=dict)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['farmer', 'occurred_at'], name='jawabu_farmer_timeline_idx'),
            models.Index(fields=['farmer', 'stage_key'], name='jawabu_farmer_stage_idx'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['farmer', 'request_id'],
                condition=~models.Q(request_id=''),
                name='jawabu_unique_event_request',
            ),
        ]


class BusinessCalendarHoliday(models.Model):
    """Admin-managed public holiday excluded from the official JBL SLA clock."""

    date = models.DateField(unique=True, db_index=True)
    name = models.CharField(max_length=160)
    active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['date']
        verbose_name = 'business calendar holiday'
        verbose_name_plural = 'business calendar holidays'

    def __str__(self):
        return f'{self.date:%d-%b-%Y}: {self.name}'


class WorkflowTimelineAnnotation(models.Model):
    """Append-only correction/redaction evidence for a projected timeline entry.

    Original workflow events remain immutable.  This record carries the
    relationship to the original entry and, when authorised, masks sensitive
    display content without destroying the event shell required for audit.
    """

    WORKFLOW_CHOICES = [
        ('jawabu_pipeline', 'Jawabu Pipeline'),
        ('tat_tracker', 'TAT Tracker'),
    ]
    KIND_CHOICES = [
        ('correction', 'Correction'),
        ('redaction', 'Redaction'),
        ('artifact_link', 'Artifact link'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow = models.CharField(max_length=40, choices=WORKFLOW_CHOICES, db_index=True)
    subject_id = models.CharField(max_length=64, db_index=True)
    source_event_id = models.CharField(max_length=64, db_index=True)
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, db_index=True)
    supersedes_event_id = models.CharField(max_length=64, blank=True, default='', db_index=True)
    note = models.TextField(blank=True, default='')
    artifact_name = models.CharField(max_length=255, blank=True, default='')
    artifact_url = models.URLField(max_length=1000, blank=True, default='')
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='workflow_timeline_annotations',
    )
    authority_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='workflow_timeline_annotation_authorizations',
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['workflow', 'subject_id', 'created_at']),
            models.Index(fields=['workflow', 'source_event_id', 'kind']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['workflow', 'subject_id', 'source_event_id', 'kind'],
                condition=models.Q(kind='redaction'),
                name='unique_workflow_timeline_redaction',
            ),
        ]
        verbose_name = 'workflow timeline annotation'
        verbose_name_plural = 'workflow timeline annotations'

    def __str__(self):
        return f'{self.workflow} {self.kind} {self.source_event_id}'


class WorkflowSlaEscalation(models.Model):
    """Idempotent overdue-stage record for supervised operational follow-up."""

    WORKFLOW_CHOICES = [
        ('jawabu_pipeline', 'Jawabu Pipeline'),
        ('tat_tracker', 'TAT Tracker'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Pending follow-up'),
        ('acknowledged', 'Acknowledged'),
        ('resolved', 'Resolved'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow = models.CharField(max_length=40, choices=WORKFLOW_CHOICES, db_index=True)
    subject_id = models.CharField(max_length=64, db_index=True)
    group_id = models.CharField(max_length=100, blank=True, default='', db_index=True)
    stage_key = models.CharField(max_length=120, db_index=True)
    branch = models.CharField(max_length=128, blank=True, default='', db_index=True)
    responsible_role = models.CharField(max_length=80, blank=True, default='', db_index=True)
    responsible_actor = models.CharField(max_length=160, blank=True, default='', db_index=True)
    target_minutes = models.PositiveIntegerField()
    overdue_minutes = models.PositiveIntegerField()
    escalation_level = models.PositiveSmallIntegerField(default=1, db_index=True)
    threshold_percent = models.PositiveSmallIntegerField(default=100)
    escalation_date = models.DateField(db_index=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='acknowledged_workflow_sla_escalations',
    )
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='resolved_workflow_sla_escalations',
    )
    follow_up_note = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['workflow', 'subject_id', 'stage_key', 'escalation_date'],
                name='unique_workflow_sla_escalation_day',
            ),
        ]
        indexes = [
            models.Index(fields=['workflow', 'status', 'created_at']),
            models.Index(fields=['group_id', 'stage_key', 'status']),
        ]
        verbose_name = 'workflow SLA escalation'
        verbose_name_plural = 'workflow SLA escalations'


class TatEscalationRule(models.Model):
    """Approved, branch-aware escalation routing for the TAT tracker."""

    ROUTE_RESPONSIBLE = 'RESPONSIBLE_ROLE'
    ROUTE_BRANCH_MANAGER = 'BRANCH_MANAGER'
    ROUTE_MANAGEMENT = 'MANAGEMENT'
    ROUTING_CHOICES = [
        (ROUTE_RESPONSIBLE, 'Responsible role'),
        (ROUTE_BRANCH_MANAGER, 'Branch manager'),
        (ROUTE_MANAGEMENT, 'Management'),
    ]

    group_configuration = models.ForeignKey(
        'GroupSheetConfiguration', on_delete=models.CASCADE, related_name='tat_escalation_rules',
    )
    threshold_percent = models.PositiveSmallIntegerField()
    routing_role = models.CharField(max_length=80, choices=ROUTING_CHOICES)
    branch = models.CharField(max_length=120, blank=True, default='', db_index=True)
    active = models.BooleanField(default=True, db_index=True)
    approved_at = models.DateTimeField(default=timezone.now, db_index=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='approved_tat_escalation_rules',
    )
    retired_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['branch', 'threshold_percent', '-approved_at']
        constraints = [
            models.UniqueConstraint(
                fields=['group_configuration', 'branch', 'threshold_percent'],
                condition=models.Q(active=True),
                name='unique_active_tat_escalation_rule',
            ),
        ]


class WorkflowTatDailyMetric(models.Model):
    """Idempotent daily operational TAT trend snapshot.

    This is a reporting projection only.  It never replaces workflow events or
    changes a case's current state.
    """

    WORKFLOW_CHOICES = WorkflowSlaEscalation.WORKFLOW_CHOICES

    metric_date = models.DateField(db_index=True)
    workflow = models.CharField(max_length=40, choices=WORKFLOW_CHOICES, db_index=True)
    group_id = models.CharField(max_length=100, blank=True, default='', db_index=True)
    branch = models.CharField(max_length=128, blank=True, default='', db_index=True)
    product_key = models.CharField(max_length=80, blank=True, default='', db_index=True)
    stage_key = models.CharField(max_length=120, db_index=True)
    responsible_role = models.CharField(max_length=80, blank=True, default='', db_index=True)
    responsible_actor = models.CharField(max_length=160, blank=True, default='', db_index=True)
    active_count = models.PositiveIntegerField(default=0)
    completed_count = models.PositiveIntegerField(default=0)
    overdue_count = models.PositiveIntegerField(default=0)
    sample_count = models.PositiveIntegerField(default=0)
    median_sla_minutes = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    p90_sla_minutes = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    median_wall_clock_minutes = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-metric_date', 'workflow', 'stage_key']
        constraints = [
            models.UniqueConstraint(
                fields=['metric_date', 'workflow', 'group_id', 'branch', 'product_key', 'stage_key', 'responsible_role', 'responsible_actor'],
                name='unique_workflow_tat_daily_metric',
            ),
        ]
        indexes = [
            models.Index(fields=['workflow', 'metric_date', 'branch']),
            models.Index(fields=['group_id', 'metric_date', 'stage_key']),
        ]
        verbose_name = 'workflow TAT daily metric'
        verbose_name_plural = 'workflow TAT daily metrics'


class JawabuDataQualityIssue(models.Model):
    """Active/resolved canonical-data warning for a Jawabu application."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    farmer = models.ForeignKey(JawabuFarmerMaster, on_delete=models.CASCADE, related_name='data_quality_issues')
    field_name = models.CharField(max_length=80, db_index=True)
    code = models.CharField(max_length=80, db_index=True)
    severity = models.CharField(max_length=20, default='warning', db_index=True)
    message = models.TextField()
    active = models.BooleanField(default=True, db_index=True)
    detected_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['field_name', 'code']
        constraints = [
            models.UniqueConstraint(fields=['farmer', 'field_name', 'code'], name='jawabu_unique_quality_issue'),
        ]


class JawabuDataQualityResolution(models.Model):
    """Append-only staff decision for a Jawabu data-quality exception."""

    ACTION_CHOICES = [
        ('corrected', 'Corrected canonical value'),
        ('accepted', 'Accepted source value'),
        ('linked', 'Linked to existing customer'),
        ('ignored', 'Accepted documented exception'),
        ('rejected', 'Rejected source row'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    issue = models.ForeignKey(
        JawabuDataQualityIssue, on_delete=models.CASCADE, related_name='resolutions',
    )
    action = models.CharField(max_length=20, choices=ACTION_CHOICES, db_index=True)
    note = models.TextField(blank=True, default='')
    actor = models.CharField(max_length=255, blank=True, default='')
    before_value = models.TextField(blank=True, default='')
    after_value = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Jawabu data-quality resolution'
        verbose_name_plural = 'Jawabu data-quality resolutions'


class JawabuCustomerFieldProvenance(models.Model):
    """Append-only source history for customer fields that cross system boundaries."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    farmer = models.ForeignKey(
        JawabuFarmerMaster, on_delete=models.CASCADE, related_name='field_provenance',
    )
    field_name = models.CharField(max_length=80, db_index=True)
    old_value = models.TextField(blank=True, default='')
    new_value = models.TextField(blank=True, default='')
    source = models.CharField(max_length=40, db_index=True)
    source_reference = models.CharField(max_length=255, blank=True, default='')
    source_row_number = models.PositiveIntegerField(null=True, blank=True)
    actor = models.CharField(max_length=255, blank=True, default='')
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['-occurred_at']
        indexes = [
            models.Index(fields=['farmer', 'field_name', 'occurred_at']),
            models.Index(fields=['source', 'occurred_at']),
        ]
        verbose_name = 'Jawabu customer field provenance'
        verbose_name_plural = 'Jawabu customer field provenance'


class OperationalProduct(models.Model):
    """Single controlled catalog for products used by imports, scopes, and TAT."""

    name = models.CharField(max_length=128)
    code = models.CharField(max_length=64, blank=True, default='')
    active = models.BooleanField(default=True, db_index=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['sort_order', 'name']
        constraints = [
            models.UniqueConstraint(Lower('name'), name='jawabu_unique_operational_product_name_ci'),
            models.UniqueConstraint(
                Lower('code'), condition=~models.Q(code=''),
                name='jawabu_unique_operational_product_code_ci',
            ),
        ]
        verbose_name = 'Operational product'
        verbose_name_plural = 'Operational products'

    def clean(self):
        super().clean()
        self.name = ' '.join(str(self.name or '').split())
        # Access scopes use the stable, lowercase TAT product keys.  Keep an
        # Admin-entered code compatible with that convention rather than
        # creating display-case variants that silently match no scope.
        self.code = re.sub(r'[^a-z0-9]+', '_', str(self.code or '').casefold()).strip('_')
        if not self.name:
            raise ValidationError({'name': 'Enter a product name.'})

    def __str__(self):
        return self.name


class UserProfile(models.Model):
    """Telegram identity attached to Django's canonical staff account."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='staff_profile',
    )
    telegram_id = models.CharField(max_length=100, blank=True, default='', db_index=True)
    telegram_username = models.CharField(max_length=100, blank=True, default='', db_index=True)
    phone_number = models.CharField(max_length=20, blank=True, default='', db_index=True)
    signing_national_id = models.CharField(max_length=40, blank=True, default='')
    signing_phone_number = models.CharField(max_length=20, blank=True, default='')
    signing_email = models.EmailField(blank=True, default='')
    telegram_metadata = models.JSONField(blank=True, default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['user__first_name', 'user__last_name', 'telegram_id']
        constraints = [
            models.UniqueConstraint(
                fields=['telegram_id'], condition=models.Q(telegram_id__gt=''),
                name='unique_bound_telegram_id',
            ),
            models.UniqueConstraint(
                models.functions.Lower('telegram_username'),
                condition=models.Q(telegram_username__gt=''),
                name='unique_enrolled_telegram_username',
            ),
        ]

    def __str__(self):
        return self.user.get_full_name() or self.user.get_username()


class UserMiniAppPreference(models.Model):
    """Validated, user-owned preferences kept separate from Telegram identity."""

    WORKFLOW_CHOICES = [
        ('jawabu_portal', 'Jawabu Portal'),
        ('complaint_cases', 'Complaint Cases'),
        ('tat_tracker', 'TAT Tracker'),
        ('spin_credit_analysis', 'SPIN / Credit Analysis'),
    ]
    ALERT_IMMEDIATE = 'immediate'
    ALERT_DAILY_DIGEST = 'daily_digest'
    ALERT_QUIET = 'quiet'
    ALERT_CHOICES = [
        (ALERT_IMMEDIATE, 'Immediate'),
        (ALERT_DAILY_DIGEST, 'Daily digest'),
        (ALERT_QUIET, 'Quiet'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='miniapp_preferences')
    workflow = models.CharField(max_length=40, choices=WORKFLOW_CHOICES, db_index=True)
    default_screen = models.CharField(max_length=80, blank=True, default='')
    default_filters = models.JSONField(blank=True, default=dict)
    compact_cards = models.BooleanField(default=False)
    alert_mode = models.CharField(max_length=16, choices=ALERT_CHOICES, default=ALERT_IMMEDIATE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'workflow'], name='unique_user_miniapp_preference')]
        ordering = ['workflow', 'user_id']


class AccessGrant(models.Model):
    """Workflow-specific scope supplementing Django Groups/Permissions."""

    WORKFLOW_CHOICES = [
        ('jawabu_portal', 'Jawabu Portal'),
        ('complaint_cases', 'Complaint Cases'),
        ('tat_tracker', 'TAT Tracker'),
        ('spin_credit_analysis', 'SPIN / Credit Analysis'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='access_grants',
    )
    workflow = models.CharField(max_length=40, choices=WORKFLOW_CHOICES, db_index=True)
    role = models.CharField(max_length=80, db_index=True)
    branch = models.CharField(max_length=120, blank=True, default='', db_index=True)
    product = models.CharField(max_length=120, blank=True, default='', db_index=True)
    group_configuration = models.ForeignKey(
        'GroupSheetConfiguration', on_delete=models.CASCADE, null=True, blank=True,
        related_name='user_access_grants',
    )
    active = models.BooleanField(default=True, db_index=True)
    source = models.CharField(max_length=40, default='admin')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['workflow', 'role', 'branch', 'product']
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'workflow', 'role', 'branch', 'product', 'group_configuration'],
                condition=models.Q(group_configuration__isnull=False),
                name='unique_user_group_access_scope',
            ),
            models.UniqueConstraint(
                fields=['user', 'workflow', 'role', 'branch', 'product'],
                condition=models.Q(group_configuration__isnull=True),
                name='unique_user_global_access_scope',
            ),
        ]

    def __str__(self):
        return f'{self.user} - {self.workflow}: {self.role}'

    def save(self, *args, **kwargs):
        """Canonicalize the workflow role before saving the grant.

        A user may hold more than one active role tag and may have separate
        branch/product/group scopes. AccessGrant is the source of truth for
        those combinations; saving one grant must never silently deactivate a
        different grant created for the same user.
        """
        from core.services.access_policies import canonical_access_role

        if self.workflow:
            self.role = canonical_access_role(self.workflow, self.role)
        with transaction.atomic():
            super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        from core.services.access_policies import validate_access_scope
        self.role = validate_access_scope(
            workflow=self.workflow,
            role=self.role,
            branch=self.branch,
            product=self.product,
            group_configuration=self.group_configuration,
        )


class WorkflowRoleCapability(models.Model):
    """An administrator-managed capability assignment for a controlled role.

    Roles and capability keys are deliberately code-owned.  This table only
    decides which of those reviewed capabilities a role receives; it cannot
    create a new unguarded permission by typo or by an Admin edit.
    """

    workflow = models.CharField(max_length=40, choices=AccessGrant.WORKFLOW_CHOICES, db_index=True)
    role = models.CharField(max_length=80, db_index=True)
    capability_key = models.CharField(max_length=120, db_index=True)
    EFFECT_ALLOW = 'allow'
    EFFECT_DENY = 'deny'
    EFFECT_CHOICES = [(EFFECT_ALLOW, 'Allow'), (EFFECT_DENY, 'Explicit deny')]

    # ``enabled`` remains during the approval-control rollout so existing
    # reports and migrations remain readable.  New policy code uses effect;
    # an explicit deny is intentionally preserved rather than treated as a
    # missing row that a later default could accidentally restore.
    enabled = models.BooleanField(default=True)
    effect = models.CharField(max_length=12, choices=EFFECT_CHOICES, default=EFFECT_ALLOW)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['workflow', 'role', 'capability_key']
        constraints = [
            models.UniqueConstraint(
                fields=['workflow', 'role', 'capability_key'],
                name='unique_workflow_role_capability',
            ),
        ]
        verbose_name = 'workflow role capability'
        verbose_name_plural = 'workflow role capabilities'

    def __str__(self):
        state = 'enabled' if self.enabled else 'disabled'
        return f'{self.workflow}: {self.role} - {self.capability_key} ({state})'

    def clean(self):
        super().clean()
        from core.services.access_policies import validate_access_scope
        from core.services.workflow_capabilities import capability_definition

        self.role = validate_access_scope(workflow=self.workflow, role=self.role)
        if capability_definition(self.workflow, self.capability_key) is None:
            raise ValidationError({
                'capability_key': 'Choose a capability that belongs to the selected workflow.',
            })

    def save(self, *args, **kwargs):
        from core.services.access_policies import canonical_access_role

        if self.workflow:
            self.role = canonical_access_role(self.workflow, self.role)
        update_fields = kwargs.get('update_fields')
        # Preserve the pre-approval-control programmatic contract for callers
        # that still set ``enabled`` directly during the rollout.
        if update_fields and 'enabled' in update_fields:
            self.effect = self.EFFECT_ALLOW if self.enabled else self.EFFECT_DENY
            kwargs['update_fields'] = set(update_fields) | {'effect'}
        self.enabled = self.effect == self.EFFECT_ALLOW
        if update_fields and 'effect' in kwargs.get('update_fields', update_fields):
            kwargs['update_fields'] = set(kwargs['update_fields']) | {'enabled'}
        super().save(*args, **kwargs)


class WorkflowRoleCapabilityAuditEvent(models.Model):
    """Append-only record of a policy-matrix change made in Django Admin."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow = models.CharField(max_length=40, choices=AccessGrant.WORKFLOW_CHOICES, db_index=True)
    role = models.CharField(max_length=80, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+',
    )
    changes = models.JSONField(default=dict, blank=True)
    source = models.CharField(max_length=40, default='admin_matrix')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['workflow', 'role', 'created_at'])]
        verbose_name = 'workflow capability audit event'
        verbose_name_plural = 'workflow capability audit events'

    def __str__(self):
        return f'{self.workflow}: {self.role} policy changed {self.created_at:%d-%b-%Y %H:%M}'


class AccessControlPolicyState(models.Model):
    """Single locked counter used to prevent approval of a stale policy diff."""

    singleton = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    version = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def current(cls):
        return cls.objects.get_or_create(singleton=1)[0]


class AccessControlChangeRequest(models.Model):
    """Maker-checker request for permanent Mini App access changes."""

    TYPE_CAPABILITY = 'capability_policy'
    TYPE_GRANT = 'access_grant'
    TYPE_DOCUMENT_SIGNOFF = 'document_signoff_policy'
    TYPE_CHOICES = [
        (TYPE_CAPABILITY, 'Role capability policy'),
        (TYPE_GRANT, 'Staff access grant'),
        (TYPE_DOCUMENT_SIGNOFF, 'Document sign-off policy'),
    ]
    STATUS_DRAFT = 'draft'
    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_APPLIED = 'applied'
    STATUS_CANCELLED = 'cancelled'
    STATUS_STALE = 'stale'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'), (STATUS_PENDING, 'Pending approval'),
        (STATUS_APPROVED, 'Approved'), (STATUS_REJECTED, 'Rejected'),
        (STATUS_APPLIED, 'Applied'), (STATUS_CANCELLED, 'Cancelled'), (STATUS_STALE, 'Stale'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    change_type = models.CharField(max_length=32, choices=TYPE_CHOICES, db_index=True)
    workflow = models.CharField(max_length=40, choices=AccessGrant.WORKFLOW_CHOICES, blank=True, default='', db_index=True)
    role = models.CharField(max_length=80, blank=True, default='', db_index=True)
    target_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='access_control_requests')
    before_snapshot = models.JSONField(default=dict, blank=True)
    proposed_snapshot = models.JSONField(default=dict, blank=True)
    impact = models.JSONField(default=dict, blank=True)
    reason = models.TextField()
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True)
    policy_version = models.PositiveIntegerField(default=1)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='requested_access_control_changes')
    requested_at = models.DateTimeField(auto_now_add=True, db_index=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='reviewed_access_control_changes')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_comment = models.TextField(blank=True, default='')
    applied_at = models.DateTimeField(null=True, blank=True)
    source_request = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL, related_name='derived_requests')

    class Meta:
        ordering = ['-requested_at']
        indexes = [models.Index(fields=['status', 'requested_at']), models.Index(fields=['workflow', 'role', 'status'])]

    def __str__(self):
        return f'{self.get_change_type_display()} {self.workflow}/{self.role} ({self.status})'


class WorkflowConfigurationChangeRequest(models.Model):
    """Maker-checker proposal for high-impact workflow configuration."""

    WORKFLOW_TAT = 'tat_tracker'
    WORKFLOW_CHOICES = [(WORKFLOW_TAT, 'TAT Tracker')]
    SETTING_TARGETS = 'tat_targets'
    SETTING_HOLIDAYS = 'business_calendar'
    SETTING_ESCALATION = 'tat_escalation'
    SETTING_CHOICES = [
        (SETTING_TARGETS, 'TAT targets'),
        (SETTING_HOLIDAYS, 'Business calendar'),
        (SETTING_ESCALATION, 'TAT escalation rules'),
    ]
    STATUS_PENDING = 'pending'
    STATUS_APPROVED = 'approved'
    STATUS_REJECTED = 'rejected'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending approval'),
        (STATUS_APPROVED, 'Approved'),
        (STATUS_REJECTED, 'Rejected'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow = models.CharField(max_length=40, choices=WORKFLOW_CHOICES, default=WORKFLOW_TAT, db_index=True)
    setting_key = models.CharField(max_length=40, choices=SETTING_CHOICES, db_index=True)
    group_configuration = models.ForeignKey(
        'GroupSheetConfiguration', null=True, blank=True, on_delete=models.PROTECT,
        related_name='workflow_configuration_requests',
    )
    before_snapshot = models.JSONField(blank=True, default=dict)
    proposed_snapshot = models.JSONField(blank=True, default=dict)
    reason = models.TextField()
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    requested_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='requested_workflow_configuration_changes')
    requested_at = models.DateTimeField(auto_now_add=True, db_index=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='reviewed_workflow_configuration_changes')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_comment = models.TextField(blank=True, default='')
    request_id = models.CharField(max_length=128, blank=True, default='', db_index=True)
    applied_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-requested_at']
        indexes = [models.Index(fields=['workflow', 'setting_key', 'status', 'requested_at'])]
        constraints = [
            models.UniqueConstraint(
                fields=['requested_by', 'request_id'],
                condition=~models.Q(request_id=''),
                name='unique_workflow_config_request_id',
            ),
        ]


class AccessControlPolicySnapshot(models.Model):
    """Immutable recoverable state created whenever an approved request applies."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    version = models.PositiveIntegerField(unique=True)
    request = models.OneToOneField(AccessControlChangeRequest, null=True, blank=True, on_delete=models.PROTECT, related_name='applied_snapshot')
    state = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-version']


class EmergencyAccessGrant(models.Model):
    """Short-lived, separately audited access for an operational emergency."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='emergency_access_grants')
    workflow = models.CharField(max_length=40, choices=AccessGrant.WORKFLOW_CHOICES, db_index=True)
    role = models.CharField(max_length=80)
    branch = models.CharField(max_length=120, blank=True, default='')
    product = models.CharField(max_length=120, blank=True, default='')
    group_configuration = models.ForeignKey('GroupSheetConfiguration', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    reason = models.TextField()
    activated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='activated_emergency_access')
    activated_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='revoked_emergency_access')

    class Meta:
        ordering = ['-activated_at']
        indexes = [models.Index(fields=['user', 'workflow', 'expires_at'])]

    @property
    def active(self):
        return self.revoked_at is None and self.expires_at > timezone.now()


class AccessControlNotification(models.Model):
    """Delivery ledger; notification failure never undoes an applied control."""

    CHANNEL_ADMIN = 'admin'
    CHANNEL_TELEGRAM = 'telegram'
    CHANNEL_CHOICES = [(CHANNEL_ADMIN, 'Admin'), (CHANNEL_TELEGRAM, 'Telegram')]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    request = models.ForeignKey(AccessControlChangeRequest, null=True, blank=True, on_delete=models.CASCADE, related_name='notifications')
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    channel = models.CharField(max_length=16, choices=CHANNEL_CHOICES)
    event = models.CharField(max_length=64)
    status = models.CharField(max_length=16, default='queued')
    error = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)


class CapabilityUsageDaily(models.Model):
    """Small daily aggregate used for least-privilege drift reports."""

    day = models.DateField(db_index=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='+')
    workflow = models.CharField(max_length=40, db_index=True)
    capability_key = models.CharField(max_length=120, db_index=True)
    use_count = models.PositiveIntegerField(default=0)
    last_used_at = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['day', 'user', 'workflow', 'capability_key'], name='unique_daily_capability_usage')]
        indexes = [models.Index(fields=['workflow', 'capability_key', 'day'])]


class MiniAppDraft(models.Model):
    """Short-lived, server-owned recovery state for interrupted Mini App work.

    Drafts intentionally hold fields only.  Attachments remain on the device until
    the staff member explicitly submits the workflow action, so an interrupted
    upload never becomes an untracked copy of a customer document.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='miniapp_drafts',
    )
    workflow = models.CharField(max_length=40, db_index=True)
    context_key = models.CharField(max_length=180, db_index=True)
    payload = models.JSONField(default=dict)
    revision = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'workflow', 'context_key'],
                name='unique_miniapp_draft_context_per_user',
            ),
        ]
        indexes = [
            models.Index(fields=['workflow', 'context_key', 'expires_at']),
            models.Index(fields=['user', 'expires_at']),
        ]

    @property
    def expired(self) -> bool:
        return self.expires_at <= timezone.now()


class JawabuFarmerUploadBatch(models.Model):
    """Staged FarmUp/system-export upload awaiting staff review and commit."""

    IMPORT_KIND_CHOICES = [
        ('farmers', 'Farmers CSV'),
        ('system_export', 'Customers Without Loans export'),
    ]

    STATUS_CHOICES = [
        ('pending_review', 'Pending Review'),
        ('committed', 'Committed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group_id = models.CharField(max_length=100, db_index=True)
    telegram_message_id = models.CharField(max_length=255, blank=True, default='', db_index=True)
    sender = models.CharField(max_length=255, blank=True, default='')
    source_filename = models.CharField(max_length=255, blank=True, default='')
    import_kind = models.CharField(
        max_length=32,
        choices=IMPORT_KIND_CHOICES,
        default='farmers',
        db_index=True,
    )
    status = models.CharField(
        max_length=32,
        choices=STATUS_CHOICES,
        default='pending_review',
        db_index=True,
    )
    total_rows = models.PositiveIntegerField(default=0)
    review_needed = models.PositiveIntegerField(default=0)
    committed_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    parsed_rows = models.JSONField(blank=True, default=list)
    mapping = models.JSONField(blank=True, default=list)
    error = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    committed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['group_id', 'created_at']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['telegram_message_id']),
        ]
        verbose_name = 'Jawabu farmer upload batch'
        verbose_name_plural = 'Jawabu farmer upload batches'

    def __str__(self):
        return f"Farm upload {self.source_filename or self.id} {self.status}"

class FcaImportRecord(models.Model):
    """Audit row for FCA Excel workbook imports."""

    IMPORT_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('imported', 'Imported'),
        ('review_needed', 'Review Needed'),
        ('failed', 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group_id = models.CharField(max_length=100, db_index=True)
    sheet_id = models.CharField(max_length=255, blank=True, default='', db_index=True)
    sheet_tab = models.CharField(max_length=255, blank=True, default='')
    row_number = models.PositiveIntegerField(null=True, blank=True)
    telegram_message_id = models.CharField(max_length=255, blank=True, default='', db_index=True)
    source_filename = models.CharField(max_length=255, blank=True, default='', db_index=True)
    source_sheet = models.CharField(max_length=255, blank=True, default='')
    source_row = models.PositiveIntegerField(null=True, blank=True)
    sender = models.CharField(max_length=255, blank=True, default='')
    customer_name = models.CharField(max_length=255, blank=True, default='', db_index=True)
    primary_phone = models.CharField(max_length=32, blank=True, default='', db_index=True)
    fca_visit_date = models.DateField(null=True, blank=True)
    fca_comment = models.TextField(blank=True, default='')
    fca_decision = models.CharField(max_length=80, blank=True, default='', db_index=True)
    import_status = models.CharField(
        max_length=32,
        choices=IMPORT_STATUS_CHOICES,
        default='pending',
    )
    parsed_fields = models.JSONField(blank=True, default=dict)
    sync_error = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['group_id', 'created_at']),
            models.Index(fields=['group_id', 'source_filename', 'source_sheet', 'source_row']),
            models.Index(fields=['primary_phone', 'customer_name']),
            models.Index(fields=['import_status', 'fca_decision']),
        ]
        verbose_name = 'FCA import record'
        verbose_name_plural = 'FCA import records'

    def __str__(self):
        label = self.customer_name or self.primary_phone or 'unknown customer'
        return f"FCA {label} {self.import_status}"


class OperationalLocation(models.Model):
    """Canonical branch and county values shared by all workflows."""

    LOCATION_TYPES = (
        ('branch', 'Branch'),
        ('county', 'County'),
    )

    location_type = models.CharField(max_length=20, choices=LOCATION_TYPES, db_index=True)
    name = models.CharField(max_length=128)
    code = models.CharField(max_length=32, blank=True, default='')
    active = models.BooleanField(default=True, db_index=True)
    sort_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['location_type', 'sort_order', 'name']
        constraints = [
            models.UniqueConstraint(
                Lower('name'), 'location_type',
                name='unique_operational_location_name_ci',
            ),
        ]
        verbose_name = 'Operational location'
        verbose_name_plural = 'Operational locations'

    def clean(self):
        super().clean()
        self.name = ' '.join(str(self.name or '').split())
        self.code = ' '.join(str(self.code or '').split()).upper()
        if not self.name:
            from django.core.exceptions import ValidationError
            raise ValidationError({'name': 'Enter a location name.'})

    def __str__(self):
        return f'{self.get_location_type_display()}: {self.name}'


class GroupSheetConfiguration(models.Model):
    """
    Admin-managed routing and workflow configuration for a Telegram group.

    Environment settings remain supported as bootstrap/fallback config, but rows
    in this model are the editable UI source for group-specific sheets, schemas,
    workflows, and parser rules.
    """

    group_id = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
        help_text='Telegram group chat ID, for example -1001234567890.',
    )
    display_name = models.CharField(
        max_length=255,
        blank=True,
        default='',
        help_text='Human-friendly name shown in the admin list.',
    )
    enabled = models.BooleanField(default=True)
    sheet_id = models.CharField(
        max_length=255,
        help_text='Google spreadsheet ID for this group.',
    )
    sheet_name = models.CharField(
        max_length=255,
        default='Complaints Register',
        help_text='Worksheet/tab name inside the spreadsheet.',
    )
    sheet_schema = models.JSONField(
        blank=True,
        default=dict,
        help_text='Optional canonical-field to sheet-header mapping.',
    )
    workflow = models.JSONField(
        blank=True,
        default=dict,
        help_text='Optional status/update workflow settings for this group.',
    )
    parser_rules = models.JSONField(
        blank=True,
        default=dict,
        help_text='Optional parsing rules for this group.',
    )
    metadata = models.JSONField(
        blank=True,
        default=dict,
        help_text='Optional labels, owner notes, or deployment metadata.',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['group_id']
        verbose_name = 'Group sheet configuration'
        verbose_name_plural = 'Group sheet configurations'

    def clean(self):
        super().clean()
        self.group_id = str(self.group_id or '').strip()
        self.sheet_id = str(self.sheet_id or '').strip()
        self.sheet_name = str(self.sheet_name or '').strip()
        if self.enabled and not self.sheet_id:
            from django.core.exceptions import ValidationError
            raise ValidationError({'sheet_id': 'Enabled groups need a sheet ID.'})

    def as_group_config_kwargs(self) -> dict:
        workflow = dict(self.workflow or {})
        # Staff identity and permissions are canonical User/AccessGrant data;
        # workflow JSON is configuration only and must not carry a second
        # authorization list.
        workflow.pop('staff', None)
        return {
            'group_id': self.group_id,
            'display_name': self.display_name,
            'sheet_id': self.sheet_id,
            'sheet_name': self.sheet_name,
            'enabled': self.enabled,
            'metadata': self.metadata or {},
            'sheet_schema': self.sheet_schema or {},
            'workflow': workflow,
            'parser_rules': self.parser_rules or {},
        }
    def sheet_url(self) -> str:
        if not self.sheet_id:
            return ''
        return f'https://docs.google.com/spreadsheets/d/{self.sheet_id}'

    def __str__(self):
        label = self.display_name or self.group_id
        return f"{label} -> {self.sheet_name}"


class SheetRegisterContract(models.Model):
    """Admin-owned publication contract for one Sheets operational register.

    Contracts make the field-level owner explicit even though the current
    platform deliberately supports only Django-to-Sheets publication.  They
    are never an authorization or inbound-import mechanism.
    """

    MODE_PUBLICATION_ONLY = 'publication_only'
    MODE_CHOICES = [(MODE_PUBLICATION_ONLY, 'Django publication only')]
    SUBJECT_NONE = 'none'
    SUBJECT_TAT_CASE = 'tat_tracker_case'
    SUBJECT_CHOICES = [
        (SUBJECT_NONE, 'No row-level subject audit'),
        (SUBJECT_TAT_CASE, 'TAT tracker case'),
    ]
    OWNER_BACKEND = 'backend_owned'
    OWNER_FORMULA = 'formula_owned'
    OWNER_DERIVED = 'derived'
    OWNER_IMMUTABLE = 'immutable'
    FIELD_OWNERS = {OWNER_BACKEND, OWNER_FORMULA, OWNER_DERIVED, OWNER_IMMUTABLE}

    group_configuration = models.ForeignKey(
        GroupSheetConfiguration, on_delete=models.CASCADE, related_name='sheet_register_contracts',
    )
    register_key = models.CharField(max_length=80)
    sheet_name = models.CharField(max_length=255)
    publication_mode = models.CharField(max_length=32, choices=MODE_CHOICES, default=MODE_PUBLICATION_ONLY)
    subject_type = models.CharField(max_length=32, choices=SUBJECT_CHOICES, default=SUBJECT_NONE)
    header_row = models.PositiveIntegerField(default=1)
    data_start_row = models.PositiveIntegerField(default=2)
    row_key_header = models.CharField(max_length=255, blank=True, default='')
    expected_headers = models.JSONField(blank=True, default=list)
    field_ownership = models.JSONField(blank=True, default=dict)
    enabled = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['group_configuration__group_id', 'register_key']
        constraints = [
            models.UniqueConstraint(
                fields=['group_configuration', 'register_key'],
                name='unique_sheet_register_contract_per_group',
            ),
        ]
        indexes = [models.Index(fields=['enabled', 'subject_type'])]
        verbose_name = 'Sheet register contract'
        verbose_name_plural = 'Sheet register contracts'

    def clean(self):
        from django.core.exceptions import ValidationError

        super().clean()
        self.register_key = str(self.register_key or '').strip()
        self.sheet_name = str(self.sheet_name or '').strip()
        self.row_key_header = str(self.row_key_header or '').strip()
        headers = self.expected_headers if isinstance(self.expected_headers, list) else []
        normalized = [' '.join(str(value or '').strip().casefold().split()) for value in headers]
        if not self.register_key:
            raise ValidationError({'register_key': 'Enter a stable register key.'})
        if not self.sheet_name:
            raise ValidationError({'sheet_name': 'Enter the configured worksheet name.'})
        if not headers or any(not value for value in normalized):
            raise ValidationError({'expected_headers': 'Enter the expected non-empty headers in order.'})
        if len(set(normalized)) != len(normalized):
            raise ValidationError({'expected_headers': 'Expected headers must be unique.'})
        ownership = self.field_ownership if isinstance(self.field_ownership, dict) else {}
        missing = [header for header in headers if header not in ownership]
        if missing:
            raise ValidationError({'field_ownership': 'Define ownership for every expected header.'})
        invalid = []
        for header, spec in ownership.items():
            if not isinstance(spec, dict) or str(spec.get('owner') or '') not in self.FIELD_OWNERS:
                invalid.append(str(header))
        if invalid:
            raise ValidationError({'field_ownership': 'Each field needs one supported owner: backend_owned, formula_owned, derived, or immutable.'})
        if self.subject_type == self.SUBJECT_TAT_CASE and not self.row_key_header:
            raise ValidationError({'row_key_header': 'TAT case audits require the immutable Case ID header.'})
        if self.data_start_row <= self.header_row:
            raise ValidationError({'data_start_row': 'The first data row must be below the header row.'})

    def __str__(self):
        return f'{self.group_configuration} / {self.register_key}'


class SheetSyncAuditSnapshot(models.Model):
    """Append-only outcome of one read-only Sheet register audit."""

    STATUS_HEALTHY = 'healthy'
    STATUS_SCHEMA_DRIFT = 'schema_drift'
    STATUS_DIVERGENCE = 'divergence'
    STATUS_UNAVAILABLE = 'unavailable'
    STATUS_CHOICES = [
        (STATUS_HEALTHY, 'Healthy'),
        (STATUS_SCHEMA_DRIFT, 'Schema drift'),
        (STATUS_DIVERGENCE, 'Divergence found'),
        (STATUS_UNAVAILABLE, 'Unavailable'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    contract = models.ForeignKey(
        SheetRegisterContract, on_delete=models.PROTECT, related_name='audit_snapshots',
    )
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, db_index=True)
    expected_header_fingerprint = models.CharField(max_length=64, blank=True, default='')
    actual_header_fingerprint = models.CharField(max_length=64, blank=True, default='')
    missing_headers = models.JSONField(blank=True, default=list)
    duplicate_headers = models.JSONField(blank=True, default=list)
    reordered_headers = models.BooleanField(default=False)
    rows_checked = models.PositiveIntegerField(default=0)
    discrepancy_count = models.PositiveIntegerField(default=0)
    error_code = models.CharField(max_length=80, blank=True, default='')
    error = models.TextField(blank=True, default='')
    checked_by = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['contract', 'created_at']),
            models.Index(fields=['status', 'created_at']),
        ]
        verbose_name = 'Sheet sync audit snapshot'
        verbose_name_plural = 'Sheet sync audit snapshots'

    def __str__(self):
        return f'{self.contract.register_key}: {self.status} ({self.created_at:%d-%b-%Y %H:%M})'


class SheetSyncDiscrepancy(models.Model):
    """One privacy-preserving difference found by a register audit."""

    KIND_MISSING_ROW = 'missing_row'
    KIND_ORPHAN_ROW = 'orphan_row'
    KIND_DUPLICATE_ROW_KEY = 'duplicate_row_key'
    KIND_ROW_POINTER = 'row_pointer_mismatch'
    KIND_FIELD_VALUE = 'field_value_mismatch'
    KIND_CHOICES = [
        (KIND_MISSING_ROW, 'Django record missing from Sheet'),
        (KIND_ORPHAN_ROW, 'Sheet row has no Django record'),
        (KIND_DUPLICATE_ROW_KEY, 'Duplicate Sheet row key'),
        (KIND_ROW_POINTER, 'Stored row pointer mismatch'),
        (KIND_FIELD_VALUE, 'Backend-owned field differs'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    snapshot = models.ForeignKey(SheetSyncAuditSnapshot, on_delete=models.CASCADE, related_name='discrepancies')
    record_key = models.CharField(max_length=255, blank=True, default='', db_index=True)
    field_name = models.CharField(max_length=255, blank=True, default='')
    kind = models.CharField(max_length=48, choices=KIND_CHOICES, db_index=True)
    expected_value_hash = models.CharField(max_length=64, blank=True, default='')
    actual_value_hash = models.CharField(max_length=64, blank=True, default='')
    detail = models.CharField(max_length=500, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['kind', 'record_key', 'field_name']
        indexes = [
            models.Index(fields=['snapshot', 'kind']),
            models.Index(fields=['record_key', 'kind']),
        ]
        verbose_name = 'Sheet sync discrepancy'
        verbose_name_plural = 'Sheet sync discrepancies'

    def __str__(self):
        return f'{self.kind}: {self.record_key or "register"}'


class TatTrackerApprovalCertificate(models.Model):
    """External e-signature evidence for a completed TAT approval stage."""

    STATUS_CHOICES = [('awaiting_signature', 'Awaiting signature'), ('signed', 'Signed'), ('declined', 'Declined'), ('expired', 'Expired'), ('delivery_failed', 'Delivery failed'), ('failed', 'Failed')]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(TatTrackerCase, on_delete=models.CASCADE, related_name='approval_certificates')
    event = models.OneToOneField(TatTrackerEvent, on_delete=models.PROTECT, related_name='approval_certificate')
    staff_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='tat_approval_certificates',
    )
    signer_name = models.CharField(max_length=255, blank=True, default='')
    signer_telegram_id = models.CharField(max_length=100, blank=True, default='')
    signer_national_id = models.CharField(max_length=40, blank=True, default='')
    signer_phone_number = models.CharField(max_length=20, blank=True, default='')
    signer_email = models.EmailField(blank=True, default='')
    stage_key = models.CharField(max_length=120, db_index=True)
    external_reference = models.CharField(max_length=80, unique=True)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default='awaiting_signature', db_index=True)
    signed_document_hash = models.CharField(max_length=64, blank=True, default='')
    signed_document_path = models.TextField(blank=True, default='')
    webhook_delivery_id = models.CharField(max_length=64, blank=True, default='', unique=True, null=True)
    error = models.TextField(blank=True, default='')
    signed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['case', 'stage_key'], name='core_tattra_case_id_61a8f6_idx'),
            models.Index(fields=['status', 'updated_at'], name='core_tattra_status_a6367e_idx'),
        ]

class RequisitionBatch(models.Model):
    """Generated requisition/order batch output kept for portal reference."""

    STATUS_CHOICES = [
        ('preview', 'Preview'),
        ('generated', 'Generated'),
        ('invoices_uploaded', 'Invoices Uploaded'),
        ('partially_invoiced', 'Partially Invoiced'),
        ('completed', 'Completed'),
        ('needs_review', 'Needs Review'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order_number = models.CharField(max_length=128, unique=True, db_index=True)
    version = models.PositiveIntegerField(
        default=0,
        db_index=True,
        help_text='Latest final requisition version for this order; starts at 1 when generated.',
    )
    preview_version = models.PositiveIntegerField(
        default=0,
        db_index=True,
        help_text='Latest stored preview version for this order.',
    )
    requisition_date = models.DateField(null=True, blank=True)
    generated_by = models.CharField(max_length=255, blank=True, default='')
    filename = models.CharField(max_length=255, blank=True, default='')
    content_type = models.CharField(
        max_length=255,
        default='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    file_content = models.BinaryField(blank=True, default=bytes)
    drive_file_id = models.CharField(max_length=255, blank=True, default='')
    drive_url = models.URLField(max_length=1000, blank=True, default='')
    drive_upload_error = models.TextField(blank=True, default='')
    drive_sync_attempts = models.PositiveIntegerField(default=0)
    drive_last_sync_at = models.DateTimeField(null=True, blank=True)
    drive_next_retry_at = models.DateTimeField(null=True, blank=True, db_index=True)
    preview_filename = models.CharField(max_length=255, blank=True, default='')
    preview_drive_file_id = models.CharField(max_length=255, blank=True, default='')
    preview_drive_url = models.URLField(max_length=1000, blank=True, default='')
    preview_generated_by = models.CharField(max_length=255, blank=True, default='')
    preview_generated_at = models.DateTimeField(null=True, blank=True)
    preview_error = models.TextField(blank=True, default='')
    preview_drive_sync_attempts = models.PositiveIntegerField(default=0)
    preview_drive_last_sync_at = models.DateTimeField(null=True, blank=True)
    preview_drive_next_retry_at = models.DateTimeField(null=True, blank=True, db_index=True)
    farmer_ids = models.JSONField(blank=True, default=list)
    farmer_count = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default='generated', db_index=True)
    invoice_summary = models.JSONField(blank=True, default=dict)
    last_invoice_result = models.JSONField(blank=True, default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-requisition_date', '-updated_at']
        indexes = [
            models.Index(fields=['order_number']),
            models.Index(fields=['status', 'updated_at']),
        ]
        verbose_name = 'Requisition batch'
        verbose_name_plural = 'Requisition batches'

    def __str__(self):
        return f"{self.order_number} ({self.status})"


class RequisitionTemplate(models.Model):
    """
    Admin-uploaded Excel templates used for Requisition/Order generation.
    """
    name = models.CharField(max_length=255, default='JBL Requisition Form')
    file = models.FileField(upload_to='requisition/', help_text='Upload the Excel (.xlsx) template here.')
    original_filename = models.CharField(max_length=255, blank=True, default='')
    content_type = models.CharField(
        max_length=255,
        blank=True,
        default='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    size = models.PositiveIntegerField(default=0)
    checksum = models.CharField(max_length=64, blank=True, default='')
    drive_file_id = models.CharField(max_length=255, blank=True, default='')
    drive_url = models.URLField(max_length=1000, blank=True, default='')
    drive_uploaded_at = models.DateTimeField(null=True, blank=True)
    drive_upload_error = models.TextField(blank=True, default='')
    is_active = models.BooleanField(default=True, help_text='Mark this as the active template used for generation.')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_active', '-updated_at']
        verbose_name = 'Requisition template'
        verbose_name_plural = 'Requisition templates'

    def save(self, *args, **kwargs):
        with transaction.atomic():
            super().save(*args, **kwargs)
            if self.is_active:
                type(self).objects.filter(
                    name__iexact=self.name,
                    is_active=True,
                ).exclude(pk=self.pk).update(
                    is_active=False,
                    updated_at=timezone.now(),
                )

    def __str__(self):
        return f"{self.name} ({'Active' if self.is_active else 'Inactive'})"


class PaymentDocumentTemplate(models.Model):
    """
    Admin-uploaded Excel template used for HB payment document generation.
    """
    name = models.CharField(max_length=255, default='HB Payment Document')
    file = models.FileField(upload_to='payment_documents/', help_text='Upload the Excel (.xlsx) payment template here.')
    original_filename = models.CharField(max_length=255, blank=True, default='')
    content_type = models.CharField(
        max_length=255,
        blank=True,
        default='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    size = models.PositiveIntegerField(default=0)
    checksum = models.CharField(max_length=64, blank=True, default='')
    drive_file_id = models.CharField(max_length=255, blank=True, default='')
    drive_url = models.URLField(max_length=1000, blank=True, default='')
    drive_uploaded_at = models.DateTimeField(null=True, blank=True)
    drive_upload_error = models.TextField(blank=True, default='')
    is_active = models.BooleanField(default=True, help_text='Mark this as the active template used for payment generation.')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_active', '-updated_at']
        verbose_name = 'Payment document template'
        verbose_name_plural = 'Payment document templates'

    def save(self, *args, **kwargs):
        with transaction.atomic():
            super().save(*args, **kwargs)
            if self.is_active:
                type(self).objects.filter(
                    name__iexact=self.name,
                    is_active=True,
                ).exclude(pk=self.pk).update(
                    is_active=False,
                    updated_at=timezone.now(),
                )

    def __str__(self):
        return f"{self.name} ({'Active' if self.is_active else 'Inactive'})"


class InvoiceUploadBatch(models.Model):
    """Drive-backed invoice PDF upload batch kept before reconciliation."""

    STATUS_CHOICES = [
        ('uploaded', 'Uploaded'),
        ('awaiting_confirmation', 'Awaiting Confirmation'),
        ('parsed', 'Parsed'),
        ('parse_failed', 'Parse Failed'),
        ('partially_matched', 'Partially Matched'),
        ('matched', 'Matched'),
        ('needs_review', 'Needs Review'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    original_filename = models.CharField(max_length=255, blank=True, default='')
    content_type = models.CharField(max_length=255, blank=True, default='application/pdf')
    size = models.PositiveIntegerField(default=0)
    uploaded_by = models.CharField(max_length=255, blank=True, default='')
    client_request_id = models.CharField(max_length=128, blank=True, default='', db_index=True)
    order_number = models.CharField(max_length=128, blank=True, default='', db_index=True)
    drive_file_id = models.CharField(max_length=255, blank=True, default='')
    drive_url = models.URLField(max_length=1000, blank=True, default='')
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default='uploaded', db_index=True)
    total_pages = models.PositiveIntegerField(default=0)
    total_parsed = models.PositiveIntegerField(default=0)
    matched_count = models.PositiveIntegerField(default=0)
    unmatched_count = models.PositiveIntegerField(default=0)
    error = models.TextField(blank=True, default='')
    sync_status = models.CharField(max_length=32, blank=True, default='', db_index=True)
    sync_error = models.TextField(blank=True, default='')
    metadata = models.JSONField(blank=True, default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['uploaded_by', 'created_at']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['client_request_id'],
                condition=~models.Q(client_request_id=''),
                name='unique_invoice_upload_client_request',
            ),
        ]
        verbose_name = 'Invoice upload batch'
        verbose_name_plural = 'Invoice upload batches'

    def __str__(self):
        return f"{self.original_filename or self.id} ({self.status})"


class ParsedInvoice(models.Model):
    """One parsed invoice page/record from a Drive-backed invoice upload batch."""

    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('unmatched', 'Unmatched'),
        ('matched', 'Matched'),
        ('ambiguous', 'Ambiguous'),
        ('ignored', 'Ignored'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(InvoiceUploadBatch, on_delete=models.CASCADE, related_name='invoices')
    page = models.PositiveIntegerField(default=0)
    invoice_no = models.CharField(max_length=128, blank=True, default='', db_index=True)
    invoice_date_raw = models.CharField(max_length=64, blank=True, default='')
    invoice_date = models.DateField(null=True, blank=True)
    customer_name = models.CharField(max_length=255, blank=True, default='', db_index=True)
    customer_id = models.CharField(max_length=64, blank=True, default='', db_index=True)
    customer_phone = models.CharField(max_length=64, blank=True, default='', db_index=True)
    invoice_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    total_after_discount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    discount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    payment = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    balance_due = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    balance_due_check = models.CharField(max_length=128, blank=True, default='')
    calculated_balance_due = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    balance_due_difference = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    balance_due_check_basis = models.CharField(max_length=128, blank=True, default='')
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default='unmatched', db_index=True)
    matched_farmer = models.ForeignKey(
        JawabuFarmerMaster,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='parsed_invoices',
    )
    proposed_farmer = models.ForeignKey(
        JawabuFarmerMaster,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='proposed_invoices',
    )
    proposed_order_number = models.CharField(max_length=128, blank=True, default='', db_index=True)
    matched_order_number = models.CharField(max_length=128, blank=True, default='', db_index=True)
    raw_payload = models.JSONField(blank=True, default=dict)
    review_notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['invoice_no']),
            models.Index(fields=['status', 'created_at']),
            models.Index(fields=['matched_order_number', 'status']),
        ]
        verbose_name = 'Parsed invoice'
        verbose_name_plural = 'Parsed invoices'

    def __str__(self):
        return f"{self.invoice_no or self.id} ({self.status})"


class ParsedInvoiceEvent(models.Model):
    """Append-only operational event for manual invoice reconciliation."""

    ACTION_CHOICES = [
        ('uploaded', 'Uploaded'),
        ('parsed', 'Parsed'),
        ('matched', 'Matched'),
        ('unmatched', 'Unmatched'),
        ('ignored', 'Ignored'),
        ('restored', 'Restored'),
        ('note', 'Note'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey(ParsedInvoice, on_delete=models.CASCADE, related_name='events')
    action = models.CharField(max_length=32, choices=ACTION_CHOICES, db_index=True)
    actor = models.CharField(max_length=255, blank=True, default='')
    note = models.TextField(blank=True, default='')
    metadata = models.JSONField(blank=True, default=dict)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['invoice', 'created_at']),
            models.Index(fields=['action', 'created_at']),
        ]
        verbose_name = 'Parsed invoice event'
        verbose_name_plural = 'Parsed invoice events'

    def __str__(self):
        return f"{self.invoice_id} {self.action} by {self.actor or 'system'}"


class PaymentDocument(models.Model):
    """Drive-backed payment workbook, review snapshot, or final artifact.

    A workbook generated for operations is deliberately not a final payment.
    It remains a review snapshot until Head of Rural approves it and supplies
    the batch Call Up Comment used in the payment template's COL column.
    """

    STATUS_CHOICES = [
        ('preview', 'Preview'),
        ('pending_review', 'Pending Head of Rural review'),
        ('reviewed', 'Reviewed'),
        ('final', 'Final'),
        ('failed', 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order_number = models.CharField(max_length=128, db_index=True)
    payment_number = models.CharField(max_length=32, blank=True, default='', db_index=True)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default='preview', db_index=True)
    version = models.PositiveIntegerField(default=1)
    filename = models.CharField(max_length=255, blank=True, default='')
    content_type = models.CharField(
        max_length=255,
        default='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    # Payment documents are Drive-backed operational files, but retaining the
    # generated bytes makes the exact version available for later physical
    # sign-off.  Older records intentionally remain blank and are treated as
    # legacy/non-signable until regenerated.
    file_content = models.BinaryField(blank=True, default=bytes)
    drive_file_id = models.CharField(max_length=255, blank=True, default='')
    drive_url = models.URLField(max_length=1000, blank=True, default='')
    drive_sync_attempts = models.PositiveIntegerField(default=0)
    drive_last_sync_at = models.DateTimeField(null=True, blank=True)
    drive_next_retry_at = models.DateTimeField(null=True, blank=True, db_index=True)
    generated_by = models.CharField(max_length=255, blank=True, default='')
    reviewed_by = models.CharField(max_length=255, blank=True, default='')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    call_up_comments = models.TextField(
        blank=True,
        default='',
        help_text='Head of Rural approval comment written to the payment template COL column.',
    )
    case_call_up_comments = models.JSONField(
        blank=True,
        default=dict,
        help_text='Per-case Head of Rural payment COL comments keyed by farmer ID.',
    )
    finalized_by = models.CharField(max_length=255, blank=True, default='')
    row_count = models.PositiveIntegerField(default=0)
    farmer_ids = models.JSONField(blank=True, default=list)
    invoice_batch_ids = models.JSONField(blank=True, default=list)
    validation_summary = models.JSONField(blank=True, default=dict)
    error = models.TextField(blank=True, default='')
    finalized_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['order_number', 'status']),
            models.Index(fields=['status', 'created_at']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['order_number', 'version'],
                condition=models.Q(status='final'),
                name='unique_final_payment_document_version',
            ),
        ]
        verbose_name = 'Payment document'
        verbose_name_plural = 'Payment documents'

    def __str__(self):
        payment_label = f" #{self.payment_number}" if self.payment_number else ''
        return f"{self.order_number}{payment_label} v{self.version} ({self.status})"


class DocumentSignoffPolicy(models.Model):
    """Maker-checker controlled role responsible for physical document sign-off."""

    DOCUMENT_REQUISITION = 'requisition'
    DOCUMENT_PAYMENT = 'payment'
    DOCUMENT_TYPE_CHOICES = [
        (DOCUMENT_REQUISITION, 'Requisition / order'),
        (DOCUMENT_PAYMENT, 'Payment schedule'),
    ]

    document_type = models.CharField(max_length=24, choices=DOCUMENT_TYPE_CHOICES, unique=True)
    workflow = models.CharField(
        max_length=40,
        choices=AccessGrant.WORKFLOW_CHOICES,
        default='jawabu_portal',
        editable=False,
    )
    approval_role = models.CharField(max_length=80)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['document_type']
        verbose_name = 'document sign-off policy'
        verbose_name_plural = 'document sign-off policies'

    def clean(self):
        from core.services.access_policies import validate_access_scope

        if self.workflow != 'jawabu_portal':
            raise ValidationError({'workflow': 'Physical finance-document sign-off is a Jawabu Portal policy.'})
        self.approval_role = validate_access_scope(
            workflow=self.workflow,
            role=self.approval_role,
        )

    def __str__(self):
        return f'{self.get_document_type_display()}: {self.approval_role}'


class DocumentPhysicalSignoff(models.Model):
    """Immutable physical-signature scan and the exact workbook it confirms.

    The system records an authorised staff attestation after a paper document
    has been signed and stamped.  It does not manufacture or verify an
    electronic signature.
    """

    DOCUMENT_REQUISITION = DocumentSignoffPolicy.DOCUMENT_REQUISITION
    DOCUMENT_PAYMENT = DocumentSignoffPolicy.DOCUMENT_PAYMENT
    DOCUMENT_TYPE_CHOICES = DocumentSignoffPolicy.DOCUMENT_TYPE_CHOICES

    STATUS_UPLOAD_PENDING = 'upload_pending'
    STATUS_SIGNED_APPROVED = 'signed_approved'
    STATUS_UPLOAD_FAILED = 'upload_failed'
    STATUS_REJECTED = 'rejected'
    STATUS_CHOICES = [
        (STATUS_UPLOAD_PENDING, 'Upload pending'),
        (STATUS_SIGNED_APPROVED, 'Signed scan approved'),
        (STATUS_UPLOAD_FAILED, 'Upload retry required'),
        (STATUS_REJECTED, 'Rejected'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document_type = models.CharField(max_length=24, choices=DOCUMENT_TYPE_CHOICES, db_index=True)
    requisition_batch = models.ForeignKey(
        RequisitionBatch,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='physical_signoffs',
    )
    payment_document = models.ForeignKey(
        PaymentDocument,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='physical_signoffs',
    )
    source_version = models.PositiveIntegerField(default=1)
    source_filename = models.CharField(max_length=255)
    source_content_type = models.CharField(max_length=255)
    source_checksum = models.CharField(max_length=64, db_index=True)
    source_file_content = models.BinaryField(blank=True, default=bytes)
    scan_filename = models.CharField(max_length=255)
    scan_content_type = models.CharField(max_length=255)
    scan_size = models.PositiveIntegerField(default=0)
    scan_checksum = models.CharField(max_length=64, db_index=True)
    scan_file_content = models.BinaryField(blank=True, default=bytes)
    drive_file_id = models.CharField(max_length=255, blank=True, default='')
    drive_url = models.URLField(max_length=1000, blank=True, default='')
    drive_sync_attempts = models.PositiveIntegerField(default=0)
    drive_last_sync_at = models.DateTimeField(null=True, blank=True)
    drive_next_retry_at = models.DateTimeField(null=True, blank=True, db_index=True)
    drive_upload_error = models.TextField(blank=True, default='')
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_UPLOAD_PENDING, db_index=True)
    attested_complete = models.BooleanField(default=False)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='uploaded_physical_document_signoffs',
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='approved_physical_document_signoffs',
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, default='')
    request_id = models.CharField(max_length=128, blank=True, default='', db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['document_type', 'status', 'created_at']),
            models.Index(fields=['requisition_batch', 'source_version']),
            models.Index(fields=['payment_document', 'source_version']),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(document_type='requisition', requisition_batch__isnull=False, payment_document__isnull=True)
                    | models.Q(document_type='payment', requisition_batch__isnull=True, payment_document__isnull=False)
                ),
                name='document_signoff_matches_artifact_type',
            ),
            models.UniqueConstraint(
                fields=['request_id'],
                condition=~models.Q(request_id=''),
                name='unique_document_signoff_request_id',
            ),
            models.UniqueConstraint(
                fields=['requisition_batch', 'source_version'],
                condition=models.Q(document_type='requisition', status='signed_approved'),
                name='unique_signed_requisition_version',
            ),
            models.UniqueConstraint(
                fields=['payment_document', 'source_version'],
                condition=models.Q(document_type='payment', status='signed_approved'),
                name='unique_signed_payment_version',
            ),
        ]
        verbose_name = 'physical document sign-off'
        verbose_name_plural = 'physical document sign-offs'

    def clean(self):
        if self.document_type == self.DOCUMENT_REQUISITION:
            if not self.requisition_batch_id or self.payment_document_id:
                raise ValidationError('A requisition sign-off must reference exactly one requisition batch.')
        elif self.document_type == self.DOCUMENT_PAYMENT:
            if not self.payment_document_id or self.requisition_batch_id:
                raise ValidationError('A payment sign-off must reference exactly one payment document.')
        else:
            raise ValidationError({'document_type': 'Select a supported document type.'})
        if not self.attested_complete:
            raise ValidationError({'attested_complete': 'The authorised approver must confirm the scan is complete, signed, stamped, and readable.'})

    def __str__(self):
        reference = self.requisition_batch_id or self.payment_document_id
        return f'{self.get_document_type_display()} {reference} v{self.source_version} ({self.status})'


class DocumentPhysicalSignoffEvent(models.Model):
    """Append-only audit trail for physical document sign-off attempts."""

    ACTION_SUBMITTED = 'submitted'
    ACTION_APPROVED = 'approved'
    ACTION_UPLOAD_FAILED = 'upload_failed'
    ACTION_RETRY_STARTED = 'retry_started'
    ACTION_REJECTED = 'rejected'
    ACTION_CHOICES = [
        (ACTION_SUBMITTED, 'Submitted'),
        (ACTION_APPROVED, 'Approved'),
        (ACTION_UPLOAD_FAILED, 'Upload failed'),
        (ACTION_RETRY_STARTED, 'Retry started'),
        (ACTION_REJECTED, 'Rejected'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    signoff = models.ForeignKey(DocumentPhysicalSignoff, on_delete=models.CASCADE, related_name='events')
    action = models.CharField(max_length=32, choices=ACTION_CHOICES, db_index=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    note = models.TextField(blank=True, default='')
    metadata = models.JSONField(blank=True, default=dict)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['signoff', 'created_at'])]
        verbose_name = 'physical document sign-off event'
        verbose_name_plural = 'physical document sign-off events'


class ComplianceAuditChainState(models.Model):
    """Single locked cursor used to serialize the compliance-evidence chain."""

    singleton = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    last_position = models.PositiveBigIntegerField(default=0)
    last_hash = models.CharField(max_length=64, blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'compliance audit chain state'
        verbose_name_plural = 'compliance audit chain state'


class ComplianceAuditEvent(models.Model):
    """Cross-workflow, append-only evidence for investigations and audits.

    Workflow-native event tables remain the detailed operational history. This
    ledger is the shared compliance projection with a stable taxonomy,
    actor/authority attribution, before/after data, and a hash-chain position.
    PostgreSQL additionally rejects UPDATE/DELETE at the database boundary.
    """

    WORKFLOW_PORTAL = 'portal'
    WORKFLOW_COMPLAINTS = 'complaint_cases'
    WORKFLOW_TAT = 'tat_tracker'
    WORKFLOW_SPIN = 'spin'
    WORKFLOW_ACCESS_CONTROL = 'access_control'
    WORKFLOW_CHOICES = [
        (WORKFLOW_PORTAL, 'Portal'),
        (WORKFLOW_COMPLAINTS, 'Complaint Cases'),
        (WORKFLOW_TAT, 'TAT Tracker'),
        (WORKFLOW_SPIN, 'SPIN / CRB'),
        (WORKFLOW_ACCESS_CONTROL, 'Access control'),
    ]

    ORIGIN_HUMAN = 'human'
    ORIGIN_SYSTEM = 'system'
    ORIGIN_EXTERNAL_SYNC = 'external_sync'
    ORIGIN_CHOICES = [
        (ORIGIN_HUMAN, 'Human action'),
        (ORIGIN_SYSTEM, 'System automation'),
        (ORIGIN_EXTERNAL_SYNC, 'External synchronization'),
    ]

    RETENTION_LEGAL_HOLD = 'legal_hold'
    RETENTION_CHOICES = [(RETENTION_LEGAL_HOLD, 'Legal hold - no automatic purge')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow = models.CharField(max_length=40, choices=WORKFLOW_CHOICES, db_index=True)
    action = models.CharField(max_length=120, db_index=True)
    category = models.CharField(max_length=40, default='workflow', db_index=True)
    origin = models.CharField(max_length=24, choices=ORIGIN_CHOICES, default=ORIGIN_HUMAN, db_index=True)
    subject_type = models.CharField(max_length=80, db_index=True)
    subject_id = models.CharField(max_length=128, db_index=True)
    customer_reference = models.CharField(max_length=128, blank=True, default='', db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='compliance_audit_actions',
    )
    authority_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='compliance_audit_authorizations',
    )
    actor_label = models.CharField(max_length=255, blank=True, default='')
    authority_label = models.CharField(max_length=255, blank=True, default='')
    request_id = models.CharField(max_length=128, blank=True, default='', db_index=True)
    source_model = models.CharField(max_length=120, blank=True, default='')
    source_event_id = models.CharField(max_length=160, blank=True, default='')
    deduplication_key = models.CharField(max_length=255, unique=True, db_index=True)
    before_values = models.JSONField(blank=True, default=dict)
    after_values = models.JSONField(blank=True, default=dict)
    metadata = models.JSONField(blank=True, default=dict)
    sensitive = models.BooleanField(default=False, db_index=True)
    retention_class = models.CharField(
        max_length=32, choices=RETENTION_CHOICES, default=RETENTION_LEGAL_HOLD, db_index=True,
    )
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    recorded_at = models.DateTimeField(auto_now_add=True, db_index=True)
    chain_position = models.PositiveBigIntegerField(unique=True, editable=False)
    previous_hash = models.CharField(max_length=64, blank=True, default='', editable=False)
    payload_hash = models.CharField(max_length=64, editable=False)
    integrity_hash = models.CharField(max_length=64, unique=True, editable=False)

    class Meta:
        ordering = ['-chain_position']
        indexes = [
            models.Index(fields=['workflow', 'occurred_at']),
            models.Index(fields=['subject_type', 'subject_id', 'occurred_at']),
            models.Index(fields=['actor', 'occurred_at']),
            models.Index(fields=['action', 'occurred_at']),
            models.Index(fields=['sensitive', 'occurred_at']),
        ]
        permissions = [
            ('export_complianceauditevent', 'Can export compliance audit evidence'),
            ('verify_complianceauditevent', 'Can verify compliance audit integrity'),
        ]
        verbose_name = 'compliance audit event'
        verbose_name_plural = 'compliance audit events'

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Compliance audit events are append-only and cannot be changed.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Compliance audit events are append-only and cannot be deleted.')

    def __str__(self):
        return f'#{self.chain_position} {self.workflow}.{self.action}'


class ComplianceAuditCheckpoint(models.Model):
    """Daily hash-chain checkpoint; outbound delivery is deliberately opt-in."""

    STATUS_DISABLED = 'disabled'
    STATUS_PENDING = 'pending'
    STATUS_SENT = 'sent'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_DISABLED, 'Delivery disabled'),
        (STATUS_PENDING, 'Ready to deliver'),
        (STATUS_SENT, 'Delivered'),
        (STATUS_FAILED, 'Delivery failed'),
    ]

    checkpoint_date = models.DateField(unique=True, db_index=True)
    chain_position = models.PositiveBigIntegerField(default=0)
    chain_hash = models.CharField(max_length=64, blank=True, default='')
    event_count = models.PositiveBigIntegerField(default=0)
    recipient_fingerprint = models.CharField(max_length=64, blank=True, default='')
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_DISABLED, db_index=True)
    delivery_attempts = models.PositiveIntegerField(default=0)
    delivered_at = models.DateTimeField(null=True, blank=True)
    delivery_error = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-checkpoint_date']
        verbose_name = 'compliance audit checkpoint'
        verbose_name_plural = 'compliance audit checkpoints'


class IntegrationOperation(models.Model):
    """Durable, redacted record of a manually retriable external operation.

    This is an operations register, not a hidden task queue. No background
    worker is enabled: the owning workflow may retry a dead-lettered operation
    when its dependency is healthy. Raw payloads never belong here.
    """

    INTEGRATION_GOOGLE_SHEETS = 'google_sheets'
    INTEGRATION_GOOGLE_DRIVE = 'google_drive'
    INTEGRATION_TELEGRAM = 'telegram'
    INTEGRATION_CHOICES = [
        (INTEGRATION_GOOGLE_SHEETS, 'Google Sheets'),
        (INTEGRATION_GOOGLE_DRIVE, 'Google Drive'),
        (INTEGRATION_TELEGRAM, 'Telegram'),
    ]
    STATUS_PENDING = 'pending'
    STATUS_RUNNING = 'running'
    STATUS_SUCCEEDED = 'succeeded'
    STATUS_RETRYABLE = 'retryable_failure'
    STATUS_DEAD_LETTER = 'dead_letter'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_RUNNING, 'Running'),
        (STATUS_SUCCEEDED, 'Succeeded'),
        (STATUS_RETRYABLE, 'Retryable failure'),
        (STATUS_DEAD_LETTER, 'Dead letter'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    integration = models.CharField(max_length=32, choices=INTEGRATION_CHOICES, db_index=True)
    operation_type = models.CharField(max_length=80, db_index=True)
    deduplication_key = models.CharField(max_length=255, unique=True, db_index=True)
    source_model = models.CharField(max_length=120, blank=True, default='')
    source_id = models.CharField(max_length=128, blank=True, default='', db_index=True)
    request_id = models.CharField(max_length=128, blank=True, default='', db_index=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='integration_operations',
    )
    requested_by_label = models.CharField(max_length=255, blank=True, default='')
    payload_digest = models.CharField(max_length=64, blank=True, default='')
    metadata = models.JSONField(blank=True, default=dict)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=1)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    next_retry_at = models.DateTimeField(null=True, blank=True, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=80, blank=True, default='')
    last_error = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['integration', 'status', 'updated_at']),
            models.Index(fields=['source_model', 'source_id', 'created_at']),
            models.Index(fields=['request_id', 'created_at']),
        ]
        verbose_name = 'integration operation'
        verbose_name_plural = 'integration operations'

    def __str__(self):
        return f'{self.integration}.{self.operation_type} ({self.status})'


class IntegrationCircuitState(models.Model):
    """One persisted bounded circuit per outbound integration."""

    STATUS_CLOSED = 'closed'
    STATUS_OPEN = 'open'
    STATUS_HALF_OPEN = 'half_open'
    STATUS_CHOICES = [
        (STATUS_CLOSED, 'Closed'),
        (STATUS_OPEN, 'Open'),
        (STATUS_HALF_OPEN, 'Half open'),
    ]

    integration = models.CharField(max_length=32, unique=True, db_index=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_CLOSED, db_index=True)
    consecutive_failures = models.PositiveIntegerField(default=0)
    failure_window_started_at = models.DateTimeField(null=True, blank=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    next_probe_at = models.DateTimeField(null=True, blank=True)
    last_failure_code = models.CharField(max_length=80, blank=True, default='')
    last_success_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'integration circuit state'
        verbose_name_plural = 'integration circuit states'

    def __str__(self):
        return f'{self.integration} ({self.status})'
