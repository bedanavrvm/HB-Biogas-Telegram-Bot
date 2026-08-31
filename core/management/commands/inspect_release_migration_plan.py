"""Print the exact migration plan without changing database state."""

import json

from django.core.management.base import BaseCommand

from core.services.production_release import migration_plan_names, migration_plan_sha256


class Command(BaseCommand):
    help = 'Print the forward Django migration plan and its SHA-256 without applying it.'

    def add_arguments(self, parser):
        parser.add_argument('--json', action='store_true', help='Print machine-readable output.')

    def handle(self, *args, **options):
        names = migration_plan_names()
        payload = {
            'count': len(names),
            'migrations': names,
            'sha256': migration_plan_sha256(names),
        }
        if options['json']:
            self.stdout.write(json.dumps(payload, sort_keys=True))
            return
        self.stdout.write(f"Migration plan ({payload['count']}):")
        for name in names:
            self.stdout.write(f'  - {name}')
        self.stdout.write(f"Plan SHA-256: {payload['sha256']}")
