from django.core.management.base import BaseCommand, CommandError

from core.services.portal_reconciliation import reconcile_due_artifacts


class Command(BaseCommand):
    help = 'Dry-run or retry due Drive-backed Jawabu portal artifacts.'

    def add_arguments(self, parser):
        parser.add_argument('--kind', choices=('orders', 'payments', 'all'), default='all')
        parser.add_argument('--limit', type=int, default=25)
        parser.add_argument('--apply', action='store_true', help='Perform external uploads; default is dry-run.')

    def handle(self, *args, **options):
        limit = options['limit']
        if limit < 1 or limit > 250:
            raise CommandError('--limit must be between 1 and 250.')
        result = reconcile_due_artifacts(
            kind=options['kind'],
            limit=limit,
            dry_run=not options['apply'],
        )
        mode = 'APPLY' if options['apply'] else 'DRY-RUN'
        self.stdout.write(f'{mode}: {len(result["orders"])} order artifact(s), {len(result["payments"])} payment artifact(s) selected.')
        for entry in [*result['orders'], *result['payments']]:
            self.stdout.write(str(entry))
