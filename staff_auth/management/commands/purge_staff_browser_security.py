"""Bounded expired-only maintenance; no global security-state clear."""
from django.core.management.base import BaseCommand, CommandError
from django.db.models.functions import Now

from staff_auth.models import StaffBrowserSecurityState


class Command(BaseCommand):
    help = 'Preview expired native browser security rows; --apply removes one bounded batch.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--batch-size', type=int, default=1000)

    def handle(self, *args, **options):
        size = options['batch_size']
        if not 1 <= size <= 10000:
            raise CommandError('Choose a batch size between 1 and 10000.')
        expired = StaffBrowserSecurityState.objects.filter(expires_at__lte=Now())
        keys = list(expired.order_by('expires_at').values_list('pk', flat=True)[:size])
        if options['apply']:
            # Recheck expiry after selection: a competing renewal must survive.
            count = expired.filter(pk__in=keys).delete()[0]
            self.stdout.write(f'Removed {count} expired security rows. Live state preserved.')
        else:
            self.stdout.write(f'Preview: {len(keys)} expired rows in this batch. No changes made.')
