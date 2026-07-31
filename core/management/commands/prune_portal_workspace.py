"""Release expired private Portal workspace conveniences without touching cases."""

from django.core.management.base import BaseCommand

from core.services.portal_workspace import purge_expired_workspace_metadata


class Command(BaseCommand):
    help = (
        'Preview or apply retention for private Portal saved recents and inaccessible pins. '
        'This command never changes Jawabu cases, workflow state, financial data, or audit history.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply', action='store_true',
            help='Apply the retention cleanup. Without this flag the command is read-only.',
        )

    def handle(self, *args, **options):
        result = purge_expired_workspace_metadata(apply=bool(options['apply']))
        message = (
            f"{result['stale_pins_released']} inaccessible pin(s) eligible for release; "
            f"{result['expired_workspace_rows_deleted']} expired workspace row(s) eligible for deletion."
        )
        if options['apply']:
            self.stdout.write(self.style.SUCCESS(f'Applied Portal workspace retention: {message}'))
        else:
            self.stdout.write(self.style.WARNING(f'Dry run only: {message} Re-run with --apply to make changes.'))
