import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.services.environment_audit import audit_environment, clean_environment


class Command(BaseCommand):
    help = 'Audit dotenv variable names or conservatively remove deprecated/default entries.'

    def add_arguments(self, parser):
        parser.add_argument('--path', default=str(Path(settings.BASE_DIR) / '.env'))
        parser.add_argument('--format', choices=('table', 'json'), default='table')
        parser.add_argument('--write-cleaned', action='store_true')
        parser.add_argument('--drop-bootstrap', action='store_true')

    def handle(self, *args, **options):
        path = Path(options['path']).resolve()
        try:
            report = (
                clean_environment(path, drop_bootstrap=options['drop_bootstrap'])
                if options['write_cleaned'] else audit_environment(path)
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        if options['format'] == 'json':
            self.stdout.write(json.dumps(report, indent=2, sort_keys=True))
            return
        self.stdout.write(f"Environment entries: {report['count']}")
        for state, count in report['summary'].items():
            self.stdout.write(f'{state}: {count}')
        for item in report['entries']:
            if item['state'] != 'retained':
                self.stdout.write(f"{item['state'].upper()}: {item['key']}")
        if report.get('backup'):
            self.stdout.write(f"Backup created at {report['backup']}")
