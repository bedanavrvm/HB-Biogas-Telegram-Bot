"""
API Views for the biogas telegram bot.

Endpoints:
- POST /api/webhook/telegram/  — Receive Telegram webhook
- POST /api/process/messages/  — Manual batch processing
- POST /api/resync/unsynced/   — Resync unsynced messages
- GET  /api/health/            — Health check

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
import io
from datetime import datetime, timezone as dt_timezone
from django.utils import timezone
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.conf import settings
import hmac
import json
import re
import requests
import zipfile

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
            'service': getattr(settings, 'APP_DISPLAY_NAME', 'Telegram Workflow Bot'),
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

    from core.services.order_approval import order_approval_branch_choices

    return render(
        request,
        'order_approval/form.html',
        {
            'group_id': str(request.GET.get('group_id', '')).strip(),
            'form_token': str(request.GET.get('token', '')).strip(),
            'max_file_size_mb': getattr(settings, 'MEDIA_MAX_FILE_SIZE_MB', 20),
            'max_files_per_slot': getattr(settings, 'ORDER_APPROVAL_MAX_FILES_PER_SLOT', 10),
            'max_total_upload_mb': getattr(settings, 'ORDER_APPROVAL_MAX_TOTAL_UPLOAD_MB', 30),
            'image_previews_enabled': getattr(
                settings,
                'ORDER_APPROVAL_IMAGE_PREVIEWS_ENABLED',
                False,
            ),
            'image_preview_limit': getattr(settings, 'ORDER_APPROVAL_IMAGE_PREVIEW_LIMIT', 3),
            'branch_choices': order_approval_branch_choices(),
        },
    )


@csrf_exempt
@require_http_methods(["POST"])
def order_approval_webapp_submit(request):
    """Accept a Telegram Web App order approval form submission."""
    try:
        from core.services.order_approval import (
            ORDER_APPROVAL_WEBAPP_FIELDS,
            collect_order_approval_uploaded_files,
            process_order_approval_form_submission,
            validate_order_approval_uploaded_files,
        )

        group_id, group_config, auth_payload, error_response_obj = (
            _order_approval_webapp_context(request.POST)
        )
        if error_response_obj:
            return error_response_obj

        upload_errors = validate_order_approval_uploaded_files(request.FILES)
        if upload_errors:
            result = {
                'success': False,
                'status': 'failed',
                'message': " ".join(upload_errors),
                'errors': upload_errors,
                'files_stored': 0,
                'warnings': [],
            }
            _send_order_approval_webapp_chat_reply(
                group_id=group_id,
                result=result,
            )
            return JsonResponse(result, status=400)

        result = process_order_approval_form_submission(
            group_config=group_config,
            fields={
                key: request.POST.get(key, '')
                for key in ORDER_APPROVAL_WEBAPP_FIELDS
            },
            uploaded_files=collect_order_approval_uploaded_files(request.FILES),
            sender=_sender_from_webapp_auth(auth_payload),
            received_at=timezone.now(),
            include_blank_fields=request.POST.get('write_blank_fields') == '1',
            edit_context={
                'id_number': request.POST.get('edit_id_number', ''),
                'sheet': request.POST.get('edit_sheet', ''),
                'row': request.POST.get('edit_row', ''),
                'fingerprint': request.POST.get('edit_fingerprint', ''),
            },
        )
        _send_order_approval_webapp_chat_reply(
            group_id=group_id,
            result=result,
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
def order_approval_webapp_lookup(request):
    """Load an existing order approval row into the Web App edit form."""
    try:
        from core.services.order_approval import lookup_order_approval_form_record

        group_id, group_config, auth_payload, error_response_obj = (
            _order_approval_webapp_context(request.POST)
        )
        del group_id, auth_payload
        if error_response_obj:
            return error_response_obj

        result = lookup_order_approval_form_record(
            group_config=group_config,
            id_number=request.POST.get('id_number', ''),
        )
        return JsonResponse(result, status=200 if result.get('success') else 400)
    except Exception as exc:
        logger.error(
            f"Unhandled order approval webapp lookup error: {exc}",
            exc_info=True,
        )
        return JsonResponse(
            {
                'success': False,
                'message': 'Lookup failed. Please check the ID and try again.',
            },
            status=500,
        )


@csrf_exempt
@require_http_methods(["POST"])
def order_approval_webapp_suggest(request):
    """Return candidate order rows while staff type an ID prefix."""
    try:
        from core.services.order_approval import suggest_order_approval_form_records

        group_id, group_config, auth_payload, error_response_obj = (
            _order_approval_webapp_context(request.POST)
        )
        del group_id, auth_payload
        if error_response_obj:
            return error_response_obj

        result = suggest_order_approval_form_records(
            group_config=group_config,
            id_prefix=request.POST.get('id_prefix', ''),
        )
        return JsonResponse(result, status=200 if result.get('success') else 400)
    except Exception as exc:
        logger.error(
            f"Unhandled order approval webapp suggest error: {exc}",
            exc_info=True,
        )
        return JsonResponse(
            {
                'success': False,
                'message': 'ID search failed. Keep typing or use Load existing.',
                'suggestions': [],
            },
            status=500,
        )


def _order_approval_webapp_context(post_data):
    from core.services.group_config import GroupRegistry
    from core.services.order_approval import (
        is_order_approval_workflow,
        validate_order_approval_form_token,
        validate_telegram_webapp_init_data,
    )

    group_id = str(post_data.get('group_id', '')).strip()
    is_valid, auth_error, auth_payload = validate_telegram_webapp_init_data(
        post_data.get('init_data', '')
    )
    if not is_valid:
        token_valid, token_error = validate_order_approval_form_token(
            token=post_data.get('form_token', ''),
            group_id=group_id,
        )
        if not token_valid:
            return (
                group_id,
                None,
                {},
                JsonResponse(
                    {'success': False, 'message': auth_error or token_error},
                    status=403,
                ),
            )
        auth_payload = {}

    group_config = GroupRegistry.get_instance().get_group(group_id)
    if not group_config or not is_order_approval_workflow(group_config):
        return (
            group_id,
            None,
            auth_payload,
            JsonResponse(
                {
                    'success': False,
                    'message': 'This Telegram group is not configured for order approvals.',
                },
                status=400,
            ),
        )

    return group_id, group_config, auth_payload, None


def _send_order_approval_webapp_chat_reply(group_id: str, result: dict) -> None:
    if not group_id:
        return

    status = result.get('status', 'failed')
    id_number = result.get('id_number', '')
    if result.get('success'):
        created = status == 'created'
        lines = [
            "ENTRY CREATED" if created else "ENTRY UPDATED",
            "",
        ]
        order_record_id = result.get('order_record_id', '')
        if order_record_id:
            lines.append(f"Order record ID: {order_record_id}")
        lines.append(f"Customer ID: {id_number}")
        customer_name = result.get('customer_name', '')
        if customer_name:
            lines.append(f"Customer: {customer_name}")
        lines.append(f"Files stored: {result.get('files_stored', 0)}")
        from core.services.order_approval import (
            field_change_lines,
            visible_field_changes,
        )

        changes = visible_field_changes(result.get('field_changes') or [])
        lines.extend(["", "Fields saved" if created else "Updated fields"])
        if changes:
            lines.extend(field_change_lines(changes))
        else:
            lines.append("- No field values changed")
    else:
        errors = result.get('errors') or [result.get('message') or 'Please check the form and try again.']
        lines = [
            result.get('title') or "ENTRY NOT SAVED",
            "",
            f"Customer ID: {id_number or 'not provided'}",
            "",
            "Fix",
        ]
        lines.extend(f"- {error}" for error in errors if str(error).strip())

    warnings = result.get('warnings') or []
    if warnings:
        lines.extend(["", "Warnings"])
        lines.extend(f"- {warning}" for warning in warnings[:3])

    _post_telegram_reply(
        chat_id=group_id,
        message_data={},
        text="\n".join(lines),
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

        # 4. Webhook secret check. It is optional only for local/test usage.
        webhook_secret = getattr(settings, 'TELEGRAM_WEBHOOK_SECRET', '')
        if not webhook_secret and not getattr(settings, 'DEBUG', False):
            logger.error("TELEGRAM_WEBHOOK_SECRET is required when DEBUG=False")
            return error_response(
                'Telegram webhook is not configured.',
                code='WEBHOOK_SECRET_REQUIRED',
                status_code=503,
            )
        if webhook_secret:
            provided = (
                request.headers.get('X-Telegram-Bot-Api-Secret-Token')
                or request.headers.get('X-Telegram-Webhook-Secret', '')
            )
            if not hmac.compare_digest(str(provided), str(webhook_secret)):
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
                        warnings = result.get('warnings') or (
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
            logger.error("Message has no chat.id — cannot route to group")
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
            from core.services.jawabu import is_jawabu_workflow
            from core.services.order_approval import (
                handle_order_approval_message,
                is_order_approval_workflow,
            )
            if is_jawabu_workflow(group_config):
                if content is None:
                    logger.debug(
                        f"Ignoring Jawabu message {telegram_message_id}: "
                        "bot was not tagged"
                    )
                    return {
                        'status': 'ignored',
                        'reason': 'Bot was not tagged',
                        'message_id': telegram_message_id,
                    }
                if _looks_like_batch_command(content):
                    return _process_jawabu_batch_command(
                        group_config=group_config,
                        message_data=message_data,
                        command_content=content,
                        sender=sender,
                        telegram_message_id=telegram_message_id,
                    )
                from core.services.commands import handle_bot_command
                command_result = handle_bot_command(
                    content,
                    group_id,
                    sender=sender,
                    telegram_message_id=telegram_message_id,
                )
                if command_result:
                    return command_result
                return {
                    'status': 'command',
                    'reply_text': (
                        "This group is configured for Jawabu HomeBiogas imports.\n"
                        "Send @bot /batch with a WhatsApp .txt or .zip export attached."
                    ),
                }
            if is_order_approval_workflow(group_config):
                if content is not None and _looks_like_fca_batch_command(content):
                    return _process_fca_batch_command(
                        group_config=group_config,
                        message_data=message_data,
                        sender=sender,
                        telegram_message_id=telegram_message_id,
                    )
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
            if content is not None and _looks_like_order_approval_content(content):
                workflow_type = (group_config.workflow or {}).get('type') or 'not set'
                logger.warning(
                    "Order approval-shaped message received in group %s, "
                    "but workflow.type is %r",
                    group_id,
                    workflow_type,
                )
                return {
                    'status': 'command',
                    'reply_text': (
                        "This group is not configured for Order Approval updates.\n"
                        f"Current workflow: {workflow_type}\n"
                        "Ask an admin to open this group in Django Admin and set "
                        "Workflow preset to Order Approval, then save."
                    ),
                }

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
        if _looks_like_batch_command(content):
            return _process_whatsapp_batch_command(
                message_data=message_data,
                command_content=content,
                sender=sender,
                received_at=received_at,
                group_id=group_id,
                telegram_message_id=telegram_message_id,
            )

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
                'rejected': sum(1 for r in results if r.get('status') == 'rejected'),
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


def _looks_like_batch_command(content: str) -> bool:
    return bool(re.match(r'^/batch(?:@\w+)?(?:\s|$)', str(content or '').strip(), re.IGNORECASE))


def _looks_like_fca_batch_command(content: str) -> bool:
    return bool(re.match(r'^/batchfca(?:@\w+)?(?:\s|$)', str(content or '').strip(), re.IGNORECASE))


def _process_whatsapp_batch_command(
    message_data: dict,
    command_content: str,
    sender: str,
    received_at: datetime,
    group_id: str,
    telegram_message_id: str,
) -> dict:
    payload = _batch_command_payload(command_content)
    if message_data.get('document') and not _looks_like_whatsapp_export_payload(payload):
        payload, document_error = _download_telegram_text_document(message_data)
        if document_error:
            return {
                'status': 'command',
                'reply_text': document_error,
            }
    elif not payload:
        payload, document_error = _download_telegram_text_document(message_data)
        if document_error:
            return {
                'status': 'command',
                'reply_text': document_error,
            }

    if not payload:
        return {
            'status': 'command',
            'reply_text': (
                "Send a WhatsApp export as a .txt file with:\n"
                "@bot /batch\n\n"
                "Or paste the export text after /batch.\n"
                "Only complete complaint entries are saved."
            ),
        }

    from core.services.parser import (
        MessageIntent,
        analyze_whatsapp_export,
        detect_message_intent,
    )

    analysis = analyze_whatsapp_export(payload)
    entries = analysis.get('entries') or []
    if not entries:
        return {
            'status': 'command',
            'reply_text': (
                "No WhatsApp export messages were found.\n"
                "Expected lines like:\n"
                "23/05/2026, 12:46 - Staff Name: CUSTOMER COMPLAIN..."
            ),
        }

    configured_max = int(getattr(settings, 'WHATSAPP_BATCH_MAX_MESSAGES', 0) or 0)
    max_entries = configured_max if configured_max > 0 else len(entries)
    truncated = configured_max > 0 and len(entries) > max_entries
    entries_to_process = entries[:max_entries] if truncated else entries
    sync_before = _sync_case_sheet_for_batch(group_id, delete_missing=True)
    results = []
    skipped_non_complaint = 0
    processed_entries = 0

    for index, entry in enumerate(entries_to_process):
        content = entry.get('content', '')
        if detect_message_intent(content) != MessageIntent.COMPLAINT:
            skipped_non_complaint += 1
            continue

        processed_entries += 1
        result = _process_single_message(
            telegram_message_id=f"{telegram_message_id}_wa_{index}",
            content=content,
            sender=entry.get('sender') or sender,
            has_image=False,
            received_at=entry.get('received_at') or received_at,
            group_id=group_id,
            source_telegram_message_id=telegram_message_id,
            batch_index=index,
            source='whatsapp_export',
            sync_after_success=False,
            defer_sheet_sync=True,
        )
        results.append(result)

    saved_count = sum(1 for r in results if r.get('status') in {'success', 'partial'})
    batch_sheet_append = _batch_append_case_results(
        results,
        group_id=group_id,
    ) if saved_count else None
    sync_after = (
        _sync_case_sheet_for_batch(group_id, delete_missing=False)
        if saved_count else None
    )

    return {
        'status': 'batch_processed',
        'source': 'whatsapp_export',
        'format': analysis.get('format', 'unknown'),
        'total': processed_entries,
        'export_messages': len(entries),
        'skipped_non_complaint': skipped_non_complaint,
        'system_lines': analysis.get('system_lines', 0),
        'orphan_lines': analysis.get('orphan_lines', 0),
        'truncated': truncated,
        'max_entries': max_entries,
        'success': sum(1 for r in results if r.get('status') == 'success'),
        'partial': sum(1 for r in results if r.get('status') == 'partial'),
        'duplicates': sum(1 for r in results if r.get('status') == 'duplicate'),
        'rejected': sum(1 for r in results if r.get('status') == 'rejected'),
        'errors': sum(1 for r in results if r.get('status') == 'error'),
        'sheet_sync_before': sync_before,
        'sheet_sync_after': sync_after,
        'batch_sheet_append': batch_sheet_append,
        'results': results,
    }


def _batch_append_case_results(results: list[dict], group_id: str) -> dict:
    """Append successfully stored case batch rows to Sheets in one request."""
    parsed_ids = [
        item.get('parsed_message_id')
        for item in results
        if item.get('status') in {'success', 'partial'} and item.get('parsed_message_id')
    ]
    if not parsed_ids:
        return {'status': 'skipped', 'row_count': 0, 'errors': []}

    try:
        from core.models import ParsedMessage
        from core.services.group_config import GroupRegistry
        from core.services.sheets import batch_append_messages

        group_config = GroupRegistry.get_instance().get_group(group_id)
        if not group_config:
            raise RuntimeError('Group is not configured for sheet sync.')

        parsed_messages = list(
            ParsedMessage.objects.filter(pk__in=parsed_ids).order_by(
                'processed_message__raw_message__batch_index',
                'created_at',
            )
        )
        result = batch_append_messages(
            parsed_messages,
            sheet_id=group_config.sheet_id,
            sheet_name=group_config.sheet_name,
            sheet_schema=group_config.sheet_schema_config,
        )
        failure_details = result.get('failure_details') or {}
        failed_ids = set(failure_details.keys())
        for item in results:
            if item.get('message_id') in failed_ids:
                item['status'] = 'partial'
                item['error'] = failure_details[item['message_id']]
        return {
            'status': 'success' if not failed_ids else 'partial',
            'row_count': len(parsed_messages),
            'synced_count': len(result.get('synced_message_ids') or []),
            'failed_count': len(failed_ids),
            'errors': list(failure_details.values())[:3],
        }
    except Exception as exc:
        logger.warning(
            'Case batch sheet append failed for group %s: %s',
            group_id,
            exc,
            exc_info=True,
        )
        try:
            from django.db.models import F
            from core.models import ParsedMessage
            ParsedMessage.objects.filter(pk__in=parsed_ids).update(
                sync_attempts=F('sync_attempts') + 1,
                last_sync_error=str(exc),
            )
        except Exception:
            logger.debug('Could not mark case batch sheet append failure on parsed rows.', exc_info=True)
        for item in results:
            if item.get('status') == 'success' and item.get('parsed_message_id'):
                item['status'] = 'partial'
                item['error'] = str(exc)
        return {
            'status': 'error',
            'row_count': len(parsed_ids),
            'synced_count': 0,
            'failed_count': len(parsed_ids),
            'errors': [str(exc)],
        }


def _sync_case_sheet_for_batch(group_id: str, delete_missing: bool) -> dict:
    """Best-effort case sheet mirror used before/after WhatsApp batch imports."""
    try:
        from core.services.sheet_sync import sync_group_from_sheet
        result = sync_group_from_sheet(
            group_id=group_id,
            delete_missing=delete_missing,
        )
        return {
            'status': result.get('status', 'unknown'),
            'row_count': result.get('row_count', 0),
            'created_count': result.get('created_count', 0),
            'updated_count': result.get('updated_count', 0),
            'deleted_count': result.get('deleted_count', 0),
            'skipped_count': result.get('skipped_count', 0),
            'backend_count': result.get('backend_count', 0),
            'errors': (result.get('errors') or [])[:3],
        }
    except Exception as exc:
        logger.warning(
            "Case sheet batch mirror failed for group %s: %s",
            group_id,
            exc,
            exc_info=True,
        )
        return {
            'status': 'error',
            'row_count': 0,
            'created_count': 0,
            'updated_count': 0,
            'deleted_count': 0,
            'skipped_count': 0,
            'backend_count': 0,
            'errors': [str(exc)],
        }


def _process_jawabu_batch_command(
    group_config,
    message_data: dict,
    command_content: str,
    sender: str,
    telegram_message_id: str,
) -> dict:
    payload = _batch_command_payload(command_content)
    if message_data.get('document') and not _looks_like_whatsapp_export_payload(payload):
        payload, document_error = _download_telegram_text_document(message_data)
        if document_error:
            return {'status': 'command', 'reply_text': document_error}
    elif not payload:
        payload, document_error = _download_telegram_text_document(message_data)
        if document_error:
            return {'status': 'command', 'reply_text': document_error}

    if not payload:
        return {
            'status': 'command',
            'reply_text': (
                "Send the Jawabu WhatsApp .txt or .zip export with:\n"
                "@bot /batch\n\n"
                "Records need Customer Name and either National ID or primary phone. Duplicates are "
                "flagged for manual review."
            ),
        }

    from core.services.jawabu import process_jawabu_batch_export

    return process_jawabu_batch_export(
        group_config=group_config,
        export_text=payload,
        telegram_message_id=telegram_message_id,
        sender=sender,
    )


def _process_fca_batch_command(
    group_config,
    message_data: dict,
    sender: str,
    telegram_message_id: str,
) -> dict:
    files, document_error = _download_telegram_fca_documents(message_data)
    if document_error:
        return {'status': 'command', 'reply_text': document_error}
    if not files:
        return {
            'status': 'command',
            'reply_text': (
                "Attach an FCA .xlsx workbook or a .zip containing FCA workbooks and send:\n"
                "@bot /batchfca\n\n"
                "The target sheet must include FCA VISIT DATE, FCA COMMENT, FCA DECISION, "
                "and FCA IMPORT STATUS columns."
            ),
        }

    from core.services.fca import process_fca_batch_files

    return process_fca_batch_files(
        group_config=group_config,
        files=files,
        telegram_message_id=telegram_message_id,
        sender=sender,
    )


def _batch_command_payload(content: str) -> str:
    text = str(content or '').strip()
    return re.sub(
        r'^/batch(?:@\w+)?\s*',
        '',
        text,
        count=1,
        flags=re.IGNORECASE,
    ).strip()


def _looks_like_whatsapp_export_payload(content: str) -> bool:
    if not content:
        return False
    return bool(
        re.search(
            r'(?:^|\n)\[?\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}'
            r'[\s,]+\d{1,2}:\d{2}(?::\d{2})?\]?\s*'
            r'(?:[-\u2013\u2014]\s*)?[^:\n]{1,80}:\s',
            content,
        )
    )


def _download_telegram_fca_documents(message_data: dict) -> tuple[list[tuple[str, bytes]], str]:
    document = message_data.get('document') or {}
    if not document:
        return [], ''

    filename = str(document.get('file_name') or '').strip()
    mime_type = str(document.get('mime_type') or '').lower()
    lower_filename = filename.lower()
    is_excel = lower_filename.endswith('.xlsx') or mime_type in {
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        'application/octet-stream',
        '',
    }
    is_zip = lower_filename.endswith('.zip') or mime_type in {
        'application/zip',
        'application/x-zip-compressed',
    }
    if not (is_excel or is_zip):
        return [], (
            "The /batchfca command only supports .xlsx files or .zip files containing .xlsx files.\n"
            "Attach the FCA workbook and send @bot /batchfca."
        )

    max_mb = max(1, int(getattr(settings, 'FCA_BATCH_MAX_FILE_SIZE_MB', 10)))
    file_size = int(document.get('file_size') or 0)
    if file_size and file_size > max_mb * 1024 * 1024:
        return [], f"FCA attachment is too large. Maximum size is {max_mb} MB."

    bot_token = settings.TELEGRAM_BOT_TOKEN
    file_id = document.get('file_id')
    if not bot_token or not file_id:
        return [], "Could not download the FCA workbook from Telegram."

    try:
        file_meta = requests.get(
            f'https://api.telegram.org/bot{bot_token}/getFile',
            params={'file_id': file_id},
            timeout=settings.API_REQUEST_TIMEOUT,
        )
        file_meta.raise_for_status()
        file_path = file_meta.json().get('result', {}).get('file_path', '')
        if not file_path:
            return [], "Telegram did not return a downloadable file path."

        file_response = requests.get(
            f'https://api.telegram.org/file/bot{bot_token}/{file_path}',
            timeout=settings.API_REQUEST_TIMEOUT,
        )
        file_response.raise_for_status()
        raw = file_response.content
        if len(raw) > max_mb * 1024 * 1024:
            return [], f"FCA attachment is too large. Maximum size is {max_mb} MB."
        return _extract_fca_workbook_files(raw, filename, max_mb), ''
    except requests.Timeout:
        logger.warning("Timed out downloading Telegram FCA workbook")
        return [], "Timed out downloading the FCA workbook. Please resend it."
    except ValueError as exc:
        return [], str(exc)
    except Exception as exc:
        logger.error(f"Failed to download Telegram FCA workbook: {exc}", exc_info=True)
        return [], "Could not download the FCA workbook. Please resend it."


def _extract_fca_workbook_files(raw: bytes, filename: str, max_mb: int) -> list[tuple[str, bytes]]:
    lower_filename = str(filename or '').lower()
    if lower_filename.endswith('.xlsx'):
        return [(filename or 'fca.xlsx', raw)]
    if not lower_filename.endswith('.zip'):
        raise ValueError("FCA attachment must be an .xlsx workbook or .zip file.")

    max_bytes = max(1, int(max_mb)) * 1024 * 1024
    workbooks = []
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        for info in archive.infolist():
            if info.is_dir() or not info.filename.lower().endswith('.xlsx'):
                continue
            if info.filename.startswith('__MACOSX/'):
                continue
            if info.file_size > max_bytes:
                raise ValueError(f"FCA workbook {info.filename} is larger than {max_mb} MB.")
            workbooks.append((info.filename, archive.read(info)))
    if not workbooks:
        raise ValueError("The FCA zip did not contain any .xlsx workbook files.")
    return workbooks


def _download_telegram_text_document(message_data: dict) -> tuple[str, str]:
    document = message_data.get('document') or {}
    if not document:
        return '', ''

    filename = str(document.get('file_name') or '').strip()
    mime_type = str(document.get('mime_type') or '').lower()
    lower_filename = filename.lower()
    is_zip_export = (
        lower_filename.endswith('.zip')
        or mime_type in {'application/zip', 'application/x-zip-compressed'}
    )
    is_text_export = (
        lower_filename.endswith('.txt')
        or mime_type.startswith('text/')
        or mime_type in {'application/octet-stream', ''}
    )
    if not (is_text_export or is_zip_export):
        return '', (
            "The /batch command only supports WhatsApp .txt or .zip exports.\n"
            "Attach the exported chat file and send @bot /batch."
        )

    file_size = int(document.get('file_size') or 0)
    max_mb = max(1, int(getattr(settings, 'WHATSAPP_BATCH_MAX_FILE_SIZE_MB', 5)))
    if file_size and file_size > max_mb * 1024 * 1024:
        return '', f"WhatsApp export is too large. Maximum size is {max_mb} MB."

    bot_token = settings.TELEGRAM_BOT_TOKEN
    file_id = document.get('file_id')
    if not bot_token or not file_id:
        return '', "Could not download the WhatsApp export from Telegram."

    try:
        file_meta = requests.get(
            f'https://api.telegram.org/bot{bot_token}/getFile',
            params={'file_id': file_id},
            timeout=settings.API_REQUEST_TIMEOUT,
        )
        file_meta.raise_for_status()
        file_path = file_meta.json().get('result', {}).get('file_path', '')
        if not file_path:
            return '', "Telegram did not return a downloadable file path."

        file_response = requests.get(
            f'https://api.telegram.org/file/bot{bot_token}/{file_path}',
            timeout=settings.API_REQUEST_TIMEOUT,
        )
        file_response.raise_for_status()
        raw = file_response.content
        if len(raw) > max_mb * 1024 * 1024:
            return '', f"WhatsApp export is too large. Maximum size is {max_mb} MB."
        return _extract_whatsapp_export_text(raw, filename, max_mb), ''
    except requests.Timeout:
        logger.warning("Timed out downloading Telegram WhatsApp export")
        return '', "Timed out downloading the WhatsApp export. Please resend it."
    except ValueError as exc:
        return '', str(exc)
    except Exception as exc:
        logger.error(f"Failed to download Telegram WhatsApp export: {exc}", exc_info=True)
        return '', "Could not download the WhatsApp export. Please resend it."


def _extract_whatsapp_export_text(raw: bytes, filename: str, max_mb: int) -> str:
    if str(filename or '').lower().endswith('.zip'):
        return _decode_whatsapp_export_zip(raw, max_mb)
    return _decode_whatsapp_export_bytes(raw)


def _decode_whatsapp_export_zip(raw: bytes, max_mb: int) -> str:
    max_bytes = max(1, int(max_mb)) * 1024 * 1024
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            text_files = [
                info for info in archive.infolist()
                if not info.is_dir() and info.filename.lower().endswith('.txt')
            ]
            if not text_files:
                raise ValueError(
                    "The WhatsApp zip did not contain a .txt chat export. "
                    "Use WhatsApp Export Chat and resend the zip."
                )
            text_files.sort(
                key=lambda info: (
                    'whatsapp chat' not in info.filename.lower()
                    and '_chat' not in info.filename.lower(),
                    len(info.filename),
                )
            )
            export_info = text_files[0]
            if export_info.file_size > max_bytes:
                raise ValueError(
                    f"WhatsApp chat text inside the zip is too large. "
                    f"Maximum size is {max_mb} MB."
                )
            return _decode_whatsapp_export_bytes(archive.read(export_info))
    except zipfile.BadZipFile as exc:
        raise ValueError(
            "The attached zip could not be opened. Please export the WhatsApp chat again."
        ) from exc


def _decode_whatsapp_export_bytes(raw: bytes) -> str:
    for encoding in ('utf-8-sig', 'utf-8', 'utf-16', 'latin-1'):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', errors='replace')


def _process_single_message(
    telegram_message_id: str,
    content: str,
    sender: str,
    has_image: bool,
    received_at: datetime,
    group_id: str = None,
    source_telegram_message_id: str = '',
    batch_index: int = None,
    source: str = 'telegram bot',
    sync_after_success: bool = True,
    defer_sheet_sync: bool = False,
) -> dict:
    """
    Run one message through dedup → parse → store → sheet sync.

    Resolves the sheet_id from GroupRegistry using group_id, then passes
    both down to process_and_store_message so the correct Google Sheet
    receives the data.
    """
    from core.services.storage import MessageRejectedError, process_and_store_message
    from core.services.group_config import GroupRegistry, get_sheet_id_for_group

    try:
        if not group_id:
            return {'status': 'error', 'error': 'No group_id provided'}

        # Resolve sheet_id via GroupRegistry
        registry = GroupRegistry.get_instance()
        group_config = registry.get_group(group_id)
        if not group_config:
            logger.error(f"No config found for group {group_id}")
            # Return a generic error — don't expose the group_id to the caller
            return {
                'status': 'error',
                'error': 'This group is not configured to receive messages.',
            }

        sheet_id = group_config.sheet_id
        sheet_name = group_config.sheet_name
        sheet_schema = group_config.sheet_schema_config

        try:
            parsed_message = process_and_store_message(
                telegram_message_id=telegram_message_id,
                content=content,
                sender=sender,
                received_at=received_at,
                has_image=has_image,
                group_id=group_id,
                sheet_name=sheet_name,
                source=source,
                source_telegram_message_id=source_telegram_message_id,
                batch_index=batch_index,
                sheet_id=sheet_id,       # ← forwarded to sheets service
                sheet_schema=sheet_schema,
                defer_sheet_sync=defer_sheet_sync,
            )
        except MessageRejectedError as exc:
            return _rejected_message_result(exc)

        if parsed_message is None:
            return {'status': 'duplicate', 'message_id': telegram_message_id}

        if sync_after_success and getattr(parsed_message, 'synced_to_sheets', False) is True:
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
            'branch_region': 'County',
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
            'warnings': getattr(parsed_message, '_processing_warnings', []),
            'parsed_message_id': parsed_message.pk,
        }

        if result['status'] == 'partial':
            sync_error = getattr(parsed_message, '_processing_error', '')
            if sync_error:
                result['error'] = sync_error
            else:
                result['warning'] = (
                    result['warnings'][0]
                    if result.get('warnings')
                    else 'Message processed with partial confidence.'
                )

        return result

    except Exception as exc:
        logger.error(f"Error in _process_single_message: {exc}", exc_info=True)
        return {'status': 'error', 'error': 'Message could not be processed'}


def _rejected_message_result(exc) -> dict:
    parsed = getattr(exc, 'parsed_result', None)
    captured_fields = {}
    field_map = {
        'sender': 'Sender',
        'customer_name': 'Customer Name',
        'customer_phone': 'Phone Number',
        'customer_id': 'Customer ID',
        'branch_region': 'County',
        'problem_description': 'Complaint Description',
    }
    for attr, label in field_map.items():
        value = getattr(parsed, attr, '') if parsed else ''
        if value:
            captured_fields[label] = (
                str(value)[:140] if attr == 'problem_description' else str(value)
            )

    return {
        'status': 'rejected',
        'message': str(exc),
        'missing_fields': list(getattr(exc, 'missing_fields', []) or []),
        'warnings': list(getattr(exc, 'warnings', []) or []),
        'captured_fields': captured_fields,
    }


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
        case_id_line = f"\nCase ID: {result['message_id']} (use this for /update)"

    warning_lines = ''
    warnings = result.get('warnings') or []
    if warnings:
        warning_lines = "\nWarnings:\n" + "\n".join(
            f"- {warning}" for warning in warnings[:5] if str(warning).strip()
        )

    if status == 'success':
        text = (
            f'OK. Message received and saved successfully'
            f'{case_id_line}{fields_summary}{warning_lines}'
        )
    elif status == 'rejected':
        missing = result.get('missing_fields') or []
        missing_lines = "\n".join(f"- {field}" for field in missing if str(field).strip())
        fix_section = f"\nMissing required fields:\n{missing_lines}" if missing_lines else ''
        text = (
            'Rejected. Complaint was not saved because required fields are missing.'
            f'{fix_section}{fields_summary}\n\n'
            'Required complaint fields:\n'
            '- NAME\n'
            '- TEL\n'
            '- ID\n'
            '- NATURE OF THE PROBLEM'
        )
    elif status == 'partial':
        if result.get('error') and 'sheet' in result['error'].lower():
            text = (
                f'Warning: Message saved to database but could not sync to the '
                f'register at this time. It will be retried automatically.'
                f'{case_id_line}{fields_summary}{warning_lines}'
            )
        else:
            text = (
                f'Warning: Message partially processed (some fields were not '
                f'recognised){case_id_line}{fields_summary}{warning_lines}'
            )
    elif status == 'duplicate':
        text = 'Warning: This message has already been processed.'
    elif status == 'skipped':
        text = 'Warning: Message skipped - no text content found.'
    elif status == 'batch_processed':
        success = result.get('success', 0)
        total = result.get('total', 0)
        rejected = result.get('rejected', 0)
        duplicates = result.get('duplicates', 0)
        partial = result.get('partial', 0)
        errors = result.get('errors', 0)
        if result.get('source') == 'whatsapp_export':
            saved = success + partial
            lines = [
                'WhatsApp batch processed',
                f"Export messages found: {result.get('export_messages', total)}",
                f"Complaint entries processed: {total}",
                f"Saved: {saved}",
            ]
            skipped = result.get('skipped_non_complaint', 0)
            if skipped:
                lines.append(f"Skipped non-complaint chat messages: {skipped}")
            system_lines = result.get('system_lines', 0)
            if system_lines:
                lines.append(f"Skipped WhatsApp system lines: {system_lines}")
            if result.get('truncated'):
                lines.append(
                    f"Processed the first {result.get('max_entries')} export messages because a limit is configured. "
                    "Set WHATSAPP_BATCH_MAX_MESSAGES=0 to process the full export in one upload."
                )
            for label, key in (
                ('Sheet sync before import', 'sheet_sync_before'),
                ('Sheet sync after import', 'sheet_sync_after'),
            ):
                sync = result.get(key)
                if not sync:
                    continue
                status_text = sync.get('status', 'unknown')
                lines.append(
                    f"{label}: {status_text} "
                    f"({sync.get('row_count', 0)} sheet rows, "
                    f"{sync.get('backend_count', 0)} backend cases)"
                )
                sync_errors = sync.get('errors') or []
                if sync_errors:
                    lines.append(f"{label} warning: {sync_errors[0]}")
        else:
            lines = [
                f'Batch processed: {success}/{total} messages saved.',
            ]
        if rejected:
            lines.append(f'Rejected: {rejected}')
        if duplicates:
            lines.append(f'Duplicates skipped: {duplicates}')
        if partial:
            lines.append(f'Saved with sync warnings: {partial}')
        if errors:
            lines.append(f'Errors: {errors}')

        rejected_results = [
            item for item in result.get('results', [])
            if item.get('status') == 'rejected'
        ]
        if rejected_results:
            lines.append('')
            lines.append('Rejected case details:')
            for index, item in enumerate(rejected_results[:3], start=1):
                missing = item.get('missing_fields') or []
                missing_text = ', '.join(str(field) for field in missing if str(field).strip())
                lines.append(f'{index}. Missing: {missing_text or "required fields"}')
            lines.append('')
            lines.append('Each complaint must include NAME, TEL, ID, and NATURE OF THE PROBLEM.')

        text = "\n".join(lines)
    elif status == 'jawabu_batch_processed':
        lines = [
            "Jawabu import processed",
            f"Export messages found: {result.get('export_messages', 0)}",
        ]
        skipped_before_start = result.get('skipped_before_start', 0)
        if skipped_before_start:
            lines.append(f"Skipped before configured start date: {skipped_before_start}")
        skipped_already_processed = result.get('skipped_already_processed', 0)
        if skipped_already_processed:
            cutoff = result.get('latest_processed_at') or 'last imported message'
            lines.append(
                f"Skipped already processed messages up to {cutoff}: "
                f"{skipped_already_processed}"
            )
        consolidated = result.get('consolidated', 0)
        lines.extend([
            f"Visit records processed: {result.get('processed', 0)}",
        ])
        if consolidated:
            lines.append(f"Auto-consolidated duplicate media/detail messages: {consolidated}")
        lines.extend([
            f"Imported: {result.get('imported', 0)}",
            f"Duplicates needing review: {result.get('duplicate_review', 0)}",
            f"Rejected: {result.get('rejected', 0)}",
            f"Failed: {result.get('failed', 0)}",
        ])
        duplicates = result.get('duplicates') or []
        if duplicates:
            lines.extend(["", "Manual verification needed"])
            for index, item in enumerate(duplicates[:8], start=1):
                lines.append(
                    f"{index}. ID {item.get('national_id') or 'missing'} | "
                    f"Phone {item.get('primary_phone') or 'missing'}"
                )
                lines.append(f"   {item.get('message') or 'message details unavailable'}")
                if item.get('duplicate_group_id'):
                    lines.append(f"   Group: {item['duplicate_group_id']}")
                existing_messages = item.get('existing_messages') or []
                for existing_message in existing_messages[:3]:
                    lines.append(f"   Existing: {existing_message}")
            if len(duplicates) > 8:
                lines.append(f"...and {len(duplicates) - 8} more duplicate message(s).")

        rejections = result.get('rejections') or []
        if rejections:
            lines.extend(["", "Rejected records"])
            for index, item in enumerate(rejections[:5], start=1):
                missing = ', '.join(item.get('missing_fields') or [])
                lines.append(f"{index}. Missing: {missing or 'required fields'}")
                lines.append(f"   {item.get('message') or 'message details unavailable'}")
            if len(rejections) > 5:
                lines.append(f"...and {len(rejections) - 5} more rejected record(s).")

        if result.get('message'):
            lines.extend(["", str(result['message'])])

        text = "\n".join(lines)
    elif status == 'fca_batch_processed':
        lines = [
            "FCA Excel import processed",
            f"Files read: {result.get('files', 0)}",
            f"Rows processed: {result.get('processed', 0)}",
            f"Imported: {result.get('imported', 0)}",
            f"Review needed: {result.get('review_needed', 0)}",
            f"Failed: {result.get('failed', 0)}",
        ]
        if result.get('sheet_tab'):
            lines.append(f"Target tab: {result.get('sheet_tab')}")
        decision_parts = []
        for key, label in (
            ('approved', 'Approved'),
            ('rejected', 'Rejected'),
            ('deferred', 'Deferred'),
            ('cash', 'Cash'),
        ):
            value = result.get(key, 0)
            if value:
                decision_parts.append(f"{label}: {value}")
        if decision_parts:
            lines.extend(["", "Decisions", ", ".join(decision_parts)])
        if result.get('duplicate_source_rows'):
            lines.append(f"Duplicate source rows flagged: {result.get('duplicate_source_rows')}")
        reviews = result.get('review_examples') or []
        if reviews:
            lines.extend(["", "Manual review examples"])
            for index, item in enumerate(reviews[:5], start=1):
                lines.append(
                    f"{index}. {item.get('customer_name') or item.get('primary_phone') or 'Unknown customer'}"
                )
                lines.append(f"   {item.get('reason') or 'Needs review'}")
                lines.append(f"   {item.get('source') or ''}")
        errors = [error for error in (result.get('errors') or []) if error]
        if errors:
            lines.extend(["", "Errors"])
            lines.extend(f"- {error}" for error in errors[:5])
        text = "\n".join(lines)
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
        }
        reply_to_message_id = message_data.get('message_id')
        if reply_to_message_id:
            data['reply_to_message_id'] = reply_to_message_id
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
                "group_id": "-1001234567890"   ← optional
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

            # ── KEY FIX: pass group_id from the request (or fallback) ──
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


def _looks_like_order_approval_content(content: str) -> bool:
    if not content:
        return False
    if re.search(
        r'\bcustomer\s+complain(?:t)?\b|\bnature\s+of\s+(?:the\s+)?problem\b',
        content,
        flags=re.IGNORECASE,
    ):
        return False
    labels = {
        'id',
        'date visited',
        'customer name',
        'primary phone',
        'secondary phone',
        'county',
        'sub-county',
        'sub county',
        'landmark',
        'visited by',
        'hb staff',
        'hb deposit',
        'jbl deposit',
        'comment',
        'imab created',
        'customer no',
        'credit analysis',
        'final decision',
    }
    seen = set()
    for line in content.splitlines():
        if ':' not in line:
            continue
        label = line.split(':', 1)[0].strip().lower()
        if label in labels:
            seen.add(label)
    return 'id' in seen and bool(seen - {'id'})


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
