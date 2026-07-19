"""Explicit repair command for Django-owned TAT values in tracker sheets."""

from django.core.management.base import BaseCommand, CommandError

from core.models import GroupSheetConfiguration
from core.services.tat_tracker import (
    PRODUCTS,
    is_tat_tracker_workflow,
    resync_tat_tracker_cases,
)


class Command(BaseCommand):
    help = 'Re-sync linked TAT tracker rows from Django. Run with --dry-run first.'

    def add_arguments(self, parser):
        parser.add_argument('--group-id', required=True, help='Configured TAT Tracker Telegram group ID.')
        parser.add_argument('--product', choices=sorted(PRODUCTS), help='Restrict the repair to one product.')
        parser.add_argument('--case-id', action='append', default=[], help='Restrict the repair to one case ID; repeatable.')
        parser.add_argument('--limit', type=int, help='Maximum linked cases to re-sync.')
        parser.add_argument('--dry-run', action='store_true', help='Report affected cases without writing to Google Sheets.')

    def handle(self, *args, **options):
        if options.get('limit') is not None and options['limit'] < 1:
            raise CommandError('--limit must be at least 1.')

        group_id = str(options['group_id']).strip()
        config = GroupSheetConfiguration.objects.filter(group_id=group_id).first()
        if not config:
            raise CommandError(f'No group configuration exists for {group_id}.')
        if not is_tat_tracker_workflow(config):
            raise CommandError(f'Group {group_id} is not configured for the TAT Tracker.')

        result = resync_tat_tracker_cases(
            config,
            product_key=options.get('product') or '',
            case_ids=options.get('case_id') or [],
            dry_run=options['dry_run'],
            limit=options.get('limit'),
            offset=0,
        )
        self.stdout.write(str(result))
        if result['failed']:
            raise CommandError('One or more cases could not be re-synced; see the result above.')
