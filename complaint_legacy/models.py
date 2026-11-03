"""Retained private provenance for explicitly reviewed historical complaints."""
import uuid
from django.conf import settings
from django.db import models


class ImportUpload(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Opaque historical upload identity; no access authority.')
    group = models.ForeignKey('core.GroupSheetConfiguration', on_delete=models.PROTECT, related_name='complaint_legacy_uploads', db_comment='Exact Complaints owner selected by authorized staff.')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='complaint_legacy_uploads', db_comment='Accountable uploader; never impersonates a historical reporter.')
    namespace = models.SlugField(max_length=64, db_comment='Stable source namespace across reviewed workbook corrections.')
    filename = models.CharField(max_length=200, db_comment='Private display filename; not a filesystem path.')
    digest = models.CharField(max_length=64, db_comment='Expected SHA256 of retained source bytes.')
    size = models.PositiveIntegerField(db_comment='Compressed source size, at most 20 MiB.')
    source_sheet = models.CharField(max_length=128, default='Case Management', db_comment='Exact selected worksheet; no inference from case content.')
    phase = models.CharField(max_length=24, default='uploading', db_comment='Server-owned upload, mapping, staging, ready, committing, complete or discarded state.')
    state = models.JSONField(default=dict, db_comment='Private mapping, byte cursor and resumable progress; no browser-owned authority.')
    revision = models.PositiveIntegerField(default=1, db_comment='Optimistic revision for consequential commands.')
    lease = models.UUIDField(null=True, blank=True, db_comment='Exclusive advancing worker token.')
    lease_until = models.DateTimeField(null=True, blank=True, db_comment='Expiry for interrupted-worker recovery.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='Actual receipt time, never the historical reported date.')

    class Meta:
        db_table = 'complaint_legacy_upload_session'
        db_table_comment = 'Authoritative historical Complaints upload/checkpoint evidence. Private; retained with imported cases. No automatic purge.'
        constraints = [models.UniqueConstraint(fields=['group', 'digest'], name='cmp_legacy_file_once')]


class ImportChunk(models.Model):
    upload = models.ForeignKey(ImportUpload, on_delete=models.CASCADE, related_name='chunks', db_comment='Private source upload; explicit uncommitted discard only.')
    kind = models.CharField(max_length=16, default='source', db_comment='Source XLSX bytes; not a provider object.')
    position = models.PositiveIntegerField(db_comment='Zero-based 512 KiB chunk position.')
    content = models.BinaryField(db_comment='Private workbook bytes; never included in logs or normal API output.')
    digest = models.CharField(max_length=64, db_comment='Chunk SHA256 for corruption checks and identical replay.')

    class Meta:
        db_table = 'complaint_legacy_chunk_evidence'
        db_table_comment = 'Checksummed original workbook bytes; authoritative source evidence retained with imported Complaints.'
        constraints = [models.UniqueConstraint(fields=['upload', 'kind', 'position'], name='cmp_legacy_chunk_once')]


class ImportRow(models.Model):
    upload = models.ForeignKey(ImportUpload, on_delete=models.CASCADE, related_name='rows', db_comment='Exact source version; committed rows cannot be discarded.')
    source_row = models.PositiveIntegerField(db_comment='Original Source Row, otherwise first-upload physical worksheet row.')
    values = models.JSONField(default=dict, db_comment='Original mapped and unmapped cells, including historical notes and extra contacts.')
    proposal = models.JSONField(default=dict, db_comment='Reviewed status/date candidates, warnings, blocking issues and exact-source digest.')
    approved = models.BooleanField(default=False, db_comment='Explicit operator selection; warnings do not silently approve a row.')
    case = models.ForeignKey('core.ParsedMessage', null=True, blank=True, on_delete=models.PROTECT, related_name='complaint_legacy_rows', db_comment='Canonical complaint retained across source-version replays; never silently overwritten.')
    committed_at = models.DateTimeField(null=True, blank=True, db_comment='Actual canonical commit time, distinct from historical report/closure dates.')
    published = models.BooleanField(default=False, db_comment='Whether normal durable publication was explicitly requested for this row.')

    class Meta:
        db_table = 'complaint_legacy_row_record'
        db_table_comment = 'Private original-vs-proposed legacy facts and canonical Complaints provenance. Retain with the case; no automatic purge.'
        constraints = [models.UniqueConstraint(fields=['upload', 'source_row'], name='cmp_legacy_row_once')]
