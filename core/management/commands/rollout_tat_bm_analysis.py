import json

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from core.services.tat_bm_stage_rollout import inventory, prepare, publish


class Command(BaseCommand):
    help = 'Dry-run BM analysis stage successors; --apply prepares and --publish explicitly activates selected products.'

    def add_arguments(self, parser):
        parser.add_argument('--product', action='append', default=[])
        parser.add_argument('--actor', default='')
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--publish', action='store_true')

    def handle(self, *args, **options):
        rows = inventory(options['product'])
        missing = set(options['product']) - {row['product'] for row in rows}
        if missing:
            raise CommandError('No eligible TAT configuration for: ' + ', '.join(sorted(missing)))
        self.stdout.write(json.dumps(rows, indent=2))
        if not options['apply']:
            if options['publish']:
                raise CommandError('--publish also requires --apply.')
            return
        if not options['product']:
            raise CommandError('Select exact --product codes before applying this change.')
        actor = get_user_model().objects.filter(username=options['actor'], is_active=True, is_superuser=True).first()
        if not actor:
            raise CommandError('--actor must identify an active Django Superuser.')
        from core.services.workflow_capabilities import capability_definitions
        capability_definitions.cache_clear()
        for row in rows:
            try:
                draft = prepare(row['source_id'], actor=actor)
                if options['publish']:
                    draft = publish(draft, actor=actor)
                self.stdout.write(f'{row["product"]}: version {draft.version} {draft.status}')
            except ValueError as exc:
                self.stderr.write(f'{row["product"]}: {exc}')
                raise CommandError('Rollout stopped; earlier completed products are safe to retry.') from exc
        capability_definitions.cache_clear()
