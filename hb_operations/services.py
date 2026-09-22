from __future__ import annotations

from datetime import date, timedelta
import uuid

from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date

from core.models import JawabuFarmerMaster, ParsedInvoice, RequisitionBatch
from core.services.portal_publication import publication_payload, reserve_farmer_publication
from core.services.workflow_access import scope_workflow_queryset

from .models import HomeBiogasAction, HomeBiogasActionEvent


WORKFLOW = 'jawabu_portal'
VIEW_CAPABILITY = 'portal.hb_action.view'
WRITE_CAPABILITY = 'portal.hb_action.write'
CORRECT_CAPABILITY = 'portal.hb_action.correct'

STATE_FIELDS = (
    'installation_status', 'planned_installation_date', 'installation_date', 'serial_number', 'readiness_status',
    'pending_installation_comment', 'installation_report_status',
    'commissioning_status', 'commissioning_date', 'pending_commissioning_comment',
)

COMMISSIONING_WAIT_DAYS = 21


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


def commissioning_readiness(action: HomeBiogasAction, *, today: date | None = None) -> dict:
    """Return the policy-derived commissioning state; never persist a stale countdown."""
    installed_on = action.installation_date if action.installation_status == HomeBiogasAction.INSTALLATION_INSTALLED else None
    if not installed_on:
        return {
            'ready_on': None, 'state': '', 'label': '',
            'days_until_ready': None, 'overdue_days': 0,
        }
    ready_on = installed_on + timedelta(days=COMMISSIONING_WAIT_DAYS)
    current = today or timezone.localdate()
    if action.commissioning_status == HomeBiogasAction.COMMISSIONING_COMMISSIONED:
        state = 'done'
        label = 'Commissioned'
        days_until = 0
        overdue_days = 0
    else:
        difference = (ready_on - current).days
        if difference > 0:
            state = 'waiting'
            label = 'Waiting period'
            days_until = difference
            overdue_days = 0
        elif difference == 0:
            state = 'due_today'
            label = 'Due today'
            days_until = 0
            overdue_days = 0
        else:
            state = 'delayed'
            label = 'Delayed'
            days_until = 0
            overdue_days = abs(difference)
    return {
        'ready_on': ready_on, 'state': state, 'label': label,
        'days_until_ready': days_until, 'overdue_days': overdue_days,
    }


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
            'farmer', 'source_requisition_batch',
            'source_requisition_batch__group_configuration',
            'source_signoff', 'updated_by',
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
    readiness = commissioning_readiness(action)
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
        'installation_status_label': (
            'Not installed' if action.installation_status == HomeBiogasAction.INSTALLATION_OPEN
            else 'Legacy closed' if action.installation_status == HomeBiogasAction.INSTALLATION_CLOSED
            else action.get_installation_status_display()
        ),
        'planned_installation_date': action.planned_installation_date.isoformat() if action.planned_installation_date else '',
        'planned_installation_date_display': _display_date(action.planned_installation_date),
        'installation_date': action.installation_date.isoformat() if action.installation_date else '',
        'installation_date_display': _display_date(action.installation_date),
        'installation_date_label': 'Actual installation date',
        'serial_number': action.serial_number,
        'readiness_status': action.readiness_status,
        'readiness_status_label': action.get_readiness_status_display() if action.readiness_status else '',
        'pending_installation_comment': action.pending_installation_comment,
        'installation_note': action.pending_installation_comment,
        'installation_report_status': action.installation_report_status,
        'installation_report_status_label': action.get_installation_report_status_display() if action.installation_report_status else '',
        'commissioning_status': action.commissioning_status,
        'commissioning_status_label': action.get_commissioning_status_display() if action.commissioning_status else '',
        'commissioning_date': action.commissioning_date.isoformat() if action.commissioning_date else '',
        'commissioning_date_display': _display_date(action.commissioning_date),
        'commissioning_date_label': 'Actual commissioning date',
        'pending_commissioning_comment': action.pending_commissioning_comment,
        'commissioning_ready_on': readiness['ready_on'].isoformat() if readiness['ready_on'] else '',
        'commissioning_ready_on_display': _display_date(readiness['ready_on']),
        'commissioning_state': readiness['state'],
        'commissioning_state_label': readiness['label'],
        'days_until_ready': readiness['days_until_ready'],
        'commissioning_overdue_days': readiness['overdue_days'],
        'revision': action.revision,
        'released_at': action.created_at.isoformat(),
        'updated_at': action.updated_at.isoformat(),
        'updated_by': _actor_label(action.updated_by),
        'detail_url': reverse('portal_hb_action_detail', kwargs={'farmer_id': farmer.id}),
        'invoice': ({
            'id': str(invoice.id), 'number': invoice.invoice_no,
            'date': _display_date(invoice.invoice_date),
            'batch_id': str(invoice.batch_id),
            'record_url': reverse('portal_invoice_screen_detail', kwargs={'invoice_id': invoice.id}),
            'preview_url': reverse('portal_preview_case_invoice', kwargs={
                'farmer_id': farmer.id, 'batch_id': invoice.batch_id,
            }),
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

    # Lock only the sign-off row. DocumentPhysicalSignoff has nullable foreign
    # keys for the mutually exclusive requisition/payment sources, so joining
    # either relation into SELECT FOR UPDATE makes PostgreSQL try to lock the
    # nullable side of an outer join (which PostgreSQL rejects).
    signoff = DocumentPhysicalSignoff.objects.select_for_update().get(pk=signoff.pk)
    if signoff.document_type != DocumentSignoffPolicy.DOCUMENT_REQUISITION:
        raise HomeBiogasActionError('Only an accepted requisition can release HomeBiogas work.')
    if signoff.status != DocumentPhysicalSignoff.STATUS_SIGNED_APPROVED:
        raise HomeBiogasActionError('The signed and stamped requisition has not been accepted.')
    # Lock the concrete requisition separately so the version cannot change
    # between validation and release, without introducing an outer join.
    batch = RequisitionBatch.objects.select_for_update().get(pk=signoff.requisition_batch_id)
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
                # Do not rely on model defaults for a business hand-off. An
                # accepted signed order always starts an actionable, open
                # installation and a not-yet-commissioned unit.
                'installation_status': HomeBiogasAction.INSTALLATION_OPEN,
                'commissioning_status': HomeBiogasAction.COMMISSIONING_NOT_COMMISSIONED,
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
                new_values={
                    'order_number': batch.order_number,
                    'requisition_version': batch.version,
                    'installation_status': HomeBiogasAction.INSTALLATION_OPEN,
                    'commissioning_status': HomeBiogasAction.COMMISSIONING_NOT_COMMISSIONED,
                },
            )
            # The farmer record is the one-way Master Data projection source.
            # Update it at the same hard-cutover hand-off, so the Sheet shows
            # Open without waiting for an HB user to make an unrelated edit.
            _sync_farmer(
                action,
                actor=actor,
                request_id=f'hb-release:{signoff.pk}:{farmer.pk}',
                required_capability='portal.documents.sign',
                deduplication_namespace='hb-release',
            )
        else:
            existing += 1
    return {'created': created, 'existing': existing, 'missing_farmer_ids': missing}


def _validate_installation(action: HomeBiogasAction, payload: dict, *, correction: bool = False) -> dict:
    if action.installation_status == HomeBiogasAction.INSTALLATION_CLOSED:
        raise HomeBiogasActionError('This legacy closed installation record is read-only.')
    target = _text(payload, 'installation_status', max_length=32)
    allowed_targets = {
        HomeBiogasAction.INSTALLATION_OPEN: {HomeBiogasAction.INSTALLATION_OPEN, HomeBiogasAction.INSTALLATION_INSTALLED},
        HomeBiogasAction.INSTALLATION_INSTALLED: {HomeBiogasAction.INSTALLATION_INSTALLED},
    }
    if not (correction and target == action.installation_status) and target not in allowed_targets.get(action.installation_status, set()):
        raise HomeBiogasActionError('That installation change is not available from the current status.')
    if (
        correction
        and action.commissioning_status == HomeBiogasAction.COMMISSIONING_COMMISSIONED
        and target != HomeBiogasAction.INSTALLATION_INSTALLED
    ):
        raise HomeBiogasActionError(
            'Installation must remain Installed because commissioning is already complete.'
        )
    readiness = _text(payload, 'readiness_status', max_length=24)
    comment = _text(payload, 'installation_note') or _text(payload, 'pending_installation_comment')
    planned_installation_date = _date_value(payload, 'planned_installation_date')
    installation_date = _date_value(payload, 'installation_date')
    serial = _text(payload, 'serial_number', max_length=128)
    # The staff form records this as a simple optional checkbox.  Preserve the
    # legacy API field for historical integrations, but never make it a gate
    # for recording an actual installation.
    if 'installation_report_submitted' in payload:
        submitted = str(payload.get('installation_report_submitted') or '').strip().lower()
        report = (
            HomeBiogasAction.REPORT_YES
            if submitted in {'1', 'true', 'yes', 'on'}
            else HomeBiogasAction.REPORT_NO
        )
    else:
        report = _text(payload, 'installation_report_status', max_length=24)

    if target == HomeBiogasAction.INSTALLATION_OPEN:
        if readiness and readiness not in dict(HomeBiogasAction.READINESS_CHOICES):
            raise HomeBiogasActionError('Choose a valid readiness status.')
        if readiness == HomeBiogasAction.READINESS_NOT_READY and not comment:
            raise HomeBiogasActionError('Add a short installation note for a known readiness blocker.')
        return {
            'installation_status': target,
            'planned_installation_date': planned_installation_date,
            'installation_date': None,
            'readiness_status': readiness, 'pending_installation_comment': comment,
            'serial_number': '', 'installation_report_status': '',
        }
    if not installation_date:
        raise HomeBiogasActionError('Choose the actual installation date.')
    if installation_date > timezone.localdate():
        raise HomeBiogasActionError('The actual installation date cannot be in the future.')
    if report and report not in dict(HomeBiogasAction.REPORT_CHOICES):
        raise HomeBiogasActionError('Choose a valid installation report status.')
    values = {
        'installation_status': target, 'planned_installation_date': None,
        'installation_date': installation_date,
        'readiness_status': '', 'pending_installation_comment': '',
        'serial_number': serial, 'installation_report_status': report,
    }
    # Completing installation is the only route into commissioning. Make that
    # state transition explicit instead of depending on an earlier default.
    # A correction to an already commissioned record deliberately preserves
    # its completed commissioning evidence.
    if action.installation_status != HomeBiogasAction.INSTALLATION_INSTALLED:
        values.update({
            'commissioning_status': HomeBiogasAction.COMMISSIONING_NOT_COMMISSIONED,
            'commissioning_date': None,
            'pending_commissioning_comment': '',
        })
    return values


def _validate_commissioning(action: HomeBiogasAction, payload: dict, *, correction: bool = False) -> tuple[dict, dict]:
    if action.installation_status != HomeBiogasAction.INSTALLATION_INSTALLED or not action.installation_date:
        raise HomeBiogasActionError('Complete installation before recording commissioning.')
    target = _text(payload, 'commissioning_status', max_length=24) or HomeBiogasAction.COMMISSIONING_COMMISSIONED
    if target != HomeBiogasAction.COMMISSIONING_COMMISSIONED:
        raise HomeBiogasActionError('Commissioning can only be marked commissioned from this screen.')
    if action.commissioning_status == HomeBiogasAction.COMMISSIONING_COMMISSIONED and not correction:
        raise HomeBiogasActionError('Commissioning is already complete. Use correction mode to amend it.')
    commissioned_on = _date_value(payload, 'commissioning_date')
    if not commissioned_on:
        raise HomeBiogasActionError('Choose the actual commissioning date.')
    if commissioned_on > timezone.localdate():
        raise HomeBiogasActionError('The actual commissioning date cannot be in the future.')
    ready_on = action.installation_date + timedelta(days=COMMISSIONING_WAIT_DAYS)
    early_by_days = max(0, (ready_on - commissioned_on).days)
    acknowledged = str(payload.get('early_commissioning_acknowledged') or '').strip().lower() in {'1', 'true', 'yes', 'on'}
    if early_by_days and not acknowledged:
        raise HomeBiogasActionError(
            f'This date is {early_by_days} day{"s" if early_by_days != 1 else ""} before the standard commissioning readiness date. Confirm the early commissioning to continue.'
        )
    values = {
        'commissioning_status': HomeBiogasAction.COMMISSIONING_COMMISSIONED,
        'commissioning_date': commissioned_on,
        'pending_commissioning_comment': '',
    }
    policy = {
        'commissioning_ready_on': ready_on.isoformat(),
        'early_commissioning_acknowledged': bool(early_by_days and acknowledged),
        'early_by_days': early_by_days,
    }
    return values, policy


def _sync_farmer(
    action: HomeBiogasAction,
    *,
    actor,
    request_id: str,
    required_capability: str = WRITE_CAPABILITY,
    deduplication_namespace: str = 'hb-action',
):
    farmer = JawabuFarmerMaster.objects.select_for_update().get(pk=action.farmer_id)
    labels = {
        HomeBiogasAction.INSTALLATION_OPEN: 'Open',
        HomeBiogasAction.INSTALLATION_INSTALLED: 'Installed',
        HomeBiogasAction.INSTALLATION_CLOSED: 'Closed',
    }
    farmer.installation_status = labels[action.installation_status]
    farmer.workflow_revision = int(farmer.workflow_revision or 0) + 1
    farmer.save(update_fields=['installation_status', 'workflow_revision', 'updated_at'])
    return reserve_farmer_publication(
        farmer, request_id=request_id, requested_by=actor,
        requested_by_label=_actor_label(actor), required_capability=required_capability,
        deduplication_namespace=deduplication_namespace,
    )


@transaction.atomic
def transition_action(action_id, *, payload: dict, actor, request_id: str, expected_revision: int):
    action = HomeBiogasAction.objects.select_for_update().select_related('farmer').get(pk=action_id)
    duplicate = action.events.filter(request_id=request_id).first() if request_id else None
    if duplicate:
        return action, [], True
    if int(expected_revision) != int(action.revision):
        raise HomeBiogasActionError('This record changed after you opened it. Refresh and try again.')
    workstream = _text(payload, 'workstream', max_length=24)
    if workstream not in {'installation', 'commissioning'}:
        raise HomeBiogasActionError('Refresh this screen before saving this HB action.')
    before = _snapshot(action)
    policy = {}
    if workstream == 'installation':
        values = _validate_installation(action, payload)
    else:
        values, policy = _validate_commissioning(action, payload)
    for key, value in values.items():
        setattr(action, key, value)
    action.revision += 1
    action.updated_by = actor
    action.save(update_fields=[*values.keys(), 'revision', 'updated_by', 'updated_at'])
    HomeBiogasActionEvent.objects.create(
        action=action, event_type=f'{workstream}.{"completed" if workstream == "commissioning" else "progressed"}', revision=action.revision,
        actor=actor, actor_label=_actor_label(actor), request_id=request_id,
        previous_values=before, new_values={**_snapshot(action), **policy},
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
    workstream = _text(payload, 'workstream', max_length=24)
    if workstream not in {'installation', 'commissioning'}:
        raise HomeBiogasActionError('Refresh this screen before saving this HB correction.')
    before = _snapshot(action)
    policy = {}
    if workstream == 'installation':
        corrected = _validate_installation(
            action,
            {**before, **payload, 'installation_status': payload.get('installation_status', action.installation_status)},
            correction=True,
        )
        corrected_installation_date = corrected.get('installation_date')
        if (
            action.commissioning_status == HomeBiogasAction.COMMISSIONING_COMMISSIONED
            and action.commissioning_date and corrected_installation_date
        ):
            ready_on = corrected_installation_date + timedelta(days=COMMISSIONING_WAIT_DAYS)
            early_by_days = max(0, (ready_on - action.commissioning_date).days)
            acknowledged = str(payload.get('early_commissioning_acknowledged') or '').strip().lower() in {'1', 'true', 'yes', 'on'}
            if early_by_days and not acknowledged:
                raise HomeBiogasActionError(
                    f'The corrected installation date makes commissioning {early_by_days} day{"s" if early_by_days != 1 else ""} earlier than the standard readiness date. Confirm this exception to continue.'
                )
            policy = {
                'commissioning_ready_on': ready_on.isoformat(),
                'early_commissioning_acknowledged': bool(early_by_days and acknowledged),
                'early_by_days': early_by_days,
            }
    else:
        corrected, policy = _validate_commissioning(action, {**before, **payload}, correction=True)
    for key, value in corrected.items():
        setattr(action, key, value)
    action.revision += 1
    action.updated_by = actor
    action.save(update_fields=[*corrected.keys(), 'revision', 'updated_by', 'updated_at'])
    HomeBiogasActionEvent.objects.create(
        action=action, event_type=f'{workstream}.corrected', revision=action.revision,
        actor=actor, actor_label=_actor_label(actor), request_id=request_id,
        previous_values=before, new_values={**_snapshot(action), **policy}, reason='',
    )
    operations = _sync_farmer(action, actor=actor, request_id=request_id)
    return action, operations, False
