import logging

from django.core.management.base import BaseCommand, CommandError

from core.services.tat_notifications import (
    begin_notification_processor_run,
    finish_notification_processor_run,
    process_due_tasks,
)


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Deliver due TAT alerts and process post-update external dispatches.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=100)

    def handle(self, *args, **options):
        run, acquired = begin_notification_processor_run()
        if not acquired:
            self.stdout.write(self.style.WARNING(
                f'Skipped overlapping TAT notification run ({run.pk}).'
            ))
            return
        count = 0
        dispatch_count = 0
        try:
            count = process_due_tasks(limit=max(1, min(int(options['limit']), 1000)))
            from core.services.tat_update_dispatch import process_dispatches
            dispatch_count = process_dispatches(limit=max(1, min(int(options['limit']), 500)))
            completed = finish_notification_processor_run(
                run, processed_task_count=count, processed_dispatch_count=dispatch_count,
            )
        except Exception as exc:
            try:
                finish_notification_processor_run(
                    run, processed_task_count=count,
                    processed_dispatch_count=dispatch_count, error=exc,
                )
            except Exception:
                logger.exception(
                    'TAT notification processor failure evidence could not be finalized; run=%s.',
                    run.pk,
                )
            logger.exception('Scheduled TAT notification processing failed; run=%s.', run.pk)
            raise CommandError('TAT notification processing failed; inspect server monitoring.') from exc
        self.stdout.write(self.style.SUCCESS(
            f'Processed {count} due TAT task(s) and {dispatch_count} update dispatch(es); run={completed.pk}.'
        ))
