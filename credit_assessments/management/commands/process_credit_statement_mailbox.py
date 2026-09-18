from django.core.management.base import BaseCommand, CommandError

from credit_assessments.mailbox import poll_mailbox


class Command(BaseCommand):
    help = 'Inspect or ingest M-PESA statement attachments from the dedicated Gmail inbox.'

    def add_arguments(self, parser):
        parser.add_argument('--commit', action='store_true', help='Upload matching PDFs to restricted Drive and persist receipt metadata.')
        parser.add_argument('--limit', type=int, default=50, help='Maximum Gmail messages to inspect (1-500).')

    def handle(self, *args, **options):
        try:
            result = poll_mailbox(commit=bool(options['commit']), limit=int(options['limit']))
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        mode = 'COMMIT' if result['commit'] else 'DRY RUN'
        self.stdout.write(self.style.SUCCESS(
            f"{mode}: inspected {result['messages']} message(s); "
            f"{result['ingested']} matching statement(s), {result['skipped']} skipped."
        ))
