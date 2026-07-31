"""
Portal Mini App API views.

Endpoints for the JBL pipeline portal — imported into core/api/views.py.

Authentication: Telegram Mini App initData is passed as X-Telegram-Init-Data header.
Identity is derived from the initData user object (no STAFF sheet lookup).
Scope: records are aggregated only within the authenticated user's workflow,
branch, product, and group grants.
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from functools import wraps
from urllib.parse import parse_qsl, quote

from django.conf import settings
from django.contrib.auth import login
from django.core.exceptions import ValidationError
from django.core.signing import BadSignature, TimestampSigner
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.utils.dateparse import parse_datetime
from django.utils import timezone
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

logger = logging.getLogger(__name__)


# ── Identity helper ───────────────────────────────────────────────────────────

def _portal_init_data_from_request(request) -> str:
    return request.headers.get('X-Telegram-Init-Data', '') or request.POST.get('init_data', '')


def validate_portal_telegram_init_data(init_data: str) -> tuple[bool, str, dict]:
    """Validate Telegram Mini App initData before portal API access."""
    if not getattr(settings, 'PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH', True):
        return True, '', {}
    from core.services.telegram_identity import TelegramAuthenticationError, validate_telegram_init_data
    try:
        payload, _ = validate_telegram_init_data(
            init_data,
            max_age_seconds=int(getattr(settings, 'PORTAL_WEBAPP_AUTH_MAX_AGE_SECONDS', 86400)),
        )
        return True, '', payload
    except TelegramAuthenticationError as exc:
        return False, str(exc), {}


def portal_auth_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # A correlation id is assigned at the response boundary. Do not invent
        # a write id here: legacy cached clients must not receive a random key
        # that looks idempotent while their actual retry is not protected.
        request.portal_request_id = ''
        started_at = time.monotonic()
        is_valid, error, payload = validate_portal_telegram_init_data(
            _portal_init_data_from_request(request)
        )
        if not is_valid:
            response = JsonResponse({'ok': False, 'error': error}, status=403)
            return _finish_portal_response(request, response, started_at)
        request.portal_auth_payload = payload
        if getattr(settings, 'PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH', True):
            from core.services.telegram_identity import (
                TelegramIdentity, resolve_or_bind_telegram_user, user_access,
            )
            try:
                user = json.loads(payload.get('user') or '{}')
            except (TypeError, ValueError):
                user = {}
            telegram_id = str(user.get('id') or '')
            canonical_user = resolve_or_bind_telegram_user(TelegramIdentity(
                telegram_id=telegram_id,
                username=str(user.get('username') or '').strip().lstrip('@'),
                first_name=str(user.get('first_name') or '').strip(),
                last_name=str(user.get('last_name') or '').strip(),
                payload=user,
            ))
            access = user_access(canonical_user, 'jawabu_portal') if canonical_user else None
            if not (access and access['authorized']):
                account_label = f' (ID {telegram_id})' if telegram_id else ''
                response = JsonResponse({
                    'ok': False,
                    'error': f'Your Telegram account{account_label} is not authorized for the Jawabu Portal.',
                }, status=403)
                return _finish_portal_response(request, response, started_at)
            if access and access['authorized']:
                login(request, canonical_user, backend='core.auth_backends.TelegramMiniAppBackend')
                request.portal_user = canonical_user
                request.portal_access = access
        if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}:
            from core.services.miniapp_requests import (
                bind_miniapp_request_identity,
                idempotency_error_response,
            )
            try:
                bind_miniapp_request_identity(request, _portal_payload_for_request_identity(request))
            except ValueError as exc:
                return _finish_portal_response(request, idempotency_error_response(exc), started_at)
            # Maintenance is a read-only safety mode. A request already inside
            # a view remains allowed to finish; only newly admitted writes are
            # rejected, preventing an IT toggle from splitting a live upload.
            if view_func.__name__ != 'portal_set_maintenance':
                from core.services.portal_maintenance import maintenance_write_blocked

                blocked, message = maintenance_write_blocked()
                if blocked:
                    return _finish_portal_response(request, JsonResponse({
                        'ok': False,
                        'error': message,
                        'code': 'portal_read_only_maintenance',
                    }, status=503), started_at)
        else:
            # Read-only navigation is not an idempotent write, but preserve a
            # valid client correlation ID so browser/Telegram traces remain
            # continuous. Invalid optional read IDs never turn a safe screen
            # load into an error response.
            from core.services.miniapp_requests import validate_request_key
            try:
                request.portal_request_id = validate_request_key(request.headers.get('X-Request-ID', ''))
            except ValueError:
                request.portal_request_id = ''
        try:
            response = view_func(request, *args, **kwargs)
        except Exception:
            logger.exception(
                'Portal request failed: request_id=%s method=%s path=%s',
                request.portal_request_id, request.method, request.path,
            )
            raise
        return _finish_portal_response(request, response, started_at)
    return wrapper


def _portal_payload_for_request_identity(request) -> dict:
    """Read only the small request identity surface; views still parse bodies."""
    content_type = str(request.content_type or '').lower()
    if 'application/json' in content_type:
        try:
            payload = json.loads(request.body.decode('utf-8') or '{}')
            return payload if isinstance(payload, dict) else {}
        except (UnicodeDecodeError, ValueError):
            return {}
    if 'multipart/' in content_type or 'application/x-www-form-urlencoded' in content_type:
        return request.POST.dict()
    return {}


def _portal_sender_from_request(request) -> str:
    """Extract a human-readable sender label from validated Telegram initData."""
    payload = getattr(request, 'portal_auth_payload', None)
    if payload is None:
        payload = dict(parse_qsl(_portal_init_data_from_request(request), keep_blank_values=True))
    user_json = payload.get('user', '')
    if not user_json:
        return ''
    try:
        user = json.loads(user_json)
        first = user.get('first_name', '')
        last = user.get('last_name', '')
        username = user.get('username', '')
        if first or last:
            return f"{first} {last}".strip()
        if username:
            return f"@{username}"
        if user.get('id'):
            return f"telegram:{user['id']}"
    except Exception:
        pass
    return ''


def _portal_request_id(request, body: dict | None = None) -> str:
    """Use a real retry key for writes and a separate random correlation id.

    Older cached Mini Apps remain accepted while the setting is false, but no
    longer gain an accidental one-off idempotency key generated by the server.
    """
    from core.services.miniapp_requests import bind_miniapp_request_identity

    body = body or {}
    identity = bind_miniapp_request_identity(request, body)
    if identity.key:
        request.portal_request_id = identity.key
        return identity.key
    if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}:
        request.portal_request_id = getattr(request, 'portal_request_id', '') or uuid.uuid4().hex
        return ''
    value = getattr(request, 'portal_request_id', '') or uuid.uuid4().hex
    request.portal_request_id = value
    return value


def _portal_workflow_revision(body: dict) -> int:
    """Require the version displayed to the staff member before a write."""
    from core.services.workflow_transitions import parse_expected_revision

    raw = body.get('workflow_revision', body.get('revision'))
    return parse_expected_revision(raw)


def _approval_conditions_from_body(body: dict) -> list[str]:
    """Normalize a compact client payload without accepting arbitrary JSON."""
    raw = body.get('conditions') or []
    if isinstance(raw, str):
        raw = raw.splitlines()
    if not isinstance(raw, list):
        raise ValueError('conditions must be a list of short condition statements.')
    values = [str(value or '').strip() for value in raw if str(value or '').strip()]
    if any(len(value) > 500 for value in values):
        raise ValueError('Each approval condition must be 500 characters or fewer.')
    return values


def _portal_workflow_error(exc):
    """Map integrity failures to safe, actionable Mini App responses."""
    from core.services.workflow_transitions import WorkflowRevisionConflict, WorkflowRevisionRequired

    if isinstance(exc, WorkflowRevisionConflict):
        return JsonResponse({
            'ok': False,
            'error': str(exc),
            'code': exc.code,
            'expected_revision': exc.expected,
            'actual_revision': exc.actual,
        }, status=409)
    if isinstance(exc, WorkflowRevisionRequired):
        return JsonResponse({'ok': False, 'error': str(exc), 'code': exc.code}, status=428)
    return None


def _finish_portal_response(request, response, started_at: float):
    """Attach a correlation id to every authenticated portal response.

    The portal has several independently evolved clients. Adding the id at
    this boundary keeps their response shapes compatible while making a
    failed Drive/Sheets operation traceable from the browser to server logs.
    """
    # This boundary also serves denied requests. Never invoke strict write-key
    # validation while formatting a 403/500 response; authenticated writes are
    # bound before their view runs, while all other responses get correlation
    # only.
    identity = getattr(request, 'miniapp_request_identity', None)
    request_id = (
        getattr(request, 'portal_request_id', '')
        or getattr(identity, 'key', '')
        or uuid.uuid4().hex
    )
    request.portal_request_id = request_id
    response['X-Request-ID'] = request_id
    from core.services.miniapp_requests import attach_miniapp_request_metadata
    response = attach_miniapp_request_metadata(request, response)
    elapsed_ms = round((time.monotonic() - started_at) * 1000, 1)
    response['Server-Timing'] = f'portal;dur={elapsed_ms}'
    if isinstance(response, JsonResponse):
        try:
            payload = json.loads(response.content.decode(response.charset or 'utf-8'))
            if isinstance(payload, dict) and 'request_id' not in payload:
                payload['request_id'] = request_id
                response.content = json.dumps(payload, ensure_ascii=False).encode(response.charset or 'utf-8')
        except (TypeError, ValueError, UnicodeDecodeError):
            logger.warning('Could not attach portal request id to JSON response: %s', request_id)
    logger.info(
        'Portal request completed: request_id=%s method=%s path=%s status=%s duration_ms=%s',
        request_id, request.method, request.path, response.status_code, elapsed_ms,
    )
    return response


def _portal_actor_telegram_id(request) -> str:
    profile = getattr(getattr(request, 'portal_user', None), 'staff_profile', None)
    if profile:
        return str(profile.telegram_id)
    payload = getattr(request, 'portal_auth_payload', {})
    try:
        return str(json.loads(payload.get('user') or '{}').get('id') or '')
    except (TypeError, ValueError):
        return ''


def _pagination_window(request, total: int, page_size: int = 30):
    try:
        page = max(1, int(request.GET.get('page', 1)))
    except (ValueError, TypeError):
        page = 1
    start = (page - 1) * page_size
    end = start + page_size
    pagination = {
        'page': page,
        'page_size': page_size,
        'total': total,
        'pages': max(1, (total + page_size - 1) // page_size),
    }
    return start, end, pagination


def _paginate_qs(qs, request, page_size: int = 30):
    """Return a paginated slice and pagination metadata."""
    total = qs.count()
    start, end, pagination = _pagination_window(request, total, page_size)
    return list(qs[start:end]), pagination


def _numbered_farmer_cards(items, pagination, *, review_map=None):
    """Serialize one current page with ephemeral, human-facing positions.

    Queue positions are calculated from the active filter/page. They are never
    persisted or used as case, customer, order, or financial identifiers.
    """
    from core.services.jawabu_pipeline import farmer_to_card

    first_position = (int(pagination['page']) - 1) * int(pagination['page_size'])
    cards = []
    for offset, farmer in enumerate(items, start=1):
        card = farmer_to_card(farmer)
        if review_map is not None:
            card = _card_with_payment_review_metadata(farmer, card, review_map)
        card['display_number'] = first_position + offset
        cards.append(card)
    return cards


def _paginate_list(items: list, request, page_size: int = 30):
    """Return a paginated slice and pagination metadata for already-built portal payloads."""
    start, end, pagination = _pagination_window(request, len(items), page_size)
    return items[start:end], pagination


def _apply_county_branch_filters(qs, request, *, params=None):
    from django.db.models import Q

    params = params if params is not None else request.GET
    county = params.get('county', '').strip()
    branch = params.get('branch', '').strip()
    if county:
        qs = qs.filter(county__iexact=county)
    if branch:
        qs = qs.filter(branch__iexact=branch)
    access = getattr(request, 'portal_access', {})
    staff_branches = [str(value).strip() for value in access.get('branches', []) if str(value).strip()]
    if staff_branches:
        # Branch names are operational data and have historically varied in
        # casing.  Enforce the grant scope case-insensitively so a branch
        # user cannot accidentally see an empty queue (or bypass scope via a
        # differently-cased query value).
        branch_scope = Q()
        for staff_branch in staff_branches:
            branch_scope |= Q(branch__iexact=staff_branch)
        qs = qs.filter(branch_scope)
    return qs


def _apply_portal_ordering(qs, *, params):
    """Allow only the private workspace's safe alternate ordering."""
    return qs.order_by('-created_at') if str(params.get('ordering') or '').strip() == 'newest' else qs


PORTAL_VIEW_ROLES = {'viewer', 'jbl_officer', 'credit_analyst', 'head_rural', 'operations'}


def _portal_capability_error(request, capability: str, farmer=None):
    """Enforce the editable role matrix plus existing branch scope rules."""
    access = getattr(request, 'portal_access', None)
    if access is None:  # Authentication is intentionally disabled in local/test environments.
        return None
    from core.services.workflow_capabilities import has_capability

    if not has_capability(request.portal_user, 'jawabu_portal', capability, access=access):
        return JsonResponse({'ok': False, 'error': 'You are not authorized for this Jawabu workflow action.'}, status=403)
    from core.services.access_control import record_capability_usage
    record_capability_usage(request.portal_user, 'jawabu_portal', capability)
    return _portal_branch_scope_error(request, farmer)


def _portal_any_capability_error(request):
    """Allow shared Portal metadata for any user with at least one module."""
    access = getattr(request, 'portal_access', None)
    if access is None:
        return None
    from core.services.workflow_capabilities import effective_capability_keys

    if effective_capability_keys(request.portal_user, 'jawabu_portal', access=access):
        return None
    return JsonResponse({'ok': False, 'error': 'You are not authorized for the Jawabu Portal.'}, status=403)


def _portal_capabilities(request) -> list[str]:
    """Expose the same matrix result to the shell that guards the API."""
    from core.services.workflow_capabilities import capabilities_for_workflow, capabilities_payload

    if getattr(request, 'portal_access', None) is None:
        # Authentication-disabled local/test mode intentionally keeps the
        # complete existing portal usable without manufacturing a staff user.
        return sorted(item.key for item in capabilities_for_workflow('jawabu_portal'))
    return capabilities_payload(
        getattr(request, 'portal_user', None), 'jawabu_portal',
        access=getattr(request, 'portal_access', None),
    )


def _portal_branch_scope_error(request, farmer=None):
    """Apply an AccessGrant branch scope without assuming a screen capability."""
    access = getattr(request, 'portal_access', None)
    if access is None or farmer is None:
        return None
    branches = {str(value).strip().casefold() for value in access.get('branches', []) if str(value).strip()}
    if branches and str(farmer.branch or '').strip().casefold() not in branches:
        return JsonResponse({'ok': False, 'error': 'This case is outside your authorized branch scope.'}, status=403)
    return None


def _portal_read_access_error(request, farmer=None, capability='portal.case.read'):
    """Apply matrix and branch guards to read endpoints as well as writes."""
    return _portal_capability_error(request, capability, farmer)


def _portal_role_error(request, allowed_roles: set[str] | str, farmer=None):
    """Compatibility wrapper for old action callers during the portal rollout."""
    if isinstance(allowed_roles, str):
        from core.services.portal_permissions import portal_action_capability

        capability = portal_action_capability(allowed_roles)
        return _portal_capability_error(request, capability, farmer)
    # Pre-matrix readers share the ordinary case read capability.  New routes
    # should pass their explicit ``portal.*`` capability to the helper above.
    return _portal_capability_error(request, 'portal.case.read', farmer)


def _portal_approval_authority_error(request, farmer, gate: str):
    """Apply normal scope checks, then accept a valid temporary delegation."""
    access = getattr(request, 'portal_access', None)
    if access is None:
        return None
    from core.services.jawabu_approvals import approval_authority

    allowed, _role, _delegation = approval_authority(
        user=getattr(request, 'portal_user', None),
        access=access,
        gate=gate,
        farmer=farmer,
    )
    if not allowed:
        return JsonResponse({'ok': False, 'error': 'You are not authorized for this Portal approval gate.'}, status=403)
    return _portal_branch_scope_error(request, farmer)


def _portal_order_scope_error(request, order_number: str):
    """Check that every application in an order is inside the actor scope."""
    from core.models import JawabuApprovalDelegation, JawabuFarmerMaster

    farmers = JawabuFarmerMaster.objects.filter(order_number=order_number).only('branch')
    for farmer in farmers:
        access_error = _portal_branch_scope_error(request, farmer)
        if access_error:
            return access_error
    return None


def _portal_farmers_scope_error(request, farmers, allowed_roles=None):
    """Apply branch scope after the caller has checked its capability."""
    for farmer in farmers:
        scope_error = _portal_branch_scope_error(request, farmer)
        if scope_error:
            return scope_error
    return None


def _portal_scoped_farmers(farmers, request):
    """Filter an already-loaded batch to the actor's branch grants."""
    branches = {
        str(value).strip().casefold()
        for value in getattr(request, 'portal_access', {}).get('branches', [])
        if str(value).strip()
    }
    if not branches:
        return list(farmers)
    return [
        farmer for farmer in farmers
        if str(getattr(farmer, 'branch', '') or '').strip().casefold() in branches
    ]


def _portal_saved_document_in_scope(request, order_number: str, farmer_ids=None) -> bool:
    """Return whether a saved artifact belongs entirely to the actor's scope."""
    identifiers = {str(value) for value in (farmer_ids or []) if value}
    if identifiers:
        from core.models import JawabuFarmerMaster

        farmers = list(JawabuFarmerMaster.objects.filter(id__in=identifiers).only('branch'))
        # Do not show historical artifacts whose scope cannot be reconstructed
        # for a branch-limited account.
        if len(farmers) != len(identifiers):
            return not getattr(request, 'portal_access', {}).get('branches')
        return _portal_farmers_scope_error(request, farmers) is None
    return _portal_order_scope_error(request, order_number) is None


PORTAL_QUEUE_FRAGMENT_CONFIG = {
    'jbl': {'service': 'jbl_visit_queue', 'mode': 'jbl_visit', 'empty_title': 'JBL visit queue is clear', 'empty_sub': 'No farmer matches the current JBL visit filters.'},
    'credit': {'service': 'credit_queue', 'mode': 'credit', 'empty_title': 'Credit queue is clear', 'empty_sub': 'No farmer matches the current credit filters.'},
    'final': {'service': 'final_review_queue', 'mode': 'final_review', 'empty_title': 'Final review queue is clear', 'empty_sub': 'No client matches the current final review filters.'},
    'requisition': {'service': 'requisition_queue', 'mode': 'requisition', 'empty_title': 'No orders to assign', 'empty_sub': 'Approved cases awaiting an order number will appear here.'},
    'deferred': {'service': 'deferred_queue', 'mode': '', 'empty_title': 'No deferred cases', 'empty_sub': 'No deferred or flagged farmers match the current filters.'},
    'all': {'service': 'all_cases', 'mode': '', 'empty_title': 'No farmers found', 'empty_sub': 'Try a different search term or filter.'},
}

PORTAL_QUEUE_CAPABILITIES = {
    'jbl': 'portal.jbl_queue.view',
    'credit': 'portal.credit_queue.view',
    'final': 'portal.final_review.view',
    'requisition': 'portal.requisition.view',
    'deferred': 'portal.deferred.view',
    'all': 'portal.case.read',
}


def _portal_review_stage(request, params=None) -> str:
    """Normalize the three HOR review lenses exposed by the review page."""
    params = params if params is not None else request.GET
    value = str(params.get('stage') or params.get('review_stage') or 'decision').strip().lower()
    return value if value in {'decision', 'requisition', 'payment'} else 'decision'


def _pending_payment_review_map(request=None):
    """Return the newest pending payment document for each selected farmer.

    Payment review is a batch checkpoint, but the review page is case based.
    Keeping this indirection in one helper prevents a farmer from appearing in
    two pending payment batches and makes the review page match the exact
    snapshot that will be approved.
    """
    from core.models import PaymentDocument

    pending = {}
    documents = PaymentDocument.objects.filter(status='pending_review').order_by('-created_at')
    for document in documents:
        if request is not None and not _portal_saved_document_in_scope(
            request, document.order_number, document.farmer_ids,
        ):
            continue
        for farmer_id in document.farmer_ids or []:
            pending.setdefault(str(farmer_id), document)
    return pending


def _payment_review_queryset(request, *, params=None):
    """Return active farmers and their pending payment-review metadata."""
    from core.models import JawabuApprovalDelegation, JawabuFarmerMaster

    review_map = _pending_payment_review_map(request)
    if not review_map:
        return JawabuFarmerMaster.objects.none(), review_map
    queryset = JawabuFarmerMaster.objects.filter(
        status='active', id__in=list(review_map),
    )
    return _apply_county_branch_filters(queryset, request, params=params), review_map


def _card_with_payment_review_metadata(farmer, card, review_map):
    document = review_map.get(str(farmer.id))
    if not document:
        return card
    card.update({
        'payment_review_document_id': str(document.id),
        'payment_review_payment_number': document.payment_number,
        'payment_review_order_number': ', '.join(
            (document.validation_summary or {}).get('order_numbers') or [document.order_number]
        ),
        'payment_review_version': document.version,
        'payment_review_created_at': document.created_at.isoformat() if document.created_at else None,
    })
    return card


def _portal_queue_queryset(queue_key: str, request, *, params=None):
    from core.services import jawabu_pipeline

    config = PORTAL_QUEUE_FRAGMENT_CONFIG.get(queue_key)
    if not config:
        return None, None
    params = params if params is not None else request.GET

    if queue_key == 'all':
        qs = jawabu_pipeline.all_cases(
            search=params.get('search', '').strip(),
            county=params.get('county', '').strip(),
            branch=params.get('branch', '').strip(),
        )
        qs = _apply_county_branch_filters(qs, request, params=params)
    else:
        if queue_key == 'final':
            stage = _portal_review_stage(request, params=params)
            if stage == 'requisition':
                qs = jawabu_pipeline.requisition_queue()
            elif stage == 'payment':
                qs, _review_map = _payment_review_queryset(request, params=params)
            else:
                qs = jawabu_pipeline.final_review_queue()
        else:
            service = getattr(jawabu_pipeline, config['service'])
            qs = service(params.get('search', '').strip()) if queue_key == 'jbl' else service()
        qs = _apply_county_branch_filters(qs, request, params=params)
    return _apply_portal_ordering(qs, params=params), config


# ── Render View ───────────────────────────────────────────────────────────────


def _batch_download_url(request, order_number: str) -> str:
    # Excel links are opened in Telegram's system browser, which cannot send
    # the Mini App initData header.  Bind a short-lived signed URL to the
    # already-authorized batch instead of weakening the API download route.
    token = TimestampSigner(salt='portal-requisition-download').sign(str(order_number))
    return request.build_absolute_uri(
        f'/api/portal/requisition-download/{quote(token, safe="")}/'
    )


