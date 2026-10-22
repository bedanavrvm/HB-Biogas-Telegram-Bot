"""Inspect only the exact new browser archives; emit an apply_patch, never install."""
import importlib.util
import json
from pathlib import Path
import tempfile

root = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('browser_review', root / 'codebase-analysis-docs/assets/review_browser_dependencies.py')
reviewer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reviewer)
path = root / 'browser/dependency-review.json'
before = path.read_text(encoding='utf-8')
review = json.loads(before)
base = json.loads((root / review['base_report']).read_text(encoding='utf-8'))
lock = json.loads((root / 'browser/package-lock.json').read_text(encoding='utf-8'))
candidate = json.loads((root / 'browser/package.json').read_text(encoding='utf-8'))
known = {(row['name'], row['version'], row['integrity']) for row in base['artifacts'] + review['new_artifacts']}
with tempfile.TemporaryDirectory(prefix='jbl-browser-archive-review-') as directory:
    for row in reviewer.lock_records(lock, candidate):
        key = (row['name'], row['version'], row['integrity'])
        if key in known:
            continue
        inspection = reviewer.fetch_archive(row, Path(directory), fetch=True)
        if inspection.get('lifecycle_scripts'):
            raise RuntimeError('New lifecycle scripts need separate review.')
        row['inspection'] = inspection
        review['new_artifacts'].append(row)
        known.add(key)
review['lock_sha256'] = reviewer.json_digest(lock)
review['scope'] = 'Exact local React/ADS and AG Grid Community browser build; production release remains gated.'
review['authorization'] = 'User: fix ui.txt before the next slice; use AG Grid tables. Local UI correction only.'
review['summary']['lock_entries'] = len(lock['packages']) - 1
review['summary']['new_inspections'] = len(review['new_artifacts'])
review['summary']['unique_artifacts'] = len(known)
review['summary']['reused_inspections'] = len(known) - len(review['new_artifacts'])
after = json.dumps(review, indent=2, ensure_ascii=False) + '\n'
import difflib
lines = list(difflib.unified_diff(before.splitlines(), after.splitlines(), n=3))[2:]
patch = ['*** Begin Patch', '*** Update File: browser/dependency-review.json']
patch.extend('@@' if line.startswith('@@') else line for line in lines)
patch.append('*** End Patch')
print(json.dumps('\n'.join(patch)))
