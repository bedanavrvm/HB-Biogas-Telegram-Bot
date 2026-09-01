"""HTTP boundary for the group-scoped Complaint Cases Telegram Mini App."""
from __future__ import annotations

import json
import logging
from functools import wraps

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from core.services.complaint_cases import (
    ComplaintCaseConflict,
    ComplaintCaseError,
    actor_can_access_case,
    actor_can,
    bootstrap_data,
    case_detail,
    complete_review_details,
    create_complaint_case,
    decode_complaint_start_param,
    evidence_for_preview,
    is_complaint_workflow,
    complaint_sheet_projection_enabled,
    list_cases_page,
    reopen_case,
    record_evidence_preview,
    resolve_case,
    retry_case_sync,
    staff_actor_for_user,
    suggest_category,
    update_case,
)
from core.services.group_config import GroupRegistry
from core.services.order_approval import GoogleDriveMediaStorage


logger = logging.getLogger(__name__)


def _bind_miniapp_write_request(request, payload: dict):
    from core.services.miniapp_requests import (
        bind_miniapp_request_identity,
        idempotency_error_response,
    )
    try:
        bind_miniapp_request_identity(request, payload)
    except ValueError as exc:
        return idempotency_error_response(exc, request)
    return None


def miniapp_write_response(view_func):
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        from core.services.miniapp_requests import (
            attach_miniapp_request_metadata,
            bind_miniapp_write_request,
            idempotency_error_response,
        )
        from core.services.miniapp_messages import normalize_miniapp_response, unexpected_miniapp_error
        try:
            bind_miniapp_write_request(request)
        except ValueError as exc:
            response = idempotency_error_response(exc, request)
        else:
            try:
                response = view_func(request, *args, **kwargs)
            except Exception as exc:
                logger.exception('Complaint Mini App request failed unexpectedly: path=%s', request.path)
                response = unexpected_miniapp_error(request, exc, workflow="complaints")
        response = attach_miniapp_request_metadata(request, response)
        return normalize_miniapp_response(request, response, workflow="complaints")
    return wrapped


@require_http_methods(['GET'])
def complaint_cases_app(request):
    """Render a shell only; every case API action still verifies Telegram identity."""
    start_payload = decode_complaint_start_param(
        request.GET.get('tgWebAppStartParam') or request.GET.get('startapp') or ''
    )
    return render(
        request,
        'complaint_cases/app.html',
        {'group_id': request.GET.get('group_id') or start_payload.get('group_id', '')},
    )


def _json_body(request) -> dict:
    try:
        return json.loads(request.body.decode('utf-8') or '{}')
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}


def _request_payload(request) -> dict:
    return request.POST.dict() if request.content_type.startswith('multipart/') else _json_body(request)


def _context(request, payload: dict):
    init_data = request.headers.get('X-Telegram-Init-Data', '') or payload.get('init_data', '')
    require_auth = bool(
        getattr(settings, 'COMPLAINT_CASES_WEBAPP_REQUIRE_TELEGRAM_AUTH', True)
    )
    identity = None
    canonical_user = None
    if require_auth:
        from core.services.telegram_identity import (
            TelegramAuthenticationError,
            resolve_or_bind_telegram_user,
            validate_telegram_init_data,
        )
        try:
            _auth_payload, identity = validate_telegram_init_data(
                init_data,
                max_age_seconds=int(getattr(
                    settings, 'COMPLAINT_CASES_WEBAPP_AUTH_MAX_AGE_SECONDS', 86400,
                )),
            )
        except TelegramAuthenticationError as exc:
            return None, None, JsonResponse({'ok': False, 'error': str(exc)}, status=403)
        canonical_user = resolve_or_bind_telegram_user(identity)
    else:
        from core.services.telegram_auth import authentication_bypass_allowed

        if not authentication_bypass_allowed():
            return None, None, JsonResponse({
                'ok': False,
                'error': 'Telegram Mini App authentication can only be disabled in an explicit local or test runtime.',
            }, status=403)
        if getattr(request.user, 'is_authenticated', False) and request.user.is_active:
            canonical_user = request.user
        else:
            return None, None, JsonResponse({
                'ok': False,
                'error': 'Sign in with a local Django test user before using authentication-disabled mode.',
            }, status=403)
    group_id = str(payload.get('group_id') or '').strip()
    group_config = GroupRegistry.get_instance().get_group(group_id)
    if not group_config or not is_complaint_workflow(group_config):
        return None, None, JsonResponse(
            {'ok': False, 'error': 'Complaint Cases is not configured for this Telegram group.'},
            status=403,
        )
    try:
        return group_config, staff_actor_for_user(
            group_config, canonical_user, identity=identity,
        ), None
    except ComplaintCaseError as exc:
        return None, None, JsonResponse({'ok': False, 'error': str(exc)}, status=403)


