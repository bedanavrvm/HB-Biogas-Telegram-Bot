from django.conf import settings
from django.db import models


class OrderSequenceState(models.Model):
    """Canonical, group-scoped allocator for official requisition numbers.

    This is durable operational configuration retained for the life of the
    group. Django is the source of truth; printed paperwork is reconciled by
    an attributed IT adjustment and never by silently inspecting Sheets.
    """

    id = models.BigAutoField(primary_key=True, db_comment='Internal sequence-state identifier.')
    group_configuration = models.OneToOneField(
        'core.GroupSheetConfiguration',
        on_delete=models.PROTECT,
        related_name='requisition_order_sequence',
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
