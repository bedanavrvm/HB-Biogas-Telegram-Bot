import json

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from core.services.fresh_database_baseline import apply_baseline, audit_baseline


class Command(BaseCommand):
    help = 'Audit or idempotently reconcile governed reference data on a fresh database.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Apply the baseline; the default is read-only.')
        parser.add_argument('--actor', default='', help='Active Superuser username for apply attribution.')
        parser.add_argument('--format', choices=('table', 'json'), default='table')

    def handle(self, *args, **options):
        if options['apply']:
            actor = get_user_model().objects.filter(
                username=options['actor'], is_active=True, is_superuser=True,
            ).first()
            if actor is None:
                raise CommandError('--actor must identify an active Django Superuser.')
            try:
                report = apply_baseline(actor=actor)
            except ValueError as exc:
                raise CommandError(str(exc)) from exc
        else:
            report = audit_baseline()

        if options['format'] == 'json':
            self.stdout.write(json.dumps(report, indent=2, sort_keys=True))
        else:
            summary = report['summary']
            self.stdout.write(
                f"Baseline: {summary['correct']} correct, {summary['missing']} missing, "
                f"{summary['conflicting']} conflicting."
            )
            counts = report['location_counts']
            self.stdout.write(
                f"Active locations: {counts['branches']} branches, {counts['counties']} counties, "
                f"{counts['sub_counties']} sub-counties."
            )
            for item in report['items']:
                if item['state'] != 'correct':
                    self.stdout.write(f"{item['state'].upper()}: {item['area']} / {item['key']} - {item['detail']}")
            self.stdout.write(report['next_step'])
        if not report['ok']:
            raise CommandError('Fresh-database baseline is not ready.')
