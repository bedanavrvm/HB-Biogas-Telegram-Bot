from django.core.management.base import BaseCommand

from core.models import ComplianceAuditEvent
from core.services.compliance_audit import verify_integrity


class Command(BaseCommand):
    help = 'Read-only monthly-style sample of sensitive compliance-audit events and integrity evidence.'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=10, help='Maximum sensitive events to sample (default 10).')
        parser.add_argument('--strict', action='store_true', help='Exit non-zero when a sampled record is incomplete.')

    def handle(self, *args, **options):
        report = verify_integrity()
        failures = []
        limit = max(1, min(int(options['limit']), 100))
        rows = ComplianceAuditEvent.objects.filter(sensitive=True).order_by('-chain_position')[:limit]
        for event in rows:
            missing = [
                name for name, value in {
                    'action': event.action,
                    'subject': event.subject_id,
                    'occurred_at': event.occurred_at,
                    'integrity_hash': event.integrity_hash,
                }.items() if not value
            ]
            if event.origin == event.ORIGIN_HUMAN and not (event.actor_id or event.actor_label):
                missing.append('actor')
            if missing:
                failures.append((event.chain_position, ', '.join(missing)))
            self.stdout.write(f'SAMPLE #{event.chain_position} {event.workflow}.{event.action}: ' + ('OK' if not missing else f'MISSING {", ".join(missing)}'))
        self.stdout.write(f'Integrity: {"OK" if report.ok else "FAILED"}; events checked: {report.checked}; sample failures: {len(failures)}.')
        if options['strict'] and (not report.ok or failures):
            raise SystemExit(1)
