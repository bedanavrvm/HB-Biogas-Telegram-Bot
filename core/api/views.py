"""
API Views for the biogas telegram bot.

Endpoints:
- POST /api/webhook/telegram/ - Receive Telegram webhook
- POST /api/process/messages/ - Manually trigger batch processing
- GET /api/health/ - Health check
- POST /api/resync/unsynced/ - Resync unsynced messages to Google Sheets

SECURITY FEATURES:
- Request size validation (max 1MB per request)
- Input field validation (required fields enforcement)
- API timeouts (10 seconds for external calls)
- Consistent error responses with error codes
- Rate limiting ready (optional django-ratelimit)
- Standardized request/response format
"""
import logging
from datetime import datetime, timezone as dt_timezone
from django.utils import timezone
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.conf import settings
import json
import requests

from .validators import (
    validate_request_size,
    validate_message_fields,
    validate_webhook_payload,
    validate_batch_messages,
    ValidationError,
    error_response,
    success_response,
    partial_response,
)

logger = logging.getLogger(__name__)

# Rate limiting decorator (optional - requires django-ratelimit package)
# To enable:
# 1. pip install django-ratelimit
# 2. Uncomment decorators below
# 3. Set RATELIMIT_ENABLE = True in settings.py
# 
# from django_ratelimit.decorators import ratelimit
# @ratelimit(key='ip', rate=settings.RATELIMIT_PER_IP, method='POST')



@csrf_exempt
@require_http_methods(["GET"])
def health_check(request):
    """
    Health check endpoint.
    Returns system status and version.
    """
    return success_response(
        data={
            'service': 'Biogas Telegram Bot',
            'version': '1.0.0',
            'timestamp': timezone.now().isoformat(),
            'database': 'connected',
        },
        message='Service is healthy'
    )


@csrf_exempt
@require_http_methods(["POST"])
def telegram_webhook(request):
    """
    Telegram webhook endpoint.
    
    Receives updates from Telegram Bot API.
    Processes incoming messages and stores structured data.
    
    Expected Telegram Update format:
    {
        "update_id": 123456,
        "message": {
            "message_id": 789,
            "from": {"id": 123, "first_name": "John"},
            "chat": {"id": -1001234567890, "type": "group"},
            "date": 1711123456,
            "text": "Forwarded message text",
            "caption": "Image caption if present"
        }
    }
    """
    try:
        # Step 1: Validate request size (DoS protection)
        try:
            validate_request_size(request)
        except ValidationError as e:
            return error_response(e.message, e.code, e.status_code)
        
        # Step 2: Parse request body
        try:
            body = json.loads(request.body)
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON received: {request.body[:100]}")
            return error_response(
                'Invalid JSON in request body',
                code='INVALID_JSON',
                status_code=400,
                details=str(e)
            )
        
        # Step 3: Validate webhook payload structure
        try:
            validate_webhook_payload(body)
        except ValidationError as e:
            return error_response(e.message, e.code, e.status_code)
        
        # Step 4: Validate webhook secret if configured
        if settings.TELEGRAM_WEBHOOK_SECRET:
            provided_secret = (
                request.headers.get('X-Telegram-Bot-Api-Secret-Token')
                or request.headers.get('X-Telegram-Webhook-Secret')
            )
            if provided_secret != settings.TELEGRAM_WEBHOOK_SECRET:
                logger.warning("Invalid webhook secret provided")
                return error_response(
                    'Unauthorized: Invalid webhook secret',
                    code='UNAUTHORIZED',
                    status_code=401
                )
        
        # Step 5: Handle different update types
        if 'message' in body:
            try:
                validate_message_fields(body['message'])
                result = _process_telegram_message(body['message'])
                _send_telegram_reply(body['message'], result)
                if result.get('status') == 'partial':
                    warnings = [result.get('error')] if result.get('error') else None
                    return partial_response(result, warnings=warnings)
                return success_response(result)
            except ValidationError as e:
                return error_response(e.message, e.code, e.status_code)
        
        elif 'channel_post' in body:
            try:
                validate_message_fields(body['channel_post'])
                result = _process_telegram_message(body['channel_post'])
                _send_telegram_reply(body['channel_post'], result)
                if result.get('status') == 'partial':
                    warnings = [result.get('error')] if result.get('error') else None
                    return partial_response(result, warnings=warnings)
                return success_response(result)
            except ValidationError as e:
                return error_response(e.message, e.code, e.status_code)
        
        else:
            # Silently ignore other update types (my_chat_member, edited_message, etc.)
            logger.debug(f"Ignored update type: {list(body.keys())}")
            return success_response(
                {'ignored': True},
                message='Update type not processed'
            )
            
    except Exception as e:
        logger.error(f"Unhandled error in webhook: {e}", exc_info=True)
        return error_response(
            'Internal server error',
            code='INTERNAL_ERROR',
            status_code=500,
            details=str(e)
        )


