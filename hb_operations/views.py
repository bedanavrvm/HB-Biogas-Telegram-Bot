from __future__ import annotations

from datetime import timedelta

from django.db.models import Q
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_date
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
)


def _actor(request):
    return getattr(request, 'portal_user', None) or (request.user if getattr(request.user, 'is_authenticated', False) else None)


def _error(message: str, *, status: int = 400, code: str = 'invalid_request'):
    return JsonResponse({'ok': False, 'error': str(message), 'code': code}, status=status)


def _action_for_request(request, farmer_id, capability):
    return scoped_actions(
        _actor(request), getattr(request, 'portal_access', None), capability,
    ).filter(farmer_id=farmer_id).first()


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


def _date_param(request, key):
    raw = str(request.GET.get(key) or '').strip()
    return parse_date(raw) if raw else None


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
    branch = str(request.GET.get('branch') or '').strip()
    if branch:
        queryset = queryset.filter(Q(farmer__system_branch__iexact=branch) | Q(farmer__branch__iexact=branch))
    invoice = str(request.GET.get('invoice') or '').strip()
    if invoice == 'present':
        queryset = queryset.filter(farmer__parsed_invoices__status='matched')
    elif invoice == 'absent':
        queryset = queryset.exclude(farmer__parsed_invoices__status='matched')
    date_from = _date_param(request, 'date_from')
    date_to = _date_param(request, 'date_to')
    today = timezone.localdate()
    state = str(request.GET.get('state') or request.GET.get('status') or '').strip()
    if queue == 'installation':
        readiness = str(request.GET.get('readiness') or '').strip()
        report = str(request.GET.get('installation_report') or '').strip()
        if readiness in dict(HomeBiogasAction.READINESS_CHOICES):
            queryset = queryset.filter(readiness_status=readiness)
        if report in dict(HomeBiogasAction.REPORT_CHOICES):
            queryset = queryset.filter(installation_report_status=report)
        if date_from:
            queryset = queryset.filter(planned_installation_date__gte=date_from)
        if date_to:
            queryset = queryset.filter(planned_installation_date__lte=date_to)
        if str(request.GET.get('overdue') or '').lower() in {'1', 'true', 'yes'}:
            queryset = queryset.filter(
                installation_status=HomeBiogasAction.INSTALLATION_OPEN,
                planned_installation_date__lt=today,
            )
        counts_queryset = queryset
        counts = {
            key: counts_queryset.filter(installation_status=key).distinct().count()
            for key, _label in HomeBiogasAction.INSTALLATION_CHOICES
        }
        if not state:
            state = HomeBiogasAction.INSTALLATION_OPEN
        if state == HomeBiogasAction.INSTALLATION_OPEN:
            queryset = queryset.filter(installation_status=HomeBiogasAction.INSTALLATION_OPEN)
        elif state in dict(HomeBiogasAction.INSTALLATION_CHOICES):
            queryset = queryset.filter(installation_status=state)
    else:
        queryset = queryset.filter(
            installation_status=HomeBiogasAction.INSTALLATION_INSTALLED,
            installation_date__isnull=False,
        )
        if date_from:
            queryset = queryset.filter(installation_date__gte=date_from - timedelta(days=COMMISSIONING_WAIT_DAYS))
        if date_to:
            queryset = queryset.filter(installation_date__lte=date_to - timedelta(days=COMMISSIONING_WAIT_DAYS))
        threshold = today - timedelta(days=COMMISSIONING_WAIT_DAYS)
        unfinished = Q(commissioning_status=HomeBiogasAction.COMMISSIONING_NOT_COMMISSIONED)
        counts_queryset = queryset
        counts = {
            'not_commissioned': counts_queryset.filter(unfinished).distinct().count(),
            'commissioned': counts_queryset.filter(
                commissioning_status=HomeBiogasAction.COMMISSIONING_COMMISSIONED,
            ).distinct().count(),
        }
        overdue_only = str(request.GET.get('overdue') or '').lower() in {'1', 'true', 'yes'}
        if overdue_only:
            queryset = queryset.filter(unfinished, installation_date__lt=threshold)
        if not state:
            state = 'not_commissioned'
        if state == 'not_commissioned':
            queryset = queryset.filter(unfinished)
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
        'filters': {
            'branches': sorted({
                str(value or '').strip()
                for row in scoped_actions(_actor(request), getattr(request, 'portal_access', None), VIEW_CAPABILITY)
                    .values('farmer__system_branch', 'farmer__branch')
                for value in (row['farmer__system_branch'], row['farmer__branch']) if str(value or '').strip()
            }),
            'readiness': [{'value': key, 'label': label} for key, label in HomeBiogasAction.READINESS_CHOICES],
            'installation_reports': [{'value': key, 'label': label} for key, label in HomeBiogasAction.REPORT_CHOICES],
        },
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
        'options': {
            'installation_statuses': [{'value': key, 'label': label} for key, label in HomeBiogasAction.INSTALLATION_CHOICES],
            'readiness_statuses': [{'value': key, 'label': label} for key, label in HomeBiogasAction.READINESS_CHOICES],
            'installation_report_statuses': [{'value': key, 'label': label} for key, label in HomeBiogasAction.REPORT_CHOICES],
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
@require_http_methods(['POST'])
def hb_action_transition(request, farmer_id):
    return _mutation(request, farmer_id, correction=False)


@portal_auth_required
@require_http_methods(['POST'])
def hb_action_correct(request, farmer_id):
    return _mutation(request, farmer_id, correction=True)
