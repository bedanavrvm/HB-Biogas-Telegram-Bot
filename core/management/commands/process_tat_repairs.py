import logging

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.services.durable_jobs import TAT_REPAIR_RUNNER, begin_runner, finish_runner
from core.services.tat_repair_jobs import process_next_repair_job


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Process bounded database-leased TAT repair case chunks.'

    def add_arguments(self, parser):
        parser.add_argument('--max-jobs', type=int, default=1)
        parser.add_argument('--case-limit', type=int, default=None)

    def handle(self, *args, **options):
        begin_runner(TAT_REPAIR_RUNNER)
        shadow = bool(getattr(settings, 'DURABLE_JOB_RUNNERS_SHADOW_MODE', True))
        configured = int(getattr(settings, 'TAT_REPAIR_RUNNER_MAX_CASES', 5) or 5)
        requested = options['case_limit'] if options['case_limit'] is not None else configured
        case_limit = max(1, min(int(requested), 1 if shadow else 1000))
        max_jobs = max(1, min(int(options['max_jobs']), 100))
        processed = 0
        jobs = 0
        try:
            for _ in range(max_jobs):
                result = process_next_repair_job(case_limit=case_limit)
                if result is None:
                    break
                jobs += 1
                processed += int(result['processed_cases'])
            finish_runner(TAT_REPAIR_RUNNER, processed_count=processed)
        except Exception as exc:
            finish_runner(TAT_REPAIR_RUNNER, processed_count=processed, error_code='runner_failed')
            logger.exception('Durable TAT repair runner failed.')
            raise CommandError('TAT repair processing failed; inspect runner health evidence.') from exc
        self.stdout.write(self.style.SUCCESS(
            f'Processed {processed} TAT repair case(s) across {jobs} job(s); shadow={shadow}.'
        ))
