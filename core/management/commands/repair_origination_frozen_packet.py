from django.core.management.base import BaseCommand, CommandError

from core.models import OriginationSigningPackage
from core.services.loan_origination import (
    OriginationError,
    recover_legacy_frozen_package,
    reset_unrecoverable_package_for_review,
)


class Command(BaseCommand):
    help = (
        'Verify and recover one legacy Origination review packet; dry-run by default. '
        'Use --apply to store exact hash-matching bytes.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--package-id', required=True, help='Origination signing package UUID.')
        parser.add_argument('--apply', action='store_true', help='Persist an exact verified reconstruction.')
        parser.add_argument(
            '--reset-for-review', action='store_true',
            help='With --apply, cancel an unrecoverable untouched package and require a new review.',
        )

    def handle(self, *args, **options):
        package_id = str(options['package_id']).strip()
        apply = bool(options['apply'])
        reset = bool(options['reset_for_review'])
        if reset and not apply:
            raise CommandError('--reset-for-review requires --apply.')
        if not OriginationSigningPackage.objects.filter(pk=package_id).exists():
            raise CommandError('Signing package not found.')

        try:
            report = recover_legacy_frozen_package(
                package_id=package_id,
                request_id=f'management:frozen-packet-recovery:{package_id}',
                apply=apply and not reset,
            )
            self.stdout.write(
                f"{'APPLY' if apply else 'DRY-RUN'} package={package_id} "
                f"status={report['status']} hash_matches={report.get('hash_matches', True)} "
                f"manifest_matches={report.get('manifest_matches', True)}"
            )
            if report['recoverable']:
                if reset:
                    raise CommandError('The package is exactly recoverable and must not be reset for review.')
                if not apply:
                    self.stdout.write('Exact reconstruction verified. Re-run with --apply to persist it.')
                elif report['applied']:
                    self.stdout.write(self.style.SUCCESS('Frozen unsigned packet recovered and audited.'))
                return
            if not reset:
                raise CommandError(
                    'Exact reconstruction failed. Do not replace the approved hash. '
                    'Re-run with --apply --reset-for-review to require a new packet approval.'
                )
            application = reset_unrecoverable_package_for_review(
                package_id=package_id,
                request_id=f'management:frozen-packet-reset:{package_id}',
            )
            self.stdout.write(self.style.WARNING(
                f'Package cancelled; application returned to final review at revision {application.revision}.'
            ))
        except OriginationError as exc:
            raise CommandError(str(exc)) from exc
