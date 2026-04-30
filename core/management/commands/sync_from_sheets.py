"""
Sync Google Sheets source-of-truth data into the local backend.
"""
from django.core.management.base import BaseCommand, CommandError

from core.services.sheet_sync import (
    sync_all_configured_groups,
    sync_group_from_sheet,
)


class Command(BaseCommand):
    help = "Mirror Google Sheets rows into the backend database."

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
        delete_missing = not options['keep_missing']
        group_id = options.get('group_id')

        if group_id:
            result = sync_group_from_sheet(
                group_id=group_id,
                delete_missing=delete_missing,
            )
        else:
            result = sync_all_configured_groups(delete_missing=delete_missing)

        if result.get('status') not in {'success', 'partial'}:
            raise CommandError(result)

        self.stdout.write(self.style.SUCCESS(str(result)))
