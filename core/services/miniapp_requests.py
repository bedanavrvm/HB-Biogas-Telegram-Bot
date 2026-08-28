"""Shared request identity policy for Telegram Mini App writes.

Telegram can redeliver a request and mobile WebViews can retry a submit after
the server has already committed it.  Individual workflows retain their own
domain-level duplicate constraints; this module gives every Mini App the same
safe transport-level request key and a gradual migration path for older
cached clients.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from django.conf import settings
from django.http import JsonResponse


_KEY_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}\Z")
_BODY_KEYS = ("client_request_id", "request_id", "create_request_id")


class IdempotencyKeyRequired(ValueError):
    """Raised only after the documented cached-client compatibility period."""


@dataclass(frozen=True)
class MiniAppRequestIdentity:
    key: str
    source: str

    @property
    def legacy_client(self) -> bool:
        return not self.key


def validate_request_key(value: Any) -> str:
    """Return a bounded transport key or an empty value for a legacy client."""
    key = str(value or "").strip()
    if not key:
        return ""
    if not _KEY_PATTERN.fullmatch(key):
        raise ValueError("The request retry identifier is invalid. Refresh the Mini App and try again.")
    return key


def resolve_miniapp_request_identity(request, payload: dict[str, Any] | None = None) -> MiniAppRequestIdentity:
    """Resolve one key with an explicit precedence and no silent random fallback."""
    payload = payload or {}
    candidates = (
        ("idempotency_key", request.headers.get("Idempotency-Key", "")),
        ("request_header", request.headers.get("X-Request-ID", "")),
        *((key, payload.get(key, "")) for key in _BODY_KEYS),
    )
    for source, value in candidates:
        key = validate_request_key(value)
        if key:
            return MiniAppRequestIdentity(key=key, source=source)
    if getattr(settings, "REQUIRE_MINIAPP_IDEMPOTENCY_KEY", False):
        raise IdempotencyKeyRequired(
            "This Mini App version is out of date. Refresh Telegram, then submit again."
        )
    return MiniAppRequestIdentity(key="", source="legacy")


def bind_miniapp_request_identity(request, payload: dict[str, Any] | None = None) -> MiniAppRequestIdentity:
    """Make the resolved key available to the view and legacy service payloads."""
    identity = resolve_miniapp_request_identity(request, payload)
    request.miniapp_request_identity = identity
    request.miniapp_request_id = identity.key
    if identity.key and payload is not None:
        payload.setdefault("client_request_id", identity.key)
        payload.setdefault("request_id", identity.key)
    return identity


def idempotency_error_response(error: Exception, request=None) -> JsonResponse:
    status = 428 if isinstance(error, IdempotencyKeyRequired) else 400
    # Imported lazily because the message boundary also uses request-key
    # validation when it assigns a support reference.
    from core.services.miniapp_messages import miniapp_error_response
    return miniapp_error_response(
        request or _RequestProxy(),
        "outdated_client" if status == 428 else "invalid_request",
        workflow="miniapp_request",
        status=status,
        developer_message=str(error),
    )


class _RequestProxy:
    """Compatibility request for callers that have not passed the request yet."""

    headers: dict = {}
    path = "miniapp-request"


def attach_miniapp_request_metadata(request, response):
    """Expose a non-breaking upgrade signal without changing response shapes."""
    identity = getattr(request, "miniapp_request_identity", None)
    if identity is None:
        return response
    if identity.key:
        response["X-Request-ID"] = identity.key
        response["X-Idempotency-Status"] = "keyed"
    elif request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        response["X-Idempotency-Status"] = "legacy-client"
        response["Warning"] = '299 - "Mini App retry key missing; refresh before enforcement is enabled"'
    return response
