"""Dormant native browser operations over the canonical Complaints services.

Separate from the intentionally restricted v1 read projection. Never mounted by
config.urls before release acceptance; no Telegram credential/session fallback.
"""
import json
from functools import wraps

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.utils.http import content_disposition_header

from core.models import ParsedMessage
from core.services import complaint_cases as cases
from core.services.access_control import record_capability_usage
from core.services.group_config import GroupConfig
from staff_auth.browser_api import browser_endpoint, require_company_browser_user
from .browser_complaint_views import _context


CASE_FIELDS = (
    'customer_name', 'customer_phone', 'secondary_phone', 'customer_id', 'county',
    'constituency', 'village', 'branch', 'category', 'description', 'status',
    'needs_details', 'reported_at', 'recorded_at', 'age_label', 'revision',
    'hb_comment_count', 'sync_status',
)
CREATE_FIELDS = frozenset((
    'client_name', 'customer_phone', 'secondary_phone', 'customer_id', 'county',
    'sub_county', 'village', 'branch_region', 'complaint_category',
    'complaint_description', 'latitude', 'longitude', 'client_request_id',
    'category_inference_token', 'voice_transcription_id', 'browser_draft_revision', 'browser_draft_key',
))
REPORT_FIELDS = frozenset(('branch', 'category', 'status', 'date_from', 'date_to',
                           'search', 'date_basis', 'metric', 'metric_value'))
ACTIONS = {
    'resolve': ('complaint.case.close', cases.resolve_case),
    'comment': ('complaint.case.comment', cases.comment_case),
    'reopen': ('complaint.case.reopen', cases.reopen_case),
    'complete-details': ('complaint.case.details.complete', cases.complete_review_details),
    'retry-publication': ('complaint.case.sync.retry', None),
    'finish-created': ('complaint.case.create', None),
}


def endpoint(methods, capability='complaint.queue.view'):
    def decorate(function):
        @browser_endpoint(methods)
        @wraps(function)
        def view(request, group_key, **kwargs):
            if not settings.STAFF_BROWSER_COMPLAINTS_ENABLED:
                return JsonResponse({'error': 'unavailable'}, status=404)
            try:
                user = require_company_browser_user(request)
            except PermissionDenied:
                return JsonResponse({'error': 'session_required'}, status=401)
            try:
                row, actor = _context(user, group_key)
                group = GroupConfig(**row.as_group_config_kwargs())
                require(actor, group, capability)
                return function(request, group, actor, **kwargs)
            except PermissionDenied:
                return JsonResponse({'error': 'access_denied'}, status=403)
            except cases.ComplaintCaseConflict as exc:
                return JsonResponse({'error': str(exc), 'code': 'revision_conflict',
                                     'current_revision': exc.current_revision}, status=409)
            except cases.ComplaintCaseError as exc:
                return JsonResponse({'error': str(exc), 'field_errors': exc.field_errors}, status=400)
        return view
    return decorate


def require(actor, group, capability):
    if not cases.actor_can(group, actor, capability):
        raise PermissionDenied
    record_capability_usage(actor.user, 'complaint_cases', capability)


def payload(request):
    try:
        if request.content_type == 'multipart/form-data':
            if any(len(request.POST.getlist(key)) != 1 for key in request.POST):
                raise ValueError
            result = request.POST.dict()
        else:
            result = json.loads(request.body)
        if not isinstance(result, dict):
            raise ValueError
        return result
    except (ValueError, UnicodeDecodeError):
        raise cases.ComplaintCaseError('Review the request and try again.') from None


def source_case(group, case_key):
    case = ParsedMessage.objects.filter(pk=case_key, group_id=group.group_id).only('message_id').first()
    if case is None:
        raise cases.ComplaintCaseError('Complaint not found in this workspace.')
    return case.message_id


def project(data):
    return {'key': data['id'], 'reference': data['reference_number'],
            **{key: data.get(key) for key in CASE_FIELDS}}


def project_detail(data, actor, group):
    result = project(data)
    result['history'] = [{key: row.get(key, '') for key in (
        'action', 'status', 'note', 'created_at', 'updated_by', 'actor_affiliation', 'display_changes',
    )} for row in data['updates'][:100]]
    result['history_truncated'] = len(data['updates']) > 100
    result['actions'] = [name for name, (capability, _) in ACTIONS.items()
                         if cases.actor_can(group, actor, capability)]
    # Only allowlisted evidence metadata; private storage identifiers never cross.
    result['evidence'] = [{key: item.get(key, '') for key in (
        'id', 'name', 'mime_type', 'previewable', 'status', 'created_at',
    )} for item in data['evidence']] if cases.actor_can(group, actor, 'complaint.case.evidence.view') else []
    result['location'] = data['location']
    return result


