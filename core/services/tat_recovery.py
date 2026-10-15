"""TAT-only status projection and Sheet recovery authority (ADR 0052)."""
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import F

from core.models import GroupSheetConfiguration, IntegrationOperation, TatTrackerCase, TatTrackerEvent, TatUpdateSideEffectDispatch
from core.services.miniapp_recovery import issue, page_payload, request_action, configuration_failure
from core.services.telegram_identity import user_access
from core.services.workflow_access import scope_workflow_queryset, matching_capability_grants
from core.services.workflow_data_mode import operational_tat_cases, assert_record_writable


def scoped_cases(actor, capability='tat.home.view', *, access=None):
    access = user_access(actor, 'tat_tracker') if access is None else access
    return scope_workflow_queryset(
        operational_tat_cases().filter(is_deleted=False), actor, 'tat_tracker', capability,
        access=access, branch_field='branch', product_field='product_key', group_field='group_id',
    )


def require_sheet_authority(actor, case):
    if not actor or not actor.is_active or not scoped_cases(actor, 'tat.publication.retry').filter(pk=case.pk).exists():
        raise PermissionDenied('Your TAT access does not allow retrying this Sheet update.')
    assert_record_writable(case)


def can_retry_targets(actor, group, *, access=None):
    if not actor or not actor.is_active:
        return False
    if actor.is_superuser:
        return True
    access = user_access(actor, 'tat_tracker') if access is None else access
    return any(not grant.branch and not grant.product for grant in matching_capability_grants(
        'tat_tracker', 'tat.publication.retry', access=access, group_configuration=group,
    ))


@transaction.atomic
def retry_sheet_dispatch(dispatch_id, *, actor):
    dispatch = TatUpdateSideEffectDispatch.objects.select_for_update().get(pk=dispatch_id)
    case = TatTrackerCase.objects.select_for_update().get(pk=dispatch.case_id)
    require_sheet_authority(actor, case)
    if dispatch.effect_type != TatUpdateSideEffectDispatch.EFFECT_SHEET:
        raise PermissionDenied('This control can retry Sheet updates only.')
    if dispatch.workflow_revision != case.workflow_revision:
        raise ValueError('This update was replaced by a newer case change. Check App status again.')
    group = GroupSheetConfiguration.objects.filter(group_id=case.group_id, enabled=True).first()
    if not group or not group.tat_sheet_projection_enabled or case.configuration_binding_status == case.CONFIG_UNRESOLVED:
        raise ValueError('Ask IT to check the case configuration and enable its Sheet projection first.')
    if dispatch.status in {dispatch.STATUS_PENDING, dispatch.STATUS_RUNNING, dispatch.STATUS_SUCCEEDED}:
        return dispatch.status  # Duplicate taps never reset a lease or completed work.
    if dispatch.status not in {dispatch.STATUS_NEEDS_ATTENTION, dispatch.STATUS_RETRYABLE}:
        raise ValueError('This update is no longer available for retry.')
    from core.services.compliance_audit import record_event
    record_event(
        workflow='tat_tracker', action='tat.sheet_projection.retry', category='configuration', origin='human',
        subject_type='tat_dispatch', subject_id=str(dispatch.pk), actor=actor, authority_user=actor,
        source_model='TatUpdateSideEffectDispatch', source_event_id=f'{dispatch.pk}:{dispatch.total_attempts}',
        deduplication_key=f'tat-sheet-retry:{dispatch.pk}:{dispatch.total_attempts}',
        before_values={'status': dispatch.status, 'error_code': dispatch.last_error_code,
                       'error_message': dispatch.last_error_message}, after_values={'status': 'pending'},
    )
    dispatch.status = dispatch.STATUS_PENDING
    dispatch.cycle_attempts = 0
    dispatch.next_retry_at = None
    dispatch.completed_at = None
    dispatch.manual_retry_reason = 'Confirmed Retry sync from TAT App status.'
    dispatch.manual_retry_by = actor
    # Keep error evidence until the worker records the next outcome.
    dispatch.save(update_fields=['status', 'cycle_attempts', 'next_retry_at', 'completed_at',
                                 'manual_retry_reason', 'manual_retry_by', 'updated_at'])
    return dispatch.status


