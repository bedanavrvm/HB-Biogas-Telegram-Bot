"""Bounded expired setup cleanup, preserving native credentials and audit."""
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from staff_auth.models import StaffBrowserSetupGrant


class Command(BaseCommand):
    help = 'Preview one expired initial-setup batch; deletion requires --apply and never removes native credentials.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--batch-size', type=int, default=1000)

    def handle(self, *args, **options):
        size = options['batch_size']
        if not 1 <= size <= 10000:
            raise CommandError('Choose a batch size from 1 to 10000.')
        cutoff = timezone.now()
        keys = list(StaffBrowserSetupGrant.objects.filter(expires_at__lte=cutoff).order_by(
            'expires_at', 'pk',
        ).values_list('pk', flat=True)[:size])
        if not options['apply']:
            self.stdout.write(f'Preview: {len(keys)} expired setup grant(s); no rows deleted.')
            return
        deleted, _ = StaffBrowserSetupGrant.objects.filter(pk__in=keys, expires_at__lte=cutoff).delete()
        self.stdout.write(f'Deleted {deleted} expired setup grant(s); native credentials and audit retained.')
