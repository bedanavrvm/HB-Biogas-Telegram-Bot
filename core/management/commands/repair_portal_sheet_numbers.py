"""Dry-run-first No. repair for the two Portal customer register tabs."""

from django.core.management.base import BaseCommand, CommandError

from core.models import GroupSheetConfiguration
from core.services.jawabu_master import (
    header_lookup_from_headers,
    master_sheet_number_changes,
    repair_master_sheet_numbers,
)
from core.services.sheets import GoogleSheetsService


class Command(BaseCommand):
    help = 'Review or repair per-tab No. values in Master Data and Eco-conserve.'

    def add_arguments(self, parser):
        parser.add_argument('--group-id', required=True)
        parser.add_argument('--commit', action='store_true', help='Write only the No. cells after review.')

    def handle(self, *args, **options):
        config = GroupSheetConfiguration.objects.filter(group_id=options['group_id']).first()
        if config is None:
            raise CommandError('The specified group configuration does not exist.')
        workflow = config.workflow or {}
        sheet_id = str(workflow.get('master_sheet_id') or config.sheet_id or '').strip()
        if not sheet_id:
            raise CommandError('The specified group has no Master Data spreadsheet configured.')
        header_row = int(workflow.get('master_header_row') or 1)
        data_start_row = int(workflow.get('master_data_start_row') or header_row + 1)
        names = (
            str(workflow.get('master_sheet_name') or 'Master Data').strip(),
            str(workflow.get('eco_conserve_sheet_name') or 'Eco-conserve').strip(),
        )
        if not all(names) or names[0] == names[1]:
            raise CommandError('Master and Eco-conserve tabs must be distinct and configured.')
        sheets = []
        for name in names:
            service = GoogleSheetsService.get_instance(sheet_id=sheet_id, sheet_name=name)
            if not service.is_available():
                raise CommandError(f'The {name} tab is unavailable; no numbering changes were made.')
            sheet = service._sheet
            lookup = header_lookup_from_headers(sheet.row_values(header_row))
            if 'no' not in lookup or 'customer name' not in lookup:
                raise CommandError(f'The {name} tab needs No. and Customer Name headers; no changes were made.')
            sheets.append((name, sheet, lookup))
        for name, sheet, lookup in sheets:
            count = len(master_sheet_number_changes(sheet, lookup, data_start_row))
            self.stdout.write(f'{name}: {count} No. cell(s) need correction.')
        if options['commit']:
            for name, sheet, lookup in sheets:
                count = repair_master_sheet_numbers(sheet, lookup, data_start_row)
                self.stdout.write(f'{name}: corrected {count} No. cell(s).')
        else:
            self.stdout.write('DRY RUN: no Sheet cells were changed. Use --commit to apply.')
