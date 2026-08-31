from django.contrib.auth import authenticate, login
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.services.telegram_identity import TelegramAuthenticationError, user_access
from core.services.miniapp_requests import miniapp_idempotency_boundary


@csrf_exempt
@require_POST
@miniapp_idempotency_boundary
def telegram_session_login(request):
    """Create a normal Django session from freshly validated Telegram initData."""
    init_data = request.headers.get('X-Telegram-Init-Data', '') or request.POST.get('init_data', '')
    try:
        user = authenticate(request, init_data=init_data)
    except TelegramAuthenticationError as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=403)
    if user is None or not user.is_active:
        return JsonResponse({'ok': False, 'error': 'Telegram account is not linked to an active user.'}, status=403)
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
