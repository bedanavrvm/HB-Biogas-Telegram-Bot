"""Deliberate infrastructure-only browser admission administration."""
import json

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError

from staff_auth.lifecycle import ACTIONS, apply_change, preview_change


class Command(BaseCommand):
    help = 'Preview browser-only admission/revocation. Writes require --apply and reviewed actor/revision/request/reason.'

    def add_arguments(self, parser):
        parser.add_argument('action', choices=ACTIONS)
        parser.add_argument('--actor', type=int, required=True)
        parser.add_argument('--user', type=int, required=True)
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--expected-revision', type=int)
        parser.add_argument('--request-key')
        parser.add_argument('--reason')
        parser.add_argument('--verification-reference', default='')

    def handle(self, *args, **options):
        actor = get_user_model().objects.filter(pk=options['actor']).first()
        try:
            if options['apply']:
                result = apply_change(
                    actor=actor, target_user_id=options['user'], action=options['action'],
                    expected_revision=options['expected_revision'], request_key=options['request_key'],
                    reason=options['reason'], verification_reference=options['verification_reference'],
                )
            else:
                result = preview_change(actor=actor, target_user_id=options['user'], action=options['action'])
                result['dry_run'] = True
        except (PermissionDenied, ValidationError) as exc:
            raise CommandError('; '.join(getattr(exc, 'messages', [str(exc)]))) from None
        self.stdout.write(json.dumps(result, sort_keys=True))
