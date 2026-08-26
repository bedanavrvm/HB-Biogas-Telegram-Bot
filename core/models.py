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


WORKFLOW_DATA_MODE_PILOT = 'pilot'
WORKFLOW_DATA_MODE_PRODUCTION = 'production'
WORKFLOW_DATA_MODE_CHOICES = [
    (WORKFLOW_DATA_MODE_PILOT, 'Pilot'),
    (WORKFLOW_DATA_MODE_PRODUCTION, 'Production'),
]


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


class ComplaintCategory(models.Model):
    """Governed, reusable complaint category and its default service target."""

    PRIORITY_CHOICES = [('high', 'High'), ('normal', 'Normal'), ('low', 'Low')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.SlugField(max_length=80, unique=True)
    label = models.CharField(max_length=160)
    description = models.TextField(blank=True, default='')
    default_priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='normal')
    default_sla_hours = models.PositiveIntegerField(default=72)
    active = models.BooleanField(default=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['label']
        verbose_name_plural = 'Complaint categories'
        constraints = [
            models.UniqueConstraint(Lower('label'), name='unique_complaint_category_label_ci'),
            models.CheckConstraint(
                condition=models.Q(default_sla_hours__gt=0), name='complaint_category_sla_positive',
            ),
        ]

    def save(self, *args, **kwargs):
        self.label = ' '.join(str(self.label or '').split())
        if not self._state.adding:
            old_key = type(self).objects.filter(pk=self.pk).values_list('key', flat=True).first()
            if old_key and old_key != self.key:
                raise ValidationError({'key': 'The canonical category key is immutable.'})
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.label


class ComplaintCategoryAlias(models.Model):
    """Legacy label resolved to one canonical complaint category."""

    category = models.ForeignKey(ComplaintCategory, on_delete=models.PROTECT, related_name='aliases')
    alias = models.CharField(max_length=160)
    normalized_alias = models.CharField(max_length=180, unique=True, editable=False)
    active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['alias']
        verbose_name_plural = 'Complaint category aliases'

    def save(self, *args, **kwargs):
        self.alias = ' '.join(str(self.alias or '').split())
        self.normalized_alias = re.sub(r'[^a-z0-9]+', ' ', self.alias.casefold()).strip()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.alias} -> {self.category}'


class ComplaintCategoryAvailability(models.Model):
    """Optional category restriction to a configured Telegram workflow group."""

    category = models.ForeignKey(ComplaintCategory, on_delete=models.CASCADE, related_name='availability')
    group_configuration = models.ForeignKey(
        'GroupSheetConfiguration', on_delete=models.CASCADE, related_name='complaint_category_availability',
    )
    active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'Complaint category availability'
        constraints = [
            models.UniqueConstraint(
                fields=['category', 'group_configuration'], name='unique_complaint_category_group',
            ),
        ]


class ComplaintCaseControl(models.Model):
    """Operational control plane layered over immutable complaint source data."""

    PRIORITY_CHOICES = ComplaintCategory.PRIORITY_CHOICES
    MATCH_CHOICES = [
        ('exact_id', 'Exact national ID'), ('exact_phone', 'Exact phone'),
        ('ambiguous', 'Ambiguous'), ('conflict', 'Conflicting identifiers'), ('unmatched', 'Unmatched'),
    ]
    SYNC_CHOICES = [('pending', 'Pending'), ('success', 'Synced'), ('failed', 'Failed')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    parsed_message = models.OneToOneField(
        ParsedMessage, on_delete=models.CASCADE, related_name='complaint_control',
    )
    category = models.ForeignKey(
        ComplaintCategory, null=True, blank=True, on_delete=models.PROTECT, related_name='cases',
    )
    branch_ref = models.ForeignKey(
        'OperationalLocation', null=True, blank=True, on_delete=models.PROTECT,
        related_name='complaint_cases', limit_choices_to={'location_type': 'branch'},
    )
    customer = models.ForeignKey(
        'JawabuCustomer', null=True, blank=True, on_delete=models.SET_NULL, related_name='complaint_cases',
    )
    customer_match_status = models.CharField(max_length=20, choices=MATCH_CHOICES, default='unmatched')
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='assigned_complaint_cases',
    )
    assigned_at = models.DateTimeField(null=True, blank=True)
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='normal', db_index=True)
    sla_target_hours = models.PositiveIntegerField(default=72)
    sla_started_at = models.DateTimeField(default=timezone.now)
    sla_due_at = models.DateTimeField(null=True, blank=True, db_index=True)
    revision = models.PositiveIntegerField(default=1)
    sync_status = models.CharField(max_length=20, choices=SYNC_CHOICES, default='pending', db_index=True)
    sync_error = models.TextField(blank=True, default='')
    last_sync_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-sla_due_at']
        indexes = [
            models.Index(fields=['assigned_to', 'priority']),
            models.Index(fields=['sync_status', 'updated_at']),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(revision__gt=0), name='complaint_case_revision_positive'),
            models.CheckConstraint(
                condition=models.Q(sla_target_hours__gt=0), name='complaint_case_sla_positive',
            ),
        ]

    def __str__(self):
        return f'{self.parsed_message.message_id} control r{self.revision}'


class ComplaintCaseEvent(models.Model):
    """Append-only evidence of every governed complaint-case change."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(ComplaintCaseControl, on_delete=models.PROTECT, related_name='events')
    revision = models.PositiveIntegerField()
    action = models.CharField(max_length=80, db_index=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    actor_label = models.CharField(max_length=255, blank=True, default='')
    request_id = models.CharField(max_length=128, blank=True, default='', db_index=True)
    payload_hash = models.CharField(max_length=64, blank=True, default='', db_index=True)
    before_values = models.JSONField(blank=True, default=dict)
    after_values = models.JSONField(blank=True, default=dict)
    reason = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['case', 'request_id'], condition=~models.Q(request_id=''),
                name='unique_complaint_case_event_request',
            ),
        ]
        indexes = [models.Index(fields=['case', 'revision'])]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Complaint case events are append-only.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Complaint case events cannot be deleted.')


class ComplaintCaseImportBatch(models.Model):
    """Auditable source record for one Superuser-initiated complaint import."""

    STATUS_PROCESSING = 'processing'
    STATUS_COMPLETE = 'complete'
    STATUS_PARTIAL = 'partial'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_PROCESSING, 'Processing'),
        (STATUS_COMPLETE, 'Complete'),
        (STATUS_PARTIAL, 'Partial'),
        (STATUS_FAILED, 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group_id = models.CharField(max_length=100, db_index=True)
    source_telegram_message_id = models.CharField(max_length=255)
    initiated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='complaint_case_import_batches',
    )
    actor_label = models.CharField(max_length=255, blank=True, default='')
    telegram_user_id_snapshot = models.CharField(max_length=64, blank=True, default='')
    source_hash = models.CharField(max_length=64, db_index=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PROCESSING, db_index=True)
    source_count = models.PositiveIntegerField(default=0)
    created_count = models.PositiveIntegerField(default=0)
    matched_count = models.PositiveIntegerField(default=0)
    rejected_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(
            fields=['group_id', 'source_telegram_message_id'],
            name='unique_complaint_import_source_message',
        )]
        verbose_name = 'Complaint case import batch'
        verbose_name_plural = 'Complaint case import batches'


class ComplaintCaseImportItem(models.Model):
    """Immutable attribution link from an imported complaint to its batch."""

    batch = models.ForeignKey(
        ComplaintCaseImportBatch, on_delete=models.PROTECT, related_name='items',
    )
    parsed_message = models.OneToOneField(
        ParsedMessage, on_delete=models.PROTECT, related_name='complaint_import_item',
    )
    source_index = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['source_index']
        constraints = [models.UniqueConstraint(
            fields=['batch', 'source_index'], name='unique_complaint_import_source_index',
        )]
        verbose_name = 'Complaint case import item'
        verbose_name_plural = 'Complaint case import items'


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
    branch_ref = models.ForeignKey(
        'OperationalLocation', null=True, blank=True, on_delete=models.PROTECT,
        limit_choices_to={'location_type': 'branch'}, related_name='order_approval_branch_updates',
    )
    county_ref = models.ForeignKey(
        'OperationalLocation', null=True, blank=True, on_delete=models.PROTECT,
        limit_choices_to={'location_type': 'county'}, related_name='order_approval_county_updates',
    )
    sub_county_ref = models.ForeignKey(
        'OperationalLocation', null=True, blank=True, on_delete=models.PROTECT,
        limit_choices_to={'location_type': 'sub_county'}, related_name='order_approval_sub_county_updates',
    )
    location_snapshot = models.JSONField(blank=True, default=dict)
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
    data_mode = models.CharField(
        max_length=16, choices=WORKFLOW_DATA_MODE_CHOICES,
        default=WORKFLOW_DATA_MODE_PILOT, db_index=True, editable=False,
    )
    pilot_cycle_id = models.UUIDField(null=True, blank=True, db_index=True, editable=False)
    data_scope_key = models.CharField(max_length=64, default='pilot:legacy', db_index=True, editable=False)
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
    product = models.ForeignKey(
        'Product', null=True, blank=True, on_delete=models.PROTECT,
        related_name='spin_credit_requests',
    )
    product_version = models.ForeignKey(
        'ProductVersion', null=True, blank=True, on_delete=models.PROTECT,
        related_name='spin_credit_requests',
    )
    product_terms_snapshot = models.JSONField(default=dict, blank=True)
    product_quote_snapshot = models.JSONField(default=dict, blank=True)
    product_requirement_evidence = models.JSONField(default=dict, blank=True)
    product_custom_values = models.JSONField(default=dict, blank=True)
    product_selected_fee_keys = models.JSONField(default=list, blank=True)
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
            models.Index(fields=['data_mode', 'pilot_cycle_id', 'created_at']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['group_id', 'source_message_hash', 'data_scope_key'],
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

    def save(self, *args, **kwargs):
        if self._state.adding and not self.pilot_cycle_id and self.data_scope_key == 'pilot:legacy':
            from core.services.workflow_data_mode import WORKFLOW_SPIN, mode_snapshot
            snapshot = mode_snapshot(WORKFLOW_SPIN)
            for field, value in snapshot.creation_fields().items():
                setattr(self, field, value)
        from core.services.product_catalog import (
            active_product_version, resolve_product, serialize_product_version,
            stage_product_mapping_issue,
        )
        if self.product_id:
            self.loan_product = self.product.name
        elif self.loan_product:
            self.product = resolve_product(self.loan_product)
        if self.product_id and not self.product_version_id:
            self.product_version = active_product_version(self.product)
        if self.product_version_id and not self.product_terms_snapshot:
            self.product_terms_snapshot = serialize_product_version(self.product_version)
        update_fields = kwargs.get('update_fields')
        if update_fields is not None:
            kwargs['update_fields'] = set(update_fields) | {
                'loan_product', 'product', 'product_version', 'product_terms_snapshot',
            }
        result = super().save(*args, **kwargs)
        if self.loan_product and not self.product_id:
            stage_product_mapping_issue(
                self.loan_product, workflow='spin_credit_analysis',
                source_model=type(self).__name__, source_record_id=self.pk,
            )
        return result


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
    data_mode = models.CharField(
        max_length=16, choices=WORKFLOW_DATA_MODE_CHOICES,
        default=WORKFLOW_DATA_MODE_PILOT, db_index=True, editable=False,
    )
    pilot_cycle_id = models.UUIDField(null=True, blank=True, db_index=True, editable=False)
    data_scope_key = models.CharField(max_length=64, default='pilot:legacy', db_index=True, editable=False)
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
                fields=['group_id', 'source_message_hash', 'data_scope_key'],
                name='unique_spin_batch_review_source_per_group',
            ),
        ]
        indexes = [
            models.Index(fields=['group_id', 'status', 'created_at']),
            models.Index(fields=['group_id', 'category', 'status']),
            models.Index(fields=['data_mode', 'pilot_cycle_id', 'created_at']),
        ]

    def __str__(self):
        return f"{self.get_category_display()} {self.group_id} #{self.source_message_index or 0}"

    def save(self, *args, **kwargs):
        if self._state.adding and not self.pilot_cycle_id and self.data_scope_key == 'pilot:legacy':
            from core.services.workflow_data_mode import WORKFLOW_SPIN, mode_snapshot
            snapshot = mode_snapshot(WORKFLOW_SPIN)
            for field, value in snapshot.creation_fields().items():
                setattr(self, field, value)
        return super().save(*args, **kwargs)


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
    data_mode = models.CharField(
        max_length=16, choices=WORKFLOW_DATA_MODE_CHOICES,
        default=WORKFLOW_DATA_MODE_PILOT, db_index=True, editable=False,
    )
    pilot_cycle_id = models.UUIDField(null=True, blank=True, db_index=True, editable=False)
    data_scope_key = models.CharField(max_length=64, default='pilot:legacy', db_index=True, editable=False)
    group_id = models.CharField(max_length=100, db_index=True)
    sheet_id = models.CharField(max_length=255, blank=True, default='', db_index=True)
    sheet_name = models.CharField(max_length=255, blank=True, default='', db_index=True)
    row_number = models.PositiveIntegerField(null=True, blank=True)
    create_request_id = models.CharField(max_length=128, blank=True, default='', db_index=True)

    case_id = models.CharField(max_length=128, db_index=True)
    product_key = models.CharField(max_length=80, db_index=True)
    product_label = models.CharField(max_length=120, blank=True, default='')
    product = models.ForeignKey(
        'Product', null=True, blank=True, on_delete=models.PROTECT,
        related_name='tat_cases',
    )
    product_version = models.ForeignKey(
        'ProductVersion', null=True, blank=True, on_delete=models.PROTECT,
        related_name='tat_cases',
    )
    product_terms_snapshot = models.JSONField(default=dict, blank=True)
    product_quote_snapshot = models.JSONField(default=dict, blank=True)
    product_requirement_evidence = models.JSONField(default=dict, blank=True)
    product_custom_values = models.JSONField(default=dict, blank=True)
    product_selected_fee_keys = models.JSONField(default=list, blank=True)
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
                fields=['group_id', 'create_request_id', 'data_scope_key'],
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
            models.Index(fields=['data_mode', 'pilot_cycle_id', 'created_at']),
        ]
        verbose_name = 'TAT tracker case'
        verbose_name_plural = 'TAT tracker cases'

    def __str__(self):
        return f"{self.case_id} - {self.client_name}"

    def save(self, *args, **kwargs):
        if self._state.adding and not self.pilot_cycle_id and self.data_scope_key == 'pilot:legacy':
            from core.services.workflow_data_mode import WORKFLOW_TAT, mode_snapshot
            snapshot = mode_snapshot(WORKFLOW_TAT)
            for field, value in snapshot.creation_fields().items():
                setattr(self, field, value)
        return super().save(*args, **kwargs)


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


class TatResponsibilityAssignment(models.Model):
    """Operational TAT owner for one scoped role, without granting access."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    group_configuration = models.ForeignKey(
        'GroupSheetConfiguration', on_delete=models.CASCADE,
        related_name='tat_responsibility_assignments',
    )
    branch = models.CharField(max_length=120, db_index=True)
    role = models.CharField(max_length=80, db_index=True)
    product_key = models.CharField(max_length=80, blank=True, default='', db_index=True)
    stage_key = models.CharField(max_length=120, blank=True, default='', db_index=True)
    primary_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='primary_tat_responsibilities',
    )
    active = models.BooleanField(default=True, db_index=True)
    effective_from = models.DateTimeField(default=timezone.now, db_index=True)
    effective_until = models.DateTimeField(null=True, blank=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='created_tat_responsibilities',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['group_configuration', 'branch', 'role', '-stage_key', '-product_key']
        constraints = [
            models.UniqueConstraint(
                fields=['group_configuration', 'branch', 'role', 'product_key', 'stage_key'],
                condition=models.Q(active=True), name='unique_active_tat_responsibility',
            ),
        ]
        indexes = [models.Index(fields=['group_configuration', 'branch', 'role', 'active'])]
        verbose_name = 'TAT responsibility assignment'
        verbose_name_plural = 'TAT responsibility assignments'

    def clean(self):
        super().clean()
        self.branch = str(self.branch or '').strip()
        self.role = str(self.role or '').strip().upper()
        self.product_key = str(self.product_key or '').strip().lower()
        self.stage_key = str(self.stage_key or '').strip()
        if not self.branch:
            raise ValidationError({'branch': 'Choose the branch this responsibility covers.'})
        if not self.role:
            raise ValidationError({'role': 'Choose the responsible TAT role.'})
        if self.stage_key and self.group_configuration_id:
            from core.services.tat_responsibilities import canonical_stage_role

            # Stage policy, not this routing row, owns the responsible role.
            # Derive it before validating the selected users so a stale or
            # manipulated Admin payload cannot create a contradictory route.
            self.role = canonical_stage_role(
                stage_key=self.stage_key,
                product_key=self.product_key,
                workflow=self.group_configuration.workflow,
            )
        if self.effective_until and self.effective_until <= self.effective_from:
            raise ValidationError({'effective_until': 'The end time must be after the start time.'})
        if self.primary_user_id:
            grants = self.primary_user.access_grants.filter(
                workflow='tat_tracker', role__iexact=self.role, active=True,
            ).filter(
                models.Q(group_configuration__isnull=True)
                | models.Q(group_configuration=self.group_configuration)
            )
            valid = any(
                (not grant.branch or grant.branch.casefold() == self.branch.casefold())
                and (not grant.product or grant.product.casefold() == self.product_key.casefold())
                for grant in grants
            )
            if not valid:
                raise ValidationError({
                    'primary_user': 'The primary actor needs a matching active TAT AccessGrant for this role and scope.',
                })

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        scope = '/'.join(part for part in [self.branch, self.product_key, self.stage_key] if part)
        return f'{scope}: {self.role} -> {self.primary_user}'


class TatResponsibilityBackup(models.Model):
    """Ordered, SLA-triggered backup for a responsibility assignment."""

    assignment = models.ForeignKey(
        TatResponsibilityAssignment, on_delete=models.CASCADE, related_name='backups',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='backup_tat_responsibilities',
    )
    rank = models.PositiveSmallIntegerField(default=1)
    threshold_percent = models.PositiveSmallIntegerField(
        default=100,
        help_text='Existing SLA percentage at which this backup receives a private alert.',
    )
    active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['rank', 'created_at']
        constraints = [
            models.UniqueConstraint(fields=['assignment', 'rank'], name='unique_tat_backup_rank'),
            models.UniqueConstraint(fields=['assignment', 'user'], name='unique_tat_backup_user'),
            models.CheckConstraint(condition=models.Q(rank__gte=1), name='tat_backup_rank_positive'),
            models.CheckConstraint(condition=models.Q(threshold_percent__gte=1), name='tat_backup_threshold_positive'),
        ]
        verbose_name = 'TAT responsibility backup'
        verbose_name_plural = 'TAT responsibility backups'

    def clean(self):
        super().clean()
        if self.assignment_id and self.user_id == self.assignment.primary_user_id:
            raise ValidationError({'user': 'The primary actor cannot also be a backup.'})
        if self.assignment_id and self.user_id:
            assignment = self.assignment
            grants = self.user.access_grants.filter(
                workflow='tat_tracker', role__iexact=assignment.role, active=True,
            ).filter(
                models.Q(group_configuration__isnull=True)
                | models.Q(group_configuration=assignment.group_configuration)
            )
            valid = any(
                (not grant.branch or grant.branch.casefold() == assignment.branch.casefold())
                and (not grant.product or grant.product.casefold() == assignment.product_key.casefold())
                for grant in grants
            )
            if not valid:
                raise ValidationError({'user': 'This backup needs a matching active TAT AccessGrant.'})
        if self.assignment_id:
            assignment = self.assignment
            if not TatEscalationRule.objects.filter(
                group_configuration=assignment.group_configuration,
                active=True,
                threshold_percent=self.threshold_percent,
            ).filter(models.Q(branch='') | models.Q(branch__iexact=assignment.branch)).exists():
                raise ValidationError({
                    'threshold_percent': 'Choose a percentage from an active TAT escalation rule for this branch.',
                })
            earlier = type(self).objects.filter(
                assignment=self.assignment, active=True, rank__lt=self.rank,
                threshold_percent__gte=self.threshold_percent,
            )
            later = type(self).objects.filter(
                assignment=self.assignment, active=True, rank__gt=self.rank,
                threshold_percent__lte=self.threshold_percent,
            )
            if self.pk:
                earlier = earlier.exclude(pk=self.pk)
                later = later.exclude(pk=self.pk)
            if earlier.exists() or later.exists():
                raise ValidationError({'threshold_percent': 'Each later backup must use a strictly later SLA threshold.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class TatResponsibilityEvent(models.Model):
    """Append-only evidence for changes to TAT operational ownership."""

    ACTION_CREATED = 'created'
    ACTION_UPDATED = 'updated'
    ACTION_DELETED = 'deleted'
    ACTION_MIGRATION_REVIEW = 'migration_review'
    ACTION_CHOICES = [
        (ACTION_CREATED, 'Created'),
        (ACTION_UPDATED, 'Updated'),
        (ACTION_DELETED, 'Deleted'),
        (ACTION_MIGRATION_REVIEW, 'Disabled for migration review'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    assignment = models.ForeignKey(
        TatResponsibilityAssignment, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='events',
    )
    assignment_id_snapshot = models.UUIDField(db_index=True)
    action = models.CharField(max_length=32, choices=ACTION_CHOICES, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='tat_responsibility_events',
    )
    reason = models.TextField(blank=True, default='')
    before_snapshot = models.JSONField(default=dict, blank=True)
    after_snapshot = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(
            fields=['assignment_id_snapshot', 'created_at'],
            name='tat_resp_evt_assign_idx',
        )]
        verbose_name = 'TAT responsibility event'
        verbose_name_plural = 'TAT responsibility events'


class TatPrivateAlertConnection(models.Model):
    """TAT-only knowledge of whether Telegram can privately reach a user."""

    STATUS_UNKNOWN = 'unknown'
    STATUS_CONNECTED = 'connected'
    STATUS_UNCONNECTED = 'unconnected'
    STATUS_BLOCKED = 'blocked'
    STATUS_TEMPORARY_FAILURE = 'temporary_failure'
    STATUS_CHOICES = [
        (STATUS_UNKNOWN, 'Unknown'),
        (STATUS_CONNECTED, 'Connected'),
        (STATUS_UNCONNECTED, 'Never connected'),
        (STATUS_BLOCKED, 'Bot blocked or permission withdrawn'),
        (STATUS_TEMPORARY_FAILURE, 'Temporarily failing'),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='tat_private_alert_connection',
    )
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_UNKNOWN, db_index=True)
    connected_at = models.DateTimeField(null=True, blank=True)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_failure_at = models.DateTimeField(null=True, blank=True)
    last_failure_code = models.CharField(max_length=80, blank=True, default='')
    last_connect_request_id = models.CharField(max_length=128, blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'TAT private alert connection'
        verbose_name_plural = 'TAT private alert connections'


class TatActionTask(models.Model):
    """Durable, revision-bound inbox task for the next TAT stage."""

    STATUS_PENDING = 'pending'
    STATUS_ACTED = 'acted'
    STATUS_SUPERSEDED = 'superseded'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'), (STATUS_ACTED, 'Acted'),
        (STATUS_SUPERSEDED, 'Superseded'), (STATUS_CANCELLED, 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    case = models.ForeignKey(TatTrackerCase, on_delete=models.CASCADE, related_name='action_tasks')
    group_configuration = models.ForeignKey(
        'GroupSheetConfiguration', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='tat_action_tasks',
    )
    assignment = models.ForeignKey(
        TatResponsibilityAssignment, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='tasks',
    )
    stage_key = models.CharField(max_length=120, db_index=True)
    stage_label = models.CharField(max_length=160)
    responsible_role = models.CharField(max_length=80, db_index=True)
    case_revision = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    recipient_snapshot = models.JSONField(default=dict, blank=True)
    acted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='acted_tat_tasks',
    )
    acted_at = models.DateTimeField(null=True, blank=True)
    superseded_by = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL, related_name='supersedes',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['case', 'stage_key', 'case_revision'],
                name='unique_tat_task_case_stage_revision',
            ),
        ]
        indexes = [
            models.Index(fields=['case', 'status', 'created_at']),
            models.Index(fields=['group_configuration', 'responsible_role', 'status']),
        ]
        verbose_name = 'TAT action task'
        verbose_name_plural = 'TAT action tasks'

    def __str__(self):
        return f'{self.case.case_id}: {self.stage_label}'


class TatActionTaskLocator(models.Model):
    """Hash-only record for an issued task deep link; raw tokens are never stored."""

    task = models.ForeignKey(TatActionTask, on_delete=models.CASCADE, related_name='locators')
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE,
        related_name='tat_task_locators',
    )
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    revoked_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=['task', 'recipient', 'expires_at'])]
        verbose_name = 'TAT task locator'
        verbose_name_plural = 'TAT task locators'


