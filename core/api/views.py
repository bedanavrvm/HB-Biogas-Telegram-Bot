"""
API Views for the biogas telegram bot.

Endpoints:
- POST /api/webhook/telegram/ - Receive Telegram webhook
- POST /api/process/messages/ - Manually trigger batch processing
- GET /api/health/ - Health check
- POST /api/resync/unsynced/ - Resync unsynced messages to Google Sheets
"""
import logging
from datetime import datetime
from django.utils import timezone
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.conf import settings
import json

logger = logging.getLogger(__name__)


@csrf_exempt
@require_http_methods(["GET"])
def health_check(request):
    """
    Health check endpoint.
    Returns system status and version.
    """
    return JsonResponse({
        'status': 'healthy',
        'service': 'Biogas Telegram Bot',
        'version': '1.0.0',
        'timestamp': timezone.now().isoformat(),
    })


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
        # Parse request body
        try:
            body = json.loads(request.body)
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON received: {request.body[:100]}")
            return JsonResponse(
                {'error': 'Invalid JSON'},
                status=400
            )
        
        # Validate webhook secret if configured
        if settings.TELEGRAM_WEBHOOK_SECRET:
            provided_secret = (
                request.headers.get('X-Telegram-Bot-Api-Secret-Token')
                or request.headers.get('X-Telegram-Webhook-Secret')
            )
            if provided_secret != settings.TELEGRAM_WEBHOOK_SECRET:
                logger.warning("Invalid webhook secret")
                return JsonResponse({'error': 'Unauthorized'}, status=401)
        
        # Handle different update types
        if 'message' in body:
            result = _process_telegram_message(body['message'])
            # Send Telegram reply
            _send_telegram_reply(body['message'], result)
            return JsonResponse(result)
        
        elif 'channel_post' in body:
            result = _process_telegram_message(body['channel_post'])
            # Send Telegram reply
            _send_telegram_reply(body['channel_post'], result)
            return JsonResponse(result)
        
        else:
            logger.warning(f"Unsupported update type: {list(body.keys())}")
            return JsonResponse(
                {'error': 'Unsupported update type'},
                status=400
            )
            
    except Exception as e:
        logger.error(f"Error processing webhook: {e}", exc_info=True)
        return JsonResponse(
            {'error': 'Internal server error'},
            status=500
        )


def _process_telegram_message(message_data: dict) -> dict:
    """
    Process a single Telegram message.
    
    Args:
        message_data: Telegram message object
        
    Returns:
        Dict with processing result
    """
    try:
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
    received_at: datetime
) -> dict:
    """
    Process and store a single message.
    
    Returns:
        Dict with processing result
    """
    from core.services.storage import process_and_store_message
    
    try:
        parsed_message = process_and_store_message(
            telegram_message_id=telegram_message_id,
            content=content,
            sender=sender,
            received_at=received_at,
            has_image=has_image,
        )
        
        if parsed_message is None:
            return {
                'status': 'duplicate',
                'message_id': telegram_message_id,
            }
        
        return {
            'status': 'success',
            'message_id': parsed_message.message_id,
            'parsed': {
                'item': parsed_message.item,
                'quantity': str(parsed_message.quantity) if parsed_message.quantity else None,
                'price': str(parsed_message.price) if parsed_message.price else None,
                'sender': parsed_message.sender,
            },
        }
        
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
    import requests
    
    chat_id = message_data.get('chat', {}).get('id')
    if not chat_id:
        return
    
    bot_token = settings.TELEGRAM_BOT_TOKEN
    if not bot_token:
        return
    
    # Determine reply message based on status
    status = result.get('status', 'unknown')
    
    if status == 'success':
        text = '✅ Message received and saved successfully'
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
        requests.post(url, data=payload, timeout=5)
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
        return datetime.fromtimestamp(date_timestamp, tz=timezone.utc)
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
        if not _authorize_manual_request(request):
            return JsonResponse({'error': 'Unauthorized'}, status=401)

        body = json.loads(request.body)
        messages = body.get('messages', [])
        
        if not messages:
            return JsonResponse(
                {'error': 'No messages provided'},
                status=400
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
        
        return JsonResponse({
            'status': 'processed',
            'total': len(messages),
            'success': success_count,
            'results': results,
        })
        
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Error in process_messages: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def resend_unsynced(request):
    """
    Manually trigger resync of unsynced messages to Google Sheets.
    
    Query params:
    - limit: Maximum number of messages to resync (default: 100)
    """
    try:
        if not _authorize_manual_request(request):
            return JsonResponse({'error': 'Unauthorized'}, status=401)

        body = json.loads(request.body) if request.body else {}
        limit = body.get('limit', 100)
        max_attempts = body.get('max_attempts', 5)
        
        from core.services.storage import bulk_resync_to_sheets
        
        result = bulk_resync_to_sheets(limit, max_attempts)
        
        return JsonResponse({
            'status': 'resync_complete',
            **result,
        })
        
    except Exception as e:
        logger.error(f"Error in resend_unsynced: {e}", exc_info=True)
        return JsonResponse({'error': str(e)}, status=500)