def _jbl_media_open_url(request, farmer_id: str, *, attachment_id: str = '', legacy_index: int | None = None) -> str:
    """Issue a short-lived external-browser link after Mini App authorization.

    Telegram's external browser cannot replay the Mini App ``initData`` header.
    The signed payload is deliberately scoped to one authorised user, one case,
    and one evidence item; it is not a replacement for the protected API route.
    """
    actor = getattr(request, 'portal_user', None)
    payload = json.dumps({
        'attachment_id': str(attachment_id or ''),
        'farmer_id': str(farmer_id),
        'legacy_index': legacy_index,
        'request_id': _portal_request_id(request),
        'user_id': str(getattr(actor, 'pk', '') or ''),
    }, sort_keys=True, separators=(',', ':'))
    token = TimestampSigner(salt='portal-jbl-media-open').sign(payload)
    return request.build_absolute_uri(
        f'/api/portal/jbl-media-open/{quote(token, safe="")}/'
    )


def _upload_generated_workbook_to_drive(data: bytes, filename: str, order_number: str) -> tuple[str, str]:
    """Store a generated workbook in the shared Google Drive media folder."""
    from django.utils import timezone
    from core.services.order_approval import GoogleDriveMediaStorage

    return GoogleDriveMediaStorage().upload(
        data,
        filename=filename,
        mime_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        id_number='generated_workbooks',
        received_at=timezone.now(),
        group_config=None,
        workflow_key='Jawabu/Requisitions',
        record_type='Order',
        record_key=order_number,
    )


def _invoice_summary_for_farmers(farmers) -> dict:
    total = len(farmers)
    invoiced = sum(1 for farmer in farmers if getattr(farmer, 'invoice_number', ''))
    pending = max(total - invoiced, 0)
    if total and invoiced == total:
        status = 'completed'
    elif invoiced:
        status = 'partially_invoiced'
    else:
        status = 'generated'
    return {
        'total_clients': total,
        'invoiced_count': invoiced,
        'pending_invoice_count': pending,
        'status': status,
    }


def _invoice_summary_for_batch(farmers, stored_summary=None) -> dict:
    """Recalculate invoice counts without discarding upload audit metadata."""
    # Farmer invoice fields are canonical for counts. Upload status/error and
    # the invoice-batch reference are workflow metadata and must survive a
    # later order regeneration or preview update.
    return {
        **(stored_summary or {}),
        **_invoice_summary_for_farmers(farmers),
    }


def _validate_requisition_farmers(farmers) -> tuple[list[dict], list[dict], list[dict]]:
    from core.services.jawabu_pipeline import farmer_to_card
    from core.services.requisition import requisition_order_deposit_values

    ready = []
    blocked = []
    warnings = []
    for farmer in farmers:
        card = farmer_to_card(farmer)
        hbg_deposit, jbl_deposit = requisition_order_deposit_values(farmer)
        card['requisition_preview'] = {
            'location': ' - '.join(part for part in (
                str(farmer.sub_county or '').strip(), str(farmer.village or '').strip(),
            ) if part),
            'hbg_deposit': str(hbg_deposit) if hbg_deposit is not None else '',
            'jbl_deposit': str(jbl_deposit) if jbl_deposit is not None else '',
        }
        missing = []
        if farmer.final_decision != 'Approved':
            missing.append(f"Final Decision is {farmer.final_decision or 'not set'}")
        if not farmer.customer_name:
            missing.append('Customer Name')
        if not farmer.customer_no:
            missing.append('Customer No')
        if not farmer.imab_created:
            missing.append('IMAB status')
        if not str(farmer.sub_county or '').strip():
            missing.append('Constituency')
        if not str(farmer.village or '').strip():
            missing.append('Village')
        if not farmer.national_id:
            warnings.append({'farmer_id': str(farmer.id), 'message': f'{farmer.customer_name or farmer.id}: National ID is blank.'})
        if not farmer.primary_phone:
            warnings.append({'farmer_id': str(farmer.id), 'message': f'{farmer.customer_name or farmer.id}: Primary phone is blank.'})
        if missing:
            blocked.append({'farmer': card, 'missing': missing})
        else:
            ready.append(card)
    return ready, blocked, warnings


def _farmers_for_batch(order_number: str, farmer_ids=None):
    from django.db.models import Q
    from core.models import JawabuFarmerMaster

    if farmer_ids:
        # Older batch rows stored only the newly-added IDs. Always union the
        # persisted snapshot with every master record carrying this order so
        # historical batches show their original clients as well.
        return list(
            JawabuFarmerMaster.objects
            .filter(Q(order_number=order_number) | Q(id__in=farmer_ids))
            .distinct()
            .order_by('customer_name')
        )
    return list(JawabuFarmerMaster.objects.filter(order_number=order_number).order_by('customer_name'))


def _requisition_order_context(order_number: str, selected_ids=None):
    """Return the already-known clients and stored batch for an order number.

    An order can be assigned before its Excel is generated, so both the
    farmer master records and the persisted batch snapshot are consulted.  A
    batch snapshot is never allowed to replace the clients already attached
    to the same order; it is an additional source of IDs during reconciliation.
    """
    from core.models import JawabuFarmerMaster, RequisitionBatch

    selected = {str(value) for value in (selected_ids or [])}
    existing = list(
        JawabuFarmerMaster.objects.filter(order_number=order_number)
        .exclude(id__in=selected)
        .order_by('customer_name')
    )
    batch = RequisitionBatch.objects.filter(order_number=order_number).first()
    batch_ids = [str(value) for value in (batch.farmer_ids or [])] if batch else []
    if batch_ids:
        known_ids = {str(farmer.id) for farmer in existing}
        missing_ids = [value for value in batch_ids if value not in known_ids and value not in selected]
        if missing_ids:
            existing.extend(JawabuFarmerMaster.objects.filter(id__in=missing_ids).order_by('customer_name'))
    return existing, batch


def _merge_requisition_farmers(selected_farmers, order_number: str, selected_ids=None):
    """Merge original order clients with the newly selected clients."""
    existing, batch = _requisition_order_context(order_number, selected_ids)
    merged = {}
    for farmer in existing:
        merged[str(farmer.id)] = farmer
    for farmer in selected_farmers:
        merged[str(farmer.id)] = farmer
    return list(merged.values()), batch


def _coerce_requisition_date(value):
    """Return a date for legacy DateField/text values used in order checks."""
    if not value:
        return None
    from datetime import date as _date, datetime as _datetime

    if isinstance(value, _datetime):
        return value.date()
    if isinstance(value, _date):
        return value
    from core.services.jawabu_validation import parse_business_date
    return parse_business_date(value)


def _requisition_order_dates(existing, batch) -> set:
    """Return canonical dates, preferring current farmer records over snapshots.

    RequisitionBatch is a historical snapshot and may retain a date from an
    older generation. The farmer master rows are canonical, so a stale batch
    date must not block reusing an order when every current farmer agrees.
    """
    farmer_dates = {
        parsed
        for farmer in existing
        if (parsed := _coerce_requisition_date(getattr(farmer, 'requisition_date', None)))
    }
    if farmer_dates:
        return farmer_dates
    batch_date = _coerce_requisition_date(getattr(batch, 'requisition_date', None)) if batch else None
    return {batch_date} if batch_date else set()


def _format_requisition_date(value):
    parsed = _coerce_requisition_date(value)
    return parsed.strftime('%d-%B-%Y') if parsed else str(value or '')


def _requisition_order_date_conflict(
    order_number: str,
    requested_date,
    selected_ids=None,
    *,
    allow_known_date_when_inconsistent: bool = False,
):
    """Return a stable error when one order is given a new requisition date.

    Older batches can contain clients with different dates. The confirmed
    requisition preview may repair that inconsistency when staff explicitly
    choose one of the dates already present; direct single-client assignment
    remains strict so it cannot silently leave a split batch behind.
    """
    existing, batch = _requisition_order_context(order_number, selected_ids)
    dates = _requisition_order_dates(existing, batch)
    if not dates:
        return '', existing, batch
    requested = _coerce_requisition_date(requested_date)
    if requested in dates and (
        len(dates) == 1 or allow_known_date_when_inconsistent
    ):
        return '', existing, batch
    labels = ', '.join(sorted(_format_requisition_date(value) for value in dates))
    return (
        f"Order number {order_number} already has requisition date {labels}. "
        f"Use the same date for this order or choose a new order number; "
        "the existing batch was not changed.",
        existing,
        batch,
    )


def _serialize_batch(batch, farmers, request, include_farmers: bool = True) -> dict:
    summary = _invoice_summary_for_batch(farmers, batch.invoice_summary)
    farmers_payload = []
    if include_farmers:
        for farmer in farmers:
            farmers_payload.append({
                'id': str(farmer.id),
                'customer_name': farmer.customer_name,
                'national_id': farmer.national_id,
                'primary_phone': farmer.primary_phone,
                'county': farmer.county,
                'sub_county': farmer.sub_county,
                'village': farmer.village,
                'branch': farmer.branch,
                'hb_sales_person': farmer.hb_sales_person,
                'credit_decision': farmer.credit_decision,
                'final_decision_comment': farmer.final_decision_comment,
                'customer_no': farmer.customer_no,
                'imab_customer_name': farmer.imab_customer_name,
                'lead_source': farmer.lead_source,
                'actual_receipts': str(farmer.actual_receipts) if farmer.actual_receipts is not None else '',
                'deposit_paid_hbg': str(farmer.deposit_paid_hbg) if farmer.deposit_paid_hbg is not None else '',
                'system_deposit_paid_jbl': str(farmer.system_deposit_paid_jbl) if farmer.system_deposit_paid_jbl is not None else '',
                'invoice_number': farmer.invoice_number,
                'invoice_date': farmer.invoice_date.strftime('%Y-%m-%d') if farmer.invoice_date else None,
                'invoice_amount': str(farmer.invoice_amount) if farmer.invoice_amount is not None else None,
                'balance_due': str(farmer.balance_due) if farmer.balance_due is not None else None,
                'invoiced': bool(farmer.invoice_number),
                'workflow_revision': farmer.workflow_revision,
            })
    return {
        'id': str(batch.id),
        'order_number': batch.order_number,
        'version': getattr(batch, 'version', 0) or 0,
        'preview_version': getattr(batch, 'preview_version', 0) or 0,
        'requisition_date': batch.requisition_date.strftime('%Y-%m-%d') if batch.requisition_date else None,
        'generated_by': batch.generated_by,
        'generated_at': batch.created_at.isoformat() if batch.created_at else None,
        'updated_at': batch.updated_at.isoformat() if batch.updated_at else None,
        'filename': batch.filename,
        'has_requisition_file': bool(batch.file_content),
        'download_url': _batch_download_url(request, batch.order_number) if batch.file_content else '',
        'drive_url': getattr(batch, 'drive_url', '') or '',
        'drive_file_id': getattr(batch, 'drive_file_id', '') or '',
        'drive_upload_error': getattr(batch, 'drive_upload_error', '') or '',
        'drive_sync_status': _artifact_sync_status(
            getattr(batch, 'drive_url', '') or '',
            getattr(batch, 'drive_upload_error', '') or '',
        ),
        'drive_sync_attempts': getattr(batch, 'drive_sync_attempts', 0) or 0,
        'drive_next_retry_at': batch.drive_next_retry_at.isoformat() if getattr(batch, 'drive_next_retry_at', None) else None,
        'preview_filename': getattr(batch, 'preview_filename', '') or '',
        'preview_drive_url': getattr(batch, 'preview_drive_url', '') or '',
        'preview_drive_file_id': getattr(batch, 'preview_drive_file_id', '') or '',
        'preview_generated_by': getattr(batch, 'preview_generated_by', '') or '',
        'preview_generated_at': batch.preview_generated_at.isoformat() if getattr(batch, 'preview_generated_at', None) else None,
        'preview_error': getattr(batch, 'preview_error', '') or '',
        'preview_sync_status': _artifact_sync_status(
            getattr(batch, 'preview_drive_url', '') or '',
            getattr(batch, 'preview_error', '') or '',
        ),
        'preview_drive_sync_attempts': getattr(batch, 'preview_drive_sync_attempts', 0) or 0,
        'preview_drive_next_retry_at': batch.preview_drive_next_retry_at.isoformat() if getattr(batch, 'preview_drive_next_retry_at', None) else None,
        # The master records are canonical. Recalculate this instead of
        # trusting a stale snapshot count from an older append-only update.
        'farmer_count': len(farmers),
        'invoiced_count': summary.get('invoiced_count', 0),
        'status': batch.status,
        'invoice_summary': summary,
        'amount_summary': _batch_amount_summary(farmers),
        'last_invoice_result': batch.last_invoice_result or {},
        'farmers': farmers_payload,
    }


def _artifact_sync_status(url: str, error: str) -> str:
    """Return one stable sync state for workbook/document consumers."""
    if str(error or '').strip():
        if 'pending' in str(error).casefold():
            return 'pending'
        return 'retryable_failure'
    if str(url or '').strip():
        return 'succeeded'
    return 'not_requested'


def _batch_amount_summary(farmers) -> dict:
    from decimal import Decimal, InvalidOperation
    from core.services.requisition import requisition_order_deposit_values

    keys = ('deposit_hb', 'deposit_jbl', 'invoice_amount', 'discount', 'payment', 'balance_due')
    totals = {key: Decimal('0') for key in keys}
    present = {key: False for key in keys}
    for farmer in farmers:
        deposit_hb, deposit_jbl = requisition_order_deposit_values(farmer)
        raw = {
            'deposit_hb': deposit_hb,
            'deposit_jbl': deposit_jbl,
            'invoice_amount': farmer.invoice_amount,
            'discount': farmer.discount,
            'payment': farmer.payment,
            'balance_due': farmer.balance_due,
        }
        for key, value in raw.items():
            if value in (None, ''):
                continue
            try:
                amount = Decimal(str(value).replace(',', ''))
            except InvalidOperation:
                continue
            totals[key] += amount
            present[key] = True
    return {key: str(totals[key]) if present[key] else None for key in keys}


def _parse_requisition_workbook_payload(request, *, allow_blocked: bool = False):
    from datetime import date as _date
    from core.models import JawabuFarmerMaster

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return None, JsonResponse({'ok': False, 'error': 'Invalid JSON body.'}, status=400)

    farmer_ids = body.get('farmer_ids') or []
    order_number = str(body.get('order_number') or '').strip()
    requisition_date_raw = str(body.get('requisition_date') or '').strip()

    if not farmer_ids:
        return None, JsonResponse({'ok': False, 'error': 'No farmers selected.'}, status=400)
    if not order_number:
        return None, JsonResponse({'ok': False, 'error': 'Order Number / Batch Ref is required.'}, status=400)
    if not requisition_date_raw:
        return None, JsonResponse({'ok': False, 'error': 'Requisition Date is required.'}, status=400)

    try:
        requisition_date = _date.fromisoformat(requisition_date_raw)
    except ValueError:
        return None, JsonResponse(
            {'ok': False, 'error': f"Invalid requisition_date '{requisition_date_raw}'. Use YYYY-MM-DD."},
            status=400,
        )

    farmers = list(JawabuFarmerMaster.objects.filter(id__in=farmer_ids))
    if len(farmers) != len(farmer_ids):
        return None, JsonResponse({'ok': False, 'error': 'One or more selected farmers not found.'}, status=404)

    farmers, batch = _merge_requisition_farmers(farmers, order_number, farmer_ids)
    access_error = _portal_farmers_scope_error(request, farmers)
    if access_error:
        return None, access_error

    date_error, existing_farmers, existing_batch = _requisition_order_date_conflict(
        order_number,
        requisition_date,
        None,
        allow_known_date_when_inconsistent=True,
    )
    if date_error:
        return None, JsonResponse({'ok': False, 'error': date_error, 'code': 'requisition_date_conflict'}, status=409)

    ready, blocked, warnings = _validate_requisition_farmers(farmers)
    known_dates = _requisition_order_dates(existing_farmers, existing_batch)
    if len(known_dates) > 1 and requisition_date in known_dates:
        labels = ', '.join(sorted(_format_requisition_date(value) for value in known_dates))
        warnings.append({
            'message': (
                f"Order {order_number} has inconsistent existing requisition dates ({labels}). "
                f"This preview uses {_format_requisition_date(requisition_date)} and generation "
                "will normalize all clients in the batch to that date."
            ),
        })
    if blocked and not allow_blocked:
        first = blocked[0]
        name = first['farmer'].get('customer_name') or first['farmer'].get('national_id') or 'Selected client'
        return None, JsonResponse({
            'ok': False,
            'error': f"{name} is not ready for requisition: {', '.join(first['missing'])}.",
            'blocked': blocked,
            'warnings': warnings,
        }, status=403)

    selected_id_set = {str(value) for value in farmer_ids}
    return {
        'body': body,
        'farmers': farmers,
        'farmer_ids': farmer_ids,
        'order_number': order_number,
        'requisition_date': requisition_date,
        'existing_order_count': len([farmer for farmer in existing_farmers if str(farmer.id) not in selected_id_set]),
        'existing_order_farmer_ids': [
            str(farmer.id) for farmer in existing_farmers
            if str(farmer.id) not in selected_id_set
        ],
        'existing_batch': batch,
        'ready': ready,
        'blocked': blocked,
        'warnings': warnings,
    }, None


def _requisition_assignment_revisions(body: dict, farmers, order_number: str, requisition_date):
    """Return the displayed revisions for cases that this request will order.

    Regenerating an already assigned batch does not change a case, so it does
    not need a revision. Assigning an order does; accepting a batch without
    those per-case revisions would otherwise reintroduce lost updates through
    the multi-select path.
    """
    from core.services.workflow_transitions import parse_expected_revision

    supplied = body.get('workflow_revisions') or {}
    if not isinstance(supplied, dict):
        raise ValueError('workflow_revisions must identify each selected case by ID.')
    expected: dict[str, int] = {}
    for farmer in farmers:
        if farmer.order_number == order_number and farmer.requisition_date == requisition_date:
            continue
        expected[str(farmer.id)] = parse_expected_revision(supplied.get(str(farmer.id)))
    return expected


def _portal_requisition_batches_payload(request) -> tuple[list[dict], dict]:
    from django.db.models import Count, Max
    from core.models import JawabuFarmerMaster, RequisitionBatch

    county = (request.GET.get('county') or '').strip().lower()
    branch = (request.GET.get('branch') or '').strip().lower()

    batches_list = []
    seen_orders = set()
    for batch in RequisitionBatch.objects.all().order_by('-requisition_date', '-updated_at'):
        all_farmers = _farmers_for_batch(batch.order_number, batch.farmer_ids or None)
        farmers = _portal_scoped_farmers(
            all_farmers, request,
        )
        if len(farmers) != len(all_farmers):
            # Do not expose a mixed-branch batch with a misleading total.
            continue
        if county:
            farmers = [farmer for farmer in farmers if (farmer.county or '').lower() == county]
        if branch:
            farmers = [farmer for farmer in farmers if (farmer.branch or '').lower() == branch]
        if (county or branch) and not farmers:
            continue
        batches_list.append(_serialize_batch(batch, farmers, request))
        seen_orders.add(batch.order_number)

    qs = JawabuFarmerMaster.objects.filter(order_number__isnull=False).exclude(order_number='')
    staff_branches = [
        str(value).strip() for value in getattr(request, 'portal_access', {}).get('branches', [])
        if str(value).strip()
    ]
    if staff_branches:
        from django.db.models import Q
        branch_scope = Q()
        for staff_branch in staff_branches:
            branch_scope |= Q(branch__iexact=staff_branch)
        qs = qs.filter(branch_scope)
    if county:
        qs = qs.filter(county__iexact=county)
    if branch:
        qs = qs.filter(branch__iexact=branch)
    legacy_data = qs.exclude(order_number__in=seen_orders).values('order_number').annotate(
        req_date=Max('requisition_date'),
        farmer_count=Count('id'),
    )
    for item in legacy_data:
        order_no = item['order_number']
        farmers = list(qs.filter(order_number=order_no).order_by('customer_name'))
        summary = _invoice_summary_for_farmers(farmers)
        pseudo = RequisitionBatch(
            order_number=order_no,
            requisition_date=item['req_date'],
            farmer_count=item['farmer_count'],
            status=summary.get('status', 'generated'),
            invoice_summary=summary,
        )
        payload = _serialize_batch(pseudo, farmers, request)
        payload.update({
            'id': '',
            'generated_by': '',
            'generated_at': '',
            'updated_at': '',
            'filename': '',
            'has_requisition_file': False,
            'download_url': '',
            'preview_drive_url': '',
            'preview_generated_at': None,
            'last_invoice_result': {},
        })
        batches_list.append(payload)

    batches_list.sort(
        key=lambda item: (item.get('requisition_date') or '', item.get('updated_at') or '', item.get('order_number') or ''),
        reverse=True,
    )
    return _paginate_list(batches_list, request)

@require_http_methods(["GET", "HEAD"])
def portal_home(request):
    return portal_screen(request, 'dashboard')


def _portal_screen_context(screen: str, **extra) -> dict:
    return {
        'active_screen': screen,
        'invoice_upload_max_file_size_mb': int(getattr(settings, 'INVOICE_UPLOAD_MAX_FILE_SIZE_MB', 8) or 8),
        **extra,
    }


@portal_auth_required
def _portal_screen_fragment(request, screen: str, context: dict | None = None):
    from core.services.portal_navigation import portal_screen_allowed
    if not portal_screen_allowed(getattr(request, 'portal_user', None), screen, access=getattr(request, 'portal_access', None)):
        return HttpResponse(
            '<section class="shell-error" role="alert"><h2>Access denied</h2>'
            '<p>Your Portal role cannot open this screen.</p></section>',
            status=403,
        )
    return render(request, 'portal/portal.html', context or _portal_screen_context(screen))


@require_http_methods(["GET", "HEAD"])
def portal_screen(request, screen: str):
    """Return the persistent shell on cold loads and authenticated content to htmx.

    The Portal's tabs intentionally share one fragment because its existing
    workflow overlays and client state span queues. The screen URL selects the
    active section while keeping that shared markup as the single source.
    """
    from core.services.portal_navigation import PORTAL_NAV_ITEMS, PORTAL_PERSONAL_NAV_ITEM
    known_screens = {item[0] for item in PORTAL_NAV_ITEMS} | {PORTAL_PERSONAL_NAV_ITEM[0]}
    if screen not in known_screens:
        return HttpResponse('Unknown portal screen.', status=404)
    if request.htmx:
        return _portal_screen_fragment(request, screen)
    return render(request, 'portal/portal_screen_full.html', _portal_screen_context(screen))


@require_http_methods(["GET", "HEAD"])
def portal_case_history_detail(request, farmer_id: str):
    """Render one customer's Case 360 as a dedicated navigable screen."""
    context = _portal_screen_context('case_history', case_history_farmer_id=farmer_id)
    if request.htmx:
        return _portal_screen_fragment(request, 'case_history', context=context)
    return render(request, 'portal/portal_screen_full.html', context)


