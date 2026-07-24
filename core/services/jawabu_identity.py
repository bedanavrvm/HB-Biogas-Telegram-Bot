"""Customer identity and repeat-unit rules for the Jawabu master pipeline."""
from __future__ import annotations

import re

from django.db import transaction
from django.db.models import Q, Max

from core.models import JawabuCustomer, JawabuFarmerMaster, JawabuPipelineEvent


class JawabuIdentityConflict(ValueError):
    pass


def normalize_identifier(value) -> str:
    return re.sub(r'\D', '', str(value or '').strip())


def normalize_primary_phone(value) -> str:
    digits = normalize_identifier(value)
    if digits.startswith('0') and len(digits) == 10:
        digits = f'254{digits[1:]}'
    elif len(digits) == 9 and digits.startswith('7'):
        digits = f'254{digits}'
    return digits


def _identity_query(national_id: str, primary_phone: str, customer_no: str = '') -> Q:
    query = Q()
    if national_id:
        query |= Q(national_id=national_id)
    if primary_phone:
        query |= Q(primary_phone=primary_phone)
    if customer_no:
        query |= Q(customer_no=customer_no)
    return query


@transaction.atomic
def resolve_application_identity(cleaned: dict, *, action: str = 'update_existing'):
    """Return (customer, unit_number, existing_application) without guessing duplicates."""
    national_id = normalize_identifier(cleaned.get('national_id'))
    primary_phone = normalize_primary_phone(cleaned.get('primary_phone'))
    customer_no = normalize_identifier(cleaned.get('customer_no'))
    query = _identity_query(national_id, primary_phone, customer_no)
    matches = list(JawabuCustomer.objects.select_for_update().filter(query)) if query.children else []
    customer_ids = {item.id for item in matches}
    if len(customer_ids) > 1:
        raise JawabuIdentityConflict(
            'These identifiers match multiple historical customers. An administrator must resolve the legacy duplicate before this row can be committed.'
        )

    customer = matches[0] if matches else None
    if customer:
        conflicts = []
        for field, value in (('National ID', national_id), ('Primary Phone', primary_phone), ('Customer No', customer_no)):
            attr = {'National ID': 'national_id', 'Primary Phone': 'primary_phone', 'Customer No': 'customer_no'}[field]
            existing = getattr(customer, attr)
            if value and existing and value != existing:
                conflicts.append(field)
        if conflicts:
            raise JawabuIdentityConflict(f"Existing customer has different {', '.join(conflicts)}.")
    else:
        customer = JawabuCustomer.objects.create(
            national_id=national_id,
            primary_phone=primary_phone,
            customer_no=customer_no,
            identity_enforced=True,
        )

    applications = JawabuFarmerMaster.objects.select_for_update().filter(customer=customer)
    if action == 'create_additional_unit':
        unit_number = (applications.aggregate(value=Max('unit_number'))['value'] or 0) + 1
        return customer, unit_number, None

    existing = applications.order_by('-updated_at').first()
    return customer, existing.unit_number if existing else 1, existing


@transaction.atomic
def set_customer_number(farmer: JawabuFarmerMaster, customer_no: str) -> None:
    customer_no = normalize_identifier(customer_no)
    if not customer_no:
        return
    conflict = (
        JawabuCustomer.objects.select_for_update()
        .filter(customer_no=customer_no)
        .exclude(pk=farmer.customer_id)
        .exists()
    ) or (
        JawabuFarmerMaster.objects.select_for_update()
        .filter(customer_no=customer_no)
        .exclude(customer_id=farmer.customer_id)
        .exclude(pk=farmer.pk)
        .exists()
    )
    if conflict:
        raise JawabuIdentityConflict('CUSTOMER NO already belongs to a different customer.')
    if farmer.customer_id:
        customer = JawabuCustomer.objects.select_for_update().get(pk=farmer.customer_id)
        customer.customer_no = customer_no
        customer.save(update_fields=['customer_no', 'updated_at'])


def record_additional_unit(farmer: JawabuFarmerMaster, actor: str = '') -> None:
    JawabuPipelineEvent.objects.create(
        farmer=farmer,
        action='additional_unit_created',
        actor=actor,
        metadata={'customer_id': str(farmer.customer_id), 'unit_number': farmer.unit_number},
    )


def restart_expired_reappraisal(farmer: JawabuFarmerMaster, *, fresh_sign_date: str, actor: str = '') -> bool:
    from core.services.jawabu_pipeline import is_reappraisal_required

    if not fresh_sign_date or not is_reappraisal_required(farmer):
        return False
    snapshot = {
        'deferred_at': farmer.deferred_at.isoformat() if farmer.deferred_at else None,
        'deferred_stage': farmer.deferred_stage,
        'deferred_until': farmer.deferred_until.isoformat() if farmer.deferred_until else None,
        'jbl_visit_date': farmer.jbl_visit_date.isoformat() if farmer.jbl_visit_date else None,
        'jbl_visit_status': farmer.jbl_visit_status,
        'credit_decision': farmer.credit_decision,
        'final_decision': farmer.final_decision,
    }
    if farmer.order_number or farmer.invoice_number:
        raise JawabuIdentityConflict('Expired deferral has order or invoice data and requires administrator review before restart.')
    for field, value in {
        'jbl_visit_date': None, 'jbl_officer': '', 'jbl_visit_status': '', 'jbl_visit_comment': '',
        'credit_decision': '', 'credit_decided_by': '', 'credit_decided_at': None,
        'final_decision': '', 'final_decision_comment': '', 'final_decided_by': '', 'final_decided_at': None,
        'deferred_at': None, 'deferred_stage': '', 'deferred_until': None,
    }.items():
        setattr(farmer, field, value)
    JawabuPipelineEvent.objects.create(
        farmer=farmer, action='reappraisal_restarted', actor=actor, metadata={'previous_state': snapshot},
    )
    return True
