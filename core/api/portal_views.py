"""
Portal Mini App API views.

Endpoints for the JBL pipeline portal — imported into core/api/views.py.

Authentication: Telegram Mini App initData is passed as X-Telegram-Init-Data header.
Identity is derived from the initData user object (no STAFF sheet lookup).
Scope: all groups are aggregated by default.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
import uuid
from functools import wraps
from urllib.parse import parse_qsl, quote

from django.conf import settings
from django.core.cache import cache
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

    bot_token = getattr(settings, 'TELEGRAM_BOT_TOKEN', '')
    if not bot_token:
        return False, 'TELEGRAM_BOT_TOKEN is not configured.', {}
    if not init_data:
        return False, 'Telegram Mini App authentication data is missing.', {}

    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop('hash', '')
    if not received_hash:
        return False, 'Telegram Mini App hash is missing.', {}

    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(pairs.items())
    )
    secret_key = hmac.new(
        b'WebAppData',
        bot_token.encode('utf-8'),
        hashlib.sha256,
    ).digest()
    calculated_hash = hmac.new(
        secret_key,
        data_check_string.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(calculated_hash, received_hash):
        return False, 'Telegram Mini App authentication failed.', {}

    auth_date = pairs.get('auth_date')
    max_age = int(getattr(settings, 'PORTAL_WEBAPP_AUTH_MAX_AGE_SECONDS', 86400))
    if auth_date and max_age > 0:
        try:
            if time.time() - int(auth_date) > max_age:
                return False, 'Telegram Mini App authentication expired.', {}
        except ValueError:
            return False, 'Telegram Mini App auth_date is invalid.', {}

    return True, '', pairs


def portal_auth_required(view_func):
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        is_valid, error, payload = validate_portal_telegram_init_data(
            _portal_init_data_from_request(request)
        )
        if not is_valid:
            return JsonResponse({'ok': False, 'error': error}, status=403)
        request.portal_auth_payload = payload
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


# ── Render View ───────────────────────────────────────────────────────────────


def _batch_download_url(request, order_number: str) -> str:
    return request.build_absolute_uri(
        f'/api/portal/requisition-batches/{quote(str(order_number), safe="")}/download/'
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
        missing = []
        if farmer.final_decision != 'Approved':
            missing.append(f"Final Decision is {farmer.final_decision or 'not set'}")
        if not farmer.customer_name:
            missing.append('Customer Name')
        if not farmer.customer_no:
            missing.append('Customer No')
        if not farmer.imab_created:
            missing.append('IMAB status')
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
        summary = {**summary, **stored_summary}
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
                'branch': farmer.branch,
                'invoice_number': farmer.invoice_number,
                'invoice_date': farmer.invoice_date.strftime('%Y-%m-%d') if farmer.invoice_date else None,
                'invoice_amount': str(farmer.invoice_amount) if farmer.invoice_amount is not None else None,
                'balance_due': str(farmer.balance_due) if farmer.balance_due is not None else None,
                'invoiced': bool(farmer.invoice_number),
            })
    return {
        'id': str(batch.id),
        'order_number': batch.order_number,
        'requisition_date': batch.requisition_date.strftime('%Y-%m-%d') if batch.requisition_date else None,
        'generated_by': batch.generated_by,
        'generated_at': batch.created_at.isoformat() if batch.created_at else None,
        'updated_at': batch.updated_at.isoformat() if batch.updated_at else None,
        'filename': batch.filename,
        'has_requisition_file': bool(batch.file_content),
        'download_url': _batch_download_url(request, batch.order_number) if batch.file_content else '',
        'farmer_count': batch.farmer_count or len(farmers),
        'invoiced_count': summary.get('invoiced_count', 0),
        'status': batch.status,
        'invoice_summary': summary,
        'last_invoice_result': batch.last_invoice_result or {},
        'farmers': farmers_payload,
    }

@require_http_methods(["GET", "HEAD"])
def portal_home(request):
    """Render the main JBL Pipeline Portal Mini App page."""
    return render(request, 'portal/portal.html', {
        'invoice_upload_max_file_size_mb': int(getattr(settings, 'INVOICE_UPLOAD_MAX_FILE_SIZE_MB', 8) or 8),
    })


# ── Dashboard ─────────────────────────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["GET"])
def portal_dashboard(request):
    """GET /api/portal/dashboard/ — pipeline queue counts."""
    from core.services.jawabu_pipeline import pipeline_counts
    counts = pipeline_counts()
    return JsonResponse({'ok': True, 'counts': counts})


# ── Meta / dropdown lists ─────────────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["GET"])
def portal_meta(request):
    """GET /api/portal/meta/ — lookup lists for Mini App dropdowns."""
    from core.models import JawabuFarmerMaster
    return JsonResponse({
        'ok': True,
        'jbl_visit_statuses': [c[0] for c in JawabuFarmerMaster.JBL_VISIT_STATUS_CHOICES],
        'credit_decisions': [c[0] for c in JawabuFarmerMaster.CREDIT_DECISION_CHOICES],
        'imab_created_options': ['Yes', 'No', 'Pending'],
        'final_decisions': [c[0] for c in JawabuFarmerMaster.FINAL_DECISION_CHOICES],
    })


# ── Stage 2: JBL Visit queue ──────────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["GET"])
def portal_jbl_queue(request):
    """GET /api/portal/jbl-queue/ — farmers awaiting JBL visit."""
    from core.services.jawabu_pipeline import jbl_visit_queue, farmer_to_card
    qs = jbl_visit_queue()
    items, pagination = _paginate_qs(qs, request)
    return JsonResponse({
        'ok': True,
        'queue': 'jbl_visit',
        'farmers': [farmer_to_card(f) for f in items],
        'pagination': pagination,
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

    getlist = getattr(request.FILES, 'getlist', None)
    files = getlist('files') if getlist else []
    if not files:
        files = list(request.FILES.values())
    if not files:
        return JsonResponse({'ok': False, 'error': 'Select at least one document or image to upload.'}, status=400)

    sender = _portal_sender_from_request(request)
    ok, error, result = append_jbl_media_links(farmer, uploaded_files=files, sender=sender)
    if not ok:
        return JsonResponse({'ok': False, 'error': error, **result}, status=400)
    return JsonResponse({'ok': True, 'farmer': farmer_to_card(farmer), **result})

@csrf_exempt
@require_http_methods(["GET"])
def portal_credit_queue(request):
    """GET /api/portal/credit-queue/ — farmers awaiting credit analysis."""
    from core.services.jawabu_pipeline import credit_queue, farmer_to_card
    qs = credit_queue()
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
    )
    if not ok:
        return JsonResponse({'ok': False, 'error': error}, status=400)
    return JsonResponse({'ok': True, 'farmer': farmer_to_card(farmer)})



# Stage 4: Head of Rural final review

@csrf_exempt
@require_http_methods(["GET"])
def portal_final_review_queue(request):
    """GET /api/portal/final-review-queue/ - records awaiting Head of Rural final decision."""
    from core.services.jawabu_pipeline import final_review_queue, farmer_to_card
    qs = final_review_queue()
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
    Body: { final_decision, decision_comment }
    """
    from core.models import JawabuFarmerMaster
    from core.services.jawabu_pipeline import set_final_decision, farmer_to_card

    try:
        farmer = JawabuFarmerMaster.objects.get(pk=farmer_id)
    except JawabuFarmerMaster.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Farmer not found.'}, status=404)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'Invalid JSON body.'}, status=400)

    final_decision = str(body.get('final_decision') or '').strip()
    decision_comment = str(body.get('decision_comment') or '').strip()
    if not final_decision:
        return JsonResponse({'ok': False, 'error': 'final_decision is required.'}, status=400)

    sender = _portal_sender_from_request(request)
    ok, error = set_final_decision(
        farmer,
        final_decision=final_decision,
        decision_comment=decision_comment,
        sender=sender,
    )
    if not ok:
        return JsonResponse({'ok': False, 'error': error}, status=400)
    return JsonResponse({'ok': True, 'farmer': farmer_to_card(farmer)})

