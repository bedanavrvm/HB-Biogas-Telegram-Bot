"""Persistent, checkpointed background execution for TAT Sheet repairs."""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import timedelta

from django.db import close_old_connections, transaction
from django.utils import timezone

from core.models import GroupSheetConfiguration, TatRepairJob, TatTrackerCase

logger = logging.getLogger(__name__)
_active_jobs: set[str] = set()
_active_jobs_lock = threading.Lock()


def create_repair_job(config: GroupSheetConfiguration, *, product_key: str = '', requested_by: str = '') -> TatRepairJob:
    queryset = TatTrackerCase.objects.filter(group_id=config.group_id, is_deleted=False)
    if product_key:
        queryset = queryset.filter(product_key=product_key)
    case_ids = list(
        queryset.filter(row_number__gt=0)
        .order_by('product_key', 'case_id')
        .values_list('case_id', flat=True)
    )
    return TatRepairJob.objects.create(
        group_configuration=config,
        product_key=product_key,
        case_ids=case_ids,
        total_cases=len(case_ids),
        skipped_unlinked=queryset.exclude(row_number__gt=0).count(),
        requested_by=requested_by,
    )


def start_repair_job(job_id) -> bool:
    """Start or resume a job without holding the originating HTTP request."""
    key = str(job_id)
    with _active_jobs_lock:
        if key in _active_jobs:
            return False
    token = uuid.uuid4()
    with transaction.atomic():
        job = TatRepairJob.objects.select_for_update().get(pk=job_id)
        if job.status in {'completed', 'completed_with_errors', 'failed'}:
            return False
        lease_is_fresh = (
            job.status == 'running'
            and job.heartbeat_at
            and job.heartbeat_at >= timezone.now() - timedelta(seconds=60)
        )
        if lease_is_fresh:
            return False
        job.status = 'running'
        job.worker_token = token
        job.heartbeat_at = timezone.now()
        job.started_at = job.started_at or timezone.now()
        job.save(update_fields=['status', 'worker_token', 'heartbeat_at', 'started_at', 'updated_at'])
    with _active_jobs_lock:
        _active_jobs.add(key)

    def worker() -> None:
        close_old_connections()
        try:
            run_repair_job(job_id, worker_token=token)
        except Exception:
            logger.exception('Background TAT repair job %s failed.', job_id)
        finally:
            close_old_connections()
            with _active_jobs_lock:
                _active_jobs.discard(key)

    threading.Thread(target=worker, name=f'tat-repair-{key[:8]}', daemon=True).start()
    return True


def run_repair_job(job_id, *, worker_token=None) -> None:
    """Process one case at a time and persist progress after each API call."""
    from core.services.tat_tracker import resync_tat_tracker_cases

    token = worker_token
    if token is None:
        token = uuid.uuid4()
        with transaction.atomic():
            job = TatRepairJob.objects.select_for_update().get(pk=job_id)
            if job.status in {'completed', 'completed_with_errors', 'failed'}:
                return
            job.status = 'running'
            job.worker_token = token
            job.heartbeat_at = timezone.now()
            job.started_at = job.started_at or timezone.now()
            job.save(update_fields=['status', 'worker_token', 'heartbeat_at', 'started_at', 'updated_at'])

    while True:
        job = TatRepairJob.objects.select_related('group_configuration').get(pk=job_id)
        if job.worker_token != token:
            return
        if job.cursor >= job.total_cases:
            job.status = 'completed_with_errors' if job.failures else 'completed'
            job.completed_at = timezone.now()
            job.heartbeat_at = timezone.now()
            job.save(update_fields=['status', 'completed_at', 'heartbeat_at', 'updated_at'])
            return

        case_id = str(job.case_ids[job.cursor])
        try:
            result = resync_tat_tracker_cases(
                job.group_configuration,
                product_key=job.product_key,
                case_ids=[case_id],
                dry_run=False,
                limit=None,
                offset=0,
            )
            synced = int(result.get('synced') or 0)
            failures = list(result.get('failed') or [])
        except Exception as exc:
            logger.exception('TAT repair job %s failed for case %s.', job_id, case_id)
            synced = 0
            failures = [{'case_id': case_id, 'error': str(exc)}]

        with transaction.atomic():
            job = TatRepairJob.objects.select_for_update().get(pk=job_id)
            if job.worker_token != token:
                return
            job.cursor += 1
            job.synced_cases += synced
            if failures:
                job.failures = [*job.failures, *failures]
            job.heartbeat_at = timezone.now()
            job.save(update_fields=['cursor', 'synced_cases', 'failures', 'heartbeat_at', 'updated_at'])


def serialize_repair_job(job: TatRepairJob) -> dict:
    return {
        'id': str(job.id),
        'status': job.status,
        'total_cases': job.total_cases,
        'processed_cases': job.cursor,
        'synced_cases': job.synced_cases,
        'skipped_unlinked': job.skipped_unlinked,
        'failure_count': len(job.failures or []),
        'failures': job.failures or [],
        'error': job.error,
        'complete': job.status in {'completed', 'completed_with_errors', 'failed'},
        'updated_at': job.updated_at.isoformat() if job.updated_at else None,
    }
