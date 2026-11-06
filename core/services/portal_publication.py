"""Durable, paced publication of Portal records to Google.

Portal changes commit locally first and reserve publication work in
``IntegrationOperation``. A visible Portal session may advance the oldest
eligible operation without blocking the staff member's workflow.
"""

from __future__ import annotations

from typing import Any
from datetime import timedelta
import hashlib
import json
import math
import logging

from django.conf import settings
from django.db.models import Q, Exists, OuterRef, Value, CharField, Case, When, IntegerField
from django.db.models.functions import Coalesce, Cast
from django.db.models.fields.json import KeyTextTransform
from django.utils import timezone

from core.models import IntegrationOperation
from core.services.external_resilience import ExternalCircuitOpen, ExternalOperationError, execute_operation, reserve_operation, operation_lease_seconds, external_call_budget


MASTER_OPERATION = 'jawabu_master_publish'
INTERNAL_ORDER_OPERATION = 'jawabu_internal_order_publish'
SOURCE_MODEL = 'JawabuFarmerMaster'
PORTAL_PUBLICATION_RUNNER = 'portal_sheet_publications'
logger = logging.getLogger(__name__)


def _with_destination(queryset):
    return queryset.annotate(destination_fifo_key=Coalesce(
        KeyTextTransform('destination_key', 'metadata'), Value('__legacy__'), output_field=CharField(),
    ))


def _blocked_source_ids():
    from core.models import JawabuFarmerMaster
    from portal_legacy.fence import blocked_cases
    return blocked_cases(JawabuFarmerMaster.objects.all()).annotate(
        legacy_source_id=Cast('pk', CharField())).values('legacy_source_id')


def _master_blocker(operation):
    if operation.operation_type != MASTER_OPERATION:
        return None
    key = (operation.metadata or {}).get('destination_key', '__legacy__')
    older = _with_destination(IntegrationOperation.objects.filter(
        integration=operation.integration, source_model=SOURCE_MODEL, operation_type=MASTER_OPERATION,
        status__in=(IntegrationOperation.STATUS_PENDING, IntegrationOperation.STATUS_RETRYABLE, IntegrationOperation.STATUS_RUNNING),
    )).exclude(source_id__in=_blocked_source_ids()).filter(destination_fifo_key=key).filter(
        Q(created_at__lt=operation.created_at) | Q(created_at=operation.created_at, pk__lt=operation.pk)
    )
    if _updates_existing_row(operation):
        older = older.filter(source_id=operation.source_id)
    return older.order_by('created_at', 'pk').first()


def _published_rows():
    return _with_destination(IntegrationOperation.objects.filter(
        operation_type=MASTER_OPERATION, status=IntegrationOperation.STATUS_SUCCEEDED,
        metadata__result__action=MASTER_OPERATION,
    ))


def _updates_existing_row(operation):
    return operation.operation_type == MASTER_OPERATION and _published_rows().filter(
        source_model=SOURCE_MODEL, source_id=operation.source_id,
        destination_fifo_key=(operation.metadata or {}).get('destination_key', '__legacy__'),
        created_at__lt=operation.created_at,
    ).exists()


def _master_claim_in_order(operation):
    return _master_blocker(operation) is None


