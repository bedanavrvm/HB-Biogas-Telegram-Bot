from __future__ import annotations

import logging
from datetime import timedelta

from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
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
    COMMISSIONING_WAIT_DAYS,
    correct_action,
    scoped_actions,
    serialize_action,
    transition_action,
    update_commissioning_notes,
)

logger = logging.getLogger(__name__)


def _actor(request):
    return getattr(request, 'portal_user', None) or (request.user if getattr(request.user, 'is_authenticated', False) else None)


def _error(message: str, *, status: int = 400, code: str = 'invalid_request'):
    return JsonResponse({'ok': False, 'error': str(message), 'code': code}, status=status)


def _action_for_request(request, farmer_id, capability):
    return scoped_actions(
        _actor(request), getattr(request, 'portal_access', None), capability,
    ).filter(farmer_id=farmer_id).first()


def _action_access_error(request, action, capability):
    """Check the same requisition group used by the scoped HB queryset."""
    access = getattr(request, 'portal_access', None)
    if access is None:
        return None
    from core.services.portal_permissions import portal_access_decision

    decision = portal_access_decision(
        _actor(request), capability, access=access, resource=action.farmer,
        group_configuration=action.source_requisition_batch.group_configuration,
        enforce_group_scope=True,
    )
    if not decision.allowed:
        return _error('This HomeBiogas action is outside your authorized scope.', status=403, code='forbidden')
    from core.services.access_control import record_capability_usage

    record_capability_usage(_actor(request), 'jawabu_portal', capability)
    return None


def _invoice_presentation(request, action, data):
    invoice = data.get('invoice')
    if not invoice:
        return data
    access = getattr(request, 'portal_access', None)
    if access is None:
        record_mode = True
    else:
        from core.services.portal_permissions import portal_access_decision
        record_mode = portal_access_decision(
            _actor(request), 'portal.invoice_identity.manage', access=access,
            resource=action.farmer,
            group_configuration=action.source_requisition_batch.group_configuration,
            enforce_group_scope=True,
        ).allowed
    data['invoice'] = {
        'id': invoice['id'], 'number': invoice['number'], 'date': invoice['date'],
        'label': 'Invoice received' if record_mode else 'Invoice sent',
        'mode': 'record' if record_mode else 'preview',
        'url': invoice['record_url'] if record_mode else invoice['preview_url'],
    }
    return data


def _serialized(request, action, *, include_history=False, workstream='installation'):
    data = _invoice_presentation(request, action, serialize_action(action, include_history=include_history))
    data['workstream'] = workstream
    data['detail_url'] = f"{data['detail_url']}?workstream={workstream}"
    return data


