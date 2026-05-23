"""
API Views for the biogas telegram bot.

Endpoints:
- POST /api/webhook/telegram/  â€” Receive Telegram webhook
- POST /api/process/messages/  â€” Manual batch processing
- POST /api/resync/unsynced/   â€” Resync unsynced messages
- GET  /api/health/            â€” Health check

KEY FIXES (v2):
- process_messages() now passes group_id (from the request body or
  settings.DEFAULT_GROUP_ID fallback) to _process_single_message().
  Previously group_id was always None, which caused an immediate error
  return from _process_single_message().
- _send_telegram_reply() no longer leaks internal group IDs or sheet IDs
  in error messages sent back to the Telegram chat.
- _process_telegram_message() logs at DEBUG for unrecognised update types
  instead of silently discarding context.
"""
import logging
from datetime import datetime, timezone as dt_timezone
from django.utils import timezone
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.conf import settings
import json
import re
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


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["GET"])
def health_check(request):
    """Returns system status and version."""
    return success_response(
        data={
            'service': 'Biogas Telegram Bot',
            'version': '1.0.0',
            'timestamp': timezone.now().isoformat(),
            'database': 'connected',
        },
        message='Service is healthy',
    )


# ---------------------------------------------------------------------------
# Telegram webhook
# ---------------------------------------------------------------------------

@require_http_methods(["GET"])
def order_approval_form(request):
    """Render the Telegram Web App form for order approval updates."""
    if not getattr(settings, 'ORDER_APPROVAL_WEBAPP_ENABLED', True):
        return render(
            request,
            'order_approval/unavailable.html',
            status=404,
        )

    return render(
        request,
            'order_approval/form.html',
        {
            'group_id': str(request.GET.get('group_id', '')).strip(),
            'form_token': str(request.GET.get('token', '')).strip(),
            'max_file_size_mb': getattr(settings, 'MEDIA_MAX_FILE_SIZE_MB', 20),
        },
    )


@csrf_exempt
@require_http_methods(["POST"])
def order_approval_webapp_submit(request):
    """Accept a Telegram Web App order approval form submission."""
    try:
        from core.services.group_config import GroupRegistry
        from core.services.order_approval import (
            is_order_approval_workflow,
            process_order_approval_form_submission,
            validate_order_approval_form_token,
            validate_telegram_webapp_init_data,
        )

        group_id = str(request.POST.get('group_id', '')).strip()
        is_valid, auth_error, auth_payload = validate_telegram_webapp_init_data(
            request.POST.get('init_data', '')
        )
        if not is_valid:
            token_valid, token_error = validate_order_approval_form_token(
                token=request.POST.get('form_token', ''),
                group_id=group_id,
            )
            if not token_valid:
                return JsonResponse(
                    {'success': False, 'message': auth_error or token_error},
                    status=403,
                )
            auth_payload = {}

        group_config = GroupRegistry.get_instance().get_group(group_id)
        if not group_config or not is_order_approval_workflow(group_config):
            return JsonResponse(
                {
                    'success': False,
                    'message': 'This Telegram group is not configured for order approvals.',
                },
                status=400,
            )

        field_names = [
            'id_number',
            'date_visited',
            'customer_name',
            'primary_phone',
            'secondary_phone',
            'county',
            'landmark',
            'visited_by',
            'hb_staff',
            'deposit_hb',
            'deposit_jbl',
            'comment',
            'imab_created',
            'customer_no',
            'credit_analysis',
        ]
        result = process_order_approval_form_submission(
            group_config=group_config,
            fields={key: request.POST.get(key, '') for key in field_names},
            uploaded_files=request.FILES.getlist('attachments'),
            sender=_sender_from_webapp_auth(auth_payload),
            received_at=timezone.now(),
        )
        return JsonResponse(result, status=200 if result.get('success') else 400)
    except Exception as exc:
        logger.error(
            f"Unhandled order approval webapp submit error: {exc}",
            exc_info=True,
        )
        return JsonResponse(
            {
                'success': False,
                'message': 'Submission failed. Please try again or use the chat format.',
            },
            status=500,
        )

