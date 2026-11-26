"""Audited amendments to historical complaints, without live response events."""
import hashlib
import json

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone

from core.models import ComplaintCaseControl, ComplaintCaseEvent, ParsedMessage
from core.services.compliance_audit import record_event
from . import services, workbook
from .models import ImportRow


@transaction.atomic
def apply_row(upload, row_id, *, group, actor, case_id, expected_revision,
              fields, notes, reason, request_key):
    owner = services.authorize(group, actor)
    if upload.group_id != owner.pk:
        raise ValueError('The source belongs to another Complaints workspace.')
    if (not isinstance(fields, dict) or set(fields) - {'status', 'date_resolved', 'resolution_details'}
            or not isinstance(notes, dict) or set(notes) - set(services.COMPLAINT_LABELS)):
        raise ValueError('Only reviewed historical status, resolution and notes are supported.')
    if any(not isinstance(v, str) or len(v) > 20000 for v in [*fields.values(), *notes.values()]):
        raise ValueError('Historical amendments require bounded text values.')
    if (not isinstance(request_key, str) or not 1 <= len(request_key) <= 128
            or not isinstance(reason, str) or not reason.strip() or len(reason) > 2000
            or type(expected_revision) is not int or expected_revision < 1):
        raise ValueError('Provide an audit reason and stable retry identifier.')
    row = ImportRow.objects.select_for_update().get(pk=row_id, upload=upload)
    if any(value.strip() != str(row.values.get(key, '')).strip() for key, value in notes.items()):
        raise ValueError('Historical notes must match the retained source cells.')
    case = ParsedMessage.objects.select_for_update().get(pk=case_id, group_id=group.group_id)
    control = ComplaintCaseControl.objects.select_for_update().get(parsed_message=case)
    if not services.cases.actor_can(group, actor, 'complaint.case.manage', case):
        raise PermissionDenied('This historical amendment is outside your Complaints scope.')
    if case.source != 'complaint_legacy' and fields:
        raise ValueError('App-created complaints must use their owning live workflow.')
    digest = hashlib.sha256(json.dumps({
        'source': str(row.pk), 'case': str(case.pk), 'fields': fields,
        'notes': notes, 'reason': reason,
    }, sort_keys=True).encode()).hexdigest()
    prior = control.events.filter(request_id=request_key).first()
    if prior:
        if prior.action != 'legacy_reconciled' or prior.payload_hash != digest:
            raise ValueError('This retry identifier belongs to a different amendment.')
        return row
    if not row.approved or row.committed_at or row.case_id:
        raise ValueError('Approve a new source-version row; original committed rows cannot be rewritten.')
    if control.revision != expected_revision:
        raise ValueError('The complaint changed after review. Reconcile the latest revision.')
    status = workbook.STATUSES.get(fields.get('status', case.complaint_status).upper())
    if not status:
        raise ValueError('Choose Open, Closed or Reopened.')
    resolved = case.date_resolved
    if 'date_resolved' in fields:
        resolved = workbook.reported_date(fields['date_resolved']) if fields['date_resolved'].strip() else None
        if fields['date_resolved'].strip() and resolved is None:
            raise ValueError('Supply a valid historical closure date.')
    if status != 'Closed':
        if fields.get('date_resolved', '').strip():
            raise ValueError('Only closed complaints can have a closure date.')
        resolved = None
    if resolved and (not case.timestamp or not case.timestamp <= resolved <= timezone.now()):
        raise ValueError('Closure must be between reporting and today.')
    before = {'status': case.complaint_status, 'date_resolved': workbook.literal(case.date_resolved),
              'resolution_details': case.resolution_details}
    case.complaint_status, case.date_resolved = status, resolved
    if 'resolution_details' in fields:
        case.resolution_details = fields['resolution_details'].strip()
    after = {'status': status, 'date_resolved': workbook.literal(resolved),
             'resolution_details': case.resolution_details}
    if before == after and not any(v.strip() for v in notes.values()):
        raise ValueError('No historical facts changed.')
    case.save(update_fields=['complaint_status', 'date_resolved', 'resolution_details'])
    control.revision += 1
    control.save(update_fields=['revision', 'updated_at'])
    event = ComplaintCaseEvent.objects.create(
        case=control, revision=control.revision, action='legacy_reconciled', actor=actor.user,
        actor_label=actor.name, request_id=request_key, payload_hash=digest, before_values=before,
        after_values={**after, 'historical_notes': {k: v.strip() for k, v in notes.items() if v.strip()},
                      'source_hash': upload.digest, 'source_row': row.source_row}, reason=reason,
    )
    row.case, row.committed_at = case, timezone.now()
    row.proposal = {**row.proposal, 'reconciliation': {'event': str(event.pk), 'fields': fields, 'notes': notes}}
    row.save(update_fields=['case', 'committed_at', 'proposal'])
    record_event(workflow='complaint_cases', action='complaint.legacy.reconciled', actor=actor.user,
                 subject_type='complaint_case', subject_id=str(case.pk), request_id=request_key,
                 deduplication_key=f'complaint-legacy-reconcile:{event.pk}',
                 source_model='ComplaintCaseEvent', source_event_id=str(event.pk),
                 before_values=before, after_values=event.after_values,
                 metadata={'source_hash': upload.digest, 'source_row': row.source_row}, sensitive=True)
    services.queue_row(row, group)
    return row
