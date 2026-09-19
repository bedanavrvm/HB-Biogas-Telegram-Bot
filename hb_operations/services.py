from __future__ import annotations

from datetime import date
import uuid

from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date

from core.models import JawabuFarmerMaster, ParsedInvoice
from core.services.portal_publication import publication_payload, reserve_farmer_publication
from core.services.workflow_access import scope_workflow_queryset

from .models import HomeBiogasAction, HomeBiogasActionEvent


WORKFLOW = 'jawabu_portal'
VIEW_CAPABILITY = 'portal.hb_action.view'
WRITE_CAPABILITY = 'portal.hb_action.write'
CORRECT_CAPABILITY = 'portal.hb_action.correct'

STATE_FIELDS = (
    'installation_status', 'installation_date', 'serial_number', 'readiness_status',
    'pending_installation_comment', 'installation_report_status',
    'commissioning_status', 'commissioning_date', 'pending_commissioning_comment',
)


class HomeBiogasActionError(ValueError):
    pass


def _actor_label(actor) -> str:
    if not actor:
        return ''
    name = str(getattr(actor, 'get_full_name', lambda: '')() or '').strip()
    return name or str(getattr(actor, 'username', '') or getattr(actor, 'email', '') or actor)


def _snapshot(action: HomeBiogasAction) -> dict:
    values = {}
    for field in STATE_FIELDS:
        value = getattr(action, field)
        values[field] = value.isoformat() if isinstance(value, date) else value
    return values


def _display_date(value) -> str:
    return value.strftime('%d-%m-%Y') if value else ''


def _date_value(payload: dict, key: str):
    raw = str(payload.get(key) or '').strip()
    if not raw:
        return None
    value = parse_date(raw)
    if value is None:
        raise HomeBiogasActionError(f'{key.replace("_", " ").title()} must be a valid date.')
    return value


def _text(payload: dict, key: str, *, max_length: int | None = None) -> str:
    value = str(payload.get(key) or '').strip()
    if max_length and len(value) > max_length:
        raise HomeBiogasActionError(f'{key.replace("_", " ").title()} is too long.')
    return value


def scoped_actions(user, access, capability: str = VIEW_CAPABILITY):
    return scope_workflow_queryset(
        HomeBiogasAction.objects.select_related(
            'farmer', 'source_requisition_batch', 'source_signoff', 'updated_by',
        ),
        user, WORKFLOW, capability, access=access,
        branch_field='farmer__branch', product_field='farmer__payment_product',
        group_field='source_requisition_batch__group_configuration__group_id',
    )


def _invoice_for(action: HomeBiogasAction):
    return ParsedInvoice.objects.filter(
        matched_farmer=action.farmer, status='matched',
    ).order_by('-updated_at').first()


