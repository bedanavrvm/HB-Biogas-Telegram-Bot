"""Bounded, durable retry and circuit-breaker primitives for integrations.

The platform intentionally has no Celery/Redis worker.  These helpers are
therefore synchronous and bounded: they record an operation before each
attempt, make at most the integration-specific number of tries, and leave a
safe retry/dead-letter record for the owning workflow. They never queue work
silently in a process-local thread.
"""

from __future__ import annotations

from datetime import timedelta
import hashlib
import random
import time
from typing import Any, Callable, TypeVar

from django.db import IntegrityError, transaction
from django.conf import settings
from django.utils import timezone

from core.models import IntegrationCircuitState, IntegrationOperation


T = TypeVar('T')
INTEGRATION_MAX_ATTEMPTS = {
    IntegrationOperation.INTEGRATION_GOOGLE_SHEETS: 4,
    IntegrationOperation.INTEGRATION_GOOGLE_DRIVE: 3,
    IntegrationOperation.INTEGRATION_TELEGRAM: 3,
}
FAILURE_WINDOW = timedelta(minutes=5)
CIRCUIT_OPEN_FOR = timedelta(minutes=10)
CIRCUIT_FAILURE_THRESHOLD = 5


class ExternalOperationError(RuntimeError):
    """Base safe integration failure; detailed causes remain server-side."""


class ExternalCircuitOpen(ExternalOperationError):
    """The dependency is cooling down after repeated transient failures."""


def redacted_error_code(error: Exception) -> str:
    response = getattr(error, 'response', None)
    status = getattr(response, 'status_code', None) or getattr(error, 'status_code', None)
    if status:
        return f'http_{int(status)}'
    text = f"{error} {getattr(error, 'description', '')}".lower()
    if 'timeout' in text:
        return 'timeout'
    if any(marker in text for marker in ('rate_limit', 'quota', '429', 'resource_exhausted')):
        return 'rate_limited'
    if any(marker in text for marker in ('connection', 'network', 'temporarily unavailable', 'service unavailable')):
        return 'network'
    return 'external_error'


def is_transient_external_error(error: Exception) -> bool:
    """Retry only network failures, 429s and server-side failures."""
    response = getattr(error, 'response', None)
    status = getattr(response, 'status_code', None) or getattr(error, 'status_code', None)
    try:
        if status is not None:
            return int(status) == 429 or int(status) >= 500
    except (TypeError, ValueError):
        pass
    text = f"{error} {getattr(error, 'description', '')}".lower()
    return any(
        marker in text
        for marker in (
            'timeout', 'timed out', 'connection reset', 'connection error',
            'network is unreachable', 'temporarily unavailable', '429',
            'rate_limit', 'quota exceeded', 'resource_exhausted', '503', '502', '504',
        )
    )


def retry_after_seconds(error: Exception, *, attempt: int, random_value: Callable[[], float] = random.random) -> float:
    """Honor Retry-After where exposed; otherwise use capped exponential jitter."""
    response = getattr(error, 'response', None)
    headers = getattr(response, 'headers', {}) or getattr(error, 'headers', {}) or {}
    raw = headers.get('Retry-After') or headers.get('retry-after')
    try:
        if raw is not None:
            return max(0.0, min(120.0, float(raw)))
    except (TypeError, ValueError):
        pass
    return min(60.0, (2 ** max(0, attempt - 1)) + random_value())


def payload_digest(value: Any) -> str:
    """Hash an operation identity without retaining customer or document data."""
    return hashlib.sha256(repr(value).encode('utf-8', errors='replace')).hexdigest()


def _safe_error(error: Exception) -> str:
    # Do not retain tokens, raw Google error JSON, or document content in the
    # durable operations register. The owning service has its normal secure log.
    return f'{type(error).__name__}: external integration did not complete.'


