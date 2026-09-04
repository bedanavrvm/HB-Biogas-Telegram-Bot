"""Stable, privacy-safe messages for Mini App HTTP boundaries.

Operational copy is deployment-controlled and intentionally separate from
legally governed Origination consent text.  The catalogue converts internal
failures into plain-language guidance while logs retain a correlation key and
safe diagnostic context.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import re
import uuid
from typing import Any, Mapping

from django.http import JsonResponse

from core.services.miniapp_requests import validate_request_key


logger = logging.getLogger(__name__)

MESSAGE_CONTRACT_VERSION = "2"
MESSAGE_CONTRACT_HEADER = "X-MiniApp-Message-Contract"


@dataclass(frozen=True)
class MiniAppMessage:
    text: str
    status: int
    tone: str = "error"
    persistence: str = "until_resolved"
    surface_hint: str = "banner"

    def presentation(self) -> dict[str, str]:
        return {
            "tone": self.tone,
            "persistence": self.persistence,
            "surface_hint": self.surface_hint,
        }


MESSAGE_CATALOG: dict[str, MiniAppMessage] = {
    "invalid_request": MiniAppMessage(
        "The app could not read this request. Try the action again. If it continues, contact JBL and share reference {request_id}.", 400,
    ),
    "invalid_idempotency_key": MiniAppMessage(
        "The request retry identifier is invalid. Refresh the Mini App and try again.", 400,
        tone="error",
        persistence="until_resolved",
        surface_hint="banner",
    ),
    "validation_failed": MiniAppMessage(
        "Check the highlighted information and try again.", 400,
    ),
    "authentication_required": MiniAppMessage(
        "Your Telegram session has expired. Close and reopen the Mini App, then try again.", 401,
    ),
    "permission_denied": MiniAppMessage(
        "You do not have access to this action. Contact a JBL administrator if you think this is a mistake.", 403,
    ),
    "item_not_found": MiniAppMessage(
        "This item is no longer available. Return to the list and refresh it.", 404,
    ),
    "conflict_reload": MiniAppMessage(
        "This information was updated elsewhere. Reload the latest version before continuing.", 409,
        tone="warning",
    ),
    "outdated_client": MiniAppMessage(
        "This Mini App is out of date. Close it, reopen it from Telegram, and try again.", 428,
        tone="warning",
    ),
    "retry_later": MiniAppMessage(
        "There have been too many attempts. Please wait a short while and try again.", 429,
        tone="warning", persistence="transient", surface_hint="toast",
    ),
    "service_unavailable": MiniAppMessage(
        "We cannot complete this right now. Your saved work is safe; please try again shortly.", 503,
    ),
    "portal_read_only_maintenance": MiniAppMessage(
        "The Portal is temporarily read-only for maintenance. Your saved work is safe; try again shortly.", 503,
        tone="warning",
    ),
    "unexpected_error": MiniAppMessage(
        "Something went wrong. Please try again. If it continues, contact JBL and share reference {request_id}.", 500,
    ),
    "origination_shared_signer_phone": MiniAppMessage(
        "{roles} use the same phone ending {phone_last4}. Confirm that this is intentional before sending the signing link.", 409,
        tone="warning",
    ),
    "signing_invalid_link": MiniAppMessage(
        "This signing link is incomplete or no longer valid. Ask the JBL officer to send you a new link.", 404,
    ),
    "signing_review_all_pages": MiniAppMessage(
        "Review every page of the loan documents before continuing.", 400,
    ),
    "signing_accept_packet": MiniAppMessage(
        "Tick the agreement box before saving your signature.", 400,
    ),
    "signing_signature_required": MiniAppMessage(
        "Draw your signature or type your full legal name before continuing.", 400,
    ),
    "signing_code_required": MiniAppMessage(
        "Enter the six-digit verification code sent to your phone.", 400,
    ),
    "signing_code_expired": MiniAppMessage(
        "That verification code has expired. Request a new code and try again.", 400,
        tone="warning",
    ),
    "signing_code_incorrect": MiniAppMessage(
        "That code is not correct. You have {attempts_remaining} attempt(s) left.", 400,
    ),
    "signing_code_locked": MiniAppMessage(
        "Signing is temporarily locked after several incorrect codes. Please wait about 30 minutes or contact the JBL officer.", 429,
        tone="warning",
    ),
    "signing_code_wait": MiniAppMessage(
        "Please wait about a minute before requesting another code.", 429,
        tone="warning", persistence="transient", surface_hint="toast",
    ),
    "signing_code_limit": MiniAppMessage(
        "No more verification codes can be sent right now. Please try again later or contact the JBL officer.", 429,
        tone="warning",
    ),
    "signing_packet_changed": MiniAppMessage(
        "The documents or signature changed before verification. Request a new code and try again.", 409,
        tone="warning",
    ),
}

# Codes with deliberate client-side behaviour.  Tests keep this set aligned
# with MiniAppUtils.handledMessageCodes; all other codes use the generic parser.
CLIENT_HANDLED_CODES = frozenset({"origination_shared_signer_phone"})

_SAFE_DETAIL_KEYS = frozenset({
    "actual_revision", "attempts_remaining", "conflict", "expected_revision",
    "field", "fields", "phone_last4", "retry_after", "roles",
})
_SAFE_CODE = re.compile(r"[a-z][a-z0-9_]{2,79}\Z")


class MiniAppUserError(Exception):
    """An expected failure with stable user copy and safe display details."""

    def __init__(
        self, code: str, *, details: Mapping[str, Any] | None = None,
        developer_message: str = "", status: int | None = None,
    ):
        if code not in MESSAGE_CATALOG:
            raise ValueError(f"Unknown Mini App message code: {code}")
        super().__init__(developer_message or code)
        self.code = code
        self.details = _safe_details(details or {})
        self.status = int(status or MESSAGE_CATALOG[code].status)


def _safe_details(details: Mapping[str, Any]) -> dict[str, Any]:
    """Retain only bounded presentation values; never pass arbitrary payloads."""
    result: dict[str, Any] = {}
    for key, value in details.items():
        if key not in _SAFE_DETAIL_KEYS:
            continue
        if isinstance(value, (bool, int)):
            result[key] = value
        elif isinstance(value, str):
            result[key] = value[:160]
        elif isinstance(value, (list, tuple)):
            result[key] = [str(item)[:80] for item in value[:10]]
    return result


def request_reference(request) -> str:
    existing = str(
        getattr(request, "portal_request_id", "")
        or getattr(request, "miniapp_request_id", "")
        or request.headers.get("X-Request-ID", "")
        or ""
    ).strip()
    try:
        return validate_request_key(existing) or uuid.uuid4().hex
    except ValueError:
        return uuid.uuid4().hex


def _default_code(status: int, payload: Mapping[str, Any]) -> str:
    supplied = str(payload.get("code") or "").strip().casefold()
    if supplied in MESSAGE_CATALOG:
        return supplied
    if payload.get("errors"):
        return "validation_failed"
    if payload.get("conflict") or status == 409:
        return "conflict_reload"
    if status in {401}:
        return "authentication_required"
    if status == 403:
        return "permission_denied"
    if status == 404:
        return "item_not_found"
    if status == 428:
        return "outdated_client"
    if status == 429:
        return "retry_later"
    if status >= 500:
        return "service_unavailable" if status in {502, 503, 504} else "unexpected_error"
    return "invalid_request"


def render_message(code: str, *, details: Mapping[str, Any] | None = None, request_id: str = "") -> str:
    message = MESSAGE_CATALOG[code].text
    values = {**_safe_details(details or {}), "request_id": request_id}
    try:
        return message.format_map(_SafeFormat(values))
    except (KeyError, ValueError):
        logger.error("Mini App message formatting failed: code=%s", code)
        return MESSAGE_CATALOG["unexpected_error"].text.format(request_id=request_id)


def message_presentation(code: str, *, status: int = 400) -> dict[str, str]:
    """Return additive UI guidance without coupling clients to message text."""
    item = MESSAGE_CATALOG.get(code)
    if item:
        return item.presentation()
    return {
        "tone": "error" if status >= 400 else "info",
        "persistence": "until_resolved" if status >= 400 else "transient",
        "surface_hint": "banner" if status >= 400 else "toast",
    }


class _SafeFormat(dict):
    def __missing__(self, key):
        return ""


def _uses_current_contract(request) -> bool:
    return str(request.headers.get(MESSAGE_CONTRACT_HEADER) or "").strip() == MESSAGE_CONTRACT_VERSION


def miniapp_error_response(
    request, code: str, *, workflow: str, status: int | None = None,
    details: Mapping[str, Any] | None = None, errors: Any = None,
    developer_message: str = "", exception: Exception | None = None,
    user_message: str = "", extra: Mapping[str, Any] | None = None,
) -> JsonResponse:
    known_code = code in MESSAGE_CATALOG
    user_message = str(user_message or "").strip()[:1000]
    if not known_code and not (_SAFE_CODE.fullmatch(code) and user_message):
        developer_message = developer_message or f"Unknown client error code {code!r}"
        code = "unexpected_error"
        known_code = True
    safe_details = _safe_details(details or {})
    request_id = request_reference(request)
    final_status = int(status or (MESSAGE_CATALOG[code].status if known_code else 400))
    message = user_message or render_message(code, details=safe_details, request_id=request_id)
    # Existing workflow payloads such as a winning revision snapshot remain
    # part of their endpoint contract. They were already deliberately exposed
    # by that view; this boundary owns only the message fields.
    payload: dict[str, Any] = dict(extra or {})
    payload.update({
        "ok": False,
        "success": False,
        "code": code,
        "message": message,
        "request_id": request_id,
        "presentation": message_presentation(code, status=final_status),
    })
    legacy = not _uses_current_contract(request)
    if legacy:
        payload["error"] = message
    if errors:
        payload["errors"] = errors
    if safe_details:
        payload["details"] = safe_details
    response = JsonResponse(payload, status=final_status)
    response["X-Request-ID"] = request_id
    response[MESSAGE_CONTRACT_HEADER] = MESSAGE_CONTRACT_VERSION
    log = (
        logger.error if final_status >= 500
        else logger.warning if final_status in {409, 428, 429}
        else logger.info
    )
    log(
        "Mini App request failed: workflow=%s code=%s request_id=%s status=%s "
        "path=%s legacy_error_mirror=%s exception=%s developer_message=%s",
        workflow, code, request_id, final_status, request.path, legacy,
        type(exception).__name__ if exception else "", developer_message[:300],
    )
    if final_status >= 500 and exception is not None:
        try:
            import sentry_sdk
            sentry_sdk.capture_exception(exception)
        except ImportError:
            pass
    return response


def unexpected_miniapp_error(request, error: Exception, *, workflow: str) -> JsonResponse:
    """Capture a genuine fault while keeping its details out of the response."""
    return miniapp_error_response(
        request, "unexpected_error", workflow=workflow, status=500,
        developer_message=type(error).__name__, exception=error,
    )


def normalize_miniapp_response(request, response, *, workflow: str):
    """Apply the v2 message contract to JSON failures without changing success data."""
    if response.get(MESSAGE_CONTRACT_HEADER) == MESSAGE_CONTRACT_VERSION:
        return response
    request_id = request_reference(request)
    response["X-Request-ID"] = response.get("X-Request-ID", request_id)
    response[MESSAGE_CONTRACT_HEADER] = MESSAGE_CONTRACT_VERSION
    if not isinstance(response, JsonResponse):
        return response
    try:
        payload = json.loads(response.content.decode(response.charset or "utf-8"))
    except (TypeError, ValueError, UnicodeDecodeError):
        return response
    if not isinstance(payload, dict):
        return response
    failed = response.status_code >= 400 or payload.get("ok") is False or payload.get("success") is False
    if not failed:
        payload.setdefault("request_id", request_id)
        response.content = json.dumps(payload, ensure_ascii=False).encode(response.charset or "utf-8")
        return response
    supplied_code = str(payload.get("code") or "").strip().casefold()
    code = supplied_code if _SAFE_CODE.fullmatch(supplied_code) else _default_code(response.status_code, payload)
    details = {
        key: payload.get(key)
        for key in _SAFE_DETAIL_KEYS
        if key in payload
    }
    if isinstance(payload.get("details"), Mapping):
        details.update(_safe_details(payload["details"]))
    # An explicit `message` is the workflow's reviewed 4xx copy. A stable
    # pre-contract domain code may also mark its legacy `error` as expected
    # business guidance. Uncoded raw exception strings remain private.
    user_message = ""
    if response.status_code < 500:
        user_message = str(payload.get("message") or "").strip()
        if not user_message and supplied_code:
            user_message = str(payload.get("error") or "").strip()
    normalized = miniapp_error_response(
        request, code, workflow=workflow, status=response.status_code,
        details=details, errors=payload.get("errors"),
        # The legacy value may contain a customer-entered value. Record only
        # its stable code/status at this boundary, never the raw browser copy.
        developer_message=f"legacy_code={str(payload.get('code') or '')[:80]}",
        user_message=user_message,
        extra={
            key: value for key, value in payload.items()
            if key not in {
                'ok', 'success', 'code', 'message', 'error', 'request_id',
                'details', 'errors', 'traceback', 'exception', 'debug', 'sql',
                'presentation',
            }
        },
    )
    for key, value in response.items():
        if key not in {"Content-Type", "Content-Length", "X-Request-ID", MESSAGE_CONTRACT_HEADER}:
            normalized[key] = value
    return normalized
