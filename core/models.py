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
    source = models.CharField(max_length=50, default='whatsapp_telegram')
    
    customer_name = models.CharField(max_length=255, blank=True, default='')
    customer_phone = models.CharField(max_length=255, blank=True, default='')
    customer_id = models.CharField(max_length=255, blank=True, default='')
    complaint_category = models.CharField(max_length=255, blank=True, default='')
    complaint_description = models.TextField(blank=True, default='')
    complaint_status = models.CharField(max_length=255, blank=True, default='')
    resolution_details = models.TextField(blank=True, default='')
    date_resolved = models.DateTimeField(null=True, blank=True)
    days_open = models.IntegerField(null=True, blank=True)
    risk_level = models.CharField(max_length=100, blank=True, default='')
    
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

    def to_sheet_row(self):
        """
        Convert to Google Sheet row format.
        Must match the fixed schema exactly.
        """
        return [
            self.message_id,
            self.timestamp.strftime('%Y-%m-%d %H:%M:%S') if self.timestamp else '',
            self.customer_name,
            self.customer_id,
            self.customer_phone,
            self.sender,
            '',  # branch_region not yet parsed
            self.complaint_category,
            self.complaint_description,
            '',  # loan_status
            '',  # loan_at_risk
            self.complaint_status,
            self.resolution_details,
            self.date_resolved.strftime('%Y-%m-%d %H:%M:%S') if self.date_resolved else '',
            str(self.days_open) if self.days_open is not None else '',
            self.risk_level,
            self.message_id,  # Internal Message ID (duplicate for backend)
            self.timestamp.strftime('%Y-%m-%d %H:%M:%S') if self.timestamp else '',  # Parsed Timestamp (duplicate for backend)
        ]
