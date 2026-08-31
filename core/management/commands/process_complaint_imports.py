import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.services.complaint_imports import (
    deliver_complaint_import_notifications,
    process_next_complaint_import_batch,
)
from core.services.durable_jobs import (
    COMPLAINT_IMPORT_RUNNER,
    begin_runner,
    finish_runner,
)


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Process bounded durable complaint-import chunks and completion notifications.'

    def add_arguments(self, parser):
        parser.add_argument('--max-batches', type=int, default=1)
        parser.add_argument('--item-limit', type=int, default=None)
        parser.add_argument('--notification-limit', type=int, default=10)

    def handle(self, *args, **options):
        begin_runner(COMPLAINT_IMPORT_RUNNER)
        shadow = bool(getattr(settings, 'DURABLE_JOB_RUNNERS_SHADOW_MODE', True))
        configured = int(getattr(settings, 'COMPLAINT_IMPORT_RUNNER_MAX_ITEMS', 10) or 10)
        requested = options['item_limit'] if options['item_limit'] is not None else configured
        item_limit = max(1, min(int(requested), 1 if shadow else 1000))
        max_batches = max(1, min(int(options['max_batches']), 100))
        processed = 0
        batches = 0
        try:
            for _ in range(max_batches):
                result = process_next_complaint_import_batch(item_limit=item_limit)
                if result is None:
                    break
                batches += 1
                processed += int(result['processed_items'])
            delivered = deliver_complaint_import_notifications(
                limit=max(1, min(int(options['notification_limit']), 100)),
            )
            finish_runner(COMPLAINT_IMPORT_RUNNER, processed_count=processed)
        except Exception as exc:
            finish_runner(COMPLAINT_IMPORT_RUNNER, processed_count=processed, error_code='runner_failed')
            logger.exception('Durable complaint import runner failed.')
            raise CommandError('Complaint import processing failed; inspect runner health evidence.') from exc
        self.stdout.write(self.style.SUCCESS(
            f'Processed {processed} complaint item(s) across {batches} batch(es); '
            f'delivered {delivered} completion notification(s); shadow={shadow}.'
        ))