class TatActionTaskRecipient(models.Model):
    """Per-user inbox and private-delivery state for one TAT task."""

    KIND_PRIMARY = 'primary'
    KIND_BACKUP = 'backup'
    KIND_ROLE = 'role'
    KIND_CHOICES = [(KIND_PRIMARY, 'Primary'), (KIND_BACKUP, 'Backup'), (KIND_ROLE, 'Role member')]
    INBOX_UNREAD = 'unread'
    INBOX_READ = 'read'
    INBOX_ACTED = 'acted'
    INBOX_SUPERSEDED = 'superseded'
    INBOX_CHOICES = [
        (INBOX_UNREAD, 'Unread'), (INBOX_READ, 'Read'),
        (INBOX_ACTED, 'Acted'), (INBOX_SUPERSEDED, 'Superseded'),
    ]
    DELIVERY_PENDING = 'pending'
    DELIVERY_SHADOW = 'shadow'
    DELIVERY_DELIVERED = 'delivered'
    DELIVERY_UNREACHABLE = 'unreachable'
    DELIVERY_RETRY = 'retry'
    DELIVERY_SKIPPED = 'skipped'
    DELIVERY_CHOICES = [
        (DELIVERY_PENDING, 'Pending'), (DELIVERY_SHADOW, 'Shadow'),
        (DELIVERY_DELIVERED, 'Delivered'), (DELIVERY_UNREACHABLE, 'Unreachable'),
        (DELIVERY_RETRY, 'Retry'), (DELIVERY_SKIPPED, 'Skipped'),
    ]

    task = models.ForeignKey(TatActionTask, on_delete=models.CASCADE, related_name='recipients')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='tat_action_task_recipients',
    )
    kind = models.CharField(max_length=16, choices=KIND_CHOICES)
    rank = models.PositiveSmallIntegerField(default=0)
    threshold_percent = models.PositiveSmallIntegerField(null=True, blank=True)
    inbox_status = models.CharField(max_length=16, choices=INBOX_CHOICES, default=INBOX_UNREAD, db_index=True)
    delivery_state = models.CharField(max_length=16, choices=DELIVERY_CHOICES, default=DELIVERY_PENDING, db_index=True)
    deliver_after = models.DateTimeField(null=True, blank=True, db_index=True)
    delivery_attempts = models.PositiveSmallIntegerField(default=0)
    telegram_message_id = models.CharField(max_length=100, blank=True, default='')
    delivery_error = models.CharField(max_length=500, blank=True, default='')
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['task', 'rank', 'created_at']
        constraints = [models.UniqueConstraint(fields=['task', 'user'], name='unique_tat_task_recipient')]
        indexes = [models.Index(fields=['user', 'inbox_status', 'created_at'])]
        verbose_name = 'TAT task recipient'
        verbose_name_plural = 'TAT task recipients'


class TatGroupExceptionStatus(models.Model):
    """One cumulative, privacy-safe group notification for unreachable tasks."""

    group_configuration = models.ForeignKey(
        'GroupSheetConfiguration', on_delete=models.CASCADE,
        related_name='tat_group_exception_statuses',
    )
    responsible_role = models.CharField(max_length=80)
    telegram_message_id = models.CharField(max_length=100, blank=True, default='')
    unresolved_count = models.PositiveIntegerField(default=0)
    oldest_task_at = models.DateTimeField(null=True, blank=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=500, blank=True, default='')
    active = models.BooleanField(default=False, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['group_configuration', 'responsible_role'],
                name='unique_tat_group_role_exception',
            ),
        ]
        verbose_name = 'TAT group delivery exception'
        verbose_name_plural = 'TAT group delivery exceptions'


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
    product = models.ForeignKey(
        'Product', null=True, blank=True, on_delete=models.PROTECT,
        related_name='tat_repair_jobs',
    )
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


class TatCaseSequence(models.Model):
    """Durable TAT case counter; purging pilot rows must never reuse a case ID."""

    group_id = models.CharField(max_length=100, db_index=True)
    product_key = models.CharField(max_length=80, db_index=True)
    year = models.PositiveIntegerField(db_index=True)
    next_number = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['group_id', 'product_key', 'year'],
                name='unique_tat_sequence_group_product_year',
            ),
        ]

    def __str__(self):
        return f'{self.group_id} {self.product_key} {self.year}: next {self.next_number}'


class WorkflowDataModeState(models.Model):
    """Singleton switchboard for SPIN/TAT creation modes and active pilot cycles."""

    SINGLETON_PK = 1

    id = models.PositiveSmallIntegerField(primary_key=True, default=SINGLETON_PK, editable=False)
    spin_mode = models.CharField(
        max_length=16, choices=WORKFLOW_DATA_MODE_CHOICES,
        default=WORKFLOW_DATA_MODE_PILOT,
    )
    spin_pilot_cycle_id = models.UUIDField(default=uuid.uuid4, editable=False)
    spin_mode_version = models.PositiveIntegerField(default=1, editable=False)
    tat_mode = models.CharField(
        max_length=16, choices=WORKFLOW_DATA_MODE_CHOICES,
        default=WORKFLOW_DATA_MODE_PILOT,
    )
    tat_pilot_cycle_id = models.UUIDField(default=uuid.uuid4, editable=False)
    tat_mode_version = models.PositiveIntegerField(default=1, editable=False)
    active_spin_purge_id = models.UUIDField(null=True, blank=True, editable=False)
    active_tat_purge_id = models.UUIDField(null=True, blank=True, editable=False)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='workflow_data_mode_updates',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'SPIN/TAT data mode'
        verbose_name_plural = 'SPIN/TAT data modes'

    def save(self, *args, **kwargs):
        self.pk = self.SINGLETON_PK
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('The workflow data-mode switchboard cannot be deleted.')

    def __str__(self):
        return f'SPIN {self.get_spin_mode_display()} / TAT {self.get_tat_mode_display()}'


class WorkflowDataModeEvent(models.Model):
    """Append-only, non-PII evidence for mode, cycle, and purge actions."""

    WORKFLOW_CHOICES = [('spin', 'SPIN'), ('tat_tracker', 'TAT Tracker')]
    ACTION_CHOICES = [
        ('mode_changed', 'Mode changed'),
        ('cycle_rotated', 'Pilot cycle rotated'),
        ('purge_started', 'Pilot purge started'),
        ('purge_completed', 'Pilot purge completed'),
        ('purge_failed', 'Pilot purge failed'),
        ('purge_cancelled', 'Pilot purge cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow = models.CharField(max_length=32, choices=WORKFLOW_CHOICES, db_index=True)
    action = models.CharField(max_length=32, choices=ACTION_CHOICES, db_index=True)
    old_mode = models.CharField(max_length=16, choices=WORKFLOW_DATA_MODE_CHOICES, blank=True, default='')
    new_mode = models.CharField(max_length=16, choices=WORKFLOW_DATA_MODE_CHOICES, blank=True, default='')
    old_cycle_id = models.UUIDField(null=True, blank=True)
    new_cycle_id = models.UUIDField(null=True, blank=True)
    reason = models.TextField()
    request_id = models.CharField(max_length=128, blank=True, default='', db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='workflow_data_mode_events',
    )
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['workflow', 'action', 'request_id'],
                condition=~models.Q(request_id=''),
                name='unique_workflow_mode_event_request',
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Workflow data-mode events are append-only.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Workflow data-mode events are append-only.')

    def __str__(self):
        return f'{self.get_workflow_display()} - {self.get_action_display()}'


class WorkflowPilotFormulaReadiness(models.Model):
    """Superuser acknowledgement that deleting rows is safe for one Sheet layout."""

    WORKFLOW_CHOICES = WorkflowDataModeEvent.WORKFLOW_CHOICES

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    workflow = models.CharField(max_length=32, choices=WORKFLOW_CHOICES, db_index=True)
    group_configuration = models.ForeignKey(
        'GroupSheetConfiguration', null=True, blank=True, on_delete=models.PROTECT,
        related_name='workflow_pilot_formula_readiness',
    )
    sheet_id = models.CharField(max_length=255, db_index=True)
    sheet_tab = models.CharField(max_length=255)
    configuration_fingerprint = models.CharField(max_length=64)
    formula_fingerprint = models.CharField(max_length=64)
    note = models.TextField()
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='acknowledged_workflow_pilot_formula_readiness',
    )
    acknowledged_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['workflow', 'sheet_tab', '-acknowledged_at']
        constraints = [
            models.UniqueConstraint(
                fields=[
                    'workflow', 'sheet_id', 'sheet_tab',
                    'configuration_fingerprint', 'formula_fingerprint',
                ],
                name='unique_workflow_pilot_formula_readiness',
            ),
        ]
        verbose_name = 'pilot purge Sheet readiness'
        verbose_name_plural = 'pilot purge Sheet readiness'


class WorkflowPilotPurgeRun(models.Model):
    """Durable manifest and progress for a resumable, verified pilot purge."""

    SCOPE_CHOICES = [
        ('spin', 'SPIN'), ('tat_tracker', 'TAT Tracker'), ('both', 'SPIN and TAT Tracker'),
    ]
    STATUS_CHOICES = [
        ('pending', 'Pending'), ('running', 'Running'), ('partial', 'Partially completed'),
        ('completed', 'Completed'), ('failed', 'Failed'), ('cancelled', 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    scope = models.CharField(max_length=32, choices=SCOPE_CHOICES, db_index=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default='pending', db_index=True)
    reason = models.TextField()
    request_id = models.CharField(max_length=128, blank=True, default='', db_index=True)
    manifest = models.JSONField(default=dict, blank=True)
    manifest_hash = models.CharField(max_length=64, blank=True, default='', db_index=True)
    progress = models.JSONField(default=dict, blank=True)
    failures = models.JSONField(default=list, blank=True)
    cutoff_at = models.DateTimeField(default=timezone.now)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='requested_workflow_pilot_purges',
    )
    started_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['scope', 'request_id'],
                condition=~models.Q(request_id=''),
                name='unique_workflow_pilot_purge_request',
            ),
        ]
        indexes = [models.Index(fields=['scope', 'status', 'created_at'])]
        verbose_name = 'pilot purge run'
        verbose_name_plural = 'pilot purge runs'

    def __str__(self):
        return f'{self.get_scope_display()} purge {self.id} ({self.status})'


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
    branch_ref = models.ForeignKey(
        'OperationalLocation', null=True, blank=True, on_delete=models.PROTECT,
        limit_choices_to={'location_type': 'branch'}, related_name='jawabu_branch_records',
    )
    county_ref = models.ForeignKey(
        'OperationalLocation', null=True, blank=True, on_delete=models.PROTECT,
        limit_choices_to={'location_type': 'county'}, related_name='jawabu_county_records',
    )
    sub_county_ref = models.ForeignKey(
        'OperationalLocation', null=True, blank=True, on_delete=models.PROTECT,
        limit_choices_to={'location_type': 'sub_county'}, related_name='jawabu_sub_county_records',
    )

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
    product = models.ForeignKey(
        'Product', null=True, blank=True, on_delete=models.PROTECT,
        related_name='jawabu_farmer_records',
    )
    product_version = models.ForeignKey(
        'ProductVersion', null=True, blank=True, on_delete=models.PROTECT,
        related_name='jawabu_farmer_records',
    )
    product_terms_snapshot = models.JSONField(default=dict, blank=True)
    product_quote_snapshot = models.JSONField(default=dict, blank=True)
    product_requirement_evidence = models.JSONField(default=dict, blank=True)
    product_custom_values = models.JSONField(default=dict, blank=True)
    product_selected_fee_keys = models.JSONField(default=list, blank=True)

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

    def save(self, *args, **kwargs):
        from core.services.product_catalog import (
            active_product_version, resolve_product, serialize_product_version,
            stage_product_mapping_issue,
        )
        if self.product_id:
            self.payment_product = self.product.name
        elif self.payment_product:
            self.product = resolve_product(self.payment_product)
        if self.product_id and not self.product_version_id:
            self.product_version = active_product_version(self.product)
        if self.product_version_id and not self.product_terms_snapshot:
            self.product_terms_snapshot = serialize_product_version(self.product_version)
        update_fields = kwargs.get('update_fields')
        if update_fields is not None:
            kwargs['update_fields'] = set(update_fields) | {
                'payment_product', 'product', 'product_version', 'product_terms_snapshot',
            }
        result = super().save(*args, **kwargs)
        if self.payment_product and not self.product_id:
            stage_product_mapping_issue(
                self.payment_product, workflow='jawabu_portal',
                source_model=type(self).__name__, source_record_id=self.pk,
            )
        return result


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
    product_ref = models.ForeignKey(
        'Product', null=True, blank=True, on_delete=models.PROTECT,
        related_name='jawabu_approval_delegations',
    )
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

    def save(self, *args, **kwargs):
        if self.product_ref_id:
            self.product = self.product_ref.code
        elif self.product:
            from core.services.product_catalog import resolve_product
            self.product_ref = resolve_product(self.product)
        return super().save(*args, **kwargs)

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


