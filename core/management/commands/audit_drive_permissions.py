"""Inspect the configured media-root sharing policy without changing Drive."""
import json

from django.core.management.base import BaseCommand, CommandError

from core.services.sync_governance import audit_drive_media_root


class Command(BaseCommand):
    help = 'Read the configured Google Drive media-root sharing policy. No Drive permissions are changed.'

    def add_arguments(self, parser):
        parser.add_argument('--strict', action='store_true', help='Return non-zero when the root is unavailable or broadly shared.')
        parser.add_argument('--json', action='store_true', help='Emit the operator-readable inspection result as JSON.')

    def handle(self, *args, **options):
        result = audit_drive_media_root()
        if options['json']:
            self.stdout.write(json.dumps(result, indent=2, sort_keys=True))
        else:
            self.stdout.write(
                f"Drive media root: {result['status']} — broad permissions: {result['broad_permission_count']}"
            )
            self.stdout.write(result['message'])
        if options['strict'] and result['status'] != 'restricted':
            raise CommandError('Drive media-root audit requires review.')