def status_payload(actor, group, *, page=1, access=None):
    cases = scoped_cases(actor, access=access).filter(group_id=group.group_id)
    retry_ids = scoped_cases(actor, 'tat.publication.retry', access=access).values('pk')
    rows = []
    dispatches = TatUpdateSideEffectDispatch.objects.filter(
        case__in=cases, workflow_revision=F('case__workflow_revision'),
    ).exclude(status__in=['succeeded', 'superseded']).select_related('case').order_by('-updated_at')
    for item in dispatches:
        sheet = item.effect_type == item.EFFECT_SHEET
        waiting = item.status in {'pending', 'running', 'retryable'}
        blocked = not group.tat_sheet_projection_enabled or item.case.configuration_binding_status == TatTrackerCase.CONFIG_UNRESOLVED
        setup = configuration_failure(item.last_error_code) or blocked
        action = None
        if sheet and not blocked and item.status in {'needs_attention', 'retryable'} and retry_ids.filter(pk=item.case_id).exists():
            action = request_action('Retry sync', '/api/tat-tracker/settings/recovery/retry/',
                                    {'dispatch_id': str(item.pk)},
                                    ('Repair the Sheet access or named-column configuration first. ' if setup else '')
                                    + 'Retry this Sheet update? The saved case will not be submitted again.')
        rows.append(issue(item.pk, 'Case Sheet update' if sheet else 'Signature delivery' if item.effect_type == item.EFFECT_SIGNATURE else 'Staff notification',
                          detail=f'{item.case.client_name or item.case.case_id} · Case changes are saved.',
                          status='Configuration required' if setup else 'Retrying' if item.status == 'running' else 'Waiting' if waiting else 'Needs review',
                          action=action, steps=(['Ask an active Django Superuser to open Django Admin → TAT update dispatches and locate this support reference.',
                                                'The Superuser can review and retry this delivery. Do not stamp or sign the stage again.'] if not sheet else
                                               ['Ask IT to check the TAT Sheet access, unique column names and case configuration.',
                                                'After the configuration is repaired, check status and retry the Sheet update.'] if setup else None)))
    from core.services.tat_comments import OPERATION_TYPE, COMMENT_CODE
    events = TatTrackerEvent.objects.filter(case__in=cases, transition_code=COMMENT_CODE)
    case_by_event = {str(e.pk): e.case for e in events.select_related('case')}
    for item in IntegrationOperation.objects.filter(operation_type=OPERATION_TYPE, source_model='core.TatTrackerEvent', source_id__in=case_by_event).exclude(status='succeeded').order_by('-updated_at'):
        case = case_by_event[item.source_id]
        blocked = not group.tat_sheet_projection_enabled or case.configuration_binding_status == TatTrackerCase.CONFIG_UNRESOLVED
        setup = configuration_failure(item.last_error_code) or blocked
        action = None
        if not blocked and item.status in {'retryable_failure', 'dead_letter'} and retry_ids.filter(pk=case.pk).exists():
            action = request_action('Retry sync', '/api/tat-tracker/settings/recovery/retry/', {'remark_operation_id': str(item.pk)},
                ('Repair the Sheet connection or named columns first. ' if setup else '') + 'Retry saving this remark to the Sheet? No new comment will be created.')
        rows.append(issue(item.pk, 'Remark Sheet update', detail=f'{case.client_name or case.case_id} · Remark is saved in TAT.',
                          status='Configuration required' if setup else 'Needs review' if item.status == 'dead_letter' else 'Waiting', action=action))
    from core.services.tat_tracker import tat_target_sheet_sync_health
    if can_retry_targets(actor, group, access=access):
        health = tat_target_sheet_sync_health(group)
        if health['status'] != 'synced':
            action = request_action('Retry sync', '/api/tat-tracker/target-settings/sync/', {},
                'Sync the group’s target Sheet? The targets used by TAT will not change.') if health.get('can_retry') else None
            rows.append(issue('tat-targets', 'Target Sheet', detail='App targets are saved and remain in use.',
                status='Configuration required' if health['status'] == 'not_configured' else 'Waiting' if health['status'] in {'pending', 'in_progress'} else 'Needs review',
                action=action, steps=['Ask TAT IT to check the target Sheet connection and access for this group.',
                                      'Use Retry sync after that connection is repaired. App targets remain live.']))
    from report_delivery.recovery import recovery_rows
    rows.extend(recovery_rows(actor, 'tat_tracker', group=group))
    return page_payload(rows, page)
