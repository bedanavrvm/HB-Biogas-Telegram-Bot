"""Bounded expiry-only maintenance; never clear live authentication state."""
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from staff_auth.models import StaffTOTPReplayState


class Command(BaseCommand):
    help = 'Preview up to one batch of expired browser TOTP claims. Deletion requires --apply.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--batch-size', type=int, default=1000)

    def handle(self, *args, **options):
        size = options['batch_size']
        if not 1 <= size <= 10000:
            raise CommandError('Choose a batch size from 1 to 10000.')
        cutoff = timezone.now()
        keys = list(StaffTOTPReplayState.objects.filter(expires_at__lte=cutoff).order_by(
            'expires_at', 'key_digest',
        ).values_list('key_digest', flat=True)[:size])
        if not options['apply']:
            self.stdout.write(f'Preview: {len(keys)} expired claim(s) selected; no rows deleted.')
            return
        # A claim can be renewed after selection. Recheck expiry on DELETE.
        deleted, _ = StaffTOTPReplayState.objects.filter(pk__in=keys, expires_at__lte=cutoff).delete()
        self.stdout.write(f'Deleted {deleted} expired claim(s); live claims retained.')
