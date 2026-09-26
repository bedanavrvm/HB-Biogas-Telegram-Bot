"""Durable, paced publication of Portal records to Google.

Portal changes commit locally first and reserve publication work in
``IntegrationOperation``. FarmUp may advance one scoped operation per visible
request; the optional management command can drain work independently.
"""

from __future__ import annotations

from typing import Any
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from core.models import IntegrationOperation
from core.services.external_resilience import ExternalOperationError, execute_operation, reserve_operation


MASTER_OPERATION = 'jawabu_master_publish'
INTERNAL_ORDER_OPERATION = 'jawabu_internal_order_publish'
SOURCE_MODEL = 'JawabuFarmerMaster'
PORTAL_PUBLICATION_RUNNER = 'portal_sheet_publications'


def publication_scheduler_health(*, now=None) -> dict[str, Any]:
    """Aggregate queue and runner freshness for Operations/IT oversight."""
    from core.models import DurableJobRunnerHeartbeat

    current = now or timezone.now()
    queued = IntegrationOperation.objects.filter(
        integration=IntegrationOperation.INTEGRATION_GOOGLE_SHEETS,
        source_model=SOURCE_MODEL,
        operation_type__in=(MASTER_OPERATION, INTERNAL_ORDER_OPERATION),
        status__in=(IntegrationOperation.STATUS_PENDING, IntegrationOperation.STATUS_RETRYABLE,
                    IntegrationOperation.STATUS_RUNNING),
    ).count()
    runner = DurableJobRunnerHeartbeat.objects.filter(runner_key=PORTAL_PUBLICATION_RUNNER).first()
    fresh = bool(runner and runner.heartbeat_at >= current - timedelta(minutes=3)
                 and runner.status != DurableJobRunnerHeartbeat.STATUS_FAILED)
    recent_attempt = IntegrationOperation.objects.filter(
        integration=IntegrationOperation.INTEGRATION_GOOGLE_SHEETS,
        source_model=SOURCE_MODEL,
        operation_type__in=(MASTER_OPERATION, INTERNAL_ORDER_OPERATION),
        last_attempt_at__gte=current - timedelta(minutes=3),
    ).exists()
    return {'queued': queued, 'healthy': fresh or recent_attempt, 'runner_status': runner.status if runner else 'never_run',
            'last_run_at': runner.heartbeat_at.isoformat() if runner else None}


class PortalPublicationError(RuntimeError):
    """A Google register could not publish this canonical Portal record."""


class PortalIdentityConflictError(PortalPublicationError):
    """A Sheet row is owned by another case; retries cannot resolve it."""

    safe_error_code = 'identity_conflict'


def _targets_for_farmer() -> list[str]:
    """Return enabled register targets without performing an external call."""
    # Imported lazily so pipeline services can reserve work without a module
    # import cycle during Django startup.
    from core.services.jawabu_pipeline import _jawabu_group_config

    group_config = _jawabu_group_config()
    if not group_config:
        return []
    workflow = getattr(group_config, 'workflow', None) or {}
    targets = []
    if workflow.get('master_sync_enabled'):
        targets.append(MASTER_OPERATION)
    if (
        workflow.get('internal_order_sync_enabled')
        and str(workflow.get('internal_order_sheet_id') or '').strip()
        and str(workflow.get('internal_order_sheet_name') or 'Orders').strip()
    ):
        targets.append(INTERNAL_ORDER_OPERATION)
    return targets


def reserve_farmer_publication(
    farmer,
    *,
    request_id: str = '',
    requested_by=None,
    requested_by_label: str = '',
    required_capability: str = 'portal.case.read',
    deduplication_namespace: str = '',
    extra_metadata: dict | None = None,
    operation_types: list[str] | tuple[str, ...] | None = None,
) -> list[IntegrationOperation]:
    """Reserve idempotent register publications for the farmer's revision.

    Only opaque identifiers and revision metadata are retained.  Fresh data is
    read from Django at execution time so a newer revision cannot publish stale
    case values.
    """
    revision = int(getattr(farmer, 'workflow_revision', 0) or 0)
    operations = []
    namespace = str(deduplication_namespace or '').strip()
    enabled_targets = _targets_for_farmer()
    requested_targets = list(operation_types) if operation_types is not None else enabled_targets
    for operation_type in requested_targets:
        if operation_type not in enabled_targets:
            continue
        deduplication_key = (
            f'portal-publication:{namespace}:{farmer.pk}:{revision}:{operation_type}'
            if namespace else f'portal-publication:{farmer.pk}:{revision}:{operation_type}'
        )
        operation, _ = reserve_operation(
            integration=IntegrationOperation.INTEGRATION_GOOGLE_SHEETS,
            operation_type=operation_type,
            deduplication_key=deduplication_key,
            source_model=SOURCE_MODEL,
            source_id=str(farmer.pk),
            request_id=str(request_id or '')[:128],
            requested_by=requested_by,
            requested_by_label=str(requested_by_label or '')[:255],
            operation_payload=(str(farmer.pk), revision, operation_type),
            metadata={
                'workflow_revision': revision, 'target': operation_type,
                'required_capability': str(required_capability or 'portal.case.read'),
                **dict(extra_metadata or {}),
            },
        )
        operations.append(operation)
    return operations


