#!/usr/bin/env python3
"""Report subsystem coverage and enforce only established, scoped gates."""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_COVERAGE = ROOT / 'coverage.json'
DEFAULT_BASELINE = ROOT / 'scripts' / 'coverage_baseline.json'
DEFAULT_REPORT = ROOT / 'coverage-subsystems.json'


def subsystem(filename: str) -> str:
    path = filename.replace('\\', '/')
    if path.startswith('core/api/'):
        return 'api'
    if path.startswith('core/services/'):
        return 'services'
    if path.startswith('core/management/commands/'):
        return 'management_commands'
    if path == 'core/models.py':
        return 'models'
    if path == 'core/admin.py' or path.startswith('core/admin_'):
        return 'admin'
    return 'other_core'


def aggregate(payload: dict) -> dict:
    groups: dict[str, dict[str, int]] = defaultdict(
        lambda: {'covered_lines': 0, 'num_statements': 0, 'covered_branches': 0, 'num_branches': 0},
    )
    for filename, details in payload.get('files', {}).items():
        if not filename.replace('\\', '/').startswith('core/'):
            continue
        target = groups[subsystem(filename)]
        summary = details['summary']
        for key in target:
            target[key] += int(summary.get(key, 0))
    result = {}
    for name, values in sorted(groups.items()):
        statements = values['num_statements']
        branches = values['num_branches']
        result[name] = {
            **values,
            'line_percent': round(100 * values['covered_lines'] / statements, 2) if statements else 100.0,
            'branch_percent': round(100 * values['covered_branches'] / branches, 2) if branches else 100.0,
        }
    return result


def added_lines(diff_text: str) -> dict[str, set[int]]:
    result: dict[str, set[int]] = defaultdict(set)
    filename = ''
    for line in diff_text.splitlines():
        if line.startswith('+++ b/'):
            filename = line[6:]
            continue
        if not filename.startswith('core/services/') or not filename.endswith('.py'):
            continue
        match = re.match(r'^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@', line)
        if not match:
            continue
        start = int(match.group(1))
        count = int(match.group(2) or 1)
        result[filename].update(range(start, start + count))
    return dict(result)


def changed_service_lines(base_ref: str) -> dict[str, set[int]]:
    if not base_ref:
        return {}
    result = subprocess.run(
        ['git', 'diff', '--unified=0', '--diff-filter=AM', f'{base_ref}...HEAD', '--', 'core/services'],
        cwd=ROOT, check=False, capture_output=True, text=True,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or f'Could not diff against {base_ref}.')
    return added_lines(result.stdout)


def quality_errors(payload: dict, baseline: dict, changed: dict[str, set[int]]) -> list[str]:
    errors = []
    totals = payload.get('totals', {})
    actual_total = float(totals.get('percent_covered', 0))
    minimum_total = float(baseline.get('total_percent', 0))
    if actual_total + 0.005 < minimum_total:
        errors.append(
            f'Total coverage regressed: {actual_total:.2f}% is below baseline {minimum_total:.2f}%.',
        )
    if not payload.get('meta', {}).get('branch_coverage'):
        errors.append('Coverage must be collected with --branch.')
    files = payload.get('files', {})
    for filename, lines in sorted(changed.items()):
        details = files.get(filename)
        if details is None:
            errors.append(f'Changed service is absent from coverage data: {filename}.')
            continue
        branch_origins = {
            int(pair[0]) for pair in details.get('executed_branches', []) + details.get('missing_branches', [])
        }
        missing = {
            int(pair[0]) for pair in details.get('missing_branches', [])
        }
        changed_origins = branch_origins & lines
        uncovered = changed_origins & missing
        if uncovered:
            display = ', '.join(str(value) for value in sorted(uncovered))
            errors.append(f'Changed service branches need coverage: {filename}:{display}.')
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--coverage-json', type=Path, default=DEFAULT_COVERAGE)
    parser.add_argument('--baseline', type=Path, default=DEFAULT_BASELINE)
    parser.add_argument('--report', type=Path, default=DEFAULT_REPORT)
    parser.add_argument('--base-ref', default='')
    parser.add_argument('--write-baseline', action='store_true')
    options = parser.parse_args(argv)
    payload = json.loads(options.coverage_json.read_text(encoding='utf-8'))
    report = {
        'total_percent': round(float(payload['totals']['percent_covered']), 2),
        'subsystems': aggregate(payload),
    }
    options.report.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(f"Total coverage: {report['total_percent']:.2f}%")
    for name, values in report['subsystems'].items():
        print(f"  {name}: lines {values['line_percent']:.2f}% / branches {values['branch_percent']:.2f}%")
    if options.write_baseline:
        options.baseline.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        print(f'Coverage baseline written to {options.baseline.relative_to(ROOT)}.')
        return 0
    baseline = json.loads(options.baseline.read_text(encoding='utf-8'))
    try:
        changed = changed_service_lines(options.base_ref)
    except RuntimeError as exc:
        print(str(exc))
        return 1
    errors = quality_errors(payload, baseline, changed)
    if errors:
        print('\n'.join(errors))
        return 1
    print(f'Coverage quality gates passed ({len(changed)} changed service file(s) checked).')
    return 0


if __name__ == '__main__':
    sys.exit(main())
