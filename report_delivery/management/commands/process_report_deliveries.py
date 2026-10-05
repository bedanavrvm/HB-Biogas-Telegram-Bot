import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from core.services.durable_jobs import begin_runner, finish_runner
from report_delivery.services import claim_delivery, process_delivery, purge_history, reserve_due


class Command(BaseCommand):
    help = 'Reserve latest due Portal reports and deliver bounded leased work through Resend.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Allow report generation and email submission.')
        parser.add_argument('--limit', type=int, default=5)
        parser.add_argument('--max-seconds', type=int, default=50)

    def handle(self, *args, **options):
        if not options['apply']:
            self.stdout.write('Read only. Use --apply after configuring approved recipients and Resend.')
            return
        if not settings.REPORT_EMAIL_DELIVERY_ENABLED or not settings.RESEND_API_KEY or not settings.REPORT_EMAIL_FROM:
            raise CommandError('Report email delivery is disabled or not configured.')
        if not 1 <= options['limit'] <= 50 or not 1 <= options['max_seconds'] <= 300:
            raise CommandError('Use limit 1–50 and max-seconds 1–300.')
        begin_runner('report_delivery')
        count, error = 0, ''
        started = time.monotonic()
        try:
            reserve_due(limit=options['limit'])
            purge_history(limit=100)
            while count < options['limit'] and time.monotonic() - started < options['max_seconds']:
                delivery = claim_delivery()
                if delivery is None:
                    break
                process_delivery(delivery)
                count += 1
        except Exception:
            error = 'report_runner_failed'
            raise CommandError('Report runner failed. Retained leases and idempotency keys protect retries.') from None
        finally:
            finish_runner('report_delivery', processed_count=count, error_code=error)
        self.stdout.write(f'Processed {count} report deliveries.')