def _process_telegram_message(message_data: dict) -> dict:
    """
    Process a single Telegram message.
    
    Extracts group_id from message and routes to correct sheet config.
    
    Args:
        message_data: Telegram message object
        
    Returns:
        Dict with processing result
    """
    try:
        # Extract group/chat ID for multi-tenant routing
        group_id = str(message_data.get('chat', {}).get('id', ''))
        if not group_id:
            logger.error("Message missing chat.id - cannot route to group")
            return {
                'status': 'error',
                'error': 'Message missing chat information',
            }
        
        # Extract message fields
        telegram_message_id = str(message_data.get('message_id', ''))
        sender = _extract_sender_name(message_data)
        content = _extract_message_content(message_data)
        has_image = _detect_image(message_data)
        received_at = _extract_timestamp(message_data)
        
        if not content:
            logger.warning(f"No content in message {telegram_message_id}")
            return {
                'status': 'skipped',
                'reason': 'No message content',
                'message_id': telegram_message_id,
            }
        
        # Check if this is a batch forward with multiple messages
        messages = _split_if_batch(content, sender, has_image, received_at)
        
        if len(messages) > 1:
            # Process each message in the batch
            results = []
            for msg in messages:
                result = _process_single_message(
                    telegram_message_id=f"{telegram_message_id}_{msg['sender']}",
                    content=msg['content'],
                    sender=msg['sender'],
                    has_image=has_image,
                    received_at=received_at,
                    group_id=group_id,
                )
                results.append(result)
            
            success_count = sum(1 for r in results if r.get('status') == 'success')
            
            return {
                'status': 'batch_processed',
                'total': len(messages),
                'success': success_count,
                'duplicates': sum(1 for r in results if r.get('status') == 'duplicate'),
                'results': results,
            }
        else:
            # Process as single message
            return _process_single_message(
                telegram_message_id=telegram_message_id,
                content=content,
                sender=sender,
                has_image=has_image,
                received_at=received_at,
                group_id=group_id,
            )
            
    except Exception as e:
        logger.error(f"Error processing Telegram message: {e}", exc_info=True)
        return {
            'status': 'error',
            'error': str(e),
        }


def _process_single_message(
    telegram_message_id: str,
    content: str,
    sender: str,
    has_image: bool,
    received_at: datetime,
    group_id: str = None
) -> dict:
    """
    Process and store a single message.
    
    Args:
        group_id: Telegram chat_id for group-aware routing
    
    Returns:
        Dict with processing result
    """
    from core.services.storage import process_and_store_message
    from core.services.group_config import get_sheet_id_for_group
    
    try:
        # Validate group is configured
        if not group_id:
            return {
                'status': 'error',
                'error': 'No group_id provided',
            }
        
        sheet_id = get_sheet_id_for_group(group_id)
        if not sheet_id:
            logger.error(f"Unknown or unconfigured group: {group_id}")
            return {
                'status': 'error',
                'error': f'Unknown group: {group_id}',
            }
        
        parsed_message = process_and_store_message(
            telegram_message_id=telegram_message_id,
            content=content,
            sender=sender,
            received_at=received_at,
            has_image=has_image,
            group_id=group_id,
            sheet_id=sheet_id,
        )
        
        if parsed_message is None:
            return {
                'status': 'duplicate',
                'message_id': telegram_message_id,
            }

        # Collect captured fields based on message intent
        captured_fields = {}
        if hasattr(parsed_message, 'sender') and parsed_message.sender:
            captured_fields['sender'] = parsed_message.sender
        if hasattr(parsed_message, 'customer_name') and parsed_message.customer_name:
            captured_fields['customer_name'] = parsed_message.customer_name
        if hasattr(parsed_message, 'customer_phone') and parsed_message.customer_phone:
            captured_fields['customer_phone'] = parsed_message.customer_phone
        if hasattr(parsed_message, 'customer_id') and parsed_message.customer_id:
            captured_fields['customer_id'] = parsed_message.customer_id
        if hasattr(parsed_message, 'problem_description') and parsed_message.problem_description:
            captured_fields['problem_description'] = parsed_message.problem_description[:100]  # First 100 chars
        if hasattr(parsed_message, 'item') and parsed_message.item:
            captured_fields['item'] = parsed_message.item
        if hasattr(parsed_message, 'quantity') and parsed_message.quantity:
            captured_fields['quantity'] = str(parsed_message.quantity)
        if hasattr(parsed_message, 'price') and parsed_message.price:
            captured_fields['price'] = str(parsed_message.price)
        if hasattr(parsed_message, 'gps_link') and parsed_message.gps_link:
            captured_fields['location'] = parsed_message.gps_link

        result = {
            'status': getattr(parsed_message, '_processing_status', 'success'),
            'message_id': parsed_message.message_id,
            'captured_fields': captured_fields,
        }

        if result['status'] == 'partial':
            sync_error = getattr(parsed_message, '_processing_error', '')
            if sync_error:
                result['error'] = sync_error
            else:
                result['warning'] = 'Message processed with partial confidence or warnings.'

        return result
        
    except Exception as e:
        logger.error(f"Error in _process_single_message: {e}", exc_info=True)
        return {
            'status': 'error',
            'error': str(e),
        }


