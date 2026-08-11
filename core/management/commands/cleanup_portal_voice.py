from django.core.management.base import BaseCommand

from core.services.portal_voice import cleanup_expired_transcriptions


class Command(BaseCommand):
    help = 'Trash expired temporary Portal voice recordings and clear transient transcripts.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=100)

    def handle(self, *args, **options):
        result = cleanup_expired_transcriptions(limit=max(1, options['limit']))
        self.stdout.write(self.style.SUCCESS(
            f"Examined {result['examined']}; deleted {result['deleted']}; failed {result['failed']}."
        ))
