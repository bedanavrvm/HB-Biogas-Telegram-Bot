"""Browser-only durable publication; canonical writes never wait for Google."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta
import hashlib
import json
import re
from uuid import UUID

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from core.models import CaseUpdate, ComplaintCaseControl, ComplaintCaseEvidence, GroupSheetConfiguration, IntegrationOperation, ParsedMessage
from core.services import complaint_cases as cases
from core.services.external_resilience import reserve_operation, operation_lease_seconds
from .models import UploadAttempt, UploadFile

DRIVE_OPERATION = 'complaint_browser.evidence'
SHEET_OPERATION = 'complaint_browser.sheet'
RUNNER = 'complaint_browser_publications'
_write = ContextVar('complaint_browser_write', default=None)


def command_capability(path):
    if path == 'cases/create/':
        return 'complaint.case.create', None
    match = re.fullmatch(r'cases/([a-f0-9-]{36})/(conversation/post|resolve|verification-comment|comment|reopen|complete-details|finish-created|retry-publication)/', path)
    if not match:
        raise cases.ComplaintCaseError('This upload command is unavailable.')
    key, action = match.groups()
    try:
        UUID(key)
    except ValueError:
        raise cases.ComplaintCaseError('Select a valid complaint.') from None
    capability = {'conversation/post': 'complaint.conversation.participate', 'resolve': 'complaint.case.close',
        'comment': 'complaint.case.comment', 'verification-comment': 'complaint.case.verification.comment', 'reopen': 'complaint.case.reopen',
        'complete-details': 'complaint.case.details.complete', 'finish-created': 'complaint.case.create',
        'retry-publication': 'complaint.case.sync.retry'}[action]
    return capability, key


def authorize(group, actor, path):
    capability, key = command_capability(path)
    case = ParsedMessage.objects.filter(pk=key, group_id=group.group_id).first() if key else None
    if key and (not case or not cases.actor_can_access_case(group, actor, 'complaint.queue.view', case.message_id)):
        raise PermissionDenied
    if not cases.actor_can(group, actor, capability, case):
        raise PermissionDenied
    return case


def manifest(files):
    maximum = int(getattr(settings, 'COMPLAINT_CASE_MAX_FILES_PER_UPDATE', 10))
    per_file = int(getattr(settings, 'COMPLAINT_CASE_MAX_FILE_SIZE_MB', 10)) * 1024 * 1024
    total = int(getattr(settings, 'COMPLAINT_CASE_MAX_TOTAL_UPLOAD_MB', 30)) * 1024 * 1024
    if not isinstance(files, list) or not 1 <= len(files) <= maximum:
        raise cases.ComplaintCaseError('Choose up to ten evidence files.')
    result = []
    for item in files:
        if (not isinstance(item, dict) or set(item) != {'name', 'size', 'sha256'}
                or not isinstance(item['name'], str) or not 1 <= len(item['name']) <= 255
                or any(char in item['name'] for char in ('/', '\\', '\0'))
                or type(item['size']) is not int or not 0 < item['size'] <= per_file
                or not isinstance(item['sha256'], str) or not re.fullmatch('[a-f0-9]{64}', item['sha256'])):
            raise cases.ComplaintCaseError('Review the evidence filenames, types and sizes.')
        result.append(item)
    if sum(item['size'] for item in result) > total:
        raise cases.ComplaintCaseError('The selected files exceed the total upload limit.')
    return result


def reserve(group, actor, path, fields, files):
    case = authorize(group, actor, path)
    if not cases.actor_can(group, actor, 'complaint.case.evidence.manage', case):
        raise PermissionDenied
    if path != 'cases/create/' and not path.endswith(('/resolve/', '/comment/', '/verification-comment/', '/conversation/post/', '/finish-created/')):
        raise cases.ComplaintCaseError('This action does not accept attachments.')
    if not isinstance(fields, dict) or len(json.dumps(fields)) > 100000:
        raise cases.ComplaintCaseError('Review the submitted fields.')
    key = cases.create_request_id(fields.get('client_request_id'))
    files = manifest(files)
    digest = cases.mutation_payload_hash({'path': path, 'fields': fields, 'files': files})
    row = GroupSheetConfiguration.objects.get(group_id=group.group_id)
    with transaction.atomic():
        # Serialize per-owner reservation limits and duplicate request keys.
        from django.contrib.auth import get_user_model
        get_user_model().objects.select_for_update().get(pk=actor.user.pk)
        existing = UploadAttempt.objects.filter(group=row, actor_reference=str(actor.user.pk), request_key=key).first()
        if existing:
            if existing.payload_hash != digest:
                raise cases.ComplaintCaseError('This retry identifier belongs to different fields or files.')
            return existing
        active = UploadAttempt.objects.filter(actor=actor.user, committed_at__isnull=True,
            created_at__gt=timezone.now() - timedelta(hours=24)).count()
        if active >= 8:
            raise cases.ComplaintCaseError('Too many unfinished uploads. Finish an existing upload or try again later.')
        attempt = UploadAttempt.objects.create(group=row, actor=actor.user, actor_reference=str(actor.user.pk),
            request_key=key, action_path=path, payload_hash=digest, case=case)
        UploadFile.objects.bulk_create([UploadFile(attempt=attempt, position=index, filename=item['name'],
            size=item['size'], content_hash=item['sha256']) for index, item in enumerate(files)])
        return attempt


def owned_attempt(group, actor, key):
    attempt = UploadAttempt.objects.filter(pk=key, group__group_id=group.group_id,
        actor_reference=str(actor.user.pk)).first()
    if not attempt:
        raise PermissionDenied
    authorize(group, actor, attempt.action_path)
    if not attempt.committed_at and attempt.created_at <= timezone.now() - timedelta(hours=24):
        raise cases.ComplaintCaseError('This unfinished upload expired. Select the files again.')
    return attempt


def receive(group, actor, attempt_key, file_key, request):
    attempt = owned_attempt(group, actor, attempt_key)
    if not cases.actor_can(group, actor, 'complaint.case.evidence.manage', attempt.case):
        raise PermissionDenied
    row = attempt.files.filter(pk=file_key).first()
    if not row:
        raise PermissionDenied
    chunks, size, digest = [], 0, hashlib.sha256()
    while chunk := request.read(256 * 1024):
        size += len(chunk)
        if size > row.size:
            raise cases.ComplaintCaseError('The file exceeds its reserved size.')
        chunks.append(chunk)
        digest.update(chunk)
    if size != row.size or digest.hexdigest() != row.content_hash:
        raise cases.ComplaintCaseError('The uploaded bytes do not match this file. Select the original file and retry.')
    data = b''.join(chunks)
    upload = SimpleUploadedFile(row.filename, data)
    cases.validate_uploaded_files([upload])
    with transaction.atomic():
        row = UploadFile.objects.select_for_update().get(pk=row.pk)
        if not row.received_at:
            row.content = data
            row.mime_type = cases.detected_upload_type(upload)
            row.received_at = timezone.now()
            row.save(update_fields=['content', 'mime_type', 'received_at', 'updated_at'])
    return row


def file_state(row):
    job = row.operation
    success = bool(row.published_at and row.evidence_id and row.evidence.upload_status == 'success')
    state = 'published' if success else 'needs_attention' if job and job.status == 'dead_letter' else (
        'retrying' if job and job.next_retry_at else 'publishing' if job and job.status == 'running' else
        'queued' if row.evidence_id else 'received' if row.received_at else 'waiting')
    percent = 100 if success else min(99, 50 + int(49 * min(row.published_bytes, row.size) / row.size)) if row.received_at else 0
    return {'id': str(row.pk), 'name': row.filename, 'size': row.size, 'stage': state, 'percent': percent,
        'received': bool(row.received_at), 'evidence': str(row.evidence_id or ''),
        'attempts': job.attempts if job else 0, 'next_retry_at': job.next_retry_at.isoformat() if job and job.next_retry_at else None}


def attempt_state(attempt):
    return {'key': str(attempt.pk), 'saved': bool(attempt.committed_at),
        'files': [file_state(row) for row in attempt.files.select_related('operation', 'evidence').order_by('position')]}


@contextmanager
def browser_write(group, actor, path, fields, uploaded, attempt_key=''):
    case = authorize(group, actor, path)
    if attempt_key and uploaded:
        raise cases.ComplaintCaseError('Choose one evidence transport for this save.')
    attempt = owned_attempt(group, actor, attempt_key) if attempt_key else None
    if attempt:
        saved_manifest = [{'name': row.filename, 'size': row.size, 'sha256': row.content_hash}
            for row in attempt.files.order_by('position')]
        digest = cases.mutation_payload_hash({'path': path, 'fields': fields, 'files': saved_manifest})
        if path != attempt.action_path or attempt.payload_hash != digest:
            raise cases.ComplaintCaseError('This upload belongs to different fields or files.')
    elif uploaded:
        cases.validate_uploaded_files(uploaded)
        facts = []
        for file in uploaded:
            raw = file.read(); file.seek(0)
            facts.append({'name': file.name, 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
        attempt = reserve(group, actor, path, fields, facts)
        for row, file in zip(attempt.files.order_by('position'), uploaded):
            raw = file.read(); file.seek(0)
            if not row.received_at:
                row.content = raw; row.received_at = timezone.now(); row.mime_type = cases.detected_upload_type(file)
                row.save(update_fields=['content', 'received_at', 'mime_type', 'updated_at'])
    with transaction.atomic():
        if attempt:
            attempt = UploadAttempt.objects.select_for_update().get(pk=attempt.pk)
            if not attempt.committed_at and attempt.created_at <= timezone.now() - timedelta(hours=24):
                raise cases.ComplaintCaseError('This unfinished upload expired. Select the files again.')
        rows = list(attempt.files.select_for_update(of=('self',)).select_related('evidence').order_by('position')) if attempt else []
        files = []
        for row in rows:
            if not row.received_at:
                raise cases.ComplaintCaseError('Wait until every selected file is received before saving.')
            # A successful replay after payload expiry needs no byte transfer.
            if row.content is None and attempt.committed_at and row.evidence_id and row.evidence.upload_status == 'success':
                continue
            if row.content is None:
                raise cases.ComplaintCaseError('The original file is unavailable. Ask Complaints IT to review this upload.')
            files.append(SimpleUploadedFile(row.filename, bytes(row.content), content_type=row.mime_type))
        state = {'group': group, 'actor': actor, 'case': case, 'attempt': attempt, 'rows': rows, 'files': files}
        token = _write.set(state)
        try:
            yield state
            if attempt:
                if any(not row.evidence_id for row in rows):
                    raise cases.ComplaintCaseError('The evidence could not be bound to the saved complaint.')
                attempt.case = state['case']
                attempt.committed_at = attempt.committed_at or timezone.now()
                attempt.save(update_fields=['case', 'committed_at'])
        finally:
            _write.reset(token)


def defer_sheet(group, case):
    if _write.get() is None:
        return False
    queue_sheet(group, case)
    return True


def queue_sheet(group, case, *, evidence=None):
    if not cases.complaint_sheet_projection_enabled(group):
        return None
    control = cases.ensure_case_control(case, group)
    job, _ = reserve_operation(integration='google_sheets', operation_type=SHEET_OPERATION,
        deduplication_key=f'complaint-browser-sheet:{control.pk}:{control.revision}' + (f':evidence:{evidence.pk}' if evidence else ''),
        source_model='ComplaintCaseControl', source_id=str(control.pk), max_attempts=8,
        metadata={'group_id': group.group_id, 'revision': control.revision})
    if job.status not in {'succeeded', 'dead_letter'}:
        ComplaintCaseControl.objects.filter(pk=control.pk).update(sync_status='pending', sync_error='')
    return job


def defer_evidence(group, case, evidence):
    state = _write.get()
    if state is None:
        return False
    state['case'] = case
    matched = [row for row in state['rows'] if row.content_hash == evidence.content_hash]
    if not matched:
        raise cases.ComplaintCaseError('Evidence does not match the received file manifest.')
    for row in matched:
        row.evidence = evidence
        if evidence.upload_status == 'success':
            row.published_at = row.published_at or timezone.now()
            row.purge_after = row.published_at + timedelta(hours=24)
            row.published_bytes = row.size
        else:
            prior = UploadFile.objects.filter(evidence=evidence, operation__isnull=False).first()
            if prior:
                row.operation = prior.operation
            else:
                row.operation, _ = reserve_operation(integration='google_drive', operation_type=DRIVE_OPERATION,
                    deduplication_key=f'complaint-browser-drive:{evidence.pk}',
                    source_model='complaint_publications.UploadFile', source_id=str(row.pk), max_attempts=8,
                    metadata={'group_id': group.group_id, 'evidence_id': str(evidence.pk)})
        row.save(update_fields=['evidence', 'operation', 'published_at', 'purge_after', 'published_bytes', 'updated_at'])
    if evidence.upload_status == 'success':
        now = timezone.now()
        UploadFile.objects.filter(evidence=evidence, published_at__isnull=True).update(
            published_at=now, purge_after=now + timedelta(hours=24), published_bytes=F('size'), resumable_uri='')
    return True


def queued_operations():
    now = timezone.now()
    return IntegrationOperation.objects.filter(operation_type__in=[DRIVE_OPERATION, SHEET_OPERATION]).filter(
        Q(status__in=[IntegrationOperation.STATUS_PENDING, IntegrationOperation.STATUS_RETRYABLE], next_retry_at__isnull=True)
        | Q(status__in=[IntegrationOperation.STATUS_PENDING, IntegrationOperation.STATUS_RETRYABLE], next_retry_at__lte=now)
        | Q(status='running', last_attempt_at__lte=now - timedelta(seconds=operation_lease_seconds()))
    ).order_by('created_at', 'pk')


def cleanup():
    now = timezone.now()
    with transaction.atomic():
        expired = list(UploadAttempt.objects.select_for_update(skip_locked=True).filter(
            committed_at__isnull=True, created_at__lte=now - timedelta(hours=24))
            .order_by('created_at').values_list('pk', flat=True)[:100])
        UploadAttempt.objects.filter(pk__in=expired).delete()
    done = list(UploadFile.objects.filter(purge_after__lte=now, content__isnull=False,
        evidence__upload_status='success').values_list('pk', flat=True)[:100])
    return len(expired), UploadFile.objects.filter(pk__in=done).update(content=None, resumable_uri='')


def is_it(actor):
    return actor.user.is_active and (actor.user.is_superuser or 'IT' in set(actor.roles or (actor.role,)))


def retry_case(group, actor, case):
    if case.group_id != group.group_id or not is_it(actor) or not cases.actor_can(group, actor, 'complaint.case.sync.retry', case):
        raise PermissionDenied
    control = cases.ensure_case_control(case, group)
    jobs = IntegrationOperation.objects.filter(status='dead_letter').filter(
        Q(operation_type=SHEET_OPERATION, source_id=str(control.pk)) |
        Q(operation_type=DRIVE_OPERATION, complaint_upload_files__evidence__parsed_message=case)).distinct()
    from core.services.compliance_audit import record_event
    count = 0
    for old in jobs:
        replacement, created = reserve_operation(integration=old.integration, operation_type=old.operation_type,
            deduplication_key=f'complaint-browser-retry:{old.pk}', source_model=old.source_model,
            source_id=old.source_id, max_attempts=8, metadata={**old.metadata, 'retry_of': str(old.pk)})
        if old.operation_type == DRIVE_OPERATION:
            evidence_ids = list(UploadFile.objects.filter(operation=old).values_list('evidence_id', flat=True))
            UploadFile.objects.filter(operation=old).update(operation=replacement)
            if replacement.status in {IntegrationOperation.STATUS_PENDING, IntegrationOperation.STATUS_RETRYABLE, IntegrationOperation.STATUS_RUNNING}:
                ComplaintCaseEvidence.objects.filter(pk__in=evidence_ids, upload_status='failed').update(upload_status='pending', upload_error='')
        if created:
            record_event(workflow='complaint_cases', action='complaint.publication.retry_requested', actor=actor.user,
                authority_user=actor.user, subject_type='complaint_case', subject_id=str(case.pk),
                deduplication_key=f'complaint-publication-retry:{old.pk}', metadata={'operation': str(replacement.pk)})
            count += 1
    return count


def case_state(group, actor, case):
    if not case or not cases.actor_can_access_case(group, actor, 'complaint.queue.view', case.message_id):
        raise PermissionDenied
    control = cases.ensure_case_control(case, group)
    files = []
    if cases.actor_can(group, actor, 'complaint.case.evidence.view', case):
        rows = UploadFile.objects.filter(evidence__parsed_message=case
            ).select_related('operation', 'evidence', 'attempt').order_by(F('published_at').desc(nulls_first=True), '-received_at', 'position')[:100]
        comments = dict(CaseUpdate.objects.filter(parsed_message=case, source='browser_staff_comment',
            client_request_id__in=[row.attempt.request_key for row in rows]).values_list('client_request_id', 'pk'))
        seen = set()
        for row in rows:
            origin = 'conversation' if row.attempt.action_path.endswith('/conversation/post/') else 'case'
            comment_key = str(comments.get(row.attempt.request_key, '')) if origin == 'conversation' else ''
            identity = (row.evidence_id, origin, comment_key)
            if identity in seen:
                continue
            seen.add(identity)
            files.append({**file_state(row), 'origin': origin, 'comment_key': comment_key})
    sheet = IntegrationOperation.objects.filter(operation_type=SHEET_OPERATION,
        source_id=str(control.pk)).order_by('-created_at', '-pk').first()
    from core.models import DurableJobRunnerHeartbeat
    heartbeat = DurableJobRunnerHeartbeat.objects.filter(runner_key=RUNNER).first()
    fresh = bool(heartbeat and heartbeat.heartbeat_at and heartbeat.heartbeat_at >= timezone.now() - timedelta(minutes=15))
    needs_attention = bool(sheet and sheet.status == 'dead_letter') or UploadFile.objects.filter(
        evidence__parsed_message=case, operation__status='dead_letter').exists()
    return {'files': files, 'needs_attention': needs_attention, 'sheet': {
        'key': str(sheet.pk) if sheet else '', 'tracked': bool(sheet),
        'status': 'paused' if sheet and not cases.complaint_sheet_projection_enabled(group) else sheet.status if sheet else 'not_required',
        'attempts': sheet.attempts if sheet else 0,
        'next_retry_at': sheet.next_retry_at.isoformat() if sheet and sheet.next_retry_at else None,
    }, 'runner_healthy': fresh, 'can_retry': is_it(actor) and cases.actor_can(group, actor, 'complaint.case.sync.retry', case)}


def attention(group, actor):
    if not is_it(actor):
        raise PermissionDenied
    from core.models import DurableJobRunnerHeartbeat
    fresh = DurableJobRunnerHeartbeat.objects.filter(runner_key=RUNNER, heartbeat_at__gte=timezone.now() - timedelta(minutes=15)).exists()
    jobs = IntegrationOperation.objects.filter(operation_type__in=[DRIVE_OPERATION, SHEET_OPERATION],
        metadata__group_id=group.group_id, status__in=['dead_letter'] if fresh else ['dead_letter', 'pending', IntegrationOperation.STATUS_RETRYABLE, 'running']).order_by('-updated_at')[:100]
    result, seen = [], set()
    for job in jobs:
        if job.operation_type == DRIVE_OPERATION:
            file = UploadFile.objects.filter(operation=job).select_related('evidence__parsed_message').first()
            case = file.evidence.parsed_message if file and file.evidence_id else None
        else:
            control = ComplaintCaseControl.objects.filter(pk=job.source_id).select_related('parsed_message').first()
            case = control.parsed_message if control else None
        if case and case.pk not in seen and cases.actor_can_access_case(group, actor, 'complaint.queue.view', case.message_id):
            seen.add(case.pk)
            state = case_state(group, actor, case)
            current_work = any(file['stage'] not in {'published', 'needs_attention'} for file in state['files']) or (
                state['sheet']['status'] in {'pending', IntegrationOperation.STATUS_RETRYABLE, 'running'})
            if not state['needs_attention'] and (fresh or not current_work):
                continue
            result.append({'key': str(case.pk), 'reference': cases.ensure_case_control(case, group).reference_number,
                'name': case.customer_name, 'failed': state['needs_attention'], 'state': state})
    return result