def _capability_error(actor, capability: str, group_config, *, resource=None, branch: str = ''):
    from core.services.workflow_access import workflow_access_decision
    decision = workflow_access_decision(
        actor.user, 'complaint_cases', capability, access=actor.access,
        group_configuration=group_config, resource=resource, branch=branch,
    )
    if not decision.allowed:
        return JsonResponse({'ok': False, 'error': 'Your assigned complaint-case role does not permit this action.'}, status=403)
    from core.services.access_control import record_capability_usage
    record_capability_usage(actor.user, 'complaint_cases', capability)
    return None


@csrf_exempt  # Verified Telegram initData is the non-cookie authentication mechanism.
@require_http_methods(['POST'])
@miniapp_write_response
def complaint_cases_bootstrap(request):
    payload = _request_payload(request)
    group_config, actor, error = _context(request, payload)
    if error:
        return error
    capability_error = _capability_error(actor, 'complaint.queue.view', group_config)
    if capability_error:
        return capability_error
    from core.services.access_control import policy_version
    from core.services.miniapp_settings import account_summary_payload, preference_payload
    from core.services.telegram_identity import user_access
    data = bootstrap_data(group_config, actor)
    data['access_policy_version'] = policy_version()
    data['personal'] = preference_payload(actor.user, 'complaint_cases')
    access = user_access(actor.user, 'complaint_cases', group_configuration=group_config)
    data['account'] = account_summary_payload(
        actor.user,
        'complaint_cases',
        roles=access.get('roles') or [],
        branches=access.get('branches') or [],
        products=access.get('products') or [],
    )
    return JsonResponse({'ok': True, 'data': data})


@csrf_exempt  # Verified Telegram initData is the non-cookie authentication mechanism.
@require_http_methods(['POST'])
@miniapp_write_response
def complaint_cases_category_suggestion(request):
    payload = _request_payload(request)
    group_config, actor, error = _context(request, payload)
    if error:
        return error
    capability_error = _capability_error(actor, 'complaint.queue.view', group_config)
    if capability_error:
        return capability_error
    return JsonResponse({
        'ok': True,
        'data': suggest_category(group_config, payload.get('description')),
    })


@csrf_exempt  # Verified Telegram initData is the non-cookie authentication mechanism.
@require_http_methods(['POST'])
@miniapp_write_response
def complaint_cases_settings_personal(request):
    """Persist only the authenticated officer's Complaint Case preferences."""
    payload = _request_payload(request)
    key_error = _bind_miniapp_write_request(request, payload)
    if key_error:
        return key_error
    group_config, actor, error = _context(request, payload)
    if error:
        return error
    capability_error = _capability_error(actor, 'complaint.queue.view', group_config)
    if capability_error:
        return capability_error
    from core.services.miniapp_settings import update_preference
    try:
        return JsonResponse({'ok': True, 'data': update_preference(actor.user, 'complaint_cases', payload.get('preferences') or {})})
    except ValueError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)


