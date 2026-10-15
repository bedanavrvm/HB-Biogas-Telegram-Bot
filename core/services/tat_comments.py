"""Append-only TAT remarks, independent of stage transitions and their clocks."""
from datetime import timedelta
import logging
from time import monotonic
from zoneinfo import ZoneInfo

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.models import GroupSheetConfiguration, IntegrationOperation, TatTrackerCase, TatTrackerEvent
from core.services.external_resilience import execute_operation, operation_lease_seconds, reserve_operation
from core.services.workflow_data_mode import assert_record_writable, is_record_operational


COMMENT_CODE = 'comment.add'
OPERATION_TYPE = 'tat_comment_sheet_projection'
SEPARATOR = '\n────────────────────\n'
logger = logging.getLogger(__name__)


class RemarkConflict(ValueError):
    """A request key already identifies a different action."""


def remark_access(group_config, user, case):
    from django.contrib.auth import get_user_model
    from core.services.telegram_identity import user_access
    from core.services.workflow_access import workflow_access_decision

    supplied_actor = (user or {}).get('_canonical_user')
    actor = get_user_model().objects.filter(pk=getattr(supplied_actor, 'pk', None), is_active=True).first()
    if not actor:
        raise PermissionDenied('Reopen TAT Tracker to sign in before adding a remark.')
    # Re-read current grants: a cached payload is not continuing authority.
    decision = workflow_access_decision(
        actor, 'tat_tracker', 'tat.home.view',
        access=user_access(actor, 'tat_tracker', group_configuration=group_config),
        resource=case, group_configuration=group_config,
    )
    if not decision.allowed:
        raise PermissionDenied('You do not have access to this case.')
    return actor, decision


def can_add_remark(group_config, user, case):
    if case.is_deleted or case.configuration_binding_status == TatTrackerCase.CONFIG_UNRESOLVED or not is_record_operational(case):
        return False
    if group_config is None:
        group_config = GroupSheetConfiguration.objects.filter(group_id=case.group_id, enabled=True).first()
    if group_config is None:
        return False
    try:
        remark_access(group_config, user, case)
    except PermissionDenied:
        return False
    return True


def formatted_remark(event):
    from core.services.tat_tracker import role_display_name
    roles = ', '.join(role_display_name(role) for role in event.actor_role.split(',') if role)
    at = event.created_at.astimezone(ZoneInfo('Africa/Nairobi')).strftime('%d-%m-%Y %H:%M')
    footer = ' · '.join(filter(None, [at, event.actor_name, roles]))
    return f'{event.new_value}\n{footer}'


@transaction.atomic
def add_remark(group_config, user, case_id, text, *, request_id, expected_mode_version=None):
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 5000:
        raise ValueError('Enter a remark of 1 to 5,000 characters.')
    if not isinstance(request_id, str) or not 1 <= len(request_id.strip()) <= 128:
        raise ValueError('Reopen the case and try saving the remark again.')
    text, request_id = text.strip(), request_id.strip()
    case = TatTrackerCase.objects.select_for_update().get(
        group_id=str(group_config.group_id), case_id=str(case_id), is_deleted=False,
    )
    actor, decision = remark_access(group_config, user, case)
    assert_record_writable(case, expected_mode_version=expected_mode_version)
    if case.configuration_binding_status == TatTrackerCase.CONFIG_UNRESOLVED:
        raise ValueError('This case is read-only until IT resolves its workflow configuration.')
    existing = case.events.filter(request_id=request_id).first()
    if existing:
        if existing.transition_code != COMMENT_CODE or existing.actor_user_id != actor.pk or existing.new_value != text:
            raise RemarkConflict('This save request already belongs to another action. Reopen the case and try again.')
        return existing, IntegrationOperation.objects.filter(deduplication_key=f'tat-comment-sheet:{existing.pk}').first()
    from core.services.tat_tracker import record_tat_event
    event = record_tat_event(
        case=case, group_id=case.group_id, actor_user=actor, authority_user=actor,
        actor_name=actor.get_full_name() or actor.get_username(),
        actor_telegram_id=str(user.get('telegram_id') or ''),
        actor_role=','.join(decision.roles) or ('IT' if decision.technical_override else ''),
        stage_key='remarks_comment', stage_label='Comment added',
        old_value=case.remarks if not case.events.filter(transition_code=COMMENT_CODE).exists() else '',
        new_value=text, source='mini_app', request_id=request_id, transition_code=COMMENT_CODE,
    )
    notes = SEPARATOR.join(filter(None, [case.remarks, formatted_remark(event)]))
    # QuerySet.update deliberately avoids auto_now and workflow update hooks.
    TatTrackerCase.objects.filter(pk=case.pk).update(remarks=notes)
    operation = None
    if bool(getattr(group_config, 'tat_sheet_projection_enabled', True)):
        from core.services.telegram_identity import database_group_configuration
        database_group = database_group_configuration(group_config)
        operation, _ = reserve_operation(
            integration=IntegrationOperation.INTEGRATION_GOOGLE_SHEETS,
            operation_type=OPERATION_TYPE, deduplication_key=f'tat-comment-sheet:{event.pk}',
            source_model='core.TatTrackerEvent', source_id=str(event.pk), request_id=request_id,
            requested_by=actor, operation_payload={'event_id': str(event.pk)},
            metadata={'group_configuration_id': database_group.pk if database_group else None,
                      'group_id': case.group_id, 'case_id': str(case.pk)}, max_attempts=5,
        )
    return event, operation


