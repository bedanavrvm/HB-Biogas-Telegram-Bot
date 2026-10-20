"""UI-source ratchet and reviewed release integrity, without production DB access."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / 'docs/ui-standard/registry.json'
UI_PREFIXES = ('core/static/miniapp/', 'origination/static/miniapp/', 'core/templates/', 'origination/templates/', 'browser/src/')


def source_hash(path):
    candidate = (ROOT / path).resolve()
    if not candidate.is_relative_to(ROOT) or not candidate.is_file():
        return None
    content = candidate.read_bytes()
    if candidate.suffix in {'.py', '.html', '.js', '.css', '.json', '.svg', '.txt', '.ts', '.tsx', '.cjs'}:
        content = content.replace(b'\r\n', b'\n')
    return hashlib.sha256(content).hexdigest()


def check_registry(registry):
    errors = []
    if registry.get('migration_authorized') is not False:
        errors.append('Phase 6 remains on hold; approval is required before changing this gate.')
    reviewed = {entry['path']: entry for entry in registry.get('changes', [])}
    known = {entry['path'] for entry in registry['legacy_sources']}
    for folder in registry.get('source_roots', []):
        for candidate in (ROOT / folder).rglob('*'):
            if candidate.suffix not in ('.html', '.js', '.css', '.ts', '.tsx') or candidate.name.startswith('vendor-'):
                continue
            relative = candidate.relative_to(ROOT).as_posix()
            change = reviewed.get(relative, {})
            if relative not in known and (change.get('sha256') != source_hash(relative)
                    or not change.get('review_reference') or not change.get('reason')):
                errors.append(f'{relative}: new UI source needs a catalogue review reference and reason.')
    for entry in registry['legacy_sources']:
        actual = source_hash(entry['path'])
        if actual == entry['sha256']:
            continue
        change = reviewed.get(entry['path'], {})
        if change.get('sha256') != actual or not change.get('review_reference') or not change.get('reason'):
            errors.append(f'{entry["path"]}: changed UI source needs a source-bound review record or explained nonvisual exception.')
    for path in registry['operational_templates']:
        if not (ROOT / path).is_file():
            errors.append(f'{path}: retained template was removed; update the reviewed consumer inventory.')
            continue
        content = (ROOT / path).read_text(encoding='utf-8')
        if 'ui_review/tokens.css' in content or 'ui_review/theme.js' in content:
            errors.append(f'{path}: candidate foundations must stay in the lab until migration approval.')
    return errors


def check_release(document):
    errors = []
    manifest = document.get('manifest', {})
    if manifest.get('migration_authorized') is not False:
        errors.append('A reviewed standard does not authorize Phase 6 migration.')
    canonical = json.dumps(manifest, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    if hashlib.sha256(canonical.encode()).hexdigest() != document.get('fingerprint'):
        errors.append('Standard manifest digest does not match.')
    expected = set(json.loads(REGISTRY.read_text(encoding='utf-8'))['pattern_keys'])
    selections = manifest.get('selections', [])
    if {item.get('pattern') for item in selections} != expected or len(selections) != len(expected):
        errors.append('The standard must account for every current pattern exactly once.')
    if not any(item.get('pattern') == 'foundations' and item.get('action') in ('adopt', 'approve') and item.get('sources') for item in selections):
        errors.append('The standard needs explicitly approved source-bound foundations.')
    for selection in manifest.get('selections', []):
        if selection.get('action') not in ('adopt', 'approve', 'defer') or not selection.get('decision'):
            errors.append(f'{selection.get("pattern")}: no explicit approval/deferral reference.')
        for item in selection.get('sources', []):
            if source_hash(item['path']) != item['sha256']:
                errors.append(f'{item["path"]}: approved source changed; create and review a new revision.')
    for module in manifest.get('governed_modules', []):
        path = module['path']
        if not path.startswith(UI_PREFIXES) or not path.endswith('.css'):
            errors.append(f'{path}: governed styles must be first-party UI CSS.')
            continue
        text = re.sub(r'/\*.*?\*/', '', (ROOT / path).read_text(encoding='utf-8'), flags=re.S)
        for prop, value in re.findall(r'(font-size|padding(?:-[a-z]+)?|margin(?:-[a-z]+)?|gap|border-radius|color|background-color)\s*:\s*([^;{}]+)', text):
            if re.search(r'\d(?:px|rem|em)\b|#[\da-f]{3,8}\b|rgba?\(', value, re.I):
                exceptions = module.get('exceptions', [])
                if not any(item.get('property') == prop and item.get('value') == value.strip() and item.get('reason') for item in exceptions):
                    errors.append(f'{path}: {prop}: {value.strip()} must use an approved token or a narrow documented exception.')
    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', type=Path)
    args = parser.parse_args()
    findings = check_registry(json.loads(REGISTRY.read_text(encoding='utf-8')))
    if args.manifest:
        findings.extend(check_release(json.loads(args.manifest.read_text(encoding='utf-8'))))
    if findings:
        print('\n'.join(findings))
        return 1
    print('UI review checks passed. Candidate code remains isolated; legacy ratchet active; Phase 6 on hold.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
