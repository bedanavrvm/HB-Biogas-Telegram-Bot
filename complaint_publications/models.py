import uuid

from django.conf import settings
from django.db import models


class UploadAttempt(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False,
        db_comment='Opaque upload attempt identity; never supplies authorization.')
    group = models.ForeignKey('core.GroupSheetConfiguration', on_delete=models.CASCADE,
        related_name='complaint_upload_attempts', db_comment='Owning Complaint workspace; no cross-workflow authority.')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL,
        related_name='complaint_upload_attempts', db_comment='Admitted staff uploader; historical reference survives deletion.')
    actor_reference = models.CharField(max_length=50, db_comment='Original actor primary key retained for replay binding.')
    request_key = models.CharField(max_length=128, db_comment='Exact browser command idempotency key.')
    action_path = models.CharField(max_length=160, db_comment='Allowlisted relative native command path.')
    payload_hash = models.CharField(max_length=64, db_comment='Canonical command and ordered file-manifest digest; no customer text.')
    case = models.ForeignKey('core.ParsedMessage', null=True, blank=True, on_delete=models.CASCADE,
        related_name='browser_upload_attempts', db_comment='Committed owning case; null only before a command commits.')
    committed_at = models.DateTimeField(null=True, blank=True, db_comment='Canonical command, bytes and jobs committed together.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='Receipt reservation time; uncommitted attempts expire after 24 hours.')

    class Meta:
        db_table = 'complaints_upload_attempt'
        db_table_comment = 'Authoritative browser upload/replay binding. Uncommitted attempts expire after 24 hours; committed metadata follows complaint retention.'
        constraints = [models.UniqueConstraint(fields=['group', 'actor_reference', 'request_key'], name='complaint_upload_request_once')]
        indexes = [models.Index(fields=['committed_at', 'created_at'], name='cmp_upload_expiry_idx')]


class UploadFile(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False,
        db_comment='Opaque per-file receipt and progress identifier.')
    attempt = models.ForeignKey(UploadAttempt, on_delete=models.CASCADE, related_name='files',
        db_comment='Ordered manifest and command owner; deletion follows its disclosed case closure.')
    position = models.PositiveSmallIntegerField(db_comment='Stable index in the exact submitted file manifest.')
    filename = models.CharField(max_length=255, db_comment='Original display filename; private metadata, never logged.')
    size = models.PositiveIntegerField(db_comment='Validated expected byte size, bounded by Complaint upload limits.')
    content_hash = models.CharField(max_length=64, db_comment='Expected SHA-256, verified at receipt and used for exact retry.')
    mime_type = models.CharField(max_length=255, blank=True, db_comment='Server-detected evidence type, never trusted from the browser.')
    content = models.BinaryField(null=True, blank=True,
        db_comment='Private temporary original bytes. Purged 24 hours after verified Drive publication; unpublished bytes are retained.')
    received_at = models.DateTimeField(null=True, blank=True, db_comment='Validated bytes durably received in Django.')
    evidence = models.ForeignKey('core.ComplaintCaseEvidence', null=True, blank=True, on_delete=models.CASCADE,
        related_name='browser_publications', db_comment='Canonical evidence metadata created in the owning command transaction.')
    operation = models.ForeignKey('core.IntegrationOperation', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='complaint_upload_files', db_comment='Current leased publication attempt; failed attempts remain in the integration ledger.')
    published_bytes = models.PositiveIntegerField(default=0, db_comment='Bytes acknowledged by the current Drive resumable session.')
    published_at = models.DateTimeField(null=True, blank=True, db_comment='Verified remote result committed; starts the 24-hour temporary-byte retention clock.')
    purge_after = models.DateTimeField(null=True, blank=True, db_comment='Earliest permitted deletion of the successful temporary payload.')
    resumable_uri = models.TextField(blank=True, default='', db_comment='Private Drive resumable session URL, never serialized, logged or exposed in Admin.')
    updated_at = models.DateTimeField(auto_now=True, db_comment='Latest durable progress or receipt change.')

    class Meta:
        db_table = 'complaints_upload_file'
        db_table_comment = 'Durable browser evidence staging and measured publication progress. Source bytes until publication, then a 24-hour cache; metadata follows complaint retention.'
        constraints = [models.UniqueConstraint(fields=['attempt', 'position'], name='complaint_upload_position_once')]
        indexes = [models.Index(fields=['purge_after'], name='cmp_file_purge_idx',
            condition=models.Q(content__isnull=False, purge_after__isnull=False))]
