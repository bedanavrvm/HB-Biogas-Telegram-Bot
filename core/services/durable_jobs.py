"""Shared liveness and readiness projections for scheduled database runners."""

from __future__ import annotations

from datetime import timedelta

from django.db.models import Q
from django.utils import timezone


COMPLAINT_IMPORT_RUNNER = 'complaint_imports'
TAT_REPAIR_RUNNER = 'tat_repairs'


def begin_runner(runner_key: str):
    from core.models import DurableJobRunnerHeartbeat

    now = timezone.now()
    row, _ = DurableJobRunnerHeartbeat.objects.update_or_create(
        runner_key=str(runner_key)[:80],
        defaults={
            'status': DurableJobRunnerHeartbeat.STATUS_RUNNING,
            'heartbeat_at': now,
            'last_started_at': now,
            'last_error_code': '',
        },
    )
    return row


def finish_runner(runner_key: str, *, processed_count: int = 0, error_code: str = ''):
    from core.models import DurableJobRunnerHeartbeat

    now = timezone.now()
    row, _ = DurableJobRunnerHeartbeat.objects.get_or_create(
        runner_key=str(runner_key)[:80],
        defaults={'last_started_at': now},
    )
    row.status = (
        DurableJobRunnerHeartbeat.STATUS_FAILED
        if error_code else DurableJobRunnerHeartbeat.STATUS_SUCCEEDED
    )
    row.heartbeat_at = now
    row.last_completed_at = now
    row.processed_count = max(0, int(processed_count))
    row.last_error_code = str(error_code or '')[:80]
    row.save(update_fields=[
        'status', 'heartbeat_at', 'last_completed_at', 'processed_count',
        'last_error_code', 'updated_at',
    ])
    return row


def durable_job_health(*, now=None, max_silence_seconds: int | None = None) -> dict:
    """Return aggregate-only runner freshness and stalled-job counts."""
    from django.conf import settings
    from core.models import (
        ComplaintCaseImportBatch,
        DurableJobRunnerHeartbeat,
        TatRepairJob,
    )

    current = now or timezone.now()
    silence = max(60, int(
        max_silence_seconds
        or getattr(settings, 'DURABLE_JOB_RUNNER_MAX_SILENCE_SECONDS', 900)
        or 900
    ))
    cutoff = current - timedelta(seconds=silence)
    lease_cutoff = current - timedelta(seconds=max(30, int(
        getattr(settings, 'DURABLE_JOB_LEASE_SECONDS', 300) or 300
    )))

    runners = {}
    for key in (COMPLAINT_IMPORT_RUNNER, TAT_REPAIR_RUNNER):
        row = DurableJobRunnerHeartbeat.objects.filter(runner_key=key).first()
        runners[key] = {
            'fresh': bool(row and row.heartbeat_at and row.heartbeat_at >= cutoff),
            'status': row.status if row else 'never_run',
            'heartbeat_at': row.heartbeat_at.isoformat() if row and row.heartbeat_at else None,
            'processed_count': int(row.processed_count) if row else 0,
            'last_error_code': row.last_error_code if row else '',
        }

    return {
        'max_silence_seconds': silence,
        'runners': runners,
        'complaint_imports': {
            'queued': ComplaintCaseImportBatch.objects.filter(
                status=ComplaintCaseImportBatch.STATUS_QUEUED,
            ).count(),
            'stalled': ComplaintCaseImportBatch.objects.filter(
                Q(status=ComplaintCaseImportBatch.STATUS_RUNNING),
                Q(heartbeat_at__lt=lease_cutoff) | Q(heartbeat_at__isnull=True),
            ).count(),
            'partial': ComplaintCaseImportBatch.objects.filter(
                status=ComplaintCaseImportBatch.STATUS_PARTIAL,
            ).count(),
        },
        'tat_repairs': {
            'queued': TatRepairJob.objects.filter(status='queued').count(),
            'stalled': TatRepairJob.objects.filter(
                Q(status='running'),
                Q(heartbeat_at__lt=lease_cutoff) | Q(heartbeat_at__isnull=True),
            ).count(),
            'completed_with_errors': TatRepairJob.objects.filter(
                status='completed_with_errors',
            ).count(),
        },
    }
