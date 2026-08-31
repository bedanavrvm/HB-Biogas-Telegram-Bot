#!/usr/bin/env python3
"""Ensure every decouple setting is represented by the environment template."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SETTINGS_FILE = ROOT / 'config' / 'settings.py'
ENV_FILE = ROOT / '.env.example'
DEPLOYMENT_ONLY = {
    'DJANGO_SUPERUSER_EMAIL',
    'DJANGO_SUPERUSER_PASSWORD',
    'DJANGO_SUPERUSER_USERNAME',
}


def settings_keys(path: Path = SETTINGS_FILE) -> set[str]:
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    result = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != 'config':
            continue
        if isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            result.add(node.args[0].value)
    return result


def env_keys(path: Path = ENV_FILE) -> set[str]:
    result = set()
    for raw_line in path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key = line.split('=', 1)[0].strip()
        if key:
            result.add(key)
    return result


def parity_errors(settings_path: Path = SETTINGS_FILE, env_path: Path = ENV_FILE) -> list[str]:
    configured = settings_keys(settings_path)
    documented = env_keys(env_path)
    errors = [f'Missing from .env.example: {key}' for key in sorted(configured - documented)]
    errors.extend(
        f'Not read by settings.py: {key}'
        for key in sorted(documented - configured - DEPLOYMENT_ONLY)
    )
    return errors


def main() -> int:
    errors = parity_errors()
    if errors:
        print('\n'.join(errors))
        return 1
    print(f'Settings/environment parity passed ({len(settings_keys())} settings).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
