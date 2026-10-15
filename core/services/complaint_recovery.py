"""Complaint register recovery; comment/resolution state is never resubmitted."""
from core.services.complaint_cases import _case_queryset, actor_can, complaint_sheet_projection_enabled
from core.services.miniapp_recovery import issue, page_payload, request_action


def status_payload(group, actor, *, page=1):
    cases = _case_queryset(group.group_id, actor).filter(complaint_control__sync_status__in=['failed', 'pending', 'suspended'])
    rows = []
    for case in cases:
        control = case.complaint_control
        enabled = complaint_sheet_projection_enabled(group)
        action = None
        if enabled and control.sync_status == 'failed' and actor_can(group, actor, 'complaint.case.sync.retry', case):
            action = request_action('Retry sync', f'/api/complaints/cases/{case.message_id}/sync-retry/', {},
                                    'Retry this complaint’s Sheet update? No comment or resolution will be submitted again.')
        rows.append(issue(control.pk, f'{control.reference_number} · Sheet update',
            detail='Complaint changes are saved in the app.',
            status='Configuration required' if not enabled else 'Waiting' if control.sync_status == 'pending' else 'Needs review',
            action=action, steps=(['Ask Complaint IT to enable the complaint Sheet projection for this group.',
                                  'Then check status and retry this saved complaint.'] if not enabled else None)))
    from report_delivery.recovery import recovery_rows
    rows.extend(recovery_rows(actor.user, 'complaint_cases', group=group))
    return page_payload(rows, page)
