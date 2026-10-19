"""Portal-authenticated HTTP boundary for pre-visit HB deposits."""

from django.core.exceptions import PermissionDenied
from django.db.models import F, Q
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from core.api.portal_views import _portal_capability_error, _portal_request_data, _portal_request_id, portal_auth_required
from .deposits import (
    DepositError, REQUIRED_DEPOSIT, VIEW_CAPABILITY, WRITE_CAPABILITY,
    deposit_queryset, scoped_deposits, serialize_deposit, update_deposit,
)


def _context(request):
    return getattr(request, 'portal_user', None), getattr(request, 'portal_access', None)


@portal_auth_required
@require_http_methods(['GET'])
def hb_deposit_list(request):
    denied = _portal_capability_error(request, VIEW_CAPABILITY)
    if denied:
        return denied
    actor, access = _context(request)
    queryset = deposit_queryset(scoped_deposits(actor, access))
    search = str(request.GET.get('search') or '').strip()
    if search:
        search_filter = (Q(customer_name__icontains=search) | Q(national_id__icontains=search)
                         | Q(primary_phone__icontains=search) | Q(customer_no__icontains=search))
        reference = search.upper().removeprefix('JBL-')
        if search.upper().startswith('JBL-') and reference.isdigit() and len(reference) <= 18:
            search_filter |= Q(case_reference_number=int(reference))
        queryset = queryset.filter(search_filter)
    held = Q(jbl_visit_date__isnull=True) & (Q(_deposit_total__isnull=True) | Q(_deposit_total__lt=REQUIRED_DEPOSIT))
    counts = {'awaiting': queryset.filter(held).count(), 'cleared': queryset.filter(_deposit_total__gte=REQUIRED_DEPOSIT).count(), 'all': queryset.count()}
    state = request.GET.get('state') or 'awaiting'
    if state not in counts:
        return JsonResponse({'ok': False, 'error': 'Choose Awaiting Deposit, Cleared or All.'}, status=400)
    if state == 'awaiting':
        queryset = queryset.filter(held)
    elif state == 'cleared':
        queryset = queryset.filter(_deposit_total__gte=REQUIRED_DEPOSIT)
    try:
        page = max(1, int(request.GET.get('page') or 1))
    except (TypeError, ValueError):
        page = 1
    total = counts[state]
    rows = list(queryset.order_by(F('hbg_visit_date').asc(nulls_last=True), 'created_at', 'pk')[(page - 1) * 30:page * 30])
    writable_ids = set(scoped_deposits(actor, access, WRITE_CAPABILITY).filter(pk__in=[row.pk for row in rows]).values_list('pk', flat=True))
    return JsonResponse({'ok': True, 'items': [serialize_deposit(row, actor=actor, access=access, write_allowed=row.pk in writable_ids) for row in rows],
                         'counts': counts, 'page': page, 'pages': max(1, (total + 29) // 30), 'total': total})


@portal_auth_required
@require_http_methods(['GET'])
def hb_deposit_detail(request, farmer_id):
    denied = _portal_capability_error(request, VIEW_CAPABILITY)
    if denied:
        return denied
    actor, access = _context(request)
    farmer = scoped_deposits(actor, access).filter(pk=farmer_id).first()
    if farmer is None:
        return JsonResponse({'ok': False, 'error': 'Deposit case not found.'}, status=404)
    return JsonResponse({'ok': True, 'deposit': serialize_deposit(farmer, actor=actor, access=access, history=True)})


@csrf_exempt  # Verified Telegram initData authenticates this non-cookie write.
@portal_auth_required
@require_http_methods(['POST'])
def hb_deposit_update(request, farmer_id):
    denied = _portal_capability_error(request, WRITE_CAPABILITY)
    if denied:
        return denied
    actor, access = _context(request)
    farmer = scoped_deposits(actor, access, WRITE_CAPABILITY).filter(pk=farmer_id).first()
    if farmer is None:
        return JsonResponse({'ok': False, 'error': 'Deposit case not found.'}, status=404)
    try:
        payload = _portal_request_data(request)
        if not isinstance(payload, dict):
            raise DepositError('Submit a valid deposit object.')
        farmer = update_deposit(
            farmer, amount=payload.get('amount'), reason=payload.get('reason'),
            expected_revision=int(payload.get('expected_revision') or 0),
            request_id=_portal_request_id(request, payload), actor=actor, access=access,
        )
    except PermissionDenied:
        return JsonResponse({'ok': False, 'error': 'This deposit action is outside your authorized scope.'}, status=403)
    except DepositError as exc:
        return JsonResponse({'ok': False, 'error': str(exc), 'code': exc.code}, status=exc.status)
    except (TypeError, ValueError):
        return JsonResponse({'ok': False, 'error': 'Submit a valid deposit amount and revision.'}, status=400)
    return JsonResponse({'ok': True, 'deposit': serialize_deposit(farmer, actor=actor, access=access, history=True)})
