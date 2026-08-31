"""Fail CI when a direct ORM mutation appears in an API view.

The checked-in baseline supports an explicitly reviewed migration window, but
is intentionally empty now that the remaining writes have service owners.
"""

from __future__ import annotations

import argparse
import ast
from collections import Counter
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / 'scripts' / 'architecture_boundaries_baseline.json'
MUTATIONS = {'create', 'update', 'update_or_create', 'get_or_create', 'bulk_create', 'bulk_update', 'delete'}


class ApiMutationVisitor(ast.NodeVisitor):
    def __init__(self, relative_path: str):
        self.relative_path = relative_path
        self.scope: list[str] = []
        self.records: list[tuple[str, str, str, str]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr in MUTATIONS:
            manager = func.value
            if isinstance(manager, ast.Attribute) and manager.attr == 'objects':
                target = ast.unparse(manager.value) if hasattr(ast, 'unparse') else '<model>'
                self.records.append((
                    self.relative_path,
                    '.'.join(self.scope) or '<module>',
                    func.attr,
                    target,
                ))
        self.generic_visit(node)


def collect() -> Counter:
    findings: Counter = Counter()
    for path in sorted((ROOT / 'core' / 'api').rglob('*.py')):
        visitor = ApiMutationVisitor(path.relative_to(ROOT).as_posix())
        visitor.visit(ast.parse(path.read_text(encoding='utf-8'), filename=str(path)))
        findings.update('|'.join(record) for record in visitor.records)
    return findings


def load_baseline() -> Counter:
    if not BASELINE.exists():
        return Counter()
    data = json.loads(BASELINE.read_text(encoding='utf-8'))
    return Counter({str(key): int(value) for key, value in data.get('findings', {}).items()})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--write-baseline', action='store_true')
    options = parser.parse_args()
    current = collect()
    if options.write_baseline:
        BASELINE.write_text(
            json.dumps({'findings': dict(sorted(current.items()))}, indent=2) + '\n',
            encoding='utf-8',
        )
        print(f'Wrote {len(current)} architecture-boundary baseline entries.')
        return 0
    baseline = load_baseline()
    added = current - baseline
    if added:
        print('New direct ORM mutation(s) in core/api. Move the business write to a service or explicitly revise the reviewed baseline:')
        for record, count in sorted(added.items()):
            print(f'  {record} x{count}')
        return 1
    print(f'Architecture boundaries passed ({sum(current.values())} legacy API mutation(s) baselineed).')
    return 0


if __name__ == '__main__':
    sys.exit(main())
