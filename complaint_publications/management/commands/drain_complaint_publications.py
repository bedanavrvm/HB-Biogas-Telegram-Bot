import time

from django.core.management.base import BaseCommand, CommandError

from core.services.durable_jobs import begin_runner, finish_runner
from complaint_publications.services import RUNNER, cleanup, queued_operations
from complaint_publications.worker import publish


class Command(BaseCommand):
    help = 'Inspect or drain browser-only Complaint publications. Schedule --apply every minute.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--limit', type=int, default=10)
        parser.add_argument('--max-seconds', type=int, default=50)

    def handle(self, *args, **options):
        if not 1 <= options['limit'] <= 25 or not 1 <= options['max_seconds'] <= 240:
            raise CommandError('Use --limit 1-25 and --max-seconds 1-240.')
        if not options['apply']:
            self.stdout.write(f'DRY RUN: {queued_operations().count()} due publication(s). No outbound calls or cleanup.')
            return
        begin_runner(RUNNER)
        deadline = time.monotonic() + options['max_seconds']
        processed = 0
        try:
            cleanup()
            # Snapshot IDs so paused, leased or cooling-down work cannot starve this run.
            for job in list(queued_operations()[:options['limit']]):
                remaining = deadline - time.monotonic()
                if remaining < 1:
                    break
                publish(job, seconds=remaining)
                processed += 1
            finish_runner(RUNNER, processed_count=processed)
        except Exception:
            finish_runner(RUNNER, processed_count=processed, error_code='runner_failed')
            raise
        self.stdout.write(f'APPLY: {processed} publication(s) inspected; {queued_operations().count()} remain due.')
