from django.core.management.base import BaseCommand

from core.services.compliance_audit import verify_integrity


class Command(BaseCommand):
    help = 'Verify the immutable compliance-audit hash chain without changing evidence.'

    def add_arguments(self, parser):
        parser.add_argument('--strict', action='store_true', help='Exit non-zero if verification fails.')

    def handle(self, *args, **options):
        report = verify_integrity()
        if report.ok:
            self.stdout.write(self.style.SUCCESS(f'Compliance audit integrity verified: {report.checked} event(s).'))
            return
        self.stderr.write(
            self.style.ERROR(
                f'Compliance audit integrity failed at position {report.first_error_position}: {report.first_error}'
            )
        )
        if options['strict']:
            raise SystemExit(1)
