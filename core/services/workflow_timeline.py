"""Internal, query-time timeline projections for workflow case views.

The source workflow events remain the audit record.  This module only joins
those immutable records with related operational artifacts for staff-facing
history.  It intentionally has no write or synchronization side effects.
"""

from __future__ import annotations

from typing import Any, Iterable

from core.models import (
    JawabuDataQualityResolution,
    JawabuFarmerMaster,
    JawabuPipelineEvent,
    JawabuCustomerFieldProvenance,
    MediaAttachment,
    ParsedInvoice,
    PaymentDocument,
    RequisitionBatch,
    TatTrackerCase,
    WorkflowTimelineAnnotation,
)


def _actor_name(user, fallback: str = '') -> str:
    if user is None:
        return str(fallback or '')
    return user.get_full_name() or user.get_username() or str(fallback or '')


def _origin(source: str) -> str:
    source = str(source or '').strip().lower()
    if source in {'sheet_sync', 'system_export', 'imab', 'sync'}:
        return 'synchronization'
    if source in {'system', 'automation', 'workflow_transition'}:
        return 'automation'
    if source in {'admin_correction', 'admin'}:
        return 'admin'
    if source in {'mini_app', 'portal', 'telegram'}:
        return 'staff'
    return source or 'system'


def _annotations(workflow: str, subject_id: str) -> tuple[dict[str, WorkflowTimelineAnnotation], list[WorkflowTimelineAnnotation]]:
    rows = list(WorkflowTimelineAnnotation.objects.filter(
        workflow=workflow,
        subject_id=str(subject_id),
    ).select_related('actor', 'authority_user'))
    redactions = {
        row.source_event_id: row
        for row in rows
        if row.kind == 'redaction'
    }
    return redactions, rows


def _entry(
    *,
    source_id: str,
    action: str,
    occurred_at,
    actor: str = '',
    authority: str = '',
    source: str = 'system',
    stage: str = '',
    detail: str = '',
    artifact: dict[str, str] | None = None,
    redaction: WorkflowTimelineAnnotation | None = None,
    kind: str = 'event',
) -> dict[str, Any]:
    public_id = source_id.split(':', 1)[1] if source_id.startswith('jawabu:') else source_id
    entry = {
        # Jawabu Case 360 historically exposed the raw pipeline UUID as `id`.
        # Preserve that contract while carrying the cross-source identifier in
        # `source_event_id` for annotations and future clients.
        'id': public_id,
        'source_event_id': source_id,
        'action': action,
        'title': action.replace('_', ' ').strip().title(),
        'kind': kind,
        'stage': stage,
        'actor': actor,
        'authority': authority,
        'source': source,
        'origin': _origin(source),
        'detail': detail,
        'occurred_at': occurred_at.isoformat(),
        'artifact': artifact,
        'redacted': bool(redaction),
        'redaction_reason': str(redaction.note or '') if redaction else '',
    }
    if redaction:
        entry['detail'] = 'Sensitive event content has been redacted.'
    return entry


def _annotation_entries(rows: Iterable[WorkflowTimelineAnnotation]) -> list[dict[str, Any]]:
    entries = []
    for row in rows:
        if row.kind == 'redaction':
            action = 'timeline_entry_redacted'
            detail = row.note or 'Sensitive content redacted by an authorised staff member.'
        elif row.kind == 'correction':
            action = 'timeline_entry_corrected'
            detail = row.note
        else:
            action = 'timeline_artifact_linked'
            detail = row.note
        entries.append(_entry(
            source_id=f'annotation:{row.id}',
            action=action,
            occurred_at=row.created_at,
            actor=_actor_name(row.actor),
            authority=_actor_name(row.authority_user),
            source='admin_correction',
            detail=detail,
            artifact={'name': row.artifact_name, 'url': row.artifact_url} if row.artifact_url else None,
            kind='annotation',
        ))
    return entries