@portal_auth_required
@require_http_methods(['GET'])
def hb_action_list(request):
    denied = _portal_capability_error(request, VIEW_CAPABILITY)
    if denied:
        return denied
    queryset = scoped_actions(_actor(request), getattr(request, 'portal_access', None), VIEW_CAPABILITY)
    queue = str(request.GET.get('queue') or 'installation').strip().lower()
    if queue not in {'installation', 'commissioning'}:
        return _error('Choose Installation or Commissioning.', code='invalid_queue')
    search = str(request.GET.get('search') or '').strip()
    if search:
        queryset = queryset.filter(
            Q(farmer__customer_name__icontains=search)
            | Q(farmer__national_id__icontains=search)
            | Q(farmer__primary_phone__icontains=search)
            | Q(source_order_number__icontains=search)
        )
    today = timezone.localdate()
    state = str(request.GET.get('state') or request.GET.get('status') or '').strip()
    if queue == 'installation':
        counts_queryset = queryset
        active_installation_states = (
            HomeBiogasAction.INSTALLATION_OPEN,
            HomeBiogasAction.INSTALLATION_INSTALLED,
        )
        counts = {
            key: counts_queryset.filter(installation_status=key).distinct().count()
            for key in active_installation_states
        }
        if state not in active_installation_states:
            state = HomeBiogasAction.INSTALLATION_OPEN
        queryset = queryset.filter(installation_status=state)
    else:
        queryset = queryset.filter(
            installation_status=HomeBiogasAction.INSTALLATION_INSTALLED,
            installation_date__isnull=False,
        )
        threshold = today - timedelta(days=COMMISSIONING_WAIT_DAYS)
        unfinished = Q(commissioning_status=HomeBiogasAction.COMMISSIONING_NOT_COMMISSIONED)
        counts_queryset = queryset
        delayed = counts_queryset.filter(unfinished, installation_date__lt=threshold)
        counts = {
            'not_commissioned': counts_queryset.filter(unfinished).distinct().count(),
            'delayed': delayed.distinct().count(),
            'commissioned': counts_queryset.filter(
                commissioning_status=HomeBiogasAction.COMMISSIONING_COMMISSIONED,
            ).distinct().count(),
        }
        if not state:
            state = 'not_commissioned'
        if state == 'not_commissioned':
            queryset = queryset.filter(unfinished)
        elif state == 'delayed':
            queryset = queryset.filter(unfinished, installation_date__lt=threshold)
        elif state == 'commissioned':
            queryset = queryset.filter(commissioning_status=HomeBiogasAction.COMMISSIONING_COMMISSIONED)
    queryset = queryset.distinct()
    try:
        page = max(1, int(request.GET.get('page') or 1))
    except (TypeError, ValueError):
        page = 1
    page_size = 30
    total = queryset.count()
    rows = queryset.order_by('-updated_at')[(page - 1) * page_size:page * page_size]
    return JsonResponse({
        'ok': True,
        'items': [_serialized(request, item, workstream=queue) for item in rows],
        'counts': counts,
        'queue': queue,
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
    denied = _action_access_error(request, action, VIEW_CAPABILITY)
    if denied:
        return denied
    from core.services.workflow_capabilities import has_capability
    actor = _actor(request)
    access = getattr(request, 'portal_access', None)
    workstream = str(request.GET.get('workstream') or '').strip().lower()
    if workstream not in {'installation', 'commissioning'}:
        workstream = 'commissioning' if action.installation_status == HomeBiogasAction.INSTALLATION_INSTALLED else 'installation'
    return JsonResponse({
        'ok': True,
        'action': _serialized(request, action, include_history=True, workstream=workstream),
        'permissions': {
            'write': access is None or has_capability(actor, 'jawabu_portal', WRITE_CAPABILITY, access=access),
            'correct': access is None or has_capability(actor, 'jawabu_portal', CORRECT_CAPABILITY, access=access),
        },
        'options': {},
    })


@portal_auth_required
@require_http_methods(['GET'])
def hb_action_document_preview(request, farmer_id, document_kind):
    """Stream only the signed order linked to one authorized HB Action."""
    action = _action_for_request(request, farmer_id, VIEW_CAPABILITY)
    if action is None:
        return _error('This HomeBiogas action is unavailable or outside your authorized scope.', status=404, code='not_found')
    denied = _action_access_error(request, action, VIEW_CAPABILITY)
    if denied:
        return denied
    if str(document_kind or '').strip().lower() != 'signed-order':
        return _error('This document preview is not available.', status=404, code='not_found')
    signoff = action.source_signoff
    if not signoff or signoff.status != 'signed_approved':
        return _error('The accepted signed order is not available for preview.', status=404, code='not_found')
    content = bytes(signoff.scan_file_content or b'')
    if not content:
        return _error('The retained signed order scan is unavailable for preview.', status=404, code='preview_unavailable')
    try:
        from core.services.compliance_audit import record_sensitive_access

        record_sensitive_access(
            workflow='portal', action='portal.hb_action.signed_order.preview',
            subject_type='document_physical_signoff', subject_id=str(signoff.pk),
            actor=_actor(request), actor_label=getattr(_actor(request), 'get_full_name', lambda: '')() or str(_actor(request) or ''),
            request_id=_portal_request_id(request),
            metadata={'farmer_id': str(action.farmer_id), 'order_number': action.source_order_number},
        )
    except Exception:
        return _error('The signed order cannot be opened safely right now. Please retry shortly.', status=503, code='audit_unavailable')
    response = HttpResponse(content, content_type=signoff.scan_content_type or 'application/octet-stream')
    response['Cache-Control'] = 'private, no-store, max-age=0'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@portal_auth_required
@require_http_methods(['GET'])
def hb_action_invoice_preview(request, farmer_id, batch_id):
    """Preview only the matched invoice shown on this authorized HB record."""
    from django.utils.http import content_disposition_header
    from core.api.portal_views import (
        _portal_case_invoice, _portal_case_invoice_audit_error,
        _portal_pdf_preview_html,
    )
    from core.services.order_approval import GoogleDriveMediaStorage

    action = _action_for_request(request, farmer_id, VIEW_CAPABILITY)
    if action is None:
        return _error('This HomeBiogas action is unavailable or outside your authorized scope.', status=404, code='not_found')
    denied = _action_access_error(request, action, VIEW_CAPABILITY)
    if denied:
        return denied
    visible_invoice = serialize_action(action).get('invoice') or {}
    if str(visible_invoice.get('batch_id') or '') != str(batch_id):
        return _error('This invoice is not available on this HomeBiogas record.', status=404, code='not_found')
    farmer, batch = _portal_case_invoice(str(farmer_id), str(batch_id))
    if not farmer or not batch or not batch.drive_file_id:
        return _error('The matched invoice is not available for in-app preview.', status=404, code='preview_unavailable')
    try:
        source = GoogleDriveMediaStorage().download(batch.drive_file_id)
        content = _portal_pdf_preview_html(source, batch.original_filename or 'Invoice.pdf')
    except Exception:
        logger.exception('HB invoice preview failed: batch_id=%s farmer_id=%s', batch.pk, action.farmer_id)
        return _error('The invoice could not be prepared for in-app viewing. Please retry shortly.', status=503, code='preview_unavailable')
    audit_error = _portal_case_invoice_audit_error(
        request, farmer=farmer, batch=batch, action='portal.hb_action.invoice.preview',
    )
    if audit_error:
        return audit_error
    response = HttpResponse(content, content_type='text/html; charset=utf-8')
    response['Content-Disposition'] = content_disposition_header(False, batch.original_filename or 'Invoice.pdf')
    response['Cache-Control'] = 'private, no-store, max-age=0'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


def _mutation(request, farmer_id, *, correction: bool):
    capability = CORRECT_CAPABILITY if correction else WRITE_CAPABILITY
    action = _action_for_request(request, farmer_id, capability)
    if action is None:
        return _error('This HomeBiogas action is unavailable or outside your authorized scope.', status=404, code='not_found')
    denied = _action_access_error(request, action, capability)
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
        'ok': True, 'action': _serialized(
            request, updated, include_history=True,
            workstream=str(body.get('workstream') or 'installation'),
        ),
        'replayed': replayed,
        'publications': [
            {'status': item.status, 'pending_operation_ids': [str(item.pk)] if item.status in {'pending', 'retryable_failure'} else []}
            for item in operations
        ],
    })


