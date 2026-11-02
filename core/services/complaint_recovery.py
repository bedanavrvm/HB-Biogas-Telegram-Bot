"""Complaint register recovery; comment/resolution state is never resubmitted."""
from core.services.complaint_cases import _case_queryset, actor_can, complaint_sheet_projection_enabled
from core.services.miniapp_recovery import issue, page_payload, request_action


def status_payload(group, actor, *, page=1):
    from complaint_publications.services import case_state, recovery_detail, recovery_cases
    cases = recovery_cases(group, actor)
    rows = []
    for case in cases:
        control = case.complaint_control
        enabled = complaint_sheet_projection_enabled(group)
        state = case_state(group, actor, case)
        sheet = state['sheet']
        action = request_action('Retry publication', f'/api/complaints/cases/{case.message_id}/sync-retry/', {},
                                'Queue the saved publication again? Comments, files and case status will not be submitted again.') if sheet['can_retry'] else None
        rows.append(issue(control.pk, f'{control.reference_number} · Sheet update',
            detail=recovery_detail(state),
            reference=sheet['key'] or control.pk,
            status='Configuration required' if not enabled else 'Needs review' if state['needs_attention'] else 'Waiting',
            action=action, steps=['Check the Sheet connection, required columns and Google access.',
                'Configure the scheduled publisher every minute: python manage.py drain_complaint_publications --apply --limit 10 --max-seconds 50',
                'After repairing the cause, retry publication. Existing active jobs retain their backoff and lease.',
                'Your saved comment, resolution and file bytes are retained. Do not enter them again.']))
    from report_delivery.recovery import recovery_rows
    rows.extend(recovery_rows(actor.user, 'complaint_cases', group=group))
    return page_payload(rows, page)
