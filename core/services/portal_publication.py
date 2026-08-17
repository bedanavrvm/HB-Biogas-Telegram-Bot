"""Durable, request-assisted publication of Portal records to Google.

Free Render has no durable worker process.  Portal changes therefore commit
locally first and reserve publication work in ``IntegrationOperation``.  The
Mini App makes small, authenticated follow-up requests; each request performs
at most one bounded external attempt and the next Portal visit resumes due
work.  This is deliberately not a process-local background queue.
"""

from __future__ import annotations

from typing import Any

from django.utils import timezone

from core.models import IntegrationOperation
from core.services.external_resilience import ExternalOperationError, execute_operation, reserve_operation


MASTER_OPERATION = 'jawabu_master_publish'
INTERNAL_ORDER_OPERATION = 'jawabu_internal_order_publish'
SOURCE_MODEL = 'JawabuFarmerMaster'


class PortalPublicationError(RuntimeError):
    """A Google register could not publish this canonical Portal record."""


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
) -> list[IntegrationOperation]:
    """Reserve idempotent register publications for the farmer's revision.

    Only opaque identifiers and revision metadata are retained.  Fresh data is
    read from Django at execution time so a newer revision cannot publish stale
    case values.
    """
    revision = int(getattr(farmer, 'workflow_revision', 0) or 0)
    operations = []
    for operation_type in _targets_for_farmer():
        operation, _ = reserve_operation(
            integration=IntegrationOperation.INTEGRATION_GOOGLE_SHEETS,
            operation_type=operation_type,
            deduplication_key=f'portal-publication:{farmer.pk}:{revision}:{operation_type}',
            source_model=SOURCE_MODEL,
            source_id=str(farmer.pk),
            request_id=str(request_id or '')[:128],
            requested_by=requested_by,
            requested_by_label=str(requested_by_label or '')[:255],
            operation_payload=(str(farmer.pk), revision, operation_type),
            metadata={
                'workflow_revision': revision, 'target': operation_type,
                'required_capability': str(required_capability or 'portal.case.read'),
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
        if int((row.metadata or {}).get('workflow_revision') or -1) != revision:
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
    farmer = JawabuFarmerMaster.objects.filter(pk=operation.source_id).first()
    if farmer is None:
        raise ValueError('The source case is no longer available.')
    operation_revision = int((operation.metadata or {}).get('workflow_revision') or 0)
    if operation_revision != int(farmer.workflow_revision or 0):
        # A newer canonical state will publish its own operation.  Completing
        # this one as superseded preserves the audit record without writing
        # obsolete values to Sheets.
        result = execute_operation(
            operation,
            lambda: {'action': 'superseded'},
            attempt_budget=1,
        )
        return {'operation': operation, 'farmer': farmer, 'result': result, 'superseded': True}

    def publish_once():
        if operation.operation_type == MASTER_OPERATION:
            completed = sync_farmer_to_master_sheet(farmer)
        else:
            completed = sync_farmer_to_internal_order_sheet(farmer)
        if not completed:
            # The low-level publisher intentionally keeps Google details in
            # protected logs.  This marker is retryable by the shared policy.
            raise PortalPublicationError('Google register is temporarily unavailable.')
        return {'action': operation.operation_type}

    try:
        result = execute_operation(operation, publish_once, attempt_budget=1)
    except ExternalOperationError:
        operation.refresh_from_db()
        return {'operation': operation, 'farmer': farmer, 'result': None, 'error': True}
    operation.refresh_from_db()
    return {'operation': operation, 'farmer': farmer, 'result': result, 'error': False}