def reserve_operation(
    *,
    integration: str,
    operation_type: str,
    deduplication_key: str,
    source_model: str = '',
    source_id: str = '',
    request_id: str = '',
    requested_by=None,
    requested_by_label: str = '',
    operation_payload: Any = None,
    metadata: dict | None = None,
    max_attempts: int | None = None,
) -> tuple[IntegrationOperation, bool]:
    """Create one durable operation, returning an existing replay safely."""
    defaults = {
        'integration': integration,
        'operation_type': str(operation_type)[:80],
        'source_model': str(source_model)[:120],
        'source_id': str(source_id)[:128],
        'request_id': str(request_id)[:128],
        'requested_by': requested_by,
        'requested_by_label': str(requested_by_label)[:255],
        'payload_digest': payload_digest(operation_payload) if operation_payload is not None else '',
        'metadata': dict(metadata or {}),
        'max_attempts': max(1, int(max_attempts or INTEGRATION_MAX_ATTEMPTS.get(integration, 1))),
    }
    try:
        with transaction.atomic():
            operation, created = IntegrationOperation.objects.get_or_create(
                deduplication_key=str(deduplication_key)[:255],
                defaults=defaults,
            )
    except IntegrityError:
        operation = IntegrationOperation.objects.get(deduplication_key=str(deduplication_key)[:255])
        created = False
    return operation, created


def _claim_circuit(integration: str, *, now):
    with transaction.atomic():
        circuit, _ = IntegrationCircuitState.objects.select_for_update().get_or_create(integration=integration)
        if circuit.status == IntegrationCircuitState.STATUS_OPEN:
            if circuit.next_probe_at and circuit.next_probe_at > now:
                raise ExternalCircuitOpen('This integration is temporarily unavailable. Retry after its recovery check.')
            circuit.status = IntegrationCircuitState.STATUS_HALF_OPEN
            circuit.save(update_fields=['status', 'updated_at'])
        elif circuit.status == IntegrationCircuitState.STATUS_HALF_OPEN:
            raise ExternalCircuitOpen('This integration is running its recovery check. Try again shortly.')
        return circuit


def _record_circuit_success(integration: str, *, now) -> None:
    with transaction.atomic():
        circuit, _ = IntegrationCircuitState.objects.select_for_update().get_or_create(integration=integration)
        circuit.status = IntegrationCircuitState.STATUS_CLOSED
        circuit.consecutive_failures = 0
        circuit.failure_window_started_at = None
        circuit.opened_at = None
        circuit.next_probe_at = None
        circuit.last_failure_code = ''
        circuit.last_success_at = now
        circuit.save()


def _record_circuit_failure(integration: str, error: Exception, *, now) -> None:
    with transaction.atomic():
        circuit, _ = IntegrationCircuitState.objects.select_for_update().get_or_create(integration=integration)
        if not circuit.failure_window_started_at or now - circuit.failure_window_started_at > FAILURE_WINDOW:
            circuit.failure_window_started_at = now
            circuit.consecutive_failures = 0
        circuit.consecutive_failures += 1
        circuit.last_failure_code = redacted_error_code(error)
        if circuit.status == IntegrationCircuitState.STATUS_HALF_OPEN or circuit.consecutive_failures >= CIRCUIT_FAILURE_THRESHOLD:
            circuit.status = IntegrationCircuitState.STATUS_OPEN
            circuit.opened_at = now
            circuit.next_probe_at = now + CIRCUIT_OPEN_FOR
        circuit.save()


def _mark_attempt(operation_id, *, now) -> IntegrationOperation | None:
    with transaction.atomic():
        operation = IntegrationOperation.objects.select_for_update().get(pk=operation_id)
        # A web worker can be recycled while an outbound request is in flight.
        # Do not let a second Mini App retry run the same operation at once;
        # after the bounded lease, a later request may safely reclaim it.
        if operation.status == IntegrationOperation.STATUS_RUNNING:
            lease_seconds = max(30, int(getattr(settings, 'API_REQUEST_TIMEOUT', 10) or 10) * 3)
            if operation.last_attempt_at and (timezone.now() - operation.last_attempt_at).total_seconds() < lease_seconds:
                return None
            operation.status = IntegrationOperation.STATUS_RETRYABLE
        operation.status = IntegrationOperation.STATUS_RUNNING
        operation.attempts += 1
        operation.last_attempt_at = now
        operation.next_retry_at = None
        operation.last_error_code = ''
        operation.last_error = ''
        operation.save()
        return operation


def _mark_success(operation_id, *, now, result: Any) -> None:
    with transaction.atomic():
        operation = IntegrationOperation.objects.select_for_update().get(pk=operation_id)
        operation.status = IntegrationOperation.STATUS_SUCCEEDED
        operation.completed_at = now
        operation.next_retry_at = None
        metadata = dict(operation.metadata or {})
        # Result identity must be operationally useful but non-sensitive.
        metadata['result_digest'] = payload_digest(result)
        if isinstance(result, dict):
            safe_result = {
                key: str(result[key])[:1000]
                for key in ('id', 'webViewLink', 'url', 'message_id', 'action')
                if result.get(key)
            }
            if safe_result:
                metadata['result'] = safe_result
        operation.metadata = metadata
        operation.save()


