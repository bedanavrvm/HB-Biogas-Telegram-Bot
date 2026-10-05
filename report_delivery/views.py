import json

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