@csrf_exempt  # Verified Telegram initData is the non-cookie authentication mechanism.
@require_http_methods(['POST'])
@miniapp_write_response
def complaint_cases_list(request):
    payload = _request_payload(request)
    group_config, actor, error = _context(request, payload)
    if error:
        return error
    capability_error = _capability_error(actor, 'complaint.queue.view', group_config)
    if capability_error:
        return capability_error
    try:
        result = list_cases_page(
            group_config, actor,
            query=str(payload.get('query') or ''), status=str(payload.get('status') or 'pending'),
            cursor=str(payload.get('cursor') or ''), limit=10,
            page=payload.get('page') if 'page' in payload else None, page_size=10,
        )
    except ComplaintCaseError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    return JsonResponse({
        'ok': True,
        'cases': result['items'],
        'next_cursor': result['next_cursor'],
        'pagination': result.get('pagination'),
        'start_index': result.get('start_index', 0),
    })


@csrf_exempt  # Verified Telegram initData is the non-cookie authentication mechanism.
@require_http_methods(['POST'])
@miniapp_write_response
def complaint_cases_list_fragment(request):
    payload = _request_payload(request)
    group_config, actor, error = _context(request, payload)
    if error:
        return error
    capability_error = _capability_error(actor, 'complaint.queue.view', group_config)
    if capability_error:
        return capability_error
    try:
        result = list_cases_page(
            group_config, actor,
            query=str(payload.get('query') or ''), status=str(payload.get('status') or 'pending'),
            page=payload.get('page') or 1, page_size=10,
        )
    except ComplaintCaseError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    return render(request, 'complaint_cases/partials/case_list.html', {
        'cases': result['items'],
        'next_cursor': result['next_cursor'],
        'start_index': result.get('start_index', 0),
        'pagination': result.get('pagination'),
    })


@csrf_exempt  # Verified Telegram initData is the non-cookie authentication mechanism.
@require_http_methods(['POST'])
@miniapp_write_response
def complaint_cases_global_overview(request):
    payload = _request_payload(request)
    group_config, actor, error = _context(request, payload)
    if error:
        return error
    capability_error = _capability_error(actor, 'complaint.queue.view', group_config)
    if capability_error:
        return capability_error
    from core.services.complaint_register import register_overview
    return JsonResponse({'ok': True, 'data': register_overview()})


@csrf_exempt  # Verified Telegram initData is the non-cookie authentication mechanism.
@require_http_methods(['POST'])
@miniapp_write_response
def complaint_cases_global_list(request):
    payload = _request_payload(request)
    group_config, actor, error = _context(request, payload)
    if error:
        return error
    capability_error = _capability_error(actor, 'complaint.queue.view', group_config)
    if capability_error:
        return capability_error
    from core.services.complaint_register import register_page
    try:
        result = register_page(
            filters=payload.get('filters') or {}, page=payload.get('page') or 1,
            page_size=50, sort=str(payload.get('sort') or '-reported_at'),
        )
    except ComplaintCaseError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    return JsonResponse({'ok': True, **result})


def _global_target_actions(actor, item: dict) -> dict[str, bool]:
    """Re-resolve target-group grants; launch-group authority never leaks into writes."""
    from core.models import GroupSheetConfiguration
    from core.services.group_config import GroupConfig

    row = GroupSheetConfiguration.objects.filter(group_id=item['group_id'], enabled=True).first()
    if not row or str((row.workflow or {}).get('type') or 'case') != 'case':
        return {'close': False, 'reopen': False, 'complete_details': False, 'sync_retry': False}
    target_config = GroupConfig(**row.as_group_config_kwargs())
    try:
        target_actor = staff_actor_for_user(target_config, actor.user)
    except ComplaintCaseError:
        return {'close': False, 'reopen': False, 'complete_details': False, 'sync_retry': False}
    return {
        'close': actor_can(target_config, target_actor, 'complaint.case.close'),
        'reopen': actor_can(target_config, target_actor, 'complaint.case.reopen'),
        'complete_details': actor_can(target_config, target_actor, 'complaint.case.details.complete'),
        'sync_retry': (
            complaint_sheet_projection_enabled(target_config)
            and actor_can(target_config, target_actor, 'complaint.case.sync.retry')
        ),
    }