@endpoint(['GET'])
def bootstrap(request, group, actor):
    return JsonResponse(cases.bootstrap_data(group, actor))


@endpoint(['POST'])
def queue(request, group, actor):
    # Search identifiers belong in the body, not access logs/referrers/URLs.
    params = payload(request)
    if set(params) - {'q', 'status', 'branch', 'category', 'page'}:
        raise cases.ComplaintCaseError('Review the queue filters.')
    if any(not isinstance(params.get(key, ''), str) for key in ('q', 'status', 'branch', 'category')):
        raise cases.ComplaintCaseError('Review the queue filters.')
    if len(params.get('q', '')) > 150 or params.get('status', 'pending') not in {'pending', 'resolved', 'all'}:
        raise cases.ComplaintCaseError('Review the search or status filter.')
    result = cases.list_cases_page(group, actor=actor, query=params.get('q', ''),
        status=params.get('status', 'pending'), branch=params.get('branch', ''),
        category=params.get('category', ''), page=params.get('page', 1), page_size=10)
    return JsonResponse({'items': [project(item) for item in result['items']],
                         'pagination': result['pagination'], 'filter_options': result['filter_options']})


@endpoint(['GET'])
def detail(request, group, actor, case_key):
    data = cases.case_detail(group, source_case(group, case_key), actor)
    return JsonResponse({'case': project_detail(data, actor, group)})


@endpoint(['POST'], 'complaint.case.create')
def create(request, group, actor):
    fields = payload(request)
    if set(fields) - CREATE_FIELDS or any(not isinstance(value, str) for value in fields.values()):
        raise cases.ComplaintCaseError('The form contains unsupported fields. Refresh before submitting.')
    result = cases.create_complaint_case(group, actor, fields, request.FILES.getlist('evidence'))
    # A completed form must not be offered later as a second complaint. Never
    # discard another device's newer draft or alter Telegram's recovery slot.
    revision = fields.get('browser_draft_revision', '')
    draft_key = fields.get('browser_draft_key', '')
    from uuid import UUID
    try:
        draft_id = UUID(draft_key)
    except (ValueError, TypeError, AttributeError):
        draft_id = None
    if draft_id and revision.isascii() and revision.isdigit() and len(revision) < 10:
        from core.models import MiniAppDraft
        MiniAppDraft.objects.filter(user=actor.user, workflow='complaint_cases',
            context_key=f'browser-create:{group.group_id}', pk=draft_id, revision=int(revision)).delete()
    return JsonResponse({'case': project(result['case']),
                         'publication_deferred': result.get('publication_deferred', False)},
                        status=201 if result['created'] else 200)


@endpoint(['POST'])
def action(request, group, actor, case_key, action):
    if action not in ACTIONS:
        raise cases.ComplaintCaseError('This complaint action is unavailable.')
    capability, function = ACTIONS[action]
    require(actor, group, capability)
    case_id = source_case(group, case_key)
    fields = payload(request)
    cases.create_request_id(fields.get('client_request_id'))
    allowed = {'client_request_id', 'expected_revision', 'resolution_text', 'reason', 'comment_text',
               'customer_phone', 'customer_id', 'complaint_category', 'latitude', 'longitude',
               'voice_transcription_id', 'creation_request_id'}
    if set(fields) - allowed:
        raise cases.ComplaintCaseError('Review the complaint action fields.')
    if action == 'retry-publication':
        data = cases.retry_case_sync(group, actor, case_id, request_id=fields['client_request_id'])
    elif action == 'finish-created':
        data = cases.finish_created_case(group, actor, case_id,
            creation_request_id=str(fields.get('creation_request_id') or ''),
            uploaded_files=request.FILES.getlist('evidence'))
    elif action == 'resolve':
        data = function(group, actor, case_id, fields, request.FILES.getlist('evidence'))
    else:
        data = function(group, actor, case_id, fields)
    return JsonResponse({'case': project_detail(data, actor, group)})