class JawabuCaseComment(models.Model):
    """Immutable human-authored Portal remark projected to Master Data."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    farmer = models.ForeignKey(
        JawabuFarmerMaster,
        on_delete=models.PROTECT,
        related_name='case_comments',
    )
    pipeline_event = models.ForeignKey(
        JawabuPipelineEvent,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='case_comments',
    )
    stage_key = models.CharField(max_length=40, db_index=True)
    comment = models.TextField()
    actor = models.CharField(max_length=255, blank=True, default='')
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='jawabu_case_comments',
    )
    role_code = models.CharField(max_length=64, blank=True, default='')
    role_label = models.CharField(max_length=128, blank=True, default='')
    request_id = models.CharField(max_length=128, blank=True, default='', db_index=True)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['occurred_at', 'created_at']
        indexes = [
            models.Index(fields=['farmer', 'occurred_at'], name='jawabu_comment_timeline_idx'),
        ]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(comment=''),
                name='jawabu_case_comment_not_empty',
            ),
            models.UniqueConstraint(
                fields=['farmer', 'request_id'],
                condition=~models.Q(request_id=''),
                name='jawabu_unique_comment_request',
            ),
        ]


class PortalMaintenanceState(models.Model):
    """Singleton operational mode for safe, staff-visible Portal maintenance."""

    MODE_LIVE = 'live'
    MODE_MAINTENANCE = 'maintenance'
    MODE_CHOICES = [
        (MODE_LIVE, 'Live'),
        (MODE_MAINTENANCE, 'Under maintenance'),
    ]

    singleton = models.PositiveSmallIntegerField(default=1, unique=True, editable=False)
    mode = models.CharField(max_length=16, choices=MODE_CHOICES, default=MODE_LIVE, db_index=True)
    reason = models.CharField(max_length=500, blank=True, default='')
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='+',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=models.Q(singleton=1), name='portal_maintenance_singleton_one'),
        ]
        verbose_name = 'Portal maintenance state'
        verbose_name_plural = 'Portal maintenance state'

    def __str__(self):
        return self.get_mode_display()


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
    data_mode = models.CharField(
        max_length=16, choices=WORKFLOW_DATA_MODE_CHOICES,
        default=WORKFLOW_DATA_MODE_PRODUCTION, db_index=True,
    )
    pilot_cycle_id = models.UUIDField(null=True, blank=True, db_index=True)
    data_scope_key = models.CharField(max_length=64, default='production', db_index=True)
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
                fields=['workflow', 'subject_id', 'stage_key', 'escalation_date', 'data_scope_key'],
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

    data_mode = models.CharField(
        max_length=16, choices=WORKFLOW_DATA_MODE_CHOICES,
        default=WORKFLOW_DATA_MODE_PRODUCTION, db_index=True,
    )
    pilot_cycle_id = models.UUIDField(null=True, blank=True, db_index=True)
    data_scope_key = models.CharField(max_length=64, default='production', db_index=True)
    metric_date = models.DateField(db_index=True)
    workflow = models.CharField(max_length=40, choices=WORKFLOW_CHOICES, db_index=True)
    group_id = models.CharField(max_length=100, blank=True, default='', db_index=True)
    branch = models.CharField(max_length=128, blank=True, default='', db_index=True)
    product_key = models.CharField(max_length=80, blank=True, default='', db_index=True)
    product = models.ForeignKey(
        'Product', null=True, blank=True, on_delete=models.PROTECT,
        related_name='tat_daily_metrics',
    )
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
                fields=['metric_date', 'workflow', 'group_id', 'branch', 'product_key', 'stage_key', 'responsible_role', 'responsible_actor', 'data_scope_key'],
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


class Product(models.Model):
    """Stable global identity for a financial product used by every workflow."""

    name = models.CharField(max_length=128)
    code = models.CharField(max_length=64, blank=True, default='')
    description = models.TextField(blank=True, default='')
    category = models.CharField(max_length=64, blank=True, default='', db_index=True)
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
        verbose_name = 'Product'
        verbose_name_plural = 'Products'

    def clean(self):
        super().clean()
        self.name = ' '.join(str(self.name or '').split())
        # Access scopes use the stable, lowercase TAT product keys.  Keep an
        # Admin-entered code compatible with that convention rather than
        # creating display-case variants that silently match no scope.
        self.code = re.sub(r'[^a-z0-9]+', '_', str(self.code or '').casefold()).strip('_')
        if not self.name:
            raise ValidationError({'name': 'Enter a product name.'})
        if not self.code:
            raise ValidationError({'code': 'Enter a stable product code.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        if not self._state.adding:
            previous_code = type(self).objects.filter(pk=self.pk).values_list('code', flat=True).first()
            if previous_code is not None and previous_code != self.code:
                raise ValidationError({'code': 'Product code is a stable identity and cannot be changed.'})
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name


# Transitional Python import compatibility. The database model and content type
# are now Product; older modules may continue importing OperationalProduct while
# they move to the global catalogue service.
OperationalProduct = Product


class ProductAlias(models.Model):
    """Approved external/import spelling for one canonical product."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='aliases')
    alias = models.CharField(max_length=160)
    normalized_alias = models.CharField(max_length=160, unique=True, db_index=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['alias']
        verbose_name_plural = 'Product aliases'

    def clean(self):
        super().clean()
        self.alias = ' '.join(str(self.alias or '').split())
        self.normalized_alias = re.sub(r'[^a-z0-9]+', '_', self.alias.casefold()).strip('_')
        if not self.normalized_alias:
            raise ValidationError({'alias': 'Enter a usable product alias.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.alias} → {self.product}'


class ProductVersion(models.Model):
    """Immutable, effective-dated commercial terms for a global product."""

    STATUS_DRAFT = 'draft'
    STATUS_SCHEDULED = 'scheduled'
    STATUS_PUBLISHED = 'published'
    STATUS_RETIRED = 'retired'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_SCHEDULED, 'Scheduled'),
        (STATUS_PUBLISHED, 'Published'),
        (STATUS_RETIRED, 'Retired'),
    ]
    TENOR_WEEK = 'week'
    TENOR_MONTH = 'month'
    TENOR_UNIT_CHOICES = [(TENOR_WEEK, 'Weeks'), (TENOR_MONTH, 'Months')]
    INTEREST_FLAT = 'flat'
    INTEREST_REDUCING = 'reducing'
    INTEREST_METHOD_CHOICES = [
        (INTEREST_FLAT, 'Flat rate'),
        (INTEREST_REDUCING, 'Reducing balance'),
    ]
    RATE_MONTHLY = 'monthly'
    RATE_ANNUAL = 'annual'
    RATE_PERIOD_CHOICES = [(RATE_MONTHLY, 'Monthly'), (RATE_ANNUAL, 'Annual')]
    REPAYMENT_WEEKLY = 'weekly'
    REPAYMENT_FORTNIGHTLY = 'fortnightly'
    REPAYMENT_MONTHLY = 'monthly'
    REPAYMENT_FREQUENCY_CHOICES = [
        (REPAYMENT_WEEKLY, 'Weekly'),
        (REPAYMENT_FORTNIGHTLY, 'Fortnightly'),
        (REPAYMENT_MONTHLY, 'Monthly'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='versions')
    version = models.PositiveIntegerField()
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True)
    currency = models.CharField(max_length=3, default='KES')
    min_amount = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    max_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    min_tenor = models.PositiveSmallIntegerField(default=1)
    max_tenor = models.PositiveSmallIntegerField(default=12)
    tenor_unit = models.CharField(max_length=12, choices=TENOR_UNIT_CHOICES, default=TENOR_MONTH)
    interest_method = models.CharField(
        max_length=16, choices=INTEREST_METHOD_CHOICES, default=INTEREST_FLAT,
    )
    interest_rate = models.DecimalField(max_digits=9, decimal_places=6, default=0)
    interest_rate_period = models.CharField(
        max_length=12, choices=RATE_PERIOD_CHOICES, default=RATE_ANNUAL,
    )
    repayment_frequency = models.CharField(
        max_length=16, choices=REPAYMENT_FREQUENCY_CHOICES, default=REPAYMENT_MONTHLY,
    )
    quote_amount_field_key = models.SlugField(
        max_length=80, default='loan_amount',
        help_text='Origination/workflow variable containing the requested principal.',
    )
    quote_tenor_field_key = models.SlugField(
        max_length=80, default='repayment_tenor',
        help_text='Origination/workflow variable containing the numeric tenor.',
    )
    effective_from = models.DateField(default=timezone.localdate, db_index=True)
    effective_to = models.DateField(null=True, blank=True, db_index=True)
    supersedes = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.PROTECT,
        related_name='superseded_by_versions',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='created_product_versions',
    )
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='published_product_versions',
    )
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['product__sort_order', 'product__name', '-version']
        constraints = [
            models.UniqueConstraint(fields=['product', 'version'], name='unique_global_product_version'),
        ]
        indexes = [models.Index(fields=['product', 'status', 'effective_from'])]

    def clean(self):
        super().clean()
        errors = {}
        self.currency = str(self.currency or '').upper().strip()
        if len(self.currency) != 3:
            errors['currency'] = 'Use a three-letter currency code.'
        if self.min_amount < 0:
            errors['min_amount'] = 'Minimum amount cannot be negative.'
        if self.max_amount is not None and self.max_amount < self.min_amount:
            errors['max_amount'] = 'Maximum amount cannot be below the minimum amount.'
        if self.min_tenor < 1:
            errors['min_tenor'] = 'Minimum tenor must be at least one.'
        if self.max_tenor < self.min_tenor:
            errors['max_tenor'] = 'Maximum tenor cannot be below the minimum tenor.'
        if self.interest_rate < 0:
            errors['interest_rate'] = 'Interest rate cannot be negative.'
        if self.effective_to and self.effective_to < self.effective_from:
            errors['effective_to'] = 'Effective-to date cannot precede effective-from.'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self._state.adding:
            if self.status != self.STATUS_DRAFT and not getattr(self, '_allow_catalog_publication', False):
                raise ValidationError(
                    'New product versions must begin as drafts and be published through the catalogue service.'
                )
        else:
            previous = type(self).objects.filter(pk=self.pk).first()
            if previous:
                immutable_fields = (
                    'product_id', 'version', 'status', 'currency', 'min_amount', 'max_amount',
                    'min_tenor', 'max_tenor', 'tenor_unit', 'interest_method', 'interest_rate',
                    'interest_rate_period', 'repayment_frequency', 'quote_amount_field_key',
                    'quote_tenor_field_key', 'effective_from', 'effective_to', 'supersedes_id',
                )
                changed = [
                    field for field in immutable_fields
                    if getattr(previous, field) != getattr(self, field)
                ]
                if (
                    previous.status != self.STATUS_DRAFT
                    and changed
                    and not getattr(self, '_allow_catalog_publication', False)
                ):
                    raise ValidationError(
                        'Published product versions are immutable. Create the next version instead.'
                    )
                if (
                    previous.status == self.STATUS_DRAFT
                    and self.status != self.STATUS_DRAFT
                    and not getattr(self, '_allow_catalog_publication', False)
                ):
                    raise ValidationError('Publish product versions through the catalogue service.')
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.product.name} v{self.version}'


def _require_draft_product_configuration(product_version: ProductVersion) -> None:
    if product_version.status != ProductVersion.STATUS_DRAFT:
        raise ValidationError(
            'Published product configuration is immutable. Create the next version instead.'
        )


class ProductFee(models.Model):
    TYPE_FIXED = 'fixed'
    TYPE_PERCENTAGE = 'percentage'
    TYPE_CHOICES = [(TYPE_FIXED, 'Fixed amount'), (TYPE_PERCENTAGE, 'Percentage')]
    BASIS_PRINCIPAL = 'principal'
    BASIS_FINANCED = 'financed_principal'
    BASIS_INTEREST = 'interest'
    BASIS_TOTAL = 'principal_interest'
    BASIS_CHOICES = [
        (BASIS_PRINCIPAL, 'Principal'),
        (BASIS_FINANCED, 'Financed principal'),
        (BASIS_INTEREST, 'Interest'),
        (BASIS_TOTAL, 'Principal plus interest'),
    ]
    COLLECTION_UPFRONT = 'upfront'
    COLLECTION_FINANCED = 'financed'
    COLLECTION_CHOICES = [(COLLECTION_UPFRONT, 'Upfront'), (COLLECTION_FINANCED, 'Financed')]

    product_version = models.ForeignKey(ProductVersion, on_delete=models.CASCADE, related_name='fees')
    key = models.SlugField(max_length=80)
    label = models.CharField(max_length=160)
    fee_type = models.CharField(max_length=16, choices=TYPE_CHOICES, default=TYPE_FIXED)
    fixed_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    percentage = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    calculation_basis = models.CharField(max_length=24, choices=BASIS_CHOICES, default=BASIS_PRINCIPAL)
    minimum_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    maximum_amount = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    collection_mode = models.CharField(max_length=16, choices=COLLECTION_CHOICES, default=COLLECTION_UPFRONT)
    mandatory = models.BooleanField(default=True)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['position', 'id']
        constraints = [models.UniqueConstraint(fields=['product_version', 'key'], name='unique_product_fee_key')]

    def clean(self):
        super().clean()
        errors = {}
        if self.fee_type == self.TYPE_FIXED and self.fixed_amount is None:
            errors['fixed_amount'] = 'Enter the fixed fee amount.'
        if self.fee_type == self.TYPE_PERCENTAGE and self.percentage is None:
            errors['percentage'] = 'Enter the fee percentage.'
        if self.fixed_amount is not None and self.fixed_amount < 0:
            errors['fixed_amount'] = 'Fee amount cannot be negative.'
        if self.percentage is not None and self.percentage < 0:
            errors['percentage'] = 'Fee percentage cannot be negative.'
        if self.minimum_amount is not None and self.minimum_amount < 0:
            errors['minimum_amount'] = 'Minimum fee cannot be negative.'
        if self.maximum_amount is not None and self.maximum_amount < 0:
            errors['maximum_amount'] = 'Maximum fee cannot be negative.'
        if self.collection_mode == self.COLLECTION_FINANCED and self.calculation_basis in {self.BASIS_INTEREST, self.BASIS_TOTAL}:
            errors['calculation_basis'] = 'A financed fee must be based on principal to avoid circular calculations.'
        if self.maximum_amount is not None and self.minimum_amount is not None and self.maximum_amount < self.minimum_amount:
            errors['maximum_amount'] = 'Maximum fee cannot be below the minimum fee.'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        _require_draft_product_configuration(self.product_version)
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        _require_draft_product_configuration(self.product_version)
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f'{self.product_version}: {self.label}'


class ProductRequirement(models.Model):
    TYPE_DOCUMENT = 'document'
    TYPE_ELIGIBILITY = 'eligibility'
    TYPE_CHECKBOX = 'checkbox'
    TYPE_AMOUNT = 'amount'
    TYPE_TEXT = 'text'
    TYPE_CHOICES = [
        (TYPE_DOCUMENT, 'Document'),
        (TYPE_ELIGIBILITY, 'Eligibility rule'),
        (TYPE_CHECKBOX, 'Confirmation'),
        (TYPE_AMOUNT, 'Amount evidence'),
        (TYPE_TEXT, 'Text evidence'),
    ]

    product_version = models.ForeignKey(ProductVersion, on_delete=models.CASCADE, related_name='requirements')
    key = models.SlugField(max_length=80)
    label = models.CharField(max_length=160)
    description = models.TextField(blank=True, default='')
    requirement_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    workflow = models.CharField(max_length=40, blank=True, default='', db_index=True)
    enforcement_stage = models.CharField(max_length=80, blank=True, default='', db_index=True)
    required = models.BooleanField(default=True)
    validation_config = models.JSONField(default=dict, blank=True)
    position = models.PositiveSmallIntegerField(default=0)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ['position', 'id']
        constraints = [models.UniqueConstraint(fields=['product_version', 'key'], name='unique_product_requirement_key')]

    def __str__(self):
        return f'{self.product_version}: {self.label}'

    def save(self, *args, **kwargs):
        _require_draft_product_configuration(self.product_version)
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        _require_draft_product_configuration(self.product_version)
        return super().delete(*args, **kwargs)


class ProductCustomAttribute(models.Model):
    TYPE_TEXT = 'text'
    TYPE_NUMBER = 'number'
    TYPE_MONEY = 'money'
    TYPE_DATE = 'date'
    TYPE_BOOLEAN = 'boolean'
    TYPE_CHOICE = 'choice'
    TYPE_CHOICES = [
        (TYPE_TEXT, 'Text'), (TYPE_NUMBER, 'Number'), (TYPE_MONEY, 'Money'),
        (TYPE_DATE, 'Date'), (TYPE_BOOLEAN, 'Yes / No'), (TYPE_CHOICE, 'Choice'),
    ]

    product_version = models.ForeignKey(ProductVersion, on_delete=models.CASCADE, related_name='custom_attributes')
    key = models.SlugField(max_length=80)
    label = models.CharField(max_length=160)
    attribute_type = models.CharField(max_length=16, choices=TYPE_CHOICES)
    required = models.BooleanField(default=False)
    help_text = models.CharField(max_length=500, blank=True, default='')
    options = models.JSONField(default=list, blank=True)
    validation_config = models.JSONField(default=dict, blank=True)
    default_value = models.JSONField(null=True, blank=True)
    workflow_visibility = models.JSONField(default=list, blank=True)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['position', 'id']
        constraints = [models.UniqueConstraint(fields=['product_version', 'key'], name='unique_product_attribute_key')]

    def clean(self):
        super().clean()
        if self.attribute_type == self.TYPE_CHOICE and not [item for item in (self.options or []) if str(item).strip()]:
            raise ValidationError({'options': 'Choice attributes require at least one option.'})
        pattern = (self.validation_config or {}).get('pattern')
        if pattern:
            try:
                re.compile(str(pattern))
            except re.error as exc:
                raise ValidationError({'validation_config': f'Invalid regular expression: {exc}.'}) from exc

    def __str__(self):
        return f'{self.product_version}: {self.label}'

    def save(self, *args, **kwargs):
        _require_draft_product_configuration(self.product_version)
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        _require_draft_product_configuration(self.product_version)
        return super().delete(*args, **kwargs)


class ProductAvailability(models.Model):
    CHANNEL_CHOICES = [
        ('portal', 'Portal'), ('telegram', 'Telegram'), ('admin', 'Django Admin'),
        ('import', 'Imports'), ('api', 'API'),
    ]

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='availability_assignments')
    branch = models.ForeignKey(
        'OperationalLocation', null=True, blank=True, on_delete=models.PROTECT,
        limit_choices_to={'location_type': 'branch'}, related_name='product_availability_assignments',
    )
    workflow = models.CharField(max_length=40, blank=True, default='', db_index=True)
    channel = models.CharField(max_length=16, choices=CHANNEL_CHOICES, blank=True, default='', db_index=True)
    scope_signature = models.CharField(max_length=180, editable=False)
    active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['product__sort_order', 'product__name', 'workflow', 'channel']
        constraints = [models.UniqueConstraint(fields=['product', 'scope_signature'], name='unique_product_availability_scope')]

    def clean(self):
        super().clean()
        if self.branch_id and self.branch.location_type != 'branch':
            raise ValidationError({'branch': 'Product availability can only reference branch locations.'})
        self.scope_signature = f'branch:{self.branch_id or "*"}|workflow:{self.workflow or "*"}|channel:{self.channel or "*"}'

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class ProductTatConfiguration(models.Model):
    """Versioned TAT and Sheet adapter for one product version."""

    product_version = models.OneToOneField(ProductVersion, on_delete=models.CASCADE, related_name='tat_configuration')
    sheet_name = models.CharField(max_length=160)
    case_prefix = models.CharField(max_length=32)
    remarks_col = models.PositiveSmallIntegerField()
    status_col = models.PositiveSmallIntegerField()
    tat_start_col = models.PositiveSmallIntegerField()
    stage_columns = models.JSONField(default=dict)
    stages = models.JSONField(default=list)
    stage_tat_columns = models.JSONField(default=list, blank=True)

    def __str__(self):
        return f'{self.product_version}: TAT configuration'

    def save(self, *args, **kwargs):
        _require_draft_product_configuration(self.product_version)
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        _require_draft_product_configuration(self.product_version)
        return super().delete(*args, **kwargs)


