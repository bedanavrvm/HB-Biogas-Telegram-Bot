"""Optional recovery runner; normal authorized reads wake the same durable work."""
from django.core.management.base import BaseCommand
from origination.services.origination_dispatch import eligible_operations, process_operations


class Command(BaseCommand):
    help = 'Inspect queued Origination delivery/archival work; --apply processes at most five operations.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        ids = list(eligible_operations().order_by('created_at').values_list('pk', flat=True)[:5])
        self.stdout.write(f'{len(ids)} eligible Origination operation(s).')
        if options['apply']:
            process_operations(ids)
