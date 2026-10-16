"""Bounded notifications and authenticated SMS delivery reconciliation."""
import time

from django.core.management.base import BaseCommand
from origination.services.origination_dispatch import eligible_operations, process_operations
from origination.services.origination_sms_delivery import RUNNER_KEY, eligible_lookups, process_due_lookups
from core.services.durable_jobs import begin_runner, finish_runner
from core.services.external_resilience import external_call_budget


class Command(BaseCommand):
    help = 'Inspect Origination work; --apply handles at most five notifications/delivery lookups in 50 seconds.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        ids = list(eligible_operations().order_by('created_at').values_list('pk', flat=True)[:5])
        self.stdout.write(f'{len(ids)} eligible Origination operation(s).')
        self.stdout.write(f'{eligible_lookups().count()} due Advanta delivery lookup(s).')
        if options['apply']:
            begin_runner(RUNNER_KEY)
            started = time.monotonic()
            processed = 0
            try:
                # Receipt reads do not wait for unrelated archival retries.
                processed = process_due_lookups(limit=5, max_seconds=50)
                for operation_id in ids[:5 - processed]:
                    remaining = 50 - (time.monotonic() - started)
                    if remaining <= 0:
                        break
                    with external_call_budget(remaining):
                        process_operations([operation_id])
                    processed += 1
            except Exception:
                finish_runner(RUNNER_KEY, processed_count=processed, error_code='runner_failed')
                raise
            finish_runner(RUNNER_KEY, processed_count=processed)
