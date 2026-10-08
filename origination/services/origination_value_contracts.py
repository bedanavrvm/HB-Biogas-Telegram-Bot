"""Versioned field meanings and one resolution path for an Origination packet.

No catalogue, clock or customer lookup is permitted during frozen resolution.
Bindings are named projections, never administrator-supplied expressions.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any

VERSION = 2
PERSON_LINKS_KEY = '_person_role_bindings'
SCOPES = {'application', 'document'}
SOURCES = {'entered', 'calculated', 'workflow'}
SUBJECTS = {
    'application', 'applicant', 'spouse', 'next_of_kin', 'referee',
    'guarantor_1', 'guarantor_2', 'supplier', 'asset_owner', 'grantor',
    'grantor_spouse', 'payer', 'seller', 'proposed_owner', 'vehicle',
    'business', 'household', 'employment', 'loan', 'document',
}
QUOTE_BINDINGS = {
    'contract_currency': ('currency',),
    'contract_interest_rate_percent': ('terms', 'interest_rate'),
    'contract_interest_method': ('terms', 'interest_method'),
    'contract_interest_rate_period': ('terms', 'interest_rate_period'),
    'contract_repayment_frequency': ('terms', 'repayment_frequency'),
    'repayment_tenor_unit': ('inputs', 'tenor_unit'),
    'installment_count': ('installment_count',),
    'installment_amount': ('installment_amount',),
    'final_installment_amount': ('final_installment_amount',),
    'financed_principal_amount': ('financed_principal',),
    'total_interest_amount': ('interest',),
    'total_repayment_amount': ('total_repayment',),
    'financed_fee_total': ('financed_fees',),
    'upfront_fee_total': ('upfront_fees',),
    'loan_fees': ('fees',),
}
SYSTEM_KEYS = {
    'reference_number', 'branch_code', 'loan_officer_name', 'application_date',
    'product_code', 'product_name', 'loan_product', 'loan_product_other',
    'borrower_full_name',
    'bro_1_name', 'repayment_period', 'interest_rate', 'repayment_frequency',
    'daily_weekly_repayment_amount',
}
WORKFLOW_BINDINGS = {
    'approval_amount': 'approved_amount', 'amount_advanced': 'disbursed_amount',
    'acknowledgement_amount': 'received_amount',
    'home_visit_completed_date': 'visit_date',
}
TOTAL_KEYS = {
    'business_total_income', 'business_total_expenses', 'business_net_surplus',
    'household_total_income', 'household_total_expenses', 'household_net_surplus',
    'secured_assets_total',
}
# Paper labels do not establish these meanings. Legacy schemas are untouched;
# an opted-in draft must explicitly resolve them before publication.
UNRESOLVED_KEYS = {'enterprise_net_income', 'household_net_income', 'supplier_code',
                   'applicant_next_of_kin', 'applicant_next_of_kin_id', 'applicant_next_of_kin_phone'}
BINDINGS = (
    {'quote.' + key for key in QUOTE_BINDINGS}
    | {'system.' + key for key in SYSTEM_KEYS}
    | {'workflow.' + key for key in WORKFLOW_BINDINGS.values()}
    | {'total.' + key for key in TOTAL_KEYS}
)


class ValueContractError(ValueError):
    def __init__(self, message: str, *, errors: dict | None = None):
        super().__init__(message)
        self.errors = errors or {}


def request_fingerprint(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str).encode()).hexdigest()


def enabled(schema: Any) -> bool:
    return isinstance(schema, dict) and schema.get('value_contract_version') == VERSION


def validate_contract(value: Any, *, source_type: str = '') -> dict:
    """Validate the deliberately small, non-executable semantic contract."""
    if value in (None, {}):
        return {}
    if not isinstance(value, dict):
        raise ValueContractError('Field meaning must be an object.')
    allowed = {'version', 'definition', 'subject', 'scope', 'source', 'unit', 'period', 'binding'}
    if set(value) - allowed:
        raise ValueContractError('Field meaning contains unsupported settings.')
    result = deepcopy(value)
    if result.get('version') != VERSION:
        raise ValueContractError('Choose a supported field-meaning version.')
    for key in ('definition', 'subject', 'scope', 'source', 'unit', 'period', 'binding'):
        if not isinstance(result.get(key, ''), str):
            raise ValueContractError('Field meaning settings must be text.')
        result[key] = result.get(key, '').strip()
    if not result['definition'] or len(result['definition']) > 500:
        raise ValueContractError('Describe what this field represents in 1–500 characters.')
    if result['subject'] not in SUBJECTS or result['scope'] not in SCOPES or result['source'] not in SOURCES:
        raise ValueContractError('Choose a supported subject, ownership and value source.')
    if len(result['unit']) > 80 or len(result['period']) > 80:
        raise ValueContractError('Units and reporting periods must be concise.')
    binding = result['binding']
    if result['source'] == 'entered':
        if binding or source_type == 'system':
            raise ValueContractError('Entered fields cannot use a generated-value binding.')
    else:
        expected = 'workflow.' if result['source'] == 'workflow' else ('quote.', 'system.', 'total.')
        if binding not in BINDINGS or not binding.startswith(expected):
            raise ValueContractError('Choose a reviewed calculation or workflow value.')
        if source_type and source_type != 'system':
            raise ValueContractError('Generated fields must use the system value source.')
    return result


def reviewed_contract(field: dict) -> dict:
    """Reviewed defaults for existing projections; entered fields keep their keys."""
    key = str(field.get('key') or '')
    if key in UNRESOLVED_KEYS:
        return {}
    source_type = field.get('source_type') or field.get('source') or 'user_input'
    contract = {
        'version': VERSION, 'definition': field.get('help_text') or field.get('label') or key,
        'subject': 'application', 'scope': 'application', 'source': 'entered',
        'unit': 'contract currency' if field.get('type') == 'money' else '',
        'period': '', 'binding': '',
    }
    if key in WORKFLOW_BINDINGS:
        contract.update(source='workflow', binding='workflow.' + WORKFLOW_BINDINGS[key])
    elif source_type == 'system':
        if key in QUOTE_BINDINGS:
            contract.update(source='calculated', binding='quote.' + key)
        elif key in SYSTEM_KEYS:
            contract.update(source='calculated', binding='system.' + key)
        elif key in TOTAL_KEYS:
            contract.update(source='calculated', binding='total.' + key)
        else:
            return {}
    # These are exact reviewed prefixes, not a label-based merge policy.
    for subject in ('applicant', 'spouse', 'next_of_kin', 'referee', 'guarantor_1', 'guarantor_2', 'supplier',
                    'business', 'household', 'employment', 'vehicle', 'grantor_spouse', 'grantor', 'asset_owner', 'seller', 'proposed_owner'):
        if key.startswith(subject + '_'):
            contract['subject'] = subject
            break
    if key in {'loan_amount', 'approval_amount', 'amount_advanced', 'acknowledgement_amount'}:
        contract['subject'] = 'loan'
    if key == 'borrower_full_name':
        contract['subject'] = 'applicant'
    if key == 'loan_amount':
        contract['definition'] = 'Requested facility amount used for the proposed product quote; not proof of approval or receipt.'
    return validate_contract(contract, source_type='system' if contract['source'] != 'entered' else source_type)


def field_contract(field: dict) -> dict:
    return validate_contract(field.get('value_contract'), source_type=field.get('source_type') or field.get('source') or '')


def upgrade_schema(schema: dict) -> dict:
    """Explicit draft-only opt-in; callers retain publication/authorization checks."""
    result = deepcopy(schema)
    result['value_contract_version'] = VERSION
    for field in [*result.get('fields', []), *result.get('system_fields', [])]:
        if isinstance(field, dict) and not field.get('value_contract'):
            field['value_contract'] = reviewed_contract(field)
            if field['value_contract'].get('source') in {'workflow', 'calculated'}:
                field['source_type'] = 'system'
    return result


def _fields(schema: dict) -> list[dict]:
    return [field for field in schema.get('fields', []) if isinstance(field, dict) and field.get('key')]


def build_packet_contract(primary_schema: dict, documents: list[dict]) -> dict:
    """Compile the selected snapshot schemas, rejecting semantic conflicts."""
    if not enabled(primary_schema):
        if any(enabled(document['schema']) for document in documents):
            raise ValueContractError('Choose documents with the same shared-value setup.')
        return {'version': 1, 'fields': {}, 'documents': {}}
    shared, local, errors, ownership = {}, {}, {}, {}
    for document in [{'key': 'primary', 'schema': primary_schema}, *documents]:
        schema, document_key = document['schema'], str(document['key'])
        if not enabled(schema):
            errors[document_key] = 'Choose a document with compatible reviewed fields.'
            continue
        local.setdefault(document_key, {})
        for field in _fields(schema):
            key = str(field['key'])
            try:
                meaning = field_contract(field)
                if not meaning:
                    raise ValueContractError('Review this field’s meaning and value source.')
                if meaning['scope'] == 'document' and document_key == 'primary':
                    raise ValueContractError('Main application inputs must use shared application ownership.')
                if key in ownership and ownership[key] != meaning['scope']:
                    raise ValueContractError('Use a distinct field for document-only information.')
                ownership[key] = meaning['scope']
                item = {**deepcopy(field), 'value_contract': meaning}
                destination = shared if meaning['scope'] == 'application' else local[document_key]
                previous = destination.get(key)
                if previous:
                    previous_meaning = {k: v for k, v in previous['value_contract'].items() if k != 'definition'}
                    current_meaning = {k: v for k, v in meaning.items() if k != 'definition'}
                    if previous.get('type') != item.get('type') or previous_meaning != current_meaning:
                        raise ValueContractError('These documents use this field for different information.')
                    previous_structure, structure = previous.get('structure') or {}, item.get('structure') or {}
                    if ({k: v for k, v in previous_structure.items() if k not in {'min_items', 'max_items'}} !=
                            {k: v for k, v in structure.items() if k not in {'min_items', 'max_items'}}
                            or (previous.get('options') or []) != (item.get('options') or [])):
                        raise ValueContractError('These documents use incompatible choices or repeating rows.')
                    if item.get('type') == 'repeating_group':
                        maxima = [int(value['max_items']) for value in (previous_structure, structure) if value.get('max_items')]
                        minimum = max(int(value.get('min_items') or 0) for value in (previous_structure, structure))
                        maximum = min(maxima) if maxima else 0
                        if maximum and minimum > maximum:
                            raise ValueContractError('These documents need incompatible numbers of rows.')
                        previous['structure'] = {**previous_structure, 'min_items': minimum, 'max_items': maximum}
                    previous['required'] = bool(previous.get('required') or item.get('required'))
                else:
                    destination[key] = item
            except ValueContractError as exc:
                errors[f'{document_key}.{key}'] = str(exc)
    if errors:
        raise ValueContractError('Review the highlighted document fields.', errors=errors)
    return {'version': VERSION, 'fields': shared, 'documents': local}


def schema_with_mapped_values(schema: dict, configuration: dict, *, captured_system: list | None = None) -> dict:
    """Compile exact layout dependencies and visible repeating-row capacities."""
    result = deepcopy(schema)
    known = {field['key']: field for field in _fields(result)}
    captured = {field['key']: field for field in [*(captured_system or []), *schema.get('system_fields', [])] if field.get('key')}
    overlays = (configuration.get('field_overlay_manifest') or {}).get('fields') or {}
    for spec in overlays.values():
        key = spec.get('context_key') if isinstance(spec, dict) else None
        if not key:
            continue
        if key not in known:
            item = deepcopy(captured.get(key) or {'key': key, 'label': key.replace('_', ' ').title(), 'type': 'text'})
            if 'structure' not in item and item.get('structure_schema'):
                item['structure'] = deepcopy(item['structure_schema'])
            if 'options' not in item and item.get('choice_options'):
                item['options'] = deepcopy(item['choice_options'])
            item['source_type'] = 'system'
            if not item.get('value_contract'):
                item['value_contract'] = reviewed_contract(item)
            result.setdefault('fields', []).append(item)
            known[key] = item
        item = known[key]
        if item.get('type') == 'repeating_group' and spec.get('render_as') == 'repeating_table':
            try:
                rows = int(spec['rows']) if spec.get('rows') not in (None, '') else 1
            except (TypeError, ValueError) as exc:
                raise ValueContractError('Review the number of document table rows.') from exc
            structure = item.setdefault('structure', {})
            if rows < 1 or rows < int(structure.get('min_items') or 0):
                raise ValueContractError('This document does not have enough rows for the required entries.')
            structure['max_items'] = min(rows, int(structure.get('max_items') or rows))
    return result


def packet_contract(application: Any) -> dict:
    def mapped_schema(schema: dict, configuration: dict) -> dict:
        return schema_with_mapped_values(schema, configuration,
            captured_system=(application.schema_snapshot or {}).get('system_fields', []))

    documents = [
        {'key': document.document_key, 'schema': mapped_schema(document.schema_snapshot,
            (document.template_snapshot or {}).get('configuration') or {})}
        for document in application.packet_documents.all()
        if document.selected and document.document_role != 'primary'
    ]
    return build_packet_contract(mapped_schema(application.schema_snapshot,
        application.template_configuration_snapshot or {}), documents)


def application_input_schema(application: Any) -> dict:
    """One input for each shared packet field; generated values are not inputs."""
    schema = deepcopy(application.schema_snapshot)
    if not enabled(schema):
        return schema
    contract = packet_contract(application)
    schema['fields'] = [deepcopy(field) for field in contract['fields'].values()
                        if field['value_contract']['source'] == 'entered']
    sections = schema.setdefault('sections', [])
    known = {section['key'] for section in sections}
    for field in schema['fields']:
        section = field.get('section_key') or 'document_details'
        field['section_key'] = section
        if section not in known:
            sections.append({'key': section, 'label': 'Document details'})
            known.add(section)
    return schema


def normalize_changes(contract: dict, payload: Any, current: dict, *, document_key: str = '') -> tuple[dict, dict]:
    """Classify a partial save; generated/unknown keys never become entered facts."""
    if not isinstance(payload, dict):
        raise ValueContractError('Enter field values as an object.')
    fields = contract['fields']
    locals_ = contract['documents'].get(document_key, {}) if document_key else {}
    shared, local, errors = deepcopy(current), {}, {}
    for key, value in payload.items():
        if key == PERSON_LINKS_KEY and not document_key:
            shared[key] = deepcopy(value)
            continue
        field = fields.get(key) or locals_.get(key)
        if not field:
            errors[key] = 'This field is not part of the selected documents.'
            continue
        if field['value_contract']['source'] != 'entered':
            errors[key] = 'This value is supplied automatically and cannot be edited.'
            continue
        (shared if key in fields else local)[key] = deepcopy(value)
    if errors:
        raise ValueContractError('Correct the highlighted fields.', errors=errors)
    shared = apply_person_links(contract, shared, posted=payload, previous=current)
    return shared, local


def person_fields(contract: dict) -> dict:
    """Identity reuse is explicit and role-specific, never a name/phone match."""
    roles = {}
    suffixes = {'_name': 'name', '_full_name': 'name', '_id_number': 'national_id',
                '_national_id': 'national_id', '_phone': 'phone', '_phone_number': 'phone'}
    for key, field in contract['fields'].items():
        meaning = field['value_contract']
        if meaning['source'] != 'entered':
            continue
        subject = meaning['subject']
        for suffix, kind in sorted(suffixes.items(), key=lambda item: -len(item[0])):
            if key.endswith(suffix):
                roles.setdefault(subject, {})[kind] = key
                break
    return roles


def apply_person_links(contract: dict, values: dict, *, posted: dict, previous: dict) -> dict:
    links = values.get(PERSON_LINKS_KEY, {})
    if not isinstance(links, dict) or any(target not in {'guarantor_1', 'guarantor_2'} or source not in {'spouse', 'next_of_kin', 'referee'} for target, source in links.items()):
        raise ValueContractError('Choose a supported person for each guarantor.', errors={PERSON_LINKS_KEY: 'Choose spouse, next of kin or referee.'})
    roles = person_fields(contract)
    result = deepcopy(values)
    for target, source in links.items():
        if set(roles.get(target, {})) != {'name', 'national_id', 'phone'} or set(roles.get(source, {})) != {'name', 'national_id', 'phone'}:
            raise ValueContractError('This document needs name, ID and phone fields for both roles before linking them.')
        for kind, key in roles[target].items():
            if (previous.get(PERSON_LINKS_KEY, {}).get(target) == source and key in posted
                    and posted[key] != previous.get(key)):
                raise ValueContractError('Edit this person in their original section, or unlink them first.', errors={key: 'This value is linked to ' + source.replace('_', ' ') + '.'})
            result[key] = deepcopy(result.get(roles[source][kind], ''))
    if links or PERSON_LINKS_KEY in values:
        result[PERSON_LINKS_KEY] = deepcopy(links)
    return result


def entered_payload(payload: dict, *, schema: dict | None = None) -> dict:
    # Values from deselected supporting documents stay recoverable on the
    # application, but cannot become active inputs or signed packet content.
    keys = {field['key'] for field in _fields(schema)} if schema is not None else None
    return {key: value for key, value in payload.items()
            if key != PERSON_LINKS_KEY and (keys is None or key in keys)}


def _get(value: dict, path: tuple[str, ...]) -> Any:
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def _money(value: Any) -> Decimal:
    if value in (None, ''):
        return Decimal('0')
    try:
        result = Decimal(str(value))
        if not result.is_finite():
            raise InvalidOperation
        return result
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueContractError('Enter a valid amount.') from exc


def calculated_totals(payload: dict) -> dict:
    def total(*keys: str) -> Decimal:
        return sum((_money(payload.get(key)) for key in keys), Decimal('0'))
    business_income = total('business_sales_amount') + sum(
        (_money(row.get('amount')) for row in payload.get('business_other_income_lines', []) if isinstance(row, dict)), Decimal('0'),
    )
    business_expenses = total('business_purchases_amount', 'business_rent_expense', 'business_payroll_expense', 'business_utilities_expense', 'business_other_expense')
    # Deliberately do not use the ambiguous legacy monthly_income contribution.
    household_income = total('net_monthly_salary', 'household_spouse_net_salary', 'household_business_income', 'household_pension_income', 'household_other_income')
    household_expenses = total('household_rent_expense', 'household_school_fees_expense', 'household_transport_expense', 'household_utilities_expense', 'household_food_expense', 'household_other_loan_repayment', 'household_medical_expense', 'household_entertainment_expense', 'household_other_expense')
    assets = sum((_money(row.get('estimated_value')) for row in payload.get('secured_assets', []) if isinstance(row, dict)), Decimal('0'))
    result = {key: format(value, 'f') for key, value in {
        'business_total_income': business_income, 'business_total_expenses': business_expenses,
        'business_net_surplus': business_income - business_expenses,
        'household_total_income': household_income, 'household_total_expenses': household_expenses,
        'household_net_surplus': household_income - household_expenses, 'secured_assets_total': assets,
    }.items()}
    def present(*keys):
        return any(payload.get(key) not in (None, '', []) for key in keys)
    business_income_present = present('business_sales_amount') or any(
        row.get('amount') not in (None, '') for row in payload.get('business_other_income_lines', []) if isinstance(row, dict))
    business_expense_present = present('business_purchases_amount', 'business_rent_expense',
        'business_payroll_expense', 'business_utilities_expense', 'business_other_expense')
    household_income_present = present(
            'net_monthly_salary', 'household_spouse_net_salary', 'household_business_income',
            'household_pension_income', 'household_other_income')
    household_expense_present = present('household_rent_expense', 'household_school_fees_expense',
        'household_transport_expense', 'household_utilities_expense', 'household_food_expense',
        'household_other_loan_repayment', 'household_medical_expense', 'household_entertainment_expense', 'household_other_expense')
    for key, has_inputs in {
        'business_total_income': business_income_present, 'business_total_expenses': business_expense_present,
        'business_net_surplus': business_income_present and business_expense_present,
        'household_total_income': household_income_present, 'household_total_expenses': household_expense_present,
        'household_net_surplus': household_income_present and household_expense_present,
        'secured_assets_total': any(row.get('estimated_value') not in (None, '') for row in payload.get('secured_assets', []) if isinstance(row, dict)),
    }.items():
        if not has_inputs:
            result[key] = ''
    return result


def resolve_values(contract: dict, payload: dict, *, quote: dict, system: dict, workflow: dict, document_values: dict | None = None) -> dict:
    """Pure resolution, suitable for synthetic tests and exact frozen reconstruction."""
    document_values = document_values or {}
    shared, documents, availability = {}, {}, {}
    for document_key, fields in [('', contract['fields']), *contract['documents'].items()]:
        totals = calculated_totals({**payload, **document_values.get(document_key, {})})
        values = shared if not document_key else documents.setdefault(document_key, {})
        for key, field in fields.items():
            meaning = field['value_contract']
            source = meaning['source']
            if source == 'entered':
                store = payload if not document_key else document_values.get(document_key, {})
                value = store.get(key)
            else:
                prefix, name = meaning['binding'].split('.', 1)
                value = (_get(quote, QUOTE_BINDINGS[name]) if prefix == 'quote' else
                         system.get(name) if prefix == 'system' else
                         workflow.get(name) if prefix == 'workflow' else totals.get(name))
            values[key] = '' if value is None else deepcopy(value)
            availability[(document_key + '.' if document_key else '') + key] = {
                'status': 'present' if value not in (None, '', []) else ('waiting_for_event' if source == 'workflow' else 'missing'),
                'source': source, 'scope': meaning['scope'],
                'read_only': source != 'entered',
            }
    return {'values': shared, 'documents': documents, 'availability': availability}


def resolve_packet_values(application: Any, *, system: dict | None = None) -> dict:
    contract = packet_contract(application)
    # Retained inputs from unselected documents are recovery data, not current
    # calculation inputs. Otherwise a removed financial document could still
    # alter a total printed in the remaining packet.
    active_payload = {key: value for key, value in (application.form_payload or {}).items()
                      if key in contract['fields'] and contract['fields'][key]['value_contract']['source'] == 'entered'}
    workflow = {}
    # Only an explicit existing approval of exact frozen terms can supply this.
    event = application.events.filter(action='approval_signed').order_by('-occurred_at', '-id').first()
    if event and application.status == application.STATUS_APPROVED:
        workflow['approved_amount'] = (event.after_values or {}).get('approved_facility_amount')
    return resolve_values(
        contract, active_payload, quote=application.product_quote_snapshot or {},
        system=system or {}, workflow=workflow,
        document_values={document.document_key: document.field_payload or {} for document in application.packet_documents.all() if document.selected},
    )
