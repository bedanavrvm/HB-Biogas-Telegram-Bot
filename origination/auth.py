"""Independent Telegram identity and staff-access boundary for Origination."""
import json
import logging
from functools import wraps

from django.conf import settings
from django.contrib.auth import login
from django.http import JsonResponse

logger = logging.getLogger(__name__)


def origination_auth_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        from core.services.telegram_auth import validate_telegram_init_data
        from core.services.telegram_identity import TelegramIdentity, resolve_or_bind_telegram_user, user_access
        from core.services.miniapp_requests import (
            attach_miniapp_request_metadata, bind_miniapp_request_identity, idempotency_error_response,
        )
        from core.services.miniapp_messages import unexpected_miniapp_error

        require_auth = getattr(settings, 'ORIGINATION_WEBAPP_REQUIRE_TELEGRAM_AUTH', True)
        valid, error, payload = validate_telegram_init_data(
            request.headers.get('X-Telegram-Init-Data', '') or request.POST.get('init_data', ''),
            require_auth=require_auth,
            max_age_seconds=getattr(settings, 'ORIGINATION_WEBAPP_AUTH_MAX_AGE_SECONDS', 86400),
        )
        if not valid:
            return JsonResponse({'ok': False, 'error': error, 'code': 'authentication_required'}, status=403)
        request.origination_auth_payload = payload
        if require_auth:
            try:
                identity = json.loads(payload.get('user') or '{}')
            except (TypeError, ValueError):
                identity = {}
            if not isinstance(identity, dict):
                identity = {}
            actor = resolve_or_bind_telegram_user(TelegramIdentity(
                telegram_id=str(identity.get('id') or ''),
                username=str(identity.get('username') or '').strip().lstrip('@'),
                first_name=str(identity.get('first_name') or '').strip(),
                last_name=str(identity.get('last_name') or '').strip(), payload=identity,
            ))
        else:
            # Shared validator permits this only in explicit local/test mode.
            actor = getattr(request, 'user', None)
        access = user_access(actor, 'loan_origination') if actor and actor.is_authenticated else None
        if not access or not access.get('authorized'):
            return JsonResponse({'ok': False, 'error': 'Your account is not authorized for Loan Origination.'}, status=403)
        request.origination_user = actor
        request.origination_access = access
        if require_auth:
            login(request, actor, backend='core.auth_backends.TelegramMiniAppBackend')
        if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}:
            try:
                if 'application/json' in str(request.content_type or ''):
                    try:
                        body = json.loads(request.body or b'{}')
                    except (ValueError, UnicodeDecodeError):
                        body = {}
                else:
                    body = request.POST.dict()
                bind_miniapp_request_identity(request, body if isinstance(body, dict) else {})
            except ValueError as exc:
                return idempotency_error_response(exc, request)
        try:
            response = view(request, *args, **kwargs)
        except Exception as exc:
            logger.exception('Origination request failed: method=%s path=%s', request.method, request.path)
            response = unexpected_miniapp_error(request, exc, workflow='loan_origination')
        return attach_miniapp_request_metadata(request, response)
    return wrapper
