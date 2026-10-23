"""Dormant native browser operations over the canonical Complaints services.

Separate from the intentionally restricted v1 read projection. Never mounted by
config.urls before release acceptance; no Telegram credential/session fallback.
"""
import json
from uuid import UUID
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
    'hb_comment_count', 'sync_status', 'days_open',
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
            **{key: data.get(key) for key in CASE_FIELDS},
            'reported_at': data.get('reported_at_iso', data.get('reported_at')),
            'recorded_at': data.get('recorded_at_iso', data.get('recorded_at'))}


def project_detail(data, actor, group):
    result = project(data)
    result['history'] = [{key: row.get(key, '') for key in (
        'id', 'action', 'status', 'note', 'created_at', 'updated_by', 'actor_affiliation', 'display_changes',
    )} for row in data['updates'][:100]]
    result['history_truncated'] = bool(data.get('history_next_cursor')) or len(data['updates']) > 100
    result['history_next_cursor'] = data.get('history_next_cursor', '')
    result['actions'] = [name for name, (capability, _) in ACTIONS.items()
                         if cases.actor_can(group, actor, capability)]
    # Only allowlisted evidence metadata; private storage identifiers never cross.
    result['evidence'] = [{key: item.get(key, '') for key in (
        'id', 'name', 'mime_type', 'previewable', 'status', 'created_at', 'created_at_iso', 'uploaded_by', 'size',
    )} for item in data['evidence']] if cases.actor_can(group, actor, 'complaint.case.evidence.view') else []
    result['location'] = data['location']
    return result


@endpoint(['GET'])
def bootstrap(request, group, actor):
    from core.services.miniapp_settings import preference_payload
    from django.utils.crypto import salted_hmac
    from staff_auth.models import StaffBrowserAdmission
    generation = StaffBrowserAdmission.objects.get(user=actor.user).revision
    # Only the same currently admitted account may resume tab-local form data.
    # This opaque binding is not a token and grants no access to any endpoint.
    continuity = salted_hmac('browser-complaint-recovery-v1',
        f'{actor.user.pk}:{actor.user.get_session_auth_hash()}:{generation}', algorithm='sha256').hexdigest()
    return JsonResponse({**cases.bootstrap_data(group, actor),
                         'continuity_key': continuity,
                         'preferences': preference_payload(actor.user, 'complaint_cases')})


@endpoint(['POST'])
def queue(request, group, actor):
    # Search identifiers belong in the body, not access logs/referrers/URLs.
    params = payload(request)
    if set(params) - {'q', 'status', 'branch', 'category', 'page', 'order', 'selected'}:
        raise cases.ComplaintCaseError('Review the queue filters.')
    if any(not isinstance(params.get(key, ''), str) for key in ('q', 'status', 'branch', 'category', 'order', 'selected')):
        raise cases.ComplaintCaseError('Review the queue filters.')
    if params.get('order', '') not in {'', 'oldest', 'newest'}:
        raise cases.ComplaintCaseError('Choose oldest or newest first.')
    if params.get('selected'):
        try:
            UUID(params['selected'])
        except ValueError:
            raise cases.ComplaintCaseError('Select a valid complaint.')
    if len(params.get('q', '')) > 150 or params.get('status', 'pending') not in {'pending', 'resolved', 'all'}:
        raise cases.ComplaintCaseError('Review the search or status filter.')
    result = cases.list_cases_page(group, actor=actor, query=params.get('q', ''),
        status=params.get('status', 'pending'), branch=params.get('branch', ''),
        category=params.get('category', ''), page=params.get('page', 1), page_size=10,
        order=params.get('order', ''), focus_key=params.get('selected', ''))
    return JsonResponse({'items': [project(item) for item in result['items']],
                         'pagination': result['pagination'], 'filter_options': result['filter_options'],
                         'navigation': result.get('navigation')})


@endpoint(['GET'])
def detail(request, group, actor, case_key):
    data = cases.case_detail(group, source_case(group, case_key), actor, paged_history=True)
    return JsonResponse({'case': project_detail(data, actor, group)})