class ProductVersionEvent(models.Model):
    """Append-only product-terms publication and lifecycle evidence."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product_version = models.ForeignKey(ProductVersion, on_delete=models.PROTECT, related_name='events')
    action = models.CharField(max_length=40, db_index=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    metadata = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['occurred_at', 'id']

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Product version events are append-only.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Product version events cannot be deleted.')


class ProductMappingIssue(models.Model):
    STATUS_OPEN = 'open'
    STATUS_RESOLVED = 'resolved'
    STATUS_CHOICES = [(STATUS_OPEN, 'Open'), (STATUS_RESOLVED, 'Resolved')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    raw_value = models.CharField(max_length=255)
    normalized_value = models.CharField(max_length=160, db_index=True)
    source_workflow = models.CharField(max_length=40, db_index=True)
    source_model = models.CharField(max_length=120, blank=True, default='')
    source_record_id = models.CharField(max_length=120, blank=True, default='')
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_OPEN, db_index=True)
    product = models.ForeignKey(Product, null=True, blank=True, on_delete=models.PROTECT, related_name='mapping_issues')
    resolved_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+')
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(
            fields=['normalized_value', 'source_workflow', 'source_model', 'source_record_id'],
            condition=models.Q(status='open'), name='unique_open_product_mapping_issue',
        )]


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
    show_business_hours_time = models.BooleanField(default=True)
    alert_mode = models.CharField(max_length=16, choices=ALERT_CHOICES, default=ALERT_IMMEDIATE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'workflow'], name='unique_user_miniapp_preference')]
        ordering = ['workflow', 'user_id']


class PortalSavedView(models.Model):
    """A private, validated Portal workspace view; never a workflow assignment."""

    ORDER_QUEUE_DEFAULT = 'queue_default'
    ORDER_NEWEST = 'newest'
    ORDERING_CHOICES = [
        (ORDER_QUEUE_DEFAULT, 'Queue default'),
        (ORDER_NEWEST, 'Newest first'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='portal_saved_views',
    )
    name = models.CharField(max_length=60)
    screen = models.CharField(max_length=80)
    queue = models.CharField(max_length=80, blank=True, default='')
    filters = models.JSONField(blank=True, default=dict)
    ordering = models.CharField(max_length=24, choices=ORDERING_CHOICES, default=ORDER_QUEUE_DEFAULT)
    is_startup = models.BooleanField(default=False)
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_startup', '-last_used_at', '-updated_at', 'name']
        constraints = [
            models.UniqueConstraint(
                models.functions.Lower('name'), 'user',
                name='unique_portal_saved_view_name_per_user',
            ),
            models.UniqueConstraint(
                fields=['user'], condition=models.Q(is_startup=True),
                name='unique_portal_saved_startup_view_per_user',
            ),
        ]
        indexes = [models.Index(fields=['user', 'is_startup'])]

    def __str__(self):
        return f'{self.user}: {self.name}'


class PortalCaseWorkspace(models.Model):
    """Private pin/recent metadata retained separately from the customer case."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='portal_case_workspace_items',
    )
    farmer = models.ForeignKey(
        'JawabuFarmerMaster', on_delete=models.CASCADE, related_name='portal_workspace_items',
    )
    pinned = models.BooleanField(default=False)
    pinned_at = models.DateTimeField(null=True, blank=True)
    last_opened_at = models.DateTimeField(null=True, blank=True)
    recent_dismissed_at = models.DateTimeField(null=True, blank=True)
    unavailable_since = models.DateTimeField(null=True, blank=True)
    last_open_key = models.CharField(max_length=64, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-pinned', '-pinned_at', '-last_opened_at']
        constraints = [
            models.UniqueConstraint(fields=['user', 'farmer'], name='unique_portal_case_workspace_per_user'),
        ]
        indexes = [
            models.Index(fields=['user', 'pinned', 'unavailable_since']),
            models.Index(fields=['user', 'last_opened_at']),
        ]

    def __str__(self):
        return f'{self.user}: {self.farmer}'


class PortalReportDefinition(models.Model):
    """An IT-owned, validated definition for a read-only Portal report.

    The JSON configuration contains only keys from the server-owned Portal
    reporting catalogue.  It intentionally never stores arbitrary ORM paths,
    SQL, source data, Drive links, or customer snapshots.
    """

    SOURCE_PORTAL_CASES = 'portal_cases'
    SOURCE_CHOICES = [
        (SOURCE_PORTAL_CASES, 'Portal customer cases'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=100)
    source_key = models.CharField(max_length=40, choices=SOURCE_CHOICES, default=SOURCE_PORTAL_CASES)
    configuration = models.JSONField(default=dict, blank=True)
    version = models.PositiveIntegerField(default=1)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='created_portal_report_definitions',
    )
    archived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name='archived_portal_report_definitions',
    )
    archived_at = models.DateTimeField(null=True, blank=True, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    create_request_id = models.CharField(max_length=128, blank=True, default='', db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_active', 'title']
        indexes = [
            models.Index(fields=['is_active', 'title']),
            models.Index(fields=['created_by', 'created_at']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['create_request_id'],
                condition=~models.Q(create_request_id=''),
                name='unique_portal_report_create_request',
            ),
        ]
        verbose_name = 'Portal report definition'
        verbose_name_plural = 'Portal report definitions'

    def __str__(self):
        return f'{self.title} (v{self.version})'


class PortalReportChart(models.Model):
    """A constrained chart attached to a Portal report definition."""

    TYPE_BAR = 'bar'
    TYPE_DOUGHNUT = 'doughnut'
    TYPE_LINE = 'line'
    TYPE_CHOICES = [
        (TYPE_BAR, 'Bar chart'),
        (TYPE_DOUGHNUT, 'Doughnut chart'),
        (TYPE_LINE, 'Line chart'),
    ]
    AGGREGATE_COUNT = 'count'
    AGGREGATE_SUM = 'sum'
    AGGREGATE_AVERAGE = 'average'
    AGGREGATE_CHOICES = [
        (AGGREGATE_COUNT, 'Count cases'),
        (AGGREGATE_SUM, 'Sum'),
        (AGGREGATE_AVERAGE, 'Average'),
    ]
    BUCKET_NONE = ''
    BUCKET_DAY = 'day'
    BUCKET_MONTH = 'month'
    DATE_BUCKET_CHOICES = [
        (BUCKET_NONE, 'No date bucket'),
        (BUCKET_DAY, 'Day'),
        (BUCKET_MONTH, 'Month'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    definition = models.ForeignKey(
        PortalReportDefinition, on_delete=models.CASCADE, related_name='charts',
    )
    title = models.CharField(max_length=100, blank=True, default='')
    chart_type = models.CharField(max_length=16, choices=TYPE_CHOICES)
    dimension_field = models.CharField(max_length=80)
    metric_field = models.CharField(max_length=80, blank=True, default='')
    aggregation = models.CharField(max_length=16, choices=AGGREGATE_CHOICES, default=AGGREGATE_COUNT)
    date_bucket = models.CharField(max_length=12, choices=DATE_BUCKET_CHOICES, blank=True, default='')
    position = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['position', 'created_at']
        constraints = [
            models.UniqueConstraint(fields=['definition', 'position'], name='unique_portal_report_chart_position'),
        ]
        verbose_name = 'Portal report chart'
        verbose_name_plural = 'Portal report charts'

    def __str__(self):
        return self.title or f'{self.definition}: {self.get_chart_type_display()}'


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
    branch_ref = models.ForeignKey(
        'OperationalLocation', null=True, blank=True, on_delete=models.PROTECT,
        limit_choices_to={'location_type': 'branch'}, related_name='access_grants',
    )
    product = models.CharField(max_length=120, blank=True, default='', db_index=True)
    product_ref = models.ForeignKey(
        'Product', null=True, blank=True, on_delete=models.PROTECT,
        related_name='access_grants',
    )
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
        if self.product_ref_id:
            self.product = self.product_ref.code
        elif self.product:
            from core.services.product_catalog import resolve_product
            self.product_ref = resolve_product(self.product)
        if self.branch_ref_id and not self.branch:
            self.branch = self.branch_ref.name
        if self.branch or self.branch_ref_id:
            from core.services.location_catalog import validate_location_selection
            branch_record, _county, _sub_county = validate_location_selection(
                branch_value=self.branch_ref or self.branch,
                source_workflow=self.workflow,
                source_model=type(self).__name__,
                source_record_id=self.pk,
            )
            self.branch_ref = branch_record
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


class AccessControlCheckerAssignment(models.Model):
    """Auditable appointment of an independent Mini App access checker.

    Django superusers are root technical approvers and therefore do not need an
    assignment.  Non-superuser checkers are appointed only through the access
    control service so the designation, its reason, and any later revocation
    remain visible in the compliance ledger.
    """

    SOURCE_BOOTSTRAP = 'bootstrap_override'
    SOURCE_SUPERUSER = 'superuser_appointment'
    SOURCE_LEGACY = 'legacy_group_backfill'
    SOURCE_CHOICES = [
        (SOURCE_BOOTSTRAP, 'Bootstrap override'),
        (SOURCE_SUPERUSER, 'Superuser appointment'),
        (SOURCE_LEGACY, 'Legacy approver-group backfill'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='access_control_checker_assignments',
    )
    appointed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='appointed_access_control_checkers',
        help_text='Blank only for an evidence-preserving legacy group backfill.',
    )
    appointment_reason = models.TextField()
    source = models.CharField(max_length=32, choices=SOURCE_CHOICES, default=SOURCE_SUPERUSER)
    appointed_at = models.DateTimeField(auto_now_add=True, db_index=True)
    revoked_at = models.DateTimeField(null=True, blank=True, db_index=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='revoked_access_control_checkers',
    )
    revocation_reason = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-appointed_at']
        constraints = [
            models.UniqueConstraint(
                fields=['user'],
                condition=models.Q(revoked_at__isnull=True),
                name='unique_active_access_control_checker',
            ),
        ]
        indexes = [models.Index(fields=['user', 'revoked_at'])]
        verbose_name = 'access control checker'
        verbose_name_plural = 'access control checkers'

    @property
    def active(self):
        return self.revoked_at is None and self.user.is_active

    def __str__(self):
        state = 'active' if self.active else 'revoked'
        return f'{self.user} ({state})'


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
    target_roles = models.JSONField(default=list, blank=True)
    request_key = models.CharField(max_length=128, blank=True, default='', db_index=True)
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
        constraints = [
            models.UniqueConstraint(
                fields=['requested_by', 'request_key'],
                condition=~models.Q(request_key=''),
                name='unique_access_change_request_key',
            ),
        ]

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
    product_ref = models.ForeignKey(
        'Product', null=True, blank=True, on_delete=models.PROTECT,
        related_name='emergency_access_grants',
    )
    group_configuration = models.ForeignKey('GroupSheetConfiguration', null=True, blank=True, on_delete=models.SET_NULL, related_name='+')
    reason = models.TextField()
    request_id = models.CharField(max_length=128, blank=True, default='', db_index=True)
    activated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='activated_emergency_access')
    activated_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='revoked_emergency_access')
    revocation_reason = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-activated_at']
        indexes = [models.Index(fields=['user', 'workflow', 'expires_at'])]
        constraints = [
            models.UniqueConstraint(
                fields=['activated_by', 'request_id'],
                condition=~models.Q(request_id=''),
                name='unique_emergency_access_request_id',
            ),
        ]

    @property
    def active(self):
        return self.revoked_at is None and self.expires_at > timezone.now()

    def save(self, *args, **kwargs):
        if self.product_ref_id:
            self.product = self.product_ref.code
        elif self.product:
            from core.services.product_catalog import resolve_product
            self.product_ref = resolve_product(self.product)
        return super().save(*args, **kwargs)


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


class OriginationDataField(models.Model):
    """Global semantic field used by product forms and legal PDF mappings."""

    TYPE_TEXT = 'text'
    TYPE_TEXTAREA = 'textarea'
    TYPE_NUMBER = 'number'
    TYPE_MONEY = 'money'
    TYPE_DATE = 'date'
    TYPE_PHONE = 'phone'
    TYPE_NATIONAL_ID = 'national_id'
    TYPE_CHOICE = 'choice'
    TYPE_BOOLEAN = 'boolean'
    TYPE_BRANCH = 'branch'
    TYPE_COUNTY = 'county'
    TYPE_SUB_COUNTY = 'sub_county'
    TYPE_REPEATING_GROUP = 'repeating_group'
    TYPE_CHOICES = [
        (TYPE_TEXT, 'Short text'), (TYPE_TEXTAREA, 'Long text'),
        (TYPE_NUMBER, 'Number'), (TYPE_MONEY, 'Money'), (TYPE_DATE, 'Date'),
        (TYPE_PHONE, 'Phone'), (TYPE_NATIONAL_ID, 'National ID'),
        (TYPE_CHOICE, 'Choice'), (TYPE_BOOLEAN, 'Yes / No'),
        (TYPE_BRANCH, 'Governed branch'), (TYPE_COUNTY, 'Governed county'),
        (TYPE_SUB_COUNTY, 'Governed sub-county'),
        (TYPE_REPEATING_GROUP, 'Repeatable group'),
    ]

    SOURCE_USER_INPUT = 'user_input'
    SOURCE_SYSTEM = 'system'
    SOURCE_CHOICES = [
        (SOURCE_USER_INPUT, 'User input'),
        (SOURCE_SYSTEM, 'System derived'),
    ]

    SENSITIVITY_PUBLIC = 'public'
    SENSITIVITY_INTERNAL = 'internal'
    SENSITIVITY_PII = 'pii'
    SENSITIVITY_FINANCIAL = 'financial'
    SENSITIVITY_RESTRICTED = 'restricted'
    SENSITIVITY_CHOICES = [
        (SENSITIVITY_PUBLIC, 'Public'), (SENSITIVITY_INTERNAL, 'Internal'),
        (SENSITIVITY_PII, 'Personal data (PII)'),
        (SENSITIVITY_FINANCIAL, 'Financial'),
        (SENSITIVITY_RESTRICTED, 'Restricted'),
    ]

    MASK_NONE = 'none'
    MASK_PARTIAL = 'partial'
    MASK_FULL = 'full'
    MASK_CHOICES = [
        (MASK_NONE, 'No masking'), (MASK_PARTIAL, 'Partial masking'),
        (MASK_FULL, 'Full masking'),
    ]

    REPORT_UNAVAILABLE = 'unavailable'
    REPORT_FILTER = 'filter'
    REPORT_DIMENSION = 'dimension'
    REPORT_METRIC = 'metric'
    REPORT_CHOICES = [
        (REPORT_UNAVAILABLE, 'Not reportable'), (REPORT_FILTER, 'Filter only'),
        (REPORT_DIMENSION, 'Dimension'), (REPORT_METRIC, 'Metric'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    key = models.SlugField(max_length=120, unique=True)
    label = models.CharField(max_length=160)
    aliases = models.JSONField(default=list, blank=True)
    category = models.CharField(max_length=80, blank=True, default='Application')
    data_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    source_type = models.CharField(
        max_length=20, choices=SOURCE_CHOICES, default=SOURCE_USER_INPUT,
    )
    sensitivity = models.CharField(
        max_length=20, choices=SENSITIVITY_CHOICES, default=SENSITIVITY_PII,
    )
    masking_policy = models.CharField(
        max_length=16, choices=MASK_CHOICES, default=MASK_PARTIAL,
    )
    reporting_use = models.CharField(
        max_length=16, choices=REPORT_CHOICES, default=REPORT_UNAVAILABLE,
    )
    export_allowed = models.BooleanField(default=False)
    help_text = models.CharField(max_length=500, blank=True, default='')
    choice_options = models.JSONField(default=list, blank=True)
    structure_schema = models.JSONField(
        default=dict, blank=True,
        help_text='Immutable child-column contract for repeatable-group fields.',
    )
    active = models.BooleanField(default=True, db_index=True)
    preferred_field = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.PROTECT,
        related_name='legacy_equivalent_fields',
        help_text=(
            'Preferred canonical field for this historical duplicate. Existing '
            'applications and PDF mappings continue using this field.'
        ),
    )
    terminology_reviewed_distinct = models.BooleanField(
        default=False,
        help_text='Confirm that this similarly named field has a genuinely distinct meaning.',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='created_origination_data_fields',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['category', 'label', 'key']
        indexes = [models.Index(fields=['active', 'category', 'label'])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(preferred_field__isnull=True) | models.Q(active=False),
                name='orig_field_preferred_requires_inactive',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(preferred_field__isnull=True)
                    | models.Q(terminology_reviewed_distinct=False)
                ),
                name='orig_field_preferred_not_distinct',
            ),
        ]

    def __str__(self):
        return f'{self.label} ({self.key})'

    def clean(self):
        super().clean()
        if self.preferred_field_id:
            if self.preferred_field_id == self.pk:
                raise ValidationError({'preferred_field': 'A field cannot replace itself.'})
            if self.preferred_field.data_type != self.data_type:
                raise ValidationError({'preferred_field': 'The preferred field must use the same data type.'})
            if not self.preferred_field.active:
                raise ValidationError({'preferred_field': 'Choose an active preferred field.'})
            if self.active:
                raise ValidationError({'active': 'A historical duplicate with a preferred field must be inactive.'})
            if self.terminology_reviewed_distinct:
                raise ValidationError({
                    'terminology_reviewed_distinct': (
                        'A field cannot be both a historical duplicate and confirmed distinct.'
                    ),
                })
        aliases = self.aliases or []
        if not isinstance(aliases, list) or any(not isinstance(item, str) for item in aliases):
            raise ValidationError({'aliases': 'Aliases must be a list of text values.'})
        normalized_aliases = [item.strip() for item in aliases if item.strip()]
        if len({item.casefold() for item in normalized_aliases}) != len(normalized_aliases):
            raise ValidationError({'aliases': 'Aliases cannot contain duplicates.'})
        self.aliases = normalized_aliases
        options = self.choice_options or []
        if self.data_type == self.TYPE_CHOICE:
            if not isinstance(options, list) or not options:
                raise ValidationError({'choice_options': 'Choice fields require canonical options.'})
            codes = []
            for option in options:
                if not isinstance(option, dict):
                    raise ValidationError({'choice_options': 'Each choice requires a code and label.'})
                code = str(option.get('code') or '').strip()
                label = str(option.get('label') or '').strip()
                if not code or not label:
                    raise ValidationError({'choice_options': 'Each choice requires a code and label.'})
                codes.append(code)
            if len(codes) != len(set(codes)):
                raise ValidationError({'choice_options': 'Canonical choice codes must be unique.'})
        elif options:
            raise ValidationError({'choice_options': 'Only choice fields may define choice options.'})
        structure = self.structure_schema or {}
        if self.data_type == self.TYPE_REPEATING_GROUP:
            if not isinstance(structure, dict):
                raise ValidationError({'structure_schema': 'Repeatable-group structure must be an object.'})
            columns = structure.get('columns')
            if not isinstance(columns, list) or not columns:
                raise ValidationError({'structure_schema': 'Repeatable groups require child columns.'})
            keys = []
            allowed_types = {
                self.TYPE_TEXT, self.TYPE_TEXTAREA, self.TYPE_NUMBER, self.TYPE_MONEY,
                self.TYPE_DATE, self.TYPE_PHONE, self.TYPE_NATIONAL_ID,
                self.TYPE_CHOICE, self.TYPE_BOOLEAN,
            }
            for column in columns:
                if not isinstance(column, dict):
                    raise ValidationError({'structure_schema': 'Every repeatable-group column must be an object.'})
                key = str(column.get('key') or '').strip()
                column_type = str(column.get('type') or '').strip()
                if not re.fullmatch(r'[a-z0-9_]+', key) or column_type not in allowed_types:
                    raise ValidationError({'structure_schema': 'Each child column requires a stable key and supported scalar type.'})
                keys.append(key)
            if len(keys) != len(set(keys)):
                raise ValidationError({'structure_schema': 'Repeatable-group child keys must be unique.'})
            minimum = int(structure.get('min_items', 0) or 0)
            maximum = int(structure.get('max_items', 0) or 0)
            if minimum < 0 or maximum < 1 or minimum > maximum or maximum > 50:
                raise ValidationError({'structure_schema': 'Repeatable-group item limits are invalid.'})
        elif structure:
            raise ValidationError({'structure_schema': 'Only repeatable-group fields may define a structure.'})
        for option in options:
            code = str(option.get('code') or '')
            if not re.fullmatch(r'[a-z0-9_]+', code):
                raise ValidationError({
                    'choice_options': 'Canonical choice codes may contain only lowercase letters, numbers, and underscores.',
                })
        if self.reporting_use == self.REPORT_METRIC and self.data_type not in {
            self.TYPE_NUMBER, self.TYPE_MONEY,
        }:
            raise ValidationError({'reporting_use': 'Only numeric or money fields may be report metrics.'})

    def save(self, *args, **kwargs):
        if self.pk:
            original = type(self).objects.filter(pk=self.pk).values(
                'key', 'data_type', 'choice_options', 'structure_schema',
            ).first()
            if original and (original['key'] != self.key or original['data_type'] != self.data_type):
                raise ValidationError('Canonical field keys and data types are immutable.')
            if original and original['structure_schema'] != (self.structure_schema or {}):
                raise ValidationError('Canonical repeatable-group structures are immutable.')
            if original and self.data_type == self.TYPE_CHOICE:
                previous_codes = {
                    str(item.get('code') or '') for item in (original['choice_options'] or [])
                    if isinstance(item, dict)
                }
                current_codes = {
                    str(item.get('code') or '') for item in (self.choice_options or [])
                    if isinstance(item, dict)
                }
                if previous_codes - current_codes:
                    raise ValidationError(
                        'Canonical choice codes cannot be removed; mark obsolete options inactive.',
                    )
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Canonical origination fields cannot be deleted; deactivate them instead.')


class OriginationDataFieldEvent(models.Model):
    """Append-only, value-free audit trail for catalogue governance."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    data_field = models.ForeignKey(
        OriginationDataField, on_delete=models.PROTECT, related_name='events',
    )
    action = models.CharField(max_length=40, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='origination_data_field_events',
    )
    metadata = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['occurred_at', 'id']

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Origination data-field events are append-only.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Origination data-field events cannot be deleted.')


class OriginationProductDefinition(models.Model):
    """Versioned, inactive-by-default contract for one loan-origination form."""

    STATUS_DRAFT = 'draft'
    STATUS_PUBLISHED = 'published'
    STATUS_RETIRED = 'retired'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_PUBLISHED, 'Published'),
        (STATUS_RETIRED, 'Retired'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product_version = models.ForeignKey(
        ProductVersion, null=True, blank=True, on_delete=models.PROTECT,
        related_name='origination_definitions',
    )
    product_key = models.SlugField(max_length=80, db_index=True)
    name = models.CharField(max_length=160)
    version = models.PositiveIntegerField(default=1)
    form_schema = models.JSONField(default=dict)
    signer_rules = models.JSONField(default=list)
    document_type = models.CharField(max_length=80)
    document_template_name = models.CharField(max_length=180, blank=True, default='')
    document_template_version = models.PositiveIntegerField(default=1)
    document_template_sha256 = models.CharField(max_length=64, blank=True, default='')
    is_active = models.BooleanField(default=False, db_index=True)
    lifecycle_status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True,
    )
    supersedes = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.PROTECT,
        related_name='superseded_by_versions',
    )
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='published_origination_product_definitions',
    )
    published_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='created_origination_product_definitions',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['product_key', '-version']
        constraints = [
            models.UniqueConstraint(
                fields=['product_key', 'version'], name='unique_origination_product_version',
            ),
            models.UniqueConstraint(
                fields=['product_key'], condition=models.Q(is_active=True),
                name='one_active_origination_product_version',
            ),
        ]
        indexes = [models.Index(
            fields=['product_key', 'is_active'], name='core_origin_product_67c040_idx',
        )]

    def __str__(self):
        return f'{self.name} v{self.version}'

    def clean(self):
        super().clean()
        if self.product_version_id:
            if self.product_key != self.product_version.product.code:
                raise ValidationError({'product_key': 'Origination product key must match the global product code.'})
            if self.name != self.product_version.product.name:
                raise ValidationError({'name': 'Origination product name must match the global product name.'})
        if self.is_active or self.lifecycle_status == self.STATUS_PUBLISHED:
            from core.services.loan_origination import OriginationError, validate_product_definition
            try:
                validate_product_definition(self)
            except OriginationError as exc:
                raise ValidationError(str(exc)) from exc


class OriginationProductDefinitionEvent(models.Model):
    """Append-only lifecycle history for a versioned origination product."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product_definition = models.ForeignKey(
        OriginationProductDefinition, on_delete=models.PROTECT, related_name='events',
    )
    action = models.CharField(max_length=40, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='origination_product_definition_events',
    )
    metadata = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['occurred_at', 'id']

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Origination product events are append-only.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Origination product events cannot be deleted.')


class OriginationFieldReviewIssue(models.Model):
    """Tracked exit path for a legacy schema field without a safe catalogue binding."""

    STATUS_OPEN = 'open'
    STATUS_RESOLVED = 'resolved'
    STATUS_ACCEPTED = 'accepted_legacy'
    STATUS_CHOICES = [
        (STATUS_OPEN, 'Needs review'), (STATUS_RESOLVED, 'Resolved'),
        (STATUS_ACCEPTED, 'Accepted as legacy'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product_definition = models.ForeignKey(
        OriginationProductDefinition, on_delete=models.PROTECT,
        related_name='field_review_issues',
    )
    legacy_key = models.CharField(max_length=120)
    legacy_type = models.CharField(max_length=20, blank=True, default='text')
    legacy_label = models.CharField(max_length=160, blank=True, default='')
    reason = models.CharField(max_length=80, blank=True, default='missing_catalogue_field')
    suggested_field = models.ForeignKey(
        OriginationDataField, null=True, blank=True, on_delete=models.PROTECT,
        related_name='suggested_legacy_reviews',
    )
    resolution_field = models.ForeignKey(
        OriginationDataField, null=True, blank=True, on_delete=models.PROTECT,
        related_name='resolved_legacy_reviews',
    )
    status = models.CharField(
        max_length=24, choices=STATUS_CHOICES, default=STATUS_OPEN, db_index=True,
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='assigned_origination_field_reviews',
    )
    resolution_notes = models.TextField(blank=True, default='')
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='resolved_origination_field_reviews',
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['status', '-created_at']
        constraints = [models.UniqueConstraint(
            fields=['product_definition', 'legacy_key'],
            name='unique_origination_field_review_key',
        )]
        indexes = [models.Index(fields=['status', 'updated_at'])]

    def __str__(self):
        return f'{self.product_definition}: {self.legacy_key}'

    def clean(self):
        super().clean()
        if self.status == self.STATUS_RESOLVED and not self.resolution_field_id:
            raise ValidationError({'resolution_field': 'Choose the canonical resolution field.'})
        if self.status == self.STATUS_ACCEPTED and not self.resolution_notes.strip():
            raise ValidationError({'resolution_notes': 'Explain why this field remains legacy.'})
        if self.resolution_field_id and self.resolution_field.data_type != self.legacy_type:
            raise ValidationError({'resolution_field': 'The canonical field must use the same data type.'})


class OriginationDocumentTemplate(models.Model):
    """Immutable Drive-backed PDF/config pair approved for origination rendering."""

    STATUS_READY = 'ready'
    STATUS_ACTIVE = 'active'
    STATUS_RETIRED = 'retired'
    STATUS_UPLOAD_FAILED = 'upload_failed'
    STATUS_CHOICES = [
        (STATUS_READY, 'Ready for review'),
        (STATUS_ACTIVE, 'Active'),
        (STATUS_RETIRED, 'Retired'),
        (STATUS_UPLOAD_FAILED, 'Upload failed'),
    ]

    ROLE_PRIMARY = 'primary'
    ROLE_SUPPORTING = 'supporting'
    ROLE_CHOICES = [
        (ROLE_PRIMARY, 'Primary LAF'),
        (ROLE_SUPPORTING, 'Supporting document'),
    ]
    INCLUDE_REQUIRED = 'required'
    INCLUDE_CONDITIONAL = 'conditional_required'
    INCLUDE_OPTIONAL = 'optional'
    INCLUDE_CHOICES = [
        (INCLUDE_REQUIRED, 'Always required'),
        (INCLUDE_CONDITIONAL, 'Required when rule matches'),
        (INCLUDE_OPTIONAL, 'Officer selectable'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product_definition = models.ForeignKey(
        OriginationProductDefinition, null=True, blank=True, on_delete=models.PROTECT,
        related_name='document_templates',
    )
    document_key = models.SlugField(max_length=80, default='primary', db_index=True)
    document_role = models.CharField(
        max_length=16, choices=ROLE_CHOICES, default=ROLE_PRIMARY, db_index=True,
    )
    inclusion_mode = models.CharField(
        max_length=24, choices=INCLUDE_CHOICES, default=INCLUDE_REQUIRED,
    )
    display_order = models.PositiveSmallIntegerField(default=0)
    officer_selectable = models.BooleanField(default=False)
    default_selected = models.BooleanField(default=False)
    applicability_rule = models.JSONField(default=dict, blank=True)
    form_schema = models.JSONField(default=dict, blank=True)
    signer_rules = models.JSONField(default=list, blank=True)
    document_type = models.SlugField(max_length=80, db_index=True)
    name = models.CharField(max_length=180)
    version = models.PositiveIntegerField()
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_READY, db_index=True)
    source_filename = models.CharField(max_length=255)
    source_sha256 = models.CharField(max_length=64, db_index=True)
    source_byte_size = models.PositiveBigIntegerField()
    page_count = models.PositiveIntegerField()
    placement_config = models.JSONField(default=dict)
    published_configuration_revision = models.ForeignKey(
        'OriginationTemplateConfigurationRevision', null=True, blank=True,
        on_delete=models.PROTECT, related_name='+',
    )
    drive_file_id = models.CharField(max_length=255, blank=True, default='')
    drive_url = models.URLField(max_length=1000, blank=True, default='')
    upload_error = models.TextField(blank=True, default='')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='created_origination_document_templates',
    )
    activated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='activated_origination_document_templates',
    )
    activated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['product_definition', 'display_order', 'document_key', '-version']
        constraints = [
            models.UniqueConstraint(
                fields=['document_type', 'version'],
                condition=models.Q(status__in=['ready', 'active']),
                name='unique_ready_active_orig_document_version',
            ),
            models.UniqueConstraint(
                fields=['document_type'], condition=models.Q(status='active'),
                name='one_active_origination_document',
            ),
        ]

    def __str__(self):
        return f'{self.name} v{self.version}'

    def clean(self):
        super().clean()
        errors = {}
        if self.document_role == self.ROLE_PRIMARY:
            if self.document_key != 'primary':
                errors['document_key'] = 'The primary LAF must use the key "primary".'
            if self.inclusion_mode != self.INCLUDE_REQUIRED:
                errors['inclusion_mode'] = 'The primary LAF is always required.'
            if self.officer_selectable:
                errors['officer_selectable'] = 'The primary LAF cannot be optional.'
        elif self.document_key == 'primary':
            errors['document_key'] = 'Supporting documents require their own stable key.'
        if self.inclusion_mode == self.INCLUDE_OPTIONAL and not self.officer_selectable:
            errors['officer_selectable'] = 'Optional documents must be officer selectable.'
        if self.inclusion_mode != self.INCLUDE_OPTIONAL and self.default_selected:
            errors['default_selected'] = 'Only optional documents can be selected by default.'
        if errors:
            raise ValidationError(errors)


class OriginationProductDocumentAssignment(models.Model):
    """Immutable product-version assignment of an approved shared document family."""

    VERSION_LATEST_COMPATIBLE = 'latest_compatible'
    VERSION_PINNED = 'pinned'
    VERSION_POLICY_CHOICES = [
        (VERSION_LATEST_COMPATIBLE, 'Latest published compatible version'),
        (VERSION_PINNED, 'Pin exact template version'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product_definition = models.ForeignKey(
        OriginationProductDefinition, on_delete=models.PROTECT,
        related_name='document_assignments',
    )
    template = models.ForeignKey(
        OriginationDocumentTemplate, on_delete=models.PROTECT,
        related_name='product_assignments',
        help_text='Compatibility baseline and family identity for this assignment.',
    )
    version_policy = models.CharField(
        max_length=24, choices=VERSION_POLICY_CHOICES,
        default=VERSION_LATEST_COMPATIBLE,
        help_text='Latest-compatible affects new applications only; every application snapshots its resolved version.',
    )
    document_key = models.SlugField(max_length=80)
    name = models.CharField(max_length=180)
    display_order = models.PositiveSmallIntegerField(default=10)
    inclusion_mode = models.CharField(
        max_length=24, choices=OriginationDocumentTemplate.INCLUDE_CHOICES,
        default=OriginationDocumentTemplate.INCLUDE_REQUIRED,
    )
    officer_selectable = models.BooleanField(default=False)
    default_selected = models.BooleanField(default=False)
    applicability_rule = models.JSONField(default=dict, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='created_origination_document_assignments',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['product_definition', 'display_order', 'document_key']
        constraints = [
            models.UniqueConstraint(
                fields=['product_definition', 'document_key'],
                name='unique_origination_product_document_key',
            ),
            models.UniqueConstraint(
                fields=['product_definition', 'template'],
                name='unique_origination_product_template_assignment',
            ),
        ]

    def __str__(self):
        return f'{self.product_definition}: {self.name}'

    def clean(self):
        super().clean()
        errors = {}
        if self.template_id:
            if (
                self.template.document_role == OriginationDocumentTemplate.ROLE_PRIMARY
                and self.template.product_definition_id is not None
            ):
                errors['template'] = 'A reusable primary LAF must be a global template.'
            if (
                self.template.product_definition_id not in (None, self.product_definition_id)
                and self.template.status not in {
                    OriginationDocumentTemplate.STATUS_ACTIVE,
                    OriginationDocumentTemplate.STATUS_RETIRED,
                }
            ):
                errors['template'] = 'Only an immutable published legacy template can be shared from another product version.'
            if (
                self.version_policy == self.VERSION_LATEST_COMPATIBLE
                and self.template.product_definition_id is not None
            ):
                errors['version_policy'] = 'Latest-compatible requires a global shared-template family.'
            if self.template.document_role == OriginationDocumentTemplate.ROLE_PRIMARY:
                if self.document_key != 'primary':
                    errors['document_key'] = 'A reusable primary LAF must use the key "primary".'
                if self.inclusion_mode != OriginationDocumentTemplate.INCLUDE_REQUIRED:
                    errors['inclusion_mode'] = 'The primary LAF is always required.'
                if self.officer_selectable:
                    errors['officer_selectable'] = 'The primary LAF cannot be officer selectable.'
                if self.default_selected:
                    errors['default_selected'] = 'The primary LAF is selected automatically.'
                if self.applicability_rule:
                    errors['applicability_rule'] = 'The primary LAF cannot have an applicability rule.'
            elif self.document_key == 'primary':
                errors['document_key'] = 'Supporting documents require their own stable key.'
        if self.inclusion_mode == OriginationDocumentTemplate.INCLUDE_OPTIONAL and not self.officer_selectable:
            errors['officer_selectable'] = 'Optional documents must be officer selectable.'
        if self.inclusion_mode != OriginationDocumentTemplate.INCLUDE_OPTIONAL and self.default_selected:
            errors['default_selected'] = 'Only optional documents can be selected by default.'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.product_definition.lifecycle_status != OriginationProductDefinition.STATUS_DRAFT:
            raise ValidationError('Document assignments are immutable; create the next product version.')
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.product_definition.lifecycle_status != OriginationProductDefinition.STATUS_DRAFT:
            raise ValidationError('Published document assignments cannot be deleted; replace them in the next product version.')
        return super().delete(*args, **kwargs)


class OriginationDocumentTemplateEvent(models.Model):
    """Append-only audit trail for legal template lifecycle changes."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    template = models.ForeignKey(
        OriginationDocumentTemplate, on_delete=models.PROTECT, related_name='events',
    )
    action = models.CharField(max_length=40, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='origination_document_template_events',
    )
    metadata = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['occurred_at', 'id']

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Origination document template events are append-only.')
        return super().save(*args, **kwargs)


class OriginationTemplateConfigurationRevision(models.Model):
    """Append-only saved calibration revision for one immutable source PDF."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    template = models.ForeignKey(
        OriginationDocumentTemplate, on_delete=models.PROTECT, related_name='configuration_revisions',
    )
    revision = models.PositiveIntegerField()
    configuration = models.JSONField(default=dict)
    is_published = models.BooleanField(default=False, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='origination_template_configuration_revisions',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    published_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['template', '-revision']
        constraints = [
            models.UniqueConstraint(
                fields=['template', 'revision'], name='unique_origination_template_config_revision',
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Origination template configuration revisions are append-only.')
        return super().save(*args, **kwargs)


class LoanOriginationApplication(models.Model):
    """Canonical, revision-controlled application captured by a field officer."""

    STATUS_DRAFT = 'draft'
    STATUS_READY_FOR_REVIEW = 'ready_for_review'
    STATUS_REVIEWED = 'reviewed'
    STATUS_SIGNING_PENDING = 'signing_pending'
    STATUS_PARTIALLY_SIGNED = 'partially_signed'
    STATUS_FULLY_SIGNED = 'fully_signed'
    STATUS_CORRECTION_REQUIRED = 'correction_required'
    STATUS_DECLINED = 'declined'
    STATUS_EXPIRED = 'expired'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_READY_FOR_REVIEW, 'Ready for review'),
        (STATUS_REVIEWED, 'Reviewed'),
        (STATUS_SIGNING_PENDING, 'Signing pending'),
        (STATUS_PARTIALLY_SIGNED, 'Partially signed'),
        (STATUS_FULLY_SIGNED, 'Fully signed'),
        (STATUS_CORRECTION_REQUIRED, 'Correction required'),
        (STATUS_DECLINED, 'Declined'),
        (STATUS_EXPIRED, 'Expired'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reference_number = models.CharField(max_length=80, unique=True, db_index=True)
    product_definition = models.ForeignKey(
        OriginationProductDefinition, on_delete=models.PROTECT, related_name='applications',
    )
    product_version = models.ForeignKey(
        ProductVersion, null=True, blank=True, on_delete=models.PROTECT,
        related_name='origination_applications',
    )
    customer = models.ForeignKey(
        'JawabuCustomer', null=True, blank=True, on_delete=models.PROTECT,
        related_name='origination_applications',
    )
    officer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='loan_origination_applications',
    )
    branch = models.CharField(max_length=128, blank=True, default='', db_index=True)
    branch_ref = models.ForeignKey(
        'OperationalLocation', null=True, blank=True, on_delete=models.PROTECT,
        limit_choices_to={'location_type': 'branch'}, related_name='origination_applications',
    )
    county_ref = models.ForeignKey(
        'OperationalLocation', null=True, blank=True, on_delete=models.PROTECT,
        limit_choices_to={'location_type': 'county'}, related_name='origination_county_applications',
    )
    sub_county_ref = models.ForeignKey(
        'OperationalLocation', null=True, blank=True, on_delete=models.PROTECT,
        limit_choices_to={'location_type': 'sub_county'}, related_name='origination_sub_county_applications',
    )
    location_snapshot = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=32, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True,
    )
    revision = models.PositiveIntegerField(default=1)
    form_payload = models.JSONField(default=dict)
    schema_snapshot = models.JSONField(default=dict)
    signer_rules_snapshot = models.JSONField(default=list)
    template_configuration_snapshot = models.JSONField(default=dict, blank=True)
    primary_previewed_revision = models.PositiveIntegerField(null=True, blank=True)
    product_terms_snapshot = models.JSONField(default=dict, blank=True)
    product_quote_snapshot = models.JSONField(default=dict, blank=True)
    product_requirement_evidence = models.JSONField(default=dict, blank=True)
    product_custom_values = models.JSONField(default=dict, blank=True)
    product_selected_fee_keys = models.JSONField(default=list, blank=True)
    identity_snapshot = models.JSONField(default=dict, blank=True)
    client_request_id = models.CharField(max_length=128, blank=True, default='', db_index=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='reviewed_loan_origination_applications',
    )
    recheck_assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='assigned_origination_rechecks',
        help_text='Checker responsible for verifying the current correction cycle.',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        constraints = [
            models.UniqueConstraint(
                fields=['officer', 'client_request_id'],
                condition=~models.Q(client_request_id=''),
                name='unique_origination_create_request_per_officer',
            ),
        ]
        indexes = [
            models.Index(
                fields=['officer', 'status', 'updated_at'], name='core_loanor_officer_3c905e_idx',
            ),
            models.Index(
                fields=['branch', 'status', 'updated_at'], name='core_loanor_branch_8c321c_idx',
            ),
        ]

    def __str__(self):
        return self.reference_number


class OriginationCommercialException(models.Model):
    """Immutable Superuser approval for exact policy mismatches on one revision."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey(
        LoanOriginationApplication, on_delete=models.PROTECT,
        related_name='commercial_exceptions',
    )
    application_revision = models.PositiveIntegerField()
    product_version = models.ForeignKey(
        ProductVersion, on_delete=models.PROTECT,
        related_name='origination_commercial_exceptions',
    )
    entered_terms_sha256 = models.CharField(max_length=64)
    expected_quote_sha256 = models.CharField(max_length=64)
    covered_mismatch_codes = models.JSONField(default=list)
    reason = models.TextField()
    approval_reference = models.CharField(max_length=255)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='approved_origination_commercial_exceptions',
    )
    approved_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        verbose_name = 'Origination commercial exception'
        verbose_name_plural = 'Origination commercial exceptions'
        ordering = ['-approved_at', 'id']
        constraints = [
            models.UniqueConstraint(
                fields=[
                    'application', 'application_revision', 'entered_terms_sha256',
                    'expected_quote_sha256',
                ],
                name='unique_origination_commercial_exception',
            ),
        ]
        indexes = [
            models.Index(
                fields=['application', 'application_revision'],
                name='orig_comm_exception_rev_idx',
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.application_id and self.product_version_id:
            if self.application.product_version_id != self.product_version_id:
                errors['product_version'] = 'The exception must use the application product version.'
        if self.approved_by_id and (
            not self.approved_by.is_active or not self.approved_by.is_superuser
        ):
            errors['approved_by'] = 'Only an active Django Superuser may approve this exception.'
        codes = self.covered_mismatch_codes or []
        if not isinstance(codes, list) or not codes or any(not isinstance(item, str) for item in codes):
            errors['covered_mismatch_codes'] = 'At least one stable policy mismatch code is required.'
        if not str(self.reason or '').strip():
            errors['reason'] = 'Record why this exception was approved.'
        if not str(self.approval_reference or '').strip():
            errors['approval_reference'] = 'Record the external approval reference.'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Origination commercial exceptions are append-only.')
        self.covered_mismatch_codes = sorted(set(self.covered_mismatch_codes or []))
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Origination commercial exceptions cannot be deleted.')

    def __str__(self):
        return f'{self.application.reference_number} r{self.application_revision}'


class OriginationReportingValue(models.Model):
    """Rebuildable typed projection of explicitly reportable application values."""

    application = models.ForeignKey(
        LoanOriginationApplication, on_delete=models.CASCADE,
        related_name='reporting_values',
    )
    data_field = models.ForeignKey(
        OriginationDataField, on_delete=models.PROTECT,
        related_name='reporting_values',
    )
    field_key = models.CharField(max_length=120)
    value_type = models.CharField(max_length=20, choices=OriginationDataField.TYPE_CHOICES)
    sensitivity = models.CharField(
        max_length=20, choices=OriginationDataField.SENSITIVITY_CHOICES,
    )
    masking_policy = models.CharField(
        max_length=16, choices=OriginationDataField.MASK_CHOICES,
    )
    reporting_use = models.CharField(
        max_length=16, choices=OriginationDataField.REPORT_CHOICES,
    )
    export_allowed = models.BooleanField(default=False)
    text_value = models.CharField(max_length=500, null=True, blank=True)
    decimal_value = models.DecimalField(
        max_digits=24, decimal_places=4, null=True, blank=True,
    )
    date_value = models.DateField(null=True, blank=True)
    boolean_value = models.BooleanField(null=True, blank=True)
    choice_code = models.CharField(max_length=120, null=True, blank=True)
    projected_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['application', 'field_key']
        constraints = [
            models.UniqueConstraint(
                fields=['application', 'data_field'],
                name='unique_origination_reporting_value',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        value_type__in=['text', 'textarea', 'phone', 'national_id'],
                        text_value__isnull=False, decimal_value__isnull=True,
                        date_value__isnull=True, boolean_value__isnull=True,
                        choice_code__isnull=True,
                    )
                    | models.Q(
                        value_type__in=['number', 'money'], text_value__isnull=True,
                        decimal_value__isnull=False, date_value__isnull=True,
                        boolean_value__isnull=True, choice_code__isnull=True,
                    )
                    | models.Q(
                        value_type='date', text_value__isnull=True,
                        decimal_value__isnull=True, date_value__isnull=False,
                        boolean_value__isnull=True, choice_code__isnull=True,
                    )
                    | models.Q(
                        value_type='boolean', text_value__isnull=True,
                        decimal_value__isnull=True, date_value__isnull=True,
                        boolean_value__isnull=False, choice_code__isnull=True,
                    )
                    | models.Q(
                        value_type='choice', text_value__isnull=True,
                        decimal_value__isnull=True, date_value__isnull=True,
                        boolean_value__isnull=True, choice_code__isnull=False,
                    )
                ),
                name='orig_reporting_matching_typed_value',
            ),
        ]
        indexes = [
            models.Index(fields=['data_field', 'text_value'], name='orig_report_field_text_idx'),
            models.Index(fields=['data_field', 'decimal_value'], name='orig_report_field_num_idx'),
            models.Index(fields=['data_field', 'date_value'], name='orig_report_field_date_idx'),
            models.Index(fields=['data_field', 'boolean_value'], name='orig_report_field_bool_idx'),
            models.Index(fields=['data_field', 'choice_code'], name='orig_report_field_choice_idx'),
        ]

    def __str__(self):
        return f'{self.application.reference_number}: {self.field_key}'


class OriginationApplicationEvent(models.Model):
    """Append-only operational history for an origination application."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey(
        LoanOriginationApplication, on_delete=models.PROTECT, related_name='events',
    )
    action = models.CharField(max_length=80, db_index=True)
    revision = models.PositiveIntegerField()
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='loan_origination_events',
    )
    request_id = models.CharField(max_length=128, blank=True, default='', db_index=True)
    before_values = models.JSONField(default=dict, blank=True)
    after_values = models.JSONField(default=dict, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['occurred_at', 'id']
        indexes = [models.Index(
            fields=['application', 'occurred_at'], name='core_origin_applica_ea7e72_idx',
        )]
        constraints = [
            models.UniqueConstraint(
                fields=['application', 'request_id'], condition=~models.Q(request_id=''),
                name='unique_origination_event_request',
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Origination application events are append-only.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Origination application events cannot be deleted.')


class OriginationReviewerNotice(models.Model):
    """Persistent in-app attention item for an Origination checker."""

    TYPE_APPROVAL_INVALIDATED = 'approval_invalidated'
    TYPE_CHOICES = [
        (TYPE_APPROVAL_INVALIDATED, 'Approval invalidated by officer recall'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey(
        LoanOriginationApplication, on_delete=models.PROTECT,
        related_name='reviewer_notices',
    )
    package = models.ForeignKey(
        'OriginationSigningPackage', null=True, blank=True, on_delete=models.PROTECT,
        related_name='reviewer_notices',
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='origination_reviewer_notices',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='created_origination_reviewer_notices',
    )
    notice_type = models.CharField(max_length=32, choices=TYPE_CHOICES, db_index=True)
    message = models.CharField(max_length=500)
    request_id = models.CharField(max_length=128)
    seen_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(
            fields=['application', 'recipient', 'request_id'],
            name='unique_orig_reviewer_notice_request',
        )]

    def __str__(self):
        return f'{self.application.reference_number}: {self.get_notice_type_display()}'


class OriginationCorrectionRequest(models.Model):
    """Append-preserving reviewer instructions for one submitted revision."""

    STATUS_OPEN = 'open'
    STATUS_ADDRESSED = 'addressed'
    STATUS_CHOICES = [
        (STATUS_OPEN, 'Open'),
        (STATUS_ADDRESSED, 'Addressed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey(
        LoanOriginationApplication, on_delete=models.PROTECT,
        related_name='correction_requests',
    )
    application_revision = models.PositiveIntegerField()
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='origination_correction_requests',
    )
    summary = models.TextField(max_length=2000)
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_OPEN, db_index=True,
    )
    addressed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='addressed_origination_corrections',
    )
    addressed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['application', 'application_revision'],
                name='unique_orig_correction_revision',
            ),
        ]
        indexes = [models.Index(
            fields=['application', 'status', 'created_at'],
            name='orig_corr_app_status_idx',
        )]

    def __str__(self):
        return f'{self.application.reference_number} correction r{self.application_revision}'

    def delete(self, *args, **kwargs):
        raise ValidationError('Origination correction requests cannot be deleted.')


class OriginationCorrectionItem(models.Model):
    """Immutable field or requirement target within a correction request."""

    TARGET_FIELD = 'field'
    TARGET_REQUIREMENT = 'requirement'
    TARGET_DOCUMENT_FIELD = 'document_field'
    TARGET_CHOICES = [
        (TARGET_FIELD, 'Application field'),
        (TARGET_REQUIREMENT, 'Product requirement'),
        (TARGET_DOCUMENT_FIELD, 'Supporting-document field'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    correction_request = models.ForeignKey(
        OriginationCorrectionRequest, on_delete=models.PROTECT, related_name='items',
    )
    target_type = models.CharField(max_length=20, choices=TARGET_CHOICES)
    target_key = models.CharField(max_length=240)
    target_label = models.CharField(max_length=160)
    instruction = models.CharField(max_length=1000, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']
        constraints = [models.UniqueConstraint(
            fields=['correction_request', 'target_type', 'target_key'],
            name='unique_orig_correction_target',
        )]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Origination correction items are immutable.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Origination correction items cannot be deleted.')


class OriginationRequirementEvidence(models.Model):
    """Audited Drive-backed evidence for one snapshotted product requirement."""

    STATUS_PENDING = 'pending'
    STATUS_UPLOADED = 'uploaded'
    STATUS_FAILED = 'failed'
    STATUS_REMOVED = 'removed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending upload'),
        (STATUS_UPLOADED, 'Uploaded'),
        (STATUS_FAILED, 'Upload failed'),
        (STATUS_REMOVED, 'Removed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey(
        LoanOriginationApplication, on_delete=models.PROTECT,
        related_name='requirement_evidence_files',
    )
    application_revision = models.PositiveIntegerField()
    requirement_key = models.CharField(max_length=80)
    requirement_label = models.CharField(max_length=160)
    original_filename = models.CharField(max_length=255)
    mime_type = models.CharField(max_length=100)
    byte_size = models.PositiveBigIntegerField()
    content_sha256 = models.CharField(max_length=64, db_index=True)
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True,
    )
    drive_file_id = models.CharField(max_length=255, blank=True, default='')
    drive_url = models.URLField(max_length=1000, blank=True, default='')
    upload_error = models.TextField(blank=True, default='')
    request_id = models.CharField(max_length=128)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='uploaded_origination_requirement_evidence',
    )
    removed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='removed_origination_requirement_evidence',
    )
    removed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['requirement_key', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['application', 'request_id'],
                name='unique_orig_evidence_request',
            ),
        ]
        indexes = [
            models.Index(
                fields=['application', 'requirement_key', 'status'],
                name='orig_evid_app_req_status_idx',
            ),
        ]

    def __str__(self):
        return f'{self.application.reference_number}: {self.requirement_label}'

    def delete(self, *args, **kwargs):
        raise ValidationError('Origination evidence cannot be deleted; remove it logically.')


class OriginationApplicationDocument(models.Model):
    """Application-scoped snapshot and progress for one generated packet document."""

    SOURCE_REQUIRED = 'required'
    SOURCE_RULE = 'rule'
    SOURCE_DEFAULT = 'default'
    SOURCE_OFFICER = 'officer'
    SOURCE_CHOICES = [
        (SOURCE_REQUIRED, 'Required'),
        (SOURCE_RULE, 'Applicability rule'),
        (SOURCE_DEFAULT, 'Default selection'),
        (SOURCE_OFFICER, 'Officer selection'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey(
        LoanOriginationApplication, on_delete=models.PROTECT, related_name='packet_documents',
    )
    template = models.ForeignKey(
        OriginationDocumentTemplate, null=True, blank=True, on_delete=models.PROTECT,
        related_name='application_documents',
    )
    assignment = models.ForeignKey(
        OriginationProductDocumentAssignment, null=True, blank=True,
        on_delete=models.PROTECT, related_name='application_documents',
    )
    document_key = models.SlugField(max_length=80)
    name = models.CharField(max_length=180)
    document_role = models.CharField(max_length=16, choices=OriginationDocumentTemplate.ROLE_CHOICES)
    display_order = models.PositiveSmallIntegerField(default=0)
    inclusion_mode = models.CharField(max_length=24, choices=OriginationDocumentTemplate.INCLUDE_CHOICES)
    selection_source = models.CharField(max_length=16, choices=SOURCE_CHOICES, default=SOURCE_REQUIRED)
    applicable = models.BooleanField(default=True)
    selected = models.BooleanField(default=True)
    template_snapshot = models.JSONField(default=dict)
    schema_snapshot = models.JSONField(default=dict, blank=True)
    signer_rules_snapshot = models.JSONField(default=list, blank=True)
    field_payload = models.JSONField(default=dict, blank=True)
    previewed_application_revision = models.PositiveIntegerField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', 'document_key']
        constraints = [models.UniqueConstraint(
            fields=['application', 'document_key'], name='unique_origination_application_document',
        )]

    def __str__(self):
        return f'{self.application.reference_number}: {self.name}'


class OriginationSigningPackage(models.Model):
    """Stable cross-system link from one frozen revision to e-signatures."""

    STATUS_PENDING = 'pending'
    STATUS_IN_PROGRESS = 'in_progress'
    STATUS_FULLY_SIGNED = 'fully_signed'
    STATUS_DECLINED = 'declined'
    STATUS_EXPIRED = 'expired'
    STATUS_CANCELLED = 'cancelled'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_IN_PROGRESS, 'In progress'),
        (STATUS_FULLY_SIGNED, 'Fully signed'),
        (STATUS_DECLINED, 'Declined'),
        (STATUS_EXPIRED, 'Expired'),
        (STATUS_CANCELLED, 'Cancelled'),
        (STATUS_FAILED, 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    application = models.ForeignKey(
        LoanOriginationApplication, on_delete=models.PROTECT, related_name='signing_packages',
    )
    application_revision = models.PositiveIntegerField()
    external_reference = models.CharField(max_length=80, unique=True, db_index=True)
    document_type = models.CharField(max_length=80)
    template_version = models.PositiveIntegerField(null=True, blank=True)
    template_sha256 = models.CharField(max_length=64, blank=True, default='')
    template_configuration_snapshot = models.JSONField(default=dict, blank=True)
    context_snapshot = models.JSONField(default=dict)
    participants_snapshot = models.JSONField(default=list)
    requirement_evidence_snapshot = models.JSONField(default=list, blank=True)
    document_manifest_snapshot = models.JSONField(default=list, blank=True)
    combined_document_hash = models.CharField(max_length=64, blank=True, default='')
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    frozen_unsigned_document = models.BinaryField(blank=True, default=bytes, editable=False)
    unsigned_document_hash = models.CharField(max_length=64, blank=True, default='')
    review_scope_sha256 = models.CharField(max_length=64, blank=True, default='', db_index=True)
    approved_unsigned_document_hash = models.CharField(max_length=64, blank=True, default='')
    approved_review_scope_sha256 = models.CharField(max_length=64, blank=True, default='')
    prepared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='prepared_origination_review_packages',
    )
    prepared_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='reviewed_origination_signing_packages',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    signed_document_hash = models.CharField(max_length=64, blank=True, default='')
    final_document_reference = models.TextField(blank=True, default='')
    final_drive_file_id = models.CharField(max_length=255, blank=True, default='')
    archive_status = models.CharField(
        max_length=24,
        choices=[
            ('not_ready', 'Not ready'),
            ('pending', 'Pending'),
            ('uploaded', 'Uploaded'),
            ('failed', 'Failed'),
        ],
        default='not_ready',
        db_index=True,
    )
    archive_error = models.TextField(blank=True, default='')
    pending_signed_document = models.BinaryField(blank=True, default=bytes, editable=False)
    finalized_at = models.DateTimeField(null=True, blank=True)
    archived_at = models.DateTimeField(null=True, blank=True)
    remote_error = models.TextField(blank=True, default='')
    test_mode = models.BooleanField(default=False)
    test_completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['application', 'application_revision'],
                name='one_signing_package_per_origination_revision',
            ),
        ]
        indexes = [models.Index(
            fields=['application', 'status', 'updated_at'], name='core_origin_applica_3a6bd3_idx',
        )]

    def __str__(self):
        return self.external_reference


