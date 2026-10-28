"""Bounded independent publisher, with fenced progress and retained receipts."""
from datetime import timedelta
from email.utils import parsedate_to_datetime
import random
import json
import hashlib

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.models import CaseUpdate, ComplaintCaseControl, GroupSheetConfiguration, IntegrationOperation, ParsedMessage
from core.services import complaint_cases as cases
from core.services.external_resilience import execute_operation, external_call_budget, ExternalCircuitOpen, operation_lease_seconds
from core.services.group_config import GroupConfig
from .models import UploadFile
from .services import DRIVE_OPERATION, SHEET_OPERATION


class PublicationUnavailable(RuntimeError):
    status_code = 503


def _claim(operation):
    if operation.operation_type == DRIVE_OPERATION:
        return UploadFile.objects.filter(pk=operation.source_id, evidence__isnull=False).exists()
    control = ComplaintCaseControl.objects.select_for_update().filter(pk=operation.source_id).first()
    if not control:
        return False
    return not IntegrationOperation.objects.filter(operation_type=SHEET_OPERATION, source_id=operation.source_id,
        status='running', last_attempt_at__gt=timezone.now() - timedelta(seconds=operation_lease_seconds())
        ).exclude(pk=operation.pk).exists()


def publish(operation, *, seconds=40):
    row = GroupSheetConfiguration.objects.filter(group_id=operation.metadata.get('group_id')).first()
    if not row:
        IntegrationOperation.objects.filter(pk=operation.pk).update(status='dead_letter', last_error_code='source_group_missing', next_retry_at=None)
        return {'missing': True}
    def pause():
        stale = timezone.now() - timedelta(seconds=operation_lease_seconds())
        IntegrationOperation.objects.filter(pk=operation.pk).filter(Q(status__in=[IntegrationOperation.STATUS_PENDING, IntegrationOperation.STATUS_RETRYABLE]) |
            Q(status='running', last_attempt_at__lte=stale)).update(status=IntegrationOperation.STATUS_RETRYABLE, next_retry_at=timezone.now() + timedelta(minutes=15))
        return {'paused': True}
    if not row.enabled:
        return pause()
    group = GroupConfig(**row.as_group_config_kwargs())
    file = UploadFile.objects.filter(pk=operation.source_id).select_related('evidence__parsed_message', 'attempt') .first() if operation.operation_type == DRIVE_OPERATION else None
    control = ComplaintCaseControl.objects.filter(pk=operation.source_id).select_related('parsed_message').first() if operation.operation_type == SHEET_OPERATION else None
    if (operation.operation_type == DRIVE_OPERATION and (not file or not file.evidence_id)) or (
            operation.operation_type == SHEET_OPERATION and not control):
        IntegrationOperation.objects.filter(pk=operation.pk).update(status='dead_letter', last_error_code='source_missing', next_retry_at=None)
        return {'missing': True}
    if operation.operation_type == SHEET_OPERATION and not cases.complaint_sheet_projection_enabled(group):
        return pause()

    def progress(received, uri):
        with transaction.atomic():
            job = IntegrationOperation.objects.select_for_update().get(pk=operation.pk)
            if job.status != 'running' or job.metadata.get('attempt_token') != operation.metadata.get('attempt_token'):
                raise PublicationUnavailable('The publication lease changed.')
            # A live transfer renews the same fenced lease; it never becomes a second writer.
            job.last_attempt_at = timezone.now()
            job.save(update_fields=['last_attempt_at', 'updated_at'])
            UploadFile.objects.filter(evidence_id=file.evidence_id, operation=job).update(
                published_bytes=max(0, min(int(received), file.size)), resumable_uri=uri, updated_at=timezone.now())

    def send():
        with external_call_budget(seconds):
            if file:
                if file.evidence.upload_status == 'success':
                    now = timezone.now()
                    UploadFile.objects.filter(evidence_id=file.evidence_id, published_at__isnull=True).update(
                        published_bytes=file.size, published_at=now, purge_after=now + timedelta(hours=24), resumable_uri='')
                    return {'id': file.evidence.drive_file_id}
                if file.content is None:
                    raise ValueError('The retained payload is missing.')
                if len(file.content) != file.size or hashlib.sha256(bytes(file.content)).hexdigest() != file.content_hash:
                    raise ValueError('The retained payload does not match its verified receipt.')
                from core.services.order_approval import GoogleDriveMediaStorage
                file_id, url = GoogleDriveMediaStorage().upload(data=bytes(file.content),
                    filename=file.evidence.storage_filename, mime_type=file.mime_type,
                    id_number=f'CASE_{file.evidence.parsed_message.message_id}', received_at=file.evidence.created_at,
                    group_config=group, workflow_key='Complaint Cases', record_type='Case',
                    record_key=file.evidence.parsed_message.message_id, publication_key=f'complaint-evidence:{file.evidence_id}',
                    progress_callback=progress, resumable_uri=file.resumable_uri)
                with transaction.atomic():
                    job = IntegrationOperation.objects.select_for_update().get(pk=operation.pk)
                    if job.status != 'running' or job.metadata.get('attempt_token') != operation.metadata.get('attempt_token'):
                        raise PublicationUnavailable('The publication lease changed.')
                    file.evidence.drive_file_id, file.evidence.drive_url = file_id, url
                    file.evidence.upload_status, file.evidence.upload_error = 'success', ''
                    file.evidence.save(update_fields=['drive_file_id', 'drive_url', 'upload_status', 'upload_error'])
                    now = timezone.now()
                    UploadFile.objects.filter(evidence_id=file.evidence_id).update(published_bytes=file.size,
                        published_at=now, purge_after=now + timedelta(hours=24), resumable_uri='', updated_at=now)
                    from core.services.compliance_audit import record_event
                    record_event(workflow='complaint_cases', action='complaint.evidence.published', origin='system',
                        subject_type='complaint_case', subject_id=str(file.evidence.parsed_message_id),
                        source_model='ComplaintCaseEvidence', source_event_id=str(file.evidence_id),
                        deduplication_key=f'complaint-publication-complete:{file.evidence_id}',
                        metadata={'operation': str(operation.pk), 'size': file.size})
                return {'id': file_id}
            case = ParsedMessage.objects.get(pk=control.parsed_message_id)
            succeeded = cases.update_sheet_case(group, case, {}) if case.synced_to_sheets else cases.sync_new_case_to_sheet(group, case)
            if not succeeded:
                # shortcut: legacy Sheet booleans lose provider headers; use typed failures when that adapter is upgraded.
                raise PublicationUnavailable('The saved Complaint snapshot is awaiting publication.')
            ComplaintCaseControl.objects.filter(pk=control.pk, revision=control.revision).update(
                sync_status='success', sync_error='', last_sync_at=timezone.now())
            CaseUpdate.objects.filter(parsed_message=case, created_at__lte=operation.created_at, sync_status__in=['pending', 'failed']).update(sync_status='success', sync_error='')
            return {'action': 'published'}

    retry_not_before = None

    def call():
        nonlocal retry_not_before
        try:
            return send()
        except Exception as error:
            failure_source = error
            while failure_source.__cause__ is not None and not (
                    getattr(failure_source, 'resp', None) or getattr(failure_source, 'status_code', None)):
                failure_source = failure_source.__cause__
            response = getattr(failure_source, 'resp', None)
            code = getattr(response, 'status', None) or getattr(failure_source, 'status_code', None)
            if isinstance(failure_source, TimeoutError):
                code = 503
            if code == 403:
                try:
                    details = json.loads(getattr(failure_source, 'content', b'{}')).get('error', {}).get('errors', [])
                    if any(item.get('reason') in {'rateLimitExceeded', 'userRateLimitExceeded'} for item in details):
                        code = 429
                except (ValueError, TypeError, AttributeError):
                    pass
            if code:
                failure = PublicationUnavailable('The external publication did not complete.')
                failure.status_code = int(code)
                failure.headers = response or getattr(failure_source, 'headers', {})
                raw = failure.headers.get('Retry-After') or failure.headers.get('retry-after')
                if raw:
                    try:
                        retry_not_before = timezone.now() + timedelta(seconds=max(0, float(raw)))
                    except (ValueError, TypeError, OverflowError):
                        try:
                            value = parsedate_to_datetime(raw)
                            if timezone.is_aware(value):
                                retry_not_before = value
                        except (ValueError, TypeError, OverflowError):
                            pass
                raise failure from None
            raise

    try:
        return execute_operation(operation, call, attempt_budget=1, claim_guard=_claim)
    except Exception as error:
        operation.refresh_from_db()
        if operation.status == IntegrationOperation.STATUS_RETRYABLE and not isinstance(error, ExternalCircuitOpen):
            delay = min(3600, 60 * 2 ** max(0, operation.attempts - 1) + random.uniform(0, 5))
            due = max(operation.next_retry_at or timezone.now(), timezone.now() + timedelta(seconds=delay), retry_not_before or timezone.now())
            IntegrationOperation.objects.filter(pk=operation.pk, status=IntegrationOperation.STATUS_RETRYABLE).update(next_retry_at=due)
        if operation.status == 'dead_letter':
            if file:
                file.evidence.upload_status = 'failed'
                file.evidence.upload_error = 'Publication needs Complaints IT attention. The original file is retained in Django.'
                file.evidence.save(update_fields=['upload_status', 'upload_error'])
            else:
                ComplaintCaseControl.objects.filter(pk=control.pk).update(sync_status='failed',
                    sync_error='Saved in Django. Background publication needs Complaints IT attention.')
            from core.services.compliance_audit import record_event
            record_event(workflow='complaint_cases', action='complaint.publication.needs_attention', origin='system',
                subject_type='complaint_case', subject_id=str(file.evidence.parsed_message_id if file else control.parsed_message_id),
                deduplication_key=f'complaint-publication-attention:{operation.pk}',
                metadata={'operation': str(operation.pk), 'attempts': operation.attempts, 'error_code': operation.last_error_code})
        return {'error': True}
