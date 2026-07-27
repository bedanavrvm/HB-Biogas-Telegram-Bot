"""Central operational branch and county configuration.

The database list is the editable source for staff-facing choices.  Static
values remain a safe bootstrap fallback for commands and deployments that run
before the location migration has been applied.
"""
from __future__ import annotations

import logging
from typing import Any

from django.apps import apps
from django.db import DatabaseError


logger = logging.getLogger(__name__)


def normalize_location_name(value: Any) -> str:
    return ' '.join(str(value or '').split())


def configured_location_names(location_type: str) -> list[str]:
    """Return active names from the central table, or an empty list if unset."""
    if not apps.ready:
        return []
    try:
        from core.models import OperationalLocation

        return [
            name for name in OperationalLocation.objects.filter(
                location_type=location_type, active=True,
            ).order_by('sort_order', 'name').values_list('name', flat=True)
        ]
    except DatabaseError as exc:
        # During an initial deployment the table may not exist yet.  Callers
        # deliberately fall back to their existing environment/static values.
        #
        # ``DatabaseError`` also covers a PostgreSQL connection that is
        # already marked as failed (for example after an invalid AccessGrant
        # inline submission).  Choice fields are constructed while Django
        # renders the admin form, so allowing this lookup to bubble up turns a
        # recoverable validation error into a blank 500 page.  The request
        # transaction is still rolled back by Django; this helper only keeps
        # rendering usable with the configured/static fallback values.
        logger.warning(
            'Operational location lookup failed; using configured fallback values (%s).',
            exc,
        )
        return []


def global_county_choices() -> list[str]:
    configured = configured_location_names('county')
    if configured:
        return configured
    # Keep the parser's established canonical list as a migration-safe fallback.
    from core.services.parser import KENYA_COUNTIES
    return list(KENYA_COUNTIES)


def county_choices(include_all: bool = False) -> list[tuple[str, str]]:
    values = global_county_choices()
    choices = [(value, value) for value in values]
    return [('', 'All counties'), *choices] if include_all else choices
