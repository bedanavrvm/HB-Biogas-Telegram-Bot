"""Runtime guard for permanent AccessGrant mutations.

Normal application code must enter this context through an approved access
service.  Tests default to the legacy fixture-friendly mode and explicitly
enable the setting when verifying the production guard.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

from django.conf import settings
from django.core.exceptions import PermissionDenied


_mutation_reason = ContextVar('access_grant_mutation_reason', default='')


@contextmanager
def governed_access_grant_mutation(reason: str):
    value = str(reason or '').strip()
    if not value:
        raise ValueError('A governed AccessGrant mutation reason is required.')
    token = _mutation_reason.set(value)
    try:
        yield
    finally:
        _mutation_reason.reset(token)


def require_access_grant_mutation() -> None:
    if not getattr(settings, 'ACCESS_GRANT_GOVERNANCE_ENFORCED', True):
        return
    if not _mutation_reason.get():
        raise PermissionDenied(
            'Permanent Access Grants may only be changed through the governed '
            'staff lifecycle or access-control services.'
        )


def current_mutation_reason() -> str:
    return _mutation_reason.get()