# ── Stage 4: Requisition / Order queue ───────────────────────────────────────

@csrf_exempt
@require_http_methods(["GET"])
def portal_requisition_queue(request):
    """GET /api/portal/requisition-queue/ — credit-approved farmers awaiting order."""
    from core.services.jawabu_pipeline import requisition_queue, farmer_to_card
    qs = requisition_queue()
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
        sender=sender,
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
    Query params: search, county, page
    """
    from core.services.jawabu_pipeline import all_cases, farmer_to_card
    search = request.GET.get('search', '').strip()
    county = request.GET.get('county', '').strip()
    qs = all_cases(search=search, county=county)
    items, pagination = _paginate_qs(qs, request)
    return JsonResponse({
        'ok': True,
        'farmers': [farmer_to_card(f) for f in items],
        'pagination': pagination,
    })


@csrf_exempt
@require_http_methods(["GET"])
def portal_deferred(request):
    """GET /api/portal/deferred/ — deferred/rejected/flagged farmers."""
    from core.services.jawabu_pipeline import deferred_queue, farmer_to_card
    qs = deferred_queue()
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
    return JsonResponse({'ok': True, 'farmer': farmer_to_card(farmer)})



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
    })

@csrf_exempt
@require_http_methods(["POST"])
def portal_requisition_generate(request):
    """
    POST /api/portal/requisition-queue/generate/
    Body: { farmer_ids: [...], order_number: "...", requisition_date: "..." }
    """
    from datetime import date as _date
    from core.models import JawabuFarmerMaster, RequisitionBatch
    from core.services.jawabu_pipeline import assign_order, sync_farmer_to_master_sheet
    from core.services.requisition import RequisitionTemplateError, generate_requisition_excel
    import json

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'Invalid JSON body.'}, status=400)

    farmer_ids = body.get('farmer_ids') or []
    order_number = str(body.get('order_number') or '').strip()
    requisition_date_raw = str(body.get('requisition_date') or '').strip()

    if not farmer_ids:
        return JsonResponse({'ok': False, 'error': 'No farmers selected.'}, status=400)
    if not order_number:
        return JsonResponse({'ok': False, 'error': 'Order Number / Batch Ref is required.'}, status=400)
    if not requisition_date_raw:
        return JsonResponse({'ok': False, 'error': 'Requisition Date is required.'}, status=400)

    try:
        requisition_date = _date.fromisoformat(requisition_date_raw)
    except ValueError:
        return JsonResponse(
            {'ok': False, 'error': f"Invalid requisition_date '{requisition_date_raw}'. Use YYYY-MM-DD."},
            status=400,
        )

    farmers = list(JawabuFarmerMaster.objects.filter(id__in=farmer_ids))
    if len(farmers) != len(farmer_ids):
        return JsonResponse({'ok': False, 'error': 'One or more selected farmers not found.'}, status=404)

    ready, blocked, warnings = _validate_requisition_farmers(farmers)
    if blocked:
        first = blocked[0]
        name = first['farmer'].get('customer_name') or first['farmer'].get('national_id') or 'Selected client'
        return JsonResponse({
            'ok': False,
            'error': f"{name} is not ready for requisition: {', '.join(first['missing'])}.",
            'blocked': blocked,
            'warnings': warnings,
        }, status=403)

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
    for farmer in farmers:
        if farmer.order_number != order_number or farmer.requisition_date != requisition_date:
            assign_order(
                farmer,
                order_number=order_number,
                requisition_date=requisition_date,
                sender=sender,
            )

    filename = f"JBL_Requisition_Form_{order_number}.xlsx"
    summary = _invoice_summary_for_farmers(farmers)
    batch, _created = RequisitionBatch.objects.update_or_create(
        order_number=order_number,
        defaults={
            'requisition_date': requisition_date,
            'generated_by': sender,
            'filename': filename,
            'file_content': xlsx_bytes,
            'farmer_ids': [str(farmer.id) for farmer in farmers],
            'farmer_count': len(farmers),
            'status': summary.get('status') or 'generated',
            'invoice_summary': summary,
        },
    )

    if body.get('return_url'):
        return JsonResponse({
            'ok': True,
            'filename': filename,
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
    payload = cache.get(f'portal_requisition_download:{token}')
    if not payload:
        return JsonResponse({'ok': False, 'error': 'Download link expired. Generate the requisition form again.'}, status=404)
    response = HttpResponse(
        b'' if request.method == 'HEAD' else payload['content'],
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = f'attachment; filename="{payload["filename"]}"'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@csrf_exempt
@require_http_methods(["GET"])
def portal_requisition_batches(request):
    """GET /api/portal/requisition-batches/ - generated batch output history."""
    from django.db.models import Count, Max
    from core.models import JawabuFarmerMaster, RequisitionBatch

    county = (request.GET.get('county') or '').strip().lower()
    branch = (request.GET.get('branch') or '').strip().lower()

    batches_list = []
    seen_orders = set()
    for batch in RequisitionBatch.objects.all().order_by('-requisition_date', '-updated_at'):
        farmers = _farmers_for_batch(batch.order_number, batch.farmer_ids or None)
        if county:
            farmers = [farmer for farmer in farmers if (farmer.county or '').lower() == county]
        if branch:
            farmers = [farmer for farmer in farmers if (farmer.branch or '').lower() == branch]
        if (county or branch) and not farmers:
            continue
        batches_list.append(_serialize_batch(batch, farmers, request))
        seen_orders.add(batch.order_number)

    # Include older sheet/order batches generated before RequisitionBatch existed.
    qs = JawabuFarmerMaster.objects.filter(order_number__isnull=False).exclude(order_number='')
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
            'last_invoice_result': {},
        })
        batches_list.append(payload)

    batches_list.sort(
        key=lambda item: (item.get('requisition_date') or '', item.get('updated_at') or '', item.get('order_number') or ''),
        reverse=True,
    )
    paged_batches, pagination = _paginate_list(batches_list, request)
    return JsonResponse({
        'ok': True,
        'batches': paged_batches,
        'pagination': pagination,
    })


@csrf_exempt
@require_http_methods(["GET"])
def portal_requisition_batch_detail(request, order_number: str):
    """GET /api/portal/requisition-batches/<order_number>/ - one batch with clients and invoice state."""
    from core.models import JawabuFarmerMaster, RequisitionBatch

    try:
        batch = RequisitionBatch.objects.get(order_number=order_number)
        farmers = _farmers_for_batch(order_number, batch.farmer_ids or None)
        return JsonResponse({'ok': True, 'batch': _serialize_batch(batch, farmers, request)})
    except RequisitionBatch.DoesNotExist:
        farmers = list(JawabuFarmerMaster.objects.filter(order_number=order_number).order_by('customer_name'))
        if not farmers:
            return JsonResponse({'ok': False, 'error': 'Batch not found.'}, status=404)
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
    if not order_number:
        return JsonResponse({'ok': False, 'error': 'order_number is required.'}, status=400)
    
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

    try:
        logger.info(
            'Invoice upload received: order=%s filename=%s size=%s bytes',
            order_number,
            getattr(pdf_file, 'name', ''),
            getattr(pdf_file, 'size', ''),
        )
        from core.models import RequisitionBatch
        from core.services.invoice_parser import match_and_update_invoices
        result = match_and_update_invoices(order_number, pdf_file.read())
        result['max_file_size_mb'] = max_mb
        try:
            batch = RequisitionBatch.objects.get(order_number=order_number)
            farmers = _farmers_for_batch(order_number, batch.farmer_ids or None)
            summary = _invoice_summary_for_farmers(farmers)
            summary.update({
                'total_parsed': result.get('total_parsed', 0),
                'matched_count': result.get('matched_count', 0),
                'candidate_count': result.get('candidate_count', 0),
            })
            if result.get('ok') and summary.get('pending_invoice_count') == 0:
                batch.status = 'completed'
            elif result.get('matched_count'):
                batch.status = 'partially_invoiced'
            else:
                batch.status = 'needs_review'
            batch.invoice_summary = summary
            batch.last_invoice_result = result
            batch.save(update_fields=['status', 'invoice_summary', 'last_invoice_result', 'updated_at'])
        except RequisitionBatch.DoesNotExist:
            pass
        return JsonResponse(result)
    except Exception as e:
        logger.exception("Error processing invoice PDF: %s", e)
        return JsonResponse({'ok': False, 'error': f"Failed to parse PDF: {str(e)}"}, status=500)
