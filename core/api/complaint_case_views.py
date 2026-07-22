"""HTTP boundary for the group-scoped Complaint Cases Telegram Mini App."""
from __future__ import annotations

import json
import logging

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from core.services.complaint_cases import (
    ComplaintCaseError,
    bootstrap_data,
    case_detail,
    create_complaint_case,
    decode_complaint_start_param,
    is_complaint_workflow,
    list_cases,
    staff_actor_for_payload,
    update_case,
)
from core.services.group_config import GroupRegistry
from core.services.telegram_auth import validate_telegram_init_data


logger = logging.getLogger(__name__)


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
    valid, error, auth_payload = validate_telegram_init_data(
        init_data,
        require_auth=getattr(settings, 'COMPLAINT_CASES_WEBAPP_REQUIRE_TELEGRAM_AUTH', True),
        max_age_seconds=getattr(settings, 'COMPLAINT_CASES_WEBAPP_AUTH_MAX_AGE_SECONDS', 86400),
    )
    if not valid:
        return None, None, JsonResponse({'ok': False, 'error': error}, status=403)
    group_id = str(payload.get('group_id') or '').strip()
    group_config = GroupRegistry.get_instance().get_group(group_id)
    if not group_config or not is_complaint_workflow(group_config):
        return None, None, JsonResponse(
            {'ok': False, 'error': 'Complaint Cases is not configured for this Telegram group.'},
            status=403,
        )
    try:
        return group_config, staff_actor_for_payload(group_config, auth_payload), None
    except ComplaintCaseError as exc:
        return None, None, JsonResponse({'ok': False, 'error': str(exc)}, status=403)


@csrf_exempt  # Verified Telegram initData is the non-cookie authentication mechanism.
@require_http_methods(['POST'])
def complaint_cases_bootstrap(request):
    payload = _request_payload(request)
    group_config, actor, error = _context(request, payload)
    if error:
        return error
    return JsonResponse({'ok': True, 'data': bootstrap_data(group_config, actor)})


@csrf_exempt  # Verified Telegram initData is the non-cookie authentication mechanism.
@require_http_methods(['POST'])
def complaint_cases_list(request):
    payload = _request_payload(request)
    group_config, actor, error = _context(request, payload)
    if error:
        return error
    del actor
    return JsonResponse(
        {
            'ok': True,
            'cases': list_cases(
                group_config,
                query=str(payload.get('query') or ''),
                status=str(payload.get('status') or 'active'),
                branch=str(payload.get('branch') or ''),
            ),
        }
    )


@csrf_exempt  # Verified Telegram initData is the non-cookie authentication mechanism.
@require_http_methods(['POST'])
def complaint_cases_list_fragment(request):
    payload = _request_payload(request)
    group_config, actor, error = _context(request, payload)
    if error:
        return error
    del actor
    cases = list_cases(
        group_config,
        query=str(payload.get('query') or ''),
        status=str(payload.get('status') or 'active'),
        branch=str(payload.get('branch') or ''),
    )
    return render(request, 'complaint_cases/partials/case_list.html', {'cases': cases})


@csrf_exempt  # Verified Telegram initData is the non-cookie authentication mechanism.
@require_http_methods(['POST'])
def complaint_cases_create(request):
    payload = _request_payload(request)
    group_config, actor, error = _context(request, payload)
    if error:
        return error
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
    if not actor.is_manager:
        result['case'].pop('raw_message', None)
    message = 'Complaint created.' if result['created'] else 'Existing complaint opened.'
    if not result['synced_to_sheet']:
        message += ' The Sheet sync is pending.'
    return JsonResponse({'ok': True, 'case': result['case'], 'message': message}, status=201 if result['created'] else 200)


@csrf_exempt  # Verified Telegram initData is the non-cookie authentication mechanism.
@require_http_methods(['POST'])
def complaint_cases_detail(request, case_id: str):
    payload = _request_payload(request)
    group_config, actor, error = _context(request, payload)
    if error:
        return error
    try:
        detail = case_detail(group_config, case_id)
    except ComplaintCaseError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=404)
    if not actor.is_manager:
        detail.pop('raw_message', None)
    return JsonResponse({'ok': True, 'case': detail})


@csrf_exempt  # Verified Telegram initData is the non-cookie authentication mechanism.
@require_http_methods(['POST'])
def complaint_cases_update(request, case_id: str):
    payload = _request_payload(request)
    group_config, actor, error = _context(request, payload)
    if error:
        return error
    try:
        result = update_case(
            group_config,
            actor,
            case_id,
            payload,
            request.FILES.getlist('evidence'),
        )
    except ComplaintCaseError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    except Exception:
        logger.exception('Complaint case update failed for group %s case %s.', group_config.group_id, case_id)
        return JsonResponse({'ok': False, 'error': 'The case update could not be saved. Try again.'}, status=500)
    if not actor.is_manager:
        result.pop('raw_message', None)
    return JsonResponse({'ok': True, 'case': result, 'message': 'Case update saved.'})
