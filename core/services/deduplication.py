"""
Deduplication service for preventing duplicate message processing.

Uses a deterministic hash based on sender + content + timestamp window
to identify and filter duplicate messages.
"""
import hashlib
from datetime import timedelta
from django.utils import timezone
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


def generate_message_hash(sender: str, content: str, timestamp: str = None) -> str:
    """
    Generate a deterministic hash for deduplication.
    
    The hash is based on:
    - Normalized sender name (lowercase, stripped)
    - Normalized content (lowercase, stripped, whitespace collapsed)
    - Timestamp window (rounded to nearest N minutes)
    
    This ensures that slightly different forwards of the same message
    will produce the same hash.
    
    Args:
        sender: Message sender name
        content: Message text content
        timestamp: Optional timestamp string (ISO format)
        
    Returns:
        SHA256 hash string (first 64 chars)
    """
    # Normalize inputs
    sender_norm = sender.strip().lower() if sender else ''
    content_norm = ' '.join(content.strip().lower().split()) if content else ''
    
    # Apply timestamp windowing if provided
    time_window = ''
    if timestamp:
        try:
            from dateutil import parser as date_parser
            dt = date_parser.parse(timestamp)
            # Round down to nearest window
            window_minutes = settings.DEDUPLICATION_WINDOW_MINUTES
            rounded_minute = (dt.minute // window_minutes) * window_minutes
            dt_rounded = dt.replace(minute=rounded_minute, second=0, microsecond=0)
            time_window = dt_rounded.isoformat()
        except Exception:
            logger.warning(f"Could not parse timestamp '{timestamp}', using empty window")
            time_window = ''
    
    # Create hash input
    hash_input = f"{sender_norm}|{content_norm}|{time_window}"
    
    # Generate SHA256 hash
    return hashlib.sha256(hash_input.encode('utf-8')).hexdigest()[:64]


def is_duplicate(message_hash: str) -> bool:
    """
    Check if a message hash already exists in the database.

    Only consider messages that were processed successfully or partially.
    Failed processing attempts should not prevent retries.
    """
    from core.models import ProcessedMessage

    try:
        return ProcessedMessage.objects.filter(
            message_hash=message_hash
        ).exclude(status='failed').exists()
    except Exception as e:
        logger.error(f"Error checking deduplication for hash {message_hash[:12]}...: {e}")
        # On error, assume not duplicate to avoid data loss
        return False


def check_duplicates(hashes: list[str]) -> dict[str, bool]:
    """
    Batch check multiple hashes for duplicates.
    
    Args:
        hashes: List of message hashes to check
        
    Returns:
        Dict mapping hash -> is_duplicate (True if duplicate)
    """
    from core.models import ProcessedMessage
    
    try:
        existing_hashes = set(
            ProcessedMessage.objects.filter(
                message_hash__in=hashes
            ).values_list('message_hash', flat=True)
        )
        
        return {h: h in existing_hashes for h in hashes}
    except Exception as e:
        logger.error(f"Error in batch deduplication check: {e}")
        return {h: False for h in hashes}


def filter_new_messages(raw_messages: list) -> list:
    """
    Filter a list of RawMessage objects, returning only non-duplicates.
    
    Args:
        raw_messages: List of RawMessage objects to filter
        
    Returns:
        List of RawMessage objects that are NOT duplicates
    """
    from core.models import RawMessage
    
    # Generate hashes for all messages
    hashes_to_check = []
    message_hash_map = []
    
    for msg in raw_messages:
        msg_hash = generate_message_hash(
            sender=msg.sender,
            content=msg.content,
            timestamp=str(msg.received_at)
        )
        hashes_to_check.append(msg_hash)
        message_hash_map.append((msg, msg_hash))
    
    # Batch check for duplicates
    duplicate_status = check_duplicates(hashes_to_check)
    
    # Filter out duplicates
    new_messages = []
    for msg, msg_hash in message_hash_map:
        if not duplicate_status.get(msg_hash, False):
            new_messages.append(msg)
        else:
            logger.info(f"Skipping duplicate message from {msg.sender}: {msg_hash[:12]}...")
    
    logger.info(
        f"Deduplication: {len(new_messages)} new, "
        f"{len(raw_messages) - len(new_messages)} duplicates out of {len(raw_messages)}"
    )
    
    return new_messages


def mark_as_processed(raw_message, message_hash: str, status: str = 'success', 
                     error_message: str = '') -> 'ProcessedMessage':
    """
    Mark a message as processed to prevent future duplicates.
    
    Args:
        raw_message: RawMessage object that was processed
        message_hash: The hash used for deduplication
        status: Processing status (success, failed, partial)
        error_message: Error details if processing failed
        
    Returns:
        Created ProcessedMessage object
    """
    from core.models import ProcessedMessage
    
    try:
        processed, created = ProcessedMessage.objects.get_or_create(
            message_hash=message_hash,
            defaults={
                'raw_message': raw_message,
                'status': status,
                'error_message': error_message,
            }
        )
        
        if not created:
            logger.warning(f"Message hash {message_hash[:12]}... already marked as processed")
        else:
            logger.debug(f"Marked message {message_hash[:12]}... as {status}")
            
        return processed
    except Exception as e:
        logger.error(f"Error marking message as processed: {e}")
        raise
