"""Read-only schema audit: never logs cells, credentials or spreadsheet IDs."""
import json

from django.core.management.base import BaseCommand, CommandError

from core.models import GroupSheetConfiguration
from core.services.sheet_columns import NamedColumns, SheetColumnError


class Command(BaseCommand):
    help = 'Audit unique named worksheet columns. Default is configuration-only; --live explicitly reads Google headers.'

    def add_arguments(self, parser):
        parser.add_argument('--configuration', action='append', default=[])
        parser.add_argument('--live', action='store_true')
        parser.add_argument('--bm-stage', action='store_true', help='Also require the three BM columns before activation.')

    def handle(self, *args, **options):
        configurations = GroupSheetConfiguration.objects.filter(enabled=True)
        if options['configuration']:
            configurations = configurations.filter(pk__in=options['configuration'])
        results = []
        for config in configurations:
            workflow = config.workflow or {}
            kind = str(workflow.get('type') or 'case')
            tabs = [str(config.sheet_name or '')]
            if kind == 'tat_tracker':
                from core.services.tat_tracker import tat_projection_sheet_name
                tabs = [tat_projection_sheet_name(config)]
                if workflow.get('sync_secondary_sheets'):
                    tabs += ['CASE_INDEX', 'AUDIT LOG']
                tabs += ['TAT TARGETS']
            elif kind == 'order_approval':
                tabs += list(workflow.get('search_sheet_names') or [])
            elif kind in {'jawabu', 'jawabu_portal', 'jawabu_pipeline'}:
                tabs += [workflow.get('master_sheet_name') or 'Master Data',
                         workflow.get('eco_conserve_sheet_name') or 'Eco-conserve']
            for tab in dict.fromkeys(value for value in tabs if value):
                row = {'configuration': str(config.pk), 'workflow': kind, 'worksheet': tab,
                       'status': 'not_read', 'issues': []}
                if options['live']:
                    try:
                        from core.services.sheets import get_sheets_service
                        sheet_id = workflow.get('master_sheet_id') or config.sheet_id if (
                            kind in {'jawabu', 'jawabu_portal', 'jawabu_pipeline'} and
                            tab in {workflow.get('master_sheet_name') or 'Master Data',
                                    workflow.get('eco_conserve_sheet_name') or 'Eco-conserve'}
                        ) else config.sheet_id
                        service = get_sheets_service(sheet_id=sheet_id, sheet_name=tab)
                        if not service.is_available():
                            raise SheetColumnError('Worksheet is unavailable; retry the read-only audit.')
                        header_row = int(workflow.get('header_row') or 1)
                        if tab in {'TAT Register', 'CASE_INDEX', 'AUDIT LOG', 'TAT TARGETS'}:
                            header_row = 1
                        if kind in {'jawabu', 'jawabu_portal', 'jawabu_pipeline'} and tab in {
                            workflow.get('master_sheet_name') or 'Master Data', workflow.get('eco_conserve_sheet_name') or 'Eco-conserve',
                        }:
                            from core.services.jawabu_master import resolve_master_sheet_layout
                            header_row, _start, headers = resolve_master_sheet_layout(service._sheet, workflow)
                        else:
                            headers = service._sheet.row_values(header_row)
                        columns = NamedColumns(headers, sheet_name=tab)
                        row['columns'] = [{'name': name, 'position': number}
                                          for number, name in enumerate(columns.headers, 1) if name.strip()]
                        if kind == 'tat_tracker' and tab == tat_projection_sheet_name(config):
                            from core.services.tat_tracker import configured_products, validate_tracker_identity_headers
                            from core.services.tat_sheet_schema import stage_names, timestamp_names, stage_minute_names
                            validate_tracker_identity_headers(list(columns.headers))
                            for product in configured_products(workflow):
                                for stage in product.stages:
                                    columns.column(*stage_names(stage))
                                    columns.column(*stage_minute_names(stage, product))
                                    if stage.auto_timestamp_key:
                                        columns.column(*timestamp_names(stage))
                            if options['bm_stage']:
                                for name in ('BM analysis approval', 'BM analysis approval timestamp', 'BM analysis approval TAT Minutes'):
                                    columns.column(name)
                        row['status'] = 'valid'
                    except SheetColumnError as exc:
                        row['status'] = 'needs_repair'
                        row['issues'].append(str(exc))
                    except Exception:
                        row['status'] = 'unavailable'
                        row['issues'].append('The worksheet could not be checked; no changes were made.')
                results.append(row)
        self.stdout.write(json.dumps(results, indent=2))
        if any(row['status'] in {'needs_repair', 'unavailable'} for row in results):
            raise CommandError('Named-column audit found worksheets needing review. No data was changed.')
