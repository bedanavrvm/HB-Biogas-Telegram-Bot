"""Optional manual diagnostic drainer for durable Portal Google Sheet work.

The normal executor is an open Portal session. No Google call is made by this
command without --apply; no cron job is required or configured.
"""

from __future__ import annotations

import time
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.models import IntegrationOperation, JawabuFarmerMaster
from core.services.external_resilience import ExternalCircuitOpen
from core.services.durable_jobs import begin_runner, finish_runner
from core.services.portal_publication import (
    PORTAL_PUBLICATION_RUNNER,
    attempt_publication,
    queued_publication_operations,
)


def due_portal_operations():
    return queued_publication_operations()


class Command(BaseCommand):
    help = 'Inspect or drain due Portal Sheet publications, with bounded Google calls.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Make Google calls; without this, inspect only.')
        parser.add_argument('--limit', type=int, default=10, help='Maximum attempts this run (1-25).')
        parser.add_argument('--max-seconds', type=int, default=50, help='Maximum run time (1-240 seconds).')

    def handle(self, *args, **options):
        limit = options['limit']
        max_seconds = options['max_seconds']
        if not 1 <= limit <= 25 or not 1 <= max_seconds <= 240:
            raise CommandError('--limit must be 1-25 and --max-seconds must be 1-240.')
        if not options['apply']:
            self.stdout.write(f'DRY RUN: {due_portal_operations().count()} due Portal Sheet operation(s); no Google calls made.')
            return

        begin_runner(PORTAL_PUBLICATION_RUNNER)
        try:
            self._drain(limit=limit, max_seconds=max_seconds)
        except Exception:
            finish_runner(PORTAL_PUBLICATION_RUNNER, error_code='runner_failed')
            raise

    def _drain(self, *, limit, max_seconds):
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
                    # Another run may own this row. Leave it to the next tick.
                    break
            else:
                # Another worker owns the short lease. Do not spin on it.
                break
        finish_runner(PORTAL_PUBLICATION_RUNNER, processed_count=attempted)
        self.stdout.write(
            f'APPLY: {attempted} Google attempt(s), {succeeded} synchronized, '
            f'{deferred} paced, {missing} missing source(s); '
            f'{due_portal_operations().count()} due operation(s) remain.'
        )