@endpoint(['POST'])
def history(request, group, actor, case_key):
    body = payload(request)
    if set(body) - {'cursor'}:
        raise cases.ComplaintCaseError('Reload the complaint activity and try again.')
    data = cases.case_history_page(group, source_case(group, case_key), actor, cursor=body.get('cursor', ''))
    return JsonResponse({'items': [{key: row.get(key, '') for key in (
        'id', 'action', 'status', 'note', 'created_at', 'updated_by', 'actor_affiliation', 'display_changes',
    )} for row in data['items']], 'next_cursor': data['next_cursor']})


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
    from core.services.miniapp_settings import PreferenceConflict, preference_payload, update_preference
    try:
        if request.method == 'POST':
            body = payload(request)
            values = body.get('preferences', {})
            if not isinstance(values, dict):
                raise ValueError
            filters = values.get('default_filters', {})
            if (not isinstance(filters, dict) or set(filters) - {'status', 'branch'}
                    or filters.get('status', '') not in {'', 'pending', 'resolved', 'all'}
                    or not isinstance(filters.get('branch', ''), str) or len(filters.get('branch', '')) > 150):
                raise ValueError
            update_preference(actor.user, 'complaint_cases', values, expected=body.get('expected'))
        return JsonResponse(preference_payload(actor.user, 'complaint_cases'))
    except PreferenceConflict as exc:
        return JsonResponse({'error': str(exc)}, status=409)
    except (ValidationError, ValueError, TypeError, AttributeError):
        raise cases.ComplaintCaseError('Review your preferences.') from None


@endpoint(['GET'])
def recovery(request, group, actor):
    # Browser-owned repair links only. Never forward Telegram action URLs.
    from django.db.models import Count
    rows = ParsedMessage.objects.filter(group_id=group.group_id,
        complaint_control__sync_status__in=['failed', 'pending', 'suspended'])
    totals = {row['complaint_control__sync_status']: row['count'] for row in
              rows.values('complaint_control__sync_status').annotate(count=Count('pk'))}
    counts = {status: totals.get(status, 0) for status in ('pending', 'failed', 'suspended')}
    counts['total'] = sum(counts.values())
    visible = rows.select_related('complaint_control').order_by('complaint_control__sync_status', 'pk')[:50]
    return JsonResponse({'counts': counts, 'issues': [{
        'key': str(row.pk), 'reference': row.complaint_control.reference_number,
        'status': row.complaint_control.sync_status,
        'can_retry': cases.complaint_sheet_projection_enabled(group)
            and cases.actor_can(group, actor, 'complaint.case.sync.retry', row),
    } for row in visible]})


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
    original_download = request.GET.get('download') == '1'
    item = cases.evidence_for_preview(group, actor, str(evidence_key), original_download=original_download)
    try:
        content = GoogleDriveMediaStorage().download(item.drive_file_id)
    except Exception:
        return JsonResponse({'error': 'The document could not be loaded. Try again shortly.'}, status=503)
    cases.record_evidence_preview(group, actor, item)
    extensions = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/webp': '.webp', 'application/pdf': '.pdf'}
    response = HttpResponse(content, content_type=item.mime_type if item.mime_type in extensions else 'application/octet-stream')
    response['Content-Disposition'] = content_disposition_header(
        original_download, item.original_filename or 'complaint-evidence' + extensions.get(item.mime_type, '.bin'))
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@endpoint(['POST'], 'complaint.case.evidence.view')
def evidence_preview(request, group, actor, evidence_key):
    """Browser-only, bounded raster page. Original files remain private downloads."""
    import re
    from core.services.order_approval import GoogleDriveMediaStorage
    from core.services.secure_media_preview import pdf_preview_html
    item = cases.evidence_for_preview(group, actor, str(evidence_key))
    body = payload(request)
    page = body.get('page', 1)
    thumbnail = body.get('thumbnail', False)
    if (set(body) - {'page', 'thumbnail'} or type(thumbnail) is not bool
            or type(page) is not int or not 1 <= page <= 10000
            or item.mime_type not in {'application/pdf', 'image/jpeg', 'image/png', 'image/webp'}
            or (item.mime_type != 'application/pdf' and page != 1)):
        raise cases.ComplaintCaseError('Choose a valid image or PDF page to preview.')
    try:
        content = GoogleDriveMediaStorage().download(item.drive_file_id)
        if item.mime_type == 'application/pdf':
            rendered = pdf_preview_html(content, item.original_filename or 'Complaint evidence',
                                        start_page=page, page_limit=1).decode('utf-8')
            total = int(re.search(r'data-total-pages="(\d+)"', rendered).group(1))
            image = re.search(r'<img src="(data:image/jpeg;base64,[A-Za-z0-9+/=]+)"', rendered).group(1)
            if page > total:
                raise ValueError('This page does not exist.')
        else:
            total = 1
        if thumbnail or item.mime_type != 'application/pdf':
            import base64
            from io import BytesIO
            from PIL import Image, ImageOps
            source = base64.b64decode(image.split(',')[1]) if item.mime_type == 'application/pdf' else content
            if not source or len(source) > 16 * 1024 * 1024:
                raise ValueError('Preview source is too large.')
            with Image.open(BytesIO(source)) as original:
                if original.width * original.height > 12_000_000:
                    raise ValueError('Preview dimensions are too large.')
                with ImageOps.exif_transpose(original).convert('RGB') as resized:
                    resized.thumbnail((320, 320) if thumbnail else (1920, 1920))
                    output = BytesIO()
                    resized.save(output, 'JPEG', quality=82)
                    image = 'data:image/jpeg;base64,' + base64.b64encode(output.getvalue()).decode('ascii')
    except Exception:
        return JsonResponse({'error': 'This file could not be previewed. Try again or download the original.'}, status=503)
    cases.record_evidence_preview(group, actor, item)
    response = JsonResponse({'image': image, 'page': page, 'page_count': total})
    response['Cache-Control'] = 'no-store, private'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@endpoint(['POST'], 'complaint.reports.view')