@csrf_exempt  # Verified Telegram initData is the non-cookie authentication mechanism.
@require_http_methods(['POST'])
@miniapp_write_response
def complaint_cases_global_detail(request, case_uuid):
    payload = _request_payload(request)
    group_config, actor, error = _context(request, payload)
    if error:
        return error
    capability_error = _capability_error(actor, 'complaint.queue.view', group_config)
    if capability_error:
        return capability_error
    from core.services.complaint_register import register_case
    try:
        item = register_case(str(case_uuid))
    except ComplaintCaseError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=404)
    item['actions'] = _global_target_actions(actor, item)
    return JsonResponse({'ok': True, 'case': item})


@csrf_exempt  # Verified Telegram initData is the non-cookie authentication mechanism.
@require_http_methods(['POST'])
@miniapp_write_response
def complaint_cases_global_export(request):
    payload = _request_payload(request)
    key_error = _bind_miniapp_write_request(request, payload)
    if key_error:
        return key_error
    group_config, actor, error = _context(request, payload)
    if error:
        return error
    capability_error = _capability_error(actor, 'complaint.case.export', group_config)
    if capability_error:
        return capability_error
    if payload.get('confirm_all') is not True:
        return JsonResponse({
            'ok': False,
            'code': 'export_confirmation_required',
            'message': 'Confirm that you intend to export every complaint case across all groups.',
        }, status=400)
    from core.services.complaint_register import export_filename, export_register_xlsx
    try:
        workbook, row_count = export_register_xlsx(
            actor=actor.user,
            request_id=str(payload.get('client_request_id') or request.headers.get('X-Request-ID') or ''),
        )
    except Exception:
        logger.exception('Global Complaint Cases export failed for user %s.', actor.user.pk)
        return JsonResponse({'ok': False, 'error': 'The complaint register could not be exported. Try again.'}, status=500)
    response = HttpResponse(
        workbook,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{export_filename()}"'
    response['X-Export-Row-Count'] = str(row_count)
    return response


@csrf_exempt  # Verified Telegram initData is the non-cookie authentication mechanism.
@require_http_methods(['POST'])
@miniapp_write_response
def complaint_cases_create(request):
    payload = _request_payload(request)
    key_error = _bind_miniapp_write_request(request, payload)
    if key_error:
        return key_error
    group_config, actor, error = _context(request, payload)
    if error:
        return error
    capability_error = _capability_error(actor, 'complaint.case.create', group_config)
    if capability_error:
        return capability_error
    try:
        result = create_complaint_case(
            group_config,
            actor,
            payload,
            request.FILES.getlist('evidence'),
        )
    except ComplaintCaseError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    except Exception:
        logger.exception('Complaint case creation failed for group %s.', group_config.group_id)
        return JsonResponse({'ok': False, 'error': 'The complaint could not be created. Try again.'}, status=500)
    if not actor_can_access_case(group_config, actor, 'complaint.case.source.view', result['case']['case_id']):
        result['case'].pop('raw_message', None)
    message = 'Complaint created.' if result['created'] else 'Existing complaint opened.'
    if result['sheet_projection_enabled'] and not result['synced_to_sheet']:
        message += ' The Sheet sync is pending.'
    return JsonResponse({'ok': True, 'case': result['case'], 'message': message}, status=201 if result['created'] else 200)


@csrf_exempt  # Verified Telegram initData is the non-cookie authentication mechanism.
@require_http_methods(['POST'])
@miniapp_write_response
def complaint_cases_detail(request, case_id: str):
    payload = _request_payload(request)
    group_config, actor, error = _context(request, payload)
    if error:
        return error
    capability_error = _capability_error(actor, 'complaint.queue.view', group_config)
    if capability_error:
        return capability_error
    try:
        detail = case_detail(group_config, case_id, actor)
    except ComplaintCaseError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=404)
    if not actor_can_access_case(group_config, actor, 'complaint.case.source.view', case_id):
        detail.pop('raw_message', None)
    return JsonResponse({'ok': True, 'case': detail})


