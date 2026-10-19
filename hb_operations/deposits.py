"""Pre-visit HB deposit policy; deliberately independent of post-order actions."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import re

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Case, DecimalField, F, Q, Value, When
from django.db.models.functions import Cast, Coalesce, Replace, Trim
from django.utils import timezone

from core.models import JawabuFarmerMaster
from core.services.workflow_access import scope_workflow_queryset, workflow_access_decision

WORKFLOW = 'jawabu_portal'
VIEW_CAPABILITY = 'portal.hb_deposit.view'
WRITE_CAPABILITY = 'portal.hb_deposit.write'
REQUIRED_DEPOSIT = Decimal('5000.00')
SOURCE = 'hb_deposit'


class DepositError(ValueError):
    def __init__(self, message, code='invalid_deposit', status=400):
        super().__init__(message)
        self.code, self.status = code, status


def parse_deposit(value) -> Decimal:
    try:
        text = str(value).strip().replace(',', '')
        if not re.fullmatch(r'[0-9]+(?:\.[0-9]{1,2})?', text):
            raise InvalidOperation
        amount = Decimal(text)
        if not amount.is_finite() or amount < 0 or amount > Decimal('9999999999.99'):
            raise InvalidOperation
        if amount != amount.quantize(Decimal('.01')):
            raise InvalidOperation
        return amount.quantize(Decimal('.01'))
    except (InvalidOperation, ValueError, TypeError):
        raise DepositError('Enter a non-negative KES amount with at most two decimal places.') from None


def recorded_deposit(farmer) -> Decimal | None:
    value = farmer.deposit_paid_hbg
    if value is None:
        value = farmer.actual_receipts
    if value in (None, ''):
        return None
    try:
        return parse_deposit(value)
    except DepositError:
        return None


def deposit_state(farmer) -> dict:
    amount = recorded_deposit(farmer)
    shortfall = max(REQUIRED_DEPOSIT - (amount or Decimal('0')), Decimal('0'))
    visited = farmer.jbl_visit_date is not None
    held = not visited and shortfall > 0
    return {
        'recorded_amount': format(amount, '.2f') if amount is not None else None,
        'required_amount': '5000.00', 'shortfall': format(shortfall, '.2f'),
        'deposit_hold': held, 'deposit_sufficient': shortfall == 0,
        'visit_recorded': visited,
        'reason': f'Awaiting HB deposit: KES {shortfall:,.2f} outstanding.' if held else '',
    }


def visit_deposit_error(farmer) -> str:
    state = deposit_state(farmer)
    return state['reason'] if state['deposit_hold'] else ''


def deposit_editable(farmer) -> bool:
    return (
        not farmer.jbl_visit_date and farmer.status != 'inactive'
        and not farmer.order_number and not farmer.invoice_number
        and farmer.workflow_state in {'', 'jbl_visit', 'deferred'}
        and (farmer.workflow_state != 'deferred' or farmer.deferred_stage == 'jbl_visit')
    )


def scoped_deposits(user, access, capability=VIEW_CAPABILITY):
    if not user or not user.is_active:
        return JawabuFarmerMaster.objects.none()
    if access is None and not user.is_superuser:
        from core.services.telegram_identity import user_access
        access = user_access(user, WORKFLOW)
    return scope_workflow_queryset(
        JawabuFarmerMaster.objects.select_related('group_configuration', 'product', 'product_version__product').exclude(status='inactive').annotate(
            _deposit_product=Coalesce('product__code', 'product_version__product__code', 'payment_product'),
        ),
        user, WORKFLOW, capability, access=access,
        branch_field='branch', product_field='_deposit_product',
        group_field='group_configuration__group_id',
    )


def deposit_queryset(queryset):
    """Safe SQL counterpart of recorded_deposit for filtering before paging.

    Only simple canonical decimal text is cast; malformed legacy text is held.
    Never cast arbitrary customer-entered text on PostgreSQL.
    """
    money = DecimalField(max_digits=12, decimal_places=2)
    return queryset.annotate(_deposit_text=Replace(Trim('actual_receipts'), Value(','), Value(''))).annotate(_deposit_total=Case(
        When(deposit_paid_hbg__isnull=False, then=F('deposit_paid_hbg')),
        When(_deposit_text__regex=r'^0*[0-9]{1,10}(\.[0-9]{1,2})?$', then=Cast('_deposit_text', money)),
        default=Value(None), output_field=money,
    ))


def hb_owns_deposit(farmer) -> bool:
    return farmer.field_provenance.filter(field_name='deposit_paid_hbg', source=SOURCE).exists()


def require_deposit_access(farmer, actor, access, capability):
    # Services do not treat an absent access context as an authorization bypass.
    if not actor or not actor.is_active:
        raise PermissionDenied('An active Portal staff account is required.')
    if access is None and not actor.is_superuser:
        from core.services.telegram_identity import user_access
        access = user_access(actor, WORKFLOW)
    decision = workflow_access_decision(
        actor, WORKFLOW, capability, access=access, resource=farmer,
        group_configuration=farmer.group_configuration,
    )
    if not decision.allowed:
        raise PermissionDenied('This deposit action is outside your authorized Portal scope.')


@transaction.atomic
def update_deposit(farmer, *, amount, reason, expected_revision, request_id, actor, access=None):
    from core.services.jawabu_case360 import record_pipeline_event
    from core.services.jawabu_customer_quality import record_field_provenance
    from core.services.portal_publication import reserve_farmer_publication

    farmer = JawabuFarmerMaster.objects.select_for_update(of=('self',)).select_related('group_configuration', 'product', 'product_version__product').get(pk=farmer.pk)
    require_deposit_access(farmer, actor, access, WRITE_CAPABILITY)
    total = parse_deposit(amount)
    note = str(reason or '').strip()
    key = str(request_id or '').strip()
    if not key or len(key) > 128:
        raise DepositError('A valid secure submission key is required.', 'request_key_required', 428)
    payload = {'amount': format(total, '.2f'), 'reason': note}
    if len(note) > 2000:
        raise DepositError('Keep the deposit explanation within 2,000 characters.')
    previous_event = farmer.pipeline_events.filter(request_id=key).first()
    if previous_event:
        if previous_event.action == 'hb_deposit_updated' and previous_event.metadata.get('request_payload') == payload:
            return farmer
        raise DepositError('This request key was used for another action. Refresh and retry.', 'idempotency_conflict', 409)
    if int(farmer.workflow_revision or 1) != int(expected_revision or 0):
        raise DepositError('This case changed. Reload before saving the deposit.', 'workflow_revision_conflict', 409)
    if not deposit_editable(farmer):
        raise DepositError('Only cases awaiting their first JBL visit can be edited. Deposit history is read-only.', 'deposit_locked', 409)
    before = recorded_deposit(farmer)
    if before is not None and total < before and not note:
        raise DepositError('Explain why the recorded total is being reduced.', 'reason_required')
    if before == total:
        raise DepositError('The recorded total has not changed.', 'no_change')
    old_state = deposit_state(farmer)
    revision = int(farmer.workflow_revision or 1)
    old_values = {'deposit_paid_hbg': old_state['recorded_amount'], 'actual_receipts': farmer.actual_receipts}
    farmer.deposit_paid_hbg = total
    farmer.actual_receipts = format(total, '.2f')
    farmer.actual_receipts_currency = 'KES'
    farmer.workflow_revision = revision + 1
    farmer.save(update_fields=['deposit_paid_hbg', 'actual_receipts', 'actual_receipts_currency', 'workflow_revision', 'updated_at'])
    actor_label = actor.get_full_name() or actor.get_username()
    new_values = {'deposit_paid_hbg': format(total, '.2f'), 'actual_receipts': farmer.actual_receipts}
    record_field_provenance(
        farmer, old_values=old_values, new_values=new_values, source=SOURCE,
        source_reference=key, actor=actor_label,
    )
    record_pipeline_event(
        farmer, action='hb_deposit_updated', stage_key='intake', source=SOURCE,
        actor=actor_label, actor_user=actor, request_id=key, reason=note,
        old_values=old_values, new_values=new_values,
        revision_before=revision, revision_after=revision + 1,
        metadata={'request_payload': payload, 'deposit_before': old_state, 'deposit_after': deposit_state(farmer)},
    )
    reserve_farmer_publication(farmer, request_id=f'hb-deposit:{key}', requested_by=actor, requested_by_label=actor_label)
    return farmer


def serialize_deposit(farmer, *, actor, access, history=False, write_allowed=None):
    from core.services.jawabu_case_reference import display_case_reference
    can_edit = False
    if write_allowed is None:
        try:
            require_deposit_access(farmer, actor, access, WRITE_CAPABILITY)
            can_edit = deposit_editable(farmer)
        except PermissionDenied:
            pass
    else:
        can_edit = bool(write_allowed) and deposit_editable(farmer)
    result = {
        'id': str(farmer.pk), 'customer_name': farmer.customer_name,
        'case_reference': display_case_reference(farmer), 'national_id': farmer.national_id,
        'primary_phone': farmer.primary_phone, 'branch': farmer.branch, 'source': farmer.source,
        'workflow_revision': int(farmer.workflow_revision or 1), 'status': farmer.status,
        'can_edit': can_edit, **deposit_state(farmer),
        'detail_url': f'/portal/s/hb-actions/{farmer.pk}/?workstream=deposits',
    }
    if history:
        result['activity'] = [{
            'action': event.action, 'actor': event.actor or 'FarmUp / system',
            'occurred_at': timezone.localtime(event.occurred_at).strftime('%d-%m-%Y %H:%M EAT'),
            'old_values': event.old_values, 'new_values': event.new_values,
            'reason': event.reason, 'metadata': event.metadata,
        } for event in farmer.pipeline_events.filter(
            Q(action__in=['hb_deposit_updated', 'hb_deposit_import_observed', 'hb_deposit_review_reconciled',
                         'hb_deposit_review_reconciliation_reversed', 'office_lead_saved_on_deposit_hold'])
            | Q(source='farmup', action__in=['application_imported', 'application_updated'])
        ).order_by('-occurred_at', '-pk')]
    return result


@transaction.atomic
def record_office_deposit_hold(farmer, *, held_intake, payload, request_id, actor, actor_label='') -> bool:
    """Retain office intake only, never a visit, under the shared case lock."""
    from core.services.jawabu_case360 import record_pipeline_event
    from core.services.portal_publication import reserve_farmer_publication

    farmer = JawabuFarmerMaster.objects.select_for_update().get(pk=farmer.pk)
    event = farmer.pipeline_events.filter(request_id=request_id).first()
    held_event = event and event.action == 'office_lead_saved_on_deposit_hold'
    if held_event and event.metadata.get('request_payload') != payload:
        raise DepositError('This submission key was already used with different lead details.', 'idempotency_conflict', 409)
    if not held_intake and not held_event:
        return False
    if event and not held_event:
        raise DepositError('This submission key was already used for a different case action.', 'idempotency_conflict', 409)
    if not held_event:
        record_pipeline_event(
            farmer, action='office_lead_saved_on_deposit_hold', stage_key='intake',
            actor=actor_label, actor_user=actor, request_id=request_id,
            new_values={'deposit_paid_hbg': payload['deposit']},
            metadata={'request_payload': payload},
            reason='Intake saved; first JBL visit awaits the HB deposit.',
        )
        reserve_farmer_publication(farmer, request_id=f'office-deposit-hold:{request_id}', requested_by=actor)
    return True
