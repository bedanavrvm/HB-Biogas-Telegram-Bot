"""Shared, append-only compliance evidence for all Mini App workflows.

This service deliberately supplements, rather than replaces, workflow-native
event models.  Native records retain operational detail; the ledger below gives
investigators one consistent shape and a verifiable sequence across workflows.
"""
from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from io import StringIO
from typing import Any
from uuid import UUID, uuid4

from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.template.loader import render_to_string
from django.utils import timezone

from core.models import (
    ComplianceAuditChainState,
    ComplianceAuditCheckpoint,
    ComplianceAuditEvent,
)


class ComplianceAuditError(ValueError):
    """Raised for an unsafe or unverifiable compliance-audit operation."""


@dataclass(frozen=True)
class IntegrityReport:
    ok: bool
    checked: int
    first_error: str = ''
    first_error_position: int | None = None


def _json_safe(value: Any) -> Any:
    """Return a deterministic JSON-safe value without recording request secrets."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)


def _event_payload(values: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _json_safe(value)
        for key, value in values.items()
        if key not in {'chain_position', 'previous_hash', 'payload_hash', 'integrity_hash'}
    }


def _hash_payload(payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, ensure_ascii=True, separators=(',', ':'), sort_keys=True)
    return hashlib.sha256(serialized.encode('utf-8')).hexdigest()


def _integrity_hash(*, position: int, previous_hash: str, payload_hash: str) -> str:
    return hashlib.sha256(f'{position}:{previous_hash}:{payload_hash}'.encode('ascii')).hexdigest()


def _label_for_user(user) -> str:
    if not user:
        return ''
    return str(user.get_full_name() or user.get_username() or '').strip()


def record_event(
    *,
    workflow: str,
    action: str,
    subject_type: str,
    subject_id: str,
    deduplication_key: str,
    category: str = 'workflow',
    origin: str = ComplianceAuditEvent.ORIGIN_HUMAN,
    customer_reference: str = '',
    actor=None,
    authority_user=None,
    actor_label: str = '',
    authority_label: str = '',
    request_id: str = '',
    source_model: str = '',
    source_event_id: str = '',
    before_values: dict | None = None,
    after_values: dict | None = None,
    metadata: dict | None = None,
    sensitive: bool = False,
    occurred_at=None,
) -> tuple[ComplianceAuditEvent, bool]:
    """Append a verifiable audit event or return the existing idempotent one."""
    key = str(deduplication_key or '').strip()
    if not key:
        raise ComplianceAuditError('A stable audit deduplication key is required.')
    if len(key) > 255:
        key = hashlib.sha256(key.encode('utf-8')).hexdigest()

    existing = ComplianceAuditEvent.objects.filter(deduplication_key=key).first()
    if existing:
        return existing, False

    with transaction.atomic():
        # The seeded singleton row is a lock even for an otherwise empty audit
        # table, which prevents duplicate chain positions under concurrent taps.
        state = ComplianceAuditChainState.objects.select_for_update().get(singleton=1)
        existing = ComplianceAuditEvent.objects.filter(deduplication_key=key).first()
        if existing:
            return existing, False

        position = state.last_position + 1
        values = {
            'workflow': workflow,
            'action': str(action),
            'category': str(category),
            'origin': origin,
            'subject_type': str(subject_type),
            'subject_id': str(subject_id),
            'customer_reference': str(customer_reference or ''),
            'actor_id': getattr(actor, 'pk', None),
            'authority_user_id': getattr(authority_user, 'pk', None),
            'actor_label': str(actor_label or _label_for_user(actor)),
            'authority_label': str(authority_label or _label_for_user(authority_user)),
            'request_id': str(request_id or ''),
            'source_model': str(source_model or ''),
            'source_event_id': str(source_event_id or ''),
            'deduplication_key': key,
            'before_values': _json_safe(before_values or {}),
            'after_values': _json_safe(after_values or {}),
            'metadata': _json_safe(metadata or {}),
            'sensitive': bool(sensitive),
            'occurred_at': occurred_at or timezone.now(),
            'chain_position': position,
            'previous_hash': state.last_hash,
        }
        payload_hash = _hash_payload(_event_payload(values))
        integrity_hash = _integrity_hash(
            position=position,
            previous_hash=state.last_hash,
            payload_hash=payload_hash,
        )
        try:
            event = ComplianceAuditEvent.objects.create(
                **values,
                payload_hash=payload_hash,
                integrity_hash=integrity_hash,
            )
        except IntegrityError:
            existing = ComplianceAuditEvent.objects.filter(deduplication_key=key).first()
            if existing:
                return existing, False
            raise
        state.last_position = position
        state.last_hash = integrity_hash
        state.save(update_fields=['last_position', 'last_hash', 'updated_at'])
        return event, True


def record_sensitive_access(
    *,
    workflow: str,
    action: str,
    subject_type: str,
    subject_id: str,
    actor=None,
    actor_label: str = '',
    request_id: str = '',
    metadata: dict | None = None,
) -> ComplianceAuditEvent:
    """Record a sensitive record view/download without storing the content itself."""
    token = request_id or str(uuid4())
    event, _created = record_event(
        workflow=workflow,
        action=action,
        category='sensitive_access',
        origin=ComplianceAuditEvent.ORIGIN_HUMAN,
        subject_type=subject_type,
        subject_id=subject_id,
        actor=actor,
        actor_label=actor_label,
        request_id=request_id,
        source_model='sensitive_access',
        source_event_id=token,
        deduplication_key=f'sensitive-access:{workflow}:{action}:{subject_type}:{subject_id}:{token}',
        metadata=metadata or {},
        sensitive=True,
    )
    return event


def verify_integrity(queryset: QuerySet[ComplianceAuditEvent] | None = None) -> IntegrityReport:
    """Verify hash linkage and event payload hashes without modifying evidence."""
    events = (queryset or ComplianceAuditEvent.objects.all()).order_by('chain_position')
    previous_hash = ''
    expected_position = 1
    checked = 0
    for event in events.iterator():
        if event.chain_position != expected_position:
            return IntegrityReport(False, checked, 'Chain position is not contiguous.', event.chain_position)
        if event.previous_hash != previous_hash:
            return IntegrityReport(False, checked, 'Previous hash does not match the preceding event.', event.chain_position)
        values = {
            'workflow': event.workflow,
            'action': event.action,
            'category': event.category,
            'origin': event.origin,
            'subject_type': event.subject_type,
            'subject_id': event.subject_id,
            'customer_reference': event.customer_reference,
            'actor_id': event.actor_id,
            'authority_user_id': event.authority_user_id,
            'actor_label': event.actor_label,
            'authority_label': event.authority_label,
            'request_id': event.request_id,
            'source_model': event.source_model,
            'source_event_id': event.source_event_id,
            'deduplication_key': event.deduplication_key,
            'before_values': event.before_values,
            'after_values': event.after_values,
            'metadata': event.metadata,
            'sensitive': event.sensitive,
            'occurred_at': event.occurred_at,
            'chain_position': event.chain_position,
            'previous_hash': event.previous_hash,
        }
        payload_hash = _hash_payload(_event_payload(values))
        if payload_hash != event.payload_hash:
            return IntegrityReport(False, checked, 'Payload hash does not match the recorded evidence.', event.chain_position)
        integrity_hash = _integrity_hash(
            position=event.chain_position,
            previous_hash=event.previous_hash,
            payload_hash=event.payload_hash,
        )
        if integrity_hash != event.integrity_hash:
            return IntegrityReport(False, checked, 'Integrity hash does not match the chain.', event.chain_position)
        previous_hash = event.integrity_hash
        expected_position += 1
        checked += 1
    return IntegrityReport(True, checked)


def filtered_events(*, filters: dict[str, Any] | None = None) -> QuerySet[ComplianceAuditEvent]:
    """Apply only explicit, investigator-facing filters to the immutable ledger."""
    filters = filters or {}
    events = ComplianceAuditEvent.objects.select_related('actor', 'authority_user').all()
    for field in ('workflow', 'action', 'origin', 'category'):
        if filters.get(field):
            events = events.filter(**{field: str(filters[field])})
    if filters.get('subject_id'):
        events = events.filter(subject_id=str(filters['subject_id']))
    if filters.get('customer_reference'):
        events = events.filter(customer_reference=str(filters['customer_reference']))
    if filters.get('actor_id'):
        events = events.filter(actor_id=filters['actor_id'])
    if filters.get('sensitive') in {True, 'true', '1', 'yes'}:
        events = events.filter(sensitive=True)
    if filters.get('from'):
        events = events.filter(occurred_at__date__gte=filters['from'])
    if filters.get('to'):
        events = events.filter(occurred_at__date__lte=filters['to'])
    return events.order_by('-chain_position')


def evidence_rows(queryset: QuerySet[ComplianceAuditEvent]) -> list[list[str]]:
    rows = [[
        'Position', 'Occurred at (EAT)', 'Workflow', 'Action', 'Origin',
        'Subject', 'Actor', 'Authority', 'Sensitive', 'Request ID', 'Integrity hash',
    ]]
    for item in queryset:
        rows.append([
            str(item.chain_position),
            timezone.localtime(item.occurred_at).strftime('%d-%b-%Y %H:%M:%S'),
            item.get_workflow_display(), item.action, item.get_origin_display(),
            f'{item.subject_type}:{item.subject_id}', item.actor_label,
            item.authority_label, 'Yes' if item.sensitive else 'No',
            item.request_id, item.integrity_hash,
        ])
    return rows


def evidence_csv(queryset: QuerySet[ComplianceAuditEvent]) -> str:
    output = StringIO()
    csv.writer(output).writerows(evidence_rows(queryset))
    return output.getvalue()


def evidence_pdf(queryset: QuerySet[ComplianceAuditEvent]) -> bytes:
    from weasyprint import HTML

    html = render_to_string('admin/core/compliance_audit_evidence.html', {
        'generated_at': timezone.localtime(),
        'rows': evidence_rows(queryset)[1:],
    })
    return HTML(string=html).write_pdf()


def create_daily_checkpoint(*, checkpoint_date=None) -> tuple[ComplianceAuditCheckpoint, bool]:
    checkpoint_date = checkpoint_date or timezone.localdate()
    existing = ComplianceAuditCheckpoint.objects.filter(checkpoint_date=checkpoint_date).first()
    if existing:
        return existing, False
    state = ComplianceAuditChainState.objects.get(singleton=1)
    recipient = str(getattr(settings, 'COMPLIANCE_AUDIT_CHECKPOINT_RECIPIENT', '') or '').strip()
    enabled = bool(getattr(settings, 'COMPLIANCE_AUDIT_CHECKPOINT_DELIVERY_ENABLED', False) and recipient)
    checkpoint = ComplianceAuditCheckpoint.objects.create(
        checkpoint_date=checkpoint_date,
        chain_position=state.last_position,
        chain_hash=state.last_hash,
        event_count=ComplianceAuditEvent.objects.count(),
        recipient_fingerprint=hashlib.sha256(recipient.casefold().encode('utf-8')).hexdigest() if recipient else '',
        status=ComplianceAuditCheckpoint.STATUS_PENDING if enabled else ComplianceAuditCheckpoint.STATUS_DISABLED,
    )
    return checkpoint, True


def deliver_checkpoint(checkpoint: ComplianceAuditCheckpoint) -> ComplianceAuditCheckpoint:
    """Deliver only when both an operator command and explicit config enable it."""
    recipient = str(getattr(settings, 'COMPLIANCE_AUDIT_CHECKPOINT_RECIPIENT', '') or '').strip()
    if not getattr(settings, 'COMPLIANCE_AUDIT_CHECKPOINT_DELIVERY_ENABLED', False) or not recipient:
        raise ComplianceAuditError('Checkpoint delivery is disabled until an approved recipient is configured.')
    report = verify_integrity()
    if not report.ok:
        raise ComplianceAuditError(f'Integrity verification failed at position {report.first_error_position}: {report.first_error}')
    checkpoint.delivery_attempts += 1
    try:
        send_mail(
            subject=f'JBL compliance audit checkpoint {checkpoint.checkpoint_date:%d-%b-%Y}',
            message=(
                f'Chain position: {checkpoint.chain_position}\n'
                f'Chain hash: {checkpoint.chain_hash}\n'
                f'Event count: {checkpoint.event_count}\n'
                f'Integrity verified events: {report.checked}\n'
            ),
            from_email=None,
            recipient_list=[recipient],
            fail_silently=False,
        )
    except Exception as exc:
        checkpoint.status = ComplianceAuditCheckpoint.STATUS_FAILED
        checkpoint.delivery_error = str(exc)[:1000]
        checkpoint.save(update_fields=['status', 'delivery_error', 'delivery_attempts', 'updated_at'])
        raise
    checkpoint.status = ComplianceAuditCheckpoint.STATUS_SENT
    checkpoint.delivery_error = ''
    checkpoint.delivered_at = timezone.now()
    checkpoint.save(update_fields=['status', 'delivery_error', 'delivery_attempts', 'delivered_at', 'updated_at'])
    return checkpoint
