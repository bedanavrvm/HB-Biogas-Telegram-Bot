from __future__ import annotations

from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from core.api.portal_views import (
    _portal_capability_error,
    _portal_request_data,
    _portal_request_id,
    portal_auth_required,
)

from .models import HomeBiogasAction
from .services import (
    CORRECT_CAPABILITY,
    VIEW_CAPABILITY,
    WRITE_CAPABILITY,
    HomeBiogasActionError,
    correct_action,
    scoped_actions,
    serialize_action,
    transition_action,
)


def _actor(request):
    return getattr(request, 'portal_user', None) or (request.user if getattr(request.user, 'is_authenticated', False) else None)


def _error(message: str, *, status: int = 400, code: str = 'invalid_request'):
    return JsonResponse({'ok': False, 'error': str(message), 'code': code}, status=status)


def _action_for_request(request, farmer_id, capability):
    return scoped_actions(
        _actor(request), getattr(request, 'portal_access', None), capability,
    ).filter(farmer_id=farmer_id).first()


@portal_auth_required
@require_http_methods(['GET'])
def hb_action_list(request):
    denied = _portal_capability_error(request, VIEW_CAPABILITY)
    if denied:
        return denied
    queryset = scoped_actions(_actor(request), getattr(request, 'portal_access', None), VIEW_CAPABILITY)
    status = str(request.GET.get('status') or '').strip()
    if status and status in dict(HomeBiogasAction.INSTALLATION_CHOICES):
        queryset = queryset.filter(installation_status=status)
    search = str(request.GET.get('search') or '').strip()
    if search:
        queryset = queryset.filter(
            Q(farmer__customer_name__icontains=search)
            | Q(farmer__national_id__icontains=search)
            | Q(farmer__primary_phone__icontains=search)
            | Q(source_order_number__icontains=search)
        )
    counts_queryset = scoped_actions(_actor(request), getattr(request, 'portal_access', None), VIEW_CAPABILITY)
    counts = {
        key: counts_queryset.filter(installation_status=key).count()
        for key, _label in HomeBiogasAction.INSTALLATION_CHOICES
    }
    try:
        page = max(1, int(request.GET.get('page') or 1))
    except (TypeError, ValueError):
        page = 1
    page_size = 30
    total = queryset.count()
    rows = queryset.order_by('-updated_at')[(page - 1) * page_size:page * page_size]
    return JsonResponse({
        'ok': True,
        'items': [serialize_action(item) for item in rows],
        'counts': counts,
        'total': total,
        'page': page,
        'pages': max(1, (total + page_size - 1) // page_size),
    })


@portal_auth_required
@require_http_methods(['GET'])
def hb_action_detail(request, farmer_id):
    action = _action_for_request(request, farmer_id, VIEW_CAPABILITY)
    if action is None:
        return _error('This HomeBiogas action is unavailable or outside your authorized scope.', status=404, code='not_found')
    denied = _portal_capability_error(request, VIEW_CAPABILITY, action.farmer)
    if denied:
        return denied
    from core.services.workflow_capabilities import has_capability
    actor = _actor(request)
    access = getattr(request, 'portal_access', None)
    return JsonResponse({
        'ok': True,
        'action': serialize_action(action, include_history=True),
        'permissions': {
            'write': access is None or has_capability(actor, 'jawabu_portal', WRITE_CAPABILITY, access=access),
            'correct': access is None or has_capability(actor, 'jawabu_portal', CORRECT_CAPABILITY, access=access),
        },
        'options': {
            'installation_statuses': [{'value': key, 'label': label} for key, label in HomeBiogasAction.INSTALLATION_CHOICES if key != HomeBiogasAction.INSTALLATION_NEEDS_PLANNING],
            'readiness_statuses': [{'value': key, 'label': label} for key, label in HomeBiogasAction.READINESS_CHOICES],
            'installation_report_statuses': [{'value': key, 'label': label} for key, label in HomeBiogasAction.REPORT_CHOICES],
            'commissioning_statuses': [{'value': key, 'label': label} for key, label in HomeBiogasAction.COMMISSIONING_CHOICES],
        },
    })


def _mutation(request, farmer_id, *, correction: bool):
    capability = CORRECT_CAPABILITY if correction else WRITE_CAPABILITY
    action = _action_for_request(request, farmer_id, capability)
    if action is None:
        return _error('This HomeBiogas action is unavailable or outside your authorized scope.', status=404, code='not_found')
    denied = _portal_capability_error(request, capability, action.farmer)
    if denied:
        return denied
    body = _portal_request_data(request)
    try:
        revision = int(body.get('revision'))
    except (TypeError, ValueError):
        return _error('Refresh this record before saving.', code='revision_required')
    request_id = _portal_request_id(request, body)
    try:
        service = correct_action if correction else transition_action
        updated, operations, replayed = service(
            action.pk, payload=body, actor=_actor(request), request_id=request_id,
            expected_revision=revision,
        )
    except HomeBiogasActionError as exc:
        return _error(str(exc))
    updated.refresh_from_db()
    return JsonResponse({
        'ok': True, 'action': serialize_action(updated, include_history=True),
        'replayed': replayed,
        'publications': [
            {'status': item.status, 'pending_operation_ids': [str(item.pk)] if item.status in {'pending', 'retryable_failure'} else []}
            for item in operations
        ],
    })


@portal_auth_required
@require_http_methods(['POST'])
def hb_action_transition(request, farmer_id):
    return _mutation(request, farmer_id, correction=False)


@portal_auth_required
@require_http_methods(['POST'])
def hb_action_correct(request, farmer_id):
    return _mutation(request, farmer_id, correction=True)

