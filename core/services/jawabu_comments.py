"""Append-only staff-comment ledger for the Jawabu Portal."""

from __future__ import annotations

from django.utils import timezone

from core.models import JawabuCaseComment, JawabuFarmerMaster, JawabuPipelineEvent


# These labels describe the accountable Portal function for the action, not
# every AccessGrant currently held by a staff member.  They are snapshotted so
# a later role change cannot rewrite the meaning of a historical remark.
STAGE_ROLE = {
    'jbl_visit': ('JBL_OFFICER', 'JBL Officer'),
    'credit': ('CREDIT_ANALYST', 'Credit Analyst'),
    'final_review': ('BUSINESS_ADMIN', 'Head of Rural'),
    'payment': ('BUSINESS_ADMIN', 'Head of Rural'),
    'order': ('HB_STAFF', 'Operations Staff'),
    'invoice': ('HB_STAFF', 'Operations Staff'),
    'correction': ('IT', 'IT'),
}


def record_case_comment(
    *,
    farmer: JawabuFarmerMaster,
    stage_key: str,
    comment: str,
    actor: str = '',
    actor_user=None,
    request_id: str = '',
    pipeline_event: JawabuPipelineEvent | None = None,
    occurred_at=None,
) -> JawabuCaseComment | None:
    """Persist one non-empty staff remark without duplicating a retried action."""
    text = str(comment or '').strip()
    if not text:
        return None
    stage = str(stage_key or '').strip()
    role_code, role_label = STAGE_ROLE.get(stage, ('', ''))
    defaults = {
        'pipeline_event': pipeline_event,
        'stage_key': stage,
        'comment': text,
        'actor': str(actor or '').strip(),
        'actor_user': actor_user,
        'role_code': role_code,
        'role_label': role_label,
        'occurred_at': occurred_at or timezone.now(),
    }
    if request_id:
        record, _created = JawabuCaseComment.objects.get_or_create(
            farmer=farmer,
            request_id=str(request_id),
            defaults=defaults,
        )
        return record
    return JawabuCaseComment.objects.create(farmer=farmer, request_id='', **defaults)


def master_comment_history(farmer: JawabuFarmerMaster) -> str:
    """Render the chronological Sheet projection without exposing event noise."""
    entries = farmer.case_comments.order_by('occurred_at', 'created_at', 'pk')
    lines: list[str] = []
    for entry in entries:
        occurred_at = entry.occurred_at
        local_time = timezone.localtime(occurred_at) if timezone.is_aware(occurred_at) else occurred_at
        timestamp = local_time.strftime('%d-%B-%Y %H:%M')
        actor = str(entry.actor or '').strip() or 'Unknown staff member'
        role = str(entry.role_label or entry.role_code or 'Portal staff').strip()
        lines.append(f'[{timestamp}] {actor} / {role} - {entry.comment}')
    return '\n'.join(lines)