def reports(request, group, actor):
    from core.services.complaint_register import complaint_report_page, complaint_report_summary, REPORT_SORT_FIELDS
    params = payload(request)
    selection = params.get('selection', {})
    if (set(params) - REPORT_FIELDS - {'granularity', 'page', 'selection', 'sort', 'table_search'}
            or any(not isinstance(value, str) for key, value in params.items() if key not in {'page', 'selection'})
            or not isinstance(selection, dict) or set(selection) - REPORT_FIELDS
            or any(not isinstance(value, str) for value in selection.values())):
        raise cases.ComplaintCaseError('Review the report filters.')
    filters = {key: params[key] for key in REPORT_FIELDS if key in params}
    sort = params.get('sort', '-date_reported')
    if sort.lstrip('-') not in REPORT_SORT_FIELDS:
        raise cases.ComplaintCaseError('Choose a supported table sort.')
    # A drill-down changes the table/export cohort, not the chart that supplied
    # it. Keep both populations behind the existing canonical filter rules.
    table_filters = {**filters, **selection}
    if params.get('table_search'):
        if len(params['table_search']) > 150:
            raise cases.ComplaintCaseError('Use a shorter table search.')
        table_filters['search'] = params['table_search']
    table = complaint_report_page(filters=table_filters, page=params.get('page', 1), page_size=25, sort=sort)
    # Links only for complaints in this request's currently authorized workspace.
    keys = dict(ParsedMessage.objects.filter(group_id=group.group_id,
        complaint_control__reference_number__in=[row['complaint_id'] for row in table['results']])
        .values_list('complaint_control__reference_number', 'pk'))
    for row in table['results']:
        row['key'] = str(keys[row['complaint_id']]) if row['complaint_id'] in keys else ''
    previous = None
    from datetime import timedelta
    from django.utils.dateparse import parse_date
    start, end = parse_date(filters.get('date_from', '')), parse_date(filters.get('date_to', ''))
    if start and end and start <= end:
        span = end - start + timedelta(days=1)
        previous = complaint_report_summary(filters={**filters, 'date_from': (start - span).isoformat(),
            'date_to': (start - timedelta(days=1)).isoformat()}, granularity=params.get('granularity', 'month'))
    return JsonResponse({'summary': complaint_report_summary(filters=filters, granularity=params.get('granularity', 'month')),
                         'table': table, 'previous': {key: previous[key] for key in
                             ('total', 'pending', 'resolved', 'card_timing', 'card_coverage')} if previous else None})


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
