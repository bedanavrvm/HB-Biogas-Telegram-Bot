"""Shared retry bookkeeping for Drive-backed portal artifacts."""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone


# Short enough for an operator retry, bounded enough not to hammer Drive when
# a service account or folder is misconfigured. The retry endpoint can always
# be used immediately; this schedule is for automated/management retries.
RETRY_DELAYS_MINUTES = (1, 5, 15, 60, 240, 1440)


def retry_at(attempts: int, *, now=None):
    current = now or timezone.now()
    index = max(0, min(int(attempts or 0), len(RETRY_DELAYS_MINUTES) - 1))
    return current + timedelta(minutes=RETRY_DELAYS_MINUTES[index])


def mark_drive_attempt(record, *, prefix: str = 'drive', update_fields: list[str] | None = None):
    """Increment and timestamp a Drive attempt before an external call."""
    attempts_field = f'{prefix}_sync_attempts'
    last_field = f'{prefix}_last_sync_at'
    next_field = f'{prefix}_next_retry_at'
    setattr(record, attempts_field, int(getattr(record, attempts_field, 0) or 0) + 1)
    setattr(record, last_field, timezone.now())
    setattr(record, next_field, None)
    fields = set(update_fields or [])
    fields.update({attempts_field, last_field, next_field, 'updated_at'})
    record.save(update_fields=sorted(fields))


def mark_drive_failure(
    record, error: str, *, prefix: str = 'drive', error_field: str | None = None,
    update_fields: list[str] | None = None,
):
    """Persist a retryable failure without discarding an older good URL."""
    attempts_field = f'{prefix}_sync_attempts'
    next_field = f'{prefix}_next_retry_at'
    setattr(record, next_field, retry_at(getattr(record, attempts_field, 0)))
    error_field = error_field or ('drive_upload_error' if hasattr(record, 'drive_upload_error') else 'error')
    setattr(record, error_field, str(error or '').strip())
    fields = set(update_fields or [])
    fields.update({error_field, next_field, 'updated_at'})
    record.save(update_fields=sorted(fields))


def mark_drive_success(
    record, *, file_id: str, url: str, prefix: str = 'drive', error_field: str | None = None,
    update_fields: list[str] | None = None,
):
    """Persist a successful upload and clear retry state."""
    file_id_field = f'{prefix}_file_id'
    url_field = f'{prefix}_url'
    setattr(record, file_id_field, file_id or '')
    setattr(record, url_field, url or '')
    next_field = f'{prefix}_next_retry_at'
    setattr(record, next_field, None)
    error_field = error_field or ('drive_upload_error' if hasattr(record, 'drive_upload_error') else 'error')
    setattr(record, error_field, '')
    fields = set(update_fields or [])
    fields.update({file_id_field, url_field, error_field, next_field, 'updated_at'})
    record.save(update_fields=sorted(fields))


def retry_requisition_batch_upload(
    batch,
    *,
    actor: str = '',
    attempt_budget: int | None = None,
    preserve_filename: bool = False,
) -> dict:
    """Publish a stored requisition workbook without regenerating business data.

    ``preserve_filename`` is used for the first automatic publication attempt.
    An explicit operator retry keeps the established versioned retry filename so
    Drive history remains easy to audit.
    """
    if not getattr(batch, 'file_content', b''):
        return {'ok': False, 'error': 'The requisition workbook is not available for retry.'}

    from core.services.order_approval import GoogleDriveMediaStorage

    mark_drive_attempt(batch)
    attempt = int(getattr(batch, 'drive_sync_attempts', 0) or 0)
    original_name = str(getattr(batch, 'filename', '') or f'JBL_Requisition_Form_{batch.order_number}.xlsx')
    if preserve_filename:
        retry_filename = original_name
    elif original_name.lower().endswith('.xlsx'):
        retry_filename = f'{original_name[:-5]}_retry{attempt}.xlsx'
    else:
        retry_filename = f'{original_name}_retry{attempt}.xlsx'
    try:
        file_id, url = GoogleDriveMediaStorage().upload(
            batch.file_content,
            filename=retry_filename,
            mime_type=getattr(batch, 'content_type', '') or 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            id_number='requisition_batches',
            received_at=timezone.now(),
            group_config=None,
            workflow_key='Jawabu/Requisitions',
            record_type='Order',
            record_key=batch.order_number,
            attempt_budget=attempt_budget,
        )
    except Exception as exc:
        mark_drive_failure(batch, 'Drive upload failed; retry required.', error_field='drive_upload_error')
        return {'ok': False, 'error': str(exc), 'retry_at': batch.drive_next_retry_at}

    batch.filename = retry_filename
    mark_drive_success(batch, file_id=file_id, url=url, error_field='drive_upload_error', update_fields=['filename'])
    return {'ok': True, 'file_id': file_id, 'url': url, 'filename': retry_filename, 'actor': actor}
