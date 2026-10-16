"""Export synthetic source scenes without querying operational records."""
import json
from pathlib import Path
import subprocess

from django.contrib.staticfiles import finders
from django.core.management.base import BaseCommand, CommandError
from django.template.loader import render_to_string

from ui_review.catalog import APPS, PATTERNS, ROOT, STATES, current_manifest, declared_values, inventory, screen_inventory, sources
from ui_review.scenes import scene_html


class Command(BaseCommand):
    help = 'Export the read-only Mini App inventory and source shells into ignored test-results only.'

    def add_arguments(self, parser):
        parser.add_argument('--output', default='test-results/ui-audit')

    def handle(self, *args, **options):
        target = (ROOT / options['output']).resolve()
        safe_root = (ROOT / 'test-results').resolve()
        if not target.is_relative_to(safe_root) or target == safe_root:
            raise CommandError('Choose a subdirectory of test-results; application files are never audit output.')
        target.mkdir(parents=True, exist_ok=True)
        scenes = []
        for app in APPS:
            for scene in sorted({item['scene'] for item in PATTERNS.values()} - {'foundations'}):
                for state in STATES:
                    filename = f'{app}-{scene}-{state}.html'
                    (target / filename).write_text(scene_html(app, scene, state, 'manager'), encoding='utf-8')
                    scenes.append({'app': app, 'scene': scene, 'state': state, 'filename': filename})
        assets = {}
        # Source hashing already resolves referenced static files; use the same
        # Django finder precedence as production, not an assumed directory.
        for app in APPS:
            for item in sources(app):
                if '/static/' in item['path']:
                    name = item['path'].split('/static/', 1)[1]
                    found = finders.find(name)
                    if found:
                        assets['/static/' + name] = Path(found).relative_to(ROOT).as_posix()
        for path in (ROOT / 'ui_review/static/ui_review').glob('*'):
            if path.is_file():
                assets['/static/ui_review/' + path.name] = path.relative_to(ROOT).as_posix()
        try:
            commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
            dirty = bool(subprocess.run(['git', 'status', '--porcelain'], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip())
        except (OSError, subprocess.CalledProcessError):
            commit, dirty = '', True
        manifest = {'format': 1, 'commit': commit, 'dirty_worktree': dirty, 'patterns': inventory(), 'apps': APPS,
                    'screen_inventory': screen_inventory(),
                    'comparisons': {key: current_manifest(key) for key in PATTERNS},
                    'assets': assets, 'scenes': scenes, 'states': STATES, 'migration_authorized': False}
        (target / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        (target / 'declared-values.json').write_text(json.dumps(declared_values(), indent=2), encoding='utf-8')
        (target / 'lab.html').write_text(render_to_string('ui_review/index.html'), encoding='utf-8')
        self.stdout.write(f'Exported {len(PATTERNS)} unapproved patterns and {len(scenes)} synthetic source scenes to {target.relative_to(ROOT)}. No database/provider writes.')