@csrf_exempt  # Verified Telegram initData is the non-cookie authentication mechanism.
@require_http_methods(['POST'])
@miniapp_write_response
def complaint_cases_update(request, case_id: str):
    """Temporary cached-client transition endpoint."""
    payload = _request_payload(request)
    key_error = _bind_miniapp_write_request(request, payload)
    if key_error:
        return key_error
    group_config, actor, error = _context(request, payload)
    if error:
        return error
    capability_error = _capability_error(actor, 'complaint.case.update', group_config)
    if capability_error:
        return capability_error
    try:
        result = update_case(
            group_config,
            actor,
            case_id,
            payload,
            request.FILES.getlist('evidence'),
        )
    except ComplaintCaseConflict as exc:
        return _conflict_response(group_config, actor, case_id, exc)
    except ComplaintCaseError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    except Exception:
        logger.exception('Complaint case update failed for group %s case %s.', group_config.group_id, case_id)
        return JsonResponse({'ok': False, 'error': 'The case update could not be saved. Try again.'}, status=500)
    if not actor_can_access_case(group_config, actor, 'complaint.case.source.view', case_id):
        result.pop('raw_message', None)
    logger.warning(
        'Deprecated complaint update endpoint used for case %s by user %s.',
        case_id, actor.user.pk,
    )
    response = JsonResponse({'ok': True, 'case': result, 'message': 'Case transition saved.'})
    response['Deprecation'] = 'true'
    return response


@csrf_exempt  # Verified Telegram initData is the non-cookie authentication mechanism.
@require_http_methods(['POST'])
@miniapp_write_response
def complaint_cases_complete_details(request, case_id: str):
    payload = _request_payload(request)
    key_error = _bind_miniapp_write_request(request, payload)
    if key_error:
        return key_error
    group_config, actor, error = _context(request, payload)
    if error:
        return error
    capability_error = _capability_error(actor, 'complaint.case.details.complete', group_config)
    if capability_error:
        return capability_error
    try:
        result = complete_review_details(group_config, actor, case_id, payload)
    except ComplaintCaseConflict as exc:
        return _conflict_response(group_config, actor, case_id, exc)
    except ComplaintCaseError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    except Exception:
        logger.exception('Complaint detail completion failed for group %s case %s.', group_config.group_id, case_id)
        return JsonResponse({'ok': False, 'error': 'The complaint details could not be saved. Try again.'}, status=500)
    return JsonResponse({'ok': True, 'case': result, 'message': 'Required details completed.'})


def _conflict_response(group_config, actor, case_id: str, exc: ComplaintCaseConflict):
    current = case_detail(group_config, case_id, actor)
    current.pop('raw_message', None)
    return JsonResponse({
        'ok': False,
        'error': str(exc),
        'code': 'revision_conflict',
        'current_revision': exc.current_revision,
        'current_case': current,
    }, status=409)


@csrf_exempt
@require_http_methods(['POST'])
@miniapp_write_response
def complaint_cases_resolve(request, case_id: str):
    payload = _request_payload(request)
    key_error = _bind_miniapp_write_request(request, payload)
    if key_error:
        return key_error
    group_config, actor, error = _context(request, payload)
    if error:
        return error
    capability_error = _capability_error(actor, 'complaint.case.close', group_config)
    if capability_error:
        return capability_error
    try:
        result = resolve_case(group_config, actor, case_id, payload, request.FILES.getlist('evidence'))
    except ComplaintCaseConflict as exc:
        return _conflict_response(group_config, actor, case_id, exc)
    except ComplaintCaseError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    except Exception:
        logger.exception('Complaint resolution failed for group %s case %s.', group_config.group_id, case_id)
        return JsonResponse({'ok': False, 'error': 'The resolution could not be saved. Try again.'}, status=500)
    return JsonResponse({'ok': True, 'case': result, 'message': 'Complaint resolved.'})


