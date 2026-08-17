from django.core.management.base import BaseCommand

from core.services.access_control_reporting import parity_report, unused_capabilities


class Command(BaseCommand):
    help = 'Report access-control policy gaps and capabilities unused within a period; never changes data.'

    def add_arguments(self, parser):
        parser.add_argument('--unused-days', type=int, default=90)
        parser.add_argument('--strict', action='store_true')

    def handle(self, *args, **options):
        parity = parity_report()
        unused = unused_capabilities(options['unused_days'])
        self.stdout.write(f"Missing policy rows: {len(parity['missing_policy_rows'])}")
        for item in parity['missing_policy_rows']:
            self.stdout.write(f"  MISSING {item['workflow']}/{item['role']}/{item['capability_key']}")
        self.stdout.write(f"Differences from deployment baseline: {len(parity['baseline_drift'])}")
        for item in parity['baseline_drift']:
            self.stdout.write(f"  BASELINE {item['workflow']}/{item['role']}/{item['capability_key']}: {item['baseline']} -> {item['current']}")
        for key in (
            'invalid_grants', 'inactive_user_grants', 'invalid_policy_rows',
            'effect_mismatches', 'dependency_violations', 'redundant_grants',
            'emergency_on_inactive_users', 'pending_self_conflicts',
        ):
            self.stdout.write(f"{key.replace('_', ' ').title()}: {len(parity[key])}")
            for item in parity[key]:
                self.stdout.write(f"  {key.upper()} {item}")
        self.stdout.write(f"Unused capabilities in {options['unused_days']} days: {len(unused)}")
        for item in unused:
            self.stdout.write(f"  UNUSED {item['workflow']}/{item['capability_key']} ({item['label']})")
        if options['strict'] and not parity['ok']:
            raise SystemExit(1)
