#!/usr/bin/env python3
"""Run pip-audit with narrow, expiring, reviewed exceptions."""

from __future__ import annotations

from datetime import date
import subprocess
import sys


AUDIT_EXCEPTIONS = (
    {
        'id': 'PYSEC-2026-3412',
        'package': 'weasyprint',
        'expires': date(2026, 9, 30),
        'reason': 'No fixed WeasyPrint release is published; PDF input remains governed and server-generated.',
    },
)


def exception_errors(today: date | None = None) -> list[str]:
    current = today or date.today()
    errors = []
    seen = set()
    for item in AUDIT_EXCEPTIONS:
        advisory_id = str(item['id'])
        if advisory_id in seen:
            errors.append(f'Duplicate dependency-audit exception: {advisory_id}.')
        seen.add(advisory_id)
        if item['expires'] < current:
            errors.append(
                f'Dependency-audit exception {advisory_id} expired on {item["expires"].isoformat()}.',
            )
        if not str(item['reason']).strip() or not str(item['package']).strip():
            errors.append(f'Dependency-audit exception {advisory_id} lacks governance metadata.')
    return errors


def main() -> int:
    errors = exception_errors()
    if errors:
        print('\n'.join(errors))
        return 1
    command = [sys.executable, '-m', 'pip_audit', '--local', '--progress-spinner=off']
    for item in AUDIT_EXCEPTIONS:
        command.extend(['--ignore-vuln', str(item['id'])])
        print(
            f"Temporary audit exception {item['id']} ({item['package']}) "
            f"expires {item['expires'].isoformat()}: {item['reason']}",
        )
    return subprocess.run(command, check=False).returncode


if __name__ == '__main__':
    sys.exit(main())
