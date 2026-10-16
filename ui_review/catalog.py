"""Code-owned pattern inventory. Human choices live in immutable Django records."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from django.contrib.staticfiles import finders
from django.template.loader import get_template

from .fingerprints import source_digest

ROOT = Path(__file__).resolve().parents[1]
APPS = {
    'portal': {'label': 'Portal', 'template': 'core/templates/base_shell.html', 'body': 'core/templates/portal/portal.html', 'url': '/portal/'},
    'tat': {'label': 'TAT Tracker', 'template': 'core/templates/tat_tracker/app.html', 'url': '/tat-tracker/'},
    'complaints': {'label': 'Complaints', 'template': 'core/templates/complaint_cases/app.html', 'url': '/complaints/'},
    'origination': {'label': 'Origination', 'template': 'origination/templates/loan_origination/app.html',
                    'additional_templates': ['origination/templates/loan_origination/sign.html'], 'url': '/origination/'},
}
STATES = ('one', 'empty', 'many', 'long', 'loading', 'error', 'denied')
ROLES = ('staff', 'manager', 'it')
FIXTURE_VERSION = 'synthetic-v1'

# App order stays fixed in each comparison, including explicit missing coverage.
# Selectors identify existing source, not a second implementation of that UI.
_ROWS = [
    ('foundations', 'Foundations', 'Type, spacing, density and themes', 'foundations', ('body',) * 4),
    ('shell', 'Navigation', 'App header and identity', 'queue', ('.app-shell-header', '#appHeader', '#appHeader', '.origination-header')),
    ('tabs', 'Navigation', 'Workspace tabs', 'queue', ('.app-sidebar', '#workspaceTabs', '#workspaceTabs', '.queue-tabs')),
    ('cards', 'Queues', 'Case cards', 'queue', ('.farmer-card', '.case-card', '.case-row', '.application-card')),
    ('identity', 'Queues', 'Names, National ID and phone', 'queue', ('.farmer-card', '.case-card', '.case-row', '.application-card')),
    ('status', 'Queues', 'Status chips and indicators', 'queue', ('.badge', '.status-chip', '.status-pill', '.status-chip')),
    ('search', 'Queues', 'Search and clear', 'queue', ('input[type=search]', '#queueSearchInput', '#caseSearch', '#origination-search')),
    ('filters', 'Queues', 'Queue filter sheet', 'filters', ('[data-portal-filter-sheet]', '#queueFilterSheet', '#complaintQueueFilterSheet', '.queue-filter-dialog')),
    ('pagination', 'Queues', 'Queue pagination', 'queue', ('.pagination', '#queuePagination', '#queuePagination', '.pagination')),
    ('forms', 'Forms', 'Form layout and labels', 'form', ('#jbl-form', '#newCaseForm', '#createCaseForm', '#origination-create')),
    ('required', 'Forms', 'Required fields and conditional inputs', 'form', ('#jbl-form', '#newCaseForm', '#createCaseForm', '#origination-create')),
    ('dropdowns', 'Forms', 'Dropdown options and search', 'form', ('select', 'select', 'select', 'select')),
    ('validation', 'Forms', 'Field errors and correction', 'form', ('[aria-invalid="true"]', '[aria-invalid="true"]', '[aria-invalid="true"]', '[aria-invalid="true"]')),
    ('drafts', 'Forms', 'Draft restore and discard', 'form', ('.draft-recovery', '.draft-recovery', '.draft-recovery', '.draft-recovery')),
    ('actions', 'Actions', 'Primary and secondary actions', 'form', ('button', 'button', 'button', 'button')),
    ('confirmations', 'Actions', 'Confirmation dialogs', 'queue', ('[role="dialog"]', '[role="dialog"]', '[role="dialog"]', '[role="dialog"]')),
    ('feedback', 'Actions', 'Success, warning and error feedback', 'queue', ('#toast', '#noticeModal', '#toast', '.toast')),
    ('loading', 'States', 'Loading state', 'queue', ('.skeleton', '#loadingBrand', '#loadingState', '.empty-state')),
    ('empty', 'States', 'Empty state', 'queue', ('.empty-state', '.empty-state', '.empty-state', '.empty-state')),
    ('recovery', 'Actions', 'Settings and recovery', 'settings', ('#page-settings', '#settingsView', '#complaintSettingsOverlay', '#origination-settings')),
    ('notifications', 'Navigation', 'Needs your input', 'queue', ('#portal-notification-panel', '#privateTaskPanel', '#errorBanner', '.reviewer-alerts')),
    ('camera', 'Evidence', 'Camera and capture', 'form', ('#jbl-camera-overlay', '#assessmentPreviewOverlay', '#cameraOverlay', '[data-id-camera]')),
    ('uploads', 'Evidence', 'File selection and progress', 'form', ('input[type="file"]', 'input[type="file"]', 'input[type="file"]', 'input[type="file"]')),
    ('preview', 'Evidence', 'Media preview, zoom and navigation', 'preview', ('#media-viewer-overlay', '#assessmentPreviewOverlay', '#mediaViewerOverlay', '#document-preview-overlay')),
    ('downloads', 'Evidence', 'Download and open file', 'reports', ('button', '#tatReportExport', '#exportResultsBtn', '[data-download]')),
    ('kpis', 'Reports', 'Summary cards', 'reports', ('.report-summary', '#tatReportMetrics', '#globalMetrics', '.metric-grid')),
    ('charts', 'Reports', 'Charts, controls and help', 'reports', ('canvas', 'canvas', 'canvas', 'canvas')),
    ('tables', 'Reports', 'Grid, copy and drill-down', 'reports', ('.ag-root', '.ag-root', '.ag-root', '.ag-root')),
    ('recognition', 'Reports', 'Standing and score detail', 'recognition', ('#page-performance', '#recognitionView', '#globalView', '#origination-root')),
    ('history', 'Details', 'Timeline and stage layout', 'detail', ('#portal-case-history', '#detailView', '#detailView', '#origination-root')),
    ('signing', 'Details', 'Signing and document actions', 'detail', ('#page-documents', '#detailView', '#detailView', '#origination-root')),
]
PATTERNS = {key: {'key': key, 'group': group, 'title': title, 'scene': scene,
                  'selectors': dict(zip(APPS, selectors))}
            for key, group, title, scene, selectors in _ROWS}
NOT_APPLICABLE = {'origination': {'kpis', 'charts', 'tables', 'recognition'},
                  'complaints': {'recognition', 'signing'}, 'tat': {'signing'}}


def screen_inventory():
    portal = (ROOT / APPS['portal']['body']).read_text(encoding='utf-8')
    return {'portal': sorted(set(re.findall(r"active_screen\s*==\s*['\"]([a-z_]+)", portal))),
            'tat': ['queue', 'create', 'case details', 'correction', 'reports', 'recognition', 'settings', 'evidence preview'],
            'complaints': ['queue', 'create', 'case details', 'HB comment / resolve', 'reports', 'settings', 'camera / media preview'],
            'origination': ['application queue', 'create', 'dynamic application sections', 'supporting documents', 'staff signing', 'remote signing', 'preview / downloads', 'settings']}


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def sources(app: str) -> list[dict]:
    config = APPS[app]
    paths = {ROOT / config['template']}
    paths.update(ROOT / name for name in config.get('additional_templates', []))
    if config.get('body'):
        paths.add(ROOT / config['body'])
    if app == 'portal':
        paths.add(ROOT / 'core/templates/portal/partials/farmer_list.html')
        paths.add(ROOT / 'core/templates/portal/partials/navigation.html')
    pending = list(paths)
    while pending:
        path = pending.pop()
        text = path.read_text(encoding='utf-8')
        for name in re.findall(r'{%\s*(?:include|extends)\s+[\'"]([^\'"]+)', text):
            included = Path(get_template(name).origin.name)
            if included not in paths:
                paths.add(included)
                pending.append(included)
        for name in re.findall(r'{%\s*static\s+[\'"]([^\'"]+)', text):
            found = finders.find(name)
            if found:
                paths.add(Path(found))
    paths.add(ROOT / 'ui_review/static/ui_review/scene_fixture.js')
    paths.add(ROOT / 'ui_review/static/ui_review/scene_driver.js')
    paths.add(Path(__file__))
    paths.add(ROOT / 'ui_review/scenes.py')
    paths.add(ROOT / 'ui_review/fingerprints.py')
    return [{'path': path.relative_to(ROOT).as_posix(), 'sha256': source_digest(path)}
            for path in sorted(paths) if path.is_file()]


def current_manifest(pattern: str, source_map=None) -> dict:
    item = PATTERNS[pattern]
    source_map = source_map or {app: sources(app) for app in APPS}
    variants = [{'id': app, 'label': config['label'], 'scene': item['scene'],
                 'selector': item['selectors'][app], 'sources': source_map[app],
                 'coverage': 'Unverified until a capture confirms the expected element and behaviour.'}
                for app, config in APPS.items() if pattern not in NOT_APPLICABLE.get(app, set())]
    if pattern == 'foundations':
        foundation_sources = [{'path': path.relative_to(ROOT).as_posix(), 'sha256': source_digest(path)}
                              for path in sorted((ROOT / 'ui_review/static/ui_review').glob('*')) if path.suffix in ('.css', '.js')]
        variants = [{'id': density, 'label': density.title(), 'scene': 'foundations',
                     'selector': '.specimen', 'sources': foundation_sources, 'proposal': True}
                    for density in ('compact', 'comfortable', 'spacious')]
    return {'format': 1, 'source_hash_format': 'lf-text-v1', 'pattern': pattern, 'title': item['title'], 'fixture_version': FIXTURE_VERSION,
            'variants': variants, 'states': list(STATES), 'roles': list(ROLES), 'evidence': [],
            'native_verified': False, 'migration_authorized': False}


def inventory() -> list[dict]:
    source_map = {app: sources(app) for app in APPS}
    return [{**item, 'fingerprint': digest(current_manifest(key, source_map))}
            for key, item in PATTERNS.items()]


def declared_values() -> dict:
    result = {}
    for app in APPS:
        values = {}
        for source in sources(app):
            if not source['path'].endswith('.css'):
                continue
            text = (ROOT / source['path']).read_text(encoding='utf-8')
            for name, value in re.findall(r'(font-size|padding|margin|gap|border-radius|box-shadow|color|background-color)\s*:\s*([^;{}]+)', text):
                values.setdefault(name, set()).add(value.strip())
        result[app] = {name: {'count': len(entries), 'values': sorted(entries)} for name, entries in values.items()}
    return {'kind': 'declared candidate dependencies, not computed style measurements', 'apps': result}
