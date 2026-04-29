"""
Storage Service

Handles persistence of raw, processed, and parsed messages.
Provides atomic transactions for data integrity.

KEY FIXES (v2):
- process_and_store_message now forwards *sheet_id* to
  append_parsed_message_to_sheet so each group's data lands in
  its own Google Sheet.
- bulk_resync_to_sheets resolves the correct sheet_id per-message
  using the stored group_id, then calls append_parsed_message_to_sheet
  with that sheet_id.  This means historical messages are resynced to
  the right sheet even when different groups share the same worker.
"""
import logging
from datetime import datetime
from typing import Optional
from django.db import transaction
from django.utils import timezone
from core.models import RawMessage, ProcessedMessage, ParsedMessage
from core.services.deduplication import generate_message_hash, mark_as_processed
from core.services.parser import ParsedResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Raw message storage
# ---------------------------------------------------------------------------

def store_raw_message(
    telegram_message_id: str,
    content: str,
    sender: str = '',
    received_at: datetime = None,
    has_image: bool = False,
) -> RawMessage:
    try:
        raw_message = RawMessage.objects.create(
            telegram_message_id=telegram_message_id,
            sender=sender,
            content=content,
            received_at=received_at or timezone.now(),
            has_image=has_image,
        )
        logger.debug(f"Stored raw message {raw_message.id} from {sender}")
        return raw_message
    except Exception as exc:
        logger.error(f"Failed to store raw message: {exc}", exc_info=True)
        raise


# ---------------------------------------------------------------------------
# Parsed message storage
# ---------------------------------------------------------------------------

def store_parsed_message(
    processed_message: ProcessedMessage,
    parsed_result: ParsedResult,
    raw_content: str,
    source: str = 'telegram bot',
    group_id: str = 'default',
) -> ParsedMessage:
    try:
        message_id = f"MSG_{processed_message.message_hash[:16].upper()}"

        parsed_message = ParsedMessage.objects.create(
            processed_message=processed_message,
            message_id=message_id,
            timestamp=parsed_result.timestamp,
            sender=parsed_result.sender,
            raw_message=raw_content,
            item=parsed_result.item,
            quantity=parsed_result.quantity,
            price=parsed_result.price,
            gps_link=parsed_result.gps_link,
            image_flag=parsed_result.image_flag,
            source=source,
            group_id=group_id,
            customer_name=parsed_result.customer_name,
            customer_phone=parsed_result.customer_phone,
            customer_id=parsed_result.customer_id,
            complaint_category=getattr(parsed_result, 'complaint_category', ''),
            complaint_description=parsed_result.problem_description,
        )

        logger.info(
            f"Stored parsed message {message_id}: "
            f"item={parsed_result.item}, qty={parsed_result.quantity}, "
            f"price={parsed_result.price}, confidence={parsed_result.confidence}"
        )
        return parsed_message

    except Exception as exc:
        logger.error(f"Failed to store parsed message: {exc}", exc_info=True)
        raise


# ---------------------------------------------------------------------------
# Main processing entry point
# ---------------------------------------------------------------------------

