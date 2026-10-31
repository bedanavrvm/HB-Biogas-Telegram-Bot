"""Retained changeover evidence; never a second workflow database."""
import uuid
from django.conf import settings
from django.db import models


class LegacyBatch(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Stable cutover batch identity.')
    group = models.ForeignKey('core.GroupSheetConfiguration', on_delete=models.PROTECT, related_name='legacy_batches', db_comment='Exact Portal owner; never inferred from workbook contents.')
    namespace = models.SlugField(max_length=100, db_comment='Operator-chosen stable namespace retained across retries and corrected files.')
    source_hash = models.CharField(max_length=64, db_comment='SHA256 of the reviewed workbook version.')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='portal_legacy_batches', db_comment='Staff member who staged this import, not a historical decision maker.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='Actual import staging time, never an operational milestone date.')

    class Meta:
        db_table = 'portal_legacy_batch_root'
        db_table_comment = 'Retained group-scoped changeover source manifest; authoritative import provenance.'
        constraints = [models.UniqueConstraint(fields=['group', 'namespace'], name='portal_legacy_namespace_unique')]


class LegacyRow(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Stable import row identity.')
    batch = models.ForeignKey(LegacyBatch, on_delete=models.PROTECT, related_name='rows', db_comment='Retained source batch.')
    source_sheet = models.CharField(max_length=128, db_comment='Original source tab identity, independent of column positions.')
    source_row = models.PositiveIntegerField(db_comment='Retained original row number, not the edited workbook position.')
    source_hash = models.CharField(max_length=64, db_comment='Workbook version supplying this row snapshot.')
    values = models.JSONField(default=dict, db_comment='Private reviewed source values; preserved even when a canonical value is unknown.')
    proposal = models.JSONField(default=dict, db_comment='Recomputed canonical candidates, state evidence and unresolved issues.')
    farmer = models.ForeignKey('core.JawabuFarmerMaster', null=True, blank=True, on_delete=models.PROTECT, related_name='legacy_records', db_comment='Canonical case created by or explicitly reconciled with this row.')
    revision = models.PositiveIntegerField(default=1, db_comment='Optimistic concurrency revision for review and commit.')
    committed_at = models.DateTimeField(null=True, blank=True, db_comment='Import commit time; never the historical case activity date.')
    continuation_confirmed = models.BooleanField(default=False, db_comment='Whether a known or audited continuation stage is established.')
    publication_ready = models.BooleanField(default=False, db_comment='Default-off until live Sheet row bindings have been reviewed.')

    class Meta:
        db_table = 'portal_legacy_row_record'
        db_table_comment = 'Immutable committed source facts and per-case historical exceptions; retain with the operational case.'
        constraints = [models.UniqueConstraint(fields=['batch', 'source_sheet', 'source_row'], name='portal_legacy_source_unique')]


class LegacyEvent(models.Model):
    id = models.BigAutoField(primary_key=True, db_comment='Immutable import audit event identity.')
    row = models.ForeignKey(LegacyRow, on_delete=models.PROTECT, related_name='events', db_comment='Source row whose import/reconciliation changed.')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='portal_legacy_events', db_comment='Current staff accountable for this action, not the historical actor.')
    request_key = models.CharField(max_length=128, db_comment='Idempotency key bound to this exact row and action payload.')
    action = models.CharField(max_length=40, db_comment='Import, explicit linkage or stage confirmation.')
    payload = models.JSONField(default=dict, db_comment='Exact reviewed action facts and source evidence, including before/after values.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='Actual audited action time.')

    class Meta:
        db_table = 'portal_legacy_event_audit'
        db_table_comment = 'Append-only changeover audit; retained with import evidence.'
        constraints = [models.UniqueConstraint(fields=['row', 'request_key'], name='portal_legacy_request_unique')]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            from django.core.exceptions import ValidationError
            raise ValidationError('Legacy audit events are append-only.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        from django.core.exceptions import ValidationError
        raise ValidationError('Retain legacy audit evidence with its case.')
