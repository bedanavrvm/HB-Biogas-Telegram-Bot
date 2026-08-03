"""Portal-owned staging and archival for FarmUp and SysUp source files.

The Portal is intentionally a review surface only in this release.  It uses
the established FarmUp/SysUp parsers and staged-batch records, but never calls
their commit functions.  A later, separately approved release may expose a
maker-checker commit action without changing how files are staged or archived.
"""

from __future__ import annotations

import hashlib
import mimetypes
import re
from pathlib import PurePath
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.models import GroupSheetConfiguration, IntegrationOperation, JawabuFarmerUploadBatch
from core.services.document_sync import mark_drive_attempt, mark_drive_failure, mark_drive_success
from core.services.external_resilience import ExternalOperationError, execute_operation, reserve_operation


IMPORT_KIND_FARMUP = 'farmup'
IMPORT_KIND_SYSUP = 'sysup'
IMPORT_KINDS = frozenset({IMPORT_KIND_FARMUP, IMPORT_KIND_SYSUP})
SOURCE_MODEL = 'core.JawabuFarmerUploadBatch'
ARCHIVE_OPERATION = 'portal_import_drive_archive'
_JAWABU_GROUP_TYPES = frozenset({'jawabu', 'jawabu_homebiogas'})
_SAFE_FILENAME = re.compile(r'[^A-Za-z0-9._ -]+')


class PortalImportError(ValueError):
    """A stable validation failure suitable for a staff-facing API response."""


def available_import_groups(*, allowed_group_ids: set[str] | None = None) -> list[dict[str, str]]:
    """Return enabled Jawabu group configurations eligible for these imports."""
    groups = []
    for config in GroupSheetConfiguration.objects.filter(enabled=True).order_by('display_name', 'group_id'):
        workflow_type = str((config.workflow or {}).get('type') or '').strip()
        if workflow_type not in _JAWABU_GROUP_TYPES:
            continue
        if allowed_group_ids is not None and str(config.group_id) not in allowed_group_ids:
            continue
        groups.append({
            'group_id': str(config.group_id),
            'label': str(config.display_name or config.group_id),
        })
    return groups


def resolve_import_group(
    group_id: str = '', *, allowed_group_ids: set[str] | None = None,
) -> GroupSheetConfiguration:
    """Resolve one configured Jawabu destination without guessing a group."""
    choices = available_import_groups(allowed_group_ids=allowed_group_ids)
    requested = str(group_id or '').strip()
    if requested:
        allowed_ids = {item['group_id'] for item in choices}
        if requested not in allowed_ids:
            raise PortalImportError('Select an active Jawabu HomeBiogas group for this import.')
        return GroupSheetConfiguration.objects.get(group_id=requested)
    if len(choices) != 1:
        raise PortalImportError('Select the Jawabu HomeBiogas group before staging this import.')
    return GroupSheetConfiguration.objects.get(group_id=choices[0]['group_id'])


def _source_limit_bytes(kind: str) -> int:
    if kind == IMPORT_KIND_FARMUP:
        max_mb = max(1, int(getattr(settings, 'FARMUP_MAX_FILE_SIZE_MB', 5) or 5))
    else:
        max_mb = max(1, int(getattr(settings, 'SYSUP_MAX_FILE_SIZE_MB', 5) or 5))
    return max_mb * 1024 * 1024


def _validated_source(kind: str, *, filename: str, content: bytes) -> tuple[str, str, bytes]:
    normalized_kind = str(kind or '').strip().lower()
    if normalized_kind not in IMPORT_KINDS:
        raise PortalImportError('Select either FarmUp or SysUp.')
    safe_name = PurePath(str(filename or '')).name.strip()
    lower_name = safe_name.lower()
    if normalized_kind == IMPORT_KIND_FARMUP and not lower_name.endswith('.csv'):
        raise PortalImportError('FarmUp accepts a Jawabu Farmers CSV file only.')
    if normalized_kind == IMPORT_KIND_SYSUP and not lower_name.endswith(('.csv', '.xlsx')):
        raise PortalImportError('SysUp accepts a Customers Without Loans CSV or XLSX export.')
    payload = bytes(content or b'')
    if not payload:
        raise PortalImportError('Choose an import file before staging it.')
    if len(payload) > _source_limit_bytes(normalized_kind):
        raise PortalImportError('This import exceeds the configured safe upload size. Split it into smaller files and retry.')
    mime_type = mimetypes.guess_type(safe_name)[0] or 'application/octet-stream'
    return normalized_kind, safe_name, payload