def _mark_failure(operation_id, error: Exception, *, now, retryable: bool) -> IntegrationOperation:
    with transaction.atomic():
        operation = IntegrationOperation.objects.select_for_update().get(pk=operation_id)
        operation.last_error_code = redacted_error_code(error)
        operation.last_error = _safe_error(error)
        if retryable and operation.attempts < operation.max_attempts:
            operation.status = IntegrationOperation.STATUS_RETRYABLE
            operation.next_retry_at = now + timedelta(seconds=retry_after_seconds(error, attempt=operation.attempts))
        else:
            operation.status = IntegrationOperation.STATUS_DEAD_LETTER
            operation.next_retry_at = None
        operation.save()
        return operation


def execute_operation(
    operation: IntegrationOperation,
    action: Callable[[], T],
    *,
    sleeper: Callable[[float], None] = time.sleep,
    random_value: Callable[[], float] = random.random,
    attempt_budget: int | None = None,
) -> T | None:
    """Run a reserved operation with bounded retry and durable outcomes.

    A prior successful operation is an idempotent replay.  Simple safe SDK
    identifiers (for example a Drive file id/link) are returned when retained;
    callers otherwise use their own canonical local record.
    """
    operation.refresh_from_db()
    if operation.status == IntegrationOperation.STATUS_SUCCEEDED:
        return (operation.metadata or {}).get('result')
    if operation.status == IntegrationOperation.STATUS_DEAD_LETTER:
        raise ExternalOperationError('This integration operation has exhausted its retry budget. Use the owning workflow\'s explicit retry action after review.')
    remaining_attempts = max(0, int(operation.max_attempts) - int(operation.attempts))
    if not remaining_attempts:
        operation.status = IntegrationOperation.STATUS_DEAD_LETTER
        operation.save(update_fields=['status', 'updated_at'])
        raise ExternalOperationError('This integration operation has exhausted its retry budget. Use the owning workflow\'s explicit retry action after review.')
    attempts_this_call = remaining_attempts
    if attempt_budget is not None:
        attempts_this_call = max(1, min(remaining_attempts, int(attempt_budget)))
    last_error: Exception | None = None
    for attempt in range(1, attempts_this_call + 1):
        now = timezone.now()
        _claim_circuit(operation.integration, now=now)
        current = _mark_attempt(operation.pk, now=now)
        if current is None:
            # Another request has the short execution lease.  Treat this as a
            # safe no-op rather than duplicating an external write.
            return None
        try:
            result = action()
        except Exception as error:  # external SDK errors are intentionally normalized below
            last_error = error
            transient = is_transient_external_error(error)
            _record_circuit_failure(operation.integration, error, now=timezone.now()) if transient else None
            saved = _mark_failure(operation.pk, error, now=timezone.now(), retryable=transient)
            if not transient or saved.status == IntegrationOperation.STATUS_DEAD_LETTER:
                raise ExternalOperationError('The external integration could not complete. Retry from the workflow when it is available.') from error
            if attempt < attempts_this_call:
                sleeper(retry_after_seconds(error, attempt=attempt, random_value=random_value))
                continue
            break
        _mark_success(operation.pk, now=timezone.now(), result=result)
        _record_circuit_success(operation.integration, now=timezone.now())
        return result
    raise ExternalOperationError('The external integration could not complete. Retry from the workflow when it is available.') from last_error


def integration_readiness() -> dict[str, Any]:
    """Return stored state only. This must never make an outbound request."""
    circuits = {
        row.integration: {
            'status': row.status,
            'consecutive_failures': row.consecutive_failures,
            'next_probe_at': row.next_probe_at.isoformat() if row.next_probe_at else None,
            'last_success_at': row.last_success_at.isoformat() if row.last_success_at else None,
        }
        for row in IntegrationCircuitState.objects.all()
    }
    pending = IntegrationOperation.objects.filter(
        status__in=[IntegrationOperation.STATUS_RETRYABLE, IntegrationOperation.STATUS_DEAD_LETTER]
    ).count()
    last_probe = IntegrationOperation.objects.filter(operation_type='readiness_probe').order_by('-updated_at').first()
    return {
        'circuits': circuits,
        'operations_requiring_attention': pending,
        'last_probe_at': last_probe.updated_at.isoformat() if last_probe else None,
    }
