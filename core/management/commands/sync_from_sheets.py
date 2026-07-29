"""Compatibility command for the retired Sheet-to-Django import path."""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Deprecated: Google Sheets are view-only publication surfaces."

    def add_arguments(self, parser):
        parser.add_argument(
            '--group-id',
            dest='group_id',
            help='Sync one Telegram group. Omit to sync all configured groups.',
        )
        parser.add_argument(
            '--keep-missing',
            action='store_true',
            help='Do not delete backend cases that are missing from the sheet.',
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING(
            'SHEET_IMPORT_DISABLED: Google Sheets are view-only. '
            'No backend records were changed. Use the explicit CSV/XLSX import workflows.'
        ))
