from django.core.management.base import BaseCommand, CommandError

from core.models import GroupSheetConfiguration
from core.services.sheets import get_sheets_service
from core.services.tat_tracker import (
    configured_products,
    is_tat_tracker_workflow,
    cleanup_tat_sheet_duplicate_case_ids,
)


class Command(BaseCommand):
    help = 'Find duplicate TAT case-ID rows; dry-run by default, delete extras only with --apply.'

    def add_arguments(self, parser):
        parser.add_argument('--group-id', required=True, help='Configured TAT Tracker Telegram group ID.')
        parser.add_argument('--product', choices=('logbook', 'mjengo', 'kilimo', 'micro_asset', 'business'))
        parser.add_argument('--apply', action='store_true', help='Delete duplicate rows after the dry-run has been reviewed.')
        parser.add_argument('--include-unlinked', action='store_true', help='Also delete duplicate IDs that have no active Django case.')

    def handle(self, *args, **options):
        group_id = str(options['group_id']).strip()
        config = GroupSheetConfiguration.objects.filter(group_id=group_id).first()
        if not config:
            raise CommandError(f'No group configuration exists for {group_id}.')
        if not is_tat_tracker_workflow(config):
            raise CommandError(f'Group {group_id} is not configured for the TAT Tracker.')

        products = configured_products(config.workflow)
        selected = str(options.get('product') or '').strip()
        if selected:
            products = [product for product in products if product.key == selected]
        if not products:
            raise CommandError('No configured TAT product matched the requested filter.')

        mode = 'APPLY' if options['apply'] else 'DRY-RUN'
        total = 0
        for product in products:
            service = get_sheets_service(sheet_id=config.sheet_id, sheet_name=product.sheet_name)
            if not service.is_available():
                raise CommandError(f'Google Sheets is unavailable for {product.sheet_name}.')
            reports = cleanup_tat_sheet_duplicate_case_ids(
                service._sheet,
                group_id=group_id,
                apply=options['apply'],
                include_unlinked=options['include_unlinked'],
            )
            total += len(reports)
            self.stdout.write(f'{mode} {product.key}: {len(reports)} duplicate case ID group(s).')
            for report in reports:
                self.stdout.write(
                    f"  {report['case_id']}: keep row {report.get('surviving_row', report['keep_row'])}; "
                    f"remove {report['delete_rows']}; linked={report['linked']}"
                    f"{'; skipped (unlinked)' if report.get('skipped_unlinked') else ''}"
                )
        if not total:
            self.stdout.write(f'{mode}: no duplicate TAT case IDs found.')