class OriginationStampAsset(models.Model):
    """Versioned, controlled PNG used only in calibrated stamp slots."""

    ENV_TEST = 'test'
    ENV_PRODUCTION = 'production'
    ENV_CHOICES = [(ENV_TEST, 'Test only'), (ENV_PRODUCTION, 'Production')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=160)
    branch = models.ForeignKey(
        'OperationalLocation', null=True, blank=True, on_delete=models.PROTECT,
        limit_choices_to={'location_type': 'branch'}, related_name='origination_stamp_assets',
    )
    environment = models.CharField(max_length=16, choices=ENV_CHOICES, default=ENV_TEST)
    version = models.PositiveIntegerField(default=1)
    image_png = models.BinaryField(editable=False)
    content_sha256 = models.CharField(max_length=64, db_index=True)
    byte_size = models.PositiveIntegerField()
    active = models.BooleanField(default=False, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='created_origination_stamp_assets',
    )
    activated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='activated_origination_stamp_assets',
    )
    activated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name', 'branch', '-version']
        constraints = [
            models.UniqueConstraint(
                fields=['name', 'environment', 'version'],
                condition=models.Q(branch__isnull=True),
                name='unique_global_origination_stamp_version',
            ),
            models.UniqueConstraint(
                fields=['name', 'branch', 'environment', 'version'],
                condition=models.Q(branch__isnull=False),
                name='unique_branch_origination_stamp_version',
            ),
        ]

    def __str__(self):
        scope = self.branch.name if self.branch_id else 'Organization'
        return f'{self.name} v{self.version} ({scope}, {self.environment})'


