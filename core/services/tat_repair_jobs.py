"""Database-leased, checkpointed execution for TAT Sheet repairs."""

from __future__ import annotations

from datetime import timedelta
import logging
import time
import uuid

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.models import GroupSheetConfiguration, TatRepairJob, TatTrackerCase

logger = logging.getLogger(__name__)


@transaction.atomic
def create_repair_job(
    config: GroupSheetConfiguration, *, product_key: str = '', requested_by: str = '',
    include_unlinked: bool = False, case_ids: list[str] | None = None,
) -> TatRepairJob:
    from core.services.workflow_data_mode import operational_tat_cases
    queryset = operational_tat_cases(
        TatTrackerCase.objects.filter(group_id=config.group_id, is_deleted=False)
    )
    if product_key:
        queryset = queryset.filter(product_key=product_key)
    requested_case_ids = [str(case_id).strip() for case_id in (case_ids or []) if str(case_id).strip()]
    if requested_case_ids:
        queryset = queryset.filter(case_id__in=requested_case_ids)
    candidate_queryset = queryset if include_unlinked else queryset.filter(row_number__gt=0)
    durable_case_ids = list(
        candidate_queryset.order_by('product_key', 'case_id').values_list('case_id', flat=True)
    )
    # Serialize reservations for one configuration so a double-click or an
    # HTTP retry resumes the same active repair instead of creating duplicate
    # scheduled work.
    locked_config = GroupSheetConfiguration.objects.select_for_update().get(pk=config.pk)
    for active_job in TatRepairJob.objects.filter(
        group_configuration=locked_config,
        product_key=product_key,
        status__in=['queued', 'running'],
    ).order_by('created_at'):
        if list(active_job.case_ids or []) == durable_case_ids:
            return active_job

    from core.services.product_catalog import resolve_product
    return TatRepairJob.objects.create(
        group_configuration=locked_config, product_key=product_key,
        product=resolve_product(product_key), case_ids=durable_case_ids,
        total_cases=len(durable_case_ids),
        skipped_unlinked=0 if include_unlinked else queryset.exclude(row_number__gt=0).count(),
        requested_by=requested_by,
    )


@transaction.atomic
def claim_repair_job(*, job_id=None, lease_seconds: int | None = None):
    """Claim one queued or stale repair with a database row lock and lease."""
    now = timezone.now()
    lease = max(30, int(lease_seconds or getattr(settings, 'DURABLE_JOB_LEASE_SECONDS', 300) or 300))
    stale_before = now - timedelta(seconds=lease)
    candidates = TatRepairJob.objects.filter(
        Q(status='queued')
        | Q(status='running', heartbeat_at__lt=stale_before)
        | Q(status='running', heartbeat_at__isnull=True)
    )
    if job_id is not None:
        candidates = candidates.filter(pk=job_id)
    candidates = candidates.order_by('created_at')
    try:
        job = candidates.select_for_update(skip_locked=True).first()
    except NotImplementedError:
        job = candidates.select_for_update().first()
    if job is None:
        return None, None
    token = uuid.uuid4()
    job.status = 'running'
    job.worker_token = token
    job.heartbeat_at = now
    job.started_at = job.started_at or now
    job.completed_at = None
    job.error = ''
    job.save(update_fields=[
        'status', 'worker_token', 'heartbeat_at', 'started_at',
        'completed_at', 'error', 'updated_at',
    ])
    return job, token