@portal_auth_required
@require_http_methods(["GET"])
def portal_navigation(request):
    """Render only links authorized for the authenticated Telegram staff member."""
    from core.services.portal_navigation import get_portal_nav_items
    return render(request, 'portal/partials/navigation.html', {
        'nav_items': get_portal_nav_items(getattr(request, 'portal_user', None), access=getattr(request, 'portal_access', None)),
        'active_screen': request.GET.get('active', 'dashboard'),
    })


def _portal_setting_options(request, actor) -> dict:
    """Return the authenticated user's valid personal Portal configuration."""
    from core.services.branches import global_branch_choices
    from core.services.portal_navigation import get_portal_nav_items
    from core.services.workflow_capabilities import has_capability

    access = getattr(request, 'portal_access', None)
    screens = [
        item for item in get_portal_nav_items(actor, access=access)
        if item['key'] != 'settings'
    ]
    staff_branches = {
        str(value).strip().casefold()
        for value in (access or {}).get('branches', [])
        if str(value).strip()
    }
    branches = global_branch_choices()
    if staff_branches:
        branches = [branch for branch in branches if branch.casefold() in staff_branches]
    return {
        'screens': screens,
        'queues': [item for item in screens if item['key'] in PORTAL_QUEUE_FRAGMENT_CONFIG],
        'branches': branches,
        'review_statuses': [
            {'value': 'decision', 'label': 'Final decisions'},
            {'value': 'payment', 'label': 'Payment batches awaiting review'},
        ],
        'operations': {
            'health': has_capability(actor, 'jawabu_portal', 'portal.health.read', access=access),
            'maintenance': has_capability(actor, 'jawabu_portal', 'portal.health.maintenance.manage', access=access),
            'delegation': has_capability(actor, 'jawabu_portal', 'portal.approval.delegation.authorize', access=access),
        },
    }


def _portal_workspace_options(request, actor) -> dict:
    """Flatten settings options into a stable service-validation contract."""
    values = _portal_setting_options(request, actor)
    return {
        'screens': [item['key'] for item in values['screens']],
        'queues': [item['key'] for item in values['queues']],
        'branches': values['branches'],
        'review_statuses': [item['value'] for item in values['review_statuses']],
    }


def _portal_workspace_access_error(request):
    """Keep paused personal-workspace data unavailable outside the IT role."""
    return _portal_capability_error(request, 'portal.workspace.manage')


@portal_auth_required
@csrf_exempt  # Verified Telegram initData is the non-cookie authentication mechanism.
@require_http_methods(["GET", "POST"])
def portal_settings(request):
    """Read or save the authenticated user's Portal-only preferences."""
    actor = getattr(request, 'portal_user', None)
    if actor is None:
        return JsonResponse({'ok': False, 'error': 'Your Portal staff account could not be resolved.'}, status=403)
    from core.services.miniapp_settings import account_summary_payload, preference_payload, update_preference

    if request.method == 'GET':
        return JsonResponse({'ok': True, 'data': {
            'personal': preference_payload(actor, 'jawabu_portal'),
            'account': account_summary_payload(
                actor,
                'jawabu_portal',
                roles=(getattr(request, 'portal_access', None) or {}).get('roles', []),
                branches=(getattr(request, 'portal_access', None) or {}).get('branches', []),
                products=(getattr(request, 'portal_access', None) or {}).get('products', []),
            ),
            **_portal_setting_options(request, actor),
        }})
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except (UnicodeDecodeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'Settings request must be valid JSON.'}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({'ok': False, 'error': 'Settings request must be a JSON object.'}, status=400)
    try:
        preferences = payload.get('preferences') or {}
        if not isinstance(preferences, dict):
            raise ValueError('Preferences must be a JSON object.')
        options = _portal_setting_options(request, actor)
        allowed_screens = {item['key'] for item in options['screens']}
        allowed_queues = {item['key'] for item in options['queues']}
        allowed_branches = {str(value).strip().casefold(): str(value).strip() for value in options['branches']}
        default_screen = str(preferences.get('default_screen') or '').strip()
        filters = preferences.get('default_filters') or {}
        if default_screen and default_screen not in allowed_screens:
            raise ValueError('Choose a landing screen available to your Portal access.')
        if not isinstance(filters, dict):
            raise ValueError('Saved filters must be a JSON object.')
        queue = str(filters.get('queue') or '').strip()
        branch = str(filters.get('branch') or '').strip()
        review_status = str(filters.get('status') or '').strip()
        if queue and queue not in allowed_queues:
            raise ValueError('Choose a work queue available to your Portal access.')
        if branch and branch.casefold() not in allowed_branches:
            raise ValueError('Choose a branch within your Portal access scope.')
        if review_status and review_status not in {'decision', 'payment'}:
            raise ValueError('Choose a valid default review list.')
        if branch:
            preferences = {
                **preferences,
                'default_filters': {**filters, 'branch': allowed_branches[branch.casefold()]},
            }
        return JsonResponse({'ok': True, 'data': update_preference(actor, 'jawabu_portal', preferences)})
    except ValueError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)


def _portal_delegation_payload(delegation) -> dict:
    """Serialize a staff-only delegation record without exposing profile metadata."""
    return {
        'id': str(delegation.pk),
        'delegate': delegation.delegate.get_full_name() or delegation.delegate.get_username(),
        'gate': delegation.gate,
        'gate_label': delegation.get_gate_display(),
        'branch': delegation.branch,
        'product': delegation.product,
        'reason': delegation.reason,
        'authorized_by': delegation.authorized_by.get_full_name() or delegation.authorized_by.get_username(),
        'starts_at': delegation.starts_at.isoformat(),
        'expires_at': delegation.expires_at.isoformat(),
        'active': delegation.active,
        'revoked_at': delegation.revoked_at.isoformat() if delegation.revoked_at else '',
        'revocation_reason': delegation.revocation_reason,
    }


def _portal_delegation_candidates(access, actor) -> list[dict]:
    """Return staff candidates with only the branch scopes the issuer may grant."""
    from django.contrib.auth import get_user_model
    from core.services.branches import global_branch_choices
    from core.services.telegram_identity import user_access

    def scope_values(snapshot) -> set[str]:
        return {
            str(value).strip().casefold()
            for value in (snapshot or {}).get('branches', [])
            if str(value).strip()
        }

    def has_global_scope(snapshot) -> bool:
        return any(not str(getattr(grant, 'branch', '') or '').strip() for grant in (snapshot or {}).get('grants', []))

    configured = [str(value).strip() for value in global_branch_choices() if str(value).strip()]
    issuer_branches = scope_values(access)
    issuer_global = has_global_scope(access)
    candidates = []
    users = get_user_model().objects.filter(
        is_active=True,
        access_grants__workflow='jawabu_portal',
        access_grants__active=True,
    ).distinct().order_by('first_name', 'last_name', 'username')
    for user in users:
        if user.pk == actor.pk:
            continue
        delegate_access = user_access(user, 'jawabu_portal')
        delegate_branches = scope_values(delegate_access)
        delegate_global = has_global_scope(delegate_access)
        permitted_branches = [
            branch for branch in configured
            if (issuer_global or branch.casefold() in issuer_branches)
            and (delegate_global or branch.casefold() in delegate_branches)
        ]
        if not permitted_branches and not (issuer_global and delegate_global):
            continue
        candidates.append({
            'id': str(user.pk),
            'label': user.get_full_name() or user.get_username(),
            'branches': permitted_branches,
            'all_branches': issuer_global and delegate_global,
        })
    return candidates


def _portal_visible_delegations(queryset, access) -> list:
    """Prevent a branch-scoped Business Admin seeing another branch's authority."""
    from core.services.jawabu_approvals import delegation_is_within_authorization_scope

    return [item for item in queryset if delegation_is_within_authorization_scope(item, access)]


@portal_auth_required
@csrf_exempt  # Verified Telegram initData is the non-cookie authentication mechanism.
@require_http_methods(["GET", "POST"])
def portal_approval_delegations(request):
    """List or create the existing time-boxed Portal approval delegations."""
    access_error = _portal_capability_error(request, 'portal.approval.delegation.authorize')
    if access_error:
        return access_error
    from core.models import JawabuApprovalDelegation
    from core.services.jawabu_approvals import create_delegation

    actor = request.portal_user
    access = request.portal_access
    if request.method == 'GET':
        active = _portal_visible_delegations(JawabuApprovalDelegation.objects.select_related('delegate', 'authorized_by').filter(
            revoked_at__isnull=True, expires_at__gt=timezone.now(),
        ).order_by('expires_at'), access)
        history = _portal_visible_delegations(
            JawabuApprovalDelegation.objects.select_related('delegate', 'authorized_by').exclude(
                pk__in=[item.pk for item in active],
            ).order_by('-starts_at')[:50],
            access,
        )[:10]
        return JsonResponse({'ok': True, 'data': {
            'delegates': _portal_delegation_candidates(access, actor),
            'gates': [
                {'value': value, 'label': label}
                for value, label in JawabuApprovalDelegation.GATE_CHOICES
            ],
            'active': [_portal_delegation_payload(item) for item in active],
            'history': [_portal_delegation_payload(item) for item in history],
        }})
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except (UnicodeDecodeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'Delegation request must be valid JSON.'}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({'ok': False, 'error': 'Delegation request must be a JSON object.'}, status=400)
    from django.contrib.auth import get_user_model
    try:
        delegate = get_user_model().objects.filter(pk=str(payload.get('delegate_id') or '')).first()
    except (TypeError, ValueError):
        delegate = None
    expiry = parse_datetime(str(payload.get('expires_at') or '').strip())
    if expiry is None:
        return JsonResponse({'ok': False, 'error': 'Choose a valid delegation expiry date and time.'}, status=400)
    if timezone.is_naive(expiry):
        expiry = timezone.make_aware(expiry, timezone.get_current_timezone())
    try:
        delegation = create_delegation(
            delegate=delegate,
            gate=str(payload.get('gate') or '').strip(),
            authorized_by=actor,
            authorization_access=access,
            branch=str(payload.get('branch') or '').strip(),
            expires_at=expiry,
            reason=str(payload.get('reason') or '').strip(),
        )
    except ValidationError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    return JsonResponse({'ok': True, 'data': _portal_delegation_payload(delegation)}, status=201)


@portal_auth_required
@csrf_exempt  # Verified Telegram initData is the non-cookie authentication mechanism.
@require_http_methods(["POST"])
def portal_approval_delegation_revoke(request, delegation_id: str):
    """Revoke one active temporary approval delegation with an audit reason."""
    access_error = _portal_capability_error(request, 'portal.approval.delegation.authorize')
    if access_error:
        return access_error
    from core.models import JawabuApprovalDelegation
    from core.services.jawabu_approvals import revoke_delegation

    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except (UnicodeDecodeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'Revocation request must be valid JSON.'}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({'ok': False, 'error': 'Revocation request must be a JSON object.'}, status=400)
    if not JawabuApprovalDelegation.objects.filter(pk=delegation_id).exists():
        return JsonResponse({'ok': False, 'error': 'Delegation not found.'}, status=404)
    try:
        delegation = revoke_delegation(
            delegation_id=delegation_id,
            actor=request.portal_user,
            access=request.portal_access,
            reason=str(payload.get('reason') or '').strip(),
        )
    except ValidationError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    return JsonResponse({'ok': True, 'data': _portal_delegation_payload(delegation)})


def _portal_workspace_payload(request, actor, *, include_summary: bool = False) -> dict:
    """Project private workspace metadata through the user's live Portal scope."""
    from core.models import JawabuFarmerMaster, PortalCaseWorkspace
    from core.services.portal_workspace import workspace_payload

    accessible = _apply_county_branch_filters(JawabuFarmerMaster.objects.all(), request)
    # Only workspace rows need availability resolution. Do not materialize every
    # case ID just to render a staff member's private shortcuts.
    workspace_farmer_ids = PortalCaseWorkspace.objects.filter(user=actor).values('farmer_id')
    accessible_ids = accessible.filter(pk__in=workspace_farmer_ids).values_list('pk', flat=True)
    options = _portal_workspace_options(request, actor)
    payload = workspace_payload(
        user=actor, accessible_farmer_ids=accessible_ids, options=options,
    )
    if include_summary:
        from core.services.workflow_sla import jawabu_sla_candidates

        startup = payload.get('startup_view')
        queue_key = str((startup or {}).get('queue') or (startup or {}).get('screen') or '')
        default_count = None
        if queue_key in PORTAL_QUEUE_FRAGMENT_CONFIG:
            params = request.GET.copy()
            filters = (startup or {}).get('filters') or {}
            if filters.get('branch'):
                params['branch'] = str(filters['branch'])
            if filters.get('status'):
                params['stage'] = str(filters['status'])
            queryset, _config = _portal_queue_queryset(queue_key, request, params=params)
            default_count = queryset.count() if queryset is not None else None
        overdue = jawabu_sla_candidates(queryset=accessible.filter(status='active'))
        payload['summary'].update({
            'default_view_label': (startup or {}).get('name') or 'Portal default',
            'default_view_count': default_count,
            'overdue_count': len(overdue),
        })
    return payload


def _portal_workspace_json_body(request):
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except (UnicodeDecodeError, ValueError):
        return None, JsonResponse({'ok': False, 'error': 'Workspace request must be valid JSON.'}, status=400)
    if not isinstance(payload, dict):
        return None, JsonResponse({'ok': False, 'error': 'Workspace request must be a JSON object.'}, status=400)
    return payload, None


@portal_auth_required
@csrf_exempt  # Verified Telegram initData is the non-cookie authentication mechanism.
@require_http_methods(["GET"])
def portal_workspace(request):
    """Return the current user's private, live-authorized Portal workspace."""
    actor = getattr(request, 'portal_user', None)
    if actor is None:
        return JsonResponse({'ok': False, 'error': 'Your Portal staff account could not be resolved.'}, status=403)
    access_error = _portal_workspace_access_error(request)
    if access_error:
        return access_error
    include_summary = str(request.GET.get('summary') or '').strip().casefold() in {'1', 'true', 'yes'}
    return JsonResponse({
        'ok': True,
        'data': _portal_workspace_payload(request, actor, include_summary=include_summary),
    })


@portal_auth_required
@csrf_exempt  # Verified Telegram initData is the non-cookie authentication mechanism.
@require_http_methods(["POST"])
def portal_workspace_views(request):
    """Create one user-owned Portal view from the currently visible context."""
    actor = getattr(request, 'portal_user', None)
    access_error = _portal_workspace_access_error(request)
    if access_error:
        return access_error
    payload, error_response = _portal_workspace_json_body(request)
    if error_response:
        return error_response
    from core.services.portal_workspace import PortalWorkspaceError, create_saved_view, serialize_saved_view

    try:
        view = create_saved_view(
            user=actor, payload=payload, options=_portal_workspace_options(request, actor),
        )
    except PortalWorkspaceError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    return JsonResponse({
        'ok': True,
        'data': serialize_saved_view(view, options=_portal_workspace_options(request, actor)),
    }, status=201)


@portal_auth_required
@csrf_exempt  # Verified Telegram initData is the non-cookie authentication mechanism.
@require_http_methods(["PATCH", "DELETE"])
def portal_workspace_view_detail(request, view_id: str):
    """Edit or remove one private saved view; never alter another staff member's view."""
    actor = getattr(request, 'portal_user', None)
    access_error = _portal_workspace_access_error(request)
    if access_error:
        return access_error
    from core.services.portal_workspace import (
        PortalWorkspaceError, delete_saved_view, rename_saved_view, serialize_saved_view,
        update_saved_view,
    )

    if request.method == 'DELETE':
        try:
            delete_saved_view(user=actor, view_id=view_id)
        except PortalWorkspaceError as exc:
            return JsonResponse({'ok': False, 'error': str(exc)}, status=404)
        return JsonResponse({'ok': True})
    payload, error_response = _portal_workspace_json_body(request)
    if error_response:
        return error_response
    try:
        view = (
            update_saved_view(
                user=actor, view_id=view_id, payload=payload,
                options=_portal_workspace_options(request, actor),
            )
            if {'screen', 'queue', 'filters', 'ordering'}.intersection(payload)
            else rename_saved_view(user=actor, view_id=view_id, name=payload.get('name'))
        )
    except PortalWorkspaceError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    return JsonResponse({
        'ok': True,
        'data': serialize_saved_view(view, options=_portal_workspace_options(request, actor)),
    })


@portal_auth_required
@csrf_exempt  # Verified Telegram initData is the non-cookie authentication mechanism.
@require_http_methods(["POST"])
def portal_workspace_view_activate(request, view_id: str):
    """Validate and return one saved view before client-side navigation applies it."""
    actor = getattr(request, 'portal_user', None)
    access_error = _portal_workspace_access_error(request)
    if access_error:
        return access_error
    from core.services.portal_workspace import PortalWorkspaceError, activate_saved_view, serialize_saved_view

    try:
        view = activate_saved_view(user=actor, view_id=view_id, options=_portal_workspace_options(request, actor))
    except PortalWorkspaceError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    return JsonResponse({
        'ok': True,
        'data': serialize_saved_view(view, options=_portal_workspace_options(request, actor)),
    })


@portal_auth_required
@csrf_exempt  # Verified Telegram initData is the non-cookie authentication mechanism.
@require_http_methods(["POST"])
def portal_workspace_view_startup(request, view_id: str):
    """Set one currently valid private view as the user's Portal startup context."""
    actor = getattr(request, 'portal_user', None)
    access_error = _portal_workspace_access_error(request)
    if access_error:
        return access_error
    from core.services.portal_workspace import PortalWorkspaceError, serialize_saved_view, set_startup_view

    try:
        view = set_startup_view(user=actor, view_id=view_id, options=_portal_workspace_options(request, actor))
    except PortalWorkspaceError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    return JsonResponse({
        'ok': True,
        'data': serialize_saved_view(view, options=_portal_workspace_options(request, actor)),
    })


def _portal_workspace_farmer(request, farmer_id: str):
    from core.models import JawabuFarmerMaster

    workspace_error = _portal_workspace_access_error(request)
    if workspace_error:
        return None, workspace_error
    farmer = JawabuFarmerMaster.objects.filter(pk=farmer_id).first()
    if farmer is None:
        return None, JsonResponse({'ok': False, 'error': 'Farmer not found.'}, status=404)
    access_error = _portal_read_access_error(request, farmer)
    if access_error:
        return None, access_error
    return farmer, None


@portal_auth_required
@csrf_exempt  # Verified Telegram initData is the non-cookie authentication mechanism.
@require_http_methods(["POST"])
def portal_workspace_case_pin(request, farmer_id: str):
    """Pin one currently accessible case in the authenticated user's workspace."""
    farmer, error_response = _portal_workspace_farmer(request, farmer_id)
    if error_response:
        return error_response
    from core.services.portal_workspace import PortalWorkspaceError, pin_case

    try:
        item = pin_case(user=request.portal_user, farmer=farmer)
    except PortalWorkspaceError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    return JsonResponse({'ok': True, 'data': {'farmer_id': str(item.farmer_id), 'pinned': item.pinned}})


@portal_auth_required
@csrf_exempt  # Verified Telegram initData is the non-cookie authentication mechanism.
@require_http_methods(["POST"])
def portal_workspace_case_unpin(request, farmer_id: str):
    """Remove one private pin while retaining any in-window recent activity."""
    farmer, error_response = _portal_workspace_farmer(request, farmer_id)
    if error_response:
        return error_response
    from core.services.portal_workspace import PortalWorkspaceError, unpin_case

    try:
        item = unpin_case(user=request.portal_user, farmer=farmer)
    except PortalWorkspaceError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    return JsonResponse({'ok': True, 'data': {'farmer_id': str(item.farmer_id), 'pinned': item.pinned}})


@portal_auth_required
@csrf_exempt  # Verified Telegram initData is the non-cookie authentication mechanism.
@require_http_methods(["POST"])
def portal_workspace_recents_clear(request):
    """Hide current recents without deleting their short investigation-retention window."""
    access_error = _portal_workspace_access_error(request)
    if access_error:
        return access_error
    from core.services.portal_workspace import dismiss_recent_cases

    count = dismiss_recent_cases(user=request.portal_user)
    return JsonResponse({'ok': True, 'data': {'dismissed_count': count}})


# ── Dashboard ─────────────────────────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["GET"])
def portal_dashboard(request):
    access_error = _portal_read_access_error(request, capability='portal.dashboard.view')
    if access_error:
        return access_error
    """GET /api/portal/dashboard/ — pipeline queue counts."""
    from core.services.jawabu_pipeline import pipeline_counts
    counts = pipeline_counts()
    return JsonResponse({'ok': True, 'counts': counts})


# ── Meta / dropdown lists ─────────────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["GET"])
def portal_meta(request):
    access_error = _portal_any_capability_error(request)
    if access_error:
        return access_error
    """GET /api/portal/meta/ — lookup lists for Mini App dropdowns."""
    from core.models import JawabuApprovalDelegation, JawabuFarmerMaster
    from core.services.branches import global_branch_choices
    from core.services.locations import global_county_choices
    from core.services.access_control import policy_version
    branches = global_branch_choices()
    staff_branches = {
        str(value).strip().casefold()
        for value in getattr(request, 'portal_access', {}).get('branches', [])
        if str(value).strip()
    }
    if staff_branches:
        branches = [branch for branch in branches if branch.casefold() in staff_branches]
    delegation_gates = []
    portal_user = getattr(request, 'portal_user', None)
    if portal_user:
        delegation_gates = list(JawabuApprovalDelegation.objects.filter(
            delegate=portal_user, starts_at__lte=timezone.now(),
            expires_at__gt=timezone.now(), revoked_at__isnull=True,
        ).values_list('gate', flat=True).distinct())
    return JsonResponse({
        'ok': True,
        'branches': branches,
        'counties': global_county_choices(),
        'jbl_visit_statuses': [c[0] for c in JawabuFarmerMaster.JBL_VISIT_STATUS_CHOICES],
        'credit_decisions': [c[0] for c in JawabuFarmerMaster.CREDIT_DECISION_CHOICES],
        'imab_created_options': ['Yes', 'No', 'Pending'],
        'final_decisions': [c[0] for c in JawabuFarmerMaster.FINAL_DECISION_CHOICES],
        'approval_delegation_gates': delegation_gates,
        'capabilities': _portal_capabilities(request),
        'access_policy_version': policy_version(),
        'jbl_visit_media_max_bytes': int(getattr(settings, 'MEDIA_MAX_FILE_SIZE_MB', 20) or 20) * 1024 * 1024,
    })


# ── Stage 2: JBL Visit queue ──────────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["GET"])
def portal_jbl_queue(request):
    access_error = _portal_read_access_error(request, capability='portal.jbl_queue.view')
    if access_error:
        return access_error
    """GET /api/portal/jbl-queue/ — farmers awaiting JBL visit."""
    from core.services.jawabu_pipeline import jbl_visit_queue, farmer_to_card
    qs = _apply_portal_ordering(
        _apply_county_branch_filters(jbl_visit_queue(request.GET.get('search', '')), request),
        params=request.GET,
    )
    items, pagination = _paginate_qs(qs, request)
    return JsonResponse({
        'ok': True,
        'queue': 'jbl_visit',
        'farmers': _numbered_farmer_cards(items, pagination),
        'pagination': pagination,
    })