def _send_telegram_reply(message_data: dict, result: dict) -> None:
    """
    Send a Telegram reply message based on processing result.
    
    Args:
        message_data: Original Telegram message
        result: Processing result dict
    """
    chat_id = message_data.get('chat', {}).get('id')
    if not chat_id:
        return
    
    bot_token = settings.TELEGRAM_BOT_TOKEN
    if not bot_token:
        return
    
    # Determine reply message based on status
    status = result.get('status', 'unknown')
    captured_fields = result.get('captured_fields', {})
    
    # Build captured fields summary
    fields_summary = ''
    if captured_fields:
        field_names = []
        for key in captured_fields.keys():
            # Format field names: customer_name → 'Customer Name'
            display_name = key.replace('_', ' ').title()
            field_names.append(display_name)
        if field_names:
            fields_summary = f"\n📋 Captured: {', '.join(field_names)}"
    
    if status == 'success':
        text = f'✅ Message received and saved successfully{fields_summary}'
    elif status == 'partial':
        if result.get('error'):
            text = f'⚠️ Message received but sheet sync failed: {result.get("error")}{fields_summary}'
        else:
            text = f'⚠️ Message partially processed (some fields missing){fields_summary}'
    elif status == 'duplicate':
        text = '⚠️ Duplicate message - already processed'
    elif status == 'skipped':
        text = '⚠️ Message skipped - no content'
    elif status == 'batch_processed':
        success = result.get('success', 0)
        total = result.get('total', 0)
        text = f'✅ Batch processed: {success}/{total} messages saved'
    elif status == 'error':
        text = f'❌ Error: {result.get("error", "Unknown error")}'
    else:
        text = f'📝 Message processed: {status}'
    
    try:
        url = f'https://api.telegram.org/bot{bot_token}/sendMessage'
        payload = {
            'chat_id': chat_id,
            'text': text,
            'reply_to_message_id': message_data.get('message_id'),
        }
        # Add timeout to prevent hanging
        requests.post(
            url,
            data=payload,
            timeout=settings.API_REQUEST_TIMEOUT
        )
    except requests.Timeout:
        logger.warning(f"Timeout sending Telegram reply to chat {chat_id}")
    except Exception as e:
        logger.error(f"Failed to send Telegram reply: {e}")


def _extract_sender_name(message_data: dict) -> str:
    """Extract sender name from Telegram message."""
    from_user = message_data.get('from', {})
    if from_user:
        first_name = from_user.get('first_name', '')
        last_name = from_user.get('last_name', '')
        username = from_user.get('username', '')
        
        if first_name or last_name:
            return f"{first_name} {last_name}".strip()
        if username:
            return username
    
    # Fallback for forwarded messages
    forward_sender = message_data.get('forward_sender_name', '')
    if forward_sender:
        return forward_sender
    
    return ''


def _extract_message_content(message_data: dict) -> str:
    """Extract message content (text or caption)."""
    text = message_data.get('text', '')
    caption = message_data.get('caption', '')
    
    # Combine text and caption
    parts = []
    if text:
        parts.append(text)
    if caption:
        parts.append(caption)
    
    return '\n'.join(parts).strip()


def _detect_image(message_data: dict) -> bool:
    """Detect if message contains an image."""
    # Check for various media types
    media_keys = [
        'photo', 'document', 'video', 'animation',
        'sticker', 'voice', 'video_note',
    ]
    
    for key in media_keys:
        if key in message_data:
            return True
    
    # Check caption without text (image-only message)
    if message_data.get('caption') and not message_data.get('text'):
        return True
    
    return False


def _extract_timestamp(message_data: dict) -> datetime:
    """Extract message timestamp."""
    date_timestamp = message_data.get('date')
    if date_timestamp:
        # Create timezone-aware datetime from Unix timestamp
        return datetime.fromtimestamp(date_timestamp, tz=dt_timezone.utc)
    return timezone.now()


def _parse_received_at(received_at_raw):
    """Parse ISO or fallback timestamp strings for manual batch processing."""
    if not received_at_raw:
        return timezone.now()

    try:
        from dateutil import parser as date_parser
        return date_parser.parse(received_at_raw)
    except Exception:
        try:
            return datetime.fromisoformat(received_at_raw.replace('Z', '+00:00'))
        except Exception:
            logger.warning(f"Could not parse received_at '{received_at_raw}', using now")
            return timezone.now()


