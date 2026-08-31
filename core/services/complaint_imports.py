"""Transactional ownership for auditable complaint batch imports."""
from __future__ import annotations

import re
from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils import timezone

from core.models import ComplaintCaseImportBatch, ComplaintCaseImportItem, ParsedMessage


class ComplaintImportError(ValueError):
    """Base error for a complaint import request that cannot be applied safely."""


class ComplaintImportAuthorizationError(ComplaintImportError):
    """Raised when an actor is not allowed to import complaint exports."""


class ComplaintImportConflict(ComplaintImportError):
    """Raised when an idempotency key is reused for different source data."""


@dataclass(frozen=True)
class ComplaintImportReservation:
    batch: ComplaintCaseImportBatch
    created: bool
    retrying: bool = False

    @property
    def already_completed(self) -> bool:
        return not self.created and not self.retrying and self.batch.status in {
            ComplaintCaseImportBatch.STATUS_COMPLETE,
            ComplaintCaseImportBatch.STATUS_PARTIAL,
        }

    @property
    def already_processing(self) -> bool:
        return (
            not self.created
            and not self.retrying
            and self.batch.status == ComplaintCaseImportBatch.STATUS_PROCESSING
        )


def _require_import_actor(actor) -> None:
    if actor is None or not actor.is_active or not actor.is_superuser:
        raise ComplaintImportAuthorizationError(
            'Complaint batch imports are restricted to an active Django Superuser.'
        )


@transaction.atomic
def reserve_complaint_import_batch(
    *,
    actor,
    group_id: str,
    source_telegram_message_id: str,
    telegram_user_id: str,
    source_hash: str,
    source_count: int,
) -> ComplaintImportReservation:
    """Create or replay the durable source reservation for one Telegram message."""
    _require_import_actor(actor)
    normalized_group_id = str(group_id or '').strip()
    normalized_message_id = str(source_telegram_message_id or '').strip()
    normalized_hash = str(source_hash or '').strip().lower()
    if not normalized_group_id or not normalized_message_id:
        raise ComplaintImportError('The Telegram group and source message are required.')
    if not re.fullmatch(r'[0-9a-f]{64}', normalized_hash):
        raise ComplaintImportError('The complaint import source hash is invalid.')
    if int(source_count) < 1:
        raise ComplaintImportError('The complaint import contains no source messages.')

    batch, created = ComplaintCaseImportBatch.objects.get_or_create(
        group_id=normalized_group_id,
        source_telegram_message_id=normalized_message_id,
        defaults={
            'initiated_by': actor,
            'actor_label': str(actor.get_full_name() or actor.get_username() or '')[:255],
            'telegram_user_id_snapshot': str(telegram_user_id or '').strip()[:64],
            'source_hash': normalized_hash,
            'source_count': int(source_count),
        },
    )
    retrying = False
    if not created:
        batch = ComplaintCaseImportBatch.objects.select_for_update().get(pk=batch.pk)
        if batch.source_hash != normalized_hash:
            raise ComplaintImportConflict(
                'That Telegram message was already used for a different batch import.'
            )
        if batch.status == ComplaintCaseImportBatch.STATUS_FAILED:
            batch.status = ComplaintCaseImportBatch.STATUS_PROCESSING
            batch.completed_at = None
            batch.save(update_fields=['status', 'completed_at'])
            retrying = True
    return ComplaintImportReservation(batch=batch, created=created, retrying=retrying)


@transaction.atomic
def associate_complaint_import_item(
    *,
    batch: ComplaintCaseImportBatch,
    parsed_message: ParsedMessage | None = None,
    parsed_message_id=None,
    source_index: int,
) -> tuple[ComplaintCaseImportItem, bool]:
    """Idempotently bind one created complaint to its immutable source position."""
    if batch is None or batch.pk is None:
        raise ComplaintImportError('A saved complaint import batch is required.')
    if int(source_index) < 0:
        raise ComplaintImportError('The complaint import source index is invalid.')
    message_id = getattr(parsed_message, 'pk', None) or parsed_message_id
    if not message_id:
        raise ComplaintImportError('A saved parsed complaint is required.')

    existing_for_message = ComplaintCaseImportItem.objects.select_for_update().filter(
        parsed_message_id=message_id,
    ).first()
    if existing_for_message:
        if (
            existing_for_message.batch_id != batch.pk
            or existing_for_message.source_index != int(source_index)
        ):
            raise ComplaintImportConflict(
                'The complaint is already attributed to a different import source.'
            )
        return existing_for_message, False

    existing_for_position = ComplaintCaseImportItem.objects.select_for_update().filter(
        batch=batch,
        source_index=int(source_index),
    ).first()
    if existing_for_position:
        if existing_for_position.parsed_message_id != message_id:
            raise ComplaintImportConflict(
                'The import source position is already attributed to a different complaint.'
            )
        return existing_for_position, False

    try:
        with transaction.atomic():
            item = ComplaintCaseImportItem.objects.create(
                batch=batch,
                parsed_message_id=message_id,
                source_index=int(source_index),
            )
    except IntegrityError:
        # Resolve a concurrent retry after its uniqueness constraint wins.
        item = ComplaintCaseImportItem.objects.filter(parsed_message_id=message_id).first()
        if item and item.batch_id == batch.pk and item.source_index == int(source_index):
            return item, False
        raise ComplaintImportConflict(
            'The complaint import attribution conflicts with an existing source.'
        )
    return item, True


@transaction.atomic
def finalize_complaint_import_batch(
    *,
    batch: ComplaintCaseImportBatch,
    created_count: int,
    matched_count: int,
    rejected_count: int,
    error_count: int,
) -> ComplaintCaseImportBatch:
    """Finish a reserved batch once; a completed replay never rewrites its result."""
    locked = ComplaintCaseImportBatch.objects.select_for_update().get(pk=batch.pk)
    if locked.status in {
        ComplaintCaseImportBatch.STATUS_COMPLETE,
        ComplaintCaseImportBatch.STATUS_PARTIAL,
    }:
        return locked
    locked.status = (
        ComplaintCaseImportBatch.STATUS_COMPLETE
        if not int(rejected_count) and not int(error_count)
        else ComplaintCaseImportBatch.STATUS_PARTIAL
    )
    locked.created_count = max(0, int(created_count))
    locked.matched_count = max(0, int(matched_count))
    locked.rejected_count = max(0, int(rejected_count))
    locked.error_count = max(0, int(error_count))
    locked.completed_at = timezone.now()
    locked.save(update_fields=[
        'status', 'created_count', 'matched_count', 'rejected_count',
        'error_count', 'completed_at',
    ])
    return locked


@transaction.atomic
def mark_complaint_import_batch_failed(*, batch: ComplaintCaseImportBatch) -> ComplaintCaseImportBatch:
    """Leave a truthful retryable terminal marker when background processing aborts."""
    locked = ComplaintCaseImportBatch.objects.select_for_update().get(pk=batch.pk)
    if locked.status not in {
        ComplaintCaseImportBatch.STATUS_COMPLETE,
        ComplaintCaseImportBatch.STATUS_PARTIAL,
    }:
        locked.status = ComplaintCaseImportBatch.STATUS_FAILED
        locked.completed_at = timezone.now()
        locked.save(update_fields=['status', 'completed_at'])
    return locked
