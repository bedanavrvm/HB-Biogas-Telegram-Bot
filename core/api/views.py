"""
API Views for the biogas telegram bot.

Endpoints:
- POST /api/webhook/telegram/  - Receive Telegram webhook
- POST /api/process/messages/  - Manual batch processing
- POST /api/resync/unsynced/   - Resync unsynced messages
- GET  /api/health/            - Health check

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
import threading
from datetime import datetime, timezone as dt_timezone
from django.utils import timezone
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.conf import settings
import hmac
import hashlib
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



@require_http_methods(["GET"])
def tat_tracker_app(request):
    """Render the TAT Tracker Telegram Mini App."""
    from core.services.tat_tracker import decode_tat_start_param
    start_payload = decode_tat_start_param(request.GET.get('tgWebAppStartParam') or request.GET.get('startapp') or '')
    group_id = request.GET.get('group_id') or start_payload.get('group_id', '')
    token = request.GET.get('token') or start_payload.get('token', '')
    return render(request, 'tat_tracker/app.html', {'group_id': group_id, 'token': token})


def _tat_json_body(request) -> dict:
    try:
        return json.loads(request.body.decode('utf-8') or '{}')
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}


def _tat_context(payload: dict):
    from core.services.group_config import GroupRegistry
    from core.services.tat_tracker import is_tat_tracker_workflow, staff_user_for_payload, validate_tat_form_token, validate_tat_telegram_webapp_init_data
    group_id = str(payload.get('group_id') or '').strip()
    token = str(payload.get('token') or '').strip()
    init_data = str(payload.get('init_data') or '').strip()
    auth_valid, auth_error, user_payload = validate_tat_telegram_webapp_init_data(init_data)
    if not auth_valid and not token:
        return '', None, {}, {}, JsonResponse({'ok': False, 'error': auth_error}, status=403)
    if token:
        token_valid, token_error = validate_tat_form_token(token, group_id)
        if not token_valid:
            return group_id, None, {}, {}, JsonResponse({'ok': False, 'error': token_error}, status=403)
    group_config = GroupRegistry.get_instance().get_group(group_id)
    if not group_config or not is_tat_tracker_workflow(group_config):
        return group_id, None, {}, {}, JsonResponse({'ok': False, 'error': 'TAT Tracker is not configured for this group.'}, status=403)
    user = staff_user_for_payload(group_config, user_payload)
    if not user.get('authorized'):
        return group_id, group_config, user_payload, user, JsonResponse({'ok': False, 'error': user.get('reason') or 'Unauthorized.'}, status=403)
    return group_id, group_config, user_payload, user, None


@csrf_exempt
@require_http_methods(["POST"])
def tat_tracker_bootstrap(request):
    payload = _tat_json_body(request)
    group_id, group_config, user_payload, user, error = _tat_context(payload)
    if error:
        return error
    from core.services.tat_tracker import bootstrap
    return JsonResponse({'ok': True, 'data': bootstrap(group_config, user_payload)})


@csrf_exempt
@require_http_methods(["POST"])
def tat_tracker_home(request):
    payload = _tat_json_body(request)
    group_id, group_config, user_payload, user, error = _tat_context(payload)
    if error:
        return error
    from core.services.tat_tracker import home_data
    return JsonResponse({'ok': True, 'data': home_data(group_config, user)})


@csrf_exempt
@require_http_methods(["POST"])
def tat_tracker_search(request):
    payload = _tat_json_body(request)
    group_id, group_config, user_payload, user, error = _tat_context(payload)
    if error:
        return error
    from core.services.tat_tracker import search_cases
    return JsonResponse({'ok': True, 'results': search_cases(group_config, user, payload.get('query', ''))})



@csrf_exempt
@require_http_methods(["POST"])
def tat_tracker_target_settings(request):
    payload = _tat_json_body(request)
    group_id, group_config, user_payload, user, error = _tat_context(payload)
    if error:
        return error
    from core.services.tat_tracker import can_manage_tat_targets, tat_target_settings, update_tat_target_settings
    if not can_manage_tat_targets(user):
        return JsonResponse({'ok': False, 'error': 'Only TAT administrators or IT staff can change SLA targets.'}, status=403)
    if 'targets' not in payload:
        return JsonResponse({'ok': True, 'data': {'targets': tat_target_settings(group_config.workflow)}})
    try:
        return JsonResponse({'ok': True, 'data': update_tat_target_settings(group_config, user, payload.get('targets'))})
    except ValueError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
@csrf_exempt
@require_http_methods(["POST"])
def tat_tracker_create(request):
    payload = _tat_json_body(request)
    group_id, group_config, user_payload, user, error = _tat_context(payload)
    if error:
        return error
    from core.services.tat_tracker import create_case
    try:
        data = create_case(group_config, user, payload)
        _send_tat_next_role_alert(group_config, data)
        return JsonResponse({'ok': True, 'data': data})
    except Exception as exc:
        logger.warning('TAT Tracker create failed: %s', exc, exc_info=True)
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)


@csrf_exempt
@require_http_methods(["POST"])
def tat_tracker_detail(request):
    payload = _tat_json_body(request)
    group_id, group_config, user_payload, user, error = _tat_context(payload)
    if error:
        return error
    from core.services.tat_tracker import get_case_detail
    try:
        return JsonResponse({'ok': True, 'data': get_case_detail(group_config, user, payload.get('case_id', ''))})
    except Exception as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=404)


@csrf_exempt
@require_http_methods(["POST"])
def tat_tracker_update(request):
    payload = _tat_json_body(request)
    group_id, group_config, user_payload, user, error = _tat_context(payload)
    if error:
        return error
    from core.services.tat_tracker import update_case
    try:
        data = update_case(group_config, user, payload.get('case_id', ''), payload.get('updates') or [])
        _dispatch_tat_approval_certificate(payload.get('case_id', ''), user)
        _send_tat_next_role_alert(group_config, data)
        return JsonResponse({'ok': True, 'data': data})
    except Exception as exc:
        logger.warning('TAT Tracker update failed: %s', exc, exc_info=True)
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)


def _dispatch_tat_approval_certificate(case_id: str, user: dict) -> None:
    if not getattr(settings, 'TAT_TRACKER_SIGNATURES_ENABLED', False):
        return
    from core.models import TatTrackerApprovalCertificate
    from core.services.tat_signature import dispatch_certificate

    certificate = TatTrackerApprovalCertificate.objects.filter(
        case__case_id=str(case_id),
        status='awaiting_signature',
        staff_member__telegram_user_id=str(user.get('telegram_id') or ''),
    ).order_by('-created_at').first()
    if not certificate:
        return
    try:
        signed_session = dispatch_certificate(certificate)
        certificate.status = 'signed'
        certificate.signed_document_hash = str(signed_session.get('signed_doc_hash') or '')
        certificate.signed_at = timezone.now()
        certificate.save(update_fields=['status', 'signed_document_hash', 'signed_at', 'updated_at'])
    except Exception as exc:
        certificate.status = 'delivery_failed'
        certificate.error = str(exc)
        certificate.save(update_fields=['status', 'error', 'updated_at'])
        logger.warning('TAT certificate delivery failed for %s: %s', certificate.external_reference, exc)


@csrf_exempt
@require_http_methods(["POST"])
def tat_signature_webhook(request):
    secret = str(getattr(settings, 'ESIGNATURES_WEBHOOK_SECRET', ''))
    signature = request.headers.get('X-ESignature-Signature', '')
    timestamp = request.headers.get('X-ESignature-Timestamp', '')
    if not secret or not timestamp or not signature.startswith('v1='):
        return JsonResponse({'ok': False, 'error': 'Unauthorized.'}, status=401)
    expected = hmac.new(secret.encode('utf-8'), f'{timestamp}.'.encode('utf-8') + request.body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature[3:], expected):
        return JsonResponse({'ok': False, 'error': 'Unauthorized.'}, status=401)
    try:
        payload = json.loads(request.body.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({'ok': False, 'error': 'Invalid JSON.'}, status=400)
    reference = str((payload.get('session') or {}).get('reference_number') or payload.get('reference_number') or '')
    delivery_id = str(request.headers.get('X-ESignature-Delivery') or '')
    event_type = str(request.headers.get('X-ESignature-Event') or payload.get('event_type') or '')
    from core.models import TatTrackerApprovalCertificate
    certificate = TatTrackerApprovalCertificate.objects.filter(external_reference=reference).first()
    if not certificate or (delivery_id and certificate.webhook_delivery_id == delivery_id):
        return JsonResponse({'ok': True})
    if event_type == 'session.fully_signed':
        document = (payload.get('document') or {})
        certificate.status = 'signed'
        certificate.signed_document_hash = str(document.get('sha256_hash') or (payload.get('session') or {}).get('signed_doc_hash') or '')
        certificate.signed_at = timezone.now()
    elif event_type == 'session.declined':
        certificate.status = 'declined'
    if delivery_id:
        certificate.webhook_delivery_id = delivery_id
    certificate.save()
    return JsonResponse({'ok': True})


def _send_tat_next_role_alert(group_config, case_data: dict) -> None:
    from core.services.tat_tracker import next_role_alert

    alert = next_role_alert(group_config, case_data)
    if not alert:
        return
    _post_telegram_reply(chat_id=group_config.group_id, message_data={}, text=alert['text'])
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

    from core.services.order_approval import (
        decode_order_approval_start_param,
        order_approval_branch_choices,
    )

    group_id = str(request.GET.get('group_id', '')).strip()
    form_token = str(request.GET.get('token', '')).strip()
    if not group_id or not form_token:
        start_payload = decode_order_approval_start_param(
            request.GET.get('tgWebAppStartParam')
            or request.GET.get('startapp')
            or request.GET.get('start_param')
            or ''
        )
        group_id = group_id or start_payload.get('group_id', '')
        form_token = form_token or start_payload.get('token', '')

    return render(
        request,
        'order_approval/form.html',
        {
            'group_id': group_id,
            'form_token': form_token,
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


@require_http_methods(["GET"])
def jawabu_farmers_review(request):
    """Render Mini App review screen for a staged Jawabu Farmers CSV upload."""
    from django.utils.safestring import mark_safe
    from core.models import JawabuFarmerUploadBatch
    from core.services.jawabu_master import decode_farmup_start_param, validate_farmup_review_token

    batch_id = str(request.GET.get('batch_id', '')).strip()
    token = str(request.GET.get('token', '')).strip()
    if not batch_id or not token:
        raw_start_param = (
            request.GET.get('tgWebAppStartParam')
            or request.GET.get('startapp')
            or request.GET.get('start_param')
            or ''
        )
        start_payload = decode_farmup_start_param(raw_start_param)
        batch_id = batch_id or start_payload.get('batch_id', '')
        token = token or start_payload.get('token', '')
        if not batch_id or not token:
            return render(request, 'jawabu_farmers/bootstrap.html')
    valid, error = validate_farmup_review_token(batch_id, token)
    if not valid:
        return render(request, 'jawabu_farmers/unavailable.html', {'message': error}, status=403)
    batch = JawabuFarmerUploadBatch.objects.filter(id=batch_id).first()
    if not batch:
        return render(
            request,
            'jawabu_farmers/unavailable.html',
            {'message': 'This Farmers upload review batch was not found.'},
            status=404,
        )
    payload = {'batch_id': str(batch.id), 'token': token, 'rows': batch.parsed_rows or [], 'status': batch.status}
    return render(request, 'jawabu_farmers/review.html', {'batch': batch, 'batch_json': mark_safe(json.dumps(payload, ensure_ascii=True).replace('</', '<\\/'))})


@csrf_exempt
@require_http_methods(["POST"])
def jawabu_farmers_review_commit(request):
    """Commit approved Mini App rows into the Jawabu farmer master table."""
    from core.models import JawabuFarmerUploadBatch
    from core.services.jawabu_master import commit_farmup_review_batch, validate_farmup_review_token

    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid request body.'}, status=400)
    batch_id = str(payload.get('batch_id', '')).strip()
    token = str(payload.get('token', '')).strip()
    valid, error = validate_farmup_review_token(batch_id, token)
    if not valid:
        return JsonResponse({'success': False, 'message': error}, status=403)
    batch = JawabuFarmerUploadBatch.objects.filter(id=batch_id).first()
    if not batch:
        return JsonResponse({'success': False, 'message': 'Upload batch was not found.'}, status=404)
    rows = payload.get('rows') or []
    if not isinstance(rows, list):
        return JsonResponse({'success': False, 'message': 'Rows must be a list.'}, status=400)
    from core.services.group_config import GroupRegistry

    group_config = GroupRegistry.get_instance().get_group(batch.group_id)
    result = commit_farmup_review_batch(batch, rows, group_config=group_config)
    result['rows'] = batch.parsed_rows
    sheet_sync = result.get('sheet_sync') or {}
    reply_lines = [
        'Farmers master upload reviewed',
        f"Committed: {result.get('committed', 0)}",
        f"Skipped: {result.get('skipped', 0)}",
        f"Review needed: {result.get('review_needed', 0)}",
    ]
    if sheet_sync.get('enabled'):
        reply_lines.extend([
            '',
            'Master Data sheet sync:',
            f"Created: {sheet_sync.get('created', 0)}",
            f"Updated: {sheet_sync.get('updated', 0)}",
            f"Conflicts: {sheet_sync.get('conflicts', 0)}",
        ])
        if sheet_sync.get('errors'):
            reply_lines.append(f"Warning: {sheet_sync['errors'][0]}")
    else:
        reply_lines.extend(['', 'Master Data sheet sync: not enabled for this group'])
    _post_telegram_reply(chat_id=batch.group_id, message_data={}, text='\n'.join(reply_lines))
    return JsonResponse(result, status=200 if result.get('success') else 400)


@require_http_methods(["GET"])
def fca_review(request):
    from django.shortcuts import render
    from django.utils.safestring import mark_safe
    from core.services.fca import (
        decode_fcaup_start_param,
        fcaup_review_payload,
        validate_fcaup_review_token,
    )

    batch_id = str(request.GET.get('batch_id') or '').strip()
    token = str(request.GET.get('token') or '').strip()
    start_param = str(
        request.GET.get('tgWebAppStartParam')
        or request.GET.get('startapp')
        or request.GET.get('start_param')
        or ''
    ).strip()
    if start_param and (not batch_id or not token):
        decoded = decode_fcaup_start_param(start_param)
        batch_id = batch_id or decoded.get('batch_id', '')
        token = token or decoded.get('token', '')
    valid, error = validate_fcaup_review_token(batch_id, token)
    if not batch_id or not valid:
        return render(
            request,
            'fca_review/unavailable.html',
            {'message': error or 'This FCA review link is missing or invalid.'},
            status=403,
        )
    payload = fcaup_review_payload(batch_id, token)
    return render(
        request,
        'fca_review/review.html',
        {
            'batch_id': batch_id,
            'batch_json': mark_safe(json.dumps(payload)),
        },
    )


@csrf_exempt
@require_http_methods(["POST"])
def fca_review_commit(request):
    from core.services.fca import (
        commit_fcaup_review_batch,
        validate_fcaup_review_token,
    )
    from core.services.group_config import GroupRegistry

    try:
        payload = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid JSON payload.'}, status=400)

    batch_id = str(payload.get('batch_id') or '').strip()
    token = str(payload.get('token') or '').strip()
    valid, error = validate_fcaup_review_token(batch_id, token)
    if not batch_id or not valid:
        return JsonResponse({'success': False, 'message': error or 'Invalid FCA review token.'}, status=403)

    from core.models import FcaImportRecord
    first_record = FcaImportRecord.objects.filter(telegram_message_id=batch_id).order_by('created_at').first()
    group_config = None
    if first_record:
        group_config = GroupRegistry.get_instance().get_group(first_record.group_id)
    result = commit_fcaup_review_batch(
        batch_id=batch_id,
        rows=payload.get('rows') or [],
        group_config=group_config,
    )
    return JsonResponse(result, status=200 if result.get('success') else 400)


@require_http_methods(["GET"])
def spin_form(request):
    """Render the SPIN/CRB request Mini App form."""
    from django.utils.safestring import mark_safe
    from core.services.group_config import GroupRegistry
    from core.services.spin_credit import decode_spin_start_param, is_spin_workflow, spin_branch_choices, spin_default_branch

    group_id = str(request.GET.get('group_id', '')).strip()
    form_token = str(request.GET.get('token', '')).strip()
    if not group_id or not form_token:
        start_payload = decode_spin_start_param(
            request.GET.get('tgWebAppStartParam')
            or request.GET.get('startapp')
            or request.GET.get('start_param')
            or ''
        )
        group_id = group_id or start_payload.get('group_id', '')
        form_token = form_token or start_payload.get('token', '')

    branch_choices = []
    default_branch = ''
    if group_id:
        group_config = GroupRegistry.get_instance().get_group(group_id)
        if group_config and is_spin_workflow(group_config):
            branch_choices = spin_branch_choices(group_config)
            default_branch = spin_default_branch(group_config)
    payload = {
        'group_id': group_id,
        'form_token': form_token,
        'branch_choices': branch_choices,
        'default_branch': default_branch,
    }
    return render(
        request,
        'spin/form.html',
        {'form_json': mark_safe(json.dumps(payload, ensure_ascii=True).replace('</', '<\\/'))},
    )


@csrf_exempt
@require_http_methods(["POST"])
def spin_form_submit(request):
    """Accept a SPIN/CRB Mini App form submission."""
    uploaded_files = []
    content_type = str(request.META.get('CONTENT_TYPE', ''))
    if content_type.startswith('application/json'):
        try:
            payload = json.loads(request.body.decode('utf-8') or '{}')
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'message': 'Invalid request body.'}, status=400)
        fields = payload.get('fields') or payload
    else:
        try:
            payload = request.POST.dict()
            files_map = request.FILES
        except Exception as exc:
            from django.http.multipartparser import MultiPartParserError

            if isinstance(exc, MultiPartParserError):
                return JsonResponse(
                    {
                        'success': False,
                        'status': 'upload_error',
                        'message': 'Telegram could not upload those files. Submit without files first, or retry with fewer/smaller files.',
                        'errors': ['Telegram could not upload those files. Submit without files first, or retry with fewer/smaller files.'],
                    },
                    status=400,
                )
            raise
        fields = payload
        from core.services.spin_credit import collect_spin_uploaded_files, validate_spin_uploaded_files

        upload_errors = validate_spin_uploaded_files(files_map)
        if upload_errors:
            return JsonResponse(
                {
                    'success': False,
                    'status': 'validation_error',
                    'message': 'Fix the highlighted file upload issue and submit again.',
                    'errors': upload_errors,
                },
                status=400,
            )
        uploaded_files = collect_spin_uploaded_files(files_map)

    group_id, group_config, auth_payload, error_response_obj = _spin_webapp_context(payload)
    if error_response_obj:
        return error_response_obj

    from core.services.spin_credit import process_spin_form_submission

    result = process_spin_form_submission(
        group_config=group_config,
        fields=fields,
        sender=_sender_from_webapp_auth(auth_payload),
        received_at=timezone.now(),
        uploaded_files=uploaded_files,
    )
    _send_spin_webapp_chat_reply(group_id, result)
    return JsonResponse(result, status=200 if result.get('success') else 400)


def _spin_webapp_context_get(request):
    from core.services.group_config import GroupRegistry
    from core.services.spin_credit import (
        is_spin_workflow,
        validate_spin_form_token,
        validate_spin_telegram_webapp_init_data,
    )
    group_id = str(request.GET.get('group_id', '')).strip()
    init_data = request.GET.get('init_data', '') or request.headers.get('X-Telegram-Init-Data', '')
    form_token = request.GET.get('form_token', '')
    is_valid, auth_error, auth_payload = validate_spin_telegram_webapp_init_data(init_data)
    if not is_valid:
        token_valid, token_error = validate_spin_form_token(
            token=form_token,
            group_id=group_id,
        )
        if not token_valid:
            return group_id, None, {}, JsonResponse({'success': False, 'message': auth_error or token_error}, status=403)
        auth_payload = {}
    group_config = GroupRegistry.get_instance().get_group(group_id)
    if not group_config or not is_spin_workflow(group_config):
        return group_id, None, auth_payload, JsonResponse({'success': False, 'message': 'This Telegram group is not configured for SPIN/CRB requests.'}, status=400)
    return group_id, group_config, auth_payload, None


@csrf_exempt
@require_http_methods(["GET"])
def spin_form_requests(request):
    """List SPIN/CRB requests for dashboard."""
    group_id, group_config, auth_payload, error_response = _spin_webapp_context_get(request)
    if error_response:
        return error_response
    user_payload = {}
    if auth_payload.get('user'):
        try:
            user_payload = json.loads(auth_payload['user'])
        except json.JSONDecodeError:
            pass
    from core.services.spin_credit import is_user_spin_analyst, spin_request_id, format_sheet_datetime, REQUEST_TYPE_LABELS
    is_analyst = is_user_spin_analyst(user_payload)
    from core.models import SpinCreditRequest
    queryset = SpinCreditRequest.objects.filter(group_id=group_id)
    queryset = queryset.order_by('-request_datetime', '-created_at')
    data = []
    for r in queryset:
        parsed_f = r.parsed_fields or {}
        data.append({
            'id': str(r.id),
            'request_id': spin_request_id(r),
            'request_datetime': format_sheet_datetime(r.request_datetime) if r.request_datetime else '',
            'requested_by': r.requested_by,
            'request_type': REQUEST_TYPE_LABELS.get(r.request_type, r.request_type),
            'branch': parsed_f.get('branch') or r.source_chat,
            'customer_name': r.customer_name,
            'national_id': r.national_id,
            'primary_phone': r.primary_phone,
            'secondary_phone': r.secondary_phone,
            'customer_type': r.customer_type,
            'loan_product': r.loan_product,
            'requested_amount': float(r.requested_amount) if r.requested_amount is not None else 0.0,
            'tenor': r.tenor,
            'business_notes': r.business_notes,
            'code': r.code,
            'attachment_names': r.attachment_names or [],
            'media_urls': parsed_f.get('media_urls', '').split('\n') if parsed_f.get('media_urls') else [],
            'import_status': r.import_status,
            'sync_error': r.sync_error,
            'spin_report_url': parsed_f.get('spin_report_url', ''),
            'crb_report_url': parsed_f.get('crb_report_url', ''),
            'credit_analysis_report_url': parsed_f.get('credit_analysis_report_url', ''),
            'analysis_completed_at': parsed_f.get('analysis_completed_at', ''),
            'analysis_completed_by': parsed_f.get('analysis_completed_by', ''),
        })
    return JsonResponse({
        'success': True,
        'is_analyst': is_analyst,
        'requests': data
    })


@csrf_exempt
@require_http_methods(["POST"])
def spin_form_complete(request):
    """Accept analyst completing a SPIN/CRB request and uploading reports."""
    payload = request.POST.dict()
    group_id, group_config, auth_payload, error_response = _spin_webapp_context(payload)
    if error_response:
        return error_response
    user_payload = {}
    if auth_payload.get('user'):
        try:
            user_payload = json.loads(auth_payload['user'])
        except json.JSONDecodeError:
            pass
    from core.services.spin_credit import is_user_spin_analyst
    if not is_user_spin_analyst(user_payload):
        return JsonResponse({'success': False, 'message': 'Only designated credit analysts can complete requests.'}, status=403)
    request_id = payload.get('request_id')
    if not request_id:
        return JsonResponse({'success': False, 'message': 'Request ID is required.'}, status=400)
    from core.models import SpinCreditRequest
    try:
        record = SpinCreditRequest.objects.get(id=request_id)
    except (SpinCreditRequest.DoesNotExist, ValueError):
        return JsonResponse({'success': False, 'message': 'Request not found.'}, status=404)
    spin_report = request.FILES.get('spin_report')
    crb_report = request.FILES.get('crb_report')
    credit_analysis = request.FILES.get('credit_analysis')
    if not spin_report and not crb_report and not credit_analysis:
        return JsonResponse({'success': False, 'message': 'At least one report file must be uploaded.'}, status=400)
    sender_name = _sender_from_webapp_auth(auth_payload) or 'Credit Analyst'
    from core.services.spin_credit import upload_report, update_spin_request_in_sheet, spin_request_id
    spin_url = upload_report(group_config, spin_report, 'spin_report', sender_name, record.national_id) if spin_report else None
    crb_url = upload_report(group_config, crb_report, 'crb_report', sender_name, record.national_id) if crb_report else None
    analysis_url = upload_report(group_config, credit_analysis, 'credit_analysis_report', sender_name, record.national_id) if credit_analysis else None
    if not record.parsed_fields:
        record.parsed_fields = {}
    if spin_url:
        record.parsed_fields['spin_report_url'] = spin_url
    if crb_url:
        record.parsed_fields['crb_report_url'] = crb_url
    if analysis_url:
        record.parsed_fields['credit_analysis_report_url'] = analysis_url
    record.parsed_fields['analysis_completed_at'] = timezone.now().isoformat()
    record.parsed_fields['analysis_completed_by'] = sender_name
    record.parsed_fields['credit_analyst_name'] = sender_name
    record.import_status = 'completed'
    record.save(update_fields=['parsed_fields', 'import_status', 'updated_at'])
    sheet_updates = {
        'analysis_status': 'Completed',
        'credit_analyst_name': sender_name,
    }
    url_lines = []
    if spin_url:
        url_lines.append(f"SPIN: {spin_url}")
    if crb_url:
        url_lines.append(f"CRB: {crb_url}")
    if analysis_url:
        url_lines.append(f"Analysis: {analysis_url}")
    if url_lines:
        sheet_updates['analyst_response'] = '\n'.join(url_lines)
    sheet_synced = update_spin_request_in_sheet(group_config, record, sheet_updates)
    tg_lines = [
        'SPIN/CRB ANALYSIS COMPLETED',
        '',
        f"Request ID: {spin_request_id(record)}",
        f"Customer: {record.customer_name}",
        f"Completed by: {sender_name}",
        '',
        'Reports Uploaded:'
    ]
    if spin_url:
        tg_lines.append(f"- SPIN Report: {spin_url}")
    if crb_url:
        tg_lines.append(f"- CRB Report: {crb_url}")
    if analysis_url:
        tg_lines.append(f"- Credit Analysis: {analysis_url}")
    _post_telegram_reply(chat_id=group_config.group_id, message_data={}, text='\n'.join(tg_lines))
    return JsonResponse({
        'success': True,
        'message': 'Request marked completed and reports synced to sheets.',
        'spin_report_url': spin_url,
        'crb_report_url': crb_url,
        'credit_analysis_report_url': analysis_url,
        'sheet_synced': sheet_synced
    })


@csrf_exempt
@require_http_methods(["POST", "PATCH"])
def spin_form_review_update(request):
    """Apply corrections for a SPIN/CRB request that needs import review."""
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid request body.'}, status=400)

    group_id, group_config, _auth_payload, error_response = _spin_webapp_context(payload)
    if error_response:
        return error_response

    request_id = str(payload.get('request_id') or '').strip()
    if not request_id:
        return JsonResponse({'success': False, 'message': 'Request ID is required.'}, status=400)

    from core.models import SpinCreditRequest
    from core.services.spin_credit import update_spin_review_request

    try:
        record = SpinCreditRequest.objects.get(id=request_id, group_id=group_id)
    except (SpinCreditRequest.DoesNotExist, ValueError):
        return JsonResponse({'success': False, 'message': 'Request not found.'}, status=404)

    result = update_spin_review_request(
        group_config=group_config,
        record=record,
        fields=payload.get('fields') or payload,
    )
    status = 200 if result.get('success') else 400
    if result.get('status') == 'not_found':
        status = 404
    return JsonResponse(result, status=status)



def _spin_webapp_context(payload: dict):
    from core.services.group_config import GroupRegistry
    from core.services.spin_credit import (
        is_spin_workflow,
        validate_spin_form_token,
        validate_spin_telegram_webapp_init_data,
    )

    group_id = str((payload or {}).get('group_id', '')).strip()
    is_valid, auth_error, auth_payload = validate_spin_telegram_webapp_init_data(
        (payload or {}).get('init_data', '')
    )
    if not is_valid:
        token_valid, token_error = validate_spin_form_token(
            token=(payload or {}).get('form_token', ''),
            group_id=group_id,
        )
        if not token_valid:
            return (
                group_id,
                None,
                {},
                JsonResponse({'success': False, 'message': auth_error or token_error}, status=403),
            )
        auth_payload = {}

    group_config = GroupRegistry.get_instance().get_group(group_id)
    if not group_config or not is_spin_workflow(group_config):
        return (
            group_id,
            None,
            auth_payload,
            JsonResponse(
                {'success': False, 'message': 'This Telegram group is not configured for SPIN/CRB requests.'},
                status=400,
            ),
        )
    return group_id, group_config, auth_payload, None


def _send_spin_webapp_chat_reply(group_id: str, result: dict) -> None:
    if not group_id:
        return
    if result.get('success'):
        lines = [
            'SPIN request received',
            '',
            f"Request ID: {result.get('request_id', '')}",
            f"Type: {result.get('request_type', '')}",
            f"Customer: {result.get('customer_name', '')}",
            f"National ID: {result.get('national_id', '')}",
            f"Phone: {result.get('primary_phone', '')}",
        ]
        files_stored = result.get('files_stored', 0)
        if files_stored:
            lines.append(f"Documents attached: {files_stored}")
        lines.extend(['', 'The credit team can now review it in the SPIN dashboard.'])
    else:
        lines = [
            'SPIN request needs attention',
            '',
            result.get('message') or 'Please check the form and try again.',
        ]
        errors = [str(error) for error in (result.get('errors') or []) if str(error).strip()]
        if errors:
            lines.extend(['', 'Please update:'])
            lines.extend(f'- {error}' for error in errors[:6])
    _post_telegram_reply(chat_id=group_id, message_data={}, text='\n'.join(lines))

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
            logger.error("Message has no chat.id - cannot route to group")
            return {'status': 'error', 'error': 'Message missing chat information'}

        telegram_message_id = str(message_data.get('message_id', ''))
        sender = _extract_sender_name(message_data)
        raw_content = _extract_message_content(message_data)
        content = _extract_tagged_message_content(message_data)
        command_content = content if content is not None else raw_content
        has_image = _detect_image(message_data)
        received_at = _extract_timestamp(message_data)
        reply_to_id = str(
            message_data.get('reply_to_message', {}).get('message_id', '')
        )

        from core.services.group_config import GroupRegistry
        group_config = GroupRegistry.get_instance().get_group(group_id)

        if _looks_like_portal_command(command_content):
            logger.info("Routing /portal command for group %s from message %s", group_id, telegram_message_id)
            return _process_portal_command(group_config, sender, telegram_message_id)

        if not group_config and _looks_like_fcaup_command(command_content):
            logger.warning(
                "Ignoring /fcaup command for unconfigured group %s message %s",
                group_id,
                telegram_message_id,
            )
            return {
                'status': 'command',
                'reply_text': (
                    "FCA upload is not configured for this group.\n"
                    "Ask an admin to add this Telegram group in Django Admin, "
                    "then select the Jawabu HomeBiogas or Order Approval workflow."
                ),
            }
        if group_config:
            from core.services.jawabu import is_jawabu_workflow
            from core.services.spin_credit import is_spin_workflow
            from core.services.tat_tracker import is_tat_tracker_workflow
            from core.services.order_approval import (
                handle_order_approval_message,
                is_order_approval_workflow,
            )
            if _looks_like_fcaup_command(command_content):
                logger.info(
                    "Routing /fcaup command for group %s from message %s",
                    group_id,
                    telegram_message_id,
                )
                return _process_fcaup_command(
                    group_config=group_config,
                    message_data=message_data,
                    sender=sender,
                    telegram_message_id=telegram_message_id,
                )
            if is_spin_workflow(group_config):
                if content is None:
                    logger.debug(
                        f"Ignoring SPIN message {telegram_message_id}: bot was not tagged"
                    )
                    return {
                        'status': 'ignored',
                        'reason': 'Bot was not tagged',
                        'message_id': telegram_message_id,
                    }
                if _looks_like_spin_form_command(content):
                    return _process_spin_form_command(
                        group_config=group_config,
                        sender=sender,
                        telegram_message_id=telegram_message_id,
                    )
                if _looks_like_batch_command(content):
                    return _process_spin_batch_command(
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
                        "This group is configured for SPIN/CRB requests.\n"
                        "Send @bot /spin to open the request form, or @bot /batch with a WhatsApp .txt/.zip export."
                    ),
                }

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
                if _looks_like_fcaup_command(command_content):
                    return _process_fcaup_command(
                        group_config=group_config,
                        message_data=message_data,
                        sender=sender,
                        telegram_message_id=telegram_message_id,
                    )
                if _looks_like_farmup_command(content):
                    return _process_jawabu_farmup_command(
                        group_config=group_config,
                        message_data=message_data,
                        sender=sender,
                        telegram_message_id=telegram_message_id,
                    )
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
                        "Send @bot /spin to open the request form, or @bot /batch with a WhatsApp .txt/.zip export."
                    ),
                }
            if is_tat_tracker_workflow(group_config):
                if content is None:
                    logger.debug(
                        f"Ignoring TAT Tracker message {telegram_message_id}: bot was not tagged"
                    )
                    return {
                        'status': 'ignored',
                        'reason': 'Bot was not tagged',
                        'message_id': telegram_message_id,
                    }
                if _looks_like_tat_tracker_command(content):
                    return _process_tat_tracker_command(
                        group_config=group_config,
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
                        "This group is configured for the TAT Tracker.\n"
                        "Send @bot /tat to open the tracker Mini App."
                    ),
                }
            if is_order_approval_workflow(group_config):
                if _looks_like_fcaup_command(command_content):
                    return _process_fcaup_command(
                        group_config=group_config,
                        message_data=message_data,
                        sender=sender,
                        telegram_message_id=telegram_message_id,
                    )
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
        if group_config and _looks_like_fcaup_command(update_content):
            logger.info(
                "Routing /fcaup command from fallback for group %s message %s",
                group_id,
                telegram_message_id,
            )
            return _process_fcaup_command(
                group_config=group_config,
                message_data=message_data,
                sender=sender,
                telegram_message_id=telegram_message_id,
            )
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


def _looks_like_fcaup_command(content: str) -> bool:
    return bool(re.search(r'(?:^|\s)/fcaup(?:@\w+)?(?:\s|$)', str(content or '').strip(), re.IGNORECASE))


def _looks_like_farmup_command(content: str) -> bool:
    return bool(re.match(r'^/farmup(?:@\w+)?(?:\s|$)', str(content or '').strip(), re.IGNORECASE))


def _looks_like_spin_form_command(content: str) -> bool:
    return bool(re.match(r'^/(?:spin|form)(?:@\w+)?(?:\s|$)', str(content or '').strip(), re.IGNORECASE))

def _looks_like_tat_tracker_command(content: str) -> bool:
    return bool(re.match(r'^/(?:tat|tracker)(?:@\w+)?(?:\s|$)', str(content or '').strip(), re.IGNORECASE))


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

    from core.services.parser import analyze_whatsapp_export

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

    async_threshold = int(
        getattr(settings, 'WHATSAPP_BATCH_ASYNC_THRESHOLD', 100) or 0
    )
    if async_threshold > 0 and len(entries) > async_threshold:
        _start_case_batch_background_import(
            payload=payload,
            analysis=analysis,
            message_data=message_data,
            sender=sender,
            received_at=received_at,
            group_id=group_id,
            telegram_message_id=telegram_message_id,
        )
        return {
            'status': 'command',
            'reply_text': (
                "WhatsApp batch import started.\n"
                f"Export messages found: {len(entries)}\n"
                "The bot will reply here again when processing finishes. "
                "You can keep using Telegram while it runs."
            ),
        }

    return _run_whatsapp_batch_import(
        analysis=analysis,
        sender=sender,
        received_at=received_at,
        group_id=group_id,
        telegram_message_id=telegram_message_id,
    )


def _start_case_batch_background_import(
    payload: str,
    analysis: dict,
    message_data: dict,
    sender: str,
    received_at: datetime,
    group_id: str,
    telegram_message_id: str,
) -> None:
    """Run a large case WhatsApp import outside the webhook response."""
    del payload  # Payload is intentionally parsed before queueing to validate the export.

    def worker() -> None:
        from django.db import close_old_connections

        close_old_connections()
        try:
            result = _run_whatsapp_batch_import(
                analysis=analysis,
                sender=sender,
                received_at=received_at,
                group_id=group_id,
                telegram_message_id=telegram_message_id,
            )
            _send_telegram_reply(message_data, result)
        except Exception as exc:
            logger.error(
                "Background case WhatsApp batch import failed: %s",
                exc,
                exc_info=True,
            )
            _send_telegram_reply(
                message_data,
                {
                    'status': 'command',
                    'reply_text': (
                        "WhatsApp batch import failed before completion.\n"
                        "Please retry the export. If it fails again, ask an admin to check Render logs."
                    ),
                },
            )
        finally:
            close_old_connections()

    thread = threading.Thread(
        target=worker,
        name=f"case-batch-{telegram_message_id}",
        daemon=True,
    )
    thread.start()


def _run_whatsapp_batch_import(
    analysis: dict,
    sender: str,
    received_at: datetime,
    group_id: str,
    telegram_message_id: str,
) -> dict:
    from core.services.parser import MessageIntent, detect_message_intent
    from core.services.group_config import GroupRegistry
    from core.services.storage import duplicate_case_for_message, repair_case_sheet_sync

    entries = analysis.get('entries') or []
    configured_max = int(getattr(settings, 'WHATSAPP_BATCH_MAX_MESSAGES', 0) or 0)
    max_entries = configured_max if configured_max > 0 else len(entries)
    truncated = configured_max > 0 and len(entries) > max_entries
    entries_to_process = entries[:max_entries] if truncated else entries
    sync_before = _sync_case_sheet_for_batch(group_id, delete_missing=True)
    group_config = GroupRegistry.get_instance().get_group(group_id)
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
        if result.get('status') == 'duplicate':
            existing_case, duplicate_hash = duplicate_case_for_message(
                sender=entry.get('sender') or sender,
                content=content,
                received_at=entry.get('received_at') or received_at,
            )
            if existing_case:
                repair_result = repair_case_sheet_sync(existing_case, group_config=group_config)
                result.update({
                    'status': 'existing_matched',
                    'duplicate_reason': 'message_hash',
                    'message_hash': duplicate_hash,
                    'message_id': existing_case.message_id,
                    'parsed_message_id': existing_case.pk,
                    'sync_repair': repair_result,
                })
            else:
                result.update({
                    'duplicate_reason': 'message_hash',
                    'message_hash': duplicate_hash,
                    'sync_repair': {'status': 'missing_case', 'synced': False},
                })
        results.append(result)

    saved_count = sum(1 for r in results if r.get('status') in {'success', 'partial'})
    existing_count = sum(1 for r in results if r.get('status') == 'existing_matched')
    sync_repairs = [r.get('sync_repair') or {} for r in results if r.get('status') == 'existing_matched']
    already_synced = sum(1 for r in sync_repairs if r.get('status') == 'already_synced')
    sync_retried = sum(1 for r in sync_repairs if r.get('status') == 'sync_retried')
    sync_retry_failed = sum(1 for r in sync_repairs if r.get('status') == 'sync_failed')
    batch_sheet_append = _batch_append_case_results(
        results,
        group_id=group_id,
    ) if saved_count else None
    append_status = (batch_sheet_append or {}).get('status')
    sync_after = (
        _sync_case_sheet_for_batch(group_id, delete_missing=False)
        if saved_count and append_status in {'success', 'partial', 'skipped'} else None
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
        'new_cases_created': saved_count,
        'existing_cases_matched': existing_count,
        'already_synchronized': already_synced,
        'synchronization_retried': sync_retried + sync_retry_failed,
        'synchronization_succeeded': sync_retried,
        'synchronization_failed': sync_retry_failed,
        'review_needed': sum(
            1 for r in results
            if (r.get('captured_fields') or {}).get('Status') == 'Review Needed'
        ),
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
            'row_count': result.get('row_count'),
            'created_count': result.get('created_count', 0),
            'updated_count': result.get('updated_count', 0),
            'deleted_count': result.get('deleted_count', 0),
            'skipped_count': result.get('skipped_count', 0),
            'backend_count': result.get('backend_count'),
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
            'row_count': None,
            'created_count': 0,
            'updated_count': 0,
            'deleted_count': 0,
            'skipped_count': 0,
            'backend_count': None,
            'errors': [str(exc)],
        }



def _process_jawabu_farmup_command(
    group_config,
    message_data: dict,
    sender: str,
    telegram_message_id: str,
) -> dict:
    csv_text, filename, document_error = _download_telegram_csv_document(message_data)
    if document_error:
        return {'status': 'command', 'reply_text': document_error}
    if not csv_text:
        return {
            'status': 'command',
            'reply_text': (
                "Attach the Jawabu Farmers CSV and send:\n"
                "@bot /farmup\n\n"
                "The bot will open a review form before anything is written to master data."
            ),
        }

    from core.services.jawabu_master import (
        build_farmup_mini_app_url,
        build_farmup_review_url,
        create_farmup_review_batch,
    )

    batch, stats = create_farmup_review_batch(
        group_id=group_config.group_id,
        telegram_message_id=telegram_message_id,
        sender=sender,
        source_filename=filename,
        csv_text=csv_text,
    )
    review_url = build_farmup_review_url(str(batch.id))
    mini_app_url = build_farmup_mini_app_url(str(batch.id))
    launch_url = mini_app_url or review_url
    if not review_url:
        return {
            'status': 'command',
            'reply_text': 'CSV parsed, but APP_BASE_URL is not configured so the review form cannot open.',
        }
    launch_note = (
        "Opening as Telegram Mini App."
        if mini_app_url
        else "Mini App short name is not configured; this button opens the secure web review link."
    )
    button_text = 'Open Farmers Review Mini App' if mini_app_url else 'Open Farmers Review'
    return {
        'status': 'command',
        'reply_text': (
            "Farmers CSV ready for review\n"
            f"Rows extracted: {stats.get('total_rows', 0)}\n"
            f"Rows needing review: {stats.get('review_needed', 0)}\n"
            f"{launch_note}\n\n"
            "Correct any values, then commit approved rows."
        ),
        'reply_markup': {
            'inline_keyboard': [[
                {'text': button_text, 'url': launch_url}
            ]]
        },
    }


def _process_tat_tracker_command(group_config, sender: str, telegram_message_id: str) -> dict:
    from core.services.tat_tracker import build_tat_tracker_mini_app_url, build_tat_tracker_url

    form_url = build_tat_tracker_url(group_config.group_id)
    mini_app_url = build_tat_tracker_mini_app_url(group_config.group_id)
    if not form_url:
        return {
            'status': 'command',
            'reply_text': 'TAT Tracker URL is not configured. Set APP_BASE_URL and redeploy.',
        }

    if mini_app_url:
        button = {'text': 'Open TAT Tracker Mini App', 'url': mini_app_url}
        mode = 'Opening through the Telegram Mini App short link.'
    else:
        button = {'text': 'Open TAT Tracker', 'url': form_url}
        mode = 'Mini App short name is not configured; this button opens the secure web tracker link.'

    return {
        'status': 'command',
        'reply_text': (
            'TAT Tracker\n'
            'Use this to create cases, search cases, and update your assigned workflow stage.\n\n'
            f'{mode}'
        ),
        'reply_markup': {'inline_keyboard': [[button]]},
    }
def _process_spin_form_command(
    group_config,
    sender: str,
    telegram_message_id: str,
) -> dict:
    from core.services.spin_credit import build_spin_form_url, build_spin_mini_app_url

    form_url = build_spin_form_url(group_config.group_id)
    mini_app_url = build_spin_mini_app_url(group_config.group_id)
    launch_url = mini_app_url or form_url
    if not launch_url:
        return {
            'status': 'command',
            'reply_text': 'APP_BASE_URL is not configured; cannot open the SPIN/CRB form.',
        }
    launch_note = (
        'Opening as Telegram Mini App.'
        if mini_app_url
        else 'Mini App short name is not configured; this button opens the secure web form link.'
    )
    button_text = 'Open SPIN/CRB Mini App' if mini_app_url else 'Open SPIN/CRB Form'
    return {
        'status': 'command',
        'reply_text': (
            'SPIN/CRB request form is ready.\n'
            f'{launch_note}\n\n'
            'Use Request Type = SPIN/CRB for the normal credit analysis request. Choose only SPIN or only CRB for rare single-report requests.'
        ),
        'reply_markup': {
            'inline_keyboard': [[{'text': button_text, 'url': launch_url}]]
        },
    }

def _process_spin_batch_command(
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
                "Send the SPIN/CRB/Credit Analysis WhatsApp .txt or .zip export with:\n"
                "@bot /batch\n\n"
                "Supported request formats: labelled SPIN, inline SPIN + credit analysis, "
                "analysis-only, and CRB report requests."
            ),
        }

    document = message_data.get('document') or {}
    source_filename = str(document.get('file_name') or '').strip()
    from core.services.spin_credit import process_spin_batch_export

    return process_spin_batch_export(
        group_config=group_config,
        export_text=payload,
        telegram_message_id=telegram_message_id,
        sender=sender,
        source_filename=source_filename,
    )


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



def _process_fcaup_command(
    group_config,
    message_data: dict,
    sender: str,
    telegram_message_id: str,
) -> dict:
    files, document_error = _download_telegram_fca_documents(message_data)
    if document_error:
        return {'status': 'command', 'reply_text': document_error.replace('/batchfca', '/fcaup')}
    if not files:
        return {
            'status': 'command',
            'reply_text': (
                "Attach the agreed FCA Section A .xlsx workbook or a .zip containing FCA workbooks and send:\n"
                "@bot /fcaup\n\n"
                "The bot updates Master Data using ID NUMBER first, then PHONE. "
                "STATUS writes to Jawabu Comment After visit; COMMENT writes to Additional Comments."
            ),
        }

    from core.services.fca import process_fcaup_files

    return process_fcaup_files(
        group_config=group_config,
        files=files,
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



def _download_telegram_csv_document(message_data: dict) -> tuple[str, str, str]:
    document = message_data.get('document') or {}
    if not document:
        return '', '', ''

    filename = str(document.get('file_name') or '').strip() or 'farmers.csv'
    mime_type = str(document.get('mime_type') or '').lower()
    if not (filename.lower().endswith('.csv') or mime_type in {'text/csv', 'application/vnd.ms-excel', 'text/plain', 'application/octet-stream', ''}):
        return '', filename, 'The /farmup command only supports a Jawabu Farmers .csv attachment.'

    file_size = int(document.get('file_size') or 0)
    max_mb = max(1, int(getattr(settings, 'FARMUP_MAX_FILE_SIZE_MB', 5)))
    if file_size and file_size > max_mb * 1024 * 1024:
        return '', filename, f'Farmers CSV is too large. Maximum size is {max_mb} MB.'

    bot_token = settings.TELEGRAM_BOT_TOKEN
    file_id = document.get('file_id')
    if not bot_token or not file_id:
        return '', filename, 'Could not download the Farmers CSV from Telegram.'

    try:
        file_meta = requests.get(
            f'https://api.telegram.org/bot{bot_token}/getFile',
            params={'file_id': file_id},
            timeout=settings.API_REQUEST_TIMEOUT,
        )
        file_meta.raise_for_status()
        file_path = file_meta.json().get('result', {}).get('file_path', '')
        if not file_path:
            return '', filename, 'Telegram did not return a downloadable file path.'
        file_response = requests.get(
            f'https://api.telegram.org/file/bot{bot_token}/{file_path}',
            timeout=settings.API_REQUEST_TIMEOUT,
        )
        file_response.raise_for_status()
        raw = file_response.content
        if len(raw) > max_mb * 1024 * 1024:
            return '', filename, f'Farmers CSV is too large. Maximum size is {max_mb} MB.'
        for encoding in ('utf-8-sig', 'utf-8', 'cp1252'):
            try:
                return raw.decode(encoding), filename, ''
            except UnicodeDecodeError:
                continue
        return '', filename, 'Could not read the CSV text encoding. Export it as UTF-8 CSV and retry.'
    except requests.Timeout:
        logger.warning('Timed out downloading Telegram Farmers CSV')
        return '', filename, 'Timed out downloading the Farmers CSV. Please resend it.'
    except Exception as exc:
        logger.error('Failed to download Telegram Farmers CSV: %s', exc, exc_info=True)
        return '', filename, 'Could not download the Farmers CSV. Please resend it.'
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
    Run one message through dedup -> parse -> store -> sheet sync.

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
            # Return a generic error - don't expose the group_id to the caller
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
                sheet_id=sheet_id,       # forwarded to sheets service
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
            'complaint_status': 'Status',
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
            '- TEL or ID\n'
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
                f"New cases created: {result.get('new_cases_created', saved)}",
            ]
            existing_matched = result.get('existing_cases_matched', 0)
            if existing_matched:
                lines.append(f"Existing cases matched: {existing_matched}")
                lines.append(f"Already synchronized: {result.get('already_synchronized', 0)}")
                lines.append(f"Synchronization retried: {result.get('synchronization_retried', 0)}")
                lines.append(f"Synchronization succeeded: {result.get('synchronization_succeeded', 0)}")
                lines.append(f"Synchronization failed: {result.get('synchronization_failed', 0)}")
            skipped = result.get('skipped_non_complaint', 0)
            if skipped:
                lines.append(f"Skipped non-complaint chat messages: {skipped}")
            system_lines = result.get('system_lines', 0)
            if system_lines:
                lines.append(f"Skipped WhatsApp system lines: {system_lines}")
            review_needed = result.get('review_needed', 0)
            if review_needed:
                lines.append(f"Saved for manual review: {review_needed}")
            if result.get('truncated'):
                lines.append(
                    f"Processed the first {result.get('max_entries')} export messages because a limit is configured. "
                    "Set WHATSAPP_BATCH_MAX_MESSAGES=0 to process the full export in one upload."
                )
            append_sync = result.get('batch_sheet_append') or {}
            if append_sync:
                append_status = append_sync.get('status', 'unknown')
                lines.append(
                    f"Sheet batch write: {append_status} "
                    f"({append_sync.get('synced_count', 0)} synced, "
                    f"{append_sync.get('failed_count', 0)} failed)"
                )
                append_errors = append_sync.get('errors') or []
                if append_errors:
                    lines.append(f"Sheet batch write warning: {append_errors[0]}")
            for label, key in (
                ('Sheet sync before import', 'sheet_sync_before'),
                ('Sheet sync after import', 'sheet_sync_after'),
            ):
                sync = result.get(key)
                if not sync:
                    continue
                status_text = sync.get('status', 'unknown')
                row_count = sync.get('row_count')
                backend_count = sync.get('backend_count')
                row_text = 'not read' if row_count is None else str(row_count)
                backend_text = 'not evaluated' if backend_count is None else str(backend_count)
                lines.append(
                    f"{label}: {status_text} "
                    f"({row_text} sheet rows, "
                    f"{backend_text} backend cases)"
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
            lines.append('Each complaint must include NAME, TEL or ID, and NATURE OF THE PROBLEM.')

        text = "\n".join(lines)
    elif status == 'spin_batch_processed':
        lines = [
            "SPIN / Credit Analysis import processed",
            f"Export messages found: {result.get('export_messages', 0)}",
            f"SPIN-related candidates: {result.get('spin_candidates', 0)}",
            f"Valid SPIN requests: {result.get('valid_requests', result.get('processed', 0))}",
            f"Incomplete SPIN requests: {result.get('incomplete_requests', 0)}",
            f"Ambiguous messages: {result.get('ambiguous_messages', 0)}",
            f"Request messages processed: {result.get('processed', 0)}",
            f"Imported: {result.get('imported', 0)}",
            f"Needs review: {result.get('review_needed', 0)}",
            f"Duplicates skipped: {result.get('duplicates', 0)}",
            f"Failed: {result.get('failed', 0)}",
        ]
        skipped = result.get('skipped', 0)
        if skipped:
            lines.append(f"Skipped other chat messages: {skipped}")
        progress_events = result.get('progress_events', 0)
        if progress_events:
            lines.append(f"Progress replies detected: {progress_events}")
            lines.append(f"Linked to requests: {result.get('linked_progress_events', 0)}")
        sheet_sync = result.get('sheet_sync') or {}
        if sheet_sync:
            sheet_name = sheet_sync.get('sheet_name')
            if sheet_name:
                lines.append(f"Legacy sheet: {sheet_name}")
            if sheet_sync.get('success'):
                lines.append(f"Sheet sync: appended {len(sheet_sync.get('row_numbers') or [])} row(s)")
            else:
                lines.append(f"Sheet sync failed: {sheet_sync.get('error') or 'unknown error'}")
        review_items = result.get('review_items') or []
        if review_items:
            lines.extend(['', 'Review needed'])
            for index, item in enumerate(review_items[:5], start=1):
                missing = ', '.join(item.get('missing_fields') or [])
                label = item.get('customer_name') or item.get('national_id') or item.get('primary_phone') or 'Unknown customer'
                lines.append(f"{index}. {label} - missing {missing or 'required fields'}")
        incomplete_items = result.get('incomplete_items') or []
        if incomplete_items:
            lines.extend(['', 'Incomplete SPIN-related messages'])
            for index, item in enumerate(incomplete_items[:5], start=1):
                keywords = ', '.join(item.get('keywords') or [])
                reason = item.get('reason') or 'Missing customer or loan details'
                lines.append(f"{index}. {reason} ({keywords or 'keyword matched'})")
        ambiguous_items = result.get('ambiguous_items') or []
        if ambiguous_items:
            lines.extend(['', 'Ambiguous customer/loan messages'])
            for index, item in enumerate(ambiguous_items[:5], start=1):
                fields = ', '.join((item.get('identifier_fields') or []) + (item.get('loan_detail_fields') or []))
                lines.append(f"{index}. Details found without SPIN keyword: {fields or 'unknown details'}")
        duplicates = result.get('duplicates_list') or []
        if duplicates:
            lines.extend(['', 'Duplicate source messages skipped'])
            for index, item in enumerate(duplicates[:5], start=1):
                label = item.get('customer_name') or item.get('national_id') or item.get('primary_phone') or 'Unknown customer'
                lines.append(f"{index}. {label}")
        if result.get('message'):
            lines.extend(['', str(result['message'])])
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
    elif status == 'fcaup_review_ready':
        lines = [
            "FCA upload ready for review",
            f"Files read: {result.get('files', 0)}",
            f"Section A rows extracted: {result.get('processed', 0)}",
            f"Rows needing review: {result.get('review_needed', 0)}",
            "Open the review form, correct values, then commit approved rows.",
        ]
        errors = [error for error in (result.get('errors') or []) if error]
        if errors:
            lines.extend(["", "Warnings"])
            lines.extend(f"- {error}" for error in errors[:5])
        _post_telegram_reply(
            chat_id,
            message_data,
            "\n".join(lines),
            reply_markup=result.get('reply_markup'),
        )
        return
    elif status == 'fcaup_processed':
        lines = [
            "FCA Master Data update processed",
            f"Files read: {result.get('files', 0)}",
            f"Section A rows processed: {result.get('processed', 0)}",
            f"MD rows updated: {result.get('updated', 0)}",
            f"MD rows created: {result.get('created', 0)}",
            f"Review needed: {result.get('review_needed', 0)}",
            f"Failed: {result.get('failed', 0)}",
        ]
        if result.get('duplicates'):
            lines.append(f"Duplicate MD matches: {result.get('duplicates')}")
        if result.get('sheet_tab'):
            lines.append(f"Master tab: {result.get('sheet_tab')}")
        status_counts = result.get('status_counts') or {}
        if status_counts:
            lines.extend(["", "Statuses imported"])
            for key, count in sorted(status_counts.items()):
                lines.append(f"- {key}: {count}")
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
        response = requests.post(
            url,
            data=data,
            timeout=settings.API_REQUEST_TIMEOUT,
        )
        if not response.ok:
            logger.warning(
                "Telegram reply failed for chat %s: %s %s",
                chat_id,
                response.status_code,
                response.text[:500],
            )
            if reply_markup:
                fallback_data = data.copy()
                fallback_data.pop('reply_markup', None)
                fallback = requests.post(
                    url,
                    data=fallback_data,
                    timeout=settings.API_REQUEST_TIMEOUT,
                )
                if not fallback.ok:
                    logger.warning(
                        "Telegram plain reply fallback failed for chat %s: %s %s",
                        chat_id,
                        fallback.status_code,
                        fallback.text[:500],
                    )
    except requests.Timeout:
        logger.warning(f"Timeout sending Telegram reply to chat {chat_id}")
    except Exception as exc:
        logger.error(f"Failed to send Telegram reply: {exc}")


# ---------------------------------------------------------------------------
# Manual batch processing
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
                "group_id": "-1001234567890"   # optional
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

            # KEY FIX: pass group_id from the request (or fallback)
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


def _looks_like_portal_command(content: str) -> bool:
    return bool(re.match(r'^/portal(?:@\w+)?(?:\s|$)', str(content or '').strip(), re.IGNORECASE))


def _process_portal_command(
    group_config,
    sender: str,
    telegram_message_id: str,
) -> dict:
    from django.conf import settings
    bot_username = str(getattr(settings, 'TELEGRAM_BOT_USERNAME', '') or '').strip().lstrip('@')
    short_name = str(getattr(settings, 'PORTAL_MINI_APP_SHORT_NAME', '') or '').strip().strip('/')
    base_url = getattr(settings, 'APP_BASE_URL', '').rstrip('/')

    if bot_username and short_name:
        launch_url = f"https://t.me/{bot_username}/{short_name}"
    else:
        if not base_url:
            return {
                'status': 'command',
                'reply_text': 'APP_BASE_URL is not configured; cannot open the Pipeline Portal.',
            }
        launch_url = f"{base_url}/api/portal/"

    return {
        'status': 'command',
        'reply_text': (
            "JBL Pipeline Portal is ready.\n"
            "Use the portal to view/update JBL visits, credit decisions, and requisition numbers."
        ),
        'reply_markup': {
            'inline_keyboard': [[
                {'text': 'Open Pipeline Portal', 'url': launch_url}
            ]]
        },
    }
