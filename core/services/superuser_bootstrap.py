"""Controlled, idempotent deployment Superuser bootstrap."""

from __future__ import annotations

from dataclasses import dataclass
import os

from django.contrib.auth import get_user_model
from django.db import transaction


class SuperuserBootstrapError(RuntimeError):
    pass


@dataclass(frozen=True)
class SuperuserBootstrapResult:
    outcome: str
    username: str = ''


@transaction.atomic
def bootstrap_superuser_from_environment() -> SuperuserBootstrapResult:
    username = str(os.getenv('DJANGO_SUPERUSER_USERNAME') or '').strip()
    email = str(os.getenv('DJANGO_SUPERUSER_EMAIL') or '').strip()
    password = str(os.getenv('DJANGO_SUPERUSER_PASSWORD') or '')
    if not all((username, email, password)):
        return SuperuserBootstrapResult('skipped')

    User = get_user_model()
    existing = User.objects.select_for_update().filter(username=username).first()
    if existing:
        if not existing.is_superuser:
            raise SuperuserBootstrapError(
                'The configured bootstrap username already belongs to a non-Superuser account.'
            )
        return SuperuserBootstrapResult('existing', username=username)

    User.objects.create_superuser(username=username, email=email, password=password)
    return SuperuserBootstrapResult('created', username=username)
