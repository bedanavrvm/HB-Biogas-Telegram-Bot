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
import uuid
from functools import wraps
from urllib.parse import parse_qsl, quote

from django.conf import settings
from django.contrib.auth import login
from django.core.signing import BadSignature, TimestampSigner
from django.http import HttpResponse, JsonResponse
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
        is_valid, error, payload = validate_portal_telegram_init_data(
            _portal_init_data_from_request(request)
        )
        if not is_valid:
            return JsonResponse({'ok': False, 'error': error}, status=403)
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
                return JsonResponse({
                    'ok': False,
                    'error': f'Your Telegram account{account_label} is not authorized for the Jawabu Portal.',
                }, status=403)
            if access and access['authorized']:
                login(request, canonical_user, backend='core.auth_backends.TelegramMiniAppBackend')
                request.portal_user = canonical_user
                request.portal_access = access
        return view_func(request, *args, **kwargs)
    return wrapper


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
    return str(request.headers.get('X-Request-ID') or (body or {}).get('request_id') or '').strip()[:128]


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


def _paginate_list(items: list, request, page_size: int = 30):
    """Return a paginated slice and pagination metadata for already-built portal payloads."""
    start, end, pagination = _pagination_window(request, len(items), page_size)
    return items[start:end], pagination


def _apply_county_branch_filters(qs, request):
    from django.db.models import Q

    county = request.GET.get('county', '').strip()
    branch = request.GET.get('branch', '').strip()
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


PORTAL_VIEW_ROLES = {
    'viewer', 'jbl_officer', 'credit_analyst', 'head_rural', 'operations',
}


def _portal_read_access_error(request, farmer=None):
    """Apply the same role and branch guard to read endpoints as writes."""
    return _portal_role_error(request, PORTAL_VIEW_ROLES, farmer)


def _portal_role_error(request, allowed_roles: set[str], farmer=None):
    access = getattr(request, 'portal_access', None)
    if access is None:  # Authentication is intentionally disabled in local/test environments.
        return None
    roles = {str(value).strip().lower() for value in access.get('roles', [])}
    if 'hb_staff' in roles:
        roles.add('operations')
    if 'admin' not in roles and roles.isdisjoint(allowed_roles):
        return JsonResponse({'ok': False, 'error': 'You are not authorized for this Jawabu workflow action.'}, status=403)
    branches = {str(value).strip().casefold() for value in access.get('branches', []) if str(value).strip()}
    if farmer is not None and branches and str(farmer.branch or '').strip().casefold() not in branches:
        return JsonResponse({'ok': False, 'error': 'This case is outside your authorized branch scope.'}, status=403)
    return None


def _portal_order_scope_error(request, order_number: str):
    """Check that every application in an order is inside the actor scope."""
    from core.models import JawabuFarmerMaster

    access_error = _portal_read_access_error(request)
    if access_error:
        return access_error
    farmers = JawabuFarmerMaster.objects.filter(order_number=order_number).only('branch')
    for farmer in farmers:
        access_error = _portal_read_access_error(request, farmer)
        if access_error:
            return access_error
    return None


def _portal_farmers_scope_error(request, farmers, allowed_roles=None):
    """Apply role and branch scope to a selected set of applications."""
    role_error = _portal_role_error(request, allowed_roles or PORTAL_VIEW_ROLES)
    if role_error:
        return role_error
    for farmer in farmers:
        role_error = _portal_role_error(request, allowed_roles or PORTAL_VIEW_ROLES, farmer)
        if role_error:
            return role_error
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
    if _portal_read_access_error(request):
        return False
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
    'jbl': {'service': 'jbl_visit_queue', 'mode': 'jbl_visit', 'empty_title': 'All caught up!', 'empty_sub': 'No farmers match the current JBL visit filters.'},
    'credit': {'service': 'credit_queue', 'mode': 'credit', 'empty_title': 'No BRO analysis cases', 'empty_sub': 'No farmers match the current credit filters.'},
    'final': {'service': 'final_review_queue', 'mode': 'final_review', 'empty_title': 'No final review cases', 'empty_sub': 'No clients match the current final review filters.'},
    'requisition': {'service': 'requisition_queue', 'mode': 'requisition', 'empty_title': 'No approved cases', 'empty_sub': 'No credit-approved farmers are awaiting an order number. Assigned orders are available under Batches.'},
    'deferred': {'service': 'deferred_queue', 'mode': '', 'empty_title': 'No deferred cases', 'empty_sub': 'No deferred or flagged farmers match the current filters.'},
    'all': {'service': 'all_cases', 'mode': '', 'empty_title': 'No farmers found', 'empty_sub': 'Try a different search term or filter.'},
}