@endpoint(['GET', 'POST'], 'complaint.case.create')
@transaction.atomic
def draft(request, group, actor):
    from core.services import miniapp_drafts as drafts
    context = {'user': actor.user, 'workflow': 'complaint_cases', 'context_key': f'browser-create:{group.group_id}'}
    try:
        if request.method == 'POST':
            body = payload(request)
            if type(body.get('revision')) is not int or body['revision'] < 0:
                raise drafts.MiniAppDraftError('Refresh before changing this draft.')
            from core.models import MiniAppDraft
            locked = MiniAppDraft.objects.select_for_update().filter(**context).first()
            if locked is None and body.get('action') == 'discard':
                return JsonResponse({'draft': None})
            if body.get('revision', 0) != 0 and (locked is None or str(locked.pk) != body.get('key')):
                raise drafts.MiniAppDraftConflict('This draft is no longer current. Refresh before changing it.')
            if body.get('action') == 'discard':
                # Revision binding prevents discarding a newer device's draft.
                current = locked
                if current and body.get('revision') != current.revision:
                    raise drafts.MiniAppDraftConflict('This draft changed. Refresh before discarding it.')
                drafts.delete_draft(**context)
                return JsonResponse({'draft': None})
            fields = body.get('fields')
            if (not isinstance(fields, dict) or set(fields) - CREATE_FIELDS
                    or any(not isinstance(value, str) for value in fields.values())):
                raise drafts.MiniAppDraftError('Review the draft fields.')
            if type(body.get('revision')) is not int or body['revision'] < 0:
                raise drafts.MiniAppDraftError('Refresh before saving this draft.')
            retained = {key: value for key, value in fields.items() if key not in {
                'voice_transcription_id', 'category_inference_token', 'client_request_id', 'browser_draft_revision', 'browser_draft_key',
            }}
            current = drafts.save_draft(**context, payload=retained, expected_revision=body['revision'])
        else:
            current = drafts.get_draft(**context)
        return JsonResponse({'draft': {'key': str(current.pk), 'fields': current.payload, 'revision': current.revision} if current else None})
    except drafts.MiniAppDraftError as exc:
        return JsonResponse({'error': str(exc)}, status=409 if isinstance(exc, drafts.MiniAppDraftConflict) else 400)


@endpoint(['GET'])
def locations(request, group, actor):
    from core.services.location_catalog import location_options
    return JsonResponse(location_options(user=actor.user, access=actor.access,
        branch_value=request.GET.get('branch', ''), county_value=request.GET.get('county', '')))


@endpoint(['POST'], 'complaint.case.create')
def category_suggestion(request, group, actor):
    return JsonResponse(cases.suggest_category(group, payload(request).get('description', '')))


@endpoint(['GET', 'POST'])
def preferences(request, group, actor):
    from django.core.exceptions import ValidationError
    from core.services.miniapp_settings import preference_payload, update_preference
    try:
        if request.method == 'POST':
            update_preference(actor.user, 'complaint_cases', payload(request).get('preferences', {}))
        return JsonResponse(preference_payload(actor.user, 'complaint_cases'))
    except (ValidationError, ValueError, TypeError, AttributeError):
        raise cases.ComplaintCaseError('Review your preferences.') from None


@endpoint(['GET'])
def recovery(request, group, actor):
    # Browser-owned repair links only. Never forward Telegram action URLs.
    rows = ParsedMessage.objects.filter(group_id=group.group_id,
        complaint_control__sync_status__in=['failed', 'pending', 'suspended']).select_related('complaint_control')[:50]
    return JsonResponse({'issues': [{
        'key': str(row.pk), 'reference': row.complaint_control.reference_number,
        'status': row.complaint_control.sync_status,
        'can_retry': cases.complaint_sheet_projection_enabled(group)
            and cases.actor_can(group, actor, 'complaint.case.sync.retry', row),
    } for row in rows]})


