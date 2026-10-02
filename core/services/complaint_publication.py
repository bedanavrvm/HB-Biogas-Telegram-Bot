"""Serialize current complaint snapshots without holding locks over Google calls."""
from datetime import timedelta
import uuid

from django.db import transaction
from django.utils import timezone

from core.models import ComplaintCaseControl, IntegrationOperation, ParsedMessage
from core.services.external_resilience import (
    execute_operation, external_call_budget, operation_lease_seconds, reserve_operation,
)

OPERATION_TYPE = 'complaint_case.publish'


def _claim_current(operation: IntegrationOperation) -> bool:
    control = ComplaintCaseControl.objects.select_for_update().get(pk=operation.source_id)
    if control.revision != operation.metadata['revision']:
        return False
    return not IntegrationOperation.objects.filter(
        operation_type=OPERATION_TYPE, source_model='ComplaintCaseControl', source_id=operation.source_id,
        status=IntegrationOperation.STATUS_RUNNING,
        last_attempt_at__gt=timezone.now() - timedelta(seconds=operation_lease_seconds()),
    ).exclude(pk=operation.pk).exists()


def publish_case_snapshot(group_config, case: ParsedMessage, service) -> bool:
    from core.services.complaint_cases import latest_resolution_text, resolution_comments_text, resolution_history_text
    for _ in range(2):
        with transaction.atomic():
            control = ComplaintCaseControl.objects.select_for_update().get(parsed_message_id=case.pk)
            revision = control.revision
            operation, _created = reserve_operation(
                integration=IntegrationOperation.INTEGRATION_GOOGLE_SHEETS, operation_type=OPERATION_TYPE,
                deduplication_key=f'complaint-publish:{control.pk}:{revision}:{uuid.uuid4().hex}',
                source_model='ComplaintCaseControl', source_id=str(control.pk),
                metadata={'revision': revision, 'group_id': str(group_config.group_id)}, max_attempts=1,
            )

        def publish():
            current = ParsedMessage.objects.get(pk=case.pk)
            ended = current.date_resolved if current.complaint_status == 'Closed' and current.date_resolved else timezone.now()
            comments = resolution_comments_text(current)
            if len(comments) > 50000:
                raise ValueError('Resolution Comments exceeds the Sheet cell limit; all comments remain saved in Django.')
            updates = {
                'status': 'CLOSED' if current.complaint_status == 'Closed' else (
                    'REOPENED' if current.complaint_status == 'Reopened' else 'OPEN'),
                'resolution_details': latest_resolution_text(current), 'resolution_comments': comments,
                'resolution_history': resolution_history_text(current), 'gps_link': current.gps_link or '',
                'customer_phone': current.customer_phone, 'customer_id': current.customer_id,
                'complaint_category': current.complaint_category,
                'date_resolved': timezone.localtime(current.date_resolved).strftime('%d-%m-%y') if current.date_resolved else '',
                'days_open': max(0, int((ended - (current.timestamp or current.created_at)).total_seconds() // 86400)),
            }
            with external_call_budget(20):
                if not service.update_case_row(control.reference_number, updates):
                    raise RuntimeError('Complaint Sheet publication is pending.')
            return {'action': 'published'}

        result = execute_operation(operation, publish, attempt_budget=1, claim_guard=_claim_current)
        if result is None:
            # This attempt never owned the remote write. Its work is coalesced
            # into the live publisher's bounded follow-up, not a phantom queue.
            IntegrationOperation.objects.filter(pk=operation.pk, status=IntegrationOperation.STATUS_PENDING).update(
                status=IntegrationOperation.STATUS_SUCCEEDED,
                metadata={**operation.metadata, 'result': {'action': 'coalesced'}},
            )
            return False
        if ComplaintCaseControl.objects.filter(pk=control.pk, revision=revision).update(
            sync_status='success', sync_error='', last_sync_at=timezone.now(),
        ):
            return True
        # A comment or resolution committed during the remote write. Publish
        # its newer snapshot next; another live publisher safely wins instead.
    return False