def _portal_queue_queryset(queue_key: str, request):
    from core.services import jawabu_pipeline

    config = PORTAL_QUEUE_FRAGMENT_CONFIG.get(queue_key)
    if not config:
        return None, None

    if queue_key == 'all':
        qs = jawabu_pipeline.all_cases(
            search=request.GET.get('search', '').strip(),
            county=request.GET.get('county', '').strip(),
            branch=request.GET.get('branch', '').strip(),
        )
        qs = _apply_county_branch_filters(qs, request)
    else:
        qs = getattr(jawabu_pipeline, config['service'])()
        qs = _apply_county_branch_filters(qs, request)
    return qs, config


# ── Render View ───────────────────────────────────────────────────────────────


def _batch_download_url(request, order_number: str) -> str:
    # Excel links are opened in Telegram's system browser, which cannot send
    # the Mini App initData header.  Bind a short-lived signed URL to the
    # already-authorized batch instead of weakening the API download route.
    token = TimestampSigner(salt='portal-requisition-download').sign(str(order_number))
    return request.build_absolute_uri(
        f'/api/portal/requisition-download/{quote(token, safe="")}/'
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


def _validate_requisition_farmers(farmers) -> tuple[list[dict], list[dict], list[dict]]:
    from core.services.jawabu_pipeline import farmer_to_card

    ready = []
    blocked = []
    warnings = []
    for farmer in farmers:
        card = farmer_to_card(farmer)
        deposit = farmer.deposit_paid_hbg if farmer.deposit_paid_hbg is not None else farmer.actual_receipts
        paid_to_jbl = bool(farmer.lead_source and 'jbl' in farmer.lead_source.lower())
        card['requisition_preview'] = {
            'location': ' - '.join(part for part in (
                str(farmer.sub_county or '').strip(), str(farmer.village or '').strip(),
            ) if part),
            'hbg_deposit': '' if paid_to_jbl else str(deposit or ''),
            'jbl_deposit': str(deposit or '') if paid_to_jbl else '',
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
    from core.models import JawabuFarmerMaster, RequisitionBatch

    if farmer_ids:
        return list(JawabuFarmerMaster.objects.filter(id__in=farmer_ids).order_by('customer_name'))
    return list(JawabuFarmerMaster.objects.filter(order_number=order_number).order_by('customer_name'))


def _serialize_batch(batch, farmers, request, include_farmers: bool = True) -> dict:
    summary = _invoice_summary_for_farmers(farmers)
    stored_summary = batch.invoice_summary or {}
    if stored_summary:
        # Counts come from current farmer records. Keep upload metadata from the
        # stored snapshot, but never let stale snapshot counts override reality.
        summary = {**stored_summary, **summary}
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
        'preview_filename': getattr(batch, 'preview_filename', '') or '',
        'preview_drive_url': getattr(batch, 'preview_drive_url', '') or '',
        'preview_drive_file_id': getattr(batch, 'preview_drive_file_id', '') or '',
        'preview_generated_by': getattr(batch, 'preview_generated_by', '') or '',
        'preview_generated_at': batch.preview_generated_at.isoformat() if getattr(batch, 'preview_generated_at', None) else None,
        'preview_error': getattr(batch, 'preview_error', '') or '',
        'farmer_count': batch.farmer_count or len(farmers),
        'invoiced_count': summary.get('invoiced_count', 0),
        'status': batch.status,
        'invoice_summary': summary,
        'amount_summary': _batch_amount_summary(farmers),
        'last_invoice_result': batch.last_invoice_result or {},
        'farmers': farmers_payload,
    }


def _batch_amount_summary(farmers) -> dict:
    from decimal import Decimal, InvalidOperation

    keys = ('deposit_hb', 'deposit_jbl', 'invoice_amount', 'discount', 'payment', 'balance_due')
    totals = {key: Decimal('0') for key in keys}
    present = {key: False for key in keys}
    for farmer in farmers:
        is_jbl = bool(farmer.lead_source and 'jbl' in farmer.lead_source.lower())
        raw = {
            'deposit_hb': None if is_jbl else farmer.actual_receipts,
            'deposit_jbl': farmer.system_deposit_paid_jbl if farmer.system_deposit_paid_jbl is not None else (farmer.actual_receipts if is_jbl else None),
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


def _parse_requisition_workbook_payload(request):
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

    ready, blocked, warnings = _validate_requisition_farmers(farmers)
    if blocked:
        first = blocked[0]
        name = first['farmer'].get('customer_name') or first['farmer'].get('national_id') or 'Selected client'
        return None, JsonResponse({
            'ok': False,
            'error': f"{name} is not ready for requisition: {', '.join(first['missing'])}.",
            'blocked': blocked,
            'warnings': warnings,
        }, status=403)

    return {
        'body': body,
        'farmers': farmers,
        'farmer_ids': farmer_ids,
        'order_number': order_number,
        'requisition_date': requisition_date,
        'warnings': warnings,
    }, None


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
    from core.services.portal_navigation import PORTAL_NAV_ITEMS
    known_screens = {item[0] for item in PORTAL_NAV_ITEMS}
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


# ── Dashboard ─────────────────────────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["GET"])
def portal_dashboard(request):
    access_error = _portal_read_access_error(request)
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
    access_error = _portal_read_access_error(request)
    if access_error:
        return access_error
    """GET /api/portal/meta/ — lookup lists for Mini App dropdowns."""
    from core.models import JawabuFarmerMaster
    from core.services.branches import global_branch_choices
    from core.services.locations import global_county_choices
    branches = global_branch_choices()
    staff_branches = {
        str(value).strip().casefold()
        for value in getattr(request, 'portal_access', {}).get('branches', [])
        if str(value).strip()
    }
    if staff_branches:
        branches = [branch for branch in branches if branch.casefold() in staff_branches]
    return JsonResponse({
        'ok': True,
        'branches': branches,
        'counties': global_county_choices(),
        'jbl_visit_statuses': [c[0] for c in JawabuFarmerMaster.JBL_VISIT_STATUS_CHOICES],
        'credit_decisions': [c[0] for c in JawabuFarmerMaster.CREDIT_DECISION_CHOICES],
        'imab_created_options': ['Yes', 'No', 'Pending'],
        'final_decisions': [c[0] for c in JawabuFarmerMaster.FINAL_DECISION_CHOICES],
    })


# ── Stage 2: JBL Visit queue ──────────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["GET"])
def portal_jbl_queue(request):
    access_error = _portal_read_access_error(request)
    if access_error:
        return access_error
    """GET /api/portal/jbl-queue/ — farmers awaiting JBL visit."""
    from core.services.jawabu_pipeline import jbl_visit_queue, farmer_to_card
    qs = _apply_county_branch_filters(jbl_visit_queue(), request)
    items, pagination = _paginate_qs(qs, request)
    return JsonResponse({
        'ok': True,
        'queue': 'jbl_visit',
        'farmers': [farmer_to_card(f) for f in items],
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
    access_error = _portal_read_access_error(request)
    if access_error:
        return access_error
    """GET /api/portal/queues/<queue_key>/fragment/ - htmx-rendered farmer queue."""
    from core.services.jawabu_pipeline import farmer_to_card

    qs, config = _portal_queue_queryset(queue_key, request)
    if qs is None:
        return HttpResponse('Unknown portal queue.', status=404)

    items, pagination = _paginate_qs(qs, request)
    return render(request, 'portal/partials/farmer_list.html', {
        'farmers': [farmer_to_card(f) for f in items],
        'pagination': pagination,
        'queue_key': queue_key,
        'mode': config['mode'],
        'county': request.GET.get('county', '').strip(),
        'branch': request.GET.get('branch', '').strip(),
        'search': request.GET.get('search', '').strip(),
        'empty_title': config['empty_title'],
        'empty_sub': config['empty_sub'],
    })


@csrf_exempt
@require_http_methods(["POST"])
def portal_log_jbl_visit(request, farmer_id: str):
    """
    POST /api/portal/jbl-queue/<farmer_id>/
    Body: { visit_date, visit_status, officer, comment }
    """
    from datetime import date as _date
    from core.models import JawabuFarmerMaster
    from core.services.jawabu_pipeline import log_jbl_visit, farmer_to_card

    try:
        farmer = JawabuFarmerMaster.objects.get(pk=farmer_id)
    except JawabuFarmerMaster.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Farmer not found.'}, status=404)

    role_error = _portal_role_error(request, {'jbl_officer'}, farmer)
    if role_error:
        return role_error

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'Invalid JSON body.'}, status=400)

    visit_date_raw = str(body.get('visit_date') or '').strip()
    if not visit_date_raw:
        visit_date = _date.today()
    else:
        try:
            visit_date = _date.fromisoformat(visit_date_raw)
        except ValueError:
            return JsonResponse(
                {'ok': False, 'error': f"Invalid visit_date '{visit_date_raw}'. Use YYYY-MM-DD."},
                status=400,
            )

    visit_status = str(body.get('visit_status') or '').strip()
    officer = str(body.get('officer') or '').strip()
    comment = str(body.get('comment') or '').strip()
    sender = _portal_sender_from_request(request) or officer
    county = str(body.get('county') or '').strip() if 'county' in body else None
    sub_county = str(body.get('sub_county') or '').strip() if 'sub_county' in body else None
    village = str(body.get('village') or '').strip() if 'village' in body else None

    latitude = body.get('latitude')
    longitude = body.get('longitude')
    try:
        latitude = float(latitude) if latitude is not None and str(latitude).strip() != '' else None
        longitude = float(longitude) if longitude is not None and str(longitude).strip() != '' else None
    except (ValueError, TypeError):
        return JsonResponse({'ok': False, 'error': 'Invalid coordinates format.'}, status=400)

    ok, error = log_jbl_visit(
        farmer,
        visit_date=visit_date,
        officer=officer or sender,
        visit_status=visit_status,
        comment=comment,
        sender=sender,
        latitude=latitude,
        longitude=longitude,
        county=county,
        sub_county=sub_county,
        village=village,
        request_id=_portal_request_id(request, body),
    )
    if not ok:
        return JsonResponse({'ok': False, 'error': error}, status=400)
    return JsonResponse({'ok': True, 'farmer': farmer_to_card(farmer)})


# ── Stage 3: Credit Decision queue ───────────────────────────────────────────

@csrf_exempt
@require_http_methods(["POST"])
def portal_upload_jbl_media(request, farmer_id: str):
    """POST /api/portal/jbl-queue/<farmer_id>/media/ - upload visit media to Drive."""
    from core.models import JawabuFarmerMaster
    from core.services.jawabu_pipeline import append_jbl_media_links, farmer_to_card

    try:
        farmer = JawabuFarmerMaster.objects.get(pk=farmer_id)
    except JawabuFarmerMaster.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Farmer not found.'}, status=404)

    role_error = _portal_role_error(request, {'jbl_officer'}, farmer)
    if role_error:
        return role_error

    getlist = getattr(request.FILES, 'getlist', None)
    files = getlist('files') if getlist else []
    if not files:
        files = list(request.FILES.values())
    if not files:
        return JsonResponse({'ok': False, 'error': 'Select at least one document or image to upload.'}, status=400)

    sender = _portal_sender_from_request(request)
    media_category = request.POST.get('media_category', 'LAF')
    ok, error, result = append_jbl_media_links(
        farmer,
        uploaded_files=files,
        sender=sender,
        media_category=media_category,
    )
    if not ok:
        return JsonResponse({'ok': False, 'error': error, **result}, status=400)
    return JsonResponse({'ok': True, 'farmer': farmer_to_card(farmer), **result})


@csrf_exempt
@require_http_methods(["GET"])
def portal_jbl_media(request, farmer_id: str):
    """GET /api/portal/jbl-queue/<farmer_id>/media/ - current LAF links."""
    from core.models import JawabuFarmerMaster, MediaAttachment

    try:
        farmer = JawabuFarmerMaster.objects.get(pk=farmer_id)
    except JawabuFarmerMaster.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Farmer not found.'}, status=404)

    access_error = _portal_read_access_error(request, farmer)
    if access_error:
        return access_error

    business_key = str(farmer.national_id or '').strip()
    attachments = MediaAttachment.objects.filter(
        business_key_type='id_number',
        business_key_value=business_key,
        file_type='LAF',
        upload_status='success',
    ).exclude(drive_url='').order_by('-created_at')
    laf_media = [
        {
            'url': item.drive_url,
            'name': item.original_filename or 'LAF document',
            'created_at': item.created_at.isoformat() if item.created_at else '',
        }
        for item in attachments
    ]
    # Older uploads may predate categorized MediaAttachment rows. Keep them
    # viewable as a clearly labelled fallback rather than hiding the evidence.
    if not laf_media:
        laf_media = [
            {'url': url.strip(), 'name': 'Legacy LAF/media link', 'created_at': ''}
            for url in str(farmer.jbl_media_urls or '').splitlines()
            if url.strip()
        ]
    return JsonResponse({'ok': True, 'laf_media': laf_media})

@csrf_exempt
@require_http_methods(["GET"])
def portal_credit_queue(request):
    access_error = _portal_read_access_error(request)
    if access_error:
        return access_error
    """GET /api/portal/credit-queue/ — farmers awaiting credit analysis."""
    from core.services.jawabu_pipeline import credit_queue, farmer_to_card
    qs = _apply_county_branch_filters(credit_queue(), request)
    items, pagination = _paginate_qs(qs, request)
    return JsonResponse({
        'ok': True,
        'queue': 'credit',
        'farmers': [farmer_to_card(f) for f in items],
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

    role_error = _portal_role_error(request, {'credit_analyst'}, farmer)
    if role_error:
        return role_error

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'Invalid JSON body.'}, status=400)

    decision = str(body.get('decision') or '').strip()
    imab_created = str(body.get('imab_created') or '').strip()
    customer_no = str(body.get('customer_no') or '').strip()
    if not decision:
        return JsonResponse({'ok': False, 'error': 'decision is required.'}, status=400)

    sender = _portal_sender_from_request(request)
    ok, error = set_credit_decision(
        farmer,
        decision=decision,
        imab_created=imab_created,
        customer_no=customer_no,
        sender=sender,
        request_id=_portal_request_id(request, body),
    )
    if not ok:
        return JsonResponse({'ok': False, 'error': error}, status=400)
    return JsonResponse({'ok': True, 'farmer': farmer_to_card(farmer)})



# Stage 4: Head of Rural final review

@csrf_exempt
@require_http_methods(["GET"])
def portal_final_review_queue(request):
    access_error = _portal_read_access_error(request)
    if access_error:
        return access_error
    """GET /api/portal/final-review-queue/ - records awaiting Head of Rural final decision."""
    from core.services.jawabu_pipeline import final_review_queue, farmer_to_card
    qs = _apply_county_branch_filters(final_review_queue(), request)
    items, pagination = _paginate_qs(qs, request)
    return JsonResponse({
        'ok': True,
        'queue': 'final_review',
        'farmers': [farmer_to_card(f) for f in items],
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

    role_error = _portal_role_error(request, {'head_rural'}, farmer)
    if role_error:
        return role_error

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'Invalid JSON body.'}, status=400)

    final_decision = str(body.get('final_decision') or '').strip()
    decision_comment = str(body.get('decision_comment') or '').strip()
    repayment_date = str(body.get('repayment_date') or '').strip() if 'repayment_date' in body else None
    repayment_tenor = str(body.get('repayment_tenor') or '').strip() if 'repayment_tenor' in body else None
    if not final_decision:
        return JsonResponse({'ok': False, 'error': 'final_decision is required.'}, status=400)

    sender = _portal_sender_from_request(request)
    ok, error = set_final_decision(
        farmer,
        final_decision=final_decision,
        decision_comment=decision_comment,
        repayment_date=repayment_date,
        repayment_tenor=repayment_tenor,
        sender=sender,
        request_id=_portal_request_id(request, body),
    )
    if not ok:
        return JsonResponse({'ok': False, 'error': error}, status=400)
    return JsonResponse({'ok': True, 'farmer': farmer_to_card(farmer)})

# ── Stage 4: Requisition / Order queue ───────────────────────────────────────

@csrf_exempt
@require_http_methods(["GET"])
def portal_requisition_queue(request):
    access_error = _portal_read_access_error(request)
    if access_error:
        return access_error
    """GET /api/portal/requisition-queue/ — credit-approved farmers awaiting order."""
    from core.services.jawabu_pipeline import requisition_queue, farmer_to_card
    qs = _apply_county_branch_filters(requisition_queue(), request)
    items, pagination = _paginate_qs(qs, request)
    return JsonResponse({
        'ok': True,
        'queue': 'requisition',
        'farmers': [farmer_to_card(f) for f in items],
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

    role_error = _portal_role_error(request, {'operations'}, farmer)
    if role_error:
        return role_error

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'Invalid JSON body.'}, status=400)

    order_number = str(body.get('order_number') or '').strip()
    requisition_date_raw = str(body.get('requisition_date') or '').strip()
    requisition_date = None
    if requisition_date_raw:
        try:
            requisition_date = _date.fromisoformat(requisition_date_raw)
        except ValueError:
            return JsonResponse(
                {'ok': False, 'error': f"Invalid requisition_date '{requisition_date_raw}'. Use YYYY-MM-DD."},
                status=400,
            )

    sender = _portal_sender_from_request(request)
    ok, error = assign_order(
        farmer,
        order_number=order_number,
        requisition_date=requisition_date,
        repayment_date=body.get('repayment_date'),
        repayment_tenor=body.get('repayment_tenor'),
        payment_product=body.get('payment_product'),
        sender=sender,
        request_id=_portal_request_id(request, body),
    )
    if not ok:
        # Gate failure → 403 Forbidden
        status_code = 403 if 'Final Decision' in error or 'final review' in error.lower() else 400
        return JsonResponse({'ok': False, 'error': error}, status=status_code)
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
    qs = _apply_county_branch_filters(qs, request)
    items, pagination = _paginate_qs(qs, request)
    return JsonResponse({
        'ok': True,
        'farmers': [farmer_to_card(f) for f in items],
        'pagination': pagination,
    })


@csrf_exempt
@require_http_methods(["GET"])
def portal_deferred(request):
    access_error = _portal_read_access_error(request)
    if access_error:
        return access_error
    """GET /api/portal/deferred/ — deferred/rejected/flagged farmers."""
    from core.services.jawabu_pipeline import deferred_queue, reappraisal_required_queue, farmer_to_card
    qs = _apply_county_branch_filters((deferred_queue() | reappraisal_required_queue()).distinct(), request)
    items, pagination = _paginate_qs(qs, request)
    return JsonResponse({
        'ok': True,
        'queue': 'deferred',
        'farmers': [farmer_to_card(f) for f in items],
        'pagination': pagination,
    })


@csrf_exempt
@require_http_methods(["GET"])
def portal_farmer_detail(request, farmer_id: str):
    """GET /api/portal/farmers/<farmer_id>/ — full detail for one farmer."""
    from core.models import JawabuFarmerMaster
    from core.services.jawabu_pipeline import farmer_to_card
    try:
        farmer = JawabuFarmerMaster.objects.get(pk=farmer_id)
    except JawabuFarmerMaster.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Farmer not found.'}, status=404)
    access_error = _portal_read_access_error(request, farmer)
    if access_error:
        return access_error
    from core.services.jawabu_case360 import serialize_case360
    return JsonResponse({'ok': True, 'farmer': farmer_to_card(farmer), 'case360': serialize_case360(farmer)})



@csrf_exempt
@require_http_methods(["POST"])
def portal_requisition_preview(request):
    """POST /api/portal/requisition-queue/preview/ - validate selected clients before generating Excel."""
    from datetime import date as _date
    from core.models import JawabuFarmerMaster

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'Invalid JSON body.'}, status=400)

    farmer_ids = body.get('farmer_ids') or []
    order_number = str(body.get('order_number') or '').strip()
    requisition_date_raw = str(body.get('requisition_date') or '').strip()
    # The in-app preview is intentionally data-only. Workbook rendering in a
    # Telegram WebView is unreliable and belongs to the confirmed download.
    preview_format = 'document'
    if not farmer_ids:
        return JsonResponse({'ok': False, 'error': 'No farmers selected.'}, status=400)
    if not order_number:
        return JsonResponse({'ok': False, 'error': 'Order Number / Batch Ref is required.'}, status=400)
    if not requisition_date_raw:
        return JsonResponse({'ok': False, 'error': 'Requisition Date is required.'}, status=400)
    try:
        requisition_date = _date.fromisoformat(requisition_date_raw)
    except ValueError:
        return JsonResponse({'ok': False, 'error': f"Invalid requisition_date '{requisition_date_raw}'. Use YYYY-MM-DD."}, status=400)

    farmers = list(JawabuFarmerMaster.objects.filter(id__in=farmer_ids))
    if len(farmers) != len(farmer_ids):
        return JsonResponse({'ok': False, 'error': 'One or more selected farmers was not found.'}, status=404)
    access_error = _portal_farmers_scope_error(request, farmers)
    if access_error:
        return access_error

    existing_order = (
        JawabuFarmerMaster.objects
        .filter(order_number=order_number)
        .exclude(id__in=farmer_ids)
        .count()
    )
    ready, blocked, warnings = _validate_requisition_farmers(farmers)
    if existing_order:
        warnings.append({
            'message': f"Order number {order_number} already exists on {existing_order} other client(s). Generating will add/update this same batch.",
        })
    return JsonResponse({
        'ok': True,
        'order_number': order_number,
        'requisition_date': requisition_date.isoformat(),
        'ready_count': len(ready),
        'blocked_count': len(blocked),
        'warning_count': len(warnings),
        'ready': ready,
        'blocked': blocked,
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
    access_error = _portal_farmers_scope_error(request, farmers, {'operations'})
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
    summary = _invoice_summary_for_farmers(farmers)
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
        batch.preview_drive_file_id = ''
        batch.preview_drive_url = ''
        batch.preview_generated_by = sender
        batch.preview_generated_at = timezone.now()
        batch.preview_error = 'Drive synchronization pending.'
        batch.farmer_ids = [str(farmer.id) for farmer in farmers]
        batch.farmer_count = len(farmers)
        if not batch.version:
            batch.status = 'preview'
        batch.invoice_summary = summary
        batch.save()
    try:
        drive_file_id, drive_url = _upload_generated_workbook_to_drive(xlsx_bytes, filename, order_number)
        preview_error = ''
    except Exception as exc:
        logger.exception('Requisition preview workbook was not stored in Google Drive.')
        batch.preview_error = 'Drive upload failed; retry required.'
        batch.save(update_fields=['preview_error', 'updated_at'])
        return JsonResponse({
            'ok': False,
            'error': 'Requisition preview could not be stored. Check synchronization status and retry.',
        }, status=502)

    batch.preview_drive_file_id = drive_file_id
    batch.preview_drive_url = drive_url
    batch.preview_error = preview_error
    batch.save(update_fields=[
        'preview_drive_file_id', 'preview_drive_url', 'preview_error', 'updated_at',
    ])

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
    access_error = _portal_farmers_scope_error(request, farmers, {'operations'})
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

    # Assign order details only after the Excel has been generated successfully.
    sender = _portal_sender_from_request(request)
    batch_request_id = _portal_request_id(request, body)
    for farmer in farmers:
        if farmer.order_number != order_number or farmer.requisition_date != requisition_date:
            assign_order(
                farmer,
                order_number=order_number,
                requisition_date=requisition_date,
                sender=sender,
                request_id=f'{batch_request_id}:{farmer.id}' if batch_request_id else '',
            )

    summary = _invoice_summary_for_farmers(farmers)
    from django.db import transaction

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
        batch.drive_file_id = ''
        batch.drive_url = ''
        batch.drive_upload_error = 'Drive synchronization pending.'
        batch.farmer_ids = [str(farmer.id) for farmer in farmers]
        batch.farmer_count = len(farmers)
        batch.status = 'needs_review'
        batch.invoice_summary = summary
        batch.save()
    try:
        drive_file_id, drive_url = _upload_generated_workbook_to_drive(xlsx_bytes, filename, order_number)
        drive_upload_error = ''
    except Exception as exc:
        logger.exception('Generated requisition workbook was not stored in Google Drive.')
        batch.drive_upload_error = 'Drive upload failed; retry required.'
        batch.status = 'needs_review'
        batch.save(update_fields=['drive_upload_error', 'status', 'updated_at'])
        return JsonResponse({
            'ok': False,
            'error': 'Generated requisition workbook could not be stored. Check synchronization status and retry.',
        }, status=502)

    batch.drive_file_id = drive_file_id
    batch.drive_url = drive_url
    batch.drive_upload_error = drive_upload_error
    batch.status = summary.get('status') or 'generated'
    batch.save(update_fields=[
        'drive_file_id', 'drive_url', 'drive_upload_error', 'status', 'updated_at',
    ])

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
    access_error = _portal_read_access_error(request)
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
    access_error = _portal_read_access_error(request)
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
        access_error = _portal_farmers_scope_error(request, farmers)
        if access_error:
            return access_error
        payload = _serialize_batch(batch, farmers, request)
        return JsonResponse({'ok': True, 'batch': payload})
    except RequisitionBatch.DoesNotExist:
        farmers = list(JawabuFarmerMaster.objects.filter(order_number=order_number).order_by('customer_name'))
        if not farmers:
            return JsonResponse({'ok': False, 'error': 'Batch not found.'}, status=404)
        access_error = _portal_farmers_scope_error(request, farmers)
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
        access_error = _portal_read_access_error(request, farmer)
        if access_error:
            return access_error
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
def portal_upload_batch_invoices(request):
    """POST /api/portal/requisition-batches/upload-invoices/ — upload a combined PDF of invoices for a batch/order."""
    order_number = request.POST.get('order_number') or request.GET.get('order_number')
    role_error = _portal_role_error(request, {'operations', 'credit_analyst'})
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
    role_error = _portal_role_error(request, {'operations', 'credit_analyst'})
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
    return {
        'id': str(batch.id),
        'original_filename': batch.original_filename,
        'content_type': batch.content_type,
        'size': batch.size,
        'uploaded_by': batch.uploaded_by,
        'drive_file_id': batch.drive_file_id,
        'drive_url': batch.drive_url,
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
        role_error = _portal_role_error(request, {'operations', 'credit_analyst'}, invoice.matched_farmer)
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
        role_error = _portal_role_error(request, {'operations', 'credit_analyst'})
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

    access_error = _portal_read_access_error(request)
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

    access_error = _portal_read_access_error(request, invoice.matched_farmer)
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

    access_error = _portal_read_access_error(request)
    if access_error:
        return access_error

    search = str(request.GET.get('search') or '').strip()
    invoice_id = str(request.GET.get('invoice_id') or '').strip()
    parsed_invoice = None
    if invoice_id:
        from core.models import ParsedInvoice
        parsed_invoice = ParsedInvoice.objects.select_related('matched_farmer').filter(pk=invoice_id).first()
        if parsed_invoice:
            access_error = _portal_read_access_error(request, parsed_invoice.matched_farmer)
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
    role_error = _portal_role_error(request, {'viewer', 'jbl_officer', 'credit_analyst', 'head_rural', 'operations'}, farmer)
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

    role_error = _portal_read_access_error(request, invoice.matched_farmer)
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

    role_error = _portal_read_access_error(request, invoice.matched_farmer)
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

    role_error = _portal_read_access_error(request, invoice.matched_farmer)
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
    role_error = _portal_read_access_error(request)
    if role_error:
        return role_error
    for invoice in invoices:
        role_error = _portal_read_access_error(request, invoice.matched_farmer)
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

    access_error = _portal_order_scope_error(request, order_number)
    if access_error:
        return access_error

    return JsonResponse({'ok': True, 'data': payment_readiness(order_number)})


@require_http_methods(["GET"])
def portal_payment_candidates(request):
    """List active invoice-matched cases available for a selected payment batch."""
    from core.models import JawabuFarmerMaster
    from core.services.payment_documents import payment_readiness
    from django.db.models import Q

    access_error = _portal_read_access_error(request)
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
    return JsonResponse({'ok': True, 'ready': readiness['ready'], 'blocked': readiness['blocked']})


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
    access_error = _portal_read_access_error(request)
    if access_error:
        return access_error
    from core.models import JawabuFarmerMaster
    selected_farmers = list(JawabuFarmerMaster.objects.filter(id__in=farmer_ids).only('branch'))
    if len(selected_farmers) != len(set(farmer_ids)):
        return JsonResponse({'ok': False, 'error': 'One or more selected cases was not found.'}, status=404)
    for farmer in selected_farmers:
        access_error = _portal_read_access_error(request, farmer)
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

    access_error = _portal_order_scope_error(request, order_number)
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
        create_payment_document,
        payment_readiness,
        serialize_payment_document,
    )

    access_error = _portal_order_scope_error(request, order_number)
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
        payment_readiness,
        serialize_payment_document,
    )

    access_error = _portal_order_scope_error(request, order_number)
    if access_error:
        return access_error

    try:
        doc = create_payment_document(
            order_number,
            payment_number=_json_body(request).get('payment_number'),
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
    role_error = _portal_role_error(request, {'head_rural'})
    if role_error:
        return role_error
    for farmer in farmers:
        role_error = _portal_role_error(request, {'head_rural'}, farmer)
        if role_error:
            return role_error

    body = _json_body(request)
    comment = str(body.get('call_up_comments') or body.get('decision_comment') or '').strip()
    if not comment:
        return JsonResponse({'ok': False, 'error': 'Head of Rural Call Up Comments are required before approval.'}, status=400)
    try:
        final_document = approve_payment_document(
            str(document.id),
            actor=_portal_sender_from_request(request),
            call_up_comments=comment,
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


@require_http_methods(["GET"])
def portal_document_history(request):
    """List generated order documents and payment review/final artifacts."""
    from core.models import PaymentDocument, RequisitionBatch

    access_error = _portal_read_access_error(request)
    if access_error:
        return access_error

    kind = request.GET.get('kind', 'orders')
    if kind == 'payments':
        # Keep pending review snapshots visible to Head of Rural.  Final
        # history and review work are one payment register, but their status
        # remains explicit so a draft can never be mistaken for a final.
        documents = PaymentDocument.objects.filter(
            status__in=['pending_review', 'final'],
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
                'generated_at': (doc.finalized_at or doc.created_at).isoformat(),
                'drive_url': doc.drive_url,
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
        }
        for doc in documents
        if _portal_saved_document_in_scope(request, doc.order_number, doc.farmer_ids)
    ]})


@require_http_methods(["GET"])
def portal_payment_document_detail(request, document_id: str):
    """Return the printable snapshot for a payment review or final artifact."""
    from django.shortcuts import get_object_or_404
    from core.models import PaymentDocument
    from core.services.payment_documents import payment_readiness, serialize_payment_document

    doc = get_object_or_404(
        PaymentDocument,
        pk=document_id,
        status__in=['pending_review', 'final'],
    )
    if not _portal_saved_document_in_scope(request, doc.order_number, doc.farmer_ids):
        return JsonResponse({'ok': False, 'error': 'You do not have access to this payment document.'}, status=403)
    summary = doc.validation_summary or {}
    rows = summary.get('preview_rows')
    if rows is None:  # Compatibility for final documents generated before snapshots existed.
        rows = [item['row'] for item in payment_readiness(doc.order_number).get('ready', [])]
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