def jawabu_case_timeline(farmer: JawabuFarmerMaster) -> dict[str, Any]:
    """Return the unified internal history for a Jawabu application."""
    redactions, annotations = _annotations('jawabu_pipeline', str(farmer.pk))
    entries: list[dict[str, Any]] = []
    # Keep a pathological event history from holding a mobile request open
    # indefinitely. The complete append-only ledger remains in Django/Admin;
    # Case History is a bounded operational projection.
    for event in farmer.pipeline_events.select_related('actor_user', 'authority_user').order_by('-occurred_at', '-created_at')[:500]:
        source_id = f'jawabu:{event.id}'
        entries.append(_entry(
            source_id=source_id,
            action=event.action,
            occurred_at=event.occurred_at,
            actor=_actor_name(event.actor_user, event.actor),
            authority=_actor_name(event.authority_user),
            source=event.source,
            stage=event.stage_key,
            detail=event.reason,
            redaction=redactions.get(source_id),
        ))

    for provenance in farmer.field_provenance.order_by('-occurred_at')[:100]:
        source_id = f'provenance:{provenance.id}'
        entries.append(_entry(
            source_id=source_id,
            action='customer_field_synchronized',
            occurred_at=provenance.occurred_at,
            actor=provenance.actor,
            source=provenance.source,
            stage='identity',
            detail=f'{provenance.field_name} updated from {provenance.source_reference or provenance.source}.',
            redaction=redactions.get(source_id),
            kind='provenance',
        ))

    for resolution in JawabuDataQualityResolution.objects.filter(issue__farmer=farmer).select_related('issue').order_by('-created_at')[:100]:
        source_id = f'quality:{resolution.id}'
        entries.append(_entry(
            source_id=source_id,
            action=f'data_quality_{resolution.action}',
            occurred_at=resolution.created_at,
            actor=resolution.actor,
            source='admin_correction',
            stage='data_quality',
            detail=resolution.note,
            redaction=redactions.get(source_id),
            kind='data_quality',
        ))

    national_id = str(farmer.national_id or '').strip()
    if national_id:
        for media in MediaAttachment.objects.filter(
            business_key_type='id_number',
            business_key_value=national_id,
            upload_status='success',
        ).order_by('-created_at')[:100]:
            source_id = f'media:{media.id}'
            entries.append(_entry(
                source_id=source_id,
                action='visit_media_uploaded',
                occurred_at=media.created_at,
                actor=media.sender,
                source='telegram',
                stage='jbl_visit',
                detail=media.file_type or 'Visit media',
                artifact={'name': media.original_filename or 'Visit media', 'url': media.drive_url} if media.drive_url else None,
                redaction=redactions.get(source_id),
                kind='document',
            ))

    if farmer.order_number:
        requisition = RequisitionBatch.objects.filter(order_number=farmer.order_number).order_by('-updated_at').first()
        if requisition:
            source_id = f'requisition:{requisition.id}'
            entries.append(_entry(
                source_id=source_id,
                action='requisition_generated',
                occurred_at=requisition.updated_at,
                actor=requisition.generated_by,
                source='portal',
                stage='order',
                detail=f'Order {requisition.order_number}, version {requisition.version}.',
                artifact={'name': requisition.filename, 'url': requisition.drive_url} if requisition.drive_url else None,
                redaction=redactions.get(source_id),
                kind='document',
            ))

    for invoice in ParsedInvoice.objects.filter(matched_farmer=farmer).select_related('batch').order_by('-updated_at')[:20]:
        source_id = f'invoice:{invoice.id}'
        entries.append(_entry(
            source_id=source_id,
            action=f'invoice_{invoice.status}',
            occurred_at=invoice.updated_at,
            source='synchronization',
            stage='invoice',
            detail=invoice.invoice_no or 'Invoice record',
            artifact={'name': invoice.batch.original_filename, 'url': invoice.batch.drive_url} if invoice.batch.drive_url else None,
            redaction=redactions.get(source_id),
            kind='document',
        ))

    # A payment document is generated from an order batch.  Filtering at the
    # database avoids scanning every historic payment document on every case
    # detail request while retaining all versions for this case's order.
    for document in PaymentDocument.objects.filter(
        order_number=farmer.order_number,
        status__in=['pending_review', 'reviewed', 'final'],
    ).order_by('-updated_at')[:50]:
        source_id = f'payment:{document.id}'
        entries.append(_entry(
            source_id=source_id,
            action=f'payment_{document.status}',
            occurred_at=document.finalized_at or document.reviewed_at or document.updated_at,
            actor=document.finalized_by or document.reviewed_by or document.generated_by,
            source='portal',
            stage='payment',
            detail=f'Payment {document.payment_number or document.order_number}, version {document.version}.',
            artifact={'name': document.filename, 'url': document.drive_url} if document.drive_url else None,
            redaction=redactions.get(source_id),
            kind='document',
        ))

    entries.extend(_annotation_entries(annotations))
    entries.sort(key=lambda item: item['occurred_at'], reverse=True)
    related_cases = []
    if farmer.customer_id:
        related_cases = [
            {
                'id': str(application.pk),
                'unit_number': application.unit_number,
                'status': application.status,
                'customer_name': application.customer_name,
            }
            for application in farmer.customer.applications.exclude(pk=farmer.pk).order_by('-updated_at')[:20]
        ]
    return {'entries': entries, 'related_cases': related_cases}


def tat_case_timeline(case: TatTrackerCase) -> dict[str, Any]:
    """Return the same normalized history contract for a TAT case."""
    redactions, annotations = _annotations('tat_tracker', str(case.pk))
    entries = []
    for event in case.events.select_related('actor_user', 'authority_user').order_by('-created_at'):
        # These two rows are idempotency/transition receipts created alongside
        # the actual staff event. Keep them in the immutable audit store while
        # omitting the duplicate, technical entry from the staff timeline.
        if (
            event.source == 'workflow_transition'
            and event.stage_key == 'workflow_transition'
            and event.transition_code in {'tat.stage.advance', 'tat.case.update'}
        ):
            continue
        source_id = f'tat:{event.id}'
        entries.append(_entry(
            source_id=source_id,
            action=event.transition_code or event.stage_key or 'case_updated',
            occurred_at=event.created_at,
            actor=_actor_name(event.actor_user, event.actor_name),
            authority=_actor_name(event.authority_user),
            source=event.source,
            stage=event.stage_label or event.stage_key,
            detail=event.reason or event.new_value,
            redaction=redactions.get(source_id),
        ))
    entries.extend(_annotation_entries(annotations))
    entries.sort(key=lambda item: item['occurred_at'], reverse=True)
    return {'entries': entries, 'related_cases': []}
