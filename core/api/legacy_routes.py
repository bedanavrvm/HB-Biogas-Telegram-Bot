"""Explicit legacy URL adapters with privacy-safe deprecation telemetry."""

from __future__ import annotations

from functools import wraps
import logging

from django.http import HttpResponseNotAllowed, HttpResponsePermanentRedirect
from django.urls import reverse


logger = logging.getLogger('core.legacy_routes')


def _record(request, canonical_path: str) -> None:
    # Deliberately omit the query string, request body, cookies, and headers.
    logger.warning(
        'Deprecated route used method=%s path=%s canonical_path=%s',
        request.method,
        request.path,
        canonical_path,
    )


def direct_legacy_alias(view, *, canonical_path: str):
    """Call a legacy POST/credential route directly until its client retires."""

    @wraps(view)
    def wrapped(request, *args, **kwargs):
        _record(request, canonical_path)
        return view(request, *args, **kwargs)

    return wrapped


def legacy_get_redirect(route_name: str):
    """Redirect a safe legacy browser GET to its named canonical root route."""

    def redirect(request, *args, **kwargs):
        if request.method not in {'GET', 'HEAD'}:
            return HttpResponseNotAllowed(['GET', 'HEAD'])
        target = reverse(route_name, args=args, kwargs=kwargs)
        _record(request, target)
        query = request.META.get('QUERY_STRING', '')
        if query:
            target = f'{target}?{query}'
        return HttpResponsePermanentRedirect(target)

    return redirect