@csrf_exempt
@require_http_methods(['POST'])
@miniapp_write_response
def complaint_cases_reopen(request, case_id: str):
    payload = _request_payload(request)
    key_error = _bind_miniapp_write_request(request, payload)
    if key_error:
        return key_error
    group_config, actor, error = _context(request, payload)
    if error:
        return error
    capability_error = _capability_error(actor, 'complaint.case.reopen', group_config)
    if capability_error:
        return capability_error
    try:
        result = reopen_case(group_config, actor, case_id, payload)
    except ComplaintCaseConflict as exc:
        return _conflict_response(group_config, actor, case_id, exc)
    except ComplaintCaseError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    except Exception:
        logger.exception('Complaint reopen failed for group %s case %s.', group_config.group_id, case_id)
        return JsonResponse({'ok': False, 'error': 'The complaint could not be reopened. Try again.'}, status=500)
    return JsonResponse({'ok': True, 'case': result, 'message': 'Complaint returned to the Pending queue.'})


@csrf_exempt  # Verified Telegram initData is the non-cookie authentication mechanism.
@require_http_methods(['POST'])
@miniapp_write_response
def complaint_cases_evidence_access(request, evidence_id: str):
    payload = _request_payload(request)
    group_config, actor, error = _context(request, payload)
    if error:
        return error
    capability_error = _capability_error(actor, 'complaint.case.evidence.view', group_config)
    if capability_error:
        return capability_error
    try:
        evidence = evidence_for_preview(group_config, actor, evidence_id)
    except ComplaintCaseError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=404)
    try:
        content = GoogleDriveMediaStorage().download(evidence.drive_file_id)
    except Exception:
        logger.exception('Could not stream complaint evidence %s.', evidence.pk)
        return JsonResponse({
            'ok': False,
            'error': 'The evidence could not be loaded from secure storage. Please retry shortly.',
        }, status=503)

    mime_type = str(evidence.mime_type or '').lower().split(';', 1)[0]
    if mime_type == 'application/pdf':
        try:
            from core.services.secure_media_preview import pdf_preview_html

            content = pdf_preview_html(content, evidence.original_filename or 'Complaint evidence.pdf')
            mime_type = 'text/html; charset=utf-8'
        except Exception:
            logger.exception('Could not prepare complaint PDF evidence %s.', evidence.pk)
            return JsonResponse({
                'ok': False,
                'error': 'This PDF could not be prepared for in-app viewing. Please retry shortly.',
            }, status=503)

    record_evidence_preview(group_config, actor, evidence)
    from django.utils.http import content_disposition_header

    response = HttpResponse(content, content_type=mime_type)
    response['Content-Disposition'] = content_disposition_header(
        False, evidence.original_filename or 'complaint-evidence'
    )
    response['Cache-Control'] = 'private, no-store, max-age=0'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@csrf_exempt  # Verified Telegram initData is the non-cookie authentication mechanism.
@require_http_methods(['POST'])
@miniapp_write_response
def complaint_cases_sync_retry(request, case_id: str):
    payload = _request_payload(request)
    key_error = _bind_miniapp_write_request(request, payload)
    if key_error:
        return key_error
    group_config, actor, error = _context(request, payload)
    if error:
        return error
    capability_error = _capability_error(actor, 'complaint.case.sync.retry', group_config)
    if capability_error:
        return capability_error
    try:
        detail = retry_case_sync(group_config, actor, case_id)
    except ComplaintCaseError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    return JsonResponse({'ok': True, 'case': detail, 'message': 'Complaint register publication retried.'})