def _current_operations(farmer) -> list[IntegrationOperation]:
    revision = int(getattr(farmer, 'workflow_revision', 0) or 0)
    rows = IntegrationOperation.objects.filter(
        source_model=SOURCE_MODEL,
        source_id=str(farmer.pk),
        operation_type__in=[MASTER_OPERATION, INTERNAL_ORDER_OPERATION],
    ).order_by('-created_at')
    latest: dict[str, IntegrationOperation] = {}
    for row in rows:
        if int((row.metadata or {}).get('workflow_revision', -1)) != revision:
            continue
        latest.setdefault(row.operation_type, row)
    return list(latest.values())


def publication_payload(farmer) -> dict[str, Any]:
    """Small, user-safe state for the current record revision."""
    operations = _current_operations(farmer)
    if not operations:
        return {'status': 'not_required', 'operations': [], 'pending_operation_ids': []}
    status_rank = {
        IntegrationOperation.STATUS_DEAD_LETTER: 'needs_attention',
        IntegrationOperation.STATUS_RUNNING: 'publishing',
        IntegrationOperation.STATUS_PENDING: 'pending',
        IntegrationOperation.STATUS_RETRYABLE: 'pending',
        IntegrationOperation.STATUS_SUCCEEDED: 'synced',
    }
    statuses = [status_rank.get(row.status, 'pending') for row in operations]
    if 'needs_attention' in statuses:
        overall = 'needs_attention'
    elif 'publishing' in statuses:
        overall = 'publishing'
    elif 'pending' in statuses:
        overall = 'pending'
    else:
        overall = 'synced'
    return {
        'status': overall,
        'operations': [
            {
                'id': str(row.pk),
                'target': row.operation_type,
                'status': status_rank.get(row.status, 'pending'),
                'issue': 'identity_review' if row.last_error_code == 'identity_conflict' else '',
                'attempts': int(row.attempts or 0),
                'next_retry_at': row.next_retry_at.isoformat() if row.next_retry_at else None,
            }
            for row in operations
        ],
        'pending_operation_ids': [
            str(row.pk) for row in operations
            if row.status in {
                IntegrationOperation.STATUS_PENDING,
                IntegrationOperation.STATUS_RETRYABLE,
            }
        ],
    }


def requeue_publication_after_review(
    operation: IntegrationOperation,
    *,
    request_id: str,
    requested_by=None,
    requested_by_label: str = '',
) -> tuple[IntegrationOperation, bool]:
    """Create one fresh, auditable retry after an exhausted publication fails.

    A dead-letter operation is immutable evidence of its failed attempt.  Do
    not reset it in place: reserve a replacement bound to the same case and
    revision, so a staff member can explicitly retry from the Portal without
    losing the failure history.
    """
    operation.refresh_from_db()
    if operation.source_model != SOURCE_MODEL or operation.operation_type not in {
        MASTER_OPERATION, INTERNAL_ORDER_OPERATION,
    }:
        raise ValueError('This is not a Portal register publication operation.')
    if operation.status != IntegrationOperation.STATUS_DEAD_LETTER:
        return operation, False

    from core.models import JawabuFarmerMaster

    farmer = JawabuFarmerMaster.objects.filter(pk=operation.source_id).first()
    if farmer is None:
        raise ValueError('The source case is no longer available.')
    if int((operation.metadata or {}).get('workflow_revision', -1)) != int(farmer.workflow_revision or 0):
        raise ValueError('This sync belongs to an older case version. Refresh before retrying.')
    current = next((row for row in _current_operations(farmer)
                    if row.operation_type == operation.operation_type), None)
    if current is not None and current.pk != operation.pk:
        raise ValueError('A newer sync attempt exists for this case. Refresh its current status.')
    replacements = reserve_farmer_publication(
        farmer,
        request_id=request_id,
        requested_by=requested_by,
        requested_by_label=requested_by_label,
        required_capability=str((operation.metadata or {}).get('required_capability') or 'portal.case.read'),
        # This stable namespace makes a repeated tap a replay of the same
        # reviewed retry, while a later dead-letter replacement gets its own
        # explicit retry chain.
        deduplication_namespace=f'manual-retry:{operation.pk}',
        operation_types=[operation.operation_type],
        extra_metadata={
            'retry_of_operation_id': str(operation.pk), 'retry_reason': 'staff_reviewed',
            **{key: (operation.metadata or {})[key] for key in ('farmup_worklist_id', 'farmup_period')
               if key in (operation.metadata or {})},
        },
    )
    if not replacements:
        raise ValueError('This Google Sheet publication is disabled in the current Portal configuration.')
    replacement = replacements[0]
    return replacement, replacement.pk != operation.pk


