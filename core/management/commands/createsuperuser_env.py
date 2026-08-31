from django.core.management.base import BaseCommand, CommandError

from core.services.superuser_bootstrap import (
    SuperuserBootstrapError,
    bootstrap_superuser_from_environment,
)


class Command(BaseCommand):
    help = 'Create superuser from environment variables'

    def handle(self, *args, **options):
        try:
            result = bootstrap_superuser_from_environment()
        except SuperuserBootstrapError as exc:
            raise CommandError(str(exc)) from exc
        if result.outcome == 'skipped':
            self.stdout.write(
                self.style.WARNING(
                    'Superuser environment variables not set. Skipping superuser creation.'
                )
            )
            return

        if result.outcome == 'existing':
            self.stdout.write(
                self.style.SUCCESS(
                    f'Superuser "{result.username}" already exists. Skipping creation.'
                )
            )
            return
        self.stdout.write(
            self.style.SUCCESS(f'Successfully created superuser "{result.username}"')
        )
