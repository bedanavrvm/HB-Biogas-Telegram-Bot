"""Run explicit, read-only schema and publication-divergence audits."""
import json

from django.core.management.base import BaseCommand, CommandError

from core.services.sync_governance import audit_configured_sheet_registers


class Command(BaseCommand):
    help = 'Audit enabled, Django-published Sheet register contracts. The command never changes Google Sheets.'

    def add_arguments(self, parser):
        parser.add_argument('--group-id', help='Limit to one configured Telegram group ID.')
        parser.add_argument('--register', help='Limit to one stable register key.')
        parser.add_argument('--checked-by', default='management:audit_sheet_registers', help='Audit actor retained with the local evidence.')
        parser.add_argument('--no-persist', action='store_true', help='Report only; do not create local audit evidence rows.')
        parser.add_argument('--strict', action='store_true', help='Return a non-zero result unless every audited register is healthy.')
        parser.add_argument('--json', action='store_true', help='Emit privacy-preserving JSON evidence.')

    def handle(self, *args, **options):
        results = audit_configured_sheet_registers(
            group_id=str(options.get('group_id') or '').strip(),
            register_key=str(options.get('register') or '').strip(),
            checked_by=str(options.get('checked_by') or ''),
            persist=not options['no_persist'],
        )
        if not results:
            raise CommandError(
                'No enabled Sheet register contracts matched. Add an explicit publication contract before auditing a register.'
            )
        if options['json']:
            self.stdout.write(json.dumps(results, indent=2, sort_keys=True, default=str))
        else:
            for result in results:
                self.stdout.write(
                    f"{result['group_id']} / {result['register_key']} / {result['sheet_name']}: "
                    f"{result['status']} — {result['rows_checked']} row(s), "
                    f"{result['discrepancy_count']} discrepancy/discrepancies"
                )
                if result['missing_headers']:
                    self.stdout.write('  Missing headers: ' + ', '.join(result['missing_headers']))
                if result['duplicate_headers']:
                    self.stdout.write('  Duplicate headers: ' + ', '.join(result['duplicate_headers']))
                if result['reordered_headers']:
                    self.stdout.write('  Expected headers are reordered.')
                if result['error']:
                    self.stdout.write('  ' + result['error'])
        if options['strict'] and any(result['status'] != 'healthy' for result in results):
            raise CommandError('One or more Sheet register audits require review.')
