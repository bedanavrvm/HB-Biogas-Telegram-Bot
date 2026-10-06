from django.conf import settings
from django.db import models


class OrderSequenceState(models.Model):
    """Canonical, group-scoped allocator for official requisition numbers.

    This is durable operational configuration retained for the life of the
    group. Django is the source of truth; printed paperwork is reconciled by
    an attributed IT adjustment and never by silently inspecting Sheets.
    """

    id = models.BigAutoField(primary_key=True, db_comment='Internal sequence-state identifier.')
    partner = models.CharField(
        max_length=20,
        choices=[('HB', 'HB'), ('ECOCONSERVE', 'Eco-conserve')],
        default='HB',
        db_comment='Fulfilment partner whose official order numbers this sequence governs.',
    )
    group_configuration = models.ForeignKey(
        'core.GroupSheetConfiguration',
        on_delete=models.PROTECT,
        related_name='requisition_order_sequences',
        db_comment='Jawabu group whose official paper numbering this sequence governs.',
    )
    next_number = models.PositiveBigIntegerField(db_comment='Next plain numeric order number available for finalization.')
    revision = models.PositiveBigIntegerField(default=1, db_comment='Optimistic concurrency revision for sequence changes.')
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
        db_comment='Staff user who most recently adjusted or consumed the sequence.',
    )
    adjustment_reason = models.TextField(blank=True, default='', db_comment='Reason for the latest attributed sequence change.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='Time this group sequence was initialized.')
    updated_at = models.DateTimeField(auto_now=True, db_comment='Time the sequence was last adjusted or consumed.')

    class Meta:
        db_table = 'requisition_order_sequence_state'
        db_table_comment = 'Group-scoped source of truth for the next official requisition order number.'
        verbose_name = 'Requisition order sequence'
        verbose_name_plural = 'Requisition order sequences'
        constraints = [
            models.UniqueConstraint(
                fields=['group_configuration', 'partner'],
                name='unique_requisition_sequence_partner',
            ),
        ]


class OrderSequenceEvent(models.Model):
    """Immutable, customer-data-free evidence for each sequence mutation."""

    id = models.BigAutoField(primary_key=True, db_comment='Internal immutable event identifier.')
    sequence = models.ForeignKey(OrderSequenceState, on_delete=models.PROTECT, related_name='events', db_comment='Sequence changed by this event.')
    action = models.CharField(max_length=24, db_comment='Whether IT adjusted or finalization consumed a number.')
    number_before = models.PositiveBigIntegerField(db_comment='Next number immediately before the mutation.')
    number_after = models.PositiveBigIntegerField(db_comment='Next number immediately after the mutation.')
    revision_after = models.PositiveBigIntegerField(db_comment='Sequence revision committed by this mutation.')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+', db_comment='Staff user accountable for the mutation.')
    reason = models.TextField(db_comment='Customer-data-free reason for the mutation.')
    request_id = models.CharField(max_length=128, blank=True, default='', db_index=True, db_comment='Idempotency key associated with the mutation.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='Time the mutation committed.')

    class Meta:
        db_table = 'requisition_order_sequence_event'
        db_table_comment = 'Immutable customer-data-free audit trail for official requisition numbering.'
        ordering = ['created_at', 'pk']
        constraints = [models.UniqueConstraint(fields=['request_id'], condition=~models.Q(request_id=''), name='unique_requisition_sequence_event_request')]


class OrderNumberClaim(models.Model):
    """Lifetime allocator slots; only explicit cancellation releases a slot.

    Django is authoritative. Retain with sequence and order audit history;
    there is no time-based purge. Uniqueness provides the allocation index.
    """
    id = models.BigAutoField(primary_key=True, db_comment='Internal number-slot identifier.')
    sequence = models.ForeignKey(OrderSequenceState, on_delete=models.PROTECT, related_name='number_claims', db_comment='Locked group/partner allocator owning this number.')
    number = models.PositiveBigIntegerField(db_comment='Printed numeric component; never a document identity.')
    batch = models.OneToOneField('core.RequisitionBatch', null=True, blank=True, on_delete=models.PROTECT, related_name='number_claim', db_comment='Current owner; null only after explicit release.')

    class Meta:
        db_table = 'requisition_order_number_claim'
        db_table_comment = 'Lifetime authoritative number slots; released slots may be reassigned under the sequence lock.'
        constraints = [models.UniqueConstraint(fields=['sequence', 'number'], name='unique_order_number_claim')]


class OrderWorkbookVersion(models.Model):
    """Immutable local order bytes, retained for the lifetime of finance evidence."""
    id = models.BigAutoField(primary_key=True, db_comment='Internal retained-workbook identifier.')
    batch = models.ForeignKey('core.RequisitionBatch', on_delete=models.PROTECT, related_name='workbook_versions', db_comment='Immutable workspace identity, independent of reused display numbers.')
    version = models.PositiveIntegerField(db_comment='Monotonic workbook version within this workspace.')
    filename = models.CharField(max_length=255, db_comment='Original generated filename.')
    file_content = models.BinaryField(db_comment='Exact immutable generated workbook bytes.')
    checksum = models.CharField(max_length=64, db_comment='SHA-256 binding for these bytes.')
    farmer_ids = models.JSONField(default=list, db_comment='Immutable case UUID membership for these bytes.')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+', db_comment='Staff user who generated this version.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='Generation timestamp.')

    def save(self, *args, **kwargs):
        if not self._state.adding:
            from django.core.exceptions import ValidationError
            raise ValidationError('Retained order versions cannot be edited; generate a new version.')
        return super().save(*args, **kwargs)

    class Meta:
        db_table = 'requisition_order_workbook_version'
        db_table_comment = 'Authoritative immutable workbook versions; lifetime financial evidence, not a Drive cache.'
        constraints = [models.UniqueConstraint(fields=['batch', 'version'], name='unique_order_workbook_version')]


class OrderWorkspaceEvent(models.Model):
    """Append-only workspace changes; lifetime financial evidence, no automatic purge."""
    id = models.BigAutoField(primary_key=True, db_comment='Internal append-only workspace-event identifier.')
    batch = models.ForeignKey('core.RequisitionBatch', on_delete=models.PROTECT, related_name='workspace_events', db_comment='Workspace changed by this event.')
    action = models.CharField(max_length=24, db_comment='Generated, appended or cancelled.')
    version = models.PositiveIntegerField(db_comment='Current workbook version at the change.')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='+', db_comment='Accountable staff user.')
    request_id = models.CharField(max_length=128, db_comment='Idempotency key for this action.')
    metadata = models.JSONField(default=dict, db_comment='Change evidence, including released display numbers and membership.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='Committed change timestamp.')

    def save(self, *args, **kwargs):
        if not self._state.adding:
            from django.core.exceptions import ValidationError
            raise ValidationError('Order workspace history cannot be edited.')
        return super().save(*args, **kwargs)

    class Meta:
        db_table = 'requisition_order_workspace_event'
        db_table_comment = 'Append-only authoritative order workspace audit; retained with financial evidence.'
        constraints = [models.UniqueConstraint(fields=['request_id'], condition=~models.Q(request_id=''), name='unique_order_workspace_request')]