def run_repair_job(
    job_id, *, worker_token=None, max_cases: int | None = None,
    sleeper=time.sleep,
) -> dict:
    """Process a bounded case chunk and checkpoint after every external call."""
    from core.services.tat_tracker import resync_tat_tracker_cases

    token = worker_token
    if token is None:
        claimed, token = claim_repair_job(job_id=job_id)
        if claimed is None:
            current = TatRepairJob.objects.get(pk=job_id)
            return {'job_id': str(current.pk), 'processed_cases': 0, 'status': current.status}
    budget = None if max_cases is None else max(1, min(int(max_cases), 1000))
    processed = 0
    while budget is None or processed < budget:
        job = TatRepairJob.objects.select_related('group_configuration').get(pk=job_id)
        if job.worker_token != token or job.status != 'running':
            break
        if job.cursor >= job.total_cases:
            break

        case_id = str(job.case_ids[job.cursor])
        try:
            result = resync_tat_tracker_cases(
                job.group_configuration, product_key=job.product_key,
                case_ids=[case_id], dry_run=False, limit=None, offset=0,
                include_unlinked=True,
            )
            synced = int(result.get('synced') or 0)
            failures = list(result.get('failed') or [])
            for failure in failures:
                logger.error(
                    'TAT repair case sync failed: job=%s case_id=%s error=%s',
                    job_id,
                    failure.get('case_id') if isinstance(failure, dict) else case_id,
                    failure.get('error') if isinstance(failure, dict) else str(failure),
                )
        except Exception as exc:
            logger.exception('TAT repair job %s failed for case %s.', job_id, case_id)
            synced = 0
            failures = [{'case_id': case_id, 'error': f'{type(exc).__name__}: repair did not complete'}]

        with transaction.atomic():
            job = TatRepairJob.objects.select_for_update().get(pk=job_id)
            if job.worker_token != token or job.status != 'running':
                break
            job.cursor += 1
            job.synced_cases += synced
            if failures:
                job.failures = [*job.failures, *failures]
            job.heartbeat_at = timezone.now()
            job.save(update_fields=['cursor', 'synced_cases', 'failures', 'heartbeat_at', 'updated_at'])
        processed += 1

        delay = max(0.0, float(getattr(settings, 'TAT_REPAIR_CASE_DELAY_SECONDS', 1.1) or 0))
        if delay and job.cursor < job.total_cases and (budget is None or processed < budget):
            sleeper(delay)

    with transaction.atomic():
        job = TatRepairJob.objects.select_for_update().get(pk=job_id)
        if job.worker_token == token and job.status == 'running':
            job.worker_token = None
            job.heartbeat_at = timezone.now()
            if job.cursor >= job.total_cases:
                job.status = 'completed_with_errors' if job.failures else 'completed'
                job.completed_at = timezone.now()
            else:
                job.status = 'queued'
            job.save(update_fields=[
                'status', 'worker_token', 'heartbeat_at', 'completed_at', 'updated_at',
            ])
    return {'job_id': str(job.pk), 'processed_cases': processed, 'status': job.status}


def process_next_repair_job(*, case_limit: int) -> dict | None:
    job, token = claim_repair_job()
    if job is None:
        return None
    return run_repair_job(job.pk, worker_token=token, max_cases=case_limit)


@transaction.atomic
def cancel_repair_job(*, job: TatRepairJob) -> TatRepairJob:
    locked = TatRepairJob.objects.select_for_update().get(pk=job.pk)
    if locked.status in {'completed', 'completed_with_errors', 'cancelled'}:
        return locked
    locked.status = 'cancelled'
    locked.worker_token = None
    locked.heartbeat_at = timezone.now()
    locked.completed_at = timezone.now()
    locked.save(update_fields=[
        'status', 'worker_token', 'heartbeat_at', 'completed_at', 'updated_at',
    ])
    return locked


def serialize_repair_job(job: TatRepairJob) -> dict:
    return {
        'id': str(job.id), 'status': job.status, 'total_cases': job.total_cases,
        'processed_cases': job.cursor, 'synced_cases': job.synced_cases,
        'skipped_unlinked': job.skipped_unlinked,
        'failure_count': len(job.failures or []), 'failures': job.failures or [],
        'error': job.error,
        'complete': job.status in {'completed', 'completed_with_errors', 'failed', 'cancelled'},
        'updated_at': job.updated_at.isoformat() if job.updated_at else None,
    }
