"""Privacy-safe Sentry configuration for the operational Django platform.

Sentry receives operational exception evidence, never customer or staff
payloads. The SDK's ``before_send`` hooks are the last in-process boundary
before an event leaves JBL infrastructure, so this module intentionally keeps
only a query-free request path and method alongside the exception itself.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit, urlunsplit


def _safe_url(value: object) -> str:
    """Remove a query string and fragment before it can leave the service."""
    text = str(value or '').strip()
    if not text:
        return ''
    parsed = urlsplit(text)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, '', ''))


def scrub_event(event: dict[str, Any], hint: dict[str, Any] | None = None) -> dict[str, Any]:
    """Remove customer and staff data from an event before Sentry delivery."""
    cleaned = dict(event or {})
    request = cleaned.get('request')
    if isinstance(request, dict):
        safe_request = {
            'method': str(request.get('method') or '').upper(),
            'url': _safe_url(request.get('url')),
        }
        cleaned['request'] = {key: value for key, value in safe_request.items() if value}
    else:
        cleaned.pop('request', None)

    # Do not allow arbitrary context to contain customer identifiers, Telegram
    # initData, credentials, document text, or financial information. Exception
    # type and stack frames remain available for grouping/debugging, while the
    # exception message is removed because application errors often interpolate
    # identifiers or customer-supplied values.
    for key in (
        'breadcrumbs', 'extra', 'fingerprint', 'logentry', 'message', 'spans',
        'tags', 'threads', 'transaction', 'user',
    ):
        cleaned.pop(key, None)
    exception = cleaned.get('exception')
    if isinstance(exception, dict) and isinstance(exception.get('values'), list):
        values = []
        for value in exception['values']:
            if not isinstance(value, dict):
                continue
            values.append({key: item for key, item in value.items() if key != 'value'})
        cleaned['exception'] = {**exception, 'values': values}
    return cleaned


def sentry_init_options(settings) -> dict[str, Any]:
    """Return the stable, privacy-safe Sentry SDK options for this service."""
    return {
        'dsn': settings.SENTRY_DSN,
        'environment': settings.SENTRY_ENVIRONMENT,
        'release': settings.APP_RELEASE or None,
        'traces_sample_rate': settings.SENTRY_TRACES_SAMPLE_RATE,
        'send_default_pii': False,
        'before_send': scrub_event,
        'before_send_transaction': scrub_event,
    }