@transaction.atomic
def publish_remark(event_id, *, group_configuration_id=None):
    """Publish current complete notes, never a stale captured append or stage row."""
    from core.services import tat_tracker
    from core.services.sheet_columns import read_named_columns, assert_columns_unchanged, named_updates
    from core.services.tat_sheet_schema import REMARK_HEADERS
    from core.services.sync_governance import assert_registered_schema_before_publish

    event = TatTrackerEvent.objects.get(pk=event_id, transition_code=COMMENT_CODE)
    case = TatTrackerCase.objects.select_for_update().get(pk=event.case_id, is_deleted=False)
    group = GroupSheetConfiguration.objects.filter(group_id=case.group_id, enabled=True).first()
    if group is None:
        raise RuntimeError('The saved TAT Sheet configuration is temporarily unavailable. Ask IT to check its setup.')
    if group_configuration_id is not None and group.pk != group_configuration_id:
        raise ValueError('The original TAT group configuration is no longer available.')
    if not tat_tracker.is_tat_tracker_workflow(group) or case.configuration_binding_status == TatTrackerCase.CONFIG_UNRESOLVED:
        raise ValueError('Resolve the TAT configuration before publishing remarks.')
    assert_record_writable(case)
    if not group.tat_sheet_projection_enabled:
        return {'action': 'projection_disabled'}
    sheet_name = tat_tracker.tat_projection_sheet_name(group)
    service = tat_tracker.get_sheets_service(sheet_id=group.sheet_id, sheet_name=sheet_name)
    if not service.is_available():
        raise RuntimeError('Google Sheets is temporarily unavailable.')
    sheet = service._sheet
    columns = read_named_columns(sheet, header_row=tat_tracker.TAT_TRACKER_HEADER_ROW)
    remarks_column = columns.column(*REMARK_HEADERS)
    remarks_header = columns.headers[remarks_column - 1]
    case_ids = sheet.col_values(columns.column('Case ID'))
    matches = [row for row, value in enumerate(case_ids, start=1)
               if row > tat_tracker.TAT_TRACKER_HEADER_ROW and str(value).strip() == case.case_id]
    if len(matches) > 1:
        raise ValueError('Duplicate Case ID in TAT Register; repair the rows before retrying.')
    if not matches:
        raise RuntimeError('The case Sheet row is temporarily unavailable; publish the case first.')
    row = matches[0]
    assert_registered_schema_before_publish(group, sheet_name, list(columns.headers))
    assert_columns_unchanged(sheet, columns, header_row=tat_tracker.TAT_TRACKER_HEADER_ROW)
    values = sheet.row_values(row)
    columns.validate_row(values)
    if str(columns.value(values, 'Case ID')).strip() != case.case_id:
        raise RuntimeError('The case Sheet row is temporarily unavailable after sorting; retry.')
    if columns.value(values, *REMARK_HEADERS) != case.remarks:
        sheet.batch_update(named_updates(columns, row, {remarks_header: case.remarks}), value_input_option='RAW')
    TatTrackerEvent.objects.filter(pk=event.pk).update(
        synced_to_sheet=True, synced_at=timezone.now(), sheet_name=sheet_name, row_number=row, sync_error='',
    )
    return {'action': 'remarks_published'}


