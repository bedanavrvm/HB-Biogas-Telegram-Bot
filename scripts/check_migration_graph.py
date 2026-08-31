#!/usr/bin/env python3
"""Validate the complete Django migration graph without mutating schema."""

from __future__ import annotations

import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django  # noqa: E402

django.setup()

from django.db import connection  # noqa: E402
from django.db.migrations.loader import MigrationLoader  # noqa: E402


def graph_errors() -> list[str]:
    try:
        loader = MigrationLoader(connection, ignore_no_migrations=True)
        loader.graph.ensure_not_cyclic()
        loader.check_consistent_history(connection)
    except Exception as exc:
        return [f'{type(exc).__name__}: {exc}']
    errors = []
    for app_label, names in sorted(loader.detect_conflicts().items()):
        errors.append(f'{app_label} has conflicting leaf migrations: {", ".join(sorted(names))}')
    return errors


def main() -> int:
    errors = graph_errors()
    if errors:
        print('Migration graph validation failed:')
        for error in errors:
            print(f'  {error}')
        return 1
    loader = MigrationLoader(connection, ignore_no_migrations=True)
    print(
        f'Migration graph validation passed '
        f'({len(loader.disk_migrations)} migration(s), {len(loader.graph.leaf_nodes())} leaf node(s)).'
    )
    return 0


if __name__ == '__main__':
    sys.exit(main())
