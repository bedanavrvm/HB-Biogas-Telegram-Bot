from django.contrib.auth import authenticate, login
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.services.telegram_identity import TelegramAuthenticationError, user_access
from core.services.miniapp_requests import miniapp_idempotency_boundary
from core.services.request_throttling import consume_identity, consume_ip


def _limited(retry_after: int) -> JsonResponse:
    response = JsonResponse({
        'ok': False,
        'error': 'Too many login attempts. Wait a short while and try again.',
        'code': 'retry_later',
    }, status=429)
    response['Retry-After'] = str(retry_after)
    return response


@csrf_exempt
@require_POST
@miniapp_idempotency_boundary
def telegram_session_login(request):
    """Create a normal Django session from freshly validated Telegram initData."""
    limit = int(getattr(settings, 'TELEGRAM_SESSION_LOGIN_RATE_LIMIT', 20))
    network = consume_ip(request, scope='telegram_session_login:network', limit=limit)
    if not network.allowed:
        return _limited(network.retry_after)
    init_data = request.headers.get('X-Telegram-Init-Data', '') or request.POST.get('init_data', '')
    try:
        user = authenticate(request, init_data=init_data)
    except TelegramAuthenticationError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=403)
    if user is None or not user.is_active:
        return JsonResponse({'ok': False, 'error': 'Telegram account is not linked to an active user.'}, status=403)
    actor = consume_identity(
        scope='telegram_session_login:actor', kind='django_user', value=user.pk, limit=limit,
    )
    if not actor.allowed:
        return _limited(actor.retry_after)
    login(request, user, backend='core.auth_backends.TelegramMiniAppBackend')
    workflows = {
        workflow: user_access(user, workflow)
        for workflow in ('jawabu_portal', 'complaint_cases', 'tat_tracker')
    }
    return JsonResponse({
        'ok': True,
        'user': {
            'id': user.pk,
            'username': user.get_username(),
            'display_name': user.get_full_name() or user.get_username(),
            'workflows': {
                key: {
                    'authorized': value['authorized'],
                    'roles': value['roles'],
                    'branches': value['branches'],
                    'products': value['products'],
                }
                for key, value in workflows.items()
            },
        },
    })