@csrf_exempt
@require_http_methods(["POST"])
def telegram_webhook(request):
    """
    Receive a Telegram webhook update.

    Validates the payload, routes to the appropriate handler, and replies
    to the Telegram chat with a human-readable status message.
    """
    try:
        # 1. Request size guard
        try:
            validate_request_size(request)
        except ValidationError as exc:
            return error_response(exc.message, exc.code, exc.status_code)

        # 2. JSON parsing
        try:
            body = json.loads(request.body)
        except json.JSONDecodeError as exc:
            logger.warning(f"Invalid JSON in webhook: {request.body[:100]}")
            return error_response(
                'Invalid JSON in request body',
                code='INVALID_JSON',
                status_code=400,
                details=str(exc),
            )

        # 3. Payload structure
        try:
            validate_webhook_payload(body)
        except ValidationError as exc:
            return error_response(exc.message, exc.code, exc.status_code)

        # 4. Optional webhook secret check
        if settings.TELEGRAM_WEBHOOK_SECRET:
            provided = (
                request.headers.get('X-Telegram-Bot-Api-Secret-Token')
                or request.headers.get('X-Telegram-Webhook-Secret', '')
            )
            if provided != settings.TELEGRAM_WEBHOOK_SECRET:
                logger.warning("Invalid webhook secret")
                return error_response(
                    'Unauthorized: Invalid webhook secret',
                    code='UNAUTHORIZED',
                    status_code=401,
                )

        # 5. Route by update type
        for key in ('message', 'channel_post'):
            if key in body:
                try:
                    validate_message_fields(body[key])
                    result = _process_telegram_message(body[key])
                    _send_telegram_reply(body[key], result)
                    if result.get('status') == 'partial':
                        warnings = (
                            [result['error']] if result.get('error') else None
                        )
                        return partial_response(result, warnings=warnings)
                    return success_response(result)
                except ValidationError as exc:
                    return error_response(exc.message, exc.code, exc.status_code)

        # Silently ignore unhandled update types (edited_message, etc.)
        logger.debug(f"Ignored update type(s): {list(body.keys())}")
        return success_response({'ignored': True}, message='Update type not processed')

    except Exception as exc:
        logger.error(f"Unhandled error in webhook: {exc}", exc_info=True)
        return error_response(
            'Internal server error',
            code='INTERNAL_ERROR',
            status_code=500,
            details=str(exc),
        )


# ---------------------------------------------------------------------------
# Internal message processing
# ---------------------------------------------------------------------------

def _process_telegram_message(message_data: dict) -> dict:
    """
    Route a single Telegram message through the processing pipeline.

    Extracts group_id from chat.id, resolves the correct sheet via
    GroupRegistry, then delegates to _process_single_message().
    """
    try:
        group_id = str(message_data.get('chat', {}).get('id', ''))
        if not group_id:
            logger.error("Message has no chat.id â€” cannot route to group")
            return {'status': 'error', 'error': 'Message missing chat information'}

        telegram_message_id = str(message_data.get('message_id', ''))
        sender = _extract_sender_name(message_data)
        raw_content = _extract_message_content(message_data)
        content = _extract_tagged_message_content(message_data)
        has_image = _detect_image(message_data)
        received_at = _extract_timestamp(message_data)
        reply_to_id = str(
            message_data.get('reply_to_message', {}).get('message_id', '')
        )

        from core.services.group_config import GroupRegistry
        group_config = GroupRegistry.get_instance().get_group(group_id)
        if group_config:
            from core.services.order_approval import (
                handle_order_approval_message,
                is_order_approval_workflow,
            )
            if is_order_approval_workflow(group_config):
                if content is None and not (reply_to_id and has_image):
                    logger.debug(
                        f"Ignoring order approval message {telegram_message_id}: "
                        "bot was not tagged"
                    )
                    return {
                        'status': 'ignored',
                        'reason': 'Bot was not tagged',
                        'message_id': telegram_message_id,
                    }
                return handle_order_approval_message(
                    group_config=group_config,
                    message_data=message_data,
                    content=content or '',
                    sender=sender,
                    received_at=received_at,
                )

        update_content = content if content is not None else raw_content
        if reply_to_id and _looks_like_status_update(update_content):
            from core.services.case_updates import handle_case_status_reply
            update_result = handle_case_status_reply(
                group_id=group_id,
                reply_to_telegram_message_id=reply_to_id,
                update_telegram_message_id=telegram_message_id,
                sender=sender,
                content=update_content,
                reply_to_text=_extract_message_content(
                    message_data.get('reply_to_message', {})
                ),
            )
            if update_result:
                return update_result

        if content is None:
            logger.debug(f"Ignoring message {telegram_message_id}: bot was not tagged")
            return {
                'status': 'ignored',
                'reason': 'Bot was not tagged',
                'message_id': telegram_message_id,
            }

        if not content:
            logger.warning(f"No content in message {telegram_message_id}")
            return {
                'status': 'skipped',
                'reason': 'No message content after bot mention',
                'message_id': telegram_message_id,
            }

        if _looks_like_status_update(content):
            return {
                'status': 'command',
                'reply_text': (
                    "To update a case, reply to the original case message with "
                    "Status: ... or use /update MSG_ID Status: ..."
                ),
            }

        from core.services.commands import handle_bot_command
        command_result = handle_bot_command(
            content,
            group_id,
            sender=sender,
            telegram_message_id=telegram_message_id,
        )
        if command_result:
            return command_result

        messages = _split_if_batch(content, sender, has_image, received_at)

        if len(messages) > 1:
            results = []
            for i, msg in enumerate(messages):
                result = _process_single_message(
                    telegram_message_id=f"{telegram_message_id}_{i}",
                    content=msg['content'],
                    sender=msg['sender'],
                    has_image=has_image,
                    received_at=received_at,
                    group_id=group_id,
                    source_telegram_message_id=telegram_message_id,
                    batch_index=i,
                )
                results.append(result)

            return {
                'status': 'batch_processed',
                'total': len(messages),
                'success': sum(1 for r in results if r.get('status') == 'success'),
                'duplicates': sum(1 for r in results if r.get('status') == 'duplicate'),
                'results': results,
            }

        return _process_single_message(
            telegram_message_id=telegram_message_id,
            content=content,
            sender=sender,
            has_image=has_image,
            received_at=received_at,
            group_id=group_id,
            source_telegram_message_id=telegram_message_id,
        )

    except Exception as exc:
        logger.error(f"Error processing Telegram message: {exc}", exc_info=True)
        return {'status': 'error', 'error': 'Message could not be processed'}