def _record_master_failure_context(operation: IntegrationOperation, farmer, context: dict) -> None:
    """Persist safe field-level publication evidence for the staff retry view."""
    metadata = dict(operation.metadata or {})
    fields = sorted({str(value)[:120] for value in (context.get('field_names') or []) if str(value).strip()})
    metadata['failure_context'] = {
        'case_reference': str(getattr(farmer, 'case_reference_number', '') or ''),
        'phase': str(context.get('phase') or 'unknown')[:40],
        'sheet_tab': str(context.get('sheet_tab') or '')[:120],
        'fields_checked': bool(context.get('fields_checked')),
        'field_names': fields[:30],
        'detail': str(context.get('detail') or '')[:255],
    }
    operation.metadata = metadata
    operation.save(update_fields=['metadata', 'updated_at'])


def attempt_publication(operation: IntegrationOperation) -> dict[str, Any]:
    """Perform exactly one bounded Google publication attempt for one record."""
    from core.models import JawabuFarmerMaster
    from core.services.jawabu_pipeline import (
        sync_farmer_to_internal_order_sheet,
        sync_farmer_to_master_sheet,
    )

    if operation.source_model != SOURCE_MODEL or operation.operation_type not in {
        MASTER_OPERATION, INTERNAL_ORDER_OPERATION,
    }:
        raise ValueError('This is not a Portal register publication operation.')
    operation.refresh_from_db()
    farmer = JawabuFarmerMaster.objects.filter(pk=operation.source_id).first()
    if farmer is None:
        raise ValueError('The source case is no longer available.')
    if operation.operation_type == MASTER_OPERATION:
        # A monthly FarmUp commit can reserve hundreds of rows. Never let a
        # later case take a lower Sheet row just because the earlier case is
        # paced, retrying, or currently owned by another worker.
        oldest_id = IntegrationOperation.objects.filter(
            integration=IntegrationOperation.INTEGRATION_GOOGLE_SHEETS,
            source_model=SOURCE_MODEL,
            operation_type=MASTER_OPERATION,
            status__in=(
                IntegrationOperation.STATUS_PENDING,
                IntegrationOperation.STATUS_RETRYABLE,
                IntegrationOperation.STATUS_RUNNING,
            ),
        ).order_by('created_at', 'pk').values_list('pk', flat=True).first()
        if oldest_id != operation.pk:
            return {'operation': operation, 'farmer': farmer, 'result': None, 'deferred': True}
    if operation.next_retry_at and operation.next_retry_at > timezone.now():
        return {'operation': operation, 'farmer': farmer, 'result': None, 'deferred': True}
    operation_revision = int((operation.metadata or {}).get('workflow_revision') or 0)
    if operation_revision != int(farmer.workflow_revision or 0):
        # A newer canonical state will publish its own operation.  Completing
        # this one as superseded preserves the audit record without writing
        # obsolete values to Sheets.
        result = execute_operation(
            operation,
            lambda: {'action': 'superseded'},
            attempt_budget=1,
            min_spacing_seconds=getattr(settings, 'PORTAL_PUBLICATION_MIN_SPACING_SECONDS', 5),
            paced_operation_types=(MASTER_OPERATION, INTERNAL_ORDER_OPERATION),
        )
        return {'operation': operation, 'farmer': farmer, 'result': result, 'superseded': True}

    def publish_once():
        if operation.operation_type == MASTER_OPERATION:
            failure_context: dict[str, Any] = {}
            completed = sync_farmer_to_master_sheet(farmer, failure_context=failure_context)
            if not completed:
                _record_master_failure_context(operation, farmer, failure_context)
        else:
            completed = sync_farmer_to_internal_order_sheet(farmer)
        if not completed:
            if operation.operation_type == MASTER_OPERATION and failure_context.get('phase') == 'identity':
                raise PortalIdentityConflictError('The Sheet row needs identity review.')
            # The low-level publisher intentionally keeps Google details in
            # protected logs.  This marker is retryable by the shared policy.
            error = PortalPublicationError('Google register is temporarily unavailable.')
            if operation.operation_type == MASTER_OPERATION and failure_context.get('provider_status') == 429:
                error.status_code = 429
            raise error
        return {'action': operation.operation_type}

    try:
        result = execute_operation(
            operation, publish_once, attempt_budget=1,
            min_spacing_seconds=getattr(settings, 'PORTAL_PUBLICATION_MIN_SPACING_SECONDS', 5),
            paced_operation_types=(MASTER_OPERATION, INTERNAL_ORDER_OPERATION),
        )
    except ExternalOperationError:
        operation.refresh_from_db()
        return {'operation': operation, 'farmer': farmer, 'result': None, 'error': True}
    operation.refresh_from_db()
    return {'operation': operation, 'farmer': farmer, 'result': result, 'error': False}
