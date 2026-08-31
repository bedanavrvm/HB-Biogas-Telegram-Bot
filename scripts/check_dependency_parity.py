#!/usr/bin/env python3
"""Check pip/Poetry parity and direct coverage of runtime imports."""

from __future__ import annotations

import ast
from pathlib import Path
import re
import sys
import tomllib


ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / 'requirements.txt'
PYPROJECT = ROOT / 'pyproject.toml'
IMPORT_TO_PACKAGE = {
    'PIL': 'pillow',
    'africastalking': 'africastalking',
    'dateutil': 'python-dateutil',
    'decouple': 'python-decouple',
    'dj_database_url': 'dj-database-url',
    'django': 'django',
    'django_htmx': 'django-htmx',
    'google': 'google-auth',
    'google_auth_httplib2': 'google-auth-httplib2',
    'googleapiclient': 'google-api-python-client',
    'gspread': 'gspread',
    'health_check': 'django-health-check',
    'httplib2': 'httplib2',
    'openpyxl': 'openpyxl',
    'pypdf': 'pypdf',
    'pypdfium2': 'pypdfium2',
    'reportlab': 'reportlab',
    'requests': 'requests',
    'rest_framework': 'djangorestframework',
    'sentry_sdk': 'sentry-sdk',
    'unfold': 'django-unfold',
    'weasyprint': 'weasyprint',
    'whitenoise': 'whitenoise',
}


def normalize(name: str) -> str:
    return re.sub(r'[-_.]+', '-', name).lower()


def requirement_packages(path: Path = REQUIREMENTS) -> set[str]:
    return set(requirement_contracts(path))


def requirement_contracts(path: Path = REQUIREMENTS) -> dict[str, tuple[str, tuple[str, ...]]]:
    contracts = {}
    for raw_line in path.read_text(encoding='utf-8').splitlines():
        line = raw_line.split('#', 1)[0].strip()
        if not line or line.startswith('-'):
            continue
        match = re.match(r'^([A-Za-z0-9_.-]+)(?:\[([^]]+)\])?(.*)$', line)
        if not match:
            continue
        name, extras, spec = match.groups()
        contracts[normalize(name)] = (
            re.sub(r'\s+', '', spec),
            tuple(sorted(normalize(item) for item in (extras or '').split(',') if item.strip())),
        )
    return contracts


def poetry_packages(path: Path = PYPROJECT) -> set[str]:
    return set(poetry_contracts(path))


def poetry_contracts(path: Path = PYPROJECT) -> dict[str, tuple[str, tuple[str, ...]]]:
    data = tomllib.loads(path.read_text(encoding='utf-8'))
    dependencies = data['tool']['poetry']['dependencies']
    contracts = {}
    for raw_name, value in dependencies.items():
        name = normalize(raw_name)
        if name == 'python':
            continue
        extras = ()
        version = value
        if isinstance(value, dict):
            version = value.get('version', '')
            extras = tuple(sorted(normalize(item) for item in value.get('extras', [])))
        spec = str(version).strip()
        if spec and not spec.startswith(('=', '>', '<', '!', '~', '^', '*')):
            spec = f'=={spec}'
        contracts[name] = (re.sub(r'\s+', '', spec), extras)
    return contracts


def runtime_imports() -> set[str]:
    imports = set()
    paths = [ROOT / 'config', ROOT / 'core']
    for base in paths:
        for path in base.rglob('*.py'):
            relative = path.relative_to(ROOT)
            if 'migrations' in relative.parts or path.name.startswith('test') or path.name.startswith('tests'):
                continue
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(item.name.split('.', 1)[0] for item in node.names)
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    imports.add(node.module.split('.', 1)[0])
    local = {'config', 'core'}
    return {
        name for name in imports
        if name not in sys.stdlib_module_names and name not in local
    }


def parity_errors() -> list[str]:
    pip = requirement_packages()
    poetry = poetry_packages()
    errors = [f'Missing from Poetry: {name}' for name in sorted(pip - poetry)]
    errors.extend(f'Missing from requirements.txt: {name}' for name in sorted(poetry - pip))
    pip_contracts = requirement_contracts()
    poetry_contracts_by_name = poetry_contracts()
    for name in sorted(pip & poetry):
        if pip_contracts[name] != poetry_contracts_by_name[name]:
            errors.append(
                f'Dependency contract differs for {name}: '
                f'pip={pip_contracts[name]!r} poetry={poetry_contracts_by_name[name]!r}'
            )
    for module in sorted(runtime_imports()):
        package = IMPORT_TO_PACKAGE.get(module)
        if not package:
            errors.append(f'Unmapped external runtime import: {module}')
        elif normalize(package) not in pip or normalize(package) not in poetry:
            errors.append(f'Runtime import {module} lacks direct dependency {package}')
    project = tomllib.loads(PYPROJECT.read_text(encoding='utf-8'))
    project_python = re.sub(r'\s+', '', str(project['project']['requires-python']))
    poetry_python = re.sub(
        r'\s+', '', str(project['tool']['poetry']['dependencies']['python']),
    )
    if project_python != '>=3.12,<3.13' or poetry_python != project_python:
        errors.append(
            'Python support must match as >=3.12,<3.13 in both project and Poetry metadata.'
        )
    return errors


def main() -> int:
    errors = parity_errors()
    if errors:
        print('\n'.join(errors))
        return 1
    print(f'Dependency parity passed ({len(requirement_packages())} direct packages).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