@csrf_exempt
@require_http_methods(["GET"])
def portal_jbl_queue_fragment(request):
    """GET /api/portal/jbl-queue/fragment/ - htmx-rendered JBL visit queue."""
    return portal_queue_fragment(request, 'jbl')


@csrf_exempt
@require_http_methods(["GET"])
def portal_queue_fragment(request, queue_key: str):
    access_error = _portal_read_access_error(
        request, capability=PORTAL_QUEUE_CAPABILITIES.get(queue_key, ''),
    )
    if access_error:
        return access_error
    """GET /api/portal/queues/<queue_key>/fragment/ - htmx-rendered farmer queue."""
    from core.services.jawabu_pipeline import farmer_to_card

    qs, config = _portal_queue_queryset(queue_key, request)
    if qs is None:
        return HttpResponse('Unknown portal queue.', status=404)

    items, pagination = _paginate_qs(qs, request)
    review_stage = _portal_review_stage(request) if queue_key == 'final' else ''
    review_map = _pending_payment_review_map(request) if review_stage == 'payment' else {}
    fragment_mode = config['mode']
    if queue_key == 'final' and review_stage == 'requisition':
        fragment_mode = 'requisition'
    elif queue_key == 'final' and review_stage == 'payment':
        fragment_mode = ''
    farmer_cards = _numbered_farmer_cards(items, pagination, review_map=review_map)
    return render(request, 'portal/partials/farmer_list.html', {
        'farmers': farmer_cards,
        'pagination': pagination,
        'queue_key': queue_key,
        'mode': fragment_mode,
        'county': request.GET.get('county', '').strip(),
        'branch': request.GET.get('branch', '').strip(),
        'search': request.GET.get('search', '').strip(),
        'review_stage': review_stage,
        'empty_title': config['empty_title'],
        'empty_sub': config['empty_sub'],
    })


@require_http_methods(["GET"])
def portal_health(request):
    """Return safe operational checks for portal staff and support admins.

    This intentionally reports configuration/state, never credentials or
    Google identifiers. It gives staff a useful explanation before they retry
    a workbook or invoice operation from a mobile WebView.
    """
    role_error = _portal_role_error(request, 'health.read')
    if role_error:
        return role_error
    from core.services.portal_health import portal_sync_health
    from core.services.portal_maintenance import current_maintenance_state

    health = portal_sync_health()
    checks = {
        'database': 'ok',
        'requisition_template': 'ok' if health['requisition_template_ready'] else 'missing',
        'payment_template': 'ok' if health['payment_template_ready'] else 'missing',
        'order_storage': 'degraded' if health['failed_order_syncs'] else 'ok',
        'payment_storage': 'degraded' if health['failed_payment_syncs'] else 'ok',
    }
    state = current_maintenance_state()
    critical_unavailable = checks['database'] != 'ok' or (
        checks['requisition_template'] == 'missing' and checks['payment_template'] == 'missing'
    )
    degraded = any(value != 'ok' for value in checks.values())
    operational_status = 'down' if critical_unavailable else (
        'maintenance' if state and state.mode == 'maintenance' else ('degraded' if degraded else 'live')
    )
    return JsonResponse({
        'ok': True,
        'status': operational_status,
        'checks': checks,
        'maintenance': {
            'mode': state.mode if state else 'live',
            'reason': state.reason if state else '',
            'updated_at': state.updated_at.isoformat() if state and state.updated_at else None,
        },
        'failed_order_syncs': health['failed_order_syncs'],
        'failed_payment_syncs': health['failed_payment_syncs'],
        'due_order_retries': health['due_order_retries'],
        'due_payment_retries': health['due_payment_retries'],
    })


def _legacy_jbl_visit_write_response():
    """Stop cached two-step clients from creating evidence without a visit."""
    return JsonResponse({
        'ok': False,
        'error': 'This Portal version is out of date. Reopen the Mini App, then submit the JBL visit again.',
        'code': 'jbl_visit_completion_upgrade_required',
    }, status=426)


@csrf_exempt
@require_http_methods(["POST"])
def portal_set_maintenance(request):
    """IT-only Portal read-only maintenance switch with compliance evidence."""
    role_error = _portal_capability_error(request, 'portal.health.maintenance.manage')
    if role_error:
        return role_error
    try:
        body = json.loads(request.body or '{}')
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'Invalid JSON body.'}, status=400)
    try:
        request_id = _portal_request_id(request, body)
        from core.services.portal_maintenance import set_maintenance_state

        state = set_maintenance_state(
            actor=getattr(request, 'portal_user', None),
            mode=body.get('mode', ''),
            reason=body.get('reason', ''),
            request_id=request_id,
        )
    except ValidationError as exc:
        return JsonResponse({'ok': False, 'error': '; '.join(exc.messages)}, status=400)
    return JsonResponse({
        'ok': True,
        'maintenance': {
            'mode': state.mode,
            'reason': state.reason,
            'updated_at': state.updated_at.isoformat(),
        },
    })


@csrf_exempt
@require_http_methods(["POST"])
def portal_log_jbl_visit(request, farmer_id: str):
    """Retired two-step completion route retained only for a safe upgrade response."""
    return _legacy_jbl_visit_write_response()


@csrf_exempt
@require_http_methods(["POST"])
def portal_complete_jbl_visit(request, farmer_id: str):
    """Validate, upload, and transition a visit through one multipart request."""
    from datetime import date as _date
    from core.models import JawabuFarmerMaster
    from core.services.jawabu_pipeline import (
        JBL_FORWARD_STATUSES,
        complete_jbl_visit,
        farmer_to_card,
    )

    try:
        farmer = JawabuFarmerMaster.objects.get(pk=farmer_id)
    except JawabuFarmerMaster.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Farmer not found.'}, status=404)
    role_error = _portal_capability_error(request, 'portal.jbl_visit.write', farmer)
    if role_error:
        return role_error
    body = request.POST.dict()
    try:
        expected_revision = _portal_workflow_revision(body)
    except ValueError as exc:
        response = _portal_workflow_error(exc)
        return response or JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    visit_date_raw = str(body.get('visit_date') or '').strip()
    try:
        visit_date = _date.fromisoformat(visit_date_raw) if visit_date_raw else _date.today()
    except ValueError:
        return JsonResponse({'ok': False, 'error': 'Visit date must use YYYY-MM-DD.'}, status=400)
    latitude = body.get('capture_latitude') or body.get('latitude')
    longitude = body.get('capture_longitude') or body.get('longitude')
    try:
        latitude = float(latitude) if latitude is not None and str(latitude).strip() else None
        longitude = float(longitude) if longitude is not None and str(longitude).strip() else None
    except (ValueError, TypeError):
        return JsonResponse({'ok': False, 'error': 'Invalid coordinates format.'}, status=400)
    getlist = getattr(request.FILES, 'getlist', None)
    categorized_files = {
        'LAF': getlist('laf_files') if getlist else [],
        'JBL_VISIT_PHOTO': getlist('jbl_visit_photo_files') if getlist else [],
    }
    visit_status = str(body.get('visit_status') or '').strip()
    # A rejected or deferred visit can be recorded without evidence.  Require
    # the separate media capability only when this request writes evidence, or
    # when the selected outcome must carry evidence to move the case forward.
    if any(categorized_files.values()) or visit_status in JBL_FORWARD_STATUSES:
        media_error = _portal_capability_error(request, 'portal.jbl_media.write', farmer)
        if media_error:
            return media_error
    sender = _portal_sender_from_request(request)
    try:
        ok, error, result = complete_jbl_visit(
            farmer,
            categorized_files=categorized_files,
            visit_date=visit_date,
            visit_status=visit_status,
            officer=str(body.get('officer') or '').strip() or sender,
            comment=str(body.get('comment') or '').strip(),
            sender=sender,
            latitude=latitude,
            longitude=longitude,
            location_unavailable_reason=str(body.get('location_unavailable_reason') or '').strip(),
            county=str(body.get('county') or '').strip() if 'county' in body else None,
            sub_county=str(body.get('sub_county') or '').strip() if 'sub_county' in body else None,
            village=str(body.get('village') or '').strip() if 'village' in body else None,
            request_id=_portal_request_id(request, body),
            expected_revision=expected_revision,
            actor_user=getattr(request, 'portal_user', None),
        )
    except ValueError as exc:
        response = _portal_workflow_error(exc)
        return response or JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    if not ok:
        return JsonResponse({'ok': False, 'error': error, **result}, status=409 if result.get('evidence_saved') else 400)
    farmer.refresh_from_db()
    return JsonResponse({'ok': True, 'farmer': farmer_to_card(farmer), **result})


# ── Stage 3: Credit Decision queue ───────────────────────────────────────────

@csrf_exempt
@require_http_methods(["POST"])
def portal_upload_jbl_media(request, farmer_id: str):
    """Retired standalone evidence route; use atomic visit completion instead."""
    return _legacy_jbl_visit_write_response()


@csrf_exempt
@require_http_methods(["GET"])
def portal_jbl_media(request, farmer_id: str):
    """GET /api/portal/jbl-queue/<farmer_id>/media/ - controlled visit evidence."""
    from django.db.models import Q
    from core.models import JawabuFarmerMaster, MediaAttachment

    try:
        farmer = JawabuFarmerMaster.objects.get(pk=farmer_id)
    except JawabuFarmerMaster.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Farmer not found.'}, status=404)

    access_error = _portal_read_access_error(request, farmer, capability='portal.jbl_media.view')
    if access_error:
        return access_error

    business_key = str(farmer.national_id or '').strip()
    attachments = MediaAttachment.objects.filter(
        upload_status='success', file_type__in=['LAF', 'JBL_VISIT_PHOTO'],
    ).filter(
        Q(jawabu_farmer=farmer) |
        Q(jawabu_farmer__isnull=True, business_key_type='id_number', business_key_value=business_key)
    ).exclude(drive_url='').order_by('-created_at')
    media = [
        {
            'id': str(item.id),
            'view_url': f'/api/portal/jbl-queue/{farmer.id}/media/{item.id}/open/',
            # ``view_url`` remains the protected API route for API callers.
            # ``open_url`` is a short-lived link for Telegram's external
            # browser, which cannot carry the Mini App authentication header.
            'open_url': _jbl_media_open_url(request, str(farmer.id), attachment_id=str(item.id)),
            'name': item.original_filename or dict({'LAF': 'LAF document', 'JBL_VISIT_PHOTO': 'JBL visit photo'}).get(item.file_type, 'Visit media'),
            'category': item.file_type,
            'created_at': item.created_at.isoformat() if item.created_at else '',
            'captured_at': item.captured_at.isoformat() if item.captured_at else '',
        }
        for item in attachments
    ]
    # Older uploads may predate categorized MediaAttachment rows. Keep them
    # viewable as a clearly labelled fallback rather than hiding the evidence.
    if not media:
        legacy_links = [url.strip() for url in str(farmer.jbl_media_urls or '').splitlines() if url.strip()]
        media = [
            {
                'id': f'legacy:{index}',
                'view_url': f'/api/portal/jbl-queue/{farmer.id}/media/legacy/{index}/open/',
                'open_url': _jbl_media_open_url(request, str(farmer.id), legacy_index=index),
                'name': 'Legacy LAF/media link',
                'category': 'LEGACY',
                'created_at': '',
                'captured_at': '',
            }
            for index, _url in enumerate(legacy_links)
        ]
    laf_media = [item for item in media if item['category'] in {'LAF', 'LEGACY'}]
    jbl_visit_photo_media = [item for item in media if item['category'] == 'JBL_VISIT_PHOTO']
    response = JsonResponse({
        'ok': True,
        'media': media,
        'laf_media': laf_media,
        'jbl_visit_photo_media': jbl_visit_photo_media,
    })
    # The response contains short-lived browser links to sensitive evidence.
    # Do not allow an intermediary or WebView cache to retain those links.
    response['Cache-Control'] = 'no-store'
    return response


@csrf_exempt
@require_http_methods(["GET"])
def portal_open_jbl_media(request, farmer_id: str, attachment_id: str):
    """Audit a sensitive evidence read before redirecting to Drive."""
    from core.models import JawabuFarmerMaster, JawabuMediaAccessEvent, MediaAttachment

    farmer = JawabuFarmerMaster.objects.filter(pk=farmer_id).first()
    if not farmer:
        return JsonResponse({'ok': False, 'error': 'Farmer not found.'}, status=404)
    from django.db.models import Q
    attachment = MediaAttachment.objects.filter(
        pk=attachment_id, upload_status='success',
    ).filter(
        Q(jawabu_farmer=farmer) |
        Q(jawabu_farmer__isnull=True, business_key_type='id_number', business_key_value=str(farmer.national_id or '').strip())
    ).exclude(drive_url='').first()
    if not attachment:
        return JsonResponse({'ok': False, 'error': 'Visit evidence was not found.'}, status=404)
    access_error = _portal_read_access_error(request, farmer, capability='portal.jbl_media.view')
    if access_error:
        return access_error
    JawabuMediaAccessEvent.objects.create(
        farmer=farmer, attachment=attachment, actor=getattr(request, 'portal_user', None),
        request_id=_portal_request_id(request),
    )
    from core.services.compliance_audit import record_sensitive_access
    record_sensitive_access(
        workflow='portal',
        action='portal.jbl_media.view',
        subject_type='media_attachment',
        subject_id=str(attachment.pk),
        actor=getattr(request, 'portal_user', None),
        request_id=_portal_request_id(request),
        metadata={'farmer_id': str(farmer.pk), 'media_category': attachment.file_type},
    )
    return HttpResponseRedirect(attachment.drive_url)


@csrf_exempt
@require_http_methods(["GET"])
def portal_open_jbl_media_signed(request, token: str):
    """Open one recently authorised evidence item in Telegram's system browser.

    The link is issued only by ``portal_jbl_media`` after normal Telegram and
    capability checks.  It expires quickly, is bound to a single evidence item
    and still records the authorised user in the access audit trail.
    """
    try:
        payload = json.loads(
            TimestampSigner(salt='portal-jbl-media-open').unsign(token, max_age=120)
        )
        farmer_id = str(payload['farmer_id'])
    except (BadSignature, KeyError, TypeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'This client-media link is invalid or has expired. Return to the Portal and open it again.'}, status=404)

    from core.models import JawabuFarmerMaster
    farmer = JawabuFarmerMaster.objects.filter(pk=farmer_id).first()
    if not farmer:
        return JsonResponse({'ok': False, 'error': 'Farmer not found.'}, status=404)

    actor = None
    actor_id = str(payload.get('user_id') or '').strip()
    if actor_id:
        from django.contrib.auth import get_user_model
        actor = get_user_model().objects.filter(pk=actor_id).first()

    attachment_id = str(payload.get('attachment_id') or '').strip()
    if attachment_id:
        from django.db.models import Q
        from core.models import JawabuMediaAccessEvent, MediaAttachment

        attachment = MediaAttachment.objects.filter(
            pk=attachment_id, upload_status='success',
        ).filter(
            Q(jawabu_farmer=farmer) |
            Q(jawabu_farmer__isnull=True, business_key_type='id_number', business_key_value=str(farmer.national_id or '').strip())
        ).exclude(drive_url='').first()
        if not attachment:
            return JsonResponse({'ok': False, 'error': 'Visit evidence was not found.'}, status=404)
        request_id = str(payload.get('request_id') or '')
        JawabuMediaAccessEvent.objects.create(
            farmer=farmer, attachment=attachment, actor=actor, request_id=request_id,
        )
        from core.services.compliance_audit import record_sensitive_access
        record_sensitive_access(
            workflow='portal',
            action='portal.jbl_media.view',
            subject_type='media_attachment',
            subject_id=str(attachment.pk),
            actor=actor,
            request_id=request_id,
            metadata={
                'access_route': 'short_lived_link',
                'farmer_id': str(farmer.pk),
                'media_category': attachment.file_type,
            },
        )
        return HttpResponseRedirect(attachment.drive_url)

    legacy_index = payload.get('legacy_index')
    if not isinstance(legacy_index, int):
        return JsonResponse({'ok': False, 'error': 'Visit evidence was not found.'}, status=404)
    links = [url.strip() for url in str(farmer.jbl_media_urls or '').splitlines() if url.strip()]
    if legacy_index < 0 or legacy_index >= len(links):
        return JsonResponse({'ok': False, 'error': 'Legacy visit evidence was not found.'}, status=404)
    from core.services.jawabu_case360 import record_pipeline_event
    from core.services.jawabu_pipeline import current_workflow_state
    record_pipeline_event(
        farmer,
        action='legacy_jbl_media_viewed',
        stage_key='jbl_visit',
        actor=actor.get_username() if actor else 'signed Portal media link',
        request_id=str(payload.get('request_id') or ''),
        source='portal_media',
        new_values={'legacy_media_index': legacy_index, 'access_route': 'short_lived_link'},
        actor_user=actor,
        transition_code='jawabu.jbl_visit.legacy_media_viewed',
        from_state=current_workflow_state(farmer),
        to_state=current_workflow_state(farmer),
        revision_before=farmer.workflow_revision,
        revision_after=farmer.workflow_revision,
    )
    return HttpResponseRedirect(links[legacy_index])


@csrf_exempt
@require_http_methods(["GET"])
def portal_open_legacy_jbl_media(request, farmer_id: str, media_index: int):
    """Audit a legacy stored link before redirecting without exposing it in JSON."""
    from core.models import JawabuFarmerMaster
    from core.services.jawabu_case360 import record_pipeline_event
    from core.services.jawabu_pipeline import current_workflow_state

    farmer = JawabuFarmerMaster.objects.filter(pk=farmer_id).first()
    if not farmer:
        return JsonResponse({'ok': False, 'error': 'Farmer not found.'}, status=404)
    access_error = _portal_read_access_error(request, farmer, capability='portal.jbl_media.view')
    if access_error:
        return access_error
    links = [url.strip() for url in str(farmer.jbl_media_urls or '').splitlines() if url.strip()]
    if media_index < 0 or media_index >= len(links):
        return JsonResponse({'ok': False, 'error': 'Legacy visit evidence was not found.'}, status=404)
    record_pipeline_event(
        farmer,
        action='legacy_jbl_media_viewed',
        stage_key='jbl_visit',
        actor=_portal_sender_from_request(request),
        request_id=_portal_request_id(request),
        source='portal_media',
        new_values={'legacy_media_index': media_index},
        actor_user=getattr(request, 'portal_user', None),
        transition_code='jawabu.jbl_visit.legacy_media_viewed',
        from_state=current_workflow_state(farmer),
        to_state=current_workflow_state(farmer),
        revision_before=farmer.workflow_revision,
        revision_after=farmer.workflow_revision,
    )
    return HttpResponseRedirect(links[media_index])


@csrf_exempt
@require_http_methods(["POST"])
def portal_clear_approval_condition(request, condition_id: str):
    """Clear one evidenced condition; the service advances only when all are met."""
    from core.models import JawabuApprovalCondition
    from core.services.jawabu_approvals import JawabuApprovalError, clear_condition
    from core.services.jawabu_pipeline import farmer_to_card

    condition = JawabuApprovalCondition.objects.select_related('approval__farmer').filter(pk=condition_id).first()
    if not condition:
        return JsonResponse({'ok': False, 'error': 'Approval condition not found.'}, status=404)
    access_error = _portal_read_access_error(request, condition.approval.farmer, capability='portal.case.read')
    if access_error:
        return access_error
    body = _json_body(request)
    try:
        clear_condition(
            condition_id=condition_id,
            actor=getattr(request, 'portal_user', None),
            access=getattr(request, 'portal_access', None),
            note=str(body.get('note') or '').strip(),
        )
    except (JawabuApprovalError, ValidationError) as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    farmer = condition.approval.farmer
    farmer.refresh_from_db()
    return JsonResponse({'ok': True, 'farmer': farmer_to_card(farmer)})

@csrf_exempt
@require_http_methods(["GET"])
def portal_credit_queue(request):
    access_error = _portal_read_access_error(request, capability='portal.credit_queue.view')
    if access_error:
        return access_error
    """GET /api/portal/credit-queue/ — farmers awaiting credit analysis."""
    from core.services.jawabu_pipeline import credit_queue, farmer_to_card
    qs = _apply_portal_ordering(_apply_county_branch_filters(credit_queue(), request), params=request.GET)
    items, pagination = _paginate_qs(qs, request)
    return JsonResponse({
        'ok': True,
        'queue': 'credit',
        'farmers': _numbered_farmer_cards(items, pagination),
        'pagination': pagination,
    })


@csrf_exempt
@require_http_methods(["POST"])
def portal_set_credit_decision(request, farmer_id: str):
    """
    POST /api/portal/credit-queue/<farmer_id>/
    Body: { decision }
    """
    from core.models import JawabuFarmerMaster
    from core.services.jawabu_pipeline import set_credit_decision, farmer_to_card

    try:
        farmer = JawabuFarmerMaster.objects.get(pk=farmer_id)
    except JawabuFarmerMaster.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Farmer not found.'}, status=404)

    role_error = _portal_approval_authority_error(request, farmer, 'credit')
    if role_error:
        return role_error

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'Invalid JSON body.'}, status=400)
    try:
        expected_revision = _portal_workflow_revision(body)
    except ValueError as exc:
        response = _portal_workflow_error(exc)
        return response or JsonResponse({'ok': False, 'error': str(exc)}, status=400)

    decision = str(body.get('decision') or '').strip()
    imab_created = str(body.get('imab_created') or '').strip()
    customer_no = str(body.get('customer_no') or '').strip()
    reason_code = str(body.get('reason_code') or '').strip()
    try:
        conditions = _approval_conditions_from_body(body)
    except ValueError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    if not decision:
        return JsonResponse({'ok': False, 'error': 'decision is required.'}, status=400)

    sender = _portal_sender_from_request(request)
    try:
        ok, error = set_credit_decision(
            farmer,
            decision=decision,
            imab_created=imab_created,
            customer_no=customer_no,
            reason_code=reason_code,
            conditions=conditions,
            sender=sender,
            request_id=_portal_request_id(request, body),
            expected_revision=expected_revision,
            actor_user=getattr(request, 'portal_user', None),
            access=getattr(request, 'portal_access', None),
        )
    except (ValueError, ValidationError) as exc:
        response = _portal_workflow_error(exc)
        return response or JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    if not ok:
        return JsonResponse({'ok': False, 'error': error}, status=400)
    farmer.refresh_from_db()
    return JsonResponse({'ok': True, 'farmer': farmer_to_card(farmer)})



# Stage 4: Head of Rural final review

