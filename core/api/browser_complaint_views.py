"""Dormant company-browser reads; intentionally absent from production URLs.

Identity assurance and current owning-workflow authority are separate checks.
Never forward the Telegram detail serializer wholesale to this channel.
"""
from functools import wraps

from django.core.exceptions import PermissionDenied
from django.http import JsonResponse

from core.models import GroupSheetConfiguration, ParsedMessage
from core.services.access_control import record_capability_usage
from core.services.complaint_cases import (
    ComplaintCaseError, actor_can, case_detail, is_complaint_workflow,
    list_cases_page, staff_actor_for_user,
)
from staff_auth.browser_api import browser_endpoint, require_company_browser_user


SUMMARY_FIELDS = ('customer_name', 'branch', 'category')
HISTORY_FIELDS = ('status', 'created_at', 'updated_by', 'actor_affiliation')
HISTORY_ACTIONS = frozenset(('created', 'updated', 'commented', 'resolved', 'reopened', 'review_completed'))


def _error(code, status):
    return JsonResponse({'error': code}, status=status)


def _read(function):
    @browser_endpoint(['GET'])
    @wraps(function)
    def view(request, *args, **kwargs):
        try:
            user = require_company_browser_user(request)
        except PermissionDenied:
            return _error('session_required', 401)
        try:
            return function(request, user, *args, **kwargs)
        except PermissionDenied:
            return _error('access_denied', 403)
        except ComplaintCaseError:
            return _error('case_unavailable', 404)
    return view


def _actor(group, user):
    try:
        actor = staff_actor_for_user(group, user)
    except ComplaintCaseError:
        raise PermissionDenied from None
    if not actor_can(group, actor, 'complaint.queue.view'):
        raise PermissionDenied
    return actor


def _context(user, group_key):
    group = GroupSheetConfiguration.objects.filter(pk=group_key, enabled=True).first()
    if group is None or not is_complaint_workflow(group):
        raise PermissionDenied
    actor = _actor(group, user)
    record_capability_usage(user, 'complaint_cases', 'complaint.queue.view')
    return group, actor


@_read
def groups(request, user):
    if request.GET:
        return _error('invalid_request', 400)
    available = []
    for group in GroupSheetConfiguration.objects.filter(enabled=True).order_by('display_name', 'pk'):
        if not is_complaint_workflow(group):
            continue
        try:
            _actor(group, user)
        except PermissionDenied:
            continue
        available.append({'key': str(group.pk), 'label': group.display_name or 'Complaints workspace'})
    return JsonResponse({'groups': available})


def _summary(payload):
    return {'key': payload['id'], **{key: payload.get(key, '') for key in SUMMARY_FIELDS},
            'reference': payload['reference_number'],
            'status': 'Resolved' if payload['status'] == 'CLOSED' else 'Needs details' if payload['needs_details'] else 'Pending',
            'reported_at': payload['reported_at'] or payload['recorded_at']}


@_read
def cases(request, user, group_key):
    group, actor = _context(user, group_key)
    params = request.GET
    if set(params) - {'q', 'status', 'page'} or any(len(params.getlist(key)) != 1 for key in params):
        return _error('invalid_request', 400)
    query, status, page = params.get('q', '').strip(), params.get('status', 'pending'), params.get('page', '1')
    if len(query) > 150 or status not in {'pending', 'resolved', 'all'} or not page.isascii() or not page.isdigit() or len(page) > 6 or int(page) < 1:
        return _error('invalid_request', 400)
    result = list_cases_page(group, actor=actor, query=query, status=status, page=int(page),
                             page_size=5, search_mode='reference_or_name')
    # The owning serializer's id is already the opaque Django UUID; case_id
    # contains a source identifier and is deliberately absent from this projection.
    return JsonResponse({'items': [_summary(item) for item in result['items']],
                         'pagination': result['pagination']})


@_read
def detail(request, user, group_key, case_key):
    group, actor = _context(user, group_key)
    if request.GET:
        return _error('invalid_request', 400)
    case = ParsedMessage.objects.filter(pk=case_key, group_id=group.group_id).only('message_id').first()
    if case is None:
        return _error('case_unavailable', 404)
    payload = case_detail(group, case.message_id, actor=actor)
    history = [{**{key: row.get(key, '') for key in HISTORY_FIELDS},
                'action': row.get('action') if row.get('action') in HISTORY_ACTIONS else 'updated'}
               for row in payload['updates'][:100]]
    return JsonResponse({'case': {**_summary(payload), 'description': payload.get('description', ''),
                                 'history': history, 'history_truncated': len(payload['updates']) > 100}})
