"""Prepare the reviewed operational Main LAF catalogue for calibration."""

from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from core.services.origination_main_laf_seeds import (
    DEFINITIONS_BY_KEY,
    MainLafSeedError,
    apply_seed,
    preflight_seed,
    selected_definitions,
)


class Command(BaseCommand):
    help = (
        'Dry-run or seed the reviewed PDFs in LAFS/MAIN as independent, '
        'unpublished Main LAF catalogue entries.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--laf-root', required=True,
            help='Directory containing the reviewed PDFs, or its parent containing MAIN/.',
        )
        parser.add_argument(
            '--laf', default='all', choices=['all', *DEFINITIONS_BY_KEY],
            help='Seed one reviewed Main LAF or all six.',
        )
        parser.add_argument(
            '--actor', required=True,
            help='Active Django Superuser username used for audit attribution.',
        )
        parser.add_argument(
            '--apply', action='store_true',
            help='Create canonical fields, ready templates and exact product eligibilities.',
        )

    def handle(self, *args, **options):
        actor = get_user_model().objects.filter(
            username=options['actor'], is_active=True, is_superuser=True,
        ).first()
        if not actor:
            raise CommandError('--actor must identify an active Django Superuser.')
        definitions = selected_definitions(options['laf'])
        laf_root = Path(options['laf_root'])
        plans = []
        try:
            # Preflight the complete selection before the first database or Drive write.
            plans = [preflight_seed(item, laf_root=laf_root) for item in definitions]
        except MainLafSeedError as exc:
            raise CommandError(str(exc)) from exc

        if not options['apply']:
            for plan in plans:
                definition = plan['definition']
                product = definition.product_code or 'unassigned'
                reusable = next((
                    item for item in plan['candidates']
                    if item.status in {item.STATUS_READY, item.STATUS_ACTIVE}
                ), None)
                action = f'inspect/reuse v{reusable.version}' if reusable else 'create v1'
                self.stdout.write(
                    f'Dry run: {definition.name}: {action}; {len(definition.fields)} reviewed '
                    f'fields, {len(definition.signers)} signer roles, product {product}, '
                    f'{definition.page_count} pages, {definition.sha256[:12]}....'
                )
                for note in definition.review_notes:
                    self.stdout.write(f'  Review note: {note}')
            self.stdout.write('No database records or Drive files were changed.')
            return

        if not str(getattr(settings, 'GOOGLE_DRIVE_MEDIA_FOLDER_ID', '') or '').strip():
            raise CommandError('GOOGLE_DRIVE_MEDIA_FOLDER_ID must be configured before --apply.')
        results = []
        try:
            for definition in definitions:
                results.append(apply_seed(definition, laf_root=laf_root, actor=actor))
        except MainLafSeedError as exc:
            raise CommandError(str(exc)) from exc
        for result in results:
            template = result['template']
            product = result['definition'].product_code or 'no product yet'
            self.stdout.write(self.style.SUCCESS(
                f'Prepared {template.name} v{template.version} for {product} with '
                f'{len(result["fields"])} canonical fields. It remains unpublished; '
                'complete visual alignment and preview review in Admin.'
            ))