def _split_if_batch(content: str, sender: str, has_image: bool, 
                    received_at: datetime) -> list[dict]:
    """
    Check if content contains multiple forwarded messages and split them.
    
    Returns:
        List of message dicts with 'sender' and 'content' keys
    """
    from core.services.parser import split_batch_message
    
    # Try to split batch
    split_messages = split_batch_message(content)
    
    if len(split_messages) > 1:
        return split_messages
    
    # Return as single message
    return [{
        'sender': sender,
        'content': content,
    }]


def _authorize_manual_request(request) -> bool:
    """Authorize manual API access using a bearer token."""
    token = getattr(settings, 'API_AUTH_TOKEN', '')
    if not token:
        logger.warning('Manual API token is not configured')
        return False

    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        provided_token = auth_header.split(' ', 1)[1].strip()
    else:
        provided_token = request.headers.get('X-API-AUTH-TOKEN', '')

    if provided_token != token:
        logger.warning('Unauthorized manual API request')
        return False

    return True


@csrf_exempt
@require_http_methods(["POST"])
def process_messages(request):
    """
    Manually trigger batch message processing.
    
    Accepts a list of messages in the request body:
    {
        "messages": [
            {
                "telegram_message_id": "123",
                "content": "Sold 3 bread 50 each to John",
                "sender": "John Doe",
                "received_at": "2026-04-15T10:30:00Z",
                "has_image": false
            }
        ]
    }
    """
    try:
        # Validate request size
        try:
            validate_request_size(request)
        except ValidationError as e:
            return error_response(e.message, e.code, e.status_code)

        if not _authorize_manual_request(request):
            return error_response(
                'Unauthorized: Missing or invalid API token',
                code='UNAUTHORIZED',
                status_code=401
            )

        try:
            body = json.loads(request.body)
        except json.JSONDecodeError as e:
            return error_response(
                'Invalid JSON in request body',
                code='INVALID_JSON',
                status_code=400,
                details=str(e)
            )
        
        messages = body.get('messages', [])
        
        # Validate batch
        is_valid, errors = validate_batch_messages(messages)
        if not is_valid:
            return error_response(
                'Invalid batch: ' + errors[0],
                code='INVALID_BATCH',
                status_code=400,
                data={'errors': errors}
            )
        
        results = []
        for msg in messages:
            received_at_raw = msg.get('received_at')
            received_at = _parse_received_at(received_at_raw)
            result = _process_single_message(
                telegram_message_id=msg.get('telegram_message_id', ''),
                content=msg.get('content', ''),
                sender=msg.get('sender', ''),
                received_at=received_at,
                has_image=msg.get('has_image', False),
            )
            results.append(result)
        
        success_count = sum(1 for r in results if r.get('status') == 'success')
        
        return success_response(
            data={
                'total': len(messages),
                'success': success_count,
                'duplicates': sum(1 for r in results if r.get('status') == 'duplicate'),
                'errors': sum(1 for r in results if r.get('status') == 'error'),
                'results': results,
            },
            message=f'Processed {len(messages)} messages'
        )
        
    except Exception as e:
        logger.error(f"Unhandled error in process_messages: {e}", exc_info=True)
        return error_response(
            'Internal server error',
            code='INTERNAL_ERROR',
            status_code=500,
            details=str(e)
        )


@csrf_exempt
@require_http_methods(["POST"])
def resend_unsynced(request):
    """
    Manually trigger resync of unsynced messages to Google Sheets.
    
    Query params:
    - limit: Maximum number of messages to resync (default: 100)
    - max_attempts: Max retry attempts (default: 5)
    """
    try:
        # Validate request size
        try:
            validate_request_size(request)
        except ValidationError as e:
            return error_response(e.message, e.code, e.status_code)

        if not _authorize_manual_request(request):
            return error_response(
                'Unauthorized: Missing or invalid API token',
                code='UNAUTHORIZED',
                status_code=401
            )

        body = json.loads(request.body) if request.body else {}
        limit = min(body.get('limit', 100), 500)  # Cap at 500 to prevent abuse
        max_attempts = min(body.get('max_attempts', settings.MAX_SYNC_ATTEMPTS), 10)
        
        from core.services.storage import bulk_resync_to_sheets
        
        result = bulk_resync_to_sheets(limit, max_attempts)
        
        return success_response(
            data=result,
            message='Resync operation complete'
        )
        
    except json.JSONDecodeError as e:
        return error_response(
            'Invalid JSON in request body',
            code='INVALID_JSON',
            status_code=400,
            details=str(e)
        )
    except Exception as e:
        logger.error(f"Unhandled error in resend_unsynced: {e}", exc_info=True)
        return error_response(
            'Internal server error',
            code='INTERNAL_ERROR',
            status_code=500,
            details=str(e)
        )
