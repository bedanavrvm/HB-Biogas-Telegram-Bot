"""Durable, bounded archive work; waking a thread never owns the evidence."""

from threading import BoundedSemaphore, Thread
from django.db import close_old_connections, connections, transaction
from django.utils import timezone
from django.db.models import Q
from core.models import IntegrationOperation
from core.services.external_resilience import reserve_operation, execute_operation

_slots = BoundedSemaphore(1)


def queue_archive(version_id, retry=False):
    operation, _ = reserve_operation(
        integration="google_drive",
        operation_type="portal_laf_archive",
        source_model="portal_lafs.PortalLafVersion",
        source_id=str(version_id),
        deduplication_key=f"portal-laf-archive:{version_id}",
        max_attempts=5,
    )
    if retry:
        IntegrationOperation.objects.filter(pk=operation.pk, status="dead_letter").update(
            status="pending", attempts=0, next_retry_at=None
        )
    transaction.on_commit(wake)


def wake():
    if not _slots.acquire(blocking=False):
        return

    def work():
        close_old_connections()
        try:
            drain()
        finally:
            connections.close_all()
            _slots.release()

    Thread(target=work, daemon=True, name="portal-laf-archive").start()


def drain():
    from .services import archive

    for operation in (
        IntegrationOperation.objects.filter(
            operation_type="portal_laf_archive", status__in=["pending", "retryable_failure", "running"]
        )
        .filter(Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=timezone.now()))
        .order_by("created_at")[:10]
    ):
        try:
            execute_operation(operation, lambda: archive(operation.source_id), attempt_budget=1)
        except Exception:
            continue
