from django.core.management.base import BaseCommand
from report_delivery.services import purge_history


class Command(BaseCommand):
    help = 'Erase old report payloads (30 days) and bounded delivery metadata (180 days).'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        if not options['apply']:
            self.stdout.write('Read only. Use --apply for bounded retention cleanup.')
            return
        payloads, deliveries, events = purge_history(limit=100)
        self.stdout.write(f'Erased {payloads} payloads; removed {deliveries} deliveries and {events} receipts.')
