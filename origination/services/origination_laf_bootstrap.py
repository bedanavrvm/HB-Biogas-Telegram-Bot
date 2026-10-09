"""Opt-in, resumable release bootstrap of reviewed, unassigned blank documents."""
from dataclasses import asdict, replace
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from core.models import ComplianceAuditEvent, IntegrationOperation
from core.services.compliance_audit import record_event
from core.services.external_resilience import external_call_budget, reserve_operation
from origination.services.origination_main_laf_seeds import (
    DEFINITIONS as MAIN_DEFINITIONS, apply_seed, preflight_seed,
)
from origination.services.origination_support_laf_seeds import DEFINITIONS as SUPPORT_DEFINITIONS


ASSET_ROOT = Path(__file__).resolve().parents[1] / 'assets' / 'lafs'
SOURCE_DEFINITIONS = tuple(item for item in MAIN_DEFINITIONS if item.key != 'water_tank') + SUPPORT_DEFINITIONS
# Increment when compilation changes without a semantic seed change.
BOOTSTRAP_CONTRACT_VERSION = 1
LEASE = timedelta(minutes=30)


class LafBootstrapError(ValueError):
    pass


def bundled_definitions():
    # Optional assets must not break Django startup when bootstrap is disabled.
    try:
        bundle = json.loads((ASSET_ROOT / 'manifest.json').read_text(encoding='utf-8'))
        if set(bundle) != {item.key for item in SOURCE_DEFINITIONS}:
            raise ValueError('Unexpected bundle inventory.')
        return tuple(replace(item, sha256=bundle[item.key]['sha256'], byte_size=bundle[item.key]['byte_size'])
                     for item in SOURCE_DEFINITIONS)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise LafBootstrapError('The reviewed blank LAF bundle is missing or invalid. Restore the deployment assets.') from exc


