"""Internal mutation authority; callers use the audited lifecycle service."""
from contextlib import contextmanager
from contextvars import ContextVar

from django.core.exceptions import PermissionDenied


_mutation = ContextVar('staff_browser_admission_mutation', default=False)


def require_mutation():
    if not _mutation.get():
        raise PermissionDenied('Use the audited staff browser lifecycle service.')


@contextmanager
def admission_mutation():
    token = _mutation.set(True)
    try:
        yield
    finally:
        _mutation.reset(token)