def serialize_action(action: HomeBiogasAction, *, include_history: bool = False) -> dict:
    farmer = action.farmer
    from core.services.jawabu_case_reference import display_case_reference

    invoice = _invoice_for(action)
    data = {
        'id': str(action.id),
        'farmer_id': str(farmer.id),
        'case_reference': display_case_reference(farmer.pk),
        'customer_name': farmer.customer_name,
        'branch': farmer.system_branch or farmer.branch,
        'product': farmer.payment_product,
        'primary_phone': farmer.primary_phone,
        'order_number': action.source_order_number,
        'installation_status': action.installation_status,
        'installation_status_label': action.get_installation_status_display(),
        'installation_date': action.installation_date.isoformat() if action.installation_date else '',
        'installation_date_display': _display_date(action.installation_date),
        'installation_date_label': 'Actual installation date' if action.installation_status == HomeBiogasAction.INSTALLATION_INSTALLED else 'Scheduled installation date',
        'serial_number': action.serial_number,
        'readiness_status': action.readiness_status,
        'readiness_status_label': action.get_readiness_status_display() if action.readiness_status else '',
        'pending_installation_comment': action.pending_installation_comment,
        'installation_report_status': action.installation_report_status,
        'installation_report_status_label': action.get_installation_report_status_display() if action.installation_report_status else '',
        'commissioning_status': action.commissioning_status,
        'commissioning_status_label': action.get_commissioning_status_display() if action.commissioning_status else '',
        'commissioning_date': action.commissioning_date.isoformat() if action.commissioning_date else '',
        'commissioning_date_display': _display_date(action.commissioning_date),
        'commissioning_date_label': 'Actual commissioning date' if action.commissioning_status == HomeBiogasAction.COMMISSIONING_DONE else 'Scheduled commissioning date',
        'pending_commissioning_comment': action.pending_commissioning_comment,
        'revision': action.revision,
        'released_at': action.created_at.isoformat(),
        'updated_at': action.updated_at.isoformat(),
        'updated_by': _actor_label(action.updated_by),
        'detail_url': reverse('portal_hb_action_detail', kwargs={'farmer_id': farmer.id}),
        'invoice': ({
            'id': str(invoice.id), 'number': invoice.invoice_no,
            'date': _display_date(invoice.invoice_date),
            'url': reverse('portal_invoice_screen_detail', kwargs={'invoice_id': invoice.id}),
        } if invoice else None),
        'publication': publication_payload(farmer),
    }
    if include_history:
        data['history'] = [
            {
                'id': str(event.id), 'event_type': event.event_type,
                'label': event.event_type.replace('_', ' ').replace('.', ' ').title(),
                'revision': event.revision, 'actor': event.actor_label,
                'reason': event.reason,
                'created_at': event.created_at.isoformat(),
            }
            for event in action.events.select_related('actor').order_by('-created_at')[:30]
        ]
    return data


@transaction.atomic
def release_requisition_signoff(signoff, *, actor=None) -> dict:
    """Release only a newly accepted requisition signoff; never backfill history."""
    from core.models import DocumentPhysicalSignoff, DocumentSignoffPolicy

    signoff = DocumentPhysicalSignoff.objects.select_for_update().select_related('requisition_batch').get(pk=signoff.pk)
    if signoff.document_type != DocumentSignoffPolicy.DOCUMENT_REQUISITION:
        raise HomeBiogasActionError('Only an accepted requisition can release HomeBiogas work.')
    if signoff.status != DocumentPhysicalSignoff.STATUS_SIGNED_APPROVED:
        raise HomeBiogasActionError('The signed and stamped requisition has not been accepted.')
    batch = signoff.requisition_batch
    if int(signoff.source_version or 0) != int(batch.version or 0):
        raise HomeBiogasActionError('The accepted scan is not for the current requisition version.')
    ids = []
    invalid_ids = []
    for raw_value in batch.farmer_ids or []:
        value = str(raw_value or '').strip()
        if not value:
            continue
        try:
            ids.append(str(uuid.UUID(value)))
        except (TypeError, ValueError, AttributeError):
            invalid_ids.append(value)
    farmers = {str(row.pk): row for row in JawabuFarmerMaster.objects.filter(pk__in=ids)}
    created = 0
    existing = 0
    missing = list(invalid_ids)
    for farmer_id in ids:
        farmer = farmers.get(farmer_id)
        if farmer is None:
            missing.append(farmer_id)
            continue
        action, was_created = HomeBiogasAction.objects.get_or_create(
            farmer=farmer,
            defaults={
                'source_requisition_batch': batch,
                'source_signoff': signoff,
                'source_order_number': batch.order_number,
                'source_requisition_version': batch.version,
                'created_by': actor,
                'updated_by': actor,
            },
        )
        if was_created:
            created += 1
            HomeBiogasActionEvent.objects.create(
                action=action, event_type='order.released_to_hb', revision=action.revision,
                actor=actor, actor_label=_actor_label(actor),
                request_id=f'hb-release:{signoff.pk}:{farmer.pk}',
                new_values={'order_number': batch.order_number, 'requisition_version': batch.version},
            )
        else:
            existing += 1
    return {'created': created, 'existing': existing, 'missing_farmer_ids': missing}


def _validate_progression(action: HomeBiogasAction, payload: dict, *, correction: bool = False) -> dict:
    target = _text(payload, 'installation_status', max_length=32)
    allowed_targets = {
        HomeBiogasAction.INSTALLATION_NEEDS_PLANNING: {HomeBiogasAction.INSTALLATION_PENDING, HomeBiogasAction.INSTALLATION_SCHEDULED, HomeBiogasAction.INSTALLATION_INSTALLED, HomeBiogasAction.INSTALLATION_CLOSED},
        HomeBiogasAction.INSTALLATION_PENDING: {HomeBiogasAction.INSTALLATION_PENDING, HomeBiogasAction.INSTALLATION_SCHEDULED, HomeBiogasAction.INSTALLATION_INSTALLED, HomeBiogasAction.INSTALLATION_CLOSED},
        HomeBiogasAction.INSTALLATION_SCHEDULED: {HomeBiogasAction.INSTALLATION_SCHEDULED, HomeBiogasAction.INSTALLATION_PENDING, HomeBiogasAction.INSTALLATION_INSTALLED, HomeBiogasAction.INSTALLATION_CLOSED},
        HomeBiogasAction.INSTALLATION_INSTALLED: {HomeBiogasAction.INSTALLATION_INSTALLED},
        HomeBiogasAction.INSTALLATION_CLOSED: set(),
    }
    if not (correction and target == action.installation_status) and target not in allowed_targets.get(action.installation_status, set()):
        raise HomeBiogasActionError('That installation change is not available from the current status.')
    readiness = _text(payload, 'readiness_status', max_length=24)
    comment = _text(payload, 'pending_installation_comment')
    installation_date = _date_value(payload, 'installation_date')
    serial = _text(payload, 'serial_number', max_length=128)
    report = _text(payload, 'installation_report_status', max_length=24)
    commissioning = _text(payload, 'commissioning_status', max_length=16)
    commissioning_date = _date_value(payload, 'commissioning_date')
    commissioning_comment = _text(payload, 'pending_commissioning_comment')

    if target in {HomeBiogasAction.INSTALLATION_PENDING, HomeBiogasAction.INSTALLATION_SCHEDULED}:
        if readiness not in dict(HomeBiogasAction.READINESS_CHOICES):
            raise HomeBiogasActionError('Choose the customer readiness status.')
        if target == HomeBiogasAction.INSTALLATION_SCHEDULED and not installation_date:
            raise HomeBiogasActionError('Choose the scheduled installation date.')
        if (readiness != HomeBiogasAction.READINESS_READY or not installation_date) and not comment:
            raise HomeBiogasActionError('Add a short pending installation comment.')
        return {
            'installation_status': target, 'installation_date': installation_date,
            'readiness_status': readiness, 'pending_installation_comment': comment,
            'serial_number': '', 'installation_report_status': '', 'commissioning_status': '',
            'commissioning_date': None, 'pending_commissioning_comment': '',
        }
    if target == HomeBiogasAction.INSTALLATION_CLOSED:
        if not comment:
            raise HomeBiogasActionError('Add a closure reason.')
        return {
            'installation_status': target, 'installation_date': None,
            'readiness_status': readiness or HomeBiogasAction.READINESS_NOT_CONFIRMED,
            'pending_installation_comment': comment, 'serial_number': '',
            'installation_report_status': '', 'commissioning_status': '',
            'commissioning_date': None, 'pending_commissioning_comment': '',
        }
    if not installation_date:
        raise HomeBiogasActionError('Choose the actual installation date.')
    if report not in dict(HomeBiogasAction.REPORT_CHOICES):
        raise HomeBiogasActionError('Choose whether the installation report was submitted.')
    if commissioning not in dict(HomeBiogasAction.COMMISSIONING_CHOICES):
        raise HomeBiogasActionError('Choose the commissioning status.')
    if commissioning == HomeBiogasAction.COMMISSIONING_DONE and not commissioning_date:
        raise HomeBiogasActionError('Choose the actual commissioning date.')
    if commissioning == HomeBiogasAction.COMMISSIONING_PENDING and not commissioning_date and not commissioning_comment:
        raise HomeBiogasActionError('Add a commissioning date or a pending commissioning comment.')
    return {
        'installation_status': target, 'installation_date': installation_date,
        'readiness_status': '', 'pending_installation_comment': '',
        'serial_number': serial, 'installation_report_status': report,
        'commissioning_status': commissioning, 'commissioning_date': commissioning_date,
        'pending_commissioning_comment': commissioning_comment if commissioning == HomeBiogasAction.COMMISSIONING_PENDING else '',
    }


def _sync_farmer(action: HomeBiogasAction, *, actor, request_id: str):
    farmer = JawabuFarmerMaster.objects.select_for_update().get(pk=action.farmer_id)
    labels = {
        HomeBiogasAction.INSTALLATION_NEEDS_PLANNING: 'Needs Planning',
        HomeBiogasAction.INSTALLATION_PENDING: 'Pending Installation',
        HomeBiogasAction.INSTALLATION_SCHEDULED: 'Scheduled',
        HomeBiogasAction.INSTALLATION_INSTALLED: 'Installed',
        HomeBiogasAction.INSTALLATION_CLOSED: 'Closed',
    }
    farmer.installation_status = labels[action.installation_status]
    farmer.workflow_revision = int(farmer.workflow_revision or 0) + 1
    farmer.save(update_fields=['installation_status', 'workflow_revision', 'updated_at'])
    return reserve_farmer_publication(
        farmer, request_id=request_id, requested_by=actor,
        requested_by_label=_actor_label(actor), required_capability=WRITE_CAPABILITY,
        deduplication_namespace='hb-action',
    )


@transaction.atomic
def transition_action(action_id, *, payload: dict, actor, request_id: str, expected_revision: int):
    action = HomeBiogasAction.objects.select_for_update().select_related('farmer').get(pk=action_id)
    duplicate = action.events.filter(request_id=request_id).first() if request_id else None
    if duplicate:
        return action, [], True
    if int(expected_revision) != int(action.revision):
        raise HomeBiogasActionError('This record changed after you opened it. Refresh and try again.')
    before = _snapshot(action)
    values = _validate_progression(action, payload)
    for key, value in values.items():
        setattr(action, key, value)
    action.revision += 1
    action.updated_by = actor
    action.save(update_fields=[*values.keys(), 'revision', 'updated_by', 'updated_at'])
    HomeBiogasActionEvent.objects.create(
        action=action, event_type='workflow.progressed', revision=action.revision,
        actor=actor, actor_label=_actor_label(actor), request_id=request_id,
        previous_values=before, new_values=_snapshot(action),
    )
    operations = _sync_farmer(action, actor=actor, request_id=request_id)
    return action, operations, False


@transaction.atomic
def correct_action(action_id, *, payload: dict, actor, request_id: str, expected_revision: int):
    action = HomeBiogasAction.objects.select_for_update().select_related('farmer').get(pk=action_id)
    duplicate = action.events.filter(request_id=request_id).first() if request_id else None
    if duplicate:
        return action, [], True
    if int(expected_revision) != int(action.revision):
        raise HomeBiogasActionError('This record changed after you opened it. Refresh and try again.')
    reason = _text(payload, 'reason')
    before = _snapshot(action)
    corrected = _validate_progression(
        action,
        {**before, **payload, 'installation_status': payload.get('installation_status', action.installation_status)},
        correction=True,
    )
    milestone_changed = any(
        before.get(key) != (value.isoformat() if isinstance(value, date) else value)
        for key, value in corrected.items()
        if key in {'installation_status', 'installation_date', 'commissioning_status', 'commissioning_date'}
    ) and (
        action.installation_status == HomeBiogasAction.INSTALLATION_INSTALLED
        or action.commissioning_status == HomeBiogasAction.COMMISSIONING_DONE
    )
    if milestone_changed and not reason:
        raise HomeBiogasActionError('Give a reason for changing a completed milestone.')
    for key, value in corrected.items():
        setattr(action, key, value)
    action.revision += 1
    action.updated_by = actor
    action.save(update_fields=[*corrected.keys(), 'revision', 'updated_by', 'updated_at'])
    HomeBiogasActionEvent.objects.create(
        action=action, event_type='record.corrected', revision=action.revision,
        actor=actor, actor_label=_actor_label(actor), request_id=request_id,
        previous_values=before, new_values=_snapshot(action), reason=reason,
    )
    operations = _sync_farmer(action, actor=actor, request_id=request_id)
    return action, operations, False