def _process_single_message(
    telegram_message_id: str,
    content: str,
    sender: str,
    has_image: bool,
    received_at: datetime,
    group_id: str = None,
    source_telegram_message_id: str = '',
    batch_index: int = None,
) -> dict:
    """
    Run one message through dedup â†’ parse â†’ store â†’ sheet sync.

    Resolves the sheet_id from GroupRegistry using group_id, then passes
    both down to process_and_store_message so the correct Google Sheet
    receives the data.
    """
    from core.services.storage import process_and_store_message
    from core.services.group_config import GroupRegistry, get_sheet_id_for_group

    try:
        if not group_id:
            return {'status': 'error', 'error': 'No group_id provided'}

        # Resolve sheet_id via GroupRegistry
        registry = GroupRegistry.get_instance()
        group_config = registry.get_group(group_id)
        if not group_config:
            logger.error(f"No config found for group {group_id}")
            # Return a generic error â€” don't expose the group_id to the caller
            return {
                'status': 'error',
                'error': 'This group is not configured to receive messages.',
            }

        sheet_id = group_config.sheet_id
        sheet_name = group_config.sheet_name
        sheet_schema = group_config.sheet_schema_config

        parsed_message = process_and_store_message(
            telegram_message_id=telegram_message_id,
            content=content,
            sender=sender,
            received_at=received_at,
            has_image=has_image,
            group_id=group_id,
            sheet_name=sheet_name,
            source_telegram_message_id=source_telegram_message_id,
            batch_index=batch_index,
            sheet_id=sheet_id,       # â† forwarded to sheets service
            sheet_schema=sheet_schema,
        )

        if parsed_message is None:
            return {'status': 'duplicate', 'message_id': telegram_message_id}

        if getattr(parsed_message, 'synced_to_sheets', False) is True:
            try:
                from core.services.sheet_sync import sync_group_from_sheet
                sync_group_from_sheet(group_id=group_id, delete_missing=True)
            except Exception as exc:
                logger.warning(
                    f"Post-append sheet mirror failed for group {group_id}: {exc}"
                )

        # Collect captured fields for the Telegram reply
        captured_fields = {}
        field_map = {
            'sender': 'Sender',
            'customer_name': 'Customer Name',
            'customer_phone': 'Phone Number',
            'customer_id': 'Customer ID',
            'complaint_description': 'Complaint Description',
            'item': 'Item',
            'quantity': 'Quantity',
            'price': 'Price',
            'gps_link': 'Location',
        }
        for attr, label in field_map.items():
            val = getattr(parsed_message, attr, None)
            if val:
                captured_fields[label] = (
                    str(val)[:140] if attr == 'complaint_description' else str(val)
                )

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
                result['warning'] = 'Message processed with partial confidence.'

        return result

    except Exception as exc:
        logger.error(f"Error in _process_single_message: {exc}", exc_info=True)
        return {'status': 'error', 'error': 'Message could not be processed'}