def _decode_farmup_csv(content: bytes) -> str:
    for encoding in ('utf-8-sig', 'utf-8'):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise PortalImportError('FarmUp CSV must be UTF-8 encoded.')


def _existing_replay(request_id: str, *, kind: str, source_hash: str) -> JawabuFarmerUploadBatch | None:
    if not request_id:
        return None
    batch = JawabuFarmerUploadBatch.objects.filter(upload_request_id=request_id).first()
    if batch is None:
        return None
    if batch.source_content_hash != source_hash or batch.import_kind != ('farmers' if kind == IMPORT_KIND_FARMUP else 'system_export'):
        raise PortalImportError('This retry key belongs to a different import. Reload the screen and submit again.')
    return batch


def _assert_replay_is_in_scope(
    batch: JawabuFarmerUploadBatch,
    *,
    requested_group_id: str,
    allowed_group_ids: set[str] | None,
) -> None:
    """Keep an idempotent replay inside the caller's original import scope.

    A retry key must replay exactly one source upload, not become a way to
    retrieve a staged file from a different configured Telegram group.
    """
    requested_group_id = str(requested_group_id or '').strip()
    if requested_group_id and str(batch.group_id) != requested_group_id:
        raise PortalImportError('This retry key belongs to a different import group. Reload the screen and submit again.')
    if allowed_group_ids is not None and str(batch.group_id) not in allowed_group_ids:
        raise PortalImportError('This staged import is unavailable in your scope.')


def reserve_import_archive(batch: JawabuFarmerUploadBatch, *, request_id: str, user=None) -> IntegrationOperation:
    """Reserve an idempotent Drive archive attempt without performing I/O."""
    operation, _ = reserve_operation(
        integration=IntegrationOperation.INTEGRATION_GOOGLE_DRIVE,
        operation_type=ARCHIVE_OPERATION,
        deduplication_key=f'portal-import-archive:{batch.pk}:{batch.source_content_hash}',
        source_model=SOURCE_MODEL,
        source_id=str(batch.pk),
        request_id=str(request_id or '')[:128],
        requested_by=user,
        requested_by_label=str(getattr(user, 'get_full_name', lambda: '')() or getattr(user, 'username', '') or '')[:255],
        operation_payload=(str(batch.pk), batch.source_content_hash),
        metadata={'import_kind': batch.import_kind, 'source_size': int(batch.source_size or 0)},
    )
    return operation


