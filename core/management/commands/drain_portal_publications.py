"""Bounded, dry-run-first drainer for durable Portal Google Sheet work.

Run on a scheduler to ensure publications progress when no staff Mini App is
open.  The browser-assisted path and this command share the same DB operation
claims, circuit breaker and pacing.  No Google call is made without --apply.
"""

from __future__ import annotations

import time
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from core.models import IntegrationOperation, JawabuFarmerMaster
from core.services.external_resilience import ExternalCircuitOpen
from core.services.portal_publication import (
    INTERNAL_ORDER_OPERATION,
    MASTER_OPERATION,
    SOURCE_MODEL,
    attempt_publication,
)


def due_portal_operations():
    now = timezone.now()
    lease_seconds = max(30, int(getattr(settings, 'API_REQUEST_TIMEOUT', 10) or 10) * 3)
    stale_running = Q(status=IntegrationOperation.STATUS_RUNNING,
                      last_attempt_at__lte=now - timedelta(seconds=lease_seconds))
    open_master_id = IntegrationOperation.objects.filter(
        integration=IntegrationOperation.INTEGRATION_GOOGLE_SHEETS,
        source_model=SOURCE_MODEL,
        operation_type=MASTER_OPERATION,
        status__in=(IntegrationOperation.STATUS_PENDING, IntegrationOperation.STATUS_RETRYABLE,
                    IntegrationOperation.STATUS_RUNNING),
    ).order_by('created_at', 'pk').values_list('pk', flat=True).first()
    queryset = IntegrationOperation.objects.filter(
        integration=IntegrationOperation.INTEGRATION_GOOGLE_SHEETS,
        source_model=SOURCE_MODEL,
        operation_type__in=(MASTER_OPERATION, INTERNAL_ORDER_OPERATION),
    ).filter(
        Q(status__in=(IntegrationOperation.STATUS_PENDING, IntegrationOperation.STATUS_RETRYABLE))
        & (Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=now))
        | stale_running
    ).order_by('created_at', 'pk')
    return queryset.filter(Q(operation_type=INTERNAL_ORDER_OPERATION) | Q(pk=open_master_id))


class Command(BaseCommand):
    help = 'Inspect or drain due Portal Sheet publications, with bounded Google calls.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Make Google calls; without this, inspect only.')
        parser.add_argument('--limit', type=int, default=5, help='Maximum attempts this run (1-25).')
        parser.add_argument('--max-seconds', type=int, default=50, help='Maximum run time (1-240 seconds).')

    def handle(self, *args, **options):
        limit = options['limit']
        max_seconds = options['max_seconds']
        if not 1 <= limit <= 25 or not 1 <= max_seconds <= 240:
            raise CommandError('--limit must be 1-25 and --max-seconds must be 1-240.')
        if not options['apply']:
            self.stdout.write(f'DRY RUN: {due_portal_operations().count()} due Portal Sheet operation(s); no Google calls made.')
            return

        deadline = time.monotonic() + max_seconds
        attempted = succeeded = deferred = missing = 0
        while attempted < limit and time.monotonic() < deadline:
            operation = due_portal_operations().first()
            if operation is None:
                break
            if not JawabuFarmerMaster.objects.filter(pk=operation.source_id).exists():
                # A reset may remove the canonical case. Do not let its stale
                # operation starve every subsequent scheduled run.
                operation.status = IntegrationOperation.STATUS_DEAD_LETTER
                operation.last_error_code = 'source_missing'
                operation.last_error = 'Canonical Portal case is no longer available.'
                operation.next_retry_at = None
                operation.save(update_fields=['status', 'last_error_code', 'last_error', 'next_retry_at', 'updated_at'])
                missing += 1
                continue
            before = operation.attempts
            try:
                result = attempt_publication(operation)
            except ExternalCircuitOpen:
                break
            operation.refresh_from_db()
            if operation.attempts > before:
                attempted += 1
                succeeded += int(operation.status == IntegrationOperation.STATUS_SUCCEEDED)
            elif result.get('error'):
                # Usually an open circuit: no Google request happened. Leave
                # the durable work intact for the next scheduled run.
                break
            elif result.get('deferred') or operation.next_retry_at:
                deferred += 1
                if operation.next_retry_at:
                    wait = min((operation.next_retry_at - timezone.now()).total_seconds(), deadline - time.monotonic())
                    if wait > 0:
                        time.sleep(wait)
            else:
                # Another worker owns the short lease. Do not spin on it.
                break
        self.stdout.write(
            f'APPLY: {attempted} Google attempt(s), {succeeded} synchronized, '
            f'{deferred} paced, {missing} missing source(s); '
            f'{due_portal_operations().count()} due operation(s) remain.'
        )