def publication_deferral(operation, *, farmer=None):
    """Explain a pending operation without exposing another case or contacting Google."""
    from core.models import IntegrationCircuitState
    from portal_legacy.fence import case_blocked
    now = timezone.now()
    reason, message, due = '', '', None
    if operation.status == IntegrationOperation.STATUS_SUCCEEDED:
        return {'deferred':False, 'deferred_reason':'', 'waiting_reason':'', 'retry_after_seconds':0, 'next_retry_at':None}
    if farmer is not None and case_blocked(farmer):
        reason, message = 'legacy_hold', 'This case is held by an unfinished legacy changeover.'
    else:
        circuit = IntegrationCircuitState.objects.filter(integration=operation.integration).first()
        if circuit and circuit.status in {circuit.STATUS_OPEN, circuit.STATUS_HALF_OPEN} and circuit.next_probe_at and circuit.next_probe_at > now:
            reason, message, due = 'circuit_cooldown', 'Google publishing is cooling down after integration failures.', circuit.next_probe_at
        elif operation.next_retry_at and operation.next_retry_at > now:
            reason = 'pacing' if operation.status == IntegrationOperation.STATUS_PENDING and not operation.last_error_code else 'provider_backoff'
            message = 'Waiting for the Sheet write interval.' if reason == 'pacing' else 'Waiting for the scheduled retry after the last Google failure.'
            due = operation.next_retry_at
        elif operation.status == IntegrationOperation.STATUS_RUNNING:
            reason, message = 'active_worker', 'Another worker is processing this update.'
            due = (operation.last_attempt_at or operation.updated_at) + timedelta(seconds=operation_lease_seconds())
        elif operation.status == IntegrationOperation.STATUS_DEAD_LETTER:
            reason, message = 'needs_attention', 'Automatic attempts stopped; review the recorded failure before retrying.'
        else:
            blocker = _master_blocker(operation)
            if blocker:
                reason, message = 'fifo', 'An earlier update must finish before this register can advance.'
                due = blocker.next_retry_at
            else:
                reason, message = 'queued', 'The update remains queued for the publisher.'
    if due and due > now:
        message += ' Next attempt after ' + timezone.localtime(due).strftime('%d-%b %H:%M:%S EAT') + '.'
    return {'deferred':True, 'deferred_reason':reason, 'waiting_reason':message,
            'retry_after_seconds':max(1, math.ceil((due-now).total_seconds())) if due else 5,
            'next_retry_at':due.isoformat() if due else None}


def queued_publication_operations():
    """Eligible work, preserving Master/Eco FIFO across all FarmUp worklists."""
    now = timezone.now()
    lease_seconds = operation_lease_seconds()
    masters = _with_destination(IntegrationOperation.objects.filter(
        integration=IntegrationOperation.INTEGRATION_GOOGLE_SHEETS,
        source_model=SOURCE_MODEL, operation_type=MASTER_OPERATION,
        status__in=(IntegrationOperation.STATUS_PENDING, IntegrationOperation.STATUS_RETRYABLE,
                    IntegrationOperation.STATUS_RUNNING),
    ))
    masters = masters.exclude(source_id__in=_blocked_source_ids())
    older = masters.filter(destination_fifo_key=OuterRef('destination_fifo_key')).filter(
        Q(created_at__lt=OuterRef('created_at')) | Q(created_at=OuterRef('created_at'), pk__lt=OuterRef('pk'))
    )
    due = (Q(status__in=(IntegrationOperation.STATUS_PENDING, IntegrationOperation.STATUS_RETRYABLE))
           & (Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=now)))
    stale_running = Q(status=IntegrationOperation.STATUS_RUNNING,
                      last_attempt_at__lte=now - timedelta(seconds=lease_seconds))
    previous_row = _published_rows().filter(source_model=SOURCE_MODEL, source_id=OuterRef('source_id'),
        destination_fifo_key=OuterRef('destination_fifo_key'), created_at__lt=OuterRef('created_at'))
    same_case_older = older.filter(source_id=OuterRef('source_id'))
    return _with_destination(IntegrationOperation.objects.filter(
        integration=IntegrationOperation.INTEGRATION_GOOGLE_SHEETS,
        source_model=SOURCE_MODEL,
        operation_type__in=(MASTER_OPERATION, INTERNAL_ORDER_OPERATION),
    )).exclude(source_id__in=_blocked_source_ids()).annotate(
        has_earlier=Exists(older), has_case_earlier=Exists(same_case_older), existing_row=Exists(previous_row),
    ).filter(due | stale_running).filter(
        Q(operation_type=INTERNAL_ORDER_OPERATION) | Q(has_earlier=False)
        | Q(existing_row=True, has_case_earlier=False)
    ).annotate(update_priority=Case(When(existing_row=True, then=Value(0)), default=Value(1), output_field=IntegerField())
    ).order_by('update_priority', 'created_at', 'pk')


def publication_queue_status() -> dict[str, Any]:
    """Opaque queue status for an authenticated Portal session."""
    active = IntegrationOperation.objects.filter(
        integration=IntegrationOperation.INTEGRATION_GOOGLE_SHEETS,
        source_model=SOURCE_MODEL,
        operation_type__in=(MASTER_OPERATION, INTERNAL_ORDER_OPERATION),
        status__in=(IntegrationOperation.STATUS_PENDING, IntegrationOperation.STATUS_RETRYABLE,
                    IntegrationOperation.STATUS_RUNNING),
    )
    from django.db.models import Min, Count
    timing = active.aggregate(next_retry=Min('next_retry_at'), oldest=Min('created_at'),
                              running=Count('pk', filter=Q(status=IntegrationOperation.STATUS_RUNNING)))
    return {'queued': active.count(), 'due': queued_publication_operations().exists(),
            'running': timing['running'],
            'next_retry_at': timing['next_retry'].isoformat() if timing['next_retry'] else None,
            'oldest_queued_at': timing['oldest'].isoformat() if timing['oldest'] else None}


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