# ---------------------------------------------------------------------------
# Telegram reply helper
# ---------------------------------------------------------------------------

def _send_telegram_reply(message_data: dict, result: dict) -> None:
    """
    Send a reply to the Telegram chat.

    SECURITY: Error messages must not expose internal identifiers such as
    group IDs, sheet IDs, or stack traces.
    """
    chat_id = message_data.get('chat', {}).get('id')
    if not chat_id:
        return

    bot_token = settings.TELEGRAM_BOT_TOKEN
    if not bot_token:
        return

    status = result.get('status', 'unknown')
    if status == 'ignored':
        return
    if status == 'command':
        text = result.get('reply_text', '')
        if not text:
            return
        _post_telegram_reply(
            chat_id,
            message_data,
            text,
            reply_markup=result.get('reply_markup'),
        )
        return

    captured_fields = result.get('captured_fields', {})

    fields_summary = ''
    if captured_fields:
        captured_lines = [
            f"{label}: {value}"
            for label, value in captured_fields.items()
            if str(value).strip()
        ]
        if captured_lines:
            fields_summary = "\nCaptured:\n" + "\n".join(captured_lines)

    case_id_line = ''
    if result.get('message_id'):
        case_id_line = f"\nCase ID: {result['message_id']}"

    if status == 'success':
        text = (
            f'OK. Message received and saved successfully'
            f'{case_id_line}{fields_summary}'
        )
    elif status == 'partial':
        if result.get('error') and 'sheet' in result['error'].lower():
            text = (
                f'Warning: Message saved to database but could not sync to the '
                f'register at this time. It will be retried automatically.'
                f'{case_id_line}{fields_summary}'
            )
        else:
            text = (
                f'Warning: Message partially processed (some fields were not '
                f'recognised){case_id_line}{fields_summary}'
            )
    elif status == 'duplicate':
        text = 'Warning: This message has already been processed.'
    elif status == 'skipped':
        text = 'Warning: Message skipped - no text content found.'
    elif status == 'batch_processed':
        success = result.get('success', 0)
        total = result.get('total', 0)
        text = f'OK. Batch processed: {success}/{total} messages saved.'
    elif status == 'error':
        text = (
            'Error: This message could not be processed. '
            'Please check the format and try again.'
        )
    else:
        text = f'Message received (status: {status})'

    _post_telegram_reply(chat_id, message_data, text)


def _post_telegram_reply(
    chat_id,
    message_data: dict,
    text: str,
    reply_markup: dict = None,
) -> None:
    try:
        bot_token = settings.TELEGRAM_BOT_TOKEN
        url = f'https://api.telegram.org/bot{bot_token}/sendMessage'
        data = {
            'chat_id': chat_id,
            'text': text[:4000],
            'reply_to_message_id': message_data.get('message_id'),
        }
        if reply_markup:
            data['reply_markup'] = json.dumps(reply_markup)
        requests.post(
            url,
            data=data,
            timeout=settings.API_REQUEST_TIMEOUT,
        )
    except requests.Timeout:
        logger.warning(f"Timeout sending Telegram reply to chat {chat_id}")
    except Exception as exc:
        logger.error(f"Failed to send Telegram reply: {exc}")


