"""Print the read-only relationship inventory used by Portal reporting."""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from core.services.reporting_relationships import relationship_inventory, portal_relationship_summary


class Command(BaseCommand):
    help = 'Print the Django model relationship inventory; this command never reads customer rows or writes data.'

    def add_arguments(self, parser):
        parser.add_argument('--json', action='store_true', dest='as_json')

    def handle(self, *args, **options):
        payload = {
            'portal_summary': portal_relationship_summary(),
            'models': relationship_inventory(),
        }
        if options['as_json']:
            self.stdout.write(json.dumps(payload, indent=2, sort_keys=True))
            return
        self.stdout.write('Portal reporting relationship inventory (read-only)')
        self.stdout.write(f"Root: {payload['portal_summary']['root']}")
        self.stdout.write('Identity-only / non-joinable sources: ' + ', '.join(payload['portal_summary']['unlinked_identity_only']))
        for model in payload['models']:
            self.stdout.write(model['model'])
            for relation in model['relations']:
                self.stdout.write(
                    f"  {relation['direction']} {relation['name']} -> {relation['target']} "
                    f"({relation['cardinality']}; {relation['classification']})"
                )
