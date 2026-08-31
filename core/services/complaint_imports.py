"""Durable, leased execution for auditable WhatsApp complaint imports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import json
import re
import uuid

import requests

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from core.models import (
    ComplaintCaseImportBatch,
    ComplaintCaseImportItem,
    IntegrationOperation,
    ParsedMessage,
)


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
            ComplaintCaseImportBatch.STATUS_COMPLETED,
            ComplaintCaseImportBatch.STATUS_PARTIAL,
            ComplaintCaseImportBatch.STATUS_CANCELLED,
        }

    @property
    def already_processing(self) -> bool:
        return not self.created and not self.retrying and self.batch.status in {
            ComplaintCaseImportBatch.STATUS_QUEUED,
            ComplaintCaseImportBatch.STATUS_RUNNING,
        }


def _require_import_actor(actor) -> None:
    if actor is None or not actor.is_active or not actor.is_superuser:
        raise ComplaintImportAuthorizationError(
            'Complaint batch imports are restricted to an active Django Superuser.'
        )


def _entry_snapshot(entry: dict, *, fallback_sender: str = '', fallback_received_at=None) -> dict:
    received_at = entry.get('received_at') or fallback_received_at
    received_value = received_at.isoformat() if isinstance(received_at, datetime) else str(received_at or '')
    return {
        'sender': str(entry.get('sender') or fallback_sender or '').strip(),
        'content': str(entry.get('content') or '').strip(),
        'received_at': received_value,
        'raw_header': str(entry.get('raw_header') or ''),
    }


def _snapshot_hash(snapshot: dict) -> str:
    encoded = json.dumps(snapshot, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


@transaction.atomic
def reserve_complaint_import_batch(
    *, actor, group_id: str, source_telegram_message_id: str,
    telegram_user_id: str, source_hash: str, source_count: int,
    entries: list[dict] | None = None, fallback_sender: str = '',
    fallback_received_at=None, analysis_snapshot: dict | None = None,
) -> ComplaintImportReservation:
    """Reserve a batch and all immutable entry snapshots in one transaction."""
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
    if entries is not None and len(entries) != int(source_count):
        raise ComplaintImportError('The complaint import snapshot count is inconsistent.')

    safe_analysis = {
        key: (analysis_snapshot or {}).get(key)
        for key in ('format', 'system_lines', 'orphan_lines', 'line_count')
        if (analysis_snapshot or {}).get(key) is not None
    }
    batch, created = ComplaintCaseImportBatch.objects.get_or_create(
        group_id=normalized_group_id,
        source_telegram_message_id=normalized_message_id,
        defaults={
            'initiated_by': actor,
            'actor_label': str(actor.get_full_name() or actor.get_username() or '')[:255],
            'telegram_user_id_snapshot': str(telegram_user_id or '').strip()[:64],
            'source_hash': normalized_hash,
            'source_count': int(source_count),
            'analysis_snapshot': safe_analysis,
            'status': ComplaintCaseImportBatch.STATUS_QUEUED,
        },
    )
    retrying = False
    if not created:
        batch = ComplaintCaseImportBatch.objects.select_for_update().get(pk=batch.pk)
        if batch.source_hash != normalized_hash or batch.source_count != int(source_count):
            raise ComplaintImportConflict(
                'That Telegram message was already used for a different batch import.'
            )
        if batch.status == ComplaintCaseImportBatch.STATUS_FAILED:
            retry_complaint_import_batch(batch=batch)
            batch.refresh_from_db()
            retrying = True

    if entries is not None:
        snapshots = [
            _entry_snapshot(entry, fallback_sender=fallback_sender, fallback_received_at=fallback_received_at)
            for entry in entries
        ]
        existing = {
            item.source_index: item
            for item in ComplaintCaseImportItem.objects.select_for_update().filter(batch=batch)
        }
        if existing and len(existing) != len(snapshots):
            raise ComplaintImportConflict('The saved complaint import item count is inconsistent.')
        new_items = []
        for source_index, snapshot in enumerate(snapshots):
            digest = _snapshot_hash(snapshot)
            saved = existing.get(source_index)
            if saved:
                if saved.content_hash != digest or saved.normalized_entry_snapshot != snapshot:
                    raise ComplaintImportConflict(
                        'The complaint import source position changed during replay.'
                    )
            else:
                new_items.append(ComplaintCaseImportItem(
                    batch=batch, source_index=source_index,
                    normalized_entry_snapshot=snapshot, content_hash=digest,
                ))
        if new_items:
            ComplaintCaseImportItem.objects.bulk_create(new_items)
    return ComplaintImportReservation(batch=batch, created=created, retrying=retrying)


@transaction.atomic
def associate_complaint_import_item(
    *, batch: ComplaintCaseImportBatch, parsed_message: ParsedMessage | None = None,
    parsed_message_id=None, source_index: int,
) -> tuple[ComplaintCaseImportItem, bool]:
    """Idempotently attach a durable source item to its canonical complaint."""
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
        if existing_for_message.batch_id != batch.pk or existing_for_message.source_index != int(source_index):
            raise ComplaintImportConflict('The complaint is already attributed to a different import source.')
        return existing_for_message, False

    item = ComplaintCaseImportItem.objects.select_for_update().filter(
        batch=batch, source_index=int(source_index),
    ).first()
    if item:
        if item.parsed_message_id and item.parsed_message_id != message_id:
            raise ComplaintImportConflict('The import source position is already attributed to a different complaint.')
        created = item.parsed_message_id is None
        item.parsed_message_id = message_id
        item.outcome_reference = str(message_id)[:128]
        if item.status in {ComplaintCaseImportItem.STATUS_QUEUED, ComplaintCaseImportItem.STATUS_RUNNING}:
            item.status = ComplaintCaseImportItem.STATUS_CREATED
        item.save(update_fields=['parsed_message', 'outcome_reference', 'status', 'updated_at'])
        return item, created

    try:
        with transaction.atomic():
            item = ComplaintCaseImportItem.objects.create(
                batch=batch, parsed_message_id=message_id, source_index=int(source_index),
                status=ComplaintCaseImportItem.STATUS_CREATED,
                outcome_reference=str(message_id)[:128],
            )
    except IntegrityError:
        item = ComplaintCaseImportItem.objects.filter(parsed_message_id=message_id).first()
        if item and item.batch_id == batch.pk and item.source_index == int(source_index):
            return item, False
        raise ComplaintImportConflict('The complaint import attribution conflicts with an existing source.')
    return item, True


def _privacy_safe_error_code(error: Exception) -> str:
    from core.services.external_resilience import redacted_error_code
    code = redacted_error_code(error)
    if code == 'external_error':
        code = re.sub(r'(?<!^)(?=[A-Z])', '_', type(error).__name__).lower()
    return str(code or 'processing_error')[:80]


def _parse_snapshot_time(value: str):
    try:
        parsed = datetime.fromisoformat(str(value or '').replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return timezone.now()
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


@transaction.atomic
def claim_complaint_import_batch(*, lease_seconds: int | None = None):
    """Claim one queued or stale batch using a cross-process database lease."""
    now = timezone.now()
    lease = max(30, int(lease_seconds or getattr(settings, 'DURABLE_JOB_LEASE_SECONDS', 300) or 300))
    stale_before = now - timedelta(seconds=lease)
    candidates = ComplaintCaseImportBatch.objects.filter(
        Q(status=ComplaintCaseImportBatch.STATUS_QUEUED)
        | Q(status=ComplaintCaseImportBatch.STATUS_RUNNING, heartbeat_at__lt=stale_before)
        | Q(status=ComplaintCaseImportBatch.STATUS_RUNNING, heartbeat_at__isnull=True)
    ).order_by('created_at')
    try:
        batch = candidates.select_for_update(skip_locked=True).first()
    except NotImplementedError:
        batch = candidates.select_for_update().first()
    if batch is None:
        return None, None
    recovering_stale_lease = batch.status == ComplaintCaseImportBatch.STATUS_RUNNING
    if recovering_stale_lease:
        batch.items.filter(status=ComplaintCaseImportItem.STATUS_RUNNING).update(
            status=ComplaintCaseImportItem.STATUS_QUEUED,
            last_error_code='stale_lease_recovered',
        )
    token = uuid.uuid4()
    batch.status = ComplaintCaseImportBatch.STATUS_RUNNING
    batch.lease_token = token
    batch.heartbeat_at = now
    batch.started_at = batch.started_at or now
    batch.attempt_count += 1
    batch.last_error_code = ''
    batch.completed_at = None
    batch.save(update_fields=[
        'status', 'lease_token', 'heartbeat_at', 'started_at', 'attempt_count',
        'last_error_code', 'completed_at', 'updated_at',
    ])
    return batch, token


def _process_import_item(batch_id, item_id, token) -> None:
    from core.services.parser import MessageIntent, detect_message_intent
    with transaction.atomic():
        batch = ComplaintCaseImportBatch.objects.select_for_update().get(pk=batch_id)
        if batch.lease_token != token or batch.status != ComplaintCaseImportBatch.STATUS_RUNNING:
            raise ComplaintImportConflict('The complaint import lease is no longer active.')
        item = ComplaintCaseImportItem.objects.select_for_update().get(pk=item_id, batch=batch)
        if item.status != ComplaintCaseImportItem.STATUS_QUEUED:
            return
        item.status = ComplaintCaseImportItem.STATUS_RUNNING
        item.attempt_count += 1
        item.started_at = item.started_at or timezone.now()
        item.last_error_code = ''
        item.save(update_fields=['status', 'attempt_count', 'started_at', 'last_error_code', 'updated_at'])
        snapshot = dict(item.normalized_entry_snapshot or {})

    content = str(snapshot.get('content') or '')
    if detect_message_intent(content) != MessageIntent.COMPLAINT:
        result = {'outcome': ComplaintCaseImportItem.STATUS_SKIPPED, 'error_code': 'not_complaint'}
    else:
        try:
            from core.api.views import _batch_append_case_results, _process_single_message
            from core.services.group_config import GroupRegistry
            from core.services.storage import duplicate_case_for_message, repair_case_sheet_sync
            processing = _process_single_message(
                telegram_message_id=f'{batch.source_telegram_message_id}_wa_{item.source_index}',
                content=content,
                sender=str(snapshot.get('sender') or batch.actor_label),
                has_image=False,
                received_at=_parse_snapshot_time(snapshot.get('received_at')),
                group_id=batch.group_id,
                source_telegram_message_id=batch.source_telegram_message_id,
                batch_index=item.source_index,
                source='whatsapp_export', sync_after_success=False, defer_sheet_sync=True,
            )
            status = processing.get('status')
            if status == 'duplicate':
                existing_case, _ = duplicate_case_for_message(
                    sender=str(snapshot.get('sender') or batch.actor_label), content=content,
                    received_at=_parse_snapshot_time(snapshot.get('received_at')),
                )
                if existing_case:
                    repair_case_sheet_sync(
                        existing_case, group_config=GroupRegistry.get_instance().get_group(batch.group_id),
                    )
                    result = {'outcome': ComplaintCaseImportItem.STATUS_MATCHED, 'parsed_message_id': existing_case.pk}
                else:
                    result = {'outcome': ComplaintCaseImportItem.STATUS_FAILED, 'error_code': 'duplicate_case_missing'}
            elif status in {'success', 'partial'} and processing.get('parsed_message_id'):
                _batch_append_case_results([processing], group_id=batch.group_id)
                result = {'outcome': ComplaintCaseImportItem.STATUS_CREATED, 'parsed_message_id': processing['parsed_message_id']}
            elif status == 'rejected':
                result = {'outcome': ComplaintCaseImportItem.STATUS_SKIPPED, 'error_code': 'validation_rejected'}
            else:
                result = {'outcome': ComplaintCaseImportItem.STATUS_FAILED, 'error_code': 'processing_failed'}
        except Exception as exc:
            result = {'outcome': ComplaintCaseImportItem.STATUS_FAILED, 'error_code': _privacy_safe_error_code(exc)}

    with transaction.atomic():
        batch = ComplaintCaseImportBatch.objects.select_for_update().get(pk=batch_id)
        if batch.lease_token != token or batch.status != ComplaintCaseImportBatch.STATUS_RUNNING:
            return
        item = ComplaintCaseImportItem.objects.select_for_update().get(pk=item_id, batch=batch)
        message_id = result.get('parsed_message_id')
        item.status = result['outcome']
        item.last_error_code = str(result.get('error_code') or '')[:80]
        item.completed_at = timezone.now()
        if message_id:
            item.parsed_message_id = message_id
            item.outcome_reference = str(message_id)[:128]
        elif item.status == ComplaintCaseImportItem.STATUS_SKIPPED:
            item.outcome_reference = item.last_error_code
        item.save(update_fields=[
            'status', 'last_error_code', 'completed_at', 'parsed_message',
            'outcome_reference', 'updated_at',
        ])
        batch.heartbeat_at = timezone.now()
        batch.save(update_fields=['heartbeat_at', 'updated_at'])


def _completion_text(batch: ComplaintCaseImportBatch) -> str:
    label = 'completed' if batch.status == ComplaintCaseImportBatch.STATUS_COMPLETED else 'completed with items needing review'
    return (
        f'WhatsApp complaint import {label}.\nCreated: {batch.created_count}\n'
        f'Matched existing: {batch.matched_count}\nSkipped: {batch.rejected_count}\nErrors: {batch.error_count}'
    )


def _reserve_completion_notification(batch: ComplaintCaseImportBatch):
    from core.services.external_resilience import reserve_operation
    return reserve_operation(
        integration=IntegrationOperation.INTEGRATION_TELEGRAM,
        operation_type='complaint_import_completion',
        deduplication_key=(
            f'telegram:complaint-import-complete:{batch.pk}:{batch.attempt_count}'
        ),
        source_model='ComplaintCaseImportBatch', source_id=str(batch.pk),
        request_id=batch.source_telegram_message_id, requested_by=batch.initiated_by,
        requested_by_label=batch.actor_label,
        operation_payload=(str(batch.pk), batch.status, batch.created_count, batch.matched_count, batch.rejected_count, batch.error_count),
        metadata={'notification_kind': 'complaint_import_completion'},
    )


@transaction.atomic
def _finish_or_requeue_batch(batch_id, token) -> ComplaintCaseImportBatch:
    batch = ComplaintCaseImportBatch.objects.select_for_update().get(pk=batch_id)
    if batch.lease_token != token:
        return batch
    items = batch.items.all()
    batch.created_count = items.filter(status=ComplaintCaseImportItem.STATUS_CREATED).count()
    batch.matched_count = items.filter(status=ComplaintCaseImportItem.STATUS_MATCHED).count()
    batch.rejected_count = items.filter(status=ComplaintCaseImportItem.STATUS_SKIPPED).count()
    batch.error_count = items.filter(status=ComplaintCaseImportItem.STATUS_FAILED).count()
    pending = items.filter(status__in=[ComplaintCaseImportItem.STATUS_QUEUED, ComplaintCaseImportItem.STATUS_RUNNING]).exists()
    batch.lease_token = None
    batch.heartbeat_at = timezone.now()
    if pending:
        batch.status = ComplaintCaseImportBatch.STATUS_QUEUED
        batch.last_error_code = ''
        batch.completed_at = None
    else:
        first_error_code = items.filter(
            Q(status=ComplaintCaseImportItem.STATUS_FAILED)
            | Q(last_error_code='validation_rejected')
        ).exclude(last_error_code='').order_by('source_index').values_list(
            'last_error_code', flat=True,
        ).first()
        batch.last_error_code = str(first_error_code or '')[:80]
        batch.status = (
            ComplaintCaseImportBatch.STATUS_PARTIAL
            if batch.error_count or items.filter(last_error_code='validation_rejected').exists()
            else ComplaintCaseImportBatch.STATUS_COMPLETED
        )
        batch.completed_at = timezone.now()
    batch.save(update_fields=[
        'created_count', 'matched_count', 'rejected_count', 'error_count',
        'lease_token', 'heartbeat_at', 'status', 'last_error_code',
        'completed_at', 'updated_at',
    ])
    if not pending:
        _reserve_completion_notification(batch)
    return batch


def process_complaint_import_batch_chunk(batch_id, *, lease_token, item_limit: int) -> dict:
    """Process a bounded chunk and persist progress after every item."""
    limit = max(1, min(int(item_limit), 1000))
    processed = 0
    while processed < limit:
        batch = ComplaintCaseImportBatch.objects.filter(pk=batch_id).first()
        if not batch or batch.lease_token != lease_token or batch.status != ComplaintCaseImportBatch.STATUS_RUNNING:
            break
        item = batch.items.filter(
            status=ComplaintCaseImportItem.STATUS_QUEUED,
        ).order_by('source_index').first()
        if item is None:
            break
        _process_import_item(batch.pk, item.pk, lease_token)
        processed += 1
    batch = _finish_or_requeue_batch(batch_id, lease_token)
    return {'batch_id': str(batch.pk), 'processed_items': processed, 'status': batch.status}


def process_next_complaint_import_batch(*, item_limit: int) -> dict | None:
    batch, token = claim_complaint_import_batch()
    if batch is None:
        return None
    return process_complaint_import_batch_chunk(batch.pk, lease_token=token, item_limit=item_limit)


def deliver_complaint_import_notifications(*, limit: int = 10) -> int:
    """Attempt due completion notifications with one durable attempt each."""
    from core.services.external_resilience import ExternalOperationError, execute_operation
    now = timezone.now()
    operations = IntegrationOperation.objects.filter(
        integration=IntegrationOperation.INTEGRATION_TELEGRAM,
        operation_type='complaint_import_completion',
        status__in=[IntegrationOperation.STATUS_PENDING, IntegrationOperation.STATUS_RETRYABLE],
    ).filter(Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=now)).order_by('created_at')[:max(1, int(limit))]
    delivered = 0
    for operation in operations:
        batch = ComplaintCaseImportBatch.objects.filter(pk=operation.source_id).first()
        if batch is None:
            continue

        def send_once():
            token = str(getattr(settings, 'TELEGRAM_BOT_TOKEN', '') or '').strip()
            if not token:
                raise RuntimeError('telegram_token_missing')
            response = requests.post(
                f'https://api.telegram.org/bot{token}/sendMessage',
                data={
                    'chat_id': batch.group_id,
                    'reply_to_message_id': batch.source_telegram_message_id,
                    'text': _completion_text(batch)[:4000],
                },
                timeout=int(getattr(settings, 'API_REQUEST_TIMEOUT', 10) or 10),
            )
            response.raise_for_status()
            payload = response.json() if response.content else {}
            return {'message_id': (payload.get('result') or {}).get('message_id')}

        try:
            result = execute_operation(operation, send_once, attempt_budget=1)
            if result is not None:
                delivered += 1
        except ExternalOperationError:
            continue
    return delivered


@transaction.atomic
def retry_complaint_import_batch(*, batch: ComplaintCaseImportBatch) -> ComplaintCaseImportBatch:
    locked = ComplaintCaseImportBatch.objects.select_for_update().get(pk=batch.pk)
    if locked.status not in {
        ComplaintCaseImportBatch.STATUS_PARTIAL,
        ComplaintCaseImportBatch.STATUS_FAILED,
        ComplaintCaseImportBatch.STATUS_CANCELLED,
    }:
        return locked
    locked.items.filter(status__in=[
        ComplaintCaseImportItem.STATUS_FAILED, ComplaintCaseImportItem.STATUS_CANCELLED,
    ]).update(status=ComplaintCaseImportItem.STATUS_QUEUED, last_error_code='', completed_at=None)
    locked.status = ComplaintCaseImportBatch.STATUS_QUEUED
    locked.lease_token = None
    locked.heartbeat_at = None
    locked.last_error_code = ''
    locked.completed_at = None
    locked.save(update_fields=[
        'status', 'lease_token', 'heartbeat_at', 'last_error_code', 'completed_at', 'updated_at',
    ])
    return locked


@transaction.atomic
def cancel_complaint_import_batch(*, batch: ComplaintCaseImportBatch) -> ComplaintCaseImportBatch:
    locked = ComplaintCaseImportBatch.objects.select_for_update().get(pk=batch.pk)
    if locked.status in {ComplaintCaseImportBatch.STATUS_COMPLETED, ComplaintCaseImportBatch.STATUS_CANCELLED}:
        return locked
    locked.items.filter(status__in=[
        ComplaintCaseImportItem.STATUS_QUEUED, ComplaintCaseImportItem.STATUS_RUNNING,
        ComplaintCaseImportItem.STATUS_FAILED,
    ]).update(status=ComplaintCaseImportItem.STATUS_CANCELLED, completed_at=timezone.now())
    locked.status = ComplaintCaseImportBatch.STATUS_CANCELLED
    locked.lease_token = None
    locked.heartbeat_at = timezone.now()
    locked.completed_at = timezone.now()
    locked.save(update_fields=['status', 'lease_token', 'heartbeat_at', 'completed_at', 'updated_at'])
    return locked


@transaction.atomic
def finalize_complaint_import_batch(
    *, batch: ComplaintCaseImportBatch, created_count: int, matched_count: int,
    rejected_count: int, error_count: int,
) -> ComplaintCaseImportBatch:
    """Compatibility finalizer for existing direct service callers."""
    locked = ComplaintCaseImportBatch.objects.select_for_update().get(pk=batch.pk)
    if locked.status in {ComplaintCaseImportBatch.STATUS_COMPLETED, ComplaintCaseImportBatch.STATUS_PARTIAL}:
        return locked
    locked.status = (
        ComplaintCaseImportBatch.STATUS_COMPLETED
        if not int(rejected_count) and not int(error_count)
        else ComplaintCaseImportBatch.STATUS_PARTIAL
    )
    locked.created_count = max(0, int(created_count))
    locked.matched_count = max(0, int(matched_count))
    locked.rejected_count = max(0, int(rejected_count))
    locked.error_count = max(0, int(error_count))
    locked.lease_token = None
    locked.completed_at = timezone.now()
    locked.save(update_fields=[
        'status', 'created_count', 'matched_count', 'rejected_count',
        'error_count', 'lease_token', 'completed_at', 'updated_at',
    ])
    return locked


@transaction.atomic
def mark_complaint_import_batch_failed(
    *, batch: ComplaintCaseImportBatch, error_code: str = 'runner_failed',
) -> ComplaintCaseImportBatch:
    locked = ComplaintCaseImportBatch.objects.select_for_update().get(pk=batch.pk)
    if locked.status not in {
        ComplaintCaseImportBatch.STATUS_COMPLETED,
        ComplaintCaseImportBatch.STATUS_PARTIAL,
        ComplaintCaseImportBatch.STATUS_CANCELLED,
    }:
        locked.status = ComplaintCaseImportBatch.STATUS_FAILED
        locked.lease_token = None
        locked.last_error_code = str(error_code or 'runner_failed')[:80]
        locked.completed_at = timezone.now()
        locked.save(update_fields=[
            'status', 'lease_token', 'last_error_code', 'completed_at', 'updated_at',
        ])
    return locked