# ---------------------------------------------------------------------------
# Manual batch processing endpoint
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["POST"])
def process_messages(request):
    """
    Manually trigger processing for a list of messages.

    Each message object may include a 'group_id' field.  If omitted,
    settings.DEFAULT_GROUP_ID is used as a fallback so the endpoint
    remains usable in single-group deployments.

    Request body:
    {
        "messages": [
            {
                "telegram_message_id": "123",
                "content": "Sold 3 bread 50 each to John",
                "sender": "John Doe",
                "received_at": "2026-04-15T10:30:00Z",
                "has_image": false,
                "group_id": "-1001234567890"   â† optional
            }
        ]
    }
    """
    try:
        try:
            validate_request_size(request)
        except ValidationError as exc:
            return error_response(exc.message, exc.code, exc.status_code)

        if not _authorize_manual_request(request):
            return error_response(
                'Unauthorized: Missing or invalid API token',
                code='UNAUTHORIZED',
                status_code=401,
            )

        try:
            body = json.loads(request.body)
        except json.JSONDecodeError as exc:
            return error_response(
                'Invalid JSON in request body',
                code='INVALID_JSON',
                status_code=400,
                details=str(exc),
            )

        messages = body.get('messages', [])

        is_valid, errors = validate_batch_messages(messages)
        if not is_valid:
            return error_response(
                'Invalid batch: ' + errors[0],
                code='INVALID_BATCH',
                status_code=400,
                data={'errors': errors},
            )

        default_group_id = getattr(settings, 'DEFAULT_GROUP_ID', 'default')
        results = []

        for msg in messages:
            received_at = _parse_received_at(msg.get('received_at'))

            # â”€â”€ KEY FIX: pass group_id from the request (or fallback) â”€â”€
            group_id = str(msg.get('group_id', '') or default_group_id).strip()

            result = _process_single_message(
                telegram_message_id=msg.get('telegram_message_id', ''),
                content=msg.get('content', ''),
                sender=msg.get('sender', ''),
                received_at=received_at,
                has_image=msg.get('has_image', False),
                group_id=group_id,
            )
            results.append(result)

        return success_response(
            data={
                'total': len(messages),
                'success': sum(1 for r in results if r.get('status') == 'success'),
                'duplicates': sum(1 for r in results if r.get('status') == 'duplicate'),
                'errors': sum(1 for r in results if r.get('status') == 'error'),
                'results': results,
            },
            message=f'Processed {len(messages)} messages',
        )

    except Exception as exc:
        logger.error(f"Unhandled error in process_messages: {exc}", exc_info=True)
        return error_response(
            'Internal server error',
            code='INTERNAL_ERROR',
            status_code=500,
            details=str(exc),
        )


# ---------------------------------------------------------------------------
# Resync endpoint
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["POST"])
def resend_unsynced(request):
    """
    Trigger a resync of unsynced messages to Google Sheets.

    Body (optional JSON):
    { "limit": 100, "max_attempts": 5 }
    """
    try:
        try:
            validate_request_size(request)
        except ValidationError as exc:
            return error_response(exc.message, exc.code, exc.status_code)

        if not _authorize_manual_request(request):
            return error_response(
                'Unauthorized: Missing or invalid API token',
                code='UNAUTHORIZED',
                status_code=401,
            )

        body = json.loads(request.body) if request.body else {}
        limit = min(body.get('limit', 100), 500)
        max_attempts = min(
            body.get('max_attempts', settings.MAX_SYNC_ATTEMPTS), 10
        )

        from core.services.storage import bulk_resync_to_sheets
        result = bulk_resync_to_sheets(limit, max_attempts)

        return success_response(data=result, message='Resync operation complete')

    except json.JSONDecodeError as exc:
        return error_response(
            'Invalid JSON in request body',
            code='INVALID_JSON',
            status_code=400,
            details=str(exc),
        )
    except Exception as exc:
        logger.error(f"Unhandled error in resend_unsynced: {exc}", exc_info=True)
        return error_response(
            'Internal server error',
            code='INTERNAL_ERROR',
            status_code=500,
            details=str(exc),
        )