class OriginationSignerSession(models.Model):
    """Revocable bearer session for one signer of one immutable packet."""

    STATUS_PENDING = 'pending'
    STATUS_OTP_SENT = 'otp_sent'
    STATUS_VERIFIED = 'verified'
    STATUS_LOCKED = 'locked'
    STATUS_EXPIRED = 'expired'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_OTP_SENT, 'OTP sent'),
        (STATUS_VERIFIED, 'Verified'),
        (STATUS_LOCKED, 'Locked'),
        (STATUS_EXPIRED, 'Expired'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]
    MODE_SELF_SERVICE = 'self_service'
    MODE_ASSISTED = 'assisted'
    MODE_CHOICES = [
        (MODE_SELF_SERVICE, 'Self service'),
        (MODE_ASSISTED, 'Assisted by staff'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    package = models.ForeignKey(
        OriginationSigningPackage, on_delete=models.PROTECT, related_name='signer_sessions',
    )
    signer_role = models.CharField(max_length=80)
    identity_snapshot = models.JSONField(default=dict, blank=True)
    phone_normalized = models.CharField(max_length=16, blank=True, default='')
    phone_hash = models.CharField(max_length=64, blank=True, default='', db_index=True)
    phone_last4 = models.CharField(max_length=4, blank=True, default='')
    token_hash = models.CharField(max_length=64, unique=True, db_index=True)
    token_expires_at = models.DateTimeField(db_index=True)
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    access_mode = models.CharField(max_length=24, choices=MODE_CHOICES, default=MODE_SELF_SERVICE)
    is_active = models.BooleanField(default=True, db_index=True)
    consent_version = models.CharField(max_length=32, blank=True, default='')
    consented_at = models.DateTimeField(null=True, blank=True)
    reviewed_pages = models.JSONField(default=list, blank=True)
    signature_capture = models.JSONField(default=dict, blank=True)
    signature_capture_sha256 = models.CharField(max_length=64, blank=True, default='')
    verified_at = models.DateTimeField(null=True, blank=True)
    locked_until = models.DateTimeField(null=True, blank=True)
    invalidated_at = models.DateTimeField(null=True, blank=True)
    shared_phone_override_reason = models.TextField(blank=True, default='')
    shared_phone_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='approved_origination_shared_phone_sessions',
    )
    shared_phone_approved_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='created_origination_signer_sessions',
    )
    assisted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='assisted_origination_signer_sessions',
    )
    request_id = models.CharField(max_length=128, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['package', 'signer_role', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['package', 'signer_role'], condition=models.Q(is_active=True),
                name='one_active_origination_signer_session',
            ),
            models.UniqueConstraint(
                fields=['package', 'request_id'], condition=~models.Q(request_id=''),
                name='unique_origination_signer_session_request',
            ),
        ]

    def __str__(self):
        return f'{self.package.external_reference}: {self.signer_role}'


