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


class LegacyUpload(models.Model):
    """Private, resumable cutover version. Retain committed provenance; no automatic purge."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Opaque upload/cutover reference.')
    batch = models.ForeignKey(LegacyBatch, on_delete=models.PROTECT, related_name='uploads', db_comment='Owning group and stable import namespace.')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='legacy_uploads', db_comment='Staff accountable for source upload.')
    filename = models.CharField(max_length=200, db_comment='Private original filename, never a filesystem path.')
    digest = models.CharField(max_length=64, db_comment='Expected SHA256, verified against retained chunks.')
    source_sheet = models.CharField(max_length=32, choices=[('Master Data','Master Data'),('Eco-conserve','Eco-conserve')], default='Master Data', db_comment='Immutable selected source register; binds decoding, cleanup, partner and projection destination.')
    size = models.PositiveIntegerField(db_comment='Expected compressed XLSX bytes, at most 20 MiB.')
    phase = models.CharField(max_length=24, default='uploading', db_comment='Server-owned resumable processing state.')
    state = models.JSONField(default=dict, db_comment='Mapping, cursor, deletion manifest, publication checkpoints and recovery evidence.')
    revision = models.PositiveIntegerField(default=1, db_comment='Optimistic concurrency for operator commands.')
    lease = models.UUIDField(null=True, blank=True, db_comment='Exclusive expiring advance owner; never workflow authority.')
    lease_until = models.DateTimeField(null=True, blank=True, db_comment='Expiry allowing recovery after worker termination.')
    frozen = models.BooleanField(default=False, db_comment='Group write fence during the approved cutover.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='Actual upload time, not historical case activity.')

    class Meta:
        db_table = 'portal_legacy_upload_session'
        db_table_comment = 'Authoritative private upload and cutover checkpoints; retained with import evidence.'
        constraints = [models.UniqueConstraint(fields=['batch','digest','source_sheet'], name='portal_legacy_upload_source_unique'),
                       models.CheckConstraint(condition=models.Q(source_sheet__in=['Master Data','Eco-conserve']), name='portal_legacy_upload_source_valid')]


class LegacyChunk(models.Model):
    upload = models.ForeignKey(LegacyUpload, on_delete=models.CASCADE, related_name='chunks', db_comment='Private upload owning these bounded bytes.')
    kind = models.CharField(max_length=16, default='source', db_comment='Source XLSX or recoverable Master Data snapshot.')
    position = models.PositiveIntegerField(db_comment='Stable zero-based chunk position.')
    content = models.BinaryField(db_comment='Private bounded source/snapshot bytes; never logged.')
    digest = models.CharField(max_length=64, db_comment='SHA256 for identical replay and corruption detection.')

    class Meta:
        db_table = 'portal_legacy_chunk_evidence'
        db_table_comment = 'Retained private source/snapshot chunks; disposable caches are reconstructed from these bytes.'
        constraints = [models.UniqueConstraint(fields=['upload','kind','position'], name='portal_legacy_chunk_position_unique')]


class LegacyDraft(models.Model):
    upload = models.ForeignKey(LegacyUpload, on_delete=models.CASCADE, related_name='drafts', db_comment='Isolated source version; never replaces a ready predecessor.')
    source_row = models.PositiveIntegerField(db_comment='Original Master Data row identity, not projected destination row.')
    values = models.JSONField(default=dict, db_comment='Reviewed historical facts, including namespaced legacy-only fields.')
    proposal = models.JSONField(default=dict, db_comment='Canonical candidates and row review issues.')
    approved = models.BooleanField(default=False, db_comment='Explicit IT selection, retained across page navigation.')
    reconciliation = models.JSONField(default=dict, db_comment='Exact existing-case link or separate-unit explanation.')
    legacy = models.ForeignKey('LegacyRow', null=True, blank=True, on_delete=models.SET_NULL, related_name='draft_versions', db_comment='Committed canonical provenance; absent until explicit commit.')

    class Meta:
        db_table = 'portal_legacy_draft_record'
        db_table_comment = 'Version-isolated review drafts; retained with source evidence or explicitly discarded before commit.'
        constraints = [models.UniqueConstraint(fields=['upload','source_row'], name='portal_legacy_draft_source_unique')]


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
