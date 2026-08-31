"""Preflight-first, locally auditable production release orchestration."""

from __future__ import annotations

import hashlib
import json
import re

from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

from core.models import ProductionReleaseAudit


_REFERENCE_PATTERN = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:/-]*\Z')
_PLACEHOLDERS = {
    'provider-backup-reference',
    'git-commit-or-render-deploy-id',
    'your-backup-reference',
}


def migration_plan_names() -> list[str]:
    """Return the forward plan without applying migrations or running signals."""
    executor = MigrationExecutor(connection)
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    names = []
    for migration, backwards in plan:
        direction = 'backward' if backwards else 'forward'
        names.append(f'{migration.app_label}.{migration.name}:{direction}')
    return names


def migration_plan_sha256(names: list[str]) -> str:
    payload = json.dumps(names, separators=(',', ':'), ensure_ascii=True)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def validate_release_reference(
    value: object, *, field_name: str, min_length: int = 2, max_length: int = 255,
) -> str:
    text = str(value or '').strip()
    if (
        not _REFERENCE_PATTERN.fullmatch(text)
        or len(text) < min_length
        or len(text) > max_length
        or text.casefold() in _PLACEHOLDERS
        or '://' in text
    ):
        raise ValueError(
            f'{field_name} must be an immutable, non-secret deployment/provider reference '
            f'using {min_length}-{max_length} safe characters.'
        )
    return text


def serialize_readiness(issues) -> dict:
    rows = [
        {'severity': item.severity, 'code': item.code, 'message': item.message}
        for item in issues
    ]
    return {'passed': not rows, 'issues': rows}


def existing_release(release_id: str):
    """Read existing evidence when its migration is already installed."""
    if ProductionReleaseAudit._meta.db_table not in connection.introspection.table_names():
        return None
    return ProductionReleaseAudit.objects.filter(release_id=release_id).first()


@transaction.atomic
def reserve_release_evidence(
    *, release_id: str, backup_reference: str, actor: str, environment: str,
    migration_names: list[str], readiness_results: dict, started_at,
) -> ProductionReleaseAudit | None:
    """Persist the reviewed plan before migrate when the audit table exists."""
    if ProductionReleaseAudit._meta.db_table not in connection.introspection.table_names():
        return None
    audit = ProductionReleaseAudit.objects.select_for_update().filter(
        release_id=release_id,
    ).first()
    if audit:
        if (
            audit.backup_reference != backup_reference
            or audit.actor != actor
            or audit.environment != environment
        ):
            raise ValueError(
                'An existing release ID cannot be rebound to different backup, actor, or environment evidence.'
            )
        if migration_names and audit.migration_names and audit.migration_names != migration_names:
            raise ValueError('An existing release ID cannot be reused for a different migration plan.')
        return audit
    audit = ProductionReleaseAudit(
        release_id=release_id,
        backup_reference=backup_reference,
        actor=actor,
        environment=environment,
        attempt_count=0,
        started_at=started_at,
    )
    audit.status = audit.STATUS_PREFLIGHT_PASSED
    audit.migration_names = migration_names
    audit.migration_plan_sha256 = migration_plan_sha256(migration_names)
    audit.readiness_results = readiness_results
    audit.failure_code = ''
    audit.save()
    return audit


@transaction.atomic
def record_release_evidence(
    *, release_id: str, backup_reference: str, actor: str, environment: str,
    status: str, migration_names: list[str], readiness_results: dict,
    started_at, migrations_completed_at=None, post_check_passed: bool = False,
    bootstrap_result: str = '', failure_code: str = '',
) -> ProductionReleaseAudit:
    audit = ProductionReleaseAudit.objects.select_for_update().filter(
        release_id=release_id,
    ).first()
    if audit:
        if (
            audit.backup_reference != backup_reference
            or audit.actor != actor
            or audit.environment != environment
        ):
            raise ValueError(
                'An existing release ID cannot be rebound to different backup, actor, or environment evidence.'
            )
        if migration_names and audit.migration_names and audit.migration_names != migration_names:
            raise ValueError('An existing release ID cannot be reused for a different migration plan.')
        audit.attempt_count += 1
        if not migration_names:
            migration_names = list(audit.migration_names or [])
    else:
        audit = ProductionReleaseAudit(
            release_id=release_id,
            backup_reference=backup_reference,
            actor=actor,
            environment=environment,
            started_at=started_at,
        )
    audit.status = status
    audit.migration_names = migration_names
    audit.migration_plan_sha256 = migration_plan_sha256(migration_names)
    audit.readiness_results = readiness_results
    audit.post_migration_check_passed = post_check_passed
    audit.superuser_bootstrap_result = bootstrap_result
    audit.failure_code = failure_code
    if migrations_completed_at is not None:
        audit.migrations_completed_at = migrations_completed_at
    recorded_at = timezone.now()
    audit.completed_at = recorded_at if status == audit.STATUS_COMPLETED else None
    attempt_history = list(audit.attempt_history or [])
    attempt_history.append({
        'attempt': audit.attempt_count,
        'status': status,
        'failure_code': failure_code,
        'migration_names': list(migration_names),
        'migration_plan_sha256': audit.migration_plan_sha256,
        'readiness_results': readiness_results,
        'post_migration_check_passed': post_check_passed,
        'superuser_bootstrap_result': bootstrap_result,
        'started_at': started_at.isoformat(),
        'migrations_completed_at': (
            migrations_completed_at.isoformat() if migrations_completed_at else None
        ),
        'recorded_at': recorded_at.isoformat(),
    })
    audit.attempt_history = attempt_history
    audit.save()
    return audit
