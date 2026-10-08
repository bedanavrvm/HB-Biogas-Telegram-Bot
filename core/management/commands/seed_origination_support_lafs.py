"""Prepare reviewed supporting PDFs using the existing dry-run seed mechanism."""
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from origination.services.origination_main_laf_seeds import apply_seed, preflight_seed, MainLafSeedError
from origination.services.origination_support_laf_seeds import DEFINITIONS, DEFINITIONS_BY_KEY


class Command(BaseCommand):
    help = 'Inspect or prepare unpublished supporting documents. Product eligibility stays empty.'

    def add_arguments(self, parser):
        parser.add_argument('--laf-root', required=True)
        parser.add_argument('--laf', choices=['all', *DEFINITIONS_BY_KEY], default='all')
        parser.add_argument('--actor', required=True)
        parser.add_argument('--apply', action='store_true')

    def handle(self, *args, **options):
        actor = get_user_model().objects.filter(username=options['actor'], is_active=True, is_superuser=True).first()
        if not actor:
            raise CommandError('--actor must identify an active Django Superuser.')
        definitions = DEFINITIONS if options['laf'] == 'all' else (DEFINITIONS_BY_KEY[options['laf']],)
        try:
            plans = [preflight_seed(item, laf_root=options['laf_root']) for item in definitions]
        except MainLafSeedError as exc:
            raise CommandError(str(exc)) from exc
        if not options['apply']:
            for plan in plans:
                definition = plan['definition']
                self.stdout.write(f'Dry run: {definition.name}: {len(definition.fields)} fields; {definition.page_count} pages; no product assignments.')
                for note in definition.review_notes:
                    self.stdout.write('  Review: ' + note)
            self.stdout.write('No database records or Drive files were changed.')
            return
        if not str(getattr(settings, 'GOOGLE_DRIVE_MEDIA_FOLDER_ID', '') or '').strip():
            raise CommandError('GOOGLE_DRIVE_MEDIA_FOLDER_ID must be configured before --apply.')
        try:
            for definition in definitions:
                result = apply_seed(definition, laf_root=options['laf_root'], actor=actor, shared_values=True)
                self.stdout.write(f'Prepared {result["template"].name}; review fields, signers and placement. Not published or assigned to products.')
        except MainLafSeedError as exc:
            raise CommandError(str(exc)) from exc