@transaction.atomic
def process_and_store_message(
    telegram_message_id: str,
    content: str,
    sender: str = '',
    received_at: datetime = None,
    has_image: bool = False,
    parser_func=None,
    source: str = 'telegram bot',
    group_id: str = None,
    sheet_name: str = None,
    sheet_id: str = None,          # ← forwarded to Google Sheets service
) -> Optional[ParsedMessage]:
    """
    Atomically process and store a message with deduplication.

    Args:
        telegram_message_id: Telegram message ID
        content:             Raw message text
        sender:              Sender display name
        received_at:         When the message was received
        has_image:           Whether an image was attached
        parser_func:         Optional custom parser (default: parse_message)
        source:              Message source tag (default: 'telegram bot')
        group_id:            Telegram chat_id for multi-tenant routing
        sheet_name:          Worksheet/tab name for the group.
        sheet_id:            Google Sheet ID for the group (looked up from
                             GroupRegistry when None)

    Returns:
        ParsedMessage on success, None if message is a duplicate.
    """
    from core.services.parser import parse_message
    from core.services.deduplication import is_duplicate

    try:
        # ── 1. Deduplication ─────────────────────────────────────────
        msg_hash = generate_message_hash(
            sender=sender,
            content=content,
            timestamp=str(received_at or timezone.now()),
        )

        if is_duplicate(msg_hash):
            logger.info(f"Duplicate message detected, skipping: {msg_hash[:12]}…")
            return None

        # ── 2. Store raw ─────────────────────────────────────────────
        raw_message = store_raw_message(
            telegram_message_id=telegram_message_id,
            content=content,
            sender=sender,
            received_at=received_at,
            has_image=has_image,
        )

        # ── 3. Mark as processed ─────────────────────────────────────
        processed_message = mark_as_processed(
            raw_message=raw_message,
            message_hash=msg_hash,
            status='success',
        )

        # ── 4. Parse ─────────────────────────────────────────────────
        if parser_func:
            parsed_result = parser_func(content, sender, has_image, received_at)
        else:
            parsed_result = parse_message(
                content=content,
                sender=sender,
                has_image=has_image,
                received_at=received_at,
            )

        # ── 5. Store parsed ──────────────────────────────────────────
        parsed_message = store_parsed_message(
            processed_message=processed_message,
            parsed_result=parsed_result,
            raw_content=content,
            source=source,
            group_id=group_id or 'default',
        )

        # ── 6. Sync to the correct Google Sheet ──────────────────────
        #       sheet_id comes from the caller (resolved via GroupRegistry)
        #       and is forwarded here so the right sheet is written.
        sync_success = False
        sync_error = ''
        try:
            from core.services.sheets import append_parsed_message_to_sheet
            sync_success = append_parsed_message_to_sheet(
                parsed_message,
                sheet_name=sheet_name,
                sheet_id=sheet_id,          # ← KEY FIX
            )
            if not sync_success:
                sync_error = 'Google Sheets sync failed'
        except Exception as exc:
            sync_error = str(exc)
            logger.warning(
                f"Failed to sync message to sheet (message stored in DB): {exc}"
            )

        # ── 7. Determine final status ─────────────────────────────────
        final_status = 'success'
        if parsed_result.confidence < 1.0 or parsed_result.warnings:
            final_status = 'partial'
        if not sync_success:
            final_status = 'partial'

        # Attach runtime metadata for the caller (not persisted)
        parsed_message._processing_status = final_status
        parsed_message._processing_error = sync_error

        if final_status != processed_message.status or sync_error:
            processed_message.status = final_status
            processed_message.error_message = sync_error
            processed_message.save(update_fields=['status', 'error_message'])

        return parsed_message

    except Exception as exc:
        logger.error(
            f"Failed to process and store message: {exc}", exc_info=True
        )
        if 'raw_message' in locals():
            try:
                mark_as_processed(
                    raw_message=raw_message,
                    message_hash=msg_hash if 'msg_hash' in locals() else 'error',
                    status='failed',
                    error_message=str(exc),
                )
            except Exception:
                pass
        raise


# ---------------------------------------------------------------------------
# Resync helpers
# ---------------------------------------------------------------------------

def get_unsynced_messages(limit: int = 100, max_attempts: int = 5) -> list:
    """Return messages that have not yet been synced and are still retryable."""
    return list(
        ParsedMessage.objects.filter(
            synced_to_sheets=False,
            sync_attempts__lt=max_attempts,
        ).order_by('timestamp')[:limit]
    )


def bulk_resync_to_sheets(limit: int = 100, max_attempts: int = 5) -> dict:
    """
    Resync failed/unsynced messages to Google Sheets.

    Each message's group_id is used to look up the correct sheet_id via
    GroupRegistry, so messages from different groups are routed to their
    own sheets instead of all going to the global GOOGLE_SHEET_ID.
    """
    from core.services.sheets import append_parsed_message_to_sheet
    from core.services.group_config import (
        get_sheet_id_for_group,
        get_sheet_name_for_group,
    )

    unsynced = get_unsynced_messages(limit, max_attempts)

    if not unsynced:
        return {
            'success_count': 0,
            'failed_count': 0,
            'errors': ['No eligible unsynced messages'],
            'attempted': 0,
        }

    success_count = 0
    failed_count = 0
    errors = []

    for msg in unsynced:
        # Resolve the sheet for this message's group
        sheet_id = None
        sheet_name = None
        if msg.group_id:
            sheet_id = get_sheet_id_for_group(msg.group_id)
            sheet_name = get_sheet_name_for_group(msg.group_id)
            if not sheet_id:
                logger.warning(
                    f"Resync: cannot resolve sheet for group {msg.group_id} "
                    f"(message {msg.message_id}) — falling back to default sheet"
                )

        try:
            success = append_parsed_message_to_sheet(
                msg,
                sheet_id=sheet_id,
                sheet_name=sheet_name,
            )
            if success:
                success_count += 1
            else:
                failed_count += 1
        except Exception as exc:
            failed_count += 1
            errors.append(f"Message {msg.message_id}: {exc}")
            logger.error(
                f"Resync error for message {msg.message_id}: {exc}",
                exc_info=True,
            )

    result = {
        'success_count': success_count,
        'failed_count': failed_count,
        'errors': errors,
        'attempted': len(unsynced),
    }
    logger.info(f"Resync complete: {result}")
    return result


def append_parsed_message_to_sheet(
    parsed_message,
    sheet_id: str = None,
    sheet_name: str = None,
):
    """Backward-compatible shim used by tests and external callers."""
    from core.services.sheets import (
        append_parsed_message_to_sheet as _append,
    )
    return _append(parsed_message, sheet_id=sheet_id, sheet_name=sheet_name)