@portal_auth_required
@csrf_exempt  # Portal writes authenticate through verified Telegram initData, not a browser cookie.
@require_http_methods(['POST'])
def hb_action_transition(request, farmer_id):
    return _mutation(request, farmer_id, correction=False)


@portal_auth_required
@csrf_exempt  # Keep correction writes on the same verified Mini App auth contract.
@require_http_methods(['POST'])
def hb_action_correct(request, farmer_id):
    return _mutation(request, farmer_id, correction=True)


@portal_auth_required
@csrf_exempt  # Portal writes authenticate through verified Telegram initData, not a browser cookie.
@require_http_methods(['POST'])
def hb_action_commissioning_notes(request, farmer_id):
    action = _action_for_request(request, farmer_id, WRITE_CAPABILITY)
    if action is None:
        return _error('This HomeBiogas action is unavailable or outside your authorized scope.', status=404, code='not_found')
    denied = _action_access_error(request, action, WRITE_CAPABILITY)
    if denied:
        return denied
    body = _portal_request_data(request)
    try:
        revision = int(body.get('revision'))
    except (TypeError, ValueError):
        return _error('Refresh this record before saving notes.', code='revision_required')
    try:
        updated, operations, replayed = update_commissioning_notes(
            action.pk, payload=body, actor=_actor(request), request_id=_portal_request_id(request, body),
            expected_revision=revision,
        )
    except HomeBiogasActionError as exc:
        return _error(str(exc))
    updated.refresh_from_db()
    return JsonResponse({
        'ok': True,
        'action': _serialized(request, updated, include_history=True, workstream='commissioning'),
        'replayed': replayed,
        'publications': [
            {'status': item.status, 'pending_operation_ids': [str(item.pk)] if item.status in {'pending', 'retryable_failure'} else []}
            for item in operations
        ],
    })