@endpoint(['POST'])
def voice(request, group, actor):
    from uuid import UUID
    from core.models import GroupSheetConfiguration, PortalVoiceTranscriptionAttempt as Attempt
    from core.services.portal_voice import VoiceInputError, create_transcription, resolve_transcription
    body = payload(request)
    capabilities = {
        Attempt.FIELD_COMPLAINT_DESCRIPTION: 'complaint.case.create',
        Attempt.FIELD_COMPLAINT_RESOLUTION_NOTE: 'complaint.case.close',
        Attempt.FIELD_COMPLAINT_RESOLUTION_COMMENT: 'complaint.case.comment',
        Attempt.FIELD_COMPLAINT_REOPEN_REASON: 'complaint.case.reopen',
    }
    field = body.get('field_name')
    if not isinstance(field, str) or field not in capabilities:
        raise cases.ComplaintCaseError('Voice input is unavailable for this field.')
    require(actor, group, capabilities[field])
    record = GroupSheetConfiguration.objects.get(group_id=group.group_id)
    try:
        case = None
        if field != Attempt.FIELD_COMPLAINT_DESCRIPTION:
            key = UUID(str(body.get('case_key', '')))
            case = cases.complaint_case_for_voice(group, actor, source_case(group, key))
        elif body.get('case_key'):
            raise ValueError
        cases.create_request_id(body.get('client_request_id'))
        if body.get('action') == 'cancel':
            resolve_transcription(attempt_id=UUID(str(body.get('transcription_id', ''))), user=actor.user,
                field_name=field, complaint_group=record, complaint_case=case, accepted=False)
            return JsonResponse({'status': 'cancelled'})
        uploaded = request.FILES.get('audio')
        if uploaded is None or uploaded.size > 5 * 1024 * 1024:
            raise cases.ComplaintCaseError('Choose a recording smaller than 5 MB.')
        attempt, replayed = create_transcription(user=actor.user, complaint_group=record, complaint_case=case,
            field_name=field, request_id=body['client_request_id'], duration_ms=int(body.get('duration_ms', 0)),
            audio=uploaded.read(), mime_type=uploaded.content_type, language_mode=str(body.get('language_mode', '')))
        return JsonResponse({'transcription_id': str(attempt.pk), 'text': attempt.transcript,
                             'status': attempt.status, 'idempotent_replay': replayed})
    except VoiceInputError as exc:
        raise cases.ComplaintCaseError(str(exc)) from exc
    except (ValueError, TypeError):
        raise cases.ComplaintCaseError('Review the recording and complaint selection.') from None


@endpoint(['GET'], 'complaint.case.evidence.view')
def evidence(request, group, actor, evidence_key):
    from core.services.order_approval import GoogleDriveMediaStorage
    item = cases.evidence_for_preview(group, actor, str(evidence_key))
    try:
        content = GoogleDriveMediaStorage().download(item.drive_file_id)
    except Exception:
        return JsonResponse({'error': 'The document could not be loaded. Try again shortly.'}, status=503)
    cases.record_evidence_preview(group, actor, item)
    response = HttpResponse(content, content_type=item.mime_type)
    response['Content-Disposition'] = content_disposition_header(
        request.GET.get('download') == '1', item.original_filename or 'complaint-evidence.pdf')
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@endpoint(['POST'], 'complaint.reports.view')
def reports(request, group, actor):
    from core.services.complaint_register import complaint_report_page, complaint_report_summary
    params = payload(request)
    if (set(params) - REPORT_FIELDS - {'granularity', 'page'}
            or any(not isinstance(value, str) for key, value in params.items() if key != 'page')):
        raise cases.ComplaintCaseError('Review the report filters.')
    filters = {key: params[key] for key in REPORT_FIELDS if key in params}
    return JsonResponse({'summary': complaint_report_summary(filters=filters, granularity=params.get('granularity', 'month')),
                         'table': complaint_report_page(filters=filters, page=params.get('page', 1))})


@endpoint(['POST'], 'complaint.reports.view')
def export(request, group, actor):
    from core.services.complaint_register import export_filename, export_register_xlsx, validate_report_filters
    require(actor, group, 'complaint.case.export')
    body = payload(request)
    request_id = cases.create_request_id(body.get('client_request_id'))
    if body.get('scope') not in {'filtered', 'all'}:
        raise cases.ComplaintCaseError('Choose filtered results or all complaints.')
    filters = body.get('filters', {})
    if not isinstance(filters, dict) or set(filters) - REPORT_FIELDS:
        raise cases.ComplaintCaseError('Review the report filters.')
    validate_report_filters(filters)
    content, count = export_register_xlsx(actor=actor.user, request_id=request_id,
        filters=filters if body['scope'] == 'filtered' else None)
    response = HttpResponse(content, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = content_disposition_header(True, export_filename(filtered=body['scope'] == 'filtered'))
    response['X-Export-Count'] = str(count)
    return response


@endpoint(['POST'], 'complaint.reports.view')
def email(request, group, actor):
    from report_delivery.views import report_export_response
    require(actor, group, 'complaint.case.export')
    return report_export_response(actor.user, 'complaint_cases', payload(request))


@endpoint(['POST'], 'complaint.reports.view')
def email_settings(request, group, actor):
    from report_delivery.views import report_settings_response
    return report_settings_response(actor.user, 'complaint_cases', payload(request))
