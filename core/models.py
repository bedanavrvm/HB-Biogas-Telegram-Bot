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
