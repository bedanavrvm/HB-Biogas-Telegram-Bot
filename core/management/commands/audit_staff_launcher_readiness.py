"""Read-only audit of Telegram staff onboarding against runtime authorization."""
from __future__ import annotations

import json

from django.core.management.base import BaseCommand

from core.models import StaffTelegramOnboarding
from core.services.staff_access_readiness import onboarding_readiness


class Command(BaseCommand):
    help = (
        'Report Telegram staff onboardings whose configured launchers do not pass '
        'the exact protected-endpoint authorization decision. This command never repairs access.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--json', action='store_true', dest='as_json')
        parser.add_argument('--include-pending-identity', action='store_true')

    def handle(self, *args, **options):
        records = []
        queryset = StaffTelegramOnboarding.objects.select_related(
            'user', 'user__staff_profile', 'plan',
        ).prefetch_related('group_invitations__group_configuration').order_by('created_at')
        for onboarding in queryset:
            result = onboarding_readiness(
                onboarding,
                require_identity=not options['include_pending_identity'],
            )
            records.append({
                'onboarding_id': str(onboarding.pk),
                'user_id': onboarding.user_id,
                'username': onboarding.user.get_username(),
                'onboarding_status': onboarding.status,
                'ready': result['ready'],
                'reason_code': result['reason_code'],
                'message': result['message'],
                'launchers': result['rows'],
            })
        failed = [record for record in records if not record['ready']]
        payload = {
            'mode': 'read_only',
            'checked': len(records),
            'ready': len(records) - len(failed),
            'failed': len(failed),
            'records': records,
        }
        if options['as_json']:
            self.stdout.write(json.dumps(payload, sort_keys=True, default=str))
        else:
            self.stdout.write(
                f"Checked {payload['checked']} onboarding(s): "
                f"{payload['ready']} ready, {payload['failed']} failed. No data changed."
            )
            for record in failed:
                self.stdout.write(
                    f"- {record['username']} [{record['onboarding_id']}]: "
                    f"{record['reason_code']} - {record['message']}"
                )
