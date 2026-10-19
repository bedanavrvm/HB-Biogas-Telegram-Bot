"""Read-only checks for the source-backed documentation bundle."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / 'codebase-analysis-docs'
ASSETS = DOCS / 'assets'


def main():
    errors = []
    anchors = 0
    for document in DOCS.rglob('*.md'):
        content = document.read_text(encoding='utf-8')
        for match in re.finditer(r'\[\[F:([^#\]]+)#(\d+)-(\d+)#([0-9a-f]{8})\]\]', content):
            relative, start, end, digest = match.groups()
            path = ROOT / relative
            if not path.is_file():
                errors.append(f'{document.name}: missing anchor file {relative}')
                continue
            raw = path.read_bytes()
            actual = hashlib.sha256(raw).hexdigest()[:8]
            if digest != actual:
                errors.append(f'{document.name}: stale hash for {relative}: {digest} != {actual}')
            if not 1 <= int(start) <= int(end) <= len(raw.splitlines()):
                errors.append(f'{document.name}: invalid line range {relative}:{start}-{end}')
            anchors += 1
        for relative in re.findall(r'`((?:core|config|origination|payments|requisitions|hb_operations|credit_assessments|report_delivery|qa_tracker|ui_review|tat_recognition|portal_recognition|scripts|docs|codebase-analysis-docs)/[^`\n]+)`', content):
            path_text = relative.split('::', 1)[0]
            if any(char in path_text for char in '*<>') or path_text.endswith('/'):
                continue
            if not (ROOT / path_text).exists():
                errors.append(f'{document.name}: missing explicit repository path {path_text}')
    source_index = json.loads((ASSETS / 'SOURCE_INDEX.json').read_text(encoding='utf-8'))
    for row in source_index['files']:
        path = ROOT / row['path']
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()[:8] != row['hash8']:
            errors.append(f'Inventory changed: {row["path"]}')
    if source_index['metadata']['parse_errors']:
        errors.append('Source parse errors are present')
    master = (DOCS / 'CODEBASE_KNOWLEDGE.md').read_text(encoding='utf-8')
    required = ('High-Level Overview', 'Mid-Level Technical Notes', 'Deep Reference',
                'Things You Must Know Before Changing Code', 'Glossary', 'Assumptions')
    for heading in required:
        if heading not in master:
            errors.append(f'Missing master section: {heading}')
    for diagram in ASSETS.glob('*.mmd'):
        # Conservative readability guard; real tokenizer length is tool/model dependent.
        words = len(diagram.read_text(encoding='utf-8').split())
        if words > 180:
            errors.append(f'Diagram too large for compact rule: {diagram.name} ({words} words)')
    print(json.dumps({'source_files_verified': len(source_index['files']),
                      'source_anchors_verified': anchors,
                      'master_lines': len(master.splitlines()),
                      'master_words': len(master.split()),
                      'errors': errors}, indent=2))
    return bool(errors)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    raise SystemExit(main())
