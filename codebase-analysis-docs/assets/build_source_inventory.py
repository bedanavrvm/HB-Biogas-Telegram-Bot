"""Rebuild static, customer-data-free analysis inventories; no Django imports.

Run from the repository root: python codebase-analysis-docs/assets/build_source_inventory.py
Only the analysis assets directory is written. Hashes describe exact file bytes.
"""
from __future__ import annotations

import ast
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
TEXT = {".py", ".js", ".css", ".html", ".md", ".txt", ".json", ".toml", ".yml", ".yaml", ".sh", ".gs", ".example"}


def expr(node):
    return ast.unparse(node) if node is not None else ""


def literal(node):
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError):
        return None


def cell(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


def category(path):
    if "/migrations/" in path:
        return "migration"
    if "vendor" in path or path.endswith(".min.js"):
        return "vendor"
    if "/tests" in path or "/test_" in path or path.startswith("test_"):
        return "test"
    if path.startswith("docs/") or path.endswith(".md"):
        return "documentation"
    if path.startswith(("config/", ".github/")) or path in {"requirements.txt", "pyproject.toml", "package.json", "playwright.config.js"}:
        return "configuration"
    if path.startswith("scripts/") or path.endswith(".sh"):
        return "operations"
    if Path(path).suffix in {".py", ".js", ".html", ".css", ".gs"}:
        return "code"
    return "opaque/other"


def main():
    paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip()
    rows, symbols, imports, models, routes, settings, errors, modules = [], [], [], [], [], [], [], []
    for path in sorted(filter(None, paths)):
        target = ROOT / path
        if not target.is_file() or path.startswith("codebase-analysis-docs/"):
            continue
        raw = target.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()[:8]
        kind = category(path)
        is_text = target.suffix in TEXT or path in {"AGENTS.md", ".gitignore"}
        lines = len(raw.splitlines()) if is_text else None
        priority = 0
        if kind in {"code", "configuration", "operations"}:
            priority = 4
        if path.endswith(("models.py", "urls.py", "settings.py")) or path in {"manage.py", "requirements.txt", "pyproject.toml", ".github/workflows/ci.yml"}:
            priority += 8
        if "/api/" in path or "/services/" in path:
            priority += 3
        if kind == "test":
            priority = 5
        if kind in {"vendor", "opaque/other"}:
            priority = -5
        rows.append(dict(path=path, type=kind, lines=lines, hash8=digest, priority=priority))
        if target.suffix != ".py":
            continue
        try:
            tree = ast.parse(raw.decode("utf-8-sig"), filename=path)
        except (SyntaxError, UnicodeDecodeError) as error:
            errors.append(dict(path=path, error=type(error).__name__))
            continue
        modules.append(dict(path=path, summary=(ast.get_docstring(tree) or "").split("\n")[0]))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                imports.append(dict(path=path, line=node.lineno, module=getattr(node, "module", None), level=getattr(node, "level", 0), names=[n.name for n in node.names]))
            if path == "config/settings.py" and isinstance(node, ast.Call) and expr(node.func) == "config" and node.args and isinstance(node.args[0], ast.Constant):
                settings.append(dict(name=node.args[0].value, line=node.lineno, cast=next((expr(k.value) for k in node.keywords if k.arg == "cast"), "str")))
            if path.endswith("urls.py") and isinstance(node, ast.Call) and expr(node.func) in {"path", "re_path", "alias"} and node.args:
                route = literal(node.args[0])
                if isinstance(route, str):
                    routes.append(dict(path=path, line=node.lineno, route=route, view=expr(node.args[1]) if len(node.args) > 1 else "", name=next((literal(k.value) for k in node.keywords if k.arg == "name"), None)))
        for node in tree.body:
            if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            entry = dict(path=path, name=node.name, kind="class" if isinstance(node, ast.ClassDef) else "function", start=node.lineno, end=node.end_lineno, hash8=digest)
            if isinstance(node, ast.ClassDef):
                entry["bases"] = [expr(n) for n in node.bases]
                entry["methods"] = [dict(name=n.name, start=n.lineno, end=n.end_lineno) for n in node.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            else:
                entry["parameters"] = [a.arg for a in node.args.posonlyargs + node.args.args + node.args.kwonlyargs]
            symbols.append(entry)
            if not isinstance(node, ast.ClassDef) or not path.endswith("models.py"):
                continue
            if not any(expr(base).endswith(("Model", "ScopedConfiguration", "ImmutableRecord")) for base in node.bases):
                continue
            fields, meta, choices = [], {}, {}
            for part in node.body:
                if isinstance(part, ast.Assign) and isinstance(part.value, ast.Call) and expr(part.value.func).split(".")[-1].endswith(("Field", "Key")):
                    call = part.value
                    fields.append(dict(name=expr(part.targets[0]), type=expr(call.func), relation=expr(call.args[0]) if call.args and expr(call.func).endswith(("ForeignKey", "OneToOneField", "ManyToManyField")) else "", options={k.arg: expr(k.value) for k in call.keywords if k.arg in {"on_delete", "related_name", "null", "blank", "unique", "primary_key", "max_length", "max_digits", "decimal_places", "db_index", "choices"}}))
                if isinstance(part, ast.ClassDef) and part.name == "Meta":
                    for prop in part.body:
                        if isinstance(prop, ast.Assign):
                            key = expr(prop.targets[0])
                            if key in {"db_table", "abstract", "proxy", "constraints", "indexes", "ordering", "unique_together"}:
                                meta[key] = expr(prop.value)
                elif isinstance(part, ast.ClassDef):
                    vals = {expr(n.targets[0]): expr(n.value) for n in part.body if isinstance(n, ast.Assign)}
                    if vals:
                        choices[part.name] = vals
            models.append(dict(path=path, name=node.name, start=node.lineno, end=node.end_lineno, hash8=digest, fields=fields, meta=meta, choices=choices))

    incoming = Counter()
    for item in imports:
        module = item["module"]
        if module and item["level"] == 0:
            incoming[module.replace(".", "/") + ".py"] += 1
            for name in item["names"]:
                incoming[(module + "." + name).replace(".", "/") + ".py"] += 1
    for row in rows:
        row["static_incoming_imports"] = incoming[row["path"]]
        if row["type"] == "code":
            row["priority"] += min(8, incoming[row["path"]])
    rows.sort(key=lambda r: (-r["priority"], r["path"]))
    metadata = dict(revision=revision, hash_algorithm="sha256-first-8-hex", file_count=len(rows), classifications=dict(Counter(r["type"] for r in rows)), parse_errors=errors)
    payloads = {"SOURCE_INDEX.json": dict(metadata=metadata, files=rows), "SYMBOL_INDEX.json": dict(metadata=metadata, symbols=symbols, imports=imports), "MODEL_INDEX.json": dict(metadata=metadata, models=models), "ROUTE_INDEX.json": dict(metadata=metadata, routes=routes), "SETTING_INDEX.json": dict(metadata=metadata, settings=settings)}
    for filename, data in payloads.items():
        (OUT / filename).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    head = ["# File index", "", f"Source revision: `{revision}`. HASH8 is SHA-256 of exact file bytes. Priority is a static heuristic, not a correctness score.", "", "Opaque artifacts are indexed only by metadata. They are not source evidence. Import counts exclude dynamic imports and relative-import resolution.", "", "(#) | PRIORITY | PATH | TYPE | LINES | HASH8 | NOTES", "--- | --- | --- | --- | --- | --- | ---"]
    for number, row in enumerate(rows, 1):
        head.append(f"{number} | {row['priority']} | `{row['path']}` | {row['type']} | {row['lines'] if row['lines'] is not None else 'opaque'} | {row['hash8']} | static incoming imports: {row['static_incoming_imports']}")
    (OUT / "FILE_INDEX.md").write_text("\n".join(head) + "\n", encoding="utf-8")
    body = ["# Static model reference", "", "Declared fields only; abstract inheritance, runtime registration, implicit Django fields, and migration state require checking authoritative model code and migrations. This is not a live database dump.", ""]
    for model in models:
        body.extend([f"## {model['path']}::{model['name']}", "", f"[[F:{model['path']}#{model['start']}-{model['end']}#{model['hash8']}]]", "", "Field | Type | Relation | Options", "--- | --- | --- | ---"])
        for field in model["fields"]:
            body.append(" | ".join(cell(x) for x in [field["name"], field["type"], field["relation"], "; ".join(f"{k}={v}" for k, v in field["options"].items())]))
        body.extend(["", "Model metadata: `" + cell(json.dumps(model["meta"])) + "`", ""])
        if model["choices"]:
            body.extend(["Declared choices: `" + cell(json.dumps(model["choices"])) + "`", ""])
    (OUT / "MODEL_REFERENCE.md").write_text("\n".join(body) + "\n", encoding="utf-8")
    api = ["# Static route reference", "", "Route patterns are local to their URL module; apply mounts from config/urls.py. Entries from calls outside urlpatterns may be helper definitions. HTTP methods, authentication, dynamic routes, and payloads must be confirmed in views/tests. This is not an OpenAPI contract.", "", "Source | Local pattern | View / include | URL name", "--- | --- | --- | ---"]
    for route in routes:
        api.append(" | ".join(cell(x) for x in [f"{route['path']}:{route['line']}", f"`{route['route']}`", f"`{route['view']}`", route["name"] or "—"]))
    (OUT / "ROUTE_REFERENCE.md").write_text("\n".join(api) + "\n", encoding="utf-8")
    by_path = defaultdict(list)
    for symbol in symbols:
        by_path[symbol['path']].append(symbol)
    module_rows = ['# Python module reference', '', 'Mechanical inventory of top-level symbols and source docstrings. A source docstring is a discovery aid, not proof that historical behavior is reachable. See the master document for interpreted ownership and retirement gates.', '', 'Module | Source summary | Public top-level symbols', '--- | --- | ---']
    for module in modules:
        if category(module['path']) in {'migration', 'test'}:
            continue
        public = ', '.join(f"{s['name']}:{s['start']}" for s in by_path[module['path']] if not s['name'].startswith('_'))
        module_rows.append(' | '.join(cell(v) for v in [module['path'], module['summary'] or '(No module docstring)', public or '(No public top-level declarations)']))
    (OUT / 'MODULE_REFERENCE.md').write_text('\n'.join(module_rows) + '\n', encoding='utf-8')
    test_rows = ['# Python test discovery map', '', 'Static discovery only; listed tests have not necessarily been executed. JavaScript/browser suites are indexed in FILE_INDEX.md and package.json.', '', 'Module | Class / function | Test methods', '--- | --- | ---']
    for symbol in symbols:
        if category(symbol['path']) != 'test':
            continue
        methods = ', '.join(m['name'] for m in symbol.get('methods', []) if m['name'].startswith('test'))
        if methods or symbol['name'].startswith('test'):
            test_rows.append(' | '.join(cell(v) for v in [symbol['path'], f"{symbol['name']}:{symbol['start']}", methods]))
    (OUT / 'TEST_REFERENCE.md').write_text('\n'.join(test_rows) + '\n', encoding='utf-8')
    catalog = json.loads((ROOT / 'docs/database/catalog.json').read_text(encoding='utf-8'))
    domain_rows = ['# Governed database catalogue projection', '', 'Copied mechanically from the customer-data-free checked-in docs/database/catalog.json, not queried from any database. Catalogue freshness is reported in the master document.', '', 'Domain | Model | Physical table | Authority | Lifecycle | Purpose | Parents', '--- | --- | --- | --- | --- | --- | ---']
    for table in catalog['tables']:
        domain_rows.append(' | '.join(cell(v) for v in [table['domain'], table['django_model'], table['table'], table['source_of_truth'], table['lifecycle'], table['purpose'], ', '.join(table['parents'])]))
    (OUT / 'DATABASE_DOMAINS.md').write_text('\n'.join(domain_rows) + '\n', encoding='utf-8')
    print(json.dumps(dict(**metadata, top_files=[r["path"] for r in rows[:50]], models=len(models), symbols=len(symbols), routes=len(routes), settings=len(settings))))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) > 1 and sys.argv[1] == "--chunk":
        # Read-only helper for bounded, anchored source inspection.
        for spec in sys.argv[2:]:
            source, start, end = spec.rsplit(":", 2)
            raw = (ROOT / source).read_bytes()
            digest = hashlib.sha256(raw).hexdigest()[:8]
            print(f"CHUNK_ID = {source}#{start}-{end}#{digest}")
            lines = raw.decode("utf-8-sig").splitlines()
            print("\n".join(f"{n + 1}: {line}" for n, line in enumerate(lines) if int(start) <= n + 1 <= int(end)))
    else:
        main()
