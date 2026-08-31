#!/usr/bin/env python3
"""Fail when an unsafe-method API route escapes the reviewed Mini App inventory."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / 'core' / 'api'
URLS_FILE = API_ROOT / 'urls.py'
UNSAFE_METHODS = frozenset({'POST', 'PUT', 'PATCH', 'DELETE'})
KEY_BOUNDARIES = frozenset({
    'miniapp_write_response', 'miniapp_idempotency_boundary', 'portal_auth_required',
})


@dataclass(frozen=True)
class DiscoveredRoute:
    name: str
    path: str
    view_name: str
    methods: frozenset[str]
    key_boundary: str


def _decorator_name(node: ast.expr) -> str:
    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return ''


def _view_contracts() -> dict[str, tuple[frozenset[str], frozenset[str]]]:
    contracts: dict[str, tuple[frozenset[str], frozenset[str]]] = {}
    for source_path in sorted(API_ROOT.glob('*.py')):
        tree = ast.parse(source_path.read_text(encoding='utf-8'), filename=str(source_path))
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            methods: set[str] = set()
            decorators = {_decorator_name(item) for item in node.decorator_list}
            for decorator in node.decorator_list:
                name = _decorator_name(decorator)
                if name == 'require_POST':
                    methods.add('POST')
                elif name == 'require_http_methods' and isinstance(decorator, ast.Call):
                    try:
                        methods.update(str(value).upper() for value in ast.literal_eval(decorator.args[0]))
                    except (IndexError, TypeError, ValueError):
                        pass
            contracts[node.name] = (frozenset(methods), frozenset(decorators))
    return contracts


def discover_write_routes() -> dict[str, DiscoveredRoute]:
    contracts = _view_contracts()
    tree = ast.parse(URLS_FILE.read_text(encoding='utf-8'), filename=str(URLS_FILE))
    discovered: dict[str, DiscoveredRoute] = {}
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == 'path'
            and len(node.args) >= 2
        ):
            continue
        try:
            route_path = str(ast.literal_eval(node.args[0]))
        except (TypeError, ValueError):
            continue
        route_name = ''
        for keyword in node.keywords:
            if keyword.arg == 'name':
                try:
                    route_name = str(ast.literal_eval(keyword.value))
                except (TypeError, ValueError):
                    route_name = ''
        view_node = node.args[1]
        url_boundary = ''
        if isinstance(view_node, ast.Call) and view_node.args:
            url_boundary = _decorator_name(view_node)
            view_node = view_node.args[0]
        if not route_name or not isinstance(view_node, ast.Name):
            continue
        methods, decorators = contracts.get(view_node.id, (frozenset(), frozenset()))
        unsafe = frozenset(methods & UNSAFE_METHODS)
        if not unsafe:
            continue
        boundary = url_boundary if url_boundary in KEY_BOUNDARIES else ''
        if not boundary:
            boundary = next((name for name in KEY_BOUNDARIES if name in decorators), '')
        discovered[route_name] = DiscoveredRoute(
            name=route_name,
            path=route_path,
            view_name=view_node.id,
            methods=unsafe,
            key_boundary=boundary,
        )
    return discovered


def inventory_errors() -> list[str]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from core.miniapp_write_inventory import (
        NON_MINIAPP_WRITE_ROUTES,
        WRITE_ROUTE_INVENTORY,
    )

    routes = discover_write_routes()
    reviewed = set(WRITE_ROUTE_INVENTORY) | set(NON_MINIAPP_WRITE_ROUTES)
    errors: list[str] = []
    for name in sorted(set(routes) - reviewed):
        item = routes[name]
        errors.append(
            f'Uninventoried unsafe-method route: {name} {sorted(item.methods)} {item.path}'
        )
    for name in sorted(reviewed - set(routes)):
        errors.append(f'Stale write-route inventory entry: {name}')
    for name, policy in sorted(WRITE_ROUTE_INVENTORY.items()):
        item = routes.get(name)
        if item is None:
            continue
        if not item.methods.issubset(set(policy.methods)):
            errors.append(
                f'Inventory methods for {name} omit {sorted(item.methods - set(policy.methods))}.'
            )
        if not item.key_boundary:
            errors.append(
                f'Mini App route {name} has no statically visible request-key boundary.'
            )
        for field_name in (
            'authentication', 'capability', 'scope', 'request_key_binding', 'domain_replay',
        ):
            if not str(getattr(policy, field_name, '') or '').strip():
                errors.append(f'Inventory field {field_name} is blank for {name}.')
    return errors


def main() -> int:
    errors = inventory_errors()
    if errors:
        for error in errors:
            print(error)
        print(f'Mini App write-route inventory failed with {len(errors)} issue(s).')
        return 1
    from core.miniapp_write_inventory import WRITE_ROUTE_INVENTORY

    print(f'Mini App write-route inventory passed ({len(WRITE_ROUTE_INVENTORY)} route(s)).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
