"""Import Jawabu Farmers CSV into internal master data."""
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core.services.jawabu_master import import_jawabu_farmers_csv


class Command(BaseCommand):
    help = 'Import and clean a Jawabu Farmers CSV into the internal master data table.'

    def add_arguments(self, parser):
        parser.add_argument('csv_path', help='Path to the Jawabu Farmers CSV file.')
        parser.add_argument(
            '--encoding',
            default='utf-8-sig',
            help='CSV file encoding. Defaults to utf-8-sig.',
        )
        parser.add_argument(
            '--source-name',
            default='',
            help='Optional source label stored on imported records.',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Parse and validate the CSV without saving records.',
        )

    def handle(self, *args, **options):
        csv_path = Path(options['csv_path'])
        if not csv_path.exists() or not csv_path.is_file():
            raise CommandError(f'CSV file not found: {csv_path}')

        source_name = options['source_name'] or csv_path.name
        try:
            with csv_path.open('r', encoding=options['encoding'], newline='') as csv_file:
                result = import_jawabu_farmers_csv(
                    csv_file,
                    source_name=source_name,
                    dry_run=options['dry_run'],
                )
        except UnicodeDecodeError as exc:
            raise CommandError(
                f'Could not read {csv_path} with encoding {options["encoding"]}: {exc}'
            ) from exc

        action = 'Validated' if options['dry_run'] else 'Imported'
        self.stdout.write(self.style.SUCCESS(f'{action} Jawabu Farmers CSV'))
        self.stdout.write(f'Total data rows: {result.total_rows}')
        self.stdout.write(f'Created: {result.created}')
        self.stdout.write(f'Updated: {result.updated}')
        self.stdout.write(f'Review needed: {result.review_needed}')
        self.stdout.write(f'Skipped blank rows: {result.skipped_blank}')
        if result.errors:
            self.stdout.write(self.style.WARNING(f'Errors: {len(result.errors)}'))
            for error in result.errors[:10]:
                self.stdout.write(f'- {error}')