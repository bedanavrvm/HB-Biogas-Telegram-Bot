"""Controlled Portal maintenance state and read-only operational projection."""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import transaction


def current_maintenance_state():
    """Return the singleton without creating state during ordinary read traffic."""
    from core.models import PortalMaintenanceState

    return PortalMaintenanceState.objects.filter(singleton=1).first()


def maintenance_write_blocked() -> tuple[bool, str]:
    state = current_maintenance_state()
    if state and state.mode == state.MODE_MAINTENANCE:
        reason = str(state.reason or '').strip()
        message = 'Portal is under maintenance. You can keep viewing records, but new changes are temporarily paused.'
        if reason:
            message = f'{message} {reason}'
        return True, message
    return False, ''


@transaction.atomic
def set_maintenance_state(*, actor, mode: str, reason: str, request_id: str = ''):
    """Change the IT-controlled read-only gate and leave compliance evidence."""
    from core.models import ComplianceAuditEvent, PortalMaintenanceState

    normalized_mode = str(mode or '').strip().lower()
    if normalized_mode not in {PortalMaintenanceState.MODE_LIVE, PortalMaintenanceState.MODE_MAINTENANCE}:
        raise ValidationError('Choose Live or Under maintenance.')
    normalized_reason = str(reason or '').strip()
    if normalized_mode == PortalMaintenanceState.MODE_MAINTENANCE and not normalized_reason:
        raise ValidationError('A maintenance reason is required before Portal can become read-only.')
    if len(normalized_reason) > 500:
        raise ValidationError('Maintenance reason must be 500 characters or fewer.')

    # A Telegram/WebView retry must never replay an old switch after another
    # IT operator has already changed the state. The immutable audit event is
    # the durable receipt for this small, high-impact write.
    if request_id and ComplianceAuditEvent.objects.filter(
        action='portal.maintenance.changed',
        request_id=request_id,
        source_model='PortalMaintenanceState',
        source_event_id='singleton:1',
    ).exists():
        return PortalMaintenanceState.objects.select_for_update().get_or_create(singleton=1)[0]

    state, _created = PortalMaintenanceState.objects.select_for_update().get_or_create(singleton=1)
    before = {'mode': state.mode, 'reason': state.reason}
    state.mode = normalized_mode
    state.reason = normalized_reason if normalized_mode == PortalMaintenanceState.MODE_MAINTENANCE else ''
    state.updated_by = actor
    state.save(update_fields=['mode', 'reason', 'updated_by', 'updated_at'])

    if before != {'mode': state.mode, 'reason': state.reason}:
        from core.services.compliance_audit import record_event

        record_event(
            workflow='jawabu_portal',
            action='portal.maintenance.changed',
            category='operations',
            origin='human',
            actor=actor,
            subject_type='portal_maintenance_state',
            subject_id='singleton:1',
            deduplication_key=f'portal-maintenance:{request_id}' if request_id else '',
            source_model='PortalMaintenanceState',
            source_event_id='singleton:1',
            before_values=before,
            after_values={'mode': state.mode, 'reason': state.reason},
            metadata={'request_id': request_id},
            request_id=request_id,
            sensitive=False,
        )
    return state