def stage_portal_import(
    *,
    kind: str,
    filename: str,
    content: bytes,
    group_id: str,
    request_id: str,
    actor,
    allowed_group_ids: set[str] | None = None,
) -> tuple[JawabuFarmerUploadBatch, IntegrationOperation, bool]:
    """Create one review-only batch and reserve archival work.

    The request key is mandatory because an Android WebView retry must return
    the original parsed batch rather than create a second import to review.
    """
    request_id = str(request_id or '').strip()
    if not request_id:
        raise PortalImportError('This upload needs a retry key. Reload the Imports screen and try again.')
    normalized_kind, safe_name, payload = _validated_source(kind, filename=filename, content=content)
    source_hash = hashlib.sha256(payload).hexdigest()
    existing = _existing_replay(request_id, kind=normalized_kind, source_hash=source_hash)
    if existing is not None:
        _assert_replay_is_in_scope(
            existing,
            requested_group_id=group_id,
            allowed_group_ids=allowed_group_ids,
        )
        return existing, reserve_import_archive(existing, request_id=request_id, user=actor), True
    group_configuration = resolve_import_group(group_id, allowed_group_ids=allowed_group_ids)
    try:
        with transaction.atomic():
            # Check again inside the transaction.  The unique request key is
            # the final concurrent-retry guard.
            existing = _existing_replay(request_id, kind=normalized_kind, source_hash=source_hash)
            if existing is not None:
                _assert_replay_is_in_scope(
                    existing,
                    requested_group_id=group_id,
                    allowed_group_ids=allowed_group_ids,
                )
                return existing, reserve_import_archive(existing, request_id=request_id, user=actor), True
            if normalized_kind == IMPORT_KIND_FARMUP:
                from core.services.jawabu_master import create_farmup_review_batch

                batch, _stats = create_farmup_review_batch(
                    group_id=group_configuration.group_id,
                    telegram_message_id='',
                    sender=str(getattr(actor, 'get_full_name', lambda: '')() or getattr(actor, 'username', '') or ''),
                    source_filename=safe_name,
                    csv_text=_decode_farmup_csv(payload),
                    group_config=group_configuration,
                )
            else:
                from core.services.system_export import create_system_export_review_batch

                batch, _stats = create_system_export_review_batch(
                    group_id=group_configuration.group_id,
                    telegram_message_id='',
                    sender=str(getattr(actor, 'get_full_name', lambda: '')() or getattr(actor, 'username', '') or ''),
                    source_filename=safe_name,
                    content=payload,
                )
            batch.created_by = actor
            batch.upload_request_id = request_id
            batch.source_mime_type = mimetypes.guess_type(safe_name)[0] or 'application/octet-stream'
            batch.source_size = len(payload)
            batch.source_content_hash = source_hash
            batch.source_content = payload
            batch.save(update_fields=[
                'created_by', 'upload_request_id', 'source_mime_type', 'source_size',
                'source_content_hash', 'source_content', 'updated_at',
            ])
            operation = reserve_import_archive(batch, request_id=request_id, user=actor)
            return batch, operation, False
    except IntegrityError:
        # A concurrent retry may have won after parser work completed.  Do not
        # surface a duplicate-batch error or leave callers guessing its state.
        existing = _existing_replay(request_id, kind=normalized_kind, source_hash=source_hash)
        if existing is not None:
            _assert_replay_is_in_scope(
                existing,
                requested_group_id=group_id,
                allowed_group_ids=allowed_group_ids,
            )
            return existing, reserve_import_archive(existing, request_id=request_id, user=actor), True
        raise


def _archive_filename(batch: JawabuFarmerUploadBatch) -> str:
    original = _SAFE_FILENAME.sub('_', PurePath(str(batch.source_filename or '')).name).strip(' ._')
    original = original[:160] or ('farmup.csv' if batch.import_kind == 'farmers' else 'system-export.csv')
    prefix = 'FarmUp' if batch.import_kind == 'farmers' else 'SysUp'
    return f'{prefix}_{str(batch.pk)[:8]}_{original}'