class OriginationOtpChallenge(models.Model):
    """Hashed, bounded OTP challenge; provider delivery never proves signing."""

    DELIVERY_PENDING = 'pending'
    DELIVERY_ACCEPTED = 'accepted'
    DELIVERY_DELIVERED = 'delivered'
    DELIVERY_FAILED = 'failed'
    DELIVERY_UNKNOWN = 'unknown'
    DELIVERY_CHOICES = [
        (DELIVERY_PENDING, 'Pending'),
        (DELIVERY_ACCEPTED, 'Accepted'),
        (DELIVERY_DELIVERED, 'Delivered'),
        (DELIVERY_FAILED, 'Failed'),
        (DELIVERY_UNKNOWN, 'Unknown'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        OriginationSignerSession, on_delete=models.PROTECT, related_name='otp_challenges',
    )
    code_hash = models.CharField(max_length=255)
    binding_sha256 = models.CharField(max_length=64)
    provider_message_id = models.CharField(max_length=255, blank=True, default='', db_index=True)
    delivery_status = models.CharField(
        max_length=24, choices=DELIVERY_CHOICES, default=DELIVERY_PENDING, db_index=True,
    )
    provider_status = models.CharField(max_length=80, blank=True, default='')
    send_sequence = models.PositiveSmallIntegerField()
    attempts_remaining = models.PositiveSmallIntegerField(default=5)
    request_id = models.CharField(max_length=128)
    source_ip_hash = models.CharField(max_length=64, blank=True, default='', db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    invalidated_at = models.DateTimeField(null=True, blank=True)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['session', '-send_sequence']
        constraints = [
            models.UniqueConstraint(
                fields=['session', 'send_sequence'], name='unique_origination_otp_sequence',
            ),
            models.UniqueConstraint(
                fields=['session', 'request_id'], name='unique_origination_otp_request',
            ),
        ]

    def __str__(self):
        return f'{self.session} OTP {self.send_sequence}'


class OriginationSigningRequestEvent(models.Model):
    """Minimal append-only database throttle evidence for public signing writes."""

    ACTION_MUTATE = 'mutate'
    ACTION_SEND = 'send'
    ACTION_VERIFY = 'verify'
    ACTION_CHOICES = [
        (ACTION_MUTATE, 'Signer write'),
        (ACTION_SEND, 'OTP send'),
        (ACTION_VERIFY, 'OTP verification'),
    ]

    id = models.BigAutoField(primary_key=True)
    session = models.ForeignKey(
        OriginationSignerSession, null=True, blank=True, on_delete=models.CASCADE,
        related_name='request_events',
    )
    action = models.CharField(max_length=16, choices=ACTION_CHOICES, db_index=True)
    request_id = models.CharField(max_length=128, blank=True, default='')
    payload_digest = models.CharField(max_length=64, blank=True, default='')
    token_hash = models.CharField(max_length=64, blank=True, default='', db_index=True)
    source_ip_hash = models.CharField(max_length=64, blank=True, default='', db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['action', 'token_hash', 'created_at'], name='core_osre_token_created_idx'),
            models.Index(fields=['action', 'source_ip_hash', 'created_at'], name='core_osre_ip_created_idx'),
        ]
        constraints = [models.UniqueConstraint(
            fields=['session', 'action', 'request_id'], condition=~models.Q(request_id=''),
            name='unique_origination_signing_request_event',
        )]


class OriginationSigningAction(models.Model):
    """Append-only evidence for one simulated or provider-verified slot action."""

    TYPE_SIGNATURE = 'signature'
    TYPE_STAMP = 'stamp'
    TYPE_DATE_SIGNED = 'date_signed'
    TYPE_CHOICES = [
        (TYPE_SIGNATURE, 'Signature'), (TYPE_STAMP, 'Stamp'),
        (TYPE_DATE_SIGNED, 'Signing date'),
    ]
    MODE_TEST = 'test'
    MODE_VERIFIED = 'verified'
    MODE_CHOICES = [(MODE_TEST, 'Test simulation'), (MODE_VERIFIED, 'Verified production')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    package = models.ForeignKey(
        OriginationSigningPackage, on_delete=models.PROTECT, related_name='actions',
    )
    document_key = models.SlugField(max_length=80)
    slot_key = models.SlugField(max_length=80)
    signer_role = models.CharField(max_length=80)
    action_type = models.CharField(max_length=16, choices=TYPE_CHOICES)
    mode = models.CharField(max_length=16, choices=MODE_CHOICES)
    stamp_asset = models.ForeignKey(
        OriginationStampAsset, null=True, blank=True, on_delete=models.PROTECT,
        related_name='signing_actions',
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='origination_signing_actions',
    )
    signer_session = models.ForeignKey(
        OriginationSignerSession, null=True, blank=True, on_delete=models.PROTECT,
        related_name='actions',
    )
    request_id = models.CharField(max_length=128, db_index=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['created_at', 'id']
        constraints = [
            models.UniqueConstraint(
                fields=['package', 'document_key', 'slot_key'],
                name='unique_origination_signing_slot_action',
            ),
            models.UniqueConstraint(
                fields=['package', 'request_id'],
                name='unique_origination_signing_action_request',
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Origination signing actions are append-only.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Origination signing actions cannot be deleted.')


class PortalVoiceTranscriptionAttempt(models.Model):
    """Append-oriented audit and retry state for bounded Portal dictation."""

    FIELD_JBL_VISIT_COMMENT = 'jbl_visit_comment'
    FIELD_FINAL_DECISION_COMMENT = 'final_decision_comment'
    FIELD_CHOICES = [
        (FIELD_JBL_VISIT_COMMENT, 'JBL visit comment'),
        (FIELD_FINAL_DECISION_COMMENT, 'Final decision after-call comment'),
    ]
    STATUS_PROCESSING = 'processing'
    STATUS_TRANSCRIBED = 'transcribed'
    STATUS_ACCEPTED = 'accepted'
    STATUS_CANCELLED = 'cancelled'
    STATUS_FAILED = 'failed'
    STATUS_EXPIRED = 'expired'
    STATUS_CHOICES = [
        (STATUS_PROCESSING, 'Processing'),
        (STATUS_TRANSCRIBED, 'Transcribed'),
        (STATUS_ACCEPTED, 'Accepted'),
        (STATUS_CANCELLED, 'Cancelled'),
        (STATUS_FAILED, 'Failed'),
        (STATUS_EXPIRED, 'Expired'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='portal_voice_transcription_attempts',
    )
    farmer = models.ForeignKey(
        'JawabuFarmerMaster',
        on_delete=models.CASCADE,
        related_name='voice_transcription_attempts',
    )
    field_name = models.CharField(max_length=64, choices=FIELD_CHOICES)
    request_id = models.CharField(max_length=128)
    audio_hash = models.CharField(max_length=64, db_index=True)
    audio_size = models.PositiveIntegerField(default=0)
    audio_mime_type = models.CharField(max_length=80, blank=True, default='')
    duration_ms = models.PositiveIntegerField(default=0)
    provider = models.CharField(max_length=32, default='groq')
    model_name = models.CharField(max_length=80, default='whisper-large-v3')
    requested_language = models.CharField(max_length=8, default='auto', db_index=True)
    detected_language = models.CharField(max_length=16, blank=True, default='')
    average_log_probability = models.FloatField(null=True, blank=True)
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_PROCESSING, db_index=True)
    transcript = models.TextField(blank=True, default='')
    provider_request_id = models.CharField(max_length=128, blank=True, default='')
    drive_file_id = models.CharField(max_length=255, blank=True, default='')
    expires_at = models.DateTimeField(db_index=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    edit_distance = models.PositiveIntegerField(null=True, blank=True)
    deletion_status = models.CharField(max_length=24, blank=True, default='not_stored', db_index=True)
    deletion_error = models.CharField(max_length=255, blank=True, default='')
    error_code = models.CharField(max_length=64, blank=True, default='')
    source_attempt = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL, related_name='retries',
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'request_id'],
                name='unique_portal_voice_request_per_user',
            ),
        ]
        indexes = [
            models.Index(fields=['user', 'created_at'], name='portal_voice_user_day_idx'),
            models.Index(fields=['status', 'expires_at'], name='portal_voice_status_exp_idx'),
            models.Index(fields=['farmer', 'field_name', 'created_at'], name='portal_voice_case_field_idx'),
        ]


class JawabuFarmerUploadBatch(models.Model):
    """Staged FarmUp/system-export upload awaiting staff review and commit.

    The original source is retained as a bounded binary payload so an accepted
    import can be archived to Drive after a free-Render request returns.  The
    parsed rows remain the review surface; they are not a replacement for the
    submitted source document.
    """

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
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='jawabu_import_batches',
    )
    upload_request_id = models.CharField(max_length=128, null=True, blank=True, unique=True)
    source_filename = models.CharField(max_length=255, blank=True, default='')
    source_mime_type = models.CharField(max_length=255, blank=True, default='')
    source_size = models.PositiveIntegerField(default=0)
    source_content_hash = models.CharField(max_length=64, blank=True, default='', db_index=True)
    source_content = models.BinaryField(blank=True, null=True)
    archive_file_id = models.CharField(max_length=255, blank=True, default='')
    archive_url = models.URLField(max_length=1000, blank=True, default='')
    archive_error = models.TextField(blank=True, default='')
    archive_sync_attempts = models.PositiveIntegerField(default=0)
    archive_last_sync_at = models.DateTimeField(null=True, blank=True)
    archive_next_retry_at = models.DateTimeField(null=True, blank=True)
    # This is a Portal working-list lifecycle, not Drive archival.  The raw
    # source, parser review metadata, integration operation, and Drive state
    # stay retained after an IT user archives the batch from the active list.
    is_portal_archived = models.BooleanField(default=False, db_index=True)
    portal_archived_at = models.DateTimeField(null=True, blank=True, db_index=True)
    portal_archived_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='archived_portal_import_batches',
    )
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
            models.Index(fields=['archive_next_retry_at']),
            models.Index(fields=['is_portal_archived', 'group_id', 'created_at']),
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
    """Stable branch, county, or sub-county identity shared by all workflows."""

    LOCATION_TYPES = (
        ('branch', 'Branch'),
        ('county', 'County'),
        ('sub_county', 'Sub-county'),
    )

    location_type = models.CharField(max_length=20, choices=LOCATION_TYPES, db_index=True)
    name = models.CharField(max_length=128)
    code = models.CharField(max_length=64)
    parent = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.PROTECT,
        related_name='children',
    )
    active = models.BooleanField(default=True, db_index=True)
    sort_order = models.PositiveIntegerField(default=0)
    source_name = models.CharField(max_length=160, blank=True, default='')
    source_reference = models.URLField(max_length=1000, blank=True, default='')
    published_at = models.DateTimeField(default=timezone.now)
    retired_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['location_type', 'sort_order', 'name']
        constraints = [
            models.UniqueConstraint(
                Lower('name'), 'location_type',
                condition=models.Q(location_type__in=['branch', 'county']),
                name='unique_operational_location_name_ci',
            ),
            models.UniqueConstraint(
                Lower('name'), 'parent',
                condition=models.Q(location_type='sub_county'),
                name='unique_sub_county_name_per_county_ci',
            ),
            models.UniqueConstraint(
                Lower('code'), name='unique_operational_location_code_ci',
            ),
            models.CheckConstraint(
                condition=~models.Q(code=''), name='operational_location_code_required',
            ),
        ]
        verbose_name = 'Operational location'
        verbose_name_plural = 'Operational locations'

    def clean(self):
        super().clean()
        self.name = ' '.join(str(self.name or '').split())
        self.code = re.sub(r'[^A-Z0-9]+', '-', str(self.code or '').upper()).strip('-')
        if not self.name:
            raise ValidationError({'name': 'Enter a location name.'})
        if not self.code:
            raise ValidationError({'code': 'Enter a stable location code.'})
        if self.location_type == 'sub_county':
            if not self.parent_id or self.parent.location_type != 'county':
                raise ValidationError({'parent': 'A sub-county must belong to a county.'})
        elif self.parent_id:
            raise ValidationError({'parent': 'Only sub-counties may have a parent location.'})
        if self.active and self.retired_at:
            raise ValidationError({'retired_at': 'An active location cannot have a retirement time.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        if not self._state.adding:
            previous = type(self).objects.filter(pk=self.pk).values(
                'code', 'location_type', 'parent_id',
            ).first()
            if previous and previous['code'] != self.code:
                raise ValidationError({'code': 'Location code is immutable.'})
            if previous and previous['location_type'] != self.location_type:
                raise ValidationError({'location_type': 'Location type is immutable.'})
            if previous and previous['parent_id'] != self.parent_id:
                raise ValidationError({'parent': 'Published location parentage is immutable; retire and replace it.'})
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Locations cannot be deleted; retire them instead.')

    def __str__(self):
        return f'{self.get_location_type_display()}: {self.name}'


class OperationalLocationAlias(models.Model):
    """Approved legacy or alternate spelling for a canonical location."""

    location = models.ForeignKey(
        OperationalLocation, on_delete=models.PROTECT, related_name='aliases',
    )
    location_type = models.CharField(max_length=20, choices=OperationalLocation.LOCATION_TYPES, editable=False)
    parent = models.ForeignKey(
        OperationalLocation, null=True, blank=True, on_delete=models.PROTECT,
        related_name='+', editable=False,
    )
    alias = models.CharField(max_length=160)
    normalized_alias = models.CharField(max_length=180, editable=False, db_index=True)
    active = models.BooleanField(default=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    retired_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['location_type', 'alias']
        constraints = [
            models.UniqueConstraint(
                fields=['location_type', 'normalized_alias'],
                condition=models.Q(location_type__in=['branch', 'county']),
                name='unique_location_alias_by_type',
            ),
            models.UniqueConstraint(
                fields=['parent', 'normalized_alias'],
                condition=models.Q(location_type='sub_county'),
                name='unique_sub_county_alias_per_county',
            ),
        ]

    def clean(self):
        super().clean()
        self.alias = ' '.join(str(self.alias or '').split())
        self.normalized_alias = re.sub(
            r'[^a-z0-9]+', '_', self.alias.casefold().replace('\u2019', "'")
        ).strip('_')
        self.location_type = self.location.location_type if self.location_id else ''
        self.parent = self.location.parent if self.location_id else None
        if not self.normalized_alias:
            raise ValidationError({'alias': 'Enter a usable location alias.'})
        canonical = OperationalLocation.objects.filter(location_type=self.location_type)
        if self.location_type == 'sub_county':
            canonical = canonical.filter(parent=self.parent)
        for location in canonical.only('id', 'name'):
            normalized_name = re.sub(
                r'[^a-z0-9]+', '_', location.name.casefold().replace('\u2019', "'")
            ).strip('_')
            if normalized_name == self.normalized_alias and location.pk != self.location_id:
                raise ValidationError({'alias': 'This alias is the canonical name of another location.'})
        if self.active and self.retired_at:
            raise ValidationError({'retired_at': 'An active alias cannot have a retirement time.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        if not self._state.adding:
            previous = type(self).objects.filter(pk=self.pk).values('location_id').first()
            if previous and previous['location_id'] != self.location_id:
                raise ValidationError({'location': 'An alias cannot be reassigned; retire it and create another.'})
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Location aliases cannot be deleted; retire them instead.')

    def __str__(self):
        return f'{self.alias} -> {self.location.name}'


class BranchServiceArea(models.Model):
    """Current governed coverage of one branch over a county or sub-county."""

    branch = models.ForeignKey(
        OperationalLocation, on_delete=models.PROTECT, related_name='service_area_assignments',
        limit_choices_to={'location_type': 'branch'},
    )
    area = models.ForeignKey(
        OperationalLocation, on_delete=models.PROTECT, related_name='serving_branch_assignments',
        limit_choices_to={'location_type__in': ['county', 'sub_county']},
    )
    is_primary = models.BooleanField(default=False, db_index=True)
    active = models.BooleanField(default=True, db_index=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='created_branch_service_areas',
    )
    retired_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='retired_branch_service_areas',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    retired_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['branch__sort_order', 'branch__name', 'area__sort_order', 'area__name']
        constraints = [
            models.UniqueConstraint(
                fields=['branch', 'area'], name='unique_branch_service_area',
            ),
            models.UniqueConstraint(
                fields=['area'], condition=models.Q(active=True, is_primary=True),
                name='unique_active_primary_branch_per_area',
            ),
        ]

    def clean(self):
        super().clean()
        if self.branch_id and self.branch.location_type != 'branch':
            raise ValidationError({'branch': 'Choose a branch location.'})
        if self.area_id and self.area.location_type not in {'county', 'sub_county'}:
            raise ValidationError({'area': 'Choose a county or sub-county.'})
        if self.branch_id and self.area_id and self.branch_id == self.area_id:
            raise ValidationError({'area': 'A branch cannot serve itself as an area.'})
        if self.active and self.retired_at:
            raise ValidationError({'retired_at': 'An active service area cannot have a retirement time.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        if not self._state.adding:
            previous = type(self).objects.filter(pk=self.pk).values('branch_id', 'area_id').first()
            if previous and (previous['branch_id'], previous['area_id']) != (self.branch_id, self.area_id):
                raise ValidationError('A service-area assignment cannot be retargeted; retire and create another.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Service areas cannot be deleted; retire them instead.')

    def __str__(self):
        return f'{self.branch.name} -> {self.area.name}'


class LocationPolicyState(models.Model):
    MODE_AUDIT = 'audit'
    MODE_STRICT = 'strict'
    MODE_CHOICES = [(MODE_AUDIT, 'Audit only'), (MODE_STRICT, 'Strict enforcement')]

    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    mode = models.CharField(max_length=16, choices=MODE_CHOICES, default=MODE_AUDIT, db_index=True)
    source_manifest = models.JSONField(default=dict, blank=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+',
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Location enforcement policy'
        verbose_name_plural = 'Location enforcement policy'

    def clean(self):
        super().clean()
        if self.pk != 1:
            raise ValidationError('Only one location policy record is allowed.')

    def save(self, *args, **kwargs):
        self.pk = 1
        self.full_clean()
        return super().save(*args, **kwargs)


class LocationConfigurationEvent(models.Model):
    """Append-only evidence for global location and coverage changes."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    subject_type = models.CharField(max_length=40, db_index=True)
    subject_id = models.CharField(max_length=120, db_index=True)
    action = models.CharField(max_length=60, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+',
    )
    request_id = models.CharField(max_length=128, blank=True, default='', db_index=True)
    before_values = models.JSONField(default=dict, blank=True)
    after_values = models.JSONField(default=dict, blank=True)
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['occurred_at', 'id']

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Location configuration events are append-only.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Location configuration events cannot be deleted.')


class LocationMappingIssue(models.Model):
    STATUS_OPEN = 'open'
    STATUS_RESOLVED = 'resolved'
    STATUS_IGNORED = 'ignored'
    STATUS_CHOICES = [
        (STATUS_OPEN, 'Open'), (STATUS_RESOLVED, 'Resolved'), (STATUS_IGNORED, 'Ignored'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    location_type = models.CharField(max_length=20, choices=OperationalLocation.LOCATION_TYPES, db_index=True)
    raw_value = models.CharField(max_length=255)
    normalized_value = models.CharField(max_length=180, db_index=True)
    source_workflow = models.CharField(max_length=40, db_index=True)
    source_model = models.CharField(max_length=120)
    source_field = models.CharField(max_length=80)
    source_record_id = models.CharField(max_length=120)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_OPEN, db_index=True)
    location = models.ForeignKey(
        OperationalLocation, null=True, blank=True, on_delete=models.PROTECT,
        related_name='mapping_issues',
    )
    detail = models.TextField(blank=True, default='')
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name='+',
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(
            fields=['location_type', 'normalized_value', 'source_model', 'source_field', 'source_record_id'],
            condition=models.Q(status='open'), name='unique_open_location_mapping_issue',
        )]

    def clean(self):
        super().clean()
        if self.location_id and self.location.location_type != self.location_type:
            raise ValidationError({'location': 'Choose a canonical location with the same type.'})
        if self.status == self.STATUS_RESOLVED and not self.location_id:
            raise ValidationError({'location': 'Choose the canonical location before resolving this issue.'})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


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
    generation_request_id = models.CharField(
        max_length=128,
        blank=True,
        default='',
        db_index=True,
        help_text='Mini App retry key for the committed requisition generation.',
    )
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
        constraints = [
            models.UniqueConstraint(
                fields=['generation_request_id'],
                condition=~models.Q(generation_request_id=''),
                name='unique_requisition_batch_generation_request',
            ),
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
        ('superseded', 'Superseded'),
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


class InvoiceIdentityReview(models.Model):
    """Append-oriented decision about invoice identity versus the JBL applicant."""

    STATUS_PENDING = 'pending'
    STATUS_SAME_PERSON = 'same_person_confirmed'
    STATUS_DIFFERENT_PERSON = 'different_person_confirmed'
    STATUS_INSUFFICIENT = 'insufficient_information'
    STATUS_FLAGGED = 'flagged_for_review'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending verification'),
        (STATUS_SAME_PERSON, 'Same person confirmed'),
        (STATUS_DIFFERENT_PERSON, 'Different person confirmed'),
        (STATUS_INSUFFICIENT, 'Insufficient information'),
        (STATUS_FLAGGED, 'Flagged for specialist review'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    invoice = models.ForeignKey(ParsedInvoice, on_delete=models.CASCADE, related_name='identity_reviews')
    farmer = models.ForeignKey(JawabuFarmerMaster, on_delete=models.CASCADE, related_name='invoice_identity_reviews')
    status = models.CharField(max_length=40, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True)
    discrepancy_codes = models.JSONField(blank=True, default=list)
    invoice_identity = models.JSONField(blank=True, default=dict)
    applicant_identity = models.JSONField(blank=True, default=dict)
    decision_note = models.TextField(blank=True, default='')
    decided_by = models.CharField(max_length=255, blank=True, default='')
    decided_at = models.DateTimeField(null=True, blank=True)
    client_request_id = models.CharField(max_length=128, blank=True, default='', db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['invoice'],
                condition=models.Q(status='pending'),
                name='unique_pending_invoice_identity_review',
            ),
            models.UniqueConstraint(
                fields=['client_request_id'],
                condition=~models.Q(client_request_id=''),
                name='unique_invoice_identity_review_request',
            ),
        ]


class JawabuRelatedPerson(models.Model):
    """A spouse/household member kept distinct from the applicant identity."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    linked_customer = models.ForeignKey(
        JawabuCustomer, on_delete=models.SET_NULL, null=True, blank=True, related_name='related_person_profiles'
    )
    full_name = models.CharField(max_length=255)
    national_id = models.CharField(max_length=64, blank=True, default='', db_index=True)
    primary_phone = models.CharField(max_length=64, blank=True, default='', db_index=True)
    source = models.CharField(max_length=255, blank=True, default='operations_verification')
    created_by = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class JawabuHouseholdRelationship(models.Model):
    """Verified relationship used to explain an invoice issued to another person."""

    STATUS_CONFIRMED = 'confirmed'
    STATUS_REVOKED = 'revoked'
    STATUS_CHOICES = [(STATUS_CONFIRMED, 'Confirmed'), (STATUS_REVOKED, 'Revoked')]
    TYPE_CHOICES = [('spouse', 'Spouse'), ('household_member', 'Household member')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    farmer = models.ForeignKey(JawabuFarmerMaster, on_delete=models.CASCADE, related_name='household_relationships')
    related_person = models.ForeignKey(JawabuRelatedPerson, on_delete=models.PROTECT, related_name='relationships')
    relationship_type = models.CharField(max_length=32, choices=TYPE_CHOICES, default='spouse')
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_CONFIRMED, db_index=True)
    attestation_note = models.TextField()
    evidence_reference = models.CharField(max_length=1000)
    confirmed_by = models.CharField(max_length=255)
    confirmed_at = models.DateTimeField(default=timezone.now)
    revoked_by = models.CharField(max_length=255, blank=True, default='')
    revoked_at = models.DateTimeField(null=True, blank=True)
    revocation_reason = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['farmer', 'related_person', 'relationship_type'],
                condition=models.Q(status='confirmed'),
                name='unique_confirmed_household_relationship',
            ),
        ]


class InvoiceNameChangeBatch(models.Model):
    """One manual/generated letter covering one or more invoice corrections."""

    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('sent_to_hb', 'Sent to HB'),
        ('awaiting_replacements', 'Awaiting replacements'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('withdrawn', 'Withdrawn'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reference = models.CharField(max_length=128, blank=True, default='', db_index=True)
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default='draft', db_index=True)
    letter_file_reference = models.CharField(max_length=1000, blank=True, default='')
    letter_checksum = models.CharField(max_length=128, blank=True, default='')
    sent_artifact = models.ForeignKey(
        'InvoiceNameChangeLetterArtifact', on_delete=models.PROTECT, null=True, blank=True,
        related_name='sent_for_batches',
    )
    legacy_manual_letter_allowed = models.BooleanField(
        default=False,
        help_text='Migration-only compatibility for draft letters created before governed DOCX generation.',
    )
    sent_reference = models.CharField(max_length=255, blank=True, default='')
    created_by = models.CharField(max_length=255)
    sent_by = models.CharField(max_length=255, blank=True, default='')
    sent_at = models.DateTimeField(null=True, blank=True)
    revision = models.PositiveIntegerField(default=1)
    client_request_id = models.CharField(max_length=128, blank=True, default='', db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['client_request_id'], condition=~models.Q(client_request_id=''),
                name='unique_invoice_name_change_batch_request',
            ),
        ]


class InvoiceNameChangeLetterTemplate(models.Model):
    """Admin-governed DOCX template for invoice-name-change letters."""

    TEMPLATE_KEY = 'invoice_name_change'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    template_key = models.CharField(max_length=64, default=TEMPLATE_KEY, editable=False)
    name = models.CharField(max_length=255, default='Request for Change of Invoice Names')
    file = models.FileField(
        upload_to='invoice_name_change_templates/',
        help_text='Upload a validated Microsoft Word (.docx) letter template.',
    )
    original_filename = models.CharField(max_length=255, blank=True, default='')
    content_type = models.CharField(
        max_length=255,
        default='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    )
    size = models.PositiveIntegerField(default=0)
    checksum = models.CharField(max_length=64, blank=True, default='')
    drive_file_id = models.CharField(max_length=255, blank=True, default='')
    drive_url = models.URLField(max_length=1000, blank=True, default='')
    drive_uploaded_at = models.DateTimeField(null=True, blank=True)
    drive_upload_error = models.TextField(blank=True, default='')
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_active', '-updated_at']
        constraints = [
            models.UniqueConstraint(
                fields=['template_key'], condition=models.Q(is_active=True),
                name='unique_active_invoice_name_change_template',
            ),
        ]
        verbose_name = 'Invoice name change letter template'
        verbose_name_plural = 'Invoice name change letter templates'

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.is_active:
                type(self).objects.filter(
                    template_key=self.template_key, is_active=True,
                ).exclude(pk=self.pk).update(is_active=False, updated_at=timezone.now())
            super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({'Active' if self.is_active else 'Archived'})"


class InvoiceNameChangeLetterArtifact(models.Model):
    """Immutable, versioned DOCX rendered from one name-change batch snapshot."""

    STATUS_GENERATED = 'generated'
    STATUS_UPLOAD_FAILED = 'upload_failed'
    STATUS_CHOICES = [
        (STATUS_GENERATED, 'Generated'),
        (STATUS_UPLOAD_FAILED, 'Drive upload failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(
        InvoiceNameChangeBatch, on_delete=models.PROTECT, related_name='letter_artifacts',
    )
    template = models.ForeignKey(
        InvoiceNameChangeLetterTemplate, on_delete=models.PROTECT,
        related_name='generated_artifacts',
    )
    version = models.PositiveIntegerField()
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_GENERATED, db_index=True)
    filename = models.CharField(max_length=255)
    content_type = models.CharField(
        max_length=255,
        default='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    )
    file_content = models.BinaryField(blank=True, default=bytes)
    checksum = models.CharField(max_length=64)
    template_checksum = models.CharField(max_length=64)
    source_fingerprint = models.CharField(max_length=64, db_index=True)
    payload_snapshot = models.JSONField(default=dict)
    generated_by = models.CharField(max_length=255)
    generated_at = models.DateTimeField(default=timezone.now)
    client_request_id = models.CharField(max_length=128, blank=True, default='', db_index=True)
    drive_file_id = models.CharField(max_length=255, blank=True, default='')
    drive_url = models.URLField(max_length=1000, blank=True, default='')
    drive_upload_error = models.TextField(blank=True, default='')
    drive_sync_attempts = models.PositiveIntegerField(default=0)
    drive_last_sync_at = models.DateTimeField(null=True, blank=True)
    drive_next_retry_at = models.DateTimeField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-version', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['batch', 'version'], name='unique_invoice_name_change_letter_version',
            ),
            models.UniqueConstraint(
                fields=['batch', 'client_request_id'],
                condition=~models.Q(client_request_id=''),
                name='unique_invoice_name_change_letter_request',
            ),
        ]
        verbose_name = 'Invoice name change letter artifact'
        verbose_name_plural = 'Invoice name change letter artifacts'

    IMMUTABLE_FIELDS = (
        'batch_id', 'template_id', 'version', 'filename', 'content_type',
        'file_content', 'checksum', 'template_checksum', 'source_fingerprint',
        'payload_snapshot', 'generated_by', 'generated_at', 'client_request_id',
    )

    def save(self, *args, **kwargs):
        if self.pk and not self._state.adding:
            original = type(self).objects.filter(pk=self.pk).values(*self.IMMUTABLE_FIELDS).first()
            if original:
                for field in self.IMMUTABLE_FIELDS:
                    current = getattr(self, field)
                    previous = original[field]
                    if field == 'file_content':
                        current = bytes(current or b'')
                        previous = bytes(previous or b'')
                    if current != previous:
                        raise ValidationError('Generated invoice-name-change letter artifacts are immutable.')
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.batch.reference or self.batch_id} v{self.version}'


class InvoiceNameChangeItem(models.Model):
    """A case-level correction preserving original and replacement invoices."""

    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('awaiting_replacement', 'Awaiting replacement'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('withdrawn', 'Withdrawn'),
    ]
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    batch = models.ForeignKey(
        InvoiceNameChangeBatch, on_delete=models.PROTECT, related_name='items', null=True, blank=True,
    )
    review = models.OneToOneField(InvoiceIdentityReview, on_delete=models.PROTECT, related_name='name_change_item')
    farmer = models.ForeignKey(JawabuFarmerMaster, on_delete=models.PROTECT, related_name='invoice_name_changes')
    relationship = models.ForeignKey(JawabuHouseholdRelationship, on_delete=models.PROTECT, related_name='invoice_name_changes')
    original_invoice = models.ForeignKey(ParsedInvoice, on_delete=models.PROTECT, related_name='name_change_requests')
    replacement_invoice = models.ForeignKey(
        ParsedInvoice, on_delete=models.PROTECT, null=True, blank=True, related_name='replacement_for_name_changes'
    )
    status = models.CharField(max_length=32, choices=STATUS_CHOICES, default='draft', db_index=True)
    original_identity = models.JSONField(blank=True, default=dict)
    requested_identity = models.JSONField(blank=True, default=dict)
    completed_by = models.CharField(max_length=255, blank=True, default='')
    completed_at = models.DateTimeField(null=True, blank=True)
    closed_reason = models.TextField(blank=True, default='')
    hb_communication_reference = models.CharField(max_length=255, blank=True, default='')
    closed_by = models.CharField(max_length=255, blank=True, default='')
    closed_at = models.DateTimeField(null=True, blank=True)
    follow_up_of = models.ForeignKey(
        'self', on_delete=models.PROTECT, null=True, blank=True, related_name='follow_ups',
    )
    client_request_id = models.CharField(max_length=128, blank=True, default='', db_index=True)
    revision = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['original_invoice'],
                condition=models.Q(status__in=['draft', 'awaiting_replacement']),
                name='unique_open_invoice_name_change',
            ),
            models.UniqueConstraint(
                fields=['client_request_id'], condition=~models.Q(client_request_id=''),
                name='unique_invoice_name_change_item_request',
            ),
        ]


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
    """Maker-checker controlled Portal roles allowed to attest physical sign-off."""

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
    # ``approval_role`` remains as a stable compatibility pointer for earlier
    # audit snapshots and integrations.  Effective authorization uses
    # ``approval_roles`` so a document type can deliberately name more than
    # one accountable operational role.
    approval_role = models.CharField(max_length=80)
    approval_roles = models.JSONField(default=list, blank=True)
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
        raw_roles = self.approval_roles or [self.approval_role]
        if isinstance(raw_roles, str):
            raw_roles = [raw_roles]
        if not isinstance(raw_roles, (list, tuple, set)):
            raise ValidationError({'approval_roles': 'Select one or more Portal roles.'})
        roles = []
        for raw_role in raw_roles:
            role = validate_access_scope(workflow=self.workflow, role=str(raw_role or ''))
            if role not in roles:
                roles.append(role)
        if not roles:
            raise ValidationError({'approval_roles': 'Select at least one Portal role.'})
        self.approval_roles = roles
        self.approval_role = roles[0]

    @property
    def effective_approval_roles(self) -> tuple[str, ...]:
        """Return the multi-role policy while preserving pre-migration rows."""
        values = self.approval_roles or [self.approval_role]
        return tuple(str(value).strip() for value in values if str(value).strip())

    def __str__(self):
        return f'{self.get_document_type_display()}: {", ".join(self.effective_approval_roles)}'


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
    INTEGRATION_AFRICAS_TALKING = 'africas_talking'
    INTEGRATION_CHOICES = [
        (INTEGRATION_GOOGLE_SHEETS, 'Google Sheets'),
        (INTEGRATION_GOOGLE_DRIVE, 'Google Drive'),
        (INTEGRATION_TELEGRAM, 'Telegram'),
        (INTEGRATION_AFRICAS_TALKING, "Africa's Talking"),
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


class MiniAppDiagnosticSession(models.Model):
    """Privacy-safe lifecycle evidence for one staff Mini App launch."""

    CLASSIFICATION_ACTIVE = 'active_visible'
    CLASSIFICATION_BACKGROUNDED = 'backgrounded'
    CLASSIFICATION_BACKGROUND_NOT_RESUMED = 'backgrounded_not_resumed'
    CLASSIFICATION_INTENTIONAL_CLOSE = 'intentional_close'
    CLASSIFICATION_CLIENT_ERROR = 'client_error_suspected'
    CLASSIFICATION_STARTUP_FAILURE = 'startup_failure'
    CLASSIFICATION_NAVIGATION = 'navigation_or_native_dismissal'
    CLASSIFICATION_STALE = 'stale_unconfirmed'
    CLASSIFICATION_ABRUPT = 'abrupt_unknown_confirmed'
    CLASSIFICATION_CHOICES = [
        (CLASSIFICATION_ACTIVE, 'Active and visible'),
        (CLASSIFICATION_BACKGROUNDED, 'Backgrounded'),
        (CLASSIFICATION_BACKGROUND_NOT_RESUMED, 'Backgrounded and not resumed'),
        (CLASSIFICATION_INTENTIONAL_CLOSE, 'Intentional close'),
        (CLASSIFICATION_CLIENT_ERROR, 'Client error suspected'),
        (CLASSIFICATION_STARTUP_FAILURE, 'Startup failure'),
        (CLASSIFICATION_NAVIGATION, 'Navigation or native dismissal'),
        (CLASSIFICATION_STALE, 'Stale and unconfirmed'),
        (CLASSIFICATION_ABRUPT, 'Abrupt unknown, confirmed on later launch'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client_session_uuid = models.UUIDField(unique=True, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='miniapp_diagnostic_sessions',
    )
    workflow = models.CharField(max_length=40, choices=AccessGrant.WORKFLOW_CHOICES, db_index=True)
    surface = models.CharField(max_length=40, db_index=True)
    release = models.CharField(max_length=80, blank=True, default='', db_index=True)
    platform = models.CharField(max_length=16, default='other', db_index=True)
    network_bucket = models.CharField(max_length=16, default='unknown', db_index=True)
    device_memory_bucket = models.CharField(max_length=16, default='unknown', db_index=True)
    classification = models.CharField(
        max_length=40, choices=CLASSIFICATION_CHOICES,
        default=CLASSIFICATION_ACTIVE, db_index=True,
    )
    last_visibility = models.CharField(max_length=12, default='visible')
    recovered_on_later_launch = models.BooleanField(default=False, db_index=True)
    started_at = models.DateTimeField(auto_now_add=True, db_index=True)
    last_signal_at = models.DateTimeField(auto_now_add=True, db_index=True)
    ended_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['workflow', 'platform', 'started_at']),
            models.Index(fields=['classification', 'started_at']),
        ]
        verbose_name = 'Mini App diagnostic session'
        verbose_name_plural = 'Mini App diagnostic sessions'

    def __str__(self):
        return f'{self.surface} {self.client_session_uuid} ({self.classification})'


class MiniAppDiagnosticEvent(models.Model):
    """Append-oriented, allowlisted signal; arbitrary client payloads are rejected."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        MiniAppDiagnosticSession, on_delete=models.CASCADE, related_name='events',
    )
    client_event_uuid = models.UUIDField()
    event_type = models.CharField(max_length=40, db_index=True)
    elapsed_ms = models.PositiveIntegerField(default=0)
    route = models.CharField(max_length=80, blank=True, default='')
    action = models.CharField(max_length=80, blank=True, default='')
    visibility = models.CharField(max_length=12, default='visible')
    online = models.BooleanField(default=True)
    network_bucket = models.CharField(max_length=16, default='unknown')
    status_bucket = models.CharField(max_length=24, blank=True, default='')
    request_id = models.CharField(max_length=128, blank=True, default='', db_index=True)
    recorded_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['session', 'elapsed_ms', 'recorded_at']
        constraints = [
            models.UniqueConstraint(
                fields=['session', 'client_event_uuid'],
                name='unique_miniapp_diagnostic_client_event',
            ),
        ]
        indexes = [
            models.Index(fields=['session', 'recorded_at']),
            models.Index(fields=['event_type', 'recorded_at']),
        ]
        verbose_name = 'Mini App diagnostic event'
        verbose_name_plural = 'Mini App diagnostic events'

    def __str__(self):
        return f'{self.session.surface}: {self.event_type}'


class MiniAppDiagnosticDailyAggregate(models.Model):
    """Longer-lived anonymous counts rolled up before raw diagnostics expire."""

    date = models.DateField(db_index=True)
    workflow = models.CharField(max_length=40, db_index=True)
    surface = models.CharField(max_length=40, db_index=True)
    platform = models.CharField(max_length=16, db_index=True)
    release = models.CharField(max_length=80, blank=True, default='', db_index=True)
    classification = models.CharField(max_length=40, db_index=True)
    network_bucket = models.CharField(max_length=16, default='unknown', db_index=True)
    session_count = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date', 'workflow', 'platform', 'classification']
        constraints = [
            models.UniqueConstraint(
                fields=[
                    'date', 'workflow', 'surface', 'platform', 'release',
                    'classification', 'network_bucket',
                ],
                name='unique_miniapp_diagnostic_daily_rollup',
            ),
        ]
        verbose_name = 'Mini App diagnostic daily aggregate'
        verbose_name_plural = 'Mini App diagnostic daily aggregates'

    def __str__(self):
        return f'{self.date} {self.surface}/{self.platform}: {self.classification}'
