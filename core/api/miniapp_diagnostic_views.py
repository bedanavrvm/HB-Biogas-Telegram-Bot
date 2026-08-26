"""Authenticated, idempotent ingestion for privacy-safe Mini App diagnostics."""

from __future__ import annotations

import json

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.models import MiniAppDiagnosticSession
from core.services.miniapp_diagnostics import (
    DiagnosticPayloadError,
    actor_id_from_signal_token,
    issue_signal_token,
    record_signals,
    start_session,
    workflow_for_surface,
)


def _json_payload(request) -> dict:
    max_bytes = int(getattr(settings, 'MINIAPP_DIAGNOSTICS_MAX_PAYLOAD_BYTES', 8192))
    if len(request.body) > max_bytes:
        raise DiagnosticPayloadError('The diagnostic payload is too large.')
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DiagnosticPayloadError('The diagnostic payload must be valid JSON.') from exc
    if not isinstance(payload, dict):
        raise DiagnosticPayloadError('The diagnostic payload must be an object.')
    return payload


def _init_data(request, payload: dict) -> str:
    return str(
        request.headers.get('X-Telegram-Init-Data')
        or payload.get('init_data')
        or ''
    )


def _authorized_actor(request, payload: dict, workflow: str):
    from core.services.telegram_identity import (
        TelegramAuthenticationError,
        resolve_or_bind_telegram_user,
        user_access,
        validate_telegram_init_data,
    )
    try:
        _raw, identity = validate_telegram_init_data(
            _init_data(request, payload),
            max_age_seconds=int(getattr(settings, 'TELEGRAM_AUTH_MAX_AGE_SECONDS', 86400)),
        )
    except TelegramAuthenticationError:
        return None
    actor = resolve_or_bind_telegram_user(identity)
    access = user_access(actor, workflow) if actor else None
    return actor if access and access.get('authorized') else None


def _error(message: str, *, status: int, code: str) -> JsonResponse:
    return JsonResponse({'ok': False, 'error': message, 'code': code}, status=status)


@csrf_exempt
@require_POST
def miniapp_diagnostic_session_start(request):
    if not getattr(settings, 'MINIAPP_DIAGNOSTICS_ENABLED', True):
        return JsonResponse({'ok': True, 'disabled': True})
    try:
        payload = _json_payload(request)
        workflow = workflow_for_surface(payload.get('surface'))
    except DiagnosticPayloadError as exc:
        return _error(str(exc), status=400, code='invalid_diagnostic_payload')
    actor = _authorized_actor(request, payload, workflow)
    if actor is None:
        return _error(
            'This Telegram account is not authorized for this Mini App.',
            status=403, code='diagnostic_access_denied',
        )
    try:
        session, created = start_session(actor=actor, payload=payload)
    except DiagnosticPayloadError as exc:
        return _error(str(exc), status=409, code='diagnostic_session_conflict')
    return JsonResponse({
        'ok': True,
        'created': created,
        'session_uuid': str(session.client_session_uuid),
        'signal_token': issue_signal_token(session),
        'classification': session.classification,
    })


@csrf_exempt
@require_POST
def miniapp_diagnostic_signals(request, session_uuid):
    if not getattr(settings, 'MINIAPP_DIAGNOSTICS_ENABLED', True):
        return JsonResponse({'ok': True, 'disabled': True, 'acknowledged': []})
    try:
        payload = _json_payload(request)
        session = MiniAppDiagnosticSession.objects.select_related('actor').get(
            client_session_uuid=session_uuid,
        )
    except DiagnosticPayloadError as exc:
        return _error(str(exc), status=400, code='invalid_diagnostic_payload')
    except MiniAppDiagnosticSession.DoesNotExist:
        return _error('The diagnostic session was not found.', status=404, code='diagnostic_session_not_found')

    actor_id = actor_id_from_signal_token(payload.get('signal_token'), session.client_session_uuid)
    if actor_id != session.actor_id:
        actor = _authorized_actor(request, payload, session.workflow)
        if actor is None or actor.pk != session.actor_id:
            return _error('The diagnostic signal is not authorized.', status=403, code='diagnostic_access_denied')
    try:
        acknowledged = record_signals(session=session, payload=payload)
    except DiagnosticPayloadError as exc:
        return _error(str(exc), status=400, code='invalid_diagnostic_payload')
    return JsonResponse({
        'ok': True,
        'session_uuid': str(session.client_session_uuid),
        'acknowledged': acknowledged,
    })