def attempt_import_archive(operation_id: str) -> dict[str, Any]:
    """Perform at most one bounded archive attempt for a previously staged file."""
    operation = IntegrationOperation.objects.filter(pk=operation_id).first()
    if operation is None or operation.source_model != SOURCE_MODEL or operation.operation_type != ARCHIVE_OPERATION:
        raise PortalImportError('This import archive operation is unavailable.')
    batch = JawabuFarmerUploadBatch.objects.filter(pk=operation.source_id).first()
    if batch is None:
        raise PortalImportError('The staged import is no longer available.')
    if batch.archive_file_id and batch.archive_url:
        return {'ok': True, 'batch': batch, 'operation': operation, 'replayed': True}
    folder_id = str(getattr(settings, 'JAWABU_IMPORTS_DRIVE_FOLDER_ID', '') or '').strip()
    if not folder_id:
        batch.archive_error = 'Import Drive archive is not configured.'
        batch.save(update_fields=['archive_error', 'updated_at'])
        return {'ok': False, 'batch': batch, 'operation': operation, 'error': batch.archive_error}
    if not batch.source_content:
        batch.archive_error = 'The original source file is unavailable for Drive archival.'
        batch.save(update_fields=['archive_error', 'updated_at'])
        return {'ok': False, 'batch': batch, 'operation': operation, 'error': batch.archive_error}
    mark_drive_attempt(batch, prefix='archive')

    def archive_once() -> dict[str, str]:
        from core.services.order_approval import GoogleDriveMediaStorage

        file_id, url = GoogleDriveMediaStorage(parent_folder_id=folder_id).upload(
            batch.source_content,
            filename=_archive_filename(batch),
            mime_type=batch.source_mime_type or 'application/octet-stream',
            id_number='portal_imports',
            received_at=batch.created_at or timezone.now(),
            workflow_key='Imports',
            record_type='Batch',
            record_key=str(batch.pk),
            attempt_budget=1,
        )
        return {'id': file_id, 'url': url}

    try:
        result = execute_operation(operation, archive_once, attempt_budget=1)
    except ExternalOperationError:
        mark_drive_failure(batch, 'Drive archive needs attention. Retry from Imports.', prefix='archive', error_field='archive_error')
        operation.refresh_from_db()
        return {'ok': False, 'batch': batch, 'operation': operation, 'error': batch.archive_error}
    if not result:
        operation.refresh_from_db()
        return {'ok': False, 'batch': batch, 'operation': operation, 'error': 'Drive archive is already being processed.'}
    file_id = str(result.get('id') or '')
    url = str(result.get('url') or result.get('webViewLink') or '')
    if not file_id or not url:
        batch.archive_error = 'Drive archive completed without a usable file reference.'
        batch.save(update_fields=['archive_error', 'updated_at'])
        return {'ok': False, 'batch': batch, 'operation': operation, 'error': batch.archive_error}
    mark_drive_success(batch, file_id=file_id, url=url, prefix='archive', error_field='archive_error')
    return {'ok': True, 'batch': batch, 'operation': operation, 'replayed': False}


def import_archive_state(batch: JawabuFarmerUploadBatch) -> str:
    if batch.archive_file_id and batch.archive_url:
        return 'archived'
    if batch.archive_error:
        return 'needs_attention'
    return 'pending'


def archive_operation_ids(batches: list[JawabuFarmerUploadBatch]) -> dict[str, str]:
    """Fetch archive-operation IDs in one query for an already scoped batch list."""
    batch_ids = [str(batch.pk) for batch in batches]
    if not batch_ids:
        return {}
    return {
        str(operation['source_id']): str(operation['id'])
        for operation in IntegrationOperation.objects.filter(
            source_model=SOURCE_MODEL,
            operation_type=ARCHIVE_OPERATION,
            source_id__in=batch_ids,
        ).values('id', 'source_id')
    }


def serialize_import_batch(
    batch: JawabuFarmerUploadBatch, *, include_rows: bool = False, archive_operation_id: str = '',
) -> dict[str, Any]:
    """Return staff-safe metadata; raw bytes and Drive URLs stay private."""
    payload: dict[str, Any] = {
        'id': str(batch.pk),
        'kind': 'farmup' if batch.import_kind == 'farmers' else 'sysup',
        'source_filename': batch.source_filename,
        'source_size': int(batch.source_size or 0),
        'group_id': batch.group_id,
        'status': batch.status,
        'total_rows': batch.total_rows,
        'review_needed': batch.review_needed,
        'committed_count': batch.committed_count,
        'skipped_count': batch.skipped_count,
        'error': batch.error,
        'created_at': batch.created_at.isoformat() if batch.created_at else None,
        'updated_at': batch.updated_at.isoformat() if batch.updated_at else None,
        'created_by': str(getattr(batch.created_by, 'get_full_name', lambda: '')() or getattr(batch.created_by, 'username', '') or batch.sender or ''),
        'archive_state': import_archive_state(batch),
        'archive_error': batch.archive_error or '',
        'archive_attempts': int(batch.archive_sync_attempts or 0),
        'archive_last_attempt_at': batch.archive_last_sync_at.isoformat() if batch.archive_last_sync_at else None,
        'archive_next_retry_at': batch.archive_next_retry_at.isoformat() if batch.archive_next_retry_at else None,
        'archive_operation_id': str(archive_operation_id or ''),
    }
    if include_rows:
        payload['mapping'] = list(batch.mapping or [])
        payload['rows'] = list(batch.parsed_rows or [])
    return payload
