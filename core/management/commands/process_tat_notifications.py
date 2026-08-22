from django.core.management.base import BaseCommand

from core.services.tat_notifications import process_due_tasks


class Command(BaseCommand):
    help = 'Deliver due private TAT task alerts and SLA backup escalations.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=100)

    def handle(self, *args, **options):
        count = process_due_tasks(limit=max(1, min(int(options['limit']), 1000)))
        self.stdout.write(self.style.SUCCESS(f'Processed {count} due TAT task(s).'))
