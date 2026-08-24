"""Prepare the reviewed reusable generic Jawabu LAF for visual calibration."""

from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from core.services.generic_jawabu_laf_seed import (
    FIELD_SPECS,
    SIGNER_RULES,
    GenericJawabuLafSeedError,
    apply_seed,
    preflight,
)


class Command(BaseCommand):
    help = (
        'Dry-run or seed the reviewed generic Jawabu LAF as one reusable primary '
        'template family. Products are never attached automatically.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--pdf', default=str(Path('LAFS') / 'Jawabu LAF (2).pdf'))
        parser.add_argument('--actor', required=True, help='Active Django Superuser username for audit events.')
        parser.add_argument('--apply', action='store_true', help='Write canonical fields and upload the reusable PDF.')

    def handle(self, *args, **options):
        actor = get_user_model().objects.filter(
            username=options['actor'], is_active=True, is_superuser=True,
        ).first()
        if not actor:
            raise CommandError('--actor must identify an active Django Superuser.')
        try:
            plan = preflight(pdf_path=options['pdf'])
            if not options['apply']:
                state = (
                    f"reuse template v{plan['existing'].version}"
                    if plan['existing'] else 'create reusable template v1'
                )
                self.stdout.write(
                    f"Dry run: would govern {len(FIELD_SPECS)} input fields and "
                    f"{len(SIGNER_RULES)} signer roles, {state}, and upload the "
                    f"{plan['page_count']}-page PDF {plan['pdf_sha256'][:12]}...."
                )
                self.stdout.write(
                    'No product will be attached or overwritten. The two Net income fields '
                    'remain independent manual values; sketches and Commissioner for Oaths are excluded.'
                )
                return
            if not str(getattr(settings, 'GOOGLE_DRIVE_MEDIA_FOLDER_ID', '') or '').strip():
                raise CommandError('GOOGLE_DRIVE_MEDIA_FOLDER_ID must be configured before --apply.')
            result = apply_seed(pdf_path=options['pdf'], actor=actor)
        except GenericJawabuLafSeedError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(
            f"Prepared {result['template']} with {len(result['fields'])} canonical fields. "
            'Open the alignment builder, place the required fields and signer slots, publish '
            'the reusable template, then explicitly assign it to each draft product that uses it.'
        ))
