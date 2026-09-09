from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Retired compatibility command; complaint batch imports are archived.'

    def add_arguments(self, parser):
        parser.add_argument('--max-batches', type=int, default=1)
        parser.add_argument('--item-limit', type=int, default=None)
        parser.add_argument('--notification-limit', type=int, default=10)

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING(
            'Complaint batch imports are retired; no records were processed.'
        ))
