"""Infrastructure-only setup preparation; never export or dispatch a proof."""
import json

from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured, PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError

from staff_auth.initial_setup import prepare_setup, preview_setup


class Command(BaseCommand):
    help = 'Preview initial setup of the exact existing admitted account; --apply prepares encrypted proof without dispatch/export.'

    def add_arguments(self, parser):
        parser.add_argument('--actor', required=True, type=int)
        parser.add_argument('--user', required=True, type=int)
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--expected-revision', type=int)
        parser.add_argument('--snapshot-fingerprint')
        parser.add_argument('--request-key')
        parser.add_argument('--reason')

    def handle(self, *args, **options):
        actor = get_user_model().objects.filter(pk=options['actor']).first()
        try:
            if options['apply']:
                result = prepare_setup(
                    actor=actor, target_user_id=options['user'], expected_revision=options['expected_revision'],
                    snapshot_fingerprint=options['snapshot_fingerprint'], request_key=options['request_key'], reason=options['reason'],
                )
            else:
                result = {**preview_setup(actor=actor, target_user_id=options['user']), 'dry_run': True}
        except (PermissionDenied, ValidationError) as exc:
            raise CommandError('; '.join(getattr(exc, 'messages', [str(exc)]))) from None
        except ImproperlyConfigured:
            raise CommandError('Dedicated setup-proof encryption is unavailable; no preparation was committed.') from None
        self.stdout.write(json.dumps(result, sort_keys=True))