@csrf_exempt
@require_http_methods(["POST"])
def sync_from_sheets(request):
    """
    Mirror Google Sheets data into the backend database.

    Body (optional JSON):
    { "group_id": "-1001234567890", "delete_missing": true }

    If group_id is omitted, every configured group is synced. In legacy
    single-sheet mode this syncs the default group.
    """
    try:
        try:
            validate_request_size(request)
        except ValidationError as exc:
            return error_response(exc.message, exc.code, exc.status_code)

        if not _authorize_manual_request(request):
            return error_response(
                'Unauthorized: Missing or invalid API token',
                code='UNAUTHORIZED',
                status_code=401,
            )

        body = json.loads(request.body) if request.body else {}
        delete_missing = bool(body.get('delete_missing', True))
        group_id = str(body.get('group_id', '')).strip()

        if group_id:
            from core.services.sheet_sync import sync_group_from_sheet
            result = sync_group_from_sheet(
                group_id=group_id,
                delete_missing=delete_missing,
            )
        else:
            from core.services.sheet_sync import sync_all_configured_groups
            result = sync_all_configured_groups(delete_missing=delete_missing)

        if result.get('status') == 'success':
            return success_response(data=result, message='Sheet sync complete')
        return partial_response(
            data=result,
            warnings=result.get('errors') or ['One or more sheet syncs failed'],
            message='Sheet sync partially completed',
        )

    except json.JSONDecodeError as exc:
        return error_response(
            'Invalid JSON in request body',
            code='INVALID_JSON',
            status_code=400,
            details=str(exc),
        )
    except Exception as exc:
        logger.error(f"Unhandled error in sync_from_sheets: {exc}", exc_info=True)
        return error_response(
            'Internal server error',
            code='INTERNAL_ERROR',
            status_code=500,
            details=str(exc),
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _authorize_manual_request(request) -> bool:
    token = getattr(settings, 'API_AUTH_TOKEN', '')
    if not token:
        logger.warning('API_AUTH_TOKEN is not configured')
        return False
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        provided = auth_header.split(' ', 1)[1].strip()
    else:
        provided = request.headers.get('X-API-AUTH-TOKEN', '')
    return provided == token


def _extract_sender_name(message_data: dict) -> str:
    from_user = message_data.get('from', {})
    if from_user:
        first = from_user.get('first_name', '')
        last = from_user.get('last_name', '')
        username = from_user.get('username', '')
        if first or last:
            return f"{first} {last}".strip()
        if username:
            return username
    return message_data.get('forward_sender_name', '')


def _extract_message_content(message_data: dict) -> str:
    parts = []
    text = message_data.get('text', '')
    caption = message_data.get('caption', '')
    if text:
        parts.append(text)
    if caption:
        parts.append(caption)
    return '\n'.join(parts).strip()


def _extract_tagged_message_content(message_data: dict) -> str | None:
    """
    Return content only when the configured bot username is explicitly tagged.

    Untagged group chatter returns None so the webhook can acknowledge the
    update without parsing, saving, syncing, or replying.
    """
    content = _extract_message_content(message_data)
    bot_username = getattr(settings, 'TELEGRAM_BOT_USERNAME', '').strip().lstrip('@')

    if not bot_username:
        logger.warning('TELEGRAM_BOT_USERNAME is not configured; ignoring webhook message')
        return None

    mention_pattern = re.compile(
        rf'@{re.escape(bot_username)}\b',
        flags=re.IGNORECASE,
    )
    if not mention_pattern.search(content):
        return None

    return mention_pattern.sub('', content).strip()


def _looks_like_status_update(content: str) -> bool:
    from core.services.case_updates import looks_like_status_update
    return looks_like_status_update(content)


def _detect_image(message_data: dict) -> bool:
    for key in ('photo', 'document', 'video', 'animation',
                'sticker', 'voice', 'video_note'):
        if key in message_data:
            return True
    if message_data.get('caption') and not message_data.get('text'):
        return True
    return False


def _extract_timestamp(message_data: dict) -> datetime:
    ts = message_data.get('date')
    if ts:
        return datetime.fromtimestamp(ts, tz=dt_timezone.utc)
    return timezone.now()


def _parse_received_at(received_at_raw) -> datetime:
    if not received_at_raw:
        return timezone.now()
    try:
        from dateutil import parser as date_parser
        return date_parser.parse(received_at_raw)
    except Exception:
        try:
            return datetime.fromisoformat(
                received_at_raw.replace('Z', '+00:00')
            )
        except Exception:
            logger.warning(
                f"Could not parse received_at '{received_at_raw}', using now"
            )
            return timezone.now()


def _sender_from_webapp_auth(auth_payload: dict) -> str:
    raw_user = (auth_payload or {}).get('user', '')
    if not raw_user:
        return 'Telegram Web App'
    try:
        user = json.loads(raw_user)
    except json.JSONDecodeError:
        return 'Telegram Web App'

    first = user.get('first_name', '')
    last = user.get('last_name', '')
    username = user.get('username', '')
    if first or last:
        return f"{first} {last}".strip()
    if username:
        return username
    if user.get('id'):
        return f"telegram:{user['id']}"
    return 'Telegram Web App'


def _split_if_batch(
    content: str, sender: str, has_image: bool, received_at: datetime
) -> list:
    from core.services.parser import split_batch_message
    split = split_batch_message(content)
    if len(split) > 1:
        return split
    return [{'sender': sender, 'content': content}]
