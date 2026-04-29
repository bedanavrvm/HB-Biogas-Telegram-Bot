"""
Database models for the biogas telegram bot system.
Provides full traceability and deduplication support.
"""
import uuid
from django.db import models
from django.utils import timezone


class RawMessage(models.Model):
    """
    Stores original message data for traceability.
    Never modified after creation - audit trail guarantee.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    telegram_message_id = models.CharField(max_length=255, db_index=True)
    sender = models.CharField(max_length=255, blank=True, default='')
    content = models.TextField()
    received_at = models.DateTimeField(default=timezone.now)
    has_image = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-received_at']
        indexes = [
            models.Index(fields=['telegram_message_id', 'received_at']),
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
    message_id = models.CharField(max_length=128, unique=True, db_index=True)
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
    
    # Google Sheets sync tracking
    synced_to_sheets = models.BooleanField(default=False)
    synced_at = models.DateTimeField(null=True, blank=True)
    sync_attempts = models.IntegerField(default=0)
    last_sync_error = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['message_id']),
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
        [6]  JBL Reported By (bot writes - uses Telegram Bot)
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
            self.customer_phone,                                                          # [5] Phone Number
            'Telegram Bot',                                                               # [6] Reported By (bot name)
            self.branch_region,                                                           # [7] Branch / Region
            self.complaint_category,                                                      # [8] Complaint Category
            self.complaint_description,                                                   # [9] Complaint Description
            self.raw_message,                                                             # [10] raw_message
            self.gps_link,                                                                # [11] gps_link
            'TRUE' if self.image_flag else '',                                            # [12] image_flag
            'telegram bot',                                                               # [13] source
            self.loan_status,                                                             # [14] Loan Status
            self.loan_at_risk,                                                            # [15] Loan at Risk
            self.risk_level,                                                              # [16] Risk Level
            self.complaint_status,                                                        # [17] Status
            self.resolution_details,                                                      # [18] Resolution Details
            self._format_sheet_date(self.date_resolved),                                # [19] Date Resolved
            str(self.days_open) if self.days_open is not None else '',                   # [20] Days Open
        ]
