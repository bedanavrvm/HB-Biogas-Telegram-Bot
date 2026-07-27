"""Repair legacy Jawabu visit-date text and optionally resync Master Data."""

from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import JawabuFarmerMaster
from core.services.jawabu_validation import normalize_date_text, parse_business_date


class Command(BaseCommand):
    help = (
        'Remove spreadsheet apostrophe/backtick markers from HBG visit dates, '
        'populate the typed date column, and optionally resync the Master Data sheet.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Persist repairs. Without this flag the command only reports changes.',
        )
        parser.add_argument(
            '--sync',
            action='store_true',
            help='After applying repairs, rewrite date cells as true Google Sheets dates.',
        )

    def handle(self, *args, **options):
        apply_changes = bool(options['apply'] or options['sync'])
        sync = bool(options['sync'])
        farmers = list(JawabuFarmerMaster.objects.order_by('pk'))
        candidates = []
        for farmer in farmers:
            normalized_text = normalize_date_text(farmer.sign_date)
            parsed = parse_business_date(normalized_text)
            if normalized_text != (farmer.sign_date or '') or parsed != farmer.hbg_visit_date:
                candidates.append((farmer, normalized_text, parsed))

        self.stdout.write(f'Rows requiring date repair: {len(candidates)}')
        if not candidates and not sync:
            return

        for farmer, normalized_text, parsed in candidates[:20]:
            self.stdout.write(
                f'{farmer.pk}: {farmer.sign_date!r} -> {normalized_text!r}; '
                f'typed={parsed.isoformat() if parsed else "invalid"}'
            )
        if len(candidates) > 20:
            self.stdout.write(f'... and {len(candidates) - 20} more')

        if not apply_changes:
            self.stdout.write(self.style.WARNING('Dry run only. Re-run with --apply to persist repairs.'))
            return

        with transaction.atomic():
            for farmer, normalized_text, parsed in candidates:
                farmer.sign_date = normalized_text
                farmer.hbg_visit_date = parsed
                farmer.save(update_fields=['sign_date', 'hbg_visit_date', 'updated_at'])

        self.stdout.write(self.style.SUCCESS(f'Repaired {len(candidates)} farmer date record(s).'))
        if sync:
            from core.services.jawabu_pipeline import sync_farmer_to_master_sheet

            synced = failed = 0
            # Date cell type cannot be inferred from get_all_values(), so a
            # forced sync intentionally touches every farmer, including rows
            # whose DB text was already clean but whose Sheet cell was still
            # stored as text.
            for farmer in farmers:
                farmer.refresh_from_db()
                if sync_farmer_to_master_sheet(farmer, force_date_columns=True):
                    synced += 1
                else:
                    failed += 1
            self.stdout.write(f'Master Data date cells synced: {synced}; failed: {failed}')
