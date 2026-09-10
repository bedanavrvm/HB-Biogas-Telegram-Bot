"""Enforce database documentation and naming for models added after catalogue adoption."""
from __future__ import annotations

import ast
import os
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
sys.path.insert(0, str(ROOT))

import django  # noqa: E402

django.setup()

from django.apps import apps  # noqa: E402
from core.services.database_catalog import MODEL_OVERRIDES  # noqa: E402


ADOPTION_MIGRATION = 168
REQUIRED_METADATA = {'domain', 'purpose', 'classification', 'source_of_truth', 'lifecycle', 'retention'}
ALLOWED_LIFECYCLES = {'active', 'temporary', 'compatibility', 'archived', 'deprecated'}
NAME_PATTERN = re.compile(r'^[a-z][a-z0-9]*_[a-z0-9_]+$')
BOUNDED_DOMAIN_APPS = {
    'origination', 'tat', 'complaints', 'jawabu', 'catalog', 'access',
    'integration', 'audit', 'platform', 'spin', 'order_approval',
}


def newly_created_core_models() -> set[str]:
    names = set()
    migration_dir = ROOT / 'core' / 'migrations'
    for path in migration_dir.glob('[0-9][0-9][0-9][0-9]_*.py'):
        try:
            number = int(path.name[:4])
        except ValueError:
            continue
        if number <= ADOPTION_MIGRATION:
            continue
        tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr != 'CreateModel':
                continue
            for keyword in node.keywords:
                if keyword.arg == 'name' and isinstance(keyword.value, ast.Constant):
                    names.add(str(keyword.value.value))
    return names


def errors() -> list[str]:
    findings = []
    for model_name in sorted(newly_created_core_models()):
        findings.append(
            f'core.{model_name}: new business models must live in their bounded-domain Django app, not legacy core'
        )
    governed_models = [
        model for model in apps.get_models()
        if model._meta.app_label in BOUNDED_DOMAIN_APPS
    ]
    for model in sorted(governed_models, key=lambda item: item._meta.label):
        label = model._meta.label
        metadata = MODEL_OVERRIDES.get(label)
        if not metadata:
            findings.append(f'{label}: add an explicit MODEL_OVERRIDES database-catalogue entry')
            continue
        missing = sorted(REQUIRED_METADATA - set(metadata))
        if missing:
            findings.append(f'{label}: missing catalogue metadata: {", ".join(missing)}')
        domain = str(metadata.get('domain') or '')
        table = model._meta.db_table
        if table.startswith('core_') or not NAME_PATTERN.fullmatch(table) or not table.startswith(f'{domain}_'):
            findings.append(f'{label}: db_table must use the predictable <domain>_<entity>_<role> convention')
        if not str(model._meta.db_table_comment or '').strip():
            findings.append(f'{label}: add Meta.db_table_comment so PostgreSQL explains the table in place')
        if metadata.get('lifecycle') not in ALLOWED_LIFECYCLES:
            findings.append(f'{label}: lifecycle must be one of {sorted(ALLOWED_LIFECYCLES)}')
        justifications = metadata.get('index_justifications') or {}
        for index in model._meta.indexes:
            if not index.name:
                findings.append(f'{label}: every explicit index must have a stable name')
            elif not str(justifications.get(index.name) or '').strip():
                findings.append(f'{label}: add an index justification for {index.name}')
        for field in model._meta.concrete_fields:
            if not str(getattr(field, 'db_comment', '') or '').strip():
                findings.append(f'{label}.{field.name}: add db_comment for PostgreSQL column discovery')
            if not field.is_relation or not field.related_model:
                continue
            related_name = getattr(field.remote_field, 'related_name', None)
            if not related_name:
                findings.append(f'{label}.{field.name}: define an intentional related_name for relationship discovery')
    return findings


def main() -> int:
    findings = errors()
    if findings:
        print('Database governance check failed:')
        for finding in findings:
            print(f'  {finding}')
        return 1
    print('Database governance passed: no new legacy-core models and all bounded-domain models are documented.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