class PortalRegisterReviewError(PortalPublicationError):
    """A local register/configuration problem is not a Google service outage."""

    def __init__(self, phase):
        super().__init__('The register needs configuration or row review.')
        self.safe_error_code = {'configuration':'sheet_configuration', 'schema':'sheet_schema',
                                'verify':'sheet_row_changed', 'row_missing':'sheet_row_missing'}[phase]


def _targets_for_farmer(farmer=None) -> list[str]:
    """Return enabled register targets without performing an external call."""
    # Imported lazily so pipeline services can reserve work without a module
    # import cycle during Django startup.
    from core.services.jawabu_pipeline import _jawabu_group_config

    group_config = _jawabu_group_config(farmer)
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


def _destination_for_farmer(farmer, operation_type):
    from core.services.jawabu_pipeline import _jawabu_group_config
    from core.services.requisition_partners import PARTNER_ECO, fulfillment_partner_for_farmer
    config = _jawabu_group_config(farmer)
    if not config:
        return None
    workflow = config.workflow or {}
    if operation_type == MASTER_OPERATION:
        tab = (workflow.get('eco_conserve_sheet_name') or 'Eco-conserve') if fulfillment_partner_for_farmer(farmer) == PARTNER_ECO else (workflow.get('master_sheet_name') or 'Master Data')
        sheet_id = workflow.get('master_sheet_id') or config.sheet_id
    else:
        tab = workflow.get('internal_order_sheet_name') or 'Orders'
        sheet_id = workflow.get('internal_order_sheet_id')
    return {'group_id': str(config.group_id), 'spreadsheet': str(sheet_id or ''), 'tab': str(tab)}


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
    from portal_legacy.models import LegacyRow
    if LegacyRow.objects.filter(farmer=farmer, publication_ready=False).exists():
        return []

    revision = int(getattr(farmer, 'workflow_revision', 0) or 0)
    operations = []
    namespace = str(deduplication_namespace or '').strip()
    enabled_targets = _targets_for_farmer(farmer)
    requested_targets = list(operation_types) if operation_types is not None else enabled_targets
    for operation_type in requested_targets:
        if operation_type not in enabled_targets:
            continue
        destination = _destination_for_farmer(farmer, operation_type)
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
                **({'destination_key': hashlib.sha256(json.dumps(destination, sort_keys=True).encode()).hexdigest(),
                    'destination': destination} if destination else {}),
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
        if (current.metadata or {}).get('retry_of_operation_id') == str(operation.pk):
            return current, False
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
    from django.db import transaction
    # Never overwrite the live attempt token with this caller's older snapshot.
    with transaction.atomic():
        current = IntegrationOperation.objects.select_for_update().get(pk=operation.pk)
        if current.status != IntegrationOperation.STATUS_RUNNING or not operation.metadata.get('attempt_token') or current.metadata.get('attempt_token') != operation.metadata.get('attempt_token'):
            return
        metadata = dict(current.metadata or {})
        _save_master_failure_context(current, farmer, context, metadata)


def _save_master_failure_context(operation, farmer, context, metadata):
    fields = sorted({str(value)[:120] for value in (context.get('field_names') or []) if str(value).strip()})
    metadata['failure_context'] = {
        'case_reference': str(getattr(farmer, 'case_reference_number', '') or ''),
        'phase': str(context.get('phase') or 'unknown')[:40],
        'sheet_tab': str(context.get('sheet_tab') or '')[:120],
        'fields_checked': bool(context.get('fields_checked')),
        'field_names': fields[:30],
        'detail': str(context.get('detail') or '')[:255],
        'provider_status': context.get('provider_status'),
    }
    operation.metadata = metadata
    operation.save(update_fields=['metadata', 'updated_at'])