def process_remark_publications(*, limit=50, max_seconds=30):
    deadline = monotonic() + max_seconds
    now = timezone.now()
    due = IntegrationOperation.objects.filter(operation_type=OPERATION_TYPE).filter(
        Q(status__in=[IntegrationOperation.STATUS_PENDING, IntegrationOperation.STATUS_RETRYABLE])
        | Q(status=IntegrationOperation.STATUS_RUNNING, last_attempt_at__lt=now - timedelta(seconds=operation_lease_seconds()))
    ).filter(Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=now)).order_by('created_at')
    processed = 0
    for operation in due[:max(1, min(limit, 500))]:
        if monotonic() >= deadline:
            break
        try:
            execute_operation(operation, lambda: publish_remark(operation.source_id, group_configuration_id=operation.metadata.get('group_configuration_id')), attempt_budget=1)
        except Exception:
            logger.warning('TAT remark publication pending or needs repair; operation=%s.', operation.pk)
        processed += 1
    return processed


@transaction.atomic
def retry_remark_publication(operation_id, *, actor):
    """Requeue only a reviewed failed remark projection; never call Google here."""
    from django.contrib.auth import get_user_model
    actor = get_user_model().objects.filter(pk=getattr(actor, 'pk', None), is_active=True).first()
    if not actor:
        raise PermissionDenied('An active TAT staff account is required.')
    operation = IntegrationOperation.objects.select_for_update().get(
        pk=operation_id, operation_type=OPERATION_TYPE,
        integration=IntegrationOperation.INTEGRATION_GOOGLE_SHEETS,
    )
    event = TatTrackerEvent.objects.get(pk=operation.source_id, transition_code=COMMENT_CODE)
    case = TatTrackerCase.objects.get(pk=event.case_id, is_deleted=False)
    from core.services.tat_recovery import require_sheet_authority
    require_sheet_authority(actor, case)
    if operation.status not in {IntegrationOperation.STATUS_RETRYABLE, IntegrationOperation.STATUS_DEAD_LETTER}:
        return False
    group_query = GroupSheetConfiguration.objects.filter(enabled=True, group_id=case.group_id)
    if operation.metadata.get('group_configuration_id') is not None:
        group_query = group_query.filter(pk=operation.metadata['group_configuration_id'])
    group = group_query.get()
    if not group.tat_sheet_projection_enabled or case.configuration_binding_status == TatTrackerCase.CONFIG_UNRESOLVED:
        raise ValueError('Check this case and its Sheet settings before retrying.')
    assert_record_writable(case)
    retry_number = int(operation.metadata.get('remark_retry_count', 0)) + 1
    from core.services.compliance_audit import record_event
    record_event(
        workflow='tat_tracker', action='tat.comment_projection.retry', category='configuration', origin='human',
        subject_type='integration_operation', subject_id=str(operation.pk), actor=actor, authority_user=actor,
        source_model='IntegrationOperation', source_event_id=f'{operation.pk}:retry:{retry_number}',
        deduplication_key=f'tat-comment-retry:{operation.pk}:{retry_number}',
        before_values={'status': operation.status, 'attempts': operation.attempts, 'error_code': operation.last_error_code},
        after_values={'status': IntegrationOperation.STATUS_PENDING, 'attempts': 0},
        metadata={'event_id': str(event.pk), 'retry_number': retry_number},
    )
    operation.status = IntegrationOperation.STATUS_PENDING
    operation.attempts = 0
    operation.next_retry_at = None
    operation.last_error_code = ''
    operation.last_error = ''
    operation.metadata = {**operation.metadata, 'remark_retry_count': retry_number, 'group_configuration_id': group.pk}
    operation.save(update_fields=['status', 'attempts', 'next_retry_at', 'last_error_code', 'last_error', 'metadata', 'updated_at'])
    return True
