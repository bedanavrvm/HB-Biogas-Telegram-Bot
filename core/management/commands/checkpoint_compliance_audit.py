from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_date

from core.services.compliance_audit import (
    ComplianceAuditError,
    create_daily_checkpoint,
    deliver_checkpoint,
    verify_integrity,
)


class Command(BaseCommand):
    help = 'Preview or create a daily compliance-audit checkpoint; delivery is always explicit.'

    def add_arguments(self, parser):
        parser.add_argument('--date', help='Checkpoint date in YYYY-MM-DD; defaults to today in Nairobi.')
        parser.add_argument('--apply', action='store_true', help='Persist the local checkpoint record.')
        parser.add_argument('--deliver', action='store_true', help='Deliver an existing/new checkpoint only when approved email config is enabled.')

    def handle(self, *args, **options):
        checkpoint_date = parse_date(options['date']) if options.get('date') else None
        if options.get('date') and checkpoint_date is None:
            raise CommandError('--date must be YYYY-MM-DD.')
        if options['deliver'] and not options['apply']:
            raise CommandError('--deliver requires --apply so the exact checkpoint is retained first.')
        report = verify_integrity()
        if not report.ok:
            raise CommandError(f'Integrity failed at {report.first_error_position}: {report.first_error}')
        if not options['apply']:
            self.stdout.write(f'Dry run: chain is valid across {report.checked} event(s); no checkpoint was created.')
            return
        checkpoint, created = create_daily_checkpoint(checkpoint_date=checkpoint_date)
        self.stdout.write(
            f"{'Created' if created else 'Reused'} checkpoint {checkpoint.checkpoint_date}: "
            f'position={checkpoint.chain_position}, status={checkpoint.status}.'
        )
        if options['deliver']:
            try:
                checkpoint = deliver_checkpoint(checkpoint)
            except ComplianceAuditError as exc:
                raise CommandError(str(exc)) from exc
            self.stdout.write(self.style.SUCCESS(f'Checkpoint delivered at {checkpoint.delivered_at}.'))