def bootstrap_fingerprint(definitions=None) -> str:
    definitions = bundled_definitions() if definitions is None else definitions
    contract = {'version': BOOTSTRAP_CONTRACT_VERSION,
                'shared_values': True, 'unassigned': True,
                'sources': [item.sha256 for item in SOURCE_DEFINITIONS],
                'definitions': [asdict(item) for item in definitions]}
    return hashlib.sha256(json.dumps(contract, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _actor(username):
    actor = get_user_model().objects.filter(username=str(username or '').strip(),
                                           is_active=True, is_superuser=True).first()
    if actor is None:
        raise LafBootstrapError('Set ORIGINATION_LAF_BOOTSTRAP_ACTOR to an existing active Superuser username.')
    return actor


def bootstrap_lafs(*, apply=False, force=False, actor_username=None, laf_root=None) -> dict:
    """Dry run by default. Force is an explicit command-only recreation request.

    Per-document commits retain successful uploads after a later failure. A
    database lease serializes first requests; completion is recorded outside
    catalogue rows so deletion never implicitly re-enables automatic seeding.
    """
    if force and not apply:
        raise LafBootstrapError('--force requires --apply.')
    actor = _actor(actor_username or getattr(settings, 'ORIGINATION_LAF_BOOTSTRAP_ACTOR', ''))
    definitions = bundled_definitions()
    fingerprint = bootstrap_fingerprint(definitions)
    completed_key = f'origination:laf-bootstrap:completed:{fingerprint}'
    if not force and ComplianceAuditEvent.objects.filter(deduplication_key=completed_key).exists():
        return {'status': 'already_completed', 'fingerprint': fingerprint}
    root = Path(laf_root) if laf_root else ASSET_ROOT
    # Validate every source and existing canonical field before the first write.
    for definition in definitions:
        preflight_seed(definition, laf_root=root, unassigned=True)
    if not apply:
        return {'status': 'dry_run', 'fingerprint': fingerprint, 'documents': len(definitions)}
    operation, _ = reserve_operation(
        integration=IntegrationOperation.INTEGRATION_GOOGLE_DRIVE,
        operation_type='origination_laf_bootstrap',
        deduplication_key=f'origination:laf-bootstrap:{fingerprint}',
        requested_by=actor, source_model='OriginationLafBootstrap', source_id=fingerprint,
        operation_payload={'fingerprint': fingerprint}, max_attempts=100,
    )
    token = uuid.uuid4().hex
    with transaction.atomic():
        operation = IntegrationOperation.objects.select_for_update().get(pk=operation.pk)
        if not force and ComplianceAuditEvent.objects.filter(deduplication_key=completed_key).exists():
            return {'status': 'already_completed', 'fingerprint': fingerprint}
        if operation.status == operation.STATUS_RUNNING and operation.last_attempt_at and (
            timezone.now() - operation.last_attempt_at < LEASE
        ):
            return {'status': 'running', 'fingerprint': fingerprint}
        operation.status = operation.STATUS_RUNNING
        operation.last_attempt_at = timezone.now()
        operation.attempts += 1
        operation.completed_at = None
        operation.last_error = ''
        operation.last_error_code = ''
        operation.metadata = {**operation.metadata, 'attempt_token': token, 'forced': force}
        operation.save()
    try:
        for definition in definitions:
            with transaction.atomic():
                current = IntegrationOperation.objects.select_for_update().get(pk=operation.pk)
                if current.metadata.get('attempt_token') != token:
                    raise LafBootstrapError('Another bootstrap attempt has taken over. Retry after it finishes.')
                current.last_attempt_at = timezone.now()
                current.save(update_fields=['last_attempt_at', 'updated_at'])
            with external_call_budget(120):
                result = apply_seed(definition, laf_root=root, actor=actor, shared_values=True, unassigned=True)
            with transaction.atomic():
                current = IntegrationOperation.objects.select_for_update().get(pk=operation.pk)
                if current.metadata.get('attempt_token') != token:
                    raise LafBootstrapError('Bootstrap ownership changed before completion.')
                current.metadata = {**current.metadata, 'last_completed_seed': definition.key,
                                    'last_template_id': str(result['template'].pk)}
                current.save(update_fields=['metadata', 'updated_at'])
        with transaction.atomic():
            current = IntegrationOperation.objects.select_for_update().get(pk=operation.pk)
            if current.metadata.get('attempt_token') != token:
                raise LafBootstrapError('Bootstrap ownership changed before completion.')
            record_event(
                workflow='loan_origination', action='laf.bootstrap_completed', category='configuration',
                subject_type='OriginationLafBootstrap', subject_id=fingerprint,
                actor=actor, authority_user=actor, request_id=token,
                deduplication_key=f'{completed_key}:force:{token}' if force else completed_key,
                after_values={'fingerprint': fingerprint, 'documents': len(definitions), 'forced': force},
            )
            # A forced first run also establishes the automatic completion marker.
            if force and not ComplianceAuditEvent.objects.filter(deduplication_key=completed_key).exists():
                record_event(
                    workflow='loan_origination', action='laf.bootstrap_completed', category='configuration',
                    subject_type='OriginationLafBootstrap', subject_id=fingerprint,
                    actor=actor, authority_user=actor, request_id=token, deduplication_key=completed_key,
                    after_values={'fingerprint': fingerprint, 'documents': len(definitions)},
                )
            current.status = current.STATUS_SUCCEEDED
            current.completed_at = timezone.now()
            current.save(update_fields=['status', 'completed_at', 'updated_at'])
    except Exception as exc:
        IntegrationOperation.objects.filter(pk=operation.pk, metadata__attempt_token=token).update(
            status=IntegrationOperation.STATUS_RETRYABLE, last_error_code=type(exc).__name__[:80],
            last_error='LAF bootstrap did not complete; successful drafts are retained. Retry the bootstrap command.',
        )
        raise LafBootstrapError('LAF bootstrap did not complete. Successful drafts are retained; retry the bootstrap command.') from exc
    return {'status': 'completed', 'fingerprint': fingerprint, 'documents': len(definitions)}


def bootstrap_lafs_from_environment() -> dict:
    if not getattr(settings, 'ORIGINATION_LAF_BOOTSTRAP_ENABLED', False):
        return {'status': 'disabled'}
    return bootstrap_lafs(apply=True)
