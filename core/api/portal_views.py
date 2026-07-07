"""
Portal Mini App API views.

Endpoints for the JBL pipeline portal — imported into core/api/views.py.

Authentication: Telegram Mini App initData is passed as X-Telegram-Init-Data header.
Identity is derived from the initData user object (no STAFF sheet lookup).
Scope: all groups are aggregated by default.
"""
from __future__ import annotations

import json
import logging

from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

logger = logging.getLogger(__name__)


# ── Identity helper ───────────────────────────────────────────────────────────

def _portal_sender_from_request(request) -> str:
    """Extract a human-readable sender label from Telegram initData header."""
    raw = request.headers.get('X-Telegram-Init-Data', '')
    if not raw:
        return ''
    try:
        from urllib.parse import parse_qs
        params = parse_qs(raw)
        user_json = (params.get('user') or [''])[0]
        if not user_json:
            return ''
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


def _paginate_qs(qs, request, page_size: int = 30):
    """Return a paginated slice and pagination metadata."""
    try:
        page = max(1, int(request.GET.get('page', 1)))
    except (ValueError, TypeError):
        page = 1
    total = qs.count()
    start = (page - 1) * page_size
    end = start + page_size
    items = list(qs[start:end])
    return items, {
        'page': page,
        'page_size': page_size,
        'total': total,
        'pages': max(1, (total + page_size - 1) // page_size),
    }


# ── Render View ───────────────────────────────────────────────────────────────

@require_http_methods(["GET"])
def portal_home(request):
    """Render the main JBL Pipeline Portal Mini App page."""
    return render(request, 'portal/portal.html')


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
    if not decision:
        return JsonResponse({'ok': False, 'error': 'decision is required.'}, status=400)

    sender = _portal_sender_from_request(request)
    ok, error = set_credit_decision(farmer, decision=decision, sender=sender)
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

    GATE: Returns HTTP 403 if credit_decision != 'Approved'.
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
        status_code = 403 if 'Credit Decision' in error or 'credit' in error.lower() else 400
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
def portal_requisition_generate(request):
    """
    POST /api/portal/requisition-queue/generate/
    Body: { farmer_ids: [...], order_number: "...", requisition_date: "..." }
    """
    from datetime import date as _date
    from django.http import HttpResponse
    from core.models import JawabuFarmerMaster
    from core.services.jawabu_pipeline import assign_order, sync_farmer_to_master_sheet
    from core.services.requisition import generate_requisition_excel
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

    # Check credit status
    for farmer in farmers:
        if farmer.credit_decision != 'Approved':
            return JsonResponse({
                'ok': False,
                'error': f"Farmer '{farmer.customer_name}' is not credit-approved (status: '{farmer.credit_decision}'). Only approved cases can be requisitioned."
            }, status=403)

    # Assign order details to each farmer if not already set or different
    sender = _portal_sender_from_request(request)
    for farmer in farmers:
        if farmer.order_number != order_number or farmer.requisition_date != requisition_date:
            assign_order(
                farmer,
                order_number=order_number,
                requisition_date=requisition_date,
                sender=sender,
            )

    # Generate the populated requisition sheet
    xlsx_bytes = generate_requisition_excel(farmers, order_number, requisition_date)

    response = HttpResponse(
        xlsx_bytes,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    filename = f"JBL_Requisition_Form_{order_number}.xlsx"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


@csrf_exempt
@require_http_methods(["GET"])
def portal_requisition_batches(request):
    """GET /api/portal/requisition-batches/ — list of unique orders/requisition batches."""
    from django.db.models import Count, Max
    from core.models import JawabuFarmerMaster
    
    qs = JawabuFarmerMaster.objects.filter(
        order_number__isnull=False
    ).exclude(order_number='')
    
    county = request.GET.get('county') or ''
    branch = request.GET.get('branch') or ''
    if county:
        qs = qs.filter(county__iexact=county)
    if branch:
        qs = qs.filter(branch__iexact=branch)
        
    batches_data = qs.values('order_number').annotate(
        req_date=Max('requisition_date'),
        farmer_count=Count('id')
    ).order_by('-req_date', '-order_number')
    
    items, pagination = _paginate_qs(batches_data, request)
    
    batches_list = []
    for item in items:
        order_no = item['order_number']
        farmers_in_batch = qs.filter(order_number=order_no).values('id', 'customer_name', 'county', 'primary_phone')
        batches_list.append({
            'order_number': order_no,
            'requisition_date': item['req_date'].strftime('%Y-%m-%d') if item['req_date'] else None,
            'farmer_count': item['farmer_count'],
            'farmers': list(farmers_in_batch),
        })
        
    return JsonResponse({
        'ok': True,
        'batches': batches_list,
        'pagination': pagination,
    })
