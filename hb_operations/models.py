import uuid

from django.conf import settings
from django.db import models


class HomeBiogasAction(models.Model):
    """Current HomeBiogas fulfilment state for one canonical Portal case."""

    INSTALLATION_NEEDS_PLANNING = 'needs_planning'
    INSTALLATION_PENDING = 'pending_installation'
    INSTALLATION_SCHEDULED = 'scheduled'
    INSTALLATION_INSTALLED = 'installed'
    INSTALLATION_CLOSED = 'closed'
    INSTALLATION_CHOICES = [
        (INSTALLATION_NEEDS_PLANNING, 'Needs planning'),
        (INSTALLATION_PENDING, 'Pending installation'),
        (INSTALLATION_SCHEDULED, 'Scheduled'),
        (INSTALLATION_INSTALLED, 'Installed'),
        (INSTALLATION_CLOSED, 'Closed'),
    ]

    READINESS_READY = 'ready'
    READINESS_NOT_READY = 'not_ready'
    READINESS_NOT_CONFIRMED = 'not_confirmed'
    READINESS_CHOICES = [
        (READINESS_READY, 'Ready'),
        (READINESS_NOT_READY, 'Not ready'),
        (READINESS_NOT_CONFIRMED, 'Not confirmed'),
    ]

    REPORT_YES = 'yes'
    REPORT_NO = 'no'
    REPORT_NOT_APPLICABLE = 'not_applicable'
    REPORT_CHOICES = [
        (REPORT_YES, 'Yes'),
        (REPORT_NO, 'No'),
        (REPORT_NOT_APPLICABLE, 'Not applicable'),
    ]

    COMMISSIONING_PENDING = 'pending'
    COMMISSIONING_DONE = 'done'
    COMMISSIONING_CHOICES = [
        (COMMISSIONING_PENDING, 'Pending'),
        (COMMISSIONING_DONE, 'Done'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Immutable HomeBiogas action identifier.')
    farmer = models.OneToOneField(
        'core.JawabuFarmerMaster', on_delete=models.PROTECT, related_name='homebiogas_action',
        db_comment='Canonical Portal case being installed and commissioned.',
    )
    source_requisition_batch = models.ForeignKey(
        'core.RequisitionBatch', on_delete=models.PROTECT, related_name='homebiogas_actions',
        db_comment='Exact finalized requisition batch that released this case to HomeBiogas.',
    )
    source_signoff = models.ForeignKey(
        'core.DocumentPhysicalSignoff', on_delete=models.PROTECT, related_name='homebiogas_actions',
        db_comment='Accepted signed and stamped requisition scan that released this case.',
    )
    source_order_number = models.CharField(max_length=128, db_comment='Immutable staff-facing order number captured at release.')
    source_requisition_version = models.PositiveIntegerField(db_comment='Exact finalized requisition version captured at release.')
    installation_status = models.CharField(
        max_length=32, choices=INSTALLATION_CHOICES, default=INSTALLATION_NEEDS_PLANNING,
        db_comment='Current server-validated installation state.',
    )
    installation_date = models.DateField(
        null=True, blank=True,
        db_comment='Scheduled date while scheduled, or actual completion date while installed.',
    )
    serial_number = models.CharField(max_length=128, blank=True, default='', db_comment='Optional manufacturer serial number retained as text.')
    readiness_status = models.CharField(max_length=24, choices=READINESS_CHOICES, blank=True, default='', db_comment='Structured readiness state for pending or scheduled installation.')
    pending_installation_comment = models.TextField(blank=True, default='', db_comment='Operational explanation while installation is pending or scheduled.')
    installation_report_status = models.CharField(max_length=24, choices=REPORT_CHOICES, blank=True, default='', db_comment='Whether the installation report was submitted to Jawabu.')
    commissioning_status = models.CharField(max_length=16, choices=COMMISSIONING_CHOICES, blank=True, default='', db_comment='Current commissioning state after installation.')
    commissioning_date = models.DateField(null=True, blank=True, db_comment='Scheduled date while pending, or actual completion date when commissioning is done.')
    pending_commissioning_comment = models.TextField(blank=True, default='', db_comment='Operational explanation while commissioning is pending.')
    revision = models.PositiveBigIntegerField(default=1, db_comment='Optimistic concurrency revision incremented by every accepted mutation.')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', db_comment='Staff actor whose accepted signoff released this record.')
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', db_comment='Staff actor responsible for the latest accepted change.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='When the accepted requisition released this case to HomeBiogas.')
    updated_at = models.DateTimeField(auto_now=True, db_comment='When the latest accepted HomeBiogas action was saved.')

    class Meta:
        db_table = 'hb_operations_action_root'
        db_table_comment = 'Django source of truth for post-order HomeBiogas installation and commissioning work.'
        ordering = ['-updated_at']
        indexes = [models.Index(fields=['installation_status', 'updated_at'], name='hb_action_status_updated_idx')]


class HomeBiogasActionEvent(models.Model):
    """Append-only audit evidence for release, progression, and corrections."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Immutable HomeBiogas action event identifier.')
    action = models.ForeignKey(HomeBiogasAction, on_delete=models.PROTECT, related_name='events', db_comment='HomeBiogas record changed by this event.')
    event_type = models.CharField(max_length=48, db_comment='Stable machine-readable release, transition, or correction action.')
    revision = models.PositiveBigIntegerField(db_comment='Record revision produced or observed by this event.')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', db_comment='Staff actor responsible for this event.')
    actor_label = models.CharField(max_length=255, blank=True, default='', db_comment='Immutable display label retained if the staff account later changes.')
    request_id = models.CharField(max_length=128, blank=True, default='', db_comment='Idempotency key for user or internal retries.')
    previous_values = models.JSONField(default=dict, blank=True, db_comment='Allowlisted prior operational values for audit interpretation.')
    new_values = models.JSONField(default=dict, blank=True, db_comment='Allowlisted accepted operational values for audit interpretation.')
    reason = models.TextField(blank=True, default='', db_comment='Required reason for consequential milestone corrections.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='When this immutable event was recorded.')

    class Meta:
        db_table = 'hb_operations_action_event'
        db_table_comment = 'Append-only audit history for HomeBiogas installation and commissioning actions.'
        ordering = ['created_at', 'pk']
        constraints = [
            models.UniqueConstraint(
                fields=['action', 'request_id'], condition=~models.Q(request_id=''),
                name='unique_hb_action_request',
            ),
        ]

