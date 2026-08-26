"""Privacy-safe Sentry configuration for the operational Django platform.

Sentry receives operational exception evidence, never customer or staff
payloads. The SDK's ``before_send`` hooks are the last in-process boundary
before an event leaves JBL infrastructure, so this module intentionally keeps
only a query-free request path and method alongside the exception itself.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit, urlunsplit
import re


_REQUEST_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}\Z')


def _safe_url(value: object) -> str:
    """Reduce a URL to an identifier-free Mini App surface path."""
    text = str(value or '').strip()
    if not text:
        return ''
    parsed = urlsplit(text)
    surface = _miniapp_surface(text)
    safe_path = {
        'complaint_cases': '/api/complaints/',
        'tat_tracker': '/api/tat-tracker/',
        'spin': '/api/spin/',
        'loan_origination': '/api/origination/',
        'order_approval': '/api/order-approval/',
        'fca_review': '/api/fca/',
        'jawabu_farmers': '/api/jawabu-farmers/',
        'portal': '/api/portal/',
        'diagnostics': '/api/miniapp-diagnostics/',
    }.get(surface, '/')
    return urlunsplit((parsed.scheme, parsed.netloc, safe_path, '', ''))


def _safe_request_id(request: object) -> str:
    if not isinstance(request, dict):
        return ''
    headers = request.get('headers')
    if isinstance(headers, dict):
        value = next((item for key, item in headers.items() if str(key).lower() == 'x-request-id'), '')
    elif isinstance(headers, (list, tuple)):
        value = next((item[1] for item in headers if len(item) == 2 and str(item[0]).lower() == 'x-request-id'), '')
    else:
        value = ''
    text = str(value or '').strip()
    return text if _REQUEST_ID.fullmatch(text) else ''


def _miniapp_surface(url: object) -> str:
    path = urlsplit(str(url or '')).path.lower()
    for marker, surface in (
        ('/complaints', 'complaint_cases'), ('/tat-tracker', 'tat_tracker'),
        ('/spin', 'spin'), ('/origination', 'loan_origination'),
        ('/order-approval', 'order_approval'), ('/fca', 'fca_review'),
        ('/jawabu-farmers', 'jawabu_farmers'), ('/portal', 'portal'),
        ('/miniapp-diagnostics', 'diagnostics'),
    ):
        if marker in path:
            return surface
    return 'other'


def scrub_event(event: dict[str, Any], hint: dict[str, Any] | None = None) -> dict[str, Any]:
    """Remove customer and staff data from an event before Sentry delivery."""
    cleaned = dict(event or {})
    request = cleaned.get('request')
    request_id = _safe_request_id(request)
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
    if request_id:
        cleaned['tags'] = {'request_id': request_id}
    return cleaned


def scrub_transaction(event: dict[str, Any], hint: dict[str, Any] | None = None) -> dict[str, Any]:
    """Keep timing structure while removing URLs, identifiers, and span payloads."""
    cleaned = dict(event or {})
    request = cleaned.get('request')
    request_id = _safe_request_id(request)
    surface = _miniapp_surface(request.get('url') if isinstance(request, dict) else '')
    if isinstance(request, dict):
        cleaned['request'] = {
            key: value for key, value in {
                'method': str(request.get('method') or '').upper(),
                'url': _safe_url(request.get('url')),
            }.items() if value
        }
    else:
        cleaned.pop('request', None)
    for key in ('breadcrumbs', 'extra', 'fingerprint', 'logentry', 'message', 'threads', 'user'):
        cleaned.pop(key, None)
    cleaned['transaction'] = f'miniapp.{surface}'
    cleaned['tags'] = {
        **({'request_id': request_id} if request_id else {}),
        'miniapp_surface': surface,
    }
    spans = []
    for span in cleaned.get('spans') or []:
        if not isinstance(span, dict):
            continue
        spans.append({
            key: value for key, value in span.items()
            if key in {'span_id', 'trace_id', 'parent_span_id', 'start_timestamp', 'timestamp', 'op', 'status'}
        })
    cleaned['spans'] = spans
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
        'before_send_transaction': scrub_transaction,
    }