def attempt_publication(operation: IntegrationOperation, *, max_seconds=20) -> dict[str, Any]:
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
    from portal_legacy.fence import case_blocked
    if case_blocked(farmer):
        return {'operation': operation, 'farmer': farmer, 'result': None, 'deferred': True}
    if operation.operation_type == MASTER_OPERATION:
        # A monthly FarmUp commit can reserve hundreds of rows. Never let a
        # later case take a lower Sheet row just because the earlier case is
        # paced, retrying, or currently owned by another worker.
        if not _master_claim_in_order(operation):
            return {'operation': operation, 'farmer': farmer, 'result': None, 'deferred': True}
    if operation.next_retry_at and operation.next_retry_at > timezone.now():
        return {'operation': operation, 'farmer': farmer, 'result': None, 'deferred': True}
    operation_revision = int((operation.metadata or {}).get('workflow_revision') or 0)
    reserved_destination = (operation.metadata or {}).get('destination')
    current_destination = _destination_for_farmer(farmer, operation.operation_type)
    if reserved_destination and reserved_destination != current_destination:
        # Do not write a different target under the old target's FIFO claim.
        # Reserve a fresh destination-bound operation, retaining this evidence.
        replacement = reserve_farmer_publication(
            farmer, deduplication_namespace=f'destination-change:{operation.pk}',
            operation_types=[operation.operation_type],
            required_capability=(operation.metadata or {}).get('required_capability', 'portal.case.read'),
        )
        if not replacement:
            return {'operation': operation, 'farmer': farmer, 'result': None, 'deferred': True}
        result = execute_operation(operation, lambda: {'action': 'superseded_destination'}, attempt_budget=1,
                                   claim_guard=_master_claim_in_order)
        return {'operation': operation, 'farmer': farmer, 'result': result, 'superseded': True}
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
            claim_guard=_master_claim_in_order,
        )
        return {'operation': operation, 'farmer': farmer, 'result': result, 'superseded': True}

    def publish_once():
        from portal_legacy.fence import case_blocked
        if case_blocked(farmer):
            raise PortalPublicationError('Portal owner is held for legacy cutover.')
        if operation.operation_type == MASTER_OPERATION:
            failure_context: dict[str, Any] = {}
            with external_call_budget(max_seconds):
                completed = sync_farmer_to_master_sheet(farmer, failure_context=failure_context,
                    existing_row_only=_updates_existing_row(operation))
            if not completed:
                _record_master_failure_context(operation, farmer, failure_context)
        else:
            with external_call_budget(max_seconds):
                completed = sync_farmer_to_internal_order_sheet(farmer)
        if not completed:
            if operation.operation_type == MASTER_OPERATION and failure_context.get('phase') == 'identity':
                raise PortalIdentityConflictError('The Sheet row needs identity review.')
            if operation.operation_type == MASTER_OPERATION and failure_context.get('phase') in {'configuration', 'schema', 'verify', 'row_missing'}:
                raise PortalRegisterReviewError(failure_context['phase'])
            # The low-level publisher intentionally keeps Google details in
            # protected logs.  This marker is retryable by the shared policy.
            error = PortalPublicationError('Google register is temporarily unavailable.')
            if operation.operation_type == MASTER_OPERATION and failure_context.get('provider_status'):
                error.status_code = failure_context['provider_status']
            raise error
        return {'action': operation.operation_type}

    try:
        result = execute_operation(
            operation, publish_once, attempt_budget=1,
            min_spacing_seconds=getattr(settings, 'PORTAL_PUBLICATION_MIN_SPACING_SECONDS', 5),
            paced_operation_types=(MASTER_OPERATION, INTERNAL_ORDER_OPERATION),
            claim_guard=_master_claim_in_order,
        )
    except ExternalCircuitOpen:
        operation.refresh_from_db()
        return {'operation':operation, 'farmer':farmer, 'result':None, 'deferred':True, 'error':False}
    except ExternalOperationError:
        operation.refresh_from_db()
        context = (operation.metadata or {}).get('failure_context') or {}
        logger.warning('Portal publication failed: operation=%s code=%s phase=%s provider_status=%s',
            operation.pk, operation.last_error_code, context.get('phase', ''), context.get('provider_status'))
        return {'operation': operation, 'farmer': farmer, 'result': None, 'error': True}
    operation.refresh_from_db()
    return {'operation': operation, 'farmer': farmer, 'result': result, 'error': False}
