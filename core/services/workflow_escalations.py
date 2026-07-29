"""Read-only escalation projections shared by Mini App case views."""

from __future__ import annotations

from core.models import WorkflowSlaEscalation


def latest_escalation(workflow: str, subject_id: str) -> dict | None:
    record = WorkflowSlaEscalation.objects.filter(
        workflow=workflow,
        subject_id=str(subject_id),
    ).exclude(status='resolved').order_by('-escalation_date', '-created_at').first()
    if record is None:
        return None
    return {
        'id': str(record.id),
        'status': record.status,
        'stage_key': record.stage_key,
        'branch': record.branch,
        'responsible_role': record.responsible_role,
        'responsible_actor': record.responsible_actor,
        'target_minutes': str(record.target_minutes),
        'overdue_minutes': str(record.overdue_minutes),
        'escalation_level': record.escalation_level,
        'threshold_percent': record.threshold_percent,
        'routing_role': (
            'Management' if record.escalation_level >= 3
            else 'Branch Manager' if record.escalation_level == 2
            else record.responsible_role or 'Responsible team'
        ),
        'escalation_date': record.escalation_date.isoformat(),
    }
