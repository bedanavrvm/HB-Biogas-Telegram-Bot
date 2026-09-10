"""Generate deterministic database catalogue documentation."""
from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core.services.database_catalog import database_catalog


class Command(BaseCommand):
    help = 'Generate the customer-data-free database catalogue and Mermaid domain relationship maps.'

    def add_arguments(self, parser):
        parser.add_argument('--output-dir', default='docs/database')
        parser.add_argument('--check', action='store_true')
        parser.add_argument('--live', action='store_true', help='Include PostgreSQL row/storage estimates in JSON output.')

    def handle(self, *args, **options):
        output_dir = Path(options['output_dir'])
        if options['live'] and options['check']:
            raise CommandError('--live cannot be combined with deterministic --check output.')
        if options['live'] and output_dir.as_posix().rstrip('/') == 'docs/database':
            raise CommandError('--live requires a private output directory; do not overwrite the checked-in catalogue.')
        entries = database_catalog(include_usage=True, include_live=options['live'])
        files = self._render(entries)
        mismatches = []
        for relative, content in files.items():
            target = output_dir / relative
            if options['check']:
                if not target.exists() or target.read_text(encoding='utf-8') != content:
                    mismatches.append(str(target))
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding='utf-8')
        if mismatches:
            raise CommandError('Database catalogue is stale: ' + ', '.join(mismatches))
        verb = 'Verified' if options['check'] else 'Generated'
        self.stdout.write(self.style.SUCCESS(f'{verb} {len(entries)} application-table catalogue entries.'))

    def _render(self, entries):
        json_text = json.dumps({'tables': entries}, indent=2, sort_keys=True) + '\n'
        rows = [
            '# Database Catalogue', '',
            'Generated from the current Django model graph. PostgreSQL remains authoritative for live row and storage estimates.', '',
            '| Domain | Table | Django model | Classification | Lifecycle | Purpose |',
            '|---|---|---|---|---|---|',
        ]
        for item in entries:
            purpose = item['purpose'].replace('|', '\\|')
            rows.append(
                f"| {item['domain']} | `{item['table']}` | `{item['django_model']}` | "
                f"{item['classification']} | {item['lifecycle']} | {purpose} |"
            )
        rows.extend(['', '## Relationship and usage details', ''])
        for item in entries:
            rows.extend([
                f"### `{item['table']}`", '',
                f"- Application identity: `{item['django_model']}` in **{item['application_area']}**",
                f"- Source of truth: **{'Yes' if item['source_of_truth'] else 'No'}**",
                f"- Retention: {item['retention']}",
                f"- Parents: {', '.join(f'`{value}`' for value in item['parents']) or 'None'}",
                f"- Children: {', '.join(f'`{value}`' for value in item['children']) or 'None'}",
                f"- Cross-domain parents: {', '.join(f'`{value}`' for value in item['cross_domain_parents']) or 'None'}",
                f"- Direct ORM writers: {', '.join(f'`{value}`' for value in item['direct_orm_writers']) or 'No direct manager mutation found; inspect owning service'}",
                f"- Used by: {', '.join(f'`{value}`' for value in item['used_by']) or 'No direct service/API/command reference found'}",
                '',
            ])
        files = {'catalog.json': json_text, 'catalog.md': '\n'.join(rows)}
        domains = sorted({item['domain'] for item in entries})
        overview = ['flowchart LR'] + [f'  {domain}["{domain.replace("_", " ").title()}"]' for domain in domains]
        cross_edges = set()
        by_label = {item['django_model']: item for item in entries}
        for item in entries:
            for parent in item['cross_domain_parents']:
                if parent in by_label:
                    cross_edges.add((item['domain'], by_label[parent]['domain']))
        overview.extend(f'  {left} --> {right}' for left, right in sorted(cross_edges) if left != right)
        files['overview.mmd'] = '\n'.join(overview) + '\n'
        for domain in domains:
            domain_entries = [item for item in entries if item['domain'] == domain]
            lines = ['erDiagram']
            for item in domain_entries:
                lines.append(f"  {item['table']} {{")
                lines.append('    string id')
                lines.append('  }')
            labels = {item['django_model']: item for item in domain_entries}
            seen = set()
            for item in domain_entries:
                for parent in item['parents']:
                    if parent in labels:
                        edge = (labels[parent]['table'], item['table'])
                        if edge not in seen:
                            lines.append(f'  {edge[0]} ||--o{{ {edge[1]} : contains')
                            seen.add(edge)
            files[f'{domain}.mmd'] = '\n'.join(lines) + '\n'
        return files
