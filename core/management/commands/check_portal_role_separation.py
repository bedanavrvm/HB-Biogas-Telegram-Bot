"""Report Portal grants affected by the Head of Rural role split."""

from django.core.management.base import BaseCommand

from core.models import AccessGrant


class Command(BaseCommand):
    help = 'Report active Jawabu Portal Head of Rural and Operations Administrator grants.'

    def handle(self, *args, **options):
        head_of_rural = list(
            AccessGrant.objects.filter(
                workflow='jawabu_portal', role='BUSINESS_ADMIN', active=True,
            ).select_related('user').order_by('user__username', 'branch', 'product')
        )
        operations = list(
            AccessGrant.objects.filter(
                workflow='jawabu_portal', role='OPERATIONS_ADMIN', active=True,
            ).select_related('user').order_by('user__username', 'branch', 'product')
        )
        self.stdout.write('Portal role-separation impact report')
        self.stdout.write(f'Active Head of Rural grants: {len(head_of_rural)}')
        for grant in head_of_rural:
            scope = ', '.join(filter(None, [grant.branch, grant.product])) or 'all permitted scope'
            self.stdout.write(f'  HEAD_OF_RURAL {grant.user.get_username()} — {scope}')
        self.stdout.write(f'Active Operations Administrator grants: {len(operations)}')
        for grant in operations:
            scope = ', '.join(filter(None, [grant.branch, grant.product])) or 'all permitted scope'
            self.stdout.write(f'  OPERATIONS_ADMIN {grant.user.get_username()} — {scope}')
        self.stdout.write(
            self.style.WARNING(
                'Head of Rural grants retain approval authority only after core.0098. '
                'Create Operations Administrator grants through the maker-checker workflow for staff who need operational processing.'
            )
        )
