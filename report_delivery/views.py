import json
from django.core.exceptions import PermissionDenied, ValidationError

from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import WebhookReceipt
from .resend import verify_webhook
from .services import reconcile_webhooks

EVENTS = {'email.sent', 'email.delivered', 'email.delivery_delayed', 'email.bounced', 'email.complained', 'email.failed'}


def report_settings_response(actor, workflow, payload):
    from .settings import settings_action
    try:
        if not isinstance(payload, dict):
            raise ValidationError('Review the report settings.')
        return JsonResponse({'ok': True, 'data': settings_action(actor, workflow, payload)})
    except PermissionDenied:
        return JsonResponse({'ok': False, 'error': 'IT access is required for this app.'}, status=403)
    except (ValidationError, ValueError, TypeError) as exc:
        message = ' '.join(exc.messages) if isinstance(exc, ValidationError) else 'Review the selected report settings.'
        return JsonResponse({'ok': False, 'error': message}, status=400)


@csrf_exempt
@require_POST
def tat_report_settings(request):
    from core.api.views import _tat_context, _tat_json_body
    from django.contrib.auth import get_user_model
    payload = _tat_json_body(request)
    if not isinstance(payload, dict):
        return JsonResponse({'ok': False, 'error': 'Review the report settings.'}, status=400)
    _, _, _, user, error = _tat_context(payload)
    if error:
        return error
    actor = get_user_model().objects.filter(pk=user.get('user_id')).first()
    return report_settings_response(actor, 'tat_tracker', payload)


@csrf_exempt
@require_POST
def complaint_report_settings(request):
    from core.api.complaint_case_views import _context, _json_body
    payload = _json_body(request)
    if not isinstance(payload, dict):
        return JsonResponse({'ok': False, 'error': 'Review the report settings.'}, status=400)
    _, actor, error = _context(request, payload)
    if error:
        return error
    return report_settings_response(actor.user, 'complaint_cases', payload)


@csrf_exempt  # Signed provider raw-body HMAC is the authentication boundary.
@require_POST
def resend_webhook(request):
    if not settings.RESEND_WEBHOOK_SECRET:
        return JsonResponse({'ok': False}, status=503)
    if len(request.body) > 65536:
        return JsonResponse({'ok': False}, status=413)
    try:
        event_id, payload = verify_webhook(request.body, request.headers)
        event_type = payload.get('type', '')
        if event_type not in EVENTS:
            return JsonResponse({'ok': True})
        provider_id = payload['data']['email_id']
        occurred_at = parse_datetime(payload.get('created_at', ''))
        if not isinstance(provider_id, str) or not 1 <= len(provider_id) <= 100 or not occurred_at or timezone.is_naive(occurred_at):
            raise ValueError
    except (ValueError, KeyError, TypeError, AttributeError):
        return JsonResponse({'ok': False}, status=400)
    with transaction.atomic():
        _, created = WebhookReceipt.objects.get_or_create(event_id=event_id, defaults={
            'provider_id': provider_id, 'event_type': event_type, 'occurred_at': occurred_at,
        })
        if created:
            reconcile_webhooks(provider_id)
    return JsonResponse({'ok': True})
