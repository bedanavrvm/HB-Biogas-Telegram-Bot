import json

from django.core.management.base import BaseCommand, CommandError

from core.services.jawabu_approvals import visit_media_orphan_report


class Command(BaseCommand):
    help = 'Report controlled Jawabu visit media linkage; never relinks or deletes Drive files.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=100, help='Maximum orphan candidates to print.')
        parser.add_argument('--strict', action='store_true', help='Exit non-zero when orphan candidates remain.')

    def handle(self, *args, **options):
        report = visit_media_orphan_report(limit=max(1, options['limit']))
        self.stdout.write(json.dumps(report, indent=2, sort_keys=True))
        if options['strict'] and report['orphan_candidate_count']:
            raise CommandError('Unlinked controlled Jawabu visit media requires review.')
