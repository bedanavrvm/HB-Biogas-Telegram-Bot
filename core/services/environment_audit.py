"""Name-only environment inventory and conservative dotenv cleanup."""
from __future__ import annotations

import re
import shutil
from pathlib import Path


KEY_RE = re.compile(r'^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$')

DEPRECATED = {
    'ORDER_APPROVAL_WEBAPP_ENABLED',
    'ORDER_APPROVAL_BRANCH_CHOICES',
    'ORDER_APPROVAL_IMAGE_PREVIEW_LIMIT',
    'ORDER_APPROVAL_IMAGE_PREVIEWS_ENABLED',
    'ORDER_APPROVAL_MAX_FILES_PER_SLOT',
    'ORDER_APPROVAL_MAX_TOTAL_UPLOAD_MB',
    'ORDER_APPROVAL_MINI_APP_SHORT_NAME',
    'ORDER_APPROVAL_WEBAPP_AUTH_MAX_AGE_SECONDS',
    'ORDER_APPROVAL_WEBAPP_REQUIRE_TELEGRAM_AUTH',
    'TAT_TRACKER_BRANCH_CHOICES',
    'WORKFLOW_BRANCH_CHOICES',
    'SENTRY_BROWSER_TRACES_SAMPLE_RAT',
}

BOOTSTRAP_ONLY = {
    'DJANGO_SUPERUSER_USERNAME', 'DJANGO_SUPERUSER_EMAIL', 'DJANGO_SUPERUSER_PASSWORD',
}

# Only remove an override when its normalized value equals the tested code
# default. Non-default tuning is always preserved.
DEFAULTS = {
    'BATCH_PROCESSING_DELAY': '1',
    'DEDUPLICATION_WINDOW_MINUTES': '5',
    'FILE_UPLOAD_MAX_MEMORY_SIZE': '0',
    'MEDIA_MAX_FILE_SIZE_MB': '20',
    'MEDIA_STORAGE_PROVIDER': 'google_drive',
    'MINIAPP_DIAGNOSTICS_AGGREGATE_RETENTION_DAYS': '180',
    'MINIAPP_DIAGNOSTICS_ENABLED': 'true',
    'MINIAPP_DIAGNOSTICS_HEARTBEAT_SECONDS': '60',
    'MINIAPP_DIAGNOSTICS_MAX_PAYLOAD_BYTES': '8192',
    'MINIAPP_DIAGNOSTICS_RAW_RETENTION_DAYS': '14',
    'MINIAPP_DIAGNOSTICS_TOKEN_MAX_AGE_SECONDS': '172800',
    'ORIGINATION_CONDITIONAL_APPROVAL_ENABLED': 'false',
    'ORIGINATION_ESIGN_ENABLED': 'false',
    'ORIGINATION_FULL_RESET_ENABLED': 'false',
    'ORIGINATION_PRODUCT_FAMILY_PURGE_ENABLED': 'false',
    'ORIGINATION_SIGNING_LINK_TTL_HOURS': '72',
    'ORIGINATION_TEST_SIGNING_ENABLED': 'false',
    'PORTAL_VOICE_INPUT_ENABLED': 'false',
    'RELEASE_ALLOW_NO_BACKUP': 'false',
    'RELEASE_ENVIRONMENT': 'production',
    'SECURE_HSTS_INCLUDE_SUBDOMAINS': 'true',
    'SECURE_HSTS_PRELOAD': 'true',
    'SECURE_HSTS_SECONDS': '31536000',
    'SECURE_SSL_REDIRECT': 'true',
    'SESSION_COOKIE_SECURE': 'true',
    'CSRF_COOKIE_SECURE': 'true',
    'SPIN_WEBAPP_AUTH_MAX_AGE_SECONDS': '86400',
    'SPIN_WEBAPP_REQUIRE_TELEGRAM_AUTH': 'true',
    'COMPLAINT_CASES_WEBAPP_REQUIRE_TELEGRAM_AUTH': 'true',
    'TAT_TRACKER_WEBAPP_REQUIRE_TELEGRAM_AUTH': 'true',
    'TAT_REPAIR_CASE_DELAY_SECONDS': '1.1',
    'TAT_REPAIR_RETRY_BASE_SECONDS': '2.0',
}


def _normalized(value: str) -> str:
    return value.strip().strip('"').strip("'").casefold()


def audit_environment(path: Path) -> dict:
    entries = []
    for line in path.read_text(encoding='utf-8').splitlines() if path.exists() else []:
        match = KEY_RE.match(line)
        if not match:
            continue
        key, value = match.groups()
        if key in DEPRECATED:
            state = 'deprecated'
        elif key in BOOTSTRAP_ONLY:
            state = 'bootstrap_only'
        elif key in DEFAULTS and _normalized(value) == DEFAULTS[key]:
            state = 'redundant_default'
        else:
            state = 'retained'
        entries.append({'key': key, 'state': state})
    return {
        'path': str(path),
        'count': len(entries),
        'summary': {
            state: sum(item['state'] == state for item in entries)
            for state in ('retained', 'bootstrap_only', 'redundant_default', 'deprecated')
        },
        'entries': entries,
    }


def clean_environment(path: Path, *, drop_bootstrap=False) -> dict:
    if not path.exists():
        raise ValueError(f'{path} does not exist.')
    backup = path.with_name(f'{path.name}.pre-cleanup')
    shutil.copy2(path, backup)
    kept = []
    for line in path.read_text(encoding='utf-8').splitlines():
        match = KEY_RE.match(line)
        if match:
            key, value = match.groups()
            redundant = key in DEFAULTS and _normalized(value) == DEFAULTS[key]
            if key in DEPRECATED or redundant or (drop_bootstrap and key in BOOTSTRAP_ONLY):
                continue
        kept.append(line)
    path.write_text('\n'.join(kept).rstrip() + '\n', encoding='utf-8')
    result = audit_environment(path)
    result['backup'] = str(backup)
    return result
