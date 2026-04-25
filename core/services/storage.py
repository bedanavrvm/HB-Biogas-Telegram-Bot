"""
Storage Service

Handles persistence of raw, processed, and parsed messages.
Provides atomic transactions for data integrity.
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


def store_raw_message(
    telegram_message_id: str,
    content: str,
    sender: str = '',
    received_at: datetime = None,
    has_image: bool = False
) -> RawMessage:
    """
    Store a raw message for traceability.
    
    Args:
        telegram_message_id: Telegram message ID
        content: Raw message text
        sender: Sender name
        received_at: When message was received
        has_image: Whether message has an image
        
    Returns:
        Created RawMessage instance
    """
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
    except Exception as e:
        logger.error(f"Failed to store raw message: {e}", exc_info=True)
        raise


def store_parsed_message(
    processed_message: ProcessedMessage,
    parsed_result: ParsedResult,
    raw_content: str,
    source: str = 'telegram bot',
    group_id: str = 'default'
) -> ParsedMessage:
    """
    Store parsed message data.
    
    Args:
        processed_message: Associated ProcessedMessage
        parsed_result: ParsedResult from parser
        raw_content: Original message text
        source: Message source identifier (default: 'telegram bot')
        group_id: Telegram group ID for multi-tenant routing
        
    Returns:
        Created ParsedMessage instance
    """
    try:
        # Generate unique message_id
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
    except Exception as e:
        logger.error(f"Failed to store parsed message: {e}", exc_info=True)
        raise


@transaction.atomic
def process_and_store_message(
    telegram_message_id: str,
    content: str,
    sender: str = '',
    received_at: datetime = None,
    has_image: bool = False,
    parser_func=None,
    source: str = 'whatsapp_telegram',
    group_id: str = None,
    sheet_id: str = None
) -> Optional[ParsedMessage]:
    """
    Atomically process and store a message with deduplication.
    
    This is the main entry point for message processing.
    
    Args:
        telegram_message_id: Telegram message ID
        content: Raw message text
        sender: Sender name
        received_at: When message was received
        has_image: Whether message has an image
        parser_func: Optional custom parser function (default: uses parser.parse_message)
        source: Message source identifier
        
    Returns:
        ParsedMessage if successfully processed, None if duplicate
    """
    from core.services.parser import parse_message
    
    try:
        # Step 1: Generate hash and check for duplicates
        msg_hash = generate_message_hash(
            sender=sender,
            content=content,
            timestamp=str(received_at or timezone.now())
        )
        from core.services.deduplication import is_duplicate

        if is_duplicate(msg_hash):
            logger.info(f"Duplicate message detected, skipping: {msg_hash[:12]}...")
            return None

        # Step 2: Store raw message
        raw_message = store_raw_message(
            telegram_message_id=telegram_message_id,
            content=content,
            sender=sender,
            received_at=received_at,
            has_image=has_image,
        )

        # Step 3: Mark as processed early so we can update status later
        processed_message = mark_as_processed(
            raw_message=raw_message,
            message_hash=msg_hash,
            status='success'
        )

        # Step 4: Parse message
        if parser_func:
            parsed_result = parser_func(content, sender, has_image, received_at)
        else:
            parsed_result = parse_message(
                content=content,
                sender=sender,
                has_image=has_image,
                received_at=received_at,
            )

        # Step 5: Store parsed result
        parsed_message = store_parsed_message(
            processed_message=processed_message,
            parsed_result=parsed_result,
            raw_content=content,
            source=source,
            group_id=group_id or 'default',
        )

        # Step 6: Sync to Google Sheets and update status
        sync_success = False
        sync_error = ''
        try:
            from core.services.sheets import append_parsed_message_to_sheet
            sync_success = append_parsed_message_to_sheet(parsed_message)
            if not sync_success:
                sync_error = 'Google Sheets sync failed'
        except Exception as e:
            sync_error = str(e)
            logger.warning(f"Failed to sync to Google Sheets (message stored): {e}")

        final_status = 'success'
        if parsed_result.confidence < 1.0 or parsed_result.warnings:
            final_status = 'partial'
        if not sync_success:
            final_status = 'partial'

        # Attach runtime processing metadata for caller use
        parsed_message._processing_status = final_status
        parsed_message._processing_error = sync_error

        if final_status != processed_message.status or sync_error:
            processed_message.status = final_status
            processed_message.error_message = sync_error
            processed_message.save(update_fields=['status', 'error_message'])

        return parsed_message
        
    except Exception as e:
        logger.error(f"Failed to process and store message: {e}", exc_info=True)
        
        # Mark as failed if we have raw_message
        if 'raw_message' in locals():
            try:
                mark_as_processed(
                    raw_message=raw_message,
                    message_hash=msg_hash if 'msg_hash' in locals() else 'error',
                    status='failed',
                    error_message=str(e),
                )
            except Exception:
                pass
        
        raise


def get_unsynced_messages(limit: int = 100, max_attempts: int = 5) -> list:
    """
    Get messages that haven't been synced to Google Sheets and are still eligible for retry.
    
    Args:
        limit: Maximum number of messages to return
        max_attempts: Maximum number of sync attempts before skipping
        
    Returns:
        List of ParsedMessage instances
    """
    return ParsedMessage.objects.filter(
        synced_to_sheets=False,
        sync_attempts__lt=max_attempts,
    ).order_by('timestamp')[:limit]


def bulk_resync_to_sheets(limit: int = 100, max_attempts: int = 5) -> dict:
    """
    Resync unsynced messages to Google Sheets.
    
    Args:
        limit: Maximum number of messages to resync
        max_attempts: Maximum sync attempts per message
        
    Returns:
        Dict with sync results
    """
    from core.services.sheets import batch_append_messages
    
    unsynced = get_unsynced_messages(limit, max_attempts)
    
    if not unsynced:
        return {
            'success_count': 0,
            'failed_count': 0,
            'errors': ['No eligible unsynced messages'],
            'attempted': 0,
        }
    
    result = batch_append_messages(list(unsynced))
    result['attempted'] = len(unsynced)
    logger.info(f"Resync complete: {result}")
    
    return result


def append_parsed_message_to_sheet(parsed_message):
    """Backward-compatible helper for tests and external callers."""
    from core.services.sheets import append_parsed_message_to_sheet as _append
    return _append(parsed_message)
