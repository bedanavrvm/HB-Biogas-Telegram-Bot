"""Audited, capability-gated corrections for non-governed Portal case fields."""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction

from core.models import JawabuFarmerMaster
from core.services.identifiers import normalize_kenyan_phone, normalize_national_id
from core.services.jawabu_case360 import record_pipeline_event
from core.services.jawabu_customer_quality import record_field_provenance
from core.services.jawabu_validation import parse_business_date, parse_money
from core.services.workflow_transitions import next_workflow_revision


CASE_CORRECTION_FIELDS = {
    'customer_name': {'label': 'Customer name', 'section': 'identity', 'type': 'text'},
    'national_id': {'label': 'National ID', 'section': 'identity', 'type': 'text'},
    'primary_phone': {'label': 'Primary phone', 'section': 'identity', 'type': 'tel'},
    'secondary_phone': {'label': 'Secondary phone', 'section': 'identity', 'type': 'tel'},
    'customer_no': {'label': 'Customer number', 'section': 'identity', 'type': 'text'},
    'lead_name': {'label': 'FarmUp lead name', 'section': 'identity', 'type': 'text'},
    'lead_national_id': {'label': 'FarmUp lead national ID', 'section': 'identity', 'type': 'text'},
    'lead_primary_phone': {'label': 'FarmUp lead phone', 'section': 'identity', 'type': 'tel'},
    'hbg_visit_date': {'label': 'HB visit date', 'section': 'intake', 'type': 'date'},
    'village': {'label': 'Village', 'section': 'intake', 'type': 'text'},
    'landmark': {'label': 'Landmark', 'section': 'intake', 'type': 'text'},
    'lead_source': {'label': 'Lead source', 'section': 'intake', 'type': 'text'},
    'hb_sales_person': {'label': 'HB salesperson', 'section': 'intake', 'type': 'text'},
    'deposit_paid_hbg': {'label': 'Deposit paid to HB', 'section': 'intake', 'type': 'money'},
}


def _display_value(value) -> str:
    if value is None:
        return ''
    if hasattr(value, 'strftime'):
        return value.strftime('%d-%m-%Y')
    if isinstance(value, Decimal):
        return format(value, 'f').rstrip('0').rstrip('.')
    return str(value)


def correction_payload(farmer: JawabuFarmerMaster) -> dict:
    return {
        'workflow_revision': int(farmer.workflow_revision or 1),
        'fields': [
            {**definition, 'key': key, 'value': _display_value(getattr(farmer, key, ''))}
            for key, definition in CASE_CORRECTION_FIELDS.items()
        ],
    }


def _clean_value(key: str, raw_value):
    if key in {'national_id', 'lead_national_id'}:
        return normalize_national_id(raw_value)
    if key in {'primary_phone', 'secondary_phone', 'lead_primary_phone'}:
        return normalize_kenyan_phone(raw_value) if str(raw_value or '').strip() else ''
    if key == 'hbg_visit_date':
        parsed = parse_business_date(raw_value)
        if str(raw_value or '').strip() and parsed is None:
            raise ValueError('HB visit date must use DD-MM-YYYY.')
        return parsed
    if key == 'deposit_paid_hbg':
        parsed = parse_money(raw_value)
        if str(raw_value or '').strip() and parsed is None:
            raise ValueError('Deposit paid to HB must be a valid non-negative number.')
        return parsed
    return ' '.join(str(raw_value or '').split())


@transaction.atomic
def correct_case_fields(
    farmer: JawabuFarmerMaster,
    *,
    values: dict,
    expected_revision: int,
    reason: str,
    request_id: str,
    actor,
) -> JawabuFarmerMaster:
    farmer = JawabuFarmerMaster.objects.select_for_update().get(pk=farmer.pk)
    reason = str(reason or '').strip()
    supplied = {key: value for key, value in (values or {}).items() if key in CASE_CORRECTION_FIELDS}
    existing = farmer.pipeline_events.filter(request_id=request_id).first() if request_id else None
    if existing:
        same_values = all(
            _display_value(getattr(farmer, key)) == _display_value(_clean_value(key, value))
            for key, value in supplied.items()
        )
        if existing.action == 'case_fields_corrected' and existing.reason == reason and same_values:
            return farmer
        raise ValueError('This request key was already used for a different case correction. Refresh and try again.')
    if int(farmer.workflow_revision or 1) != int(expected_revision or 0):
        raise ValueError('This case changed after you opened it. Reload Case History and review the latest values.')
    if not reason:
        raise ValueError('Enter a correction reason for the audit timeline.')
    if not supplied:
        raise ValueError('No editable case fields were supplied.')

    old_values = {}
    new_values = {}
    update_fields = []
    for key, raw_value in supplied.items():
        cleaned = _clean_value(key, raw_value)
        previous = getattr(farmer, key)
        if _display_value(previous) == _display_value(cleaned):
            continue
        old_values[key] = _display_value(previous)
        new_values[key] = _display_value(cleaned)
        setattr(farmer, key, cleaned)
        update_fields.append(key)
    if not update_fields:
        raise ValueError('No field values changed.')

    revision_before, revision_after = next_workflow_revision(farmer)
    farmer.workflow_revision = revision_after
    farmer.save(update_fields=[*update_fields, 'workflow_revision', 'updated_at'])
    actor_label = actor.get_full_name() or actor.get_username()
    record_field_provenance(
        farmer,
        old_values=old_values,
        new_values=new_values,
        source='admin_correction',
        source_reference=f'portal-case:{farmer.pk}',
        actor=actor_label,
    )
    record_pipeline_event(
        farmer,
        action='case_fields_corrected',
        stage_key='case_history',
        actor=actor_label,
        actor_user=actor,
        source='admin_correction',
        request_id=request_id,
        old_values=old_values,
        new_values=new_values,
        reason=reason,
        revision_before=revision_before,
        revision_after=revision_after,
        metadata={'corrected_fields': sorted(new_values)},
    )
    from core.services.portal_publication import reserve_farmer_publication

    reserve_farmer_publication(
        farmer,
        request_id=f'case-correction:{request_id or farmer.pk}:{revision_after}',
        requested_by=actor,
        requested_by_label=actor_label,
    )
    return farmer
