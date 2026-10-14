"""Telegram Main Mini App entry point; no cross-workflow role inheritance."""
from django.conf import settings
from django.contrib.auth import authenticate
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from core.services.telegram_identity import TelegramAuthenticationError
from core.services.request_throttling import consume_ip


@require_GET
def miniapp_launcher(request):
    response = render(request, 'miniapp_launcher.html')
    response['Cache-Control'] = 'no-store, private'
    return response


@csrf_exempt  # Verified initData, never the browser session, supplies identity.
@require_POST
def miniapp_available(request):
    limit = int(getattr(settings, 'TELEGRAM_SESSION_LOGIN_RATE_LIMIT', 120))
    throttle = consume_ip(request, scope='miniapp_launcher:network', limit=limit)
    if not throttle.allowed:
        response = JsonResponse({'ok': False, 'error': 'Please wait a moment and try again.'}, status=429)
        response['Retry-After'] = str(throttle.retry_after)
        return response
    try:
        user = authenticate(request, init_data=request.headers.get('X-Telegram-Init-Data', ''))
    except TelegramAuthenticationError:
        user = None
    if not user or not user.is_active:
        response = JsonResponse({'ok': False, 'error': 'Open JBL Apps from Telegram using your linked staff account.'}, status=403)
    else:
        from core.services.miniapp_launcher import available_apps
        response = JsonResponse({'ok': True, 'apps': available_apps(user)})
    response['Cache-Control'] = 'no-store, private'
    return response
