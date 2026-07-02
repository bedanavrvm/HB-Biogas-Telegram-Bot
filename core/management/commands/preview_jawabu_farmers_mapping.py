"""Create review CSVs for mapping Jawabu Farmers exports to master data."""
import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core.services.jawabu_master import (
    MASTER_PREVIEW_HEADERS,
    build_cleaned_master_preview,
    mapping_review_rows,
)


class Command(BaseCommand):
    help = 'Generate reviewable mapping and cleaned-preview CSVs from Jawabu Farmers exports.'

    def add_arguments(self, parser):
        parser.add_argument(
            'csv_paths',
            nargs='+',
            help='One or more Jawabu Farmers CSV files.',
        )
        parser.add_argument(
            '--output-dir',
            default='artifacts/jawabu_master_preview',
            help='Directory for generated review CSVs.',
        )
        parser.add_argument(
            '--encoding',
            default='utf-8-sig',
            help='CSV file encoding. Defaults to utf-8-sig.',
        )

    def handle(self, *args, **options):
        output_dir = Path(options['output_dir'])
        output_dir.mkdir(parents=True, exist_ok=True)
        csv_paths = [Path(path) for path in options['csv_paths']]
        missing = [str(path) for path in csv_paths if not path.exists() or not path.is_file()]
        if missing:
            raise CommandError('CSV file(s) not found: ' + ', '.join(missing))

        mapping_path = output_dir / 'jawabu_farmers_to_master_mapping_review.csv'
        with mapping_path.open('w', encoding='utf-8-sig', newline='') as f:
            fieldnames = ['source_column', 'master_column', 'field', 'confidence', 'notes']
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(mapping_review_rows())

        preview_path = output_dir / 'jawabu_farmers_cleaned_master_preview.csv'
        stats_rows = []
        with preview_path.open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=MASTER_PREVIEW_HEADERS)
            writer.writeheader()
            for path in csv_paths:
                with path.open('r', encoding=options['encoding'], newline='') as csv_file:
                    rows, stats = build_cleaned_master_preview(
                        csv_file,
                        source_name=path.name,
                    )
                writer.writerows(rows)
                stats_rows.append({
                    'source_file': path.name,
                    'total_rows': stats['total_rows'],
                    'preview_rows': len(rows),
                    'review_needed': stats['review_needed'],
                    'skipped_blank': stats['skipped_blank'],
                    'detected_headers': ' | '.join(stats['headers']),
                    'detected_mapping': '; '.join(
                        f'{field}={header}'
                        for field, header in sorted(stats['header_map'].items())
                    ),
                })

        stats_path = output_dir / 'jawabu_farmers_import_preview_stats.csv'
        with stats_path.open('w', encoding='utf-8-sig', newline='') as f:
            fieldnames = [
                'source_file', 'total_rows', 'preview_rows', 'review_needed',
                'skipped_blank', 'detected_headers', 'detected_mapping',
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(stats_rows)

        self.stdout.write(self.style.SUCCESS('Generated Jawabu Farmers review files'))
        self.stdout.write(f'Mapping review: {mapping_path}')
        self.stdout.write(f'Cleaned preview: {preview_path}')
        self.stdout.write(f'Import stats: {stats_path}')