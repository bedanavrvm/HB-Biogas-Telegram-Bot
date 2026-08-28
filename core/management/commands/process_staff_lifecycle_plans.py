from django.core.management.base import BaseCommand

from core.services.staff_lifecycle import process_due_lifecycle_plans


class Command(BaseCommand):
    help = 'Apply independently approved staff lifecycle plans whose effective time has arrived.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=100)

    def handle(self, *args, **options):
        result = process_due_lifecycle_plans(limit=max(1, min(options['limit'], 1000)))
        self.stdout.write(
            self.style.SUCCESS(
                f"Due: {result['due']}; applied: {result['applied']}; stale: {result['stale']}."
            )
        )
