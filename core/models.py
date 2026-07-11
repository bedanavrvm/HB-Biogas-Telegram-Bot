"""
Database models for the biogas telegram bot system.
Provides full traceability and deduplication support.
"""
import uuid
import re
from django.db import models
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
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['group_id', 'created_at']),
            models.Index(fields=['telegram_message_id']),
            models.Index(fields=['reply_to_telegram_message_id']),
        ]

    def __str__(self):
        return f"CaseUpdate {self.parsed_message.message_id}: {self.new_status}"


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
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['group_id', 'created_at']),
            models.Index(fields=['business_key_type', 'business_key_value']),
            models.Index(fields=['telegram_file_id']),
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
            models.Index(fields=['group_id', 'national_id', 'primary_phone']),
            models.Index(fields=['group_id', 'import_status']),
            models.Index(fields=['source_message_hash']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['group_id', 'source_message_hash'],
                name='unique_spin_request_source_per_group',
            ),
        ]
        verbose_name = 'SPIN / CRB request'
        verbose_name_plural = 'SPIN / CRB requests'

    def __str__(self):
        return f"{self.get_request_type_display()} {self.customer_name or self.national_id or self.primary_phone}".strip()


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


class JawabuFarmerMaster(models.Model):
    """Clean internal master data for Jawabu farmers used by visit forms."""

    STATUS_CHOICES = [
        ('active', 'Active'),
        ('review_needed', 'Review Needed'),
        ('inactive', 'Inactive'),
    ]

    # Stage 2 â€” JBL visit status dropdown (aligns with FCAUP_STATUS_VALUES in fca.py)
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

    # Stage 3 â€” Credit Decision values (master data dropdown)
    CREDIT_DECISION_CHOICES = [
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected'),
        ('Deferred', 'Deferred'),
        ('Exemption Approved', 'Exemption Approved'),
        ('Pending', 'Pending'),
    ]

    FINAL_DECISION_CHOICES = [
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected'),
        ('Deferred', 'Deferred'),
        ('Under Review', 'Under Review'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
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
    hb_sales_person = models.CharField(max_length=255, blank=True, default='', db_index=True)
    sign_date = models.CharField(max_length=32, blank=True, default='')
    created_date = models.CharField(max_length=32, blank=True, default='')
    comments = models.TextField(blank=True, default='')

    gps_link = models.URLField(max_length=1000, blank=True, default='')
    latitude = models.CharField(max_length=64, blank=True, default='')
    longitude = models.CharField(max_length=64, blank=True, default='')

    # â”€â”€ Stage 2: JBL visit â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
        help_text='Jawabu Comment After Visit â€” 12-option dropdown set by JBL officer.',
    )
    jbl_visit_comment = models.TextField(
        blank=True, default='',
        help_text='Optional free-text comment from the JBL officer.',
    )

    # â”€â”€ Stage 3: Credit decision â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    credit_decision = models.CharField(
        max_length=80, blank=True, default='',
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

    jbl_media_urls = models.TextField(
        blank=True, default='',
        help_text='Drive links for documents/images uploaded during the JBL visit stage.',
    )

    # â”€â”€ Stage 4: Requisition / order â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    requisition_date = models.DateField(
        null=True, blank=True,
        help_text='Jawabu Requisition Date â€” only set after Credit Decision = Approved.',
    )
    order_number = models.CharField(
        max_length=128, blank=True, default='', db_index=True,
        help_text='Order No. assigned by admin after credit approval.',
    )

    # â”€â”€ Stage 7: Invoice generation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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
        ]
        verbose_name = 'Jawabu farmer master record'
        verbose_name_plural = 'Jawabu farmer master data'

    def __str__(self):
        label = self.customer_name or self.national_id or self.primary_phone or 'unknown farmer'
        return f"{label} ({self.status})"

class JawabuFarmerUploadBatch(models.Model):
    """Staged CSV upload for staff review before updating Jawabu farmer master data."""

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
        return {
            'group_id': self.group_id,
            'display_name': self.display_name,
            'sheet_id': self.sheet_id,
            'sheet_name': self.sheet_name,
            'enabled': self.enabled,
            'metadata': self.metadata or {},
            'sheet_schema': self.sheet_schema or {},
            'workflow': self.workflow or {},
            'parser_rules': self.parser_rules or {},
        }

    def sheet_url(self) -> str:
        if not self.sheet_id:
            return ''
        return f'https://docs.google.com/spreadsheets/d/{self.sheet_id}'

    def __str__(self):
        label = self.display_name or self.group_id
        return f"{label} -> {self.sheet_name}"


class RequisitionBatch(models.Model):
    """Generated requisition/order batch output kept for portal reference."""

    STATUS_CHOICES = [
        ('generated', 'Generated'),
        ('invoices_uploaded', 'Invoices Uploaded'),
        ('partially_invoiced', 'Partially Invoiced'),
        ('completed', 'Completed'),
        ('needs_review', 'Needs Review'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order_number = models.CharField(max_length=128, unique=True, db_index=True)
    requisition_date = models.DateField(null=True, blank=True)
    generated_by = models.CharField(max_length=255, blank=True, default='')
    filename = models.CharField(max_length=255, blank=True, default='')
    content_type = models.CharField(
        max_length=255,
        default='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    file_content = models.BinaryField(blank=True, default=bytes)
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
    is_active = models.BooleanField(default=True, help_text='Mark this as the active template used for generation.')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_active', '-updated_at']
        verbose_name = 'Requisition template'
        verbose_name_plural = 'Requisition templates'

    def __str__(self):
        return f"{self.name} ({'Active' if self.is_active else 'Inactive'})"