@csrf_exempt
@require_http_methods(["GET"])
def portal_final_review_queue(request):
    access_error = _portal_read_access_error(request, capability='portal.final_review.view')
    if access_error:
        return access_error
    """GET /api/portal/final-review-queue/ - the Head of Rural review lenses.

    ``stage=decision`` is the original final-decision queue.  ``stage=requisition``
    shows approved cases waiting for order batching, while ``stage=payment``
    shows the exact farmers captured by pending payment review documents.
    """
    from core.services.jawabu_pipeline import final_review_queue, farmer_to_card
    stage = _portal_review_stage(request)
    review_map = {}
    if stage == 'requisition':
        from core.services.jawabu_pipeline import requisition_queue
        qs = _apply_portal_ordering(_apply_county_branch_filters(requisition_queue(), request), params=request.GET)
    elif stage == 'payment':
        qs, review_map = _payment_review_queryset(request)
    else:
        qs = _apply_portal_ordering(_apply_county_branch_filters(final_review_queue(), request), params=request.GET)
    qs = _apply_portal_ordering(qs, params=request.GET)
    items, pagination = _paginate_qs(qs, request)
    return JsonResponse({
        'ok': True,
        'queue': 'final_review',
        'review_stage': stage,
        'farmers': _numbered_farmer_cards(items, pagination, review_map=review_map),
        'pagination': pagination,
    })


@csrf_exempt
@require_http_methods(["POST"])
def portal_set_final_decision(request, farmer_id: str):
    """
    POST /api/portal/final-review-queue/<farmer_id>/
    Body: { final_decision, decision_comment, repayment_date, repayment_tenor }
    """
    from core.models import JawabuFarmerMaster
    from core.services.jawabu_pipeline import set_final_decision, farmer_to_card

    try:
        farmer = JawabuFarmerMaster.objects.get(pk=farmer_id)
    except JawabuFarmerMaster.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Farmer not found.'}, status=404)

    role_error = _portal_approval_authority_error(request, farmer, 'final_review')
    if role_error:
        return role_error

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'Invalid JSON body.'}, status=400)
    try:
        expected_revision = _portal_workflow_revision(body)
    except ValueError as exc:
        response = _portal_workflow_error(exc)
        return response or JsonResponse({'ok': False, 'error': str(exc)}, status=400)

    final_decision = str(body.get('final_decision') or '').strip()
    decision_comment = str(body.get('decision_comment') or '').strip()
    repayment_date = str(body.get('repayment_date') or '').strip() if 'repayment_date' in body else None
    repayment_tenor = str(body.get('repayment_tenor') or '').strip() if 'repayment_tenor' in body else None
    reason_code = str(body.get('reason_code') or '').strip()
    try:
        conditions = _approval_conditions_from_body(body)
    except ValueError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    if not final_decision:
        return JsonResponse({'ok': False, 'error': 'final_decision is required.'}, status=400)

    sender = _portal_sender_from_request(request)
    try:
        ok, error = set_final_decision(
            farmer,
            final_decision=final_decision,
            decision_comment=decision_comment,
            reason_code=reason_code,
            conditions=conditions,
            repayment_date=repayment_date,
            repayment_tenor=repayment_tenor,
            sender=sender,
            request_id=_portal_request_id(request, body),
            expected_revision=expected_revision,
            actor_user=getattr(request, 'portal_user', None),
            access=getattr(request, 'portal_access', None),
        )
    except (ValueError, ValidationError) as exc:
        response = _portal_workflow_error(exc)
        return response or JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    if not ok:
        return JsonResponse({'ok': False, 'error': error}, status=400)
    farmer.refresh_from_db()
    return JsonResponse({'ok': True, 'farmer': farmer_to_card(farmer)})


@csrf_exempt
@require_http_methods(["POST"])
def portal_return_for_rework(request, farmer_id: str):
    """Return an eligible Jawabu case to the preceding accountable stage."""
    from core.models import JawabuFarmerMaster
    from core.services.jawabu_pipeline import JawabuWorkflowState, farmer_to_card, return_for_rework

    try:
        farmer = JawabuFarmerMaster.objects.get(pk=farmer_id)
    except JawabuFarmerMaster.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Farmer not found.'}, status=404)
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'Invalid JSON body.'}, status=400)
    try:
        expected_revision = _portal_workflow_revision(body)
    except ValueError as exc:
        response = _portal_workflow_error(exc)
        return response or JsonResponse({'ok': False, 'error': str(exc)}, status=400)

    target_state = str(body.get('target_state') or '').strip()
    capability_action = {
        JawabuWorkflowState.JBL_VISIT: 'credit.write',
        JawabuWorkflowState.CREDIT: 'final_review.write',
    }.get(target_state)
    if not capability_action:
        return JsonResponse({'ok': False, 'error': 'Select a valid return stage.'}, status=400)
    role_error = _portal_role_error(request, capability_action, farmer)
    if role_error:
        return role_error
    try:
        ok, error = return_for_rework(
            farmer,
            target_state=target_state,
            reason=str(body.get('reason') or ''),
            sender=_portal_sender_from_request(request),
            request_id=_portal_request_id(request, body),
            expected_revision=expected_revision,
            actor_user=getattr(request, 'portal_user', None),
        )
    except ValueError as exc:
        response = _portal_workflow_error(exc)
        return response or JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    if not ok:
        return JsonResponse({'ok': False, 'error': error}, status=400)
    farmer.refresh_from_db()
    return JsonResponse({'ok': True, 'farmer': farmer_to_card(farmer)})

# ── Stage 4: Requisition / Order queue ───────────────────────────────────────

@csrf_exempt
@require_http_methods(["GET"])
def portal_requisition_queue(request):
    access_error = _portal_read_access_error(request, capability='portal.requisition.view')
    if access_error:
        return access_error
    """GET /api/portal/requisition-queue/ — credit-approved farmers awaiting order."""
    from core.services.jawabu_pipeline import requisition_queue, farmer_to_card
    qs = _apply_portal_ordering(_apply_county_branch_filters(requisition_queue(), request), params=request.GET)
    items, pagination = _paginate_qs(qs, request)
    return JsonResponse({
        'ok': True,
        'queue': 'requisition',
        'farmers': _numbered_farmer_cards(items, pagination),
        'pagination': pagination,
    })


@csrf_exempt
@require_http_methods(["POST"])
def portal_assign_order(request, farmer_id: str):
    """
    POST /api/portal/requisition-queue/<farmer_id>/
    Body: { order_number, requisition_date (YYYY-MM-DD, optional) }

    GATE: Returns HTTP 403 if final_decision != 'Approved'.
    """
    from datetime import date as _date
    from core.models import JawabuFarmerMaster
    from core.services.jawabu_pipeline import assign_order, farmer_to_card

    try:
        farmer = JawabuFarmerMaster.objects.get(pk=farmer_id)
    except JawabuFarmerMaster.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Farmer not found.'}, status=404)

    role_error = _portal_role_error(request, 'requisition.write', farmer)
    if role_error:
        return role_error

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'Invalid JSON body.'}, status=400)
    try:
        expected_revision = _portal_workflow_revision(body)
    except ValueError as exc:
        response = _portal_workflow_error(exc)
        return response or JsonResponse({'ok': False, 'error': str(exc)}, status=400)

    order_number = str(body.get('order_number') or '').strip()
    requisition_date_raw = str(body.get('requisition_date') or '').strip()
    existing_order_scope_error = _portal_order_scope_error(request, order_number)
    if existing_order_scope_error:
        return existing_order_scope_error
    requisition_date = None
    if requisition_date_raw:
        try:
            requisition_date = _date.fromisoformat(requisition_date_raw)
        except ValueError:
            return JsonResponse(
                {'ok': False, 'error': f"Invalid requisition_date '{requisition_date_raw}'. Use YYYY-MM-DD."},
                status=400,
            )

    # An order number represents one requisition batch and therefore one
    # requisition date. Never silently split or overwrite that date when a
    # later client is attached to the same order.
    if requisition_date is not None:
        date_error, _, _ = _requisition_order_date_conflict(order_number, requisition_date)
        if date_error:
            return JsonResponse({'ok': False, 'error': date_error, 'code': 'requisition_date_conflict'}, status=409)
    else:
        existing_farmers, existing_batch = _requisition_order_context(order_number)
        known_dates = _requisition_order_dates(existing_farmers, existing_batch)
        if len(known_dates) == 1:
            requisition_date = next(iter(known_dates))
        elif len(known_dates) > 1:
            date_error, _, _ = _requisition_order_date_conflict(order_number, None)
            return JsonResponse({'ok': False, 'error': date_error, 'code': 'requisition_date_conflict'}, status=409)

    sender = _portal_sender_from_request(request)
    try:
        ok, error = assign_order(
            farmer,
            order_number=order_number,
            requisition_date=requisition_date,
            repayment_date=body.get('repayment_date'),
            repayment_tenor=body.get('repayment_tenor'),
            payment_product=body.get('payment_product'),
            sender=sender,
            request_id=_portal_request_id(request, body),
            expected_revision=expected_revision,
            actor_user=getattr(request, 'portal_user', None),
        )
    except ValueError as exc:
        response = _portal_workflow_error(exc)
        return response or JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    if not ok:
        # Gate failure → 403 Forbidden
        status_code = 403 if 'Final Decision' in error or 'final review' in error.lower() else 400
        return JsonResponse({'ok': False, 'error': error}, status=status_code)
    farmer.refresh_from_db()
    return JsonResponse({'ok': True, 'farmer': farmer_to_card(farmer)})


# ── All cases + deferred ──────────────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["GET"])
def portal_all_cases(request):
    """
    GET /api/portal/farmers/
    Query params: search, county, branch, page
    """
    from core.services.jawabu_pipeline import all_cases, farmer_to_card
    access_error = _portal_read_access_error(request)
    if access_error:
        return access_error
    search = request.GET.get('search', '').strip()
    county = request.GET.get('county', '').strip()
    branch = request.GET.get('branch', '').strip()
    qs = all_cases(search=search, county=county, branch=branch)
    qs = _apply_portal_ordering(_apply_county_branch_filters(qs, request), params=request.GET)
    items, pagination = _paginate_qs(qs, request)
    return JsonResponse({
        'ok': True,
        'farmers': _numbered_farmer_cards(items, pagination),
        'pagination': pagination,
    })


@csrf_exempt
@require_http_methods(["GET"])
def portal_deferred(request):
    access_error = _portal_read_access_error(request, capability='portal.deferred.view')
    if access_error:
        return access_error
    """GET /api/portal/deferred/ — deferred/rejected/flagged farmers."""
    from core.services.jawabu_pipeline import deferred_queue, reappraisal_required_queue, farmer_to_card
    qs = _apply_portal_ordering(
        _apply_county_branch_filters((deferred_queue() | reappraisal_required_queue()).distinct(), request),
        params=request.GET,
    )
    items, pagination = _paginate_qs(qs, request)
    return JsonResponse({
        'ok': True,
        'queue': 'deferred',
        'farmers': _numbered_farmer_cards(items, pagination),
        'pagination': pagination,
    })


@csrf_exempt
@require_http_methods(["GET"])
def portal_farmer_detail(request, farmer_id: str):
    """GET /api/portal/farmers/<farmer_id>/ — full detail for one farmer."""
    from core.models import JawabuFarmerMaster
    from core.services.jawabu_pipeline import farmer_to_card
    from django.db.models import Q
    from core.models import SpinCreditRequest
    try:
        farmer = JawabuFarmerMaster.objects.get(pk=farmer_id)
    except JawabuFarmerMaster.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Farmer not found.'}, status=404)
    access_error = _portal_read_access_error(request, farmer)
    if access_error:
        return access_error
    actor = getattr(request, 'portal_user', None)
    open_key = str(request.headers.get('X-Portal-Workspace-Open-Key') or '').strip()
    from core.services.workflow_capabilities import has_capability
    if (
        actor is not None
        and open_key
        and has_capability(
            actor,
            'jawabu_portal',
            'portal.workspace.manage',
            access=getattr(request, 'portal_access', None),
        )
    ):
        from core.services.portal_workspace import PortalWorkspaceError, record_case_open

        try:
            record_case_open(user=actor, farmer=farmer, open_key=open_key)
        except PortalWorkspaceError as exc:
            return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    from core.services.jawabu_case360 import serialize_case360
    card = farmer_to_card(farmer)
    identity_filters = None
    if farmer.national_id:
        identity_filters = Q(national_id=farmer.national_id)
    for phone in (farmer.primary_phone, farmer.secondary_phone):
        if phone:
            phone_filter = Q(primary_phone=phone) | Q(secondary_phone=phone)
            identity_filters = (identity_filters | phone_filter) if identity_filters is not None else phone_filter
    spin_references = []
    if identity_filters:
        for record in SpinCreditRequest.objects.filter(identity_filters).order_by('-created_at')[:20]:
            parsed = record.parsed_fields or {}
            links = []
            for key, label in (
                ('spin_report_url', 'SPIN report'),
                ('crb_report_url', 'CRB report'),
                ('credit_analysis_report_url', 'Credit analysis'),
            ):
                url = str(parsed.get(key) or '').strip()
                if url:
                    links.append({'label': label, 'url': url})
            for index, url in enumerate(str(parsed.get('media_urls') or '').splitlines(), start=1):
                url = url.strip()
                if url:
                    links.append({'label': f'Uploaded SPIN/CRB file {index}', 'url': url})
            spin_references.append({
                'request_type': record.get_request_type_display(),
                'status': record.get_import_status_display(),
                'created_at': record.created_at.isoformat() if record.created_at else '',
                'links': links,
                'attachment_names': record.attachment_names or [],
            })
    card['spin_references'] = spin_references
    return JsonResponse({'ok': True, 'farmer': card, 'case360': serialize_case360(farmer)})



@csrf_exempt
@require_http_methods(["POST"])
def portal_requisition_preview(request):
    """POST /api/portal/requisition-queue/preview/ - validate selected clients before generating Excel."""
    # The in-app preview is intentionally data-only. Workbook rendering in a
    # Telegram WebView is unreliable and belongs to the confirmed download.
    preview_format = 'document'
    parsed, error_response = _parse_requisition_workbook_payload(request, allow_blocked=True)
    if error_response:
        return error_response

    farmers = parsed['farmers']
    farmer_ids = parsed['farmer_ids']
    order_number = parsed['order_number']
    requisition_date = parsed['requisition_date']
    access_error = _portal_capability_error(request, 'portal.requisition.view') or _portal_farmers_scope_error(request, farmers)
    if access_error:
        return access_error

    warnings = list(parsed['warnings'])
    if parsed['existing_order_count']:
        warnings.append({
            'message': (
                f"Order number {order_number} already exists on "
                f"{parsed['existing_order_count']} other client(s). "
                "This preview includes the original clients and the newly selected clients."
            ),
        })
    return JsonResponse({
        'ok': True,
        'order_number': order_number,
        'requisition_date': requisition_date.isoformat(),
        'ready_count': len(parsed['ready']),
        'blocked_count': len(parsed['blocked']),
        'warning_count': len(warnings),
        'ready': parsed['ready'],
        'blocked': parsed['blocked'],
        'warnings': warnings,
        'workbook_preview': None,
        'preview_format': preview_format,
    })


@csrf_exempt
@require_http_methods(["POST"])
def portal_requisition_workbook_preview(request):
    """Legacy Drive-backed preview endpoint retained for old Mini App clients.

    The current UI never calls this side-effecting endpoint: it renders the
    values in-app and only generates the confirmed Excel output after review.
    """
    from django.utils import timezone
    from core.models import RequisitionBatch
    from core.services.requisition import RequisitionTemplateError, generate_requisition_excel

    parsed, error_response = _parse_requisition_workbook_payload(request)
    if error_response:
        return error_response

    farmers = parsed['farmers']
    order_number = parsed['order_number']
    requisition_date = parsed['requisition_date']
    access_error = _portal_capability_error(request, 'portal.requisition.write') or _portal_farmers_scope_error(request, farmers, {'operations'})
    if access_error:
        return access_error
    try:
        xlsx_bytes = generate_requisition_excel(farmers, order_number, requisition_date)
    except RequisitionTemplateError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    except FileNotFoundError:
        logger.exception('Requisition template file is missing.')
        return JsonResponse({
            'ok': False,
            'error': 'The requisition Excel template file is missing. Upload it in Django Admin > Requisition templates and mark it active.',
        }, status=400)

    sender = _portal_sender_from_request(request)
    from django.db import transaction

    # Reserve a new preview version before the external upload. This keeps
    # repeated previews as identifiable snapshots instead of overwriting one
    # batch row or creating same-name Drive files.
    with transaction.atomic():
        batch = (
            RequisitionBatch.objects.select_for_update()
            .filter(order_number=order_number)
            .first()
        )
        if batch is None:
            batch = RequisitionBatch(order_number=order_number, preview_version=1)
        else:
            batch.preview_version = (batch.preview_version or 0) + 1
        filename = f"JBL_Requisition_Form_{order_number}_preview_v{batch.preview_version}.xlsx"
        batch.requisition_date = requisition_date
        batch.preview_filename = filename
        batch.preview_generated_by = sender
        batch.preview_generated_at = timezone.now()
        batch.preview_error = 'Drive synchronization pending.'
        batch.farmer_ids = [str(farmer.id) for farmer in farmers]
        batch.farmer_count = len(farmers)
        if not batch.version:
            batch.status = 'preview'
        summary = _invoice_summary_for_batch(farmers, batch.invoice_summary)
        batch.invoice_summary = summary
        batch.save()
    from core.services.document_sync import mark_drive_attempt, mark_drive_failure, mark_drive_success
    mark_drive_attempt(batch, prefix='preview_drive')
    try:
        drive_file_id, drive_url = _upload_generated_workbook_to_drive(xlsx_bytes, filename, order_number)
    except Exception as exc:
        logger.exception('Requisition preview workbook was not stored in Google Drive.')
        mark_drive_failure(
            batch, 'Drive upload failed; retry required.',
            prefix='preview_drive', error_field='preview_error',
        )
        return JsonResponse({
            'ok': False,
            'error': 'Requisition preview could not be stored. Check synchronization status and retry.',
        }, status=502)

    mark_drive_success(
        batch, file_id=drive_file_id, url=drive_url,
        prefix='preview_drive', error_field='preview_error',
    )

    return JsonResponse({
        'ok': True,
        'filename': filename,
        'drive_url': drive_url,
        'batch': _serialize_batch(batch, farmers, request),
    })


