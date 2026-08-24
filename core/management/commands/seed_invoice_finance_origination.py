"""Prepare the reviewed Invoice Finance origination contract for calibration."""

from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from core.services.invoice_finance_origination_seed import (
    FIELD_SPECS,
    SIGNER_RULES,
    InvoiceFinanceSeedError,
    apply_seed,
    preflight,
)


class Command(BaseCommand):
    help = (
        'Dry-run or apply the reviewed Invoice Finance canonical fields, form schema, '
        'signer rules, and draft primary LAF. PDF coordinates are never auto-published.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--product-code', default='invoice_finance')
        parser.add_argument('--pdf', default=str(Path('LAFS') / 'INVOICE FINANCE.pdf'))
        parser.add_argument('--actor', required=True, help='Active Django Superuser username for audit events.')
        parser.add_argument('--apply', action='store_true', help='Write the reviewed draft and upload its PDF.')

    def handle(self, *args, **options):
        actor = get_user_model().objects.filter(
            username=options['actor'], is_active=True, is_superuser=True,
        ).first()
        if not actor:
            raise CommandError('--actor must identify an active Django Superuser.')
        try:
            plan = preflight(product_code=options['product_code'], pdf_path=options['pdf'])
            if not options['apply']:
                action = (
                    f"replace draft Origination version {plan['draft'].version}"
                    if plan['draft'] else
                    f"create a successor to published Origination version {plan['published'].version}"
                    if plan['published'] else 'create Origination version 1'
                )
                self.stdout.write(
                    f"Dry run: {plan['product'].name} / commercial terms v{plan['product_version'].version}; "
                    f"would {action}, govern {len(FIELD_SPECS)} fields and {len(SIGNER_RULES)} signers, "
                    f"then upload {plan['page_count']}-page PDF {plan['pdf_sha256'][:12]}…."
                )
                self.stdout.write(
                    'The PDF ATTACH section is intentionally ignored. No document requirements or '
                    'supporting-document assignments will be created. Re-run with --apply to write.'
                )
                return
            if not str(getattr(settings, 'GOOGLE_DRIVE_MEDIA_FOLDER_ID', '') or '').strip():
                raise CommandError('GOOGLE_DRIVE_MEDIA_FOLDER_ID must be configured before --apply.')
            result = apply_seed(
                product_code=options['product_code'], pdf_path=options['pdf'], actor=actor,
            )
        except InvoiceFinanceSeedError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(
            f"Prepared {result['definition']} with {len(result['fields'])} canonical fields and "
            f"{result['template']}. Open its alignment builder, place every required field and signer "
            'slot, preview the filled sample, then publish the product.'
        ))
