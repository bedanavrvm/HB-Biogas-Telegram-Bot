"""Privacy-safe aggregate diagnostics for the Mini App idempotency cutover."""

from __future__ import annotations

from datetime import timedelta
import re

from django.db import IntegrityError, transaction
from django.db.models import F, Sum
from django.utils import timezone


_ROUTE_NAME = re.compile(r'[A-Za-z0-9_.:-]{1,100}\Z')
_METHODS = frozenset({'POST', 'PUT', 'PATCH', 'DELETE'})
_OUTCOMES = frozenset({'accepted', 'rejected'})


def record_legacy_write(*, route_name: str, method: str, outcome: str) -> None:
    """Increment one anonymous route/day bucket; never retain actor or payload."""
    from core.models import MiniAppLegacyWriteDailyAggregate

    safe_route = str(route_name or '').strip()
    safe_method = str(method or '').strip().upper()
    safe_outcome = str(outcome or '').strip().lower()
    if not _ROUTE_NAME.fullmatch(safe_route):
        safe_route = 'unresolved'
    if safe_method not in _METHODS:
        return
    if safe_outcome not in _OUTCOMES:
        return
    lookup = {
        'date': timezone.localdate(),
        'route_name': safe_route,
        'method': safe_method,
        'outcome': safe_outcome,
    }
    try:
        with transaction.atomic():
            row, created = MiniAppLegacyWriteDailyAggregate.objects.get_or_create(
                **lookup, defaults={'request_count': 1},
            )
    except IntegrityError:
        created = False
        row = MiniAppLegacyWriteDailyAggregate.objects.get(**lookup)
    if not created:
        MiniAppLegacyWriteDailyAggregate.objects.filter(pk=row.pk).update(
            request_count=F('request_count') + 1,
        )


def recent_legacy_write_summary(*, observation_days: int) -> dict:
    """Return aggregate-only readiness evidence for the observation window."""
    from core.models import MiniAppLegacyWriteDailyAggregate

    days = max(1, min(int(observation_days), 90))
    cutoff = timezone.localdate() - timedelta(days=days - 1)
    rows = MiniAppLegacyWriteDailyAggregate.objects.filter(date__gte=cutoff)
    totals = {
        item['outcome']: int(item['total'] or 0)
        for item in rows.values('outcome').annotate(total=Sum('request_count'))
    }
    return {
        'observation_days': days,
        'accepted': totals.get('accepted', 0),
        'rejected': totals.get('rejected', 0),
        'route_count': rows.values('route_name').distinct().count(),
    }