@csrf_exempt
@require_http_methods(["POST"])
def portal_requisition_generate(request):
    """
    POST /api/portal/requisition-queue/generate/
    Body: { farmer_ids: [...], order_number: "...", requisition_date: "..." }
    """
    from core.models import RequisitionBatch
    from core.services.jawabu_pipeline import assign_order, sync_farmer_to_master_sheet
    from core.services.requisition import RequisitionTemplateError, generate_requisition_excel

    parsed, error_response = _parse_requisition_workbook_payload(request)
    if error_response:
        return error_response
    body = parsed['body']
    farmers = parsed['farmers']
    order_number = parsed['order_number']
    requisition_date = parsed['requisition_date']
    access_error = _portal_capability_error(request, 'portal.requisition.write') or _portal_farmers_scope_error(request, farmers)
    if access_error:
        return access_error
    try:
        expected_revisions = _requisition_assignment_revisions(
            body,
            farmers,
            order_number,
            requisition_date,
        )
    except ValueError as exc:
        response = _portal_workflow_error(exc)
        return response or JsonResponse({'ok': False, 'error': str(exc)}, status=400)

    try:
        xlsx_bytes = generate_requisition_excel(farmers, order_number, requisition_date)
    except RequisitionTemplateError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    except FileNotFoundError:
        logger.exception('Requisition template file is missing.')
        return JsonResponse({
            'ok': False,
            'error': 'The requisition Excel template file is missing. Upload it in Django Admin > Requisition templates and mark it active.',
        }, status=400)

    # Assign order details only after the Excel has been generated successfully.
    # Lock and validate the whole write set before assigning any individual
    # case; a stale case therefore cannot leave a half-assigned local batch.
    sender = _portal_sender_from_request(request)
    batch_request_id = _portal_request_id(request, body)
    from django.db import transaction
    from core.models import JawabuFarmerMaster
    from core.services.workflow_transitions import validate_workflow_revision

    try:
        with transaction.atomic():
            locked_farmers = {
                str(farmer.id): farmer
                for farmer in JawabuFarmerMaster.objects.select_for_update()
                .filter(id__in=[farmer.id for farmer in farmers])
                .order_by('id')
            }
            for farmer_id, expected_revision in expected_revisions.items():
                validate_workflow_revision(locked_farmers[farmer_id], expected_revision)
            for farmer in farmers:
                locked = locked_farmers[str(farmer.id)]
                if locked.order_number != order_number or locked.requisition_date != requisition_date:
                    ok, assignment_error = assign_order(
                        locked,
                        order_number=order_number,
                        requisition_date=requisition_date,
                        sender=sender,
                        request_id=f'{batch_request_id}:{locked.id}' if batch_request_id else '',
                        expected_revision=expected_revisions[str(locked.id)],
                        actor_user=getattr(request, 'portal_user', None),
                    )
                    if not ok:
                        raise ValueError(assignment_error)
    except ValueError as exc:
        response = _portal_workflow_error(exc)
        return response or JsonResponse({'ok': False, 'error': str(exc)}, status=400)

    # Reserve a monotonic version before contacting Drive.  The batch row is
    # the latest pointer, while each generated workbook remains identifiable
    # by its immutable versioned filename in Drive.
    with transaction.atomic():
        batch = (
            RequisitionBatch.objects.select_for_update()
            .filter(order_number=order_number)
            .first()
        )
        if batch is None:
            batch = RequisitionBatch(order_number=order_number)
        batch.version = (batch.version or 0) + 1
        filename = f"JBL_Requisition_Form_{order_number}_v{batch.version}.xlsx"
        batch.requisition_date = requisition_date
        batch.generated_by = sender
        batch.filename = filename
        batch.file_content = xlsx_bytes
        batch.drive_upload_error = 'Drive synchronization pending.'
        batch.farmer_ids = [str(farmer.id) for farmer in farmers]
        batch.farmer_count = len(farmers)
        batch.status = 'needs_review'
        summary = _invoice_summary_for_batch(farmers, batch.invoice_summary)
        batch.invoice_summary = summary
        batch.save()
    from core.services.document_sync import mark_drive_attempt, mark_drive_failure, mark_drive_success
    mark_drive_attempt(batch)
    try:
        drive_file_id, drive_url = _upload_generated_workbook_to_drive(xlsx_bytes, filename, order_number)
    except Exception as exc:
        logger.exception('Generated requisition workbook was not stored in Google Drive.')
        mark_drive_failure(batch, 'Drive upload failed; retry required.', error_field='drive_upload_error')
        batch.status = 'needs_review'
        batch.save(update_fields=['status', 'updated_at'])
        return JsonResponse({
            'ok': False,
            'error': 'Generated requisition workbook could not be stored. Check synchronization status and retry.',
        }, status=502)

    mark_drive_success(
        batch, file_id=drive_file_id, url=drive_url, error_field='drive_upload_error',
    )
    batch.status = summary.get('status') or 'generated'
    batch.save(update_fields=['status', 'updated_at'])

    if body.get('return_url'):
        return JsonResponse({
            'ok': True,
            'filename': filename,
            'drive_url': drive_url,
            'download_url': _batch_download_url(request, order_number),
            'batch': _serialize_batch(batch, farmers, request),
        })

    response = HttpResponse(
        xlsx_bytes,
        content_type=batch.content_type,
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@csrf_exempt
@require_http_methods(["GET", "HEAD"])
def portal_requisition_download(request, token: str):
    """Short-lived mobile-friendly download for generated requisition Excel files."""
    try:
        order_number = TimestampSigner(salt='portal-requisition-download').unsign(token, max_age=900)
    except BadSignature:
        return JsonResponse({'ok': False, 'error': 'Download link expired. Generate the requisition form again.'}, status=404)
    from core.models import RequisitionBatch
    batch = RequisitionBatch.objects.filter(order_number=order_number).first()
    if not batch or not batch.file_content:
        return JsonResponse({'ok': False, 'error': 'Generated requisition file was not found for this order.'}, status=404)
    response = HttpResponse(
        b'' if request.method == 'HEAD' else batch.file_content,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    filename = batch.filename or f'JBL_Requisition_Form_{order_number}.xlsx'
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@csrf_exempt
@require_http_methods(["GET"])
def portal_requisition_batches(request):
    access_error = _portal_read_access_error(request, capability='portal.batches.view')
    if access_error:
        return access_error
    """GET /api/portal/requisition-batches/ - generated batch output history."""
    paged_batches, pagination = _portal_requisition_batches_payload(request)
    return JsonResponse({
        'ok': True,
        'batches': paged_batches,
        'pagination': pagination,
    })


@csrf_exempt
@require_http_methods(["GET"])
def portal_requisition_batches_fragment(request):
    access_error = _portal_read_access_error(request, capability='portal.batches.view')
    if access_error:
        return access_error
    """GET /api/portal/requisition-batches/fragment/ - htmx-rendered batch history."""
    paged_batches, pagination = _portal_requisition_batches_payload(request)
    return render(request, 'portal/partials/batch_list.html', {
        'batches': paged_batches,
        'pagination': pagination,
        'county': request.GET.get('county', '').strip(),
        'branch': request.GET.get('branch', '').strip(),
        'empty_title': 'No batches found',
        'empty_sub': 'No requisition batches match the current filters.',
    })


@csrf_exempt
@require_http_methods(["GET"])
def portal_requisition_batch_detail(request, order_number: str):
    """GET /api/portal/requisition-batches/<order_number>/ - one batch with clients and invoice state."""
    from core.models import JawabuFarmerMaster, RequisitionBatch

    try:
        batch = RequisitionBatch.objects.get(order_number=order_number)
        farmers = _farmers_for_batch(order_number, batch.farmer_ids or None)
        access_error = _portal_capability_error(request, 'portal.batches.view') or _portal_farmers_scope_error(request, farmers)
        if access_error:
            return access_error
        payload = _serialize_batch(batch, farmers, request)
        return JsonResponse({'ok': True, 'batch': payload})
    except RequisitionBatch.DoesNotExist:
        farmers = list(JawabuFarmerMaster.objects.filter(order_number=order_number).order_by('customer_name'))
        if not farmers:
            return JsonResponse({'ok': False, 'error': 'Batch not found.'}, status=404)
        access_error = _portal_capability_error(request, 'portal.batches.view') or _portal_farmers_scope_error(request, farmers)
        if access_error:
            return access_error
        summary = _invoice_summary_for_farmers(farmers)
        pseudo = RequisitionBatch(
            order_number=order_number,
            requisition_date=farmers[0].requisition_date,
            farmer_count=len(farmers),
            status=summary.get('status', 'generated'),
            invoice_summary=summary,
        )
        return JsonResponse({'ok': True, 'batch': _serialize_batch(pseudo, farmers, request)})


@csrf_exempt
@require_http_methods(["GET", "HEAD"])
def portal_requisition_batch_download(request, order_number: str):
    """Download a persisted generated requisition Excel file by order number."""
    from core.models import RequisitionBatch

    try:
        batch = RequisitionBatch.objects.get(order_number=order_number)
    except RequisitionBatch.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Generated requisition file was not found for this order.'}, status=404)
    if not batch.file_content:
        return JsonResponse({'ok': False, 'error': 'This batch has no saved requisition file. Regenerate it from Ready for Orders.'}, status=404)
    from core.models import JawabuFarmerMaster
    farmers = JawabuFarmerMaster.objects.filter(
        id__in=batch.farmer_ids or [],
    )
    for farmer in farmers:
        access_error = _portal_read_access_error(request, farmer, capability='portal.batches.view')
        if access_error:
            return access_error
    from core.services.compliance_audit import record_sensitive_access
    record_sensitive_access(
        workflow='portal',
        action='portal.requisition.workbook.download',
        subject_type='requisition_batch',
        subject_id=str(batch.pk),
        actor=getattr(request, 'portal_user', None),
        actor_label=_portal_sender_from_request(request),
        request_id=_portal_request_id(request),
        metadata={'order_number': batch.order_number, 'version': getattr(batch, 'version', 0) or 0},
    )
    filename = batch.filename or f'JBL_Requisition_Form_{batch.order_number}.xlsx'
    response = HttpResponse(
        b'' if request.method == 'HEAD' else batch.file_content,
        content_type=batch.content_type,
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@csrf_exempt
@require_http_methods(["POST"])
def portal_requisition_batch_retry_sync(request, order_number: str):
    """Retry Drive storage for the latest saved requisition workbook."""
    from core.models import RequisitionBatch
    from core.services.document_sync import retry_requisition_batch_upload

    batch = RequisitionBatch.objects.filter(order_number=order_number).first()
    if not batch:
        return JsonResponse({'ok': False, 'error': 'Requisition batch not found.'}, status=404)
    role_error = _portal_role_error(request, 'requisition.write')
    if role_error:
        return role_error
    scope_error = _portal_order_scope_error(request, order_number)
    if scope_error:
        return scope_error
    result = retry_requisition_batch_upload(batch, actor=_portal_sender_from_request(request))
    if not result.get('ok'):
        return JsonResponse({
            'ok': False,
            'error': 'Requisition workbook synchronization failed. Retry again after checking the storage status.',
            'retry_at': result.get('retry_at').isoformat() if result.get('retry_at') else None,
        }, status=502)
    farmers = _farmers_for_batch(order_number, batch.farmer_ids or None)
    return JsonResponse({'ok': True, 'batch': _serialize_batch(batch, farmers, request), 'retried': True})


@csrf_exempt
@require_http_methods(["POST"])
def portal_upload_batch_invoices(request):
    """POST /api/portal/requisition-batches/upload-invoices/ — upload a combined PDF of invoices for a batch/order."""
    order_number = request.POST.get('order_number') or request.GET.get('order_number')
    role_error = _portal_role_error(request, 'invoice.write')
    if role_error:
        return role_error
    if order_number:
        scope_error = _portal_order_scope_error(request, order_number)
        if scope_error:
            return scope_error
    
    pdf_file = request.FILES.get('file')
    if not pdf_file:
        return JsonResponse({'ok': False, 'error': 'No file uploaded under key "file".'}, status=400)
        
    if not str(pdf_file.name or '').lower().endswith('.pdf'):
        return JsonResponse({'ok': False, 'error': 'Only PDF files are supported.'}, status=400)

    max_mb = max(1, int(getattr(settings, 'INVOICE_UPLOAD_MAX_FILE_SIZE_MB', 8) or 8))
    max_bytes = max_mb * 1024 * 1024
    if getattr(pdf_file, 'size', 0) and pdf_file.size > max_bytes:
        return JsonResponse({
            'ok': False,
            'error': f'Invoice PDF is too large for this Mini App upload. Maximum size is {max_mb} MB.',
            'max_file_size_mb': max_mb,
        }, status=413)

    from core.services.invoice_parser import InvoiceUploadStorageError

    try:
        pdf_bytes = pdf_file.read()
        request_id = _portal_request_id(request, request.POST.dict())
        logger.info(
            'Invoice upload received: order=%s filename=%s size=%s bytes',
            order_number or 'invoice_pool',
            getattr(pdf_file, 'name', ''),
            getattr(pdf_file, 'size', ''),
        )
        from core.models import RequisitionBatch
        from core.services.invoice_parser import (
            ingest_invoice_upload_batch,
            propose_invoice_batch_matches,
        )
        upload_batch = ingest_invoice_upload_batch(
            pdf_bytes=pdf_bytes,
            filename=getattr(pdf_file, 'name', '') or 'hb_invoices.pdf',
            content_type=getattr(pdf_file, 'content_type', '') or 'application/pdf',
            uploaded_by=_portal_sender_from_request(request),
            order_number=order_number or '',
            client_request_id=request_id,
        )
        if not order_number:
            return JsonResponse({
                'ok': upload_batch.total_parsed > 0,
                'invoice_batch_id': str(upload_batch.id),
                'drive_url': upload_batch.drive_url,
                'status': upload_batch.status,
                'total_pages': upload_batch.total_pages,
                'total_parsed': upload_batch.total_parsed,
                'matched_count': upload_batch.matched_count,
                'unmatched_count': upload_batch.unmatched_count,
                'max_file_size_mb': max_mb,
            })

        upload_batch = propose_invoice_batch_matches(upload_batch)
        result = {
            'ok': upload_batch.total_parsed > 0,
            'requires_confirmation': True,
            'invoice_batch_id': str(upload_batch.id),
            'invoice_batch_status': upload_batch.status,
            'drive_url': upload_batch.drive_url,
            'total_parsed': upload_batch.total_parsed,
            'matched_count': 0,
            'max_file_size_mb': max_mb,
            'results': [_serialize_parsed_invoice(item) for item in upload_batch.invoices.select_related('proposed_farmer')],
        }
        try:
            batch = RequisitionBatch.objects.get(order_number=order_number)
            farmers = _farmers_for_batch(order_number, batch.farmer_ids or None)
            summary = _invoice_summary_for_farmers(farmers)
            summary.update({'total_parsed': upload_batch.total_parsed, 'matched_count': 0,
                            'last_invoice_upload_status': 'awaiting_confirmation',
                            'last_invoice_upload_error': '', 'invoice_batch_id': str(upload_batch.id)})
            batch.status = 'needs_review'
            batch.invoice_summary = summary
            batch.last_invoice_result = result
            batch.save(update_fields=['status', 'invoice_summary', 'last_invoice_result', 'updated_at'])
        except RequisitionBatch.DoesNotExist:
            pass
        return JsonResponse(result)
    except InvoiceUploadStorageError as e:
        return JsonResponse({'ok': False, 'error': 'Invoice PDF could not be stored. Check synchronization status and retry.'}, status=502)
    except Exception as e:
        logger.exception("Error processing invoice PDF: %s", e)
        return JsonResponse({'ok': False, 'error': 'Invoice PDF could not be parsed. Check that it is a readable invoice PDF.'}, status=400)


@csrf_exempt
@require_http_methods(["POST"])
def portal_invoice_pool_upload(request):
    """Upload one or more HB invoice PDFs into the general unmatched invoice pool."""
    role_error = _portal_role_error(request, 'invoice.write')
    if role_error:
        return role_error
    getlist = getattr(request.FILES, 'getlist', None)
    pdf_files = getlist('file') if getlist else []
    if not pdf_files:
        pdf_file = request.FILES.get('file')
        pdf_files = [pdf_file] if pdf_file else []
    if not pdf_files:
        return JsonResponse({'ok': False, 'error': 'No file uploaded under key "file".'}, status=400)

    max_mb = max(1, int(getattr(settings, 'INVOICE_UPLOAD_MAX_FILE_SIZE_MB', 8) or 8))
    max_bytes = max_mb * 1024 * 1024
    request_id = _portal_request_id(request, request.POST.dict())
    for pdf_index, pdf_file in enumerate(pdf_files, start=1):
        if not str(pdf_file.name or '').lower().endswith('.pdf'):
            return JsonResponse({'ok': False, 'error': f'Only PDF files are supported: {pdf_file.name}'}, status=400)
        if getattr(pdf_file, 'size', 0) and pdf_file.size > max_bytes:
            return JsonResponse({
                'ok': False,
                'error': f'Invoice PDF is too large for this Mini App upload: {pdf_file.name}. Maximum size is {max_mb} MB.',
                'max_file_size_mb': max_mb,
            }, status=413)

    from core.services.invoice_parser import InvoiceUploadStorageError, ingest_invoice_upload_batch

    batches = []
    failures = []
    uploaded_by = _portal_sender_from_request(request)
    for pdf_index, pdf_file in enumerate(pdf_files, start=1):
        filename = getattr(pdf_file, 'name', '') or 'hb_invoices.pdf'
        try:
            batch = ingest_invoice_upload_batch(
                pdf_bytes=pdf_file.read(),
                filename=filename,
                content_type=getattr(pdf_file, 'content_type', '') or 'application/pdf',
                uploaded_by=uploaded_by,
                client_request_id=(f'{request_id}:{pdf_index}' if request_id else ''),
            )
            batches.append(batch)
        except InvoiceUploadStorageError as exc:
            logger.exception('Invoice PDF storage failed for filename=%s', filename)
            failures.append({'filename': filename, 'error': 'Invoice PDF could not be stored in Google Drive.'})
        except Exception as exc:
            logger.exception("Invoice pool upload failed for %s", filename)
            failures.append({'filename': filename, 'error': 'Invoice PDF could not be parsed.'})

    if not batches:
        status = 502 if any('Google Drive' in item['error'] for item in failures) else 500
        return JsonResponse({
            'ok': False,
            'error': failures[0]['error'] if failures else 'Invoice upload failed.',
            'failures': failures,
            'max_file_size_mb': max_mb,
        }, status=status)

    total_pages = sum(batch.total_pages for batch in batches)
    total_parsed = sum(batch.total_parsed for batch in batches)
    unmatched_count = sum(batch.unmatched_count for batch in batches)
    first_batch = batches[0]

    return JsonResponse({
        'ok': total_parsed > 0 and not failures,
        'invoice_batch_id': str(first_batch.id),
        'invoice_batch_ids': [str(batch.id) for batch in batches],
        'drive_url': first_batch.drive_url,
        'status': 'partial' if failures else 'parsed',
        'total_uploaded': len(batches),
        'total_failed': len(failures),
        'total_pages': total_pages,
        'total_parsed': total_parsed,
        'unmatched_count': unmatched_count,
        'batches': [_serialize_invoice_batch(batch) for batch in batches],
        'failures': failures,
        'max_file_size_mb': max_mb,
    }, status=207 if failures else 200)


def _serialize_invoice_batch(batch) -> dict:
    sync_error = str(getattr(batch, 'sync_error', '') or getattr(batch, 'error', '') or '').strip()
    sync_status = str(getattr(batch, 'sync_status', '') or '').strip().lower()
    if sync_status in {'success', 'succeeded'} or str(batch.drive_url or '').strip():
        sync_state = 'succeeded'
    elif sync_status in {'pending', 'processing', 'queued'}:
        sync_state = 'pending'
    elif sync_error or sync_status in {'failed', 'error'}:
        sync_state = 'retryable_failure'
    else:
        sync_state = 'not_requested'
    return {
        'id': str(batch.id),
        'original_filename': batch.original_filename,
        'content_type': batch.content_type,
        'size': batch.size,
        'uploaded_by': batch.uploaded_by,
        'drive_file_id': batch.drive_file_id,
        'drive_url': batch.drive_url,
        'sync_status': sync_state,
        'sync_error': sync_error,
        'sync_attempts': getattr(batch, 'sync_attempts', 0) or 0,
        'next_retry_at': batch.next_retry_at.isoformat() if getattr(batch, 'next_retry_at', None) else None,
        'status': batch.status,
        'total_pages': batch.total_pages,
        'total_parsed': batch.total_parsed,
        'matched_count': batch.matched_count,
        'unmatched_count': batch.unmatched_count,
        'error': batch.error,
        'created_at': batch.created_at.isoformat() if batch.created_at else None,
        'updated_at': batch.updated_at.isoformat() if batch.updated_at else None,
    }


def _serialize_parsed_invoice(
    invoice,
    payment_readiness_by_order: dict | None = None,
    *,
    include_duplicate_summary: bool = False,
) -> dict:
    farmer = invoice.matched_farmer
    order_number = invoice.matched_order_number or (farmer.order_number if farmer else '')
    readiness = (payment_readiness_by_order or {}).get(order_number) if order_number else None
    data = {
        'id': str(invoice.id),
        'batch_id': str(invoice.batch_id),
        'batch_filename': invoice.batch.original_filename if invoice.batch_id else '',
        'page': invoice.page,
        'invoice_no': invoice.invoice_no,
        'invoice_date': invoice.invoice_date.isoformat() if invoice.invoice_date else invoice.invoice_date_raw,
        'customer_name': invoice.customer_name,
        'customer_id': invoice.customer_id,
        'customer_phone': invoice.customer_phone,
        'invoice_amount': str(invoice.invoice_amount) if invoice.invoice_amount is not None else '',
        'total_after_discount': str(invoice.total_after_discount) if invoice.total_after_discount is not None else '',
        'discount': str(invoice.discount) if invoice.discount is not None else '',
        'payment': str(invoice.payment) if invoice.payment is not None else '',
        # Invoice PDFs call this field Payment; staff use it as the HBG
        # deposit. Expose the explicit meaning without removing the legacy key.
        'hbg_deposit': str(
            farmer.deposit_paid_hbg
            if farmer and farmer.deposit_paid_hbg is not None
            else (invoice.payment if invoice.payment is not None else (farmer.actual_receipts if farmer else None))
        ) if (
            farmer and farmer.deposit_paid_hbg is not None
        ) or invoice.payment is not None or (
            farmer and farmer.actual_receipts not in (None, '')
        ) else '',
        'balance_due': str(invoice.balance_due) if invoice.balance_due is not None else '',
        'balance_due_check': invoice.balance_due_check,
        'status': invoice.status,
        'matched_farmer_id': str(farmer.id) if farmer else '',
        'matched_farmer_name': farmer.customer_name if farmer else '',
        'matched_order_number': order_number,
        'proposed_farmer_id': str(invoice.proposed_farmer_id or ''),
        'proposed_farmer_name': invoice.proposed_farmer.customer_name if invoice.proposed_farmer_id else '',
        'proposed_order_number': invoice.proposed_order_number,
        'payment_readiness': readiness or {},
        'review_notes': invoice.review_notes,
        'created_at': invoice.created_at.isoformat() if invoice.created_at else None,
        'updated_at': invoice.updated_at.isoformat() if invoice.updated_at else None,
    }
    if include_duplicate_summary:
        data['duplicate_count'] = _invoice_duplicate_count(invoice)
    return data


@csrf_exempt
@require_http_methods(["PATCH", "POST"])
def portal_invoice_draft_edit(request, invoice_id: str):
    from core.models import ParsedInvoice
    from core.services.invoice_parser import edit_draft_invoice

    try:
        payload = json.loads(request.body or b'{}')
        invoice = ParsedInvoice.objects.select_related('batch').get(pk=invoice_id)
        role_error = _portal_role_error(request, 'invoice.write', invoice.matched_farmer)
        if role_error:
            return role_error
        invoice = edit_draft_invoice(invoice, payload, actor=_portal_sender_from_request(request))
    except ParsedInvoice.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Invoice draft not found.'}, status=404)
    except (ValueError, json.JSONDecodeError) as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    return JsonResponse({'ok': True, 'invoice': _serialize_parsed_invoice(invoice)})


@csrf_exempt
@require_http_methods(["POST"])
def portal_invoice_batch_confirm(request, batch_id: str):
    from core.models import InvoiceUploadBatch
    from core.services.invoice_parser import confirm_invoice_batch

    try:
        batch = InvoiceUploadBatch.objects.get(pk=batch_id)
        role_error = _portal_role_error(request, 'invoice.write')
        if role_error:
            return role_error
        if batch.order_number:
            scope_error = _portal_order_scope_error(request, batch.order_number)
            if scope_error:
                return scope_error
        batch = confirm_invoice_batch(batch, actor=_portal_sender_from_request(request))
    except InvoiceUploadBatch.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Invoice batch not found.'}, status=404)
    except ValueError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
    return JsonResponse({'ok': batch.sync_status == 'success', 'batch': _serialize_invoice_batch(batch)}, status=200 if batch.sync_status == 'success' else 202)


def _serialize_invoice_event(event) -> dict:
    return {
        'id': str(event.id),
        'action': event.action,
        'actor': event.actor,
        'note': event.note,
        'metadata': event.metadata or {},
        'created_at': event.created_at.isoformat() if event.created_at else None,
    }


def _invoice_duplicate_query(invoice):
    from django.db.models import Q

    query = Q()
    if invoice.invoice_no:
        query |= Q(invoice_no__iexact=invoice.invoice_no)
    if invoice.customer_id:
        query |= Q(customer_id__iexact=invoice.customer_id)
    phone_digits = re.sub(r'\D', '', invoice.customer_phone or '')
    if phone_digits:
        query |= Q(customer_phone__icontains=phone_digits[-9:])
    return query, phone_digits


def _invoice_duplicate_reasons(invoice, candidate, phone_digits: str) -> list[str]:
    reasons = []
    if invoice.invoice_no and str(candidate.invoice_no or '').strip().lower() == invoice.invoice_no.strip().lower():
        reasons.append('Same invoice no')
    if invoice.customer_id and str(candidate.customer_id or '').strip().lower() == invoice.customer_id.strip().lower():
        reasons.append('Same ID')
    candidate_phone = re.sub(r'\D', '', candidate.customer_phone or '')[-9:]
    if phone_digits and candidate_phone and candidate_phone == phone_digits[-9:]:
        reasons.append('Same phone')
    return reasons


def _invoice_duplicate_count(invoice) -> int:
    from core.models import ParsedInvoice

    query, _phone_digits = _invoice_duplicate_query(invoice)
    if not query.children:
        return 0
    return ParsedInvoice.objects.filter(query).exclude(pk=invoice.pk).count()


def _invoice_duplicate_candidates(invoice) -> list[dict]:
    from core.models import ParsedInvoice

    query, phone_digits = _invoice_duplicate_query(invoice)
    if not query.children:
        return []

    candidates = (
        ParsedInvoice.objects
        .select_related('batch', 'matched_farmer')
        .filter(query)
        .exclude(pk=invoice.pk)
        .order_by('-created_at')[:8]
    )
    rows = []
    for candidate in candidates:
        reasons = _invoice_duplicate_reasons(invoice, candidate, phone_digits)
        serialized = _serialize_parsed_invoice(candidate)
        serialized['duplicate_reasons'] = reasons
        rows.append(serialized)
    return rows


@require_http_methods(["GET"])
def portal_invoice_pool(request):
    """Return invoice upload batches and parsed invoice records for the invoice workspace."""
    from django.db.models import Count, Q
    from core.models import InvoiceUploadBatch, ParsedInvoice

    access_error = _portal_read_access_error(request, capability='portal.invoice.view')
    if access_error:
        return access_error

    status = str(request.GET.get('status') or '').strip()
    search = str(request.GET.get('search') or '').strip()
    batch_id = str(request.GET.get('batch_id') or '').strip()
    review = str(request.GET.get('review') or '').strip()

    invoices = ParsedInvoice.objects.select_related('batch', 'matched_farmer').all()
    staff_branches = [
        str(value).strip() for value in getattr(request, 'portal_access', {}).get('branches', [])
        if str(value).strip()
    ]
    if staff_branches:
        branch_scope = Q()
        for staff_branch in staff_branches:
            branch_scope |= Q(matched_farmer__branch__iexact=staff_branch)
        # An unmatched invoice has no trusted branch, so it is intentionally
        # hidden from branch-limited accounts until an unrestricted reviewer
        # links it to a case.
        invoices = invoices.filter(branch_scope)
    scoped_invoices = invoices
    if status:
        invoices = invoices.filter(status=status)
    if batch_id:
        invoices = invoices.filter(batch_id=batch_id)
    if search:
        invoices = invoices.filter(
            Q(invoice_no__icontains=search)
            | Q(customer_name__icontains=search)
            | Q(customer_id__icontains=search)
            | Q(customer_phone__icontains=search)
            | Q(matched_order_number__icontains=search)
            | Q(batch__original_filename__icontains=search)
        )
    invoices = invoices.order_by('-created_at')

    review_filtered = None
    if review == 'duplicates':
        review_filtered = [
            invoice for invoice in invoices[:300]
            if _invoice_duplicate_count(invoice) > 0
        ]
    elif review in {'payment_blocked', 'payment_ready'}:
        from core.services.payment_documents import payment_readiness
        matched_invoices = [
            invoice for invoice in invoices[:300]
            if invoice.status == 'matched' and (
                invoice.matched_order_number or (invoice.matched_farmer and invoice.matched_farmer.order_number)
            )
        ]
        readiness_cache = {}
        selected = []
        for invoice in matched_invoices:
            order_number = invoice.matched_order_number or invoice.matched_farmer.order_number
            if order_number not in readiness_cache:
                try:
                    readiness_cache[order_number] = payment_readiness(order_number)
                except Exception as exc:
                    logger.exception('Payment readiness calculation failed for order=%s', order_number)
                    readiness_cache[order_number] = {'error': 'Payment readiness is temporarily unavailable.', 'blocked_count': 1, 'ready_count': 0}
            readiness = readiness_cache[order_number]
            blocked_count = int(readiness.get('blocked_count') or 0)
            if review == 'payment_blocked' and blocked_count > 0:
                selected.append(invoice)
            elif review == 'payment_ready' and blocked_count == 0 and int(readiness.get('ready_count') or 0) > 0:
                selected.append(invoice)
        review_filtered = selected

    if review_filtered is not None:
        paged_invoices, invoice_pagination = _paginate_list(review_filtered, request, page_size=25)
    else:
        paged_invoices, invoice_pagination = _paginate_qs(invoices, request, page_size=25)
    readiness_by_order = {}
    order_numbers = sorted({
        invoice.matched_order_number or (invoice.matched_farmer.order_number if invoice.matched_farmer else '')
        for invoice in paged_invoices
        if invoice.status == 'matched' and (invoice.matched_order_number or (invoice.matched_farmer and invoice.matched_farmer.order_number))
    })
    if order_numbers:
        from core.services.payment_documents import payment_readiness
        for order_number in order_numbers:
            try:
                readiness = payment_readiness(order_number)
            except Exception as exc:
                logger.exception('Payment readiness calculation failed for order=%s', order_number)
                readiness_by_order[order_number] = {'ok': False, 'error': 'Payment readiness is temporarily unavailable.'}
            else:
                readiness_by_order[order_number] = {
                    'ready_count': readiness.get('ready_count', 0),
                    'blocked_count': readiness.get('blocked_count', 0),
                    'farmer_count': readiness.get('farmer_count', 0),
                }

    batches = InvoiceUploadBatch.objects.filter(
        invoices__in=scoped_invoices,
    ).annotate(invoice_count=Count('invoices')).distinct().order_by('-created_at')[:20]
    summary = {
        'batch_count': scoped_invoices.values('batch_id').distinct().count(),
        'invoice_count': scoped_invoices.count(),
        'unmatched_count': scoped_invoices.filter(status='unmatched').count(),
        'matched_count': scoped_invoices.filter(status='matched').count(),
        'ambiguous_count': scoped_invoices.filter(status='ambiguous').count(),
        'ignored_count': scoped_invoices.filter(status='ignored').count(),
    }

    return JsonResponse({
        'ok': True,
        'summary': summary,
        'batches': [_serialize_invoice_batch(batch) for batch in batches],
        'invoices': [
            _serialize_parsed_invoice(invoice, readiness_by_order, include_duplicate_summary=True)
            for invoice in paged_invoices
        ],
        'pagination': invoice_pagination,
        'filters': {
            'status': status,
            'search': search,
            'batch_id': batch_id,
            'review': review,
        },
    })


@require_http_methods(["GET"])
def portal_invoice_detail(request, invoice_id: str):
    """Return one parsed invoice with audit events, duplicate signals, and source PDF context."""
    from core.models import ParsedInvoice

    try:
        invoice = ParsedInvoice.objects.select_related('batch', 'matched_farmer').get(pk=invoice_id)
    except ParsedInvoice.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Invoice not found.'}, status=404)

    access_error = _portal_read_access_error(request, invoice.matched_farmer, capability='portal.invoice.view')
    if access_error:
        return access_error

    readiness_by_order = {}
    order_number = invoice.matched_order_number or (invoice.matched_farmer.order_number if invoice.matched_farmer else '')
    if order_number:
        from core.services.payment_documents import payment_readiness
        try:
            readiness = payment_readiness(order_number)
        except Exception as exc:
            logger.exception('Payment readiness calculation failed for order=%s', order_number)
            readiness_by_order[order_number] = {
                'ok': False,
                'error': 'Payment readiness is temporarily unavailable.',
            }
        else:
            readiness_by_order[order_number] = {
                'ready_count': readiness.get('ready_count', 0),
                'blocked_count': readiness.get('blocked_count', 0),
                'farmer_count': readiness.get('farmer_count', 0),
                'blocked': readiness.get('blocked', []),
            }

    events = invoice.events.all().order_by('-created_at')[:25]
    return JsonResponse({
        'ok': True,
        'invoice': _serialize_parsed_invoice(invoice, readiness_by_order),
        'batch': _serialize_invoice_batch(invoice.batch),
        'source_pdf_url': invoice.batch.drive_url,
        'events': [_serialize_invoice_event(event) for event in events],
        'duplicates': _invoice_duplicate_candidates(invoice),
        'raw_payload': invoice.raw_payload or {},
    })


@require_http_methods(["GET"])
def portal_invoice_farmer_candidates(request):
    """Search farmer records that an invoice can be manually linked to."""
    from django.db.models import Q
    from core.models import JawabuFarmerMaster

    access_error = _portal_read_access_error(request, capability='portal.invoice.view')
    if access_error:
        return access_error

    search = str(request.GET.get('search') or '').strip()
    invoice_id = str(request.GET.get('invoice_id') or '').strip()
    parsed_invoice = None
    if invoice_id:
        from core.models import ParsedInvoice
        parsed_invoice = ParsedInvoice.objects.select_related('matched_farmer').filter(pk=invoice_id).first()
        if parsed_invoice:
            access_error = _portal_read_access_error(request, parsed_invoice.matched_farmer, capability='portal.invoice.view')
            if access_error:
                return access_error
    if len(search) < 2 and not parsed_invoice:
        return JsonResponse({'ok': True, 'farmers': []})

    query = Q()
    if search:
        query |= (
            Q(customer_name__icontains=search)
            | Q(national_id__icontains=search)
            | Q(primary_phone__icontains=search)
            | Q(order_number__icontains=search)
            | Q(customer_no__icontains=search)
        )
    if parsed_invoice:
        if parsed_invoice.customer_id:
            query |= Q(national_id__iexact=parsed_invoice.customer_id)
        if parsed_invoice.customer_name:
            query |= Q(customer_name__icontains=parsed_invoice.customer_name)
        phone_digits = re.sub(r'\D', '', parsed_invoice.customer_phone or '')
        if phone_digits:
            query |= Q(primary_phone__icontains=phone_digits[-9:])
    if not query.children:
        return JsonResponse({'ok': True, 'farmers': []})
    candidate_qs = JawabuFarmerMaster.objects.filter(status='active').filter(query)
    candidate_qs = _apply_county_branch_filters(candidate_qs, request)
    qs = list(candidate_qs.order_by('customer_name')[:30])

    def score(farmer):
        points = 0
        reasons = []
        if parsed_invoice:
            if parsed_invoice.customer_id and str(farmer.national_id or '').strip() == parsed_invoice.customer_id:
                points += 100
                reasons.append('ID match')
            inv_phone = re.sub(r'\D', '', parsed_invoice.customer_phone or '')[-9:]
            farmer_phone = re.sub(r'\D', '', farmer.primary_phone or '')[-9:]
            if inv_phone and farmer_phone and inv_phone == farmer_phone:
                points += 80
                reasons.append('Phone match')
            if parsed_invoice.customer_name and str(farmer.customer_name or '').strip().lower() == parsed_invoice.customer_name.strip().lower():
                points += 60
                reasons.append('Name match')
        if search:
            needle = search.lower()
            if needle in str(farmer.order_number or '').lower():
                points += 25
                reasons.append('Order search')
            if needle in str(farmer.customer_no or '').lower():
                points += 25
                reasons.append('Customer no search')
        return points, reasons

    scored = []
    for farmer in qs:
        points, reasons = score(farmer)
        scored.append((points, farmer.customer_name or '', farmer, reasons))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return JsonResponse({
        'ok': True,
        'farmers': [
            {
                'id': str(farmer.id),
                'customer_name': farmer.customer_name,
                'national_id': farmer.national_id,
                'primary_phone': farmer.primary_phone,
                'order_number': farmer.order_number,
                'county': farmer.county,
                'sub_county': farmer.sub_county,
                'village': farmer.village,
                'customer_no': farmer.customer_no,
                'invoice_number': farmer.invoice_number,
                'has_invoice': bool(farmer.invoice_number),
                'invoice_conflict_label': (
                    f"Existing invoice {farmer.invoice_number}" if farmer.invoice_number else ''
                ),
                'match_score': points,
                'match_reasons': reasons,
            }
            for points, _name, farmer, reasons in scored[:15]
        ],
    })


def _json_body(request) -> dict:
    try:
        return json.loads(request.body or b'{}')
    except (json.JSONDecodeError, ValueError):
        return {}


@csrf_exempt
@require_http_methods(["POST"])
def portal_invoice_match(request, invoice_id: str):
    """Manually link a parsed invoice to the correct farmer/order record."""
    from core.models import JawabuFarmerMaster, ParsedInvoice
    from core.services.invoice_parser import InvoiceSheetSyncError, manually_match_invoice

    body = _json_body(request)
    farmer_id = str(body.get('farmer_id') or '').strip()
    note = str(body.get('note') or '').strip()
    if not farmer_id:
        return JsonResponse({'ok': False, 'error': 'farmer_id is required.'}, status=400)
    try:
        invoice = ParsedInvoice.objects.get(pk=invoice_id)
        farmer = JawabuFarmerMaster.objects.get(pk=farmer_id)
    except ParsedInvoice.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Invoice not found.'}, status=404)
    except JawabuFarmerMaster.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Farmer not found.'}, status=404)
    role_error = _portal_role_error(request, 'invoice.write', farmer)
    if role_error:
        return role_error

    try:
        invoice = manually_match_invoice(invoice, farmer, actor=_portal_sender_from_request(request), note=note)
    except InvoiceSheetSyncError as exc:
        logger.exception('Invoice Sheet synchronization failed during manual match.')
        return JsonResponse({'ok': False, 'error': 'Invoice matched locally but could not be synchronized. Retry synchronization.'}, status=502)
    except Exception as exc:
        logger.exception("Manual invoice match failed")
        return JsonResponse({'ok': False, 'error': 'Manual invoice matching failed. Retry or contact an administrator.'}, status=500)

    return JsonResponse({'ok': True, 'invoice': _serialize_parsed_invoice(invoice)})


@csrf_exempt
@require_http_methods(["POST"])
def portal_invoice_unmatch(request, invoice_id: str):
    """Remove a parsed invoice match and clear farmer invoice fields when appropriate."""
    from core.models import ParsedInvoice
    from core.services.invoice_parser import InvoiceSheetSyncError, unmatch_invoice

    body = _json_body(request)
    try:
        invoice = ParsedInvoice.objects.get(pk=invoice_id)
    except ParsedInvoice.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Invoice not found.'}, status=404)

    role_error = _portal_role_error(request, 'invoice.write', invoice.matched_farmer)
    if role_error:
        return role_error

    try:
        invoice = unmatch_invoice(invoice, actor=_portal_sender_from_request(request), note=str(body.get('note') or '').strip())
    except InvoiceSheetSyncError as exc:
        logger.exception('Invoice Sheet synchronization failed during unmatch.')
        return JsonResponse({'ok': False, 'error': 'Invoice was updated locally but could not be synchronized. Retry synchronization.'}, status=502)
    except Exception as exc:
        logger.exception("Manual invoice unmatch failed")
        return JsonResponse({'ok': False, 'error': 'Invoice unmatch failed. Retry or contact an administrator.'}, status=500)

    return JsonResponse({'ok': True, 'invoice': _serialize_parsed_invoice(invoice)})


@csrf_exempt
@require_http_methods(["POST"])
def portal_invoice_ignore(request, invoice_id: str):
    """Mark a parsed invoice as ignored with an audit note."""
    from core.models import ParsedInvoice
    from core.services.invoice_parser import ignore_invoice

    body = _json_body(request)
    try:
        invoice = ParsedInvoice.objects.get(pk=invoice_id)
    except ParsedInvoice.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Invoice not found.'}, status=404)

    role_error = _portal_role_error(request, 'invoice.write', invoice.matched_farmer)
    if role_error:
        return role_error

    invoice = ignore_invoice(invoice, actor=_portal_sender_from_request(request), note=str(body.get('note') or '').strip())
    return JsonResponse({'ok': True, 'invoice': _serialize_parsed_invoice(invoice)})


@csrf_exempt
@require_http_methods(["POST"])
def portal_invoice_restore(request, invoice_id: str):
    """Restore an ignored parsed invoice to the unmatched review queue."""
    from core.models import ParsedInvoice
    from core.services.invoice_parser import restore_invoice

    body = _json_body(request)
    try:
        invoice = ParsedInvoice.objects.get(pk=invoice_id)
    except ParsedInvoice.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Invoice not found.'}, status=404)

    role_error = _portal_role_error(request, 'invoice.write', invoice.matched_farmer)
    if role_error:
        return role_error

    invoice = restore_invoice(invoice, actor=_portal_sender_from_request(request), note=str(body.get('note') or '').strip())
    return JsonResponse({'ok': True, 'invoice': _serialize_parsed_invoice(invoice)})


@csrf_exempt
@require_http_methods(["POST"])
def portal_invoice_bulk_action(request):
    """Apply safe review actions to selected invoice records."""
    from core.models import ParsedInvoice
    from core.services.invoice_parser import ignore_invoice, restore_invoice

    body = _json_body(request)
    action = str(body.get('action') or '').strip().lower()
    invoice_ids = [str(item).strip() for item in (body.get('invoice_ids') or []) if str(item).strip()]
    note = str(body.get('note') or '').strip()
    if action not in {'ignore', 'restore'}:
        return JsonResponse({'ok': False, 'error': 'Unsupported bulk invoice action.'}, status=400)
    if not invoice_ids:
        return JsonResponse({'ok': False, 'error': 'Select at least one invoice.'}, status=400)

    actor = _portal_sender_from_request(request)
    invoices = list(ParsedInvoice.objects.filter(pk__in=invoice_ids).select_related('batch', 'matched_farmer'))
    role_error = _portal_role_error(request, 'invoice.write')
    if role_error:
        return role_error
    for invoice in invoices:
        role_error = _portal_role_error(request, 'invoice.write', invoice.matched_farmer)
        if role_error:
            return role_error
    changed = []
    skipped = []
    for invoice in invoices:
        if action == 'ignore':
            if invoice.status == 'matched':
                skipped.append({'id': str(invoice.id), 'reason': 'matched invoices are not bulk ignored'})
                continue
            changed.append(ignore_invoice(invoice, actor=actor, note=note or 'Bulk ignored.'))
        elif action == 'restore':
            if invoice.status != 'ignored':
                skipped.append({'id': str(invoice.id), 'reason': 'only ignored invoices can be restored'})
                continue
            changed.append(restore_invoice(invoice, actor=actor, note=note or 'Bulk restored.'))

    found_ids = {str(invoice.id) for invoice in invoices}
    for invoice_id in invoice_ids:
        if invoice_id not in found_ids:
            skipped.append({'id': invoice_id, 'reason': 'not found'})

    return JsonResponse({
        'ok': True,
        'action': action,
        'changed_count': len(changed),
        'skipped_count': len(skipped),
        'skipped': skipped,
        'invoices': [_serialize_parsed_invoice(invoice) for invoice in changed[:25]],
    })


@require_http_methods(["GET"])
def portal_payment_readiness(request, order_number: str):
    """Return readiness status for payment document generation."""
    from core.services.payment_documents import payment_readiness

    access_error = _portal_capability_error(request, 'portal.payment.view') or _portal_order_scope_error(request, order_number)
    if access_error:
        return access_error

    return JsonResponse({'ok': True, 'data': payment_readiness(order_number)})


@require_http_methods(["GET"])
def portal_payment_candidates(request):
    """List active invoice-matched cases available for a selected payment batch."""
    from core.models import JawabuFarmerMaster
    from core.services.payment_documents import payment_readiness
    from django.db.models import Q

    access_error = _portal_read_access_error(request, capability='portal.payment.view')
    if access_error:
        return access_error

    search = request.GET.get('search', '').strip()
    queryset = JawabuFarmerMaster.objects.filter(
        status='active', parsed_invoices__status='matched', parsed_invoices__matched_farmer__isnull=False,
    ).exclude(pipeline_events__action='payment_finalized').distinct().order_by('customer_name')
    queryset = _apply_county_branch_filters(queryset, request)
    if search:
        queryset = queryset.filter(
            Q(customer_name__icontains=search)
            | Q(national_id__icontains=search)
            | Q(primary_phone__icontains=search)
            | Q(order_number__icontains=search)
            | Q(invoice_number__icontains=search)
        )
    farmers = list(queryset[:250])
    readiness = payment_readiness(farmer_ids=[str(farmer.id) for farmer in farmers]) if farmers else {'ready': [], 'blocked': []}
    pending_map = _pending_payment_review_map(request)
    pending_review = []
    ready = []
    blocked = []
    for item in readiness.get('ready', []):
        document = pending_map.get(str(item.get('farmer_id')))
        if document:
            item = {
                **item,
                'payment_review_document_id': str(document.id),
                'payment_review_payment_number': document.payment_number,
                'payment_review_order_number': ', '.join(
                    (document.validation_summary or {}).get('order_numbers') or [document.order_number]
                ),
            }
            pending_review.append(item)
        else:
            ready.append(item)
    for item in readiness.get('blocked', []):
        document = pending_map.get(str(item.get('farmer_id')))
        if document:
            item = {
                **item,
                'payment_review_document_id': str(document.id),
                'payment_review_payment_number': document.payment_number,
                'payment_review_order_number': ', '.join(
                    (document.validation_summary or {}).get('order_numbers') or [document.order_number]
                ),
            }
            pending_review.append(item)
        else:
            blocked.append(item)
    return JsonResponse({
        'ok': True,
        'ready': ready,
        'blocked': blocked,
        'pending_review': pending_review,
    })


@csrf_exempt
@require_http_methods(["POST"])
def portal_payment_selection(request):
    """Preview or submit an explicitly selected payment batch for review.

    ``final=true`` is retained for client compatibility, but it now creates a
    review snapshot.  Only the Head of Rural approval endpoint can create the
    immutable final payment artifact.
    """
    from core.services.payment_documents import (
        PaymentTemplateError, create_payment_document,
        normalize_payment_number, payment_readiness, serialize_payment_document,
    )
    body = _json_body(request)
    farmer_ids = [str(value) for value in (body.get('farmer_ids') or []) if value]
    final = bool(body.get('final'))
    access_error = _portal_read_access_error(request, capability='portal.payment.prepare')
    if access_error:
        return access_error
    from core.models import JawabuFarmerMaster
    selected_farmers = list(JawabuFarmerMaster.objects.filter(id__in=farmer_ids).only('branch'))
    if len(selected_farmers) != len(set(farmer_ids)):
        return JsonResponse({'ok': False, 'error': 'One or more selected cases was not found.'}, status=404)
    for farmer in selected_farmers:
        access_error = _portal_read_access_error(request, farmer, capability='portal.payment.prepare')
        if access_error:
            return access_error
    try:
        payment_number = normalize_payment_number(body.get('payment_number'))
        if final:
            from core.models import JawabuFarmerMaster
            already_paid = JawabuFarmerMaster.objects.filter(
                id__in=farmer_ids, pipeline_events__action='payment_finalized',
            ).values_list('customer_name', flat=True)
            already_paid = list(already_paid)
            if already_paid:
                raise PaymentTemplateError(
                    'Already finalized in a payment batch: ' + ', '.join(already_paid[:5])
                )
        scope = f'PAYMENT-{payment_number}'
        readiness = payment_readiness(scope, farmer_ids=farmer_ids)
        if final:
            from core.models import PaymentDocument
            selected_set = set(farmer_ids)
            existing_review = next(
                (
                    candidate for candidate in PaymentDocument.objects.filter(
                        order_number=scope,
                        payment_number=payment_number,
                        status='pending_review',
                    ).order_by('-created_at')
                    if set(str(value) for value in (candidate.farmer_ids or [])) == selected_set
                ),
                None,
            )
            if existing_review:
                return JsonResponse({
                    'ok': True,
                    'document': serialize_payment_document(existing_review),
                    'requires_head_rural_review': True,
                    'idempotent_replay': True,
                })
            pending_map = _pending_payment_review_map(request)
            overlap = [pending_map[str(farmer_id)] for farmer_id in farmer_ids if str(farmer_id) in pending_map]
            if overlap:
                numbers = ', '.join(sorted({str(doc.payment_number or doc.order_number) for doc in overlap}))
                raise PaymentTemplateError(
                    f'One or more selected cases is already awaiting Head of Rural payment review ({numbers}). '
                    'Open the Review queue to complete that batch first.'
                )
            document = create_payment_document(
                scope, payment_number, actor=_portal_sender_from_request(request),
                final=False,
                status='pending_review',
                farmer_ids=farmer_ids,
            )
            return JsonResponse({
                'ok': True,
                'document': serialize_payment_document(document),
                'requires_head_rural_review': True,
            })
        # Previewing a payment is deliberately data-only. Generating an Excel
        # workbook here made preview depend on Drive/template availability and
        # triggered the blank-canvas failure in Telegram WebViews.
        return JsonResponse({
            'ok': True,
            'readiness': readiness,
            'workbook_preview': None,
        })
    except PaymentTemplateError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)


@require_http_methods(["GET"])
def portal_payment_preview_data(request, order_number: str):
    """Return canonical payment rows for the printable in-app preview."""
    from core.services.payment_documents import PaymentTemplateError, normalize_payment_number, payment_readiness

    try:
        payment_number = normalize_payment_number(request.GET.get('payment_number'))
    except PaymentTemplateError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)

    access_error = _portal_capability_error(request, 'portal.payment.view') or _portal_order_scope_error(request, order_number)
    if access_error:
        return access_error

    readiness = payment_readiness(order_number)
    rows = [item.get('row') or {} for item in readiness.get('ready', [])]
    amount_keys = ('hb_invoice_amount', 'expected_invoice_amount', 'discount', 'deposit_paid_hbg', 'deposit_paid_jbl', 'loan_amount')
    totals = {}
    for key in amount_keys:
        values = [row.get(key) for row in rows if row.get(key) not in (None, '')]
        totals[key] = str(sum(values)) if values else None
    return JsonResponse({'ok': readiness.get('blocked_count', 0) == 0, 'preview': {
        'order_number': order_number, 'payment_number': payment_number, 'rows': rows, 'totals': totals,
        'ready_count': readiness.get('ready_count', 0), 'blocked': readiness.get('blocked', []),
    }, 'workbook_preview': None})


@csrf_exempt
@require_http_methods(["POST"])
def portal_payment_document_preview(request, order_number: str):
    """Create a Drive-backed payment workbook preview."""
    from core.services.payment_documents import (
        PaymentTemplateError,
        approve_payment_document,
        create_payment_document,
        payment_readiness,
        serialize_payment_document,
    )

    access_error = _portal_capability_error(request, 'portal.payment.prepare') or _portal_order_scope_error(request, order_number)
    if access_error:
        return access_error

    try:
        doc = create_payment_document(
            order_number,
            payment_number=_json_body(request).get('payment_number'),
            actor=_portal_sender_from_request(request),
            final=False,
        )
    except PaymentTemplateError as exc:
        return JsonResponse({'ok': False, 'error': str(exc), 'readiness': payment_readiness(order_number)}, status=400)
    except Exception as exc:
        logger.exception("Payment preview generation failed for order %s", order_number)
        return JsonResponse({'ok': False, 'error': 'Payment preview could not be stored. Check synchronization status and retry.'}, status=502)
    return JsonResponse({'ok': True, 'document': serialize_payment_document(doc)})


@csrf_exempt
@require_http_methods(["POST"])
def portal_payment_document_finalize(request, order_number: str):
    """Create a Drive-backed payment review snapshot.

    The historical URL is kept so older Mini App clients continue to work,
    but it no longer bypasses Head of Rural approval.
    """
    from core.services.payment_documents import (
        PaymentTemplateError,
        create_payment_document,
        normalize_payment_number,
        payment_readiness,
        serialize_payment_document,
    )

    access_error = _portal_capability_error(request, 'portal.payment.prepare') or _portal_order_scope_error(request, order_number)
    if access_error:
        return access_error

    body = _json_body(request)
    try:
        payment_number = normalize_payment_number(body.get('payment_number'))
        # The batch detail page can be retried by Telegram/WebView or by a
        # double tap. Reuse the current review snapshot instead of creating a
        # second visible payment card for the same order and payment number.
        from core.models import PaymentDocument
        existing_review = PaymentDocument.objects.filter(
            order_number=order_number,
            payment_number=payment_number,
            status='pending_review',
        ).order_by('-version', '-created_at').first()
        if existing_review:
            return JsonResponse({
                'ok': True,
                'document': serialize_payment_document(existing_review),
                'requires_head_rural_review': True,
                'idempotent_replay': True,
            })
        doc = create_payment_document(
            order_number,
            payment_number=payment_number,
            actor=_portal_sender_from_request(request),
            final=False,
            status='pending_review',
        )
    except PaymentTemplateError as exc:
        return JsonResponse({'ok': False, 'error': str(exc), 'readiness': payment_readiness(order_number)}, status=400)
    except Exception as exc:
        logger.exception("Payment review generation failed for order %s", order_number)
        return JsonResponse({'ok': False, 'error': 'Payment review could not be stored. Check synchronization status and retry.'}, status=502)
    return JsonResponse({
        'ok': True,
        'document': serialize_payment_document(doc),
        'requires_head_rural_review': True,
    })


@csrf_exempt
@require_http_methods(["POST"])
def portal_payment_document_approve(request, document_id: str):
    """Approve a payment review and create the true final workbook."""
    from core.models import JawabuFarmerMaster, PaymentDocument
    from core.services.payment_documents import (
        PaymentTemplateError,
        approve_payment_document,
        payment_readiness,
        serialize_payment_document,
    )

    try:
        document = PaymentDocument.objects.get(pk=document_id)
    except PaymentDocument.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Payment review not found.'}, status=404)

    farmers = list(JawabuFarmerMaster.objects.filter(id__in=document.farmer_ids or []))
    if len(farmers) != len(set(document.farmer_ids or [])):
        return JsonResponse({'ok': False, 'error': 'The payment review references a missing case.'}, status=409)
    for farmer in farmers:
        role_error = _portal_approval_authority_error(request, farmer, 'payment_review')
        if role_error:
            return role_error

    body = _json_body(request)
    comment = str(body.get('call_up_comments') or body.get('decision_comment') or '').strip()
    case_comments = body.get('case_call_up_comments') or {}
    if not isinstance(case_comments, dict):
        return JsonResponse({'ok': False, 'error': 'case_call_up_comments must be an object keyed by case ID.'}, status=400)
    # Keep old clients working when they send one batch comment, but require
    # the current per-case contract whenever the review form submits comments.
    if not case_comments and not comment:
        return JsonResponse({'ok': False, 'error': 'Enter a Head of Rural Call Up Comment for every selected case.'}, status=400)
    try:
        final_document = approve_payment_document(
            str(document.id),
            actor=_portal_sender_from_request(request),
            actor_user=getattr(request, 'portal_user', None),
            access=getattr(request, 'portal_access', None),
            call_up_comments=comment,
            case_call_up_comments={str(key): str(value or '').strip() for key, value in case_comments.items()},
        )
    except PaymentTemplateError as exc:
        return JsonResponse({
            'ok': False,
            'error': str(exc),
            'readiness': payment_readiness(
                document.order_number,
                farmer_ids=list(document.farmer_ids or []),
            ),
        }, status=400)
    except Exception:
        logger.exception('Payment approval failed for review %s', document_id)
        return JsonResponse({'ok': False, 'error': 'Payment approval could not be completed. Check synchronization status and retry.'}, status=502)
    return JsonResponse({'ok': True, 'document': serialize_payment_document(final_document)})


@csrf_exempt
@require_http_methods(["POST"])
def portal_payment_document_regenerate(request, document_id: str):
    """Create a new payment review snapshot from a saved payment document.

    Regeneration deliberately re-enters the Head-of-Rural review state.  A
    saved final workbook is an audit artifact and must never be overwritten or
    silently treated as an approved replacement.
    """
    from core.models import JawabuFarmerMaster, PaymentDocument
    from core.services.payment_documents import (
        PaymentTemplateError,
        create_payment_document,
        payment_readiness,
        serialize_payment_document,
    )

    try:
        source = PaymentDocument.objects.get(
            pk=document_id,
            status__in=['pending_review', 'final', 'failed'],
        )
    except PaymentDocument.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Payment document was not found or cannot be regenerated.'}, status=404)

    farmer_ids = [str(value) for value in (source.farmer_ids or []) if value]
    if not farmer_ids:
        # Payment documents created before farmer_ids became part of the
        # snapshot can still be regenerated from their stored preview rows.
        farmer_ids = [
            str((row or {}).get('farmer_id')).strip()
            for row in (source.validation_summary or {}).get('preview_rows', [])
            if (row or {}).get('farmer_id')
        ]
    if not farmer_ids:
        farmer_ids = [
            str(value)
            for value in JawabuFarmerMaster.objects.filter(
                order_number=source.order_number,
                status='active',
            ).values_list('id', flat=True)
        ]
    if not farmer_ids:
        return JsonResponse({
            'ok': False,
            'error': 'The saved payment document has no linked active cases. It cannot be regenerated safely.',
        }, status=409)
    farmers = list(
        JawabuFarmerMaster.objects.filter(id__in=farmer_ids, status='active')
    ) if farmer_ids else []
    if farmer_ids and len(farmers) != len(set(farmer_ids)):
        return JsonResponse({'ok': False, 'error': 'The saved payment document references a missing case.'}, status=409)
    if farmers:
        access_error = _portal_capability_error(request, 'portal.documents.regenerate') or _portal_farmers_scope_error(request, farmers)
    else:
        access_error = _portal_order_scope_error(request, source.order_number)
    if access_error:
        return access_error

    # A pending review is already the current editable payment snapshot. A
    # repeated regenerate click must replay that document instead of creating
    # another indistinguishable review row/version.
    if source.status == 'pending_review':
        return JsonResponse({
            'ok': True,
            'document': serialize_payment_document(source),
            'regenerated_from_document_id': str(source.id),
            'requires_head_rural_review': True,
            'idempotent_replay': True,
        })

    source_summary = source.validation_summary or {}
    source_artifact_status = str(source_summary.get('artifact_status') or '').strip()
    if source.status == 'failed' and source_artifact_status == 'final':
        review_id = str(source_summary.get('review_document_id') or '').strip()
        if not review_id:
            return JsonResponse({
                'ok': False,
                'error': 'This failed final has no linked payment review. Recreate the payment review before retrying.',
            }, status=409)
        role_error = _portal_role_error(request, 'payment.review')
        if role_error:
            return role_error
        try:
            final_document = approve_payment_document(
                review_id,
                actor=_portal_sender_from_request(request),
                call_up_comments=source.call_up_comments,
                case_call_up_comments=source.case_call_up_comments or {},
            )
        except PaymentTemplateError as exc:
            return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
        except Exception:
            logger.exception('Failed payment final retry failed for %s', document_id)
            return JsonResponse({
                'ok': False,
                'error': 'Payment final retry failed. Check synchronization status and retry.',
            }, status=502)
        return JsonResponse({
            'ok': True,
            'document': serialize_payment_document(final_document),
            'retried_from_document_id': str(source.id),
            'idempotent_replay': False,
        })

    try:
        regenerated = create_payment_document(
            source.order_number,
            payment_number=source.payment_number,
            actor=_portal_sender_from_request(request),
            final=False,
            status=source_artifact_status if source.status == 'failed' and source_artifact_status in {'preview', 'pending_review'} else 'pending_review',
            farmer_ids=farmer_ids or None,
            call_up_comments=source.call_up_comments,
            case_call_up_comments=source.case_call_up_comments or {},
        )
    except PaymentTemplateError as exc:
        return JsonResponse({
            'ok': False,
            'error': str(exc),
            'readiness': payment_readiness(
                source.order_number,
                farmer_ids=farmer_ids or None,
            ),
        }, status=400)
    except Exception:
        logger.exception('Payment document regeneration failed for %s', document_id)
        return JsonResponse({
            'ok': False,
            'error': 'Payment document could not be regenerated. Check synchronization status and retry.',
        }, status=502)

    return JsonResponse({
        'ok': True,
        'document': serialize_payment_document(regenerated),
        'regenerated_from_document_id': str(source.id),
        'requires_head_rural_review': True,
    })


@require_http_methods(["GET"])
def portal_document_history(request):
    """List generated order documents and payment review/final artifacts."""
    from core.models import PaymentDocument, RequisitionBatch
    from core.services.document_signoffs import (
        can_approve_physical_signoff,
        document_signoff_summary,
    )

    access_error = _portal_read_access_error(request, capability='portal.documents.view')
    if access_error:
        return access_error

    kind = request.GET.get('kind', 'orders')
    from core.services.compliance_audit import record_sensitive_access
    record_sensitive_access(
        workflow='portal',
        action='portal.document_history.view',
        subject_type='document_history',
        subject_id=str(kind),
        actor=getattr(request, 'portal_user', None),
        actor_label=_portal_sender_from_request(request),
        request_id=_portal_request_id(request),
        metadata={'kind': kind},
    )
    can_sign_requisition = can_approve_physical_signoff(
        getattr(request, 'portal_user', None),
        getattr(request, 'portal_access', None),
        'requisition',
    )
    can_sign_payment = can_approve_physical_signoff(
        getattr(request, 'portal_user', None),
        getattr(request, 'portal_access', None),
        'payment',
    )
    if kind == 'payments':
        # Keep pending review snapshots visible to Head of Rural.  Final
        # history and review work are one payment register, but their status
        # remains explicit so a draft can never be mistaken for a final.
        documents = PaymentDocument.objects.filter(
            status__in=['pending_review', 'final', 'failed'],
        ).order_by('-created_at')[:100]
        return JsonResponse({'ok': True, 'kind': kind, 'documents': [
            {
                'id': str(doc.id),
                'order_number': ', '.join((doc.validation_summary or {}).get('order_numbers') or [doc.order_number]),
                'status': doc.status,
                'version': doc.version,
                'filename': doc.filename,
                'payment_number': doc.payment_number, 'row_count': doc.row_count,
                'generated_by': doc.finalized_by or doc.generated_by,
                # For a final document, finalized_at is set after the final
                # workbook upload. A review's updated_at is set after its
                # workbook upload, so it is more accurate than created_at
                # (which is reserved before the Drive call).
                'generated_at': (doc.finalized_at or doc.updated_at or doc.created_at).isoformat(),
                'workbook_generated_at': (doc.finalized_at or doc.updated_at or doc.created_at).isoformat(),
                'drive_url': doc.drive_url,
                'sync_status': (
                    'retryable_failure' if doc.error else 'succeeded' if doc.drive_url else 'pending'
                ),
                'sync_error': doc.error or '',
                'sync_attempts': getattr(doc, 'drive_sync_attempts', 0) or 0,
                'next_retry_at': doc.drive_next_retry_at.isoformat() if getattr(doc, 'drive_next_retry_at', None) else None,
                'farmer_ids': [str(value) for value in (doc.farmer_ids or [])],
                'physical_signoff': document_signoff_summary(
                    'payment', doc, can_upload=can_sign_payment,
                ),
            }
            for doc in documents
            if _portal_saved_document_in_scope(request, doc.order_number, doc.farmer_ids)
        ]})
    documents = RequisitionBatch.objects.exclude(status='preview').order_by('-updated_at')[:100]
    return JsonResponse({'ok': True, 'kind': 'orders', 'documents': [
        {
            'id': str(doc.id), 'order_number': doc.order_number,
            'version': getattr(doc, 'version', 0) or 0,
            'filename': doc.filename,
            'preview_version': getattr(doc, 'preview_version', 0) or 0,
            'preview_filename': getattr(doc, 'preview_filename', '') or '',
            'row_count': doc.farmer_count, 'generated_by': doc.generated_by,
            'generated_at': doc.updated_at.isoformat(),
            'drive_url': doc.drive_url,
            'requisition_date': doc.requisition_date.isoformat() if doc.requisition_date else None,
            'workbook_generated_at': doc.updated_at.isoformat(),
            'farmer_ids': [str(value) for value in (doc.farmer_ids or [])],
            'sync_status': _artifact_sync_status(doc.drive_url, doc.drive_upload_error),
            'sync_error': doc.drive_upload_error or '',
            'physical_signoff': document_signoff_summary(
                'requisition', doc, can_upload=can_sign_requisition,
            ),
        }
        for doc in documents
        if _portal_saved_document_in_scope(request, doc.order_number, doc.farmer_ids)
    ]})


def _portal_document_signoff_document(request, document_type: str, document_id: str):
    """Resolve an artifact and apply the normal document/scope guard first."""
    from django.shortcuts import get_object_or_404
    from core.models import PaymentDocument, RequisitionBatch

    if document_type == 'requisition':
        document = get_object_or_404(RequisitionBatch, pk=document_id)
        farmer_ids = document.farmer_ids
        order_number = document.order_number
    elif document_type == 'payment':
        document = get_object_or_404(PaymentDocument, pk=document_id)
        farmer_ids = document.farmer_ids
        order_number = document.order_number
    else:
        return None, JsonResponse({'ok': False, 'error': 'Unsupported document type.'}, status=404)
    if _portal_capability_error(request, 'portal.documents.sign') or not _portal_saved_document_in_scope(request, order_number, farmer_ids):
        return None, JsonResponse({'ok': False, 'error': 'You do not have access to sign this document.'}, status=403)
    return document, None


@csrf_exempt
@require_http_methods(["POST"])
def portal_document_physical_signoff_upload(request, document_type: str, document_id: str):
    """Upload one externally signed/stamped scan for a retained workbook."""
    from core.services.document_signoffs import PhysicalSignoffError, submit_physical_signoff, serialize_physical_signoff

    _document, access_error = _portal_document_signoff_document(request, document_type, document_id)
    if access_error:
        return access_error
    if str(request.POST.get('attested_complete') or '').casefold() not in {'1', 'true', 'yes', 'on'}:
        return JsonResponse({
            'ok': False,
            'error': 'Confirm that the scan is complete, signed, stamped, readable, and matches this exact document version.',
        }, status=400)
    try:
        signoff, replayed = submit_physical_signoff(
            document_type=document_type,
            document_id=document_id,
            uploaded_file=request.FILES.get('signed_scan'),
            actor=getattr(request, 'portal_user', None),
            access=getattr(request, 'portal_access', None),
            request_id=_portal_request_id(request),
        )
    except PhysicalSignoffError as exc:
        return JsonResponse({'ok': False, 'error': '; '.join(exc.messages)}, status=400)
    except Exception:
        logger.exception('Physical sign-off submission failed: document_type=%s document_id=%s', document_type, document_id)
        return JsonResponse({'ok': False, 'error': 'The signed scan could not be stored. Retry without changing the document version.'}, status=502)
    payload = serialize_physical_signoff(
        signoff,
        document_type=document_type,
        source_available=True,
        can_upload=True,
    )
    return JsonResponse({
        'ok': signoff.status != 'upload_failed',
        'pending_retry': signoff.status == 'upload_failed',
        'idempotent_replay': replayed,
        'signoff': payload,
    }, status=202 if signoff.status == 'upload_failed' else 200)


@csrf_exempt
@require_http_methods(["POST"])
def portal_document_physical_signoff_retry(request, signoff_id: str):
    """Retry a failed Drive upload without accepting a second scan."""
    from core.models import DocumentPhysicalSignoff
    from core.services.document_signoffs import (
        PhysicalSignoffError,
        retry_physical_signoff,
        serialize_physical_signoff,
    )

    try:
        existing = DocumentPhysicalSignoff.objects.select_related('requisition_batch', 'payment_document').get(pk=signoff_id)
    except DocumentPhysicalSignoff.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Signed-scan record not found.'}, status=404)
    document = existing.requisition_batch or existing.payment_document
    if _portal_capability_error(request, 'portal.documents.sign') or not _portal_saved_document_in_scope(
        request,
        getattr(document, 'order_number', ''),
        getattr(document, 'farmer_ids', []),
    ):
        return JsonResponse({'ok': False, 'error': 'You do not have access to retry this signed scan.'}, status=403)
    try:
        signoff = retry_physical_signoff(
            signoff_id=signoff_id,
            actor=getattr(request, 'portal_user', None),
            access=getattr(request, 'portal_access', None),
        )
    except PhysicalSignoffError as exc:
        return JsonResponse({'ok': False, 'error': '; '.join(exc.messages)}, status=400)
    except Exception:
        logger.exception('Physical sign-off retry failed: signoff=%s', signoff_id)
        return JsonResponse({'ok': False, 'error': 'The signed-scan upload could not be retried.'}, status=502)
    return JsonResponse({
        'ok': signoff.status != 'upload_failed',
        'pending_retry': signoff.status == 'upload_failed',
        'signoff': serialize_physical_signoff(signoff, document_type=signoff.document_type, source_available=True, can_upload=True),
    }, status=202 if signoff.status == 'upload_failed' else 200)


@require_http_methods(["GET"])
def portal_payment_document_detail(request, document_id: str):
    """Return the printable snapshot for a payment review or final artifact."""
    from django.shortcuts import get_object_or_404
    from core.models import PaymentDocument
    from core.services.payment_documents import payment_readiness, serialize_payment_document

    doc = get_object_or_404(
        PaymentDocument,
        pk=document_id,
        status__in=['pending_review', 'final', 'failed'],
    )
    if _portal_capability_error(request, 'portal.documents.view') or not _portal_saved_document_in_scope(request, doc.order_number, doc.farmer_ids):
        return JsonResponse({'ok': False, 'error': 'You do not have access to this payment document.'}, status=403)
    from core.services.compliance_audit import record_sensitive_access
    record_sensitive_access(
        workflow='portal',
        action='portal.payment_document.view',
        subject_type='payment_document',
        subject_id=str(doc.pk),
        actor=getattr(request, 'portal_user', None),
        actor_label=_portal_sender_from_request(request),
        request_id=_portal_request_id(request),
        metadata={'order_number': doc.order_number, 'payment_number': doc.payment_number, 'version': doc.version},
    )
    summary = doc.validation_summary or {}
    rows = summary.get('preview_rows')
    if rows is None:  # Compatibility for final documents generated before snapshots existed.
        rows = [item['row'] for item in payment_readiness(doc.order_number).get('ready', [])]
    rows = list(rows or [])
    if doc.status == 'pending_review':
        # Pending snapshots created before the payment/order comment split may
        # have copied the order comment into row-level ``call_up_comments``.
        # Never expose that value as a payment COL; only the per-case map is a
        # valid HOR payment comment.
        case_comments = {str(key): str(value or '').strip() for key, value in (doc.case_call_up_comments or {}).items()}
        farmer_ids = [str(value) for value in (doc.farmer_ids or [])]
        sanitized_rows = []
        for index, row in enumerate(rows):
            clean_row = dict(row or {})
            farmer_id = str(clean_row.get('farmer_id') or (farmer_ids[index] if index < len(farmer_ids) else '')).strip()
            if farmer_id:
                clean_row['farmer_id'] = farmer_id
            clean_row['call_up_comments'] = case_comments.get(farmer_id, '')
            sanitized_rows.append(clean_row)
        rows = sanitized_rows
    amount_keys = ('hb_invoice_amount', 'discount', 'deposit_paid_hbg', 'deposit_paid_jbl')
    totals = {}
    for key in amount_keys:
        values = [row.get(key) for row in rows if row.get(key) not in (None, '')]
        from decimal import Decimal
        totals[key] = str(sum(Decimal(str(value)) for value in values)) if values else None
    return JsonResponse({'ok': True, 'document': serialize_payment_document(doc), 'preview': {
        'order_number': ', '.join(summary.get('order_numbers') or [doc.order_number]),
        'payment_number': doc.payment_number,
        'ready_count': len(rows), 'rows': rows, 'totals': totals,
    }, 'workbook_preview': None})
