"""Inspect or explicitly apply the reviewed deployment LAF bundle."""
from django.core.management.base import BaseCommand, CommandError

from origination.services.origination_laf_bootstrap import bootstrap_lafs


class Command(BaseCommand):
    help = 'Inspect eleven blank LAF seeds; --apply uploads unassigned drafts, --force explicitly recreates deleted seeds.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--force', action='store_true')
        parser.add_argument('--actor', default='')

    def handle(self, *args, **options):
        try:
            result = bootstrap_lafs(apply=options['apply'], force=options['force'],
                                    actor_username=options['actor'])
        except Exception as exc:
            raise CommandError('LAF bootstrap failed. Check the reviewed assets, canonical field contracts, active Superuser actor and Drive configuration.') from exc
        self.stdout.write(f"LAF bootstrap: {result['status']} ({result['fingerprint'][:12]}).")
