import json

from django.core.management.base import BaseCommand, CommandError

from core.services.location_catalog import catalog_readiness, current_policy


class Command(BaseCommand):
    help = 'Report governed branch/county/sub-county readiness without changing data.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--require-ready', action='store_true',
            help='Return a non-zero exit status when strict-enforcement readiness is incomplete.',
        )

    def handle(self, *args, **options):
        payload = {
            'policy_mode': current_policy().mode,
            **catalog_readiness(),
        }
        self.stdout.write(json.dumps(payload, indent=2, sort_keys=True))
        if options['require_ready'] and not payload['ready']:
            raise CommandError('The location catalogue is not ready for strict enforcement.')
