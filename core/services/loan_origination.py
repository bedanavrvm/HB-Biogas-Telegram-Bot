"""Canonical, product-neutral loan-origination application services."""

from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from core.models import (
    LoanOriginationApplication,
    OriginationApplicationEvent,
    OriginationProductDefinition,
    OriginationSigningPackage,
)


class OriginationError(ValueError):
    """Stable validation error safe for Portal responses."""

    def __init__(self, message: str, *, errors: dict[str, str] | None = None):
        super().__init__(message)
        self.errors = errors or {}


class OriginationConflict(OriginationError):
    """The caller attempted to change a stale application revision."""


SUPPORTED_FIELD_TYPES = {
    'text', 'textarea', 'number', 'money', 'date', 'phone', 'national_id',
    'choice', 'boolean', 'branch', 'county', 'sub_county',
    'repeating_group',
}

APPLICANT_NAME_KEYS = (
    'applicant_full_name', 'borrower_full_name', 'customer_name',
)
APPLICANT_ID_KEYS = ('applicant_id_number', 'applicant_national_id', 'national_id')
APPLICANT_PHONE_KEYS = ('applicant_phone', 'applicant_primary_phone', 'primary_phone')
APPLICANT_IDENTITY_CONTRACT = 'applicant_v1'

SIGNER_ROLE_CATALOG = (
    ('borrower', 'Borrower'),
    ('customer', 'Borrower (legacy compatibility role)'),
    ('guarantor_1', 'Guarantor 1'),
    ('guarantor_2', 'Guarantor 2'),
    ('bro_1', 'Business Relationship Officer 1'),
    ('bro_2', 'Business Relationship Officer 2'),
    ('loan_officer', 'Loan Officer'),
    ('officer', 'Officer (legacy role)'),
    ('branch_manager', 'Branch Manager'),
    ('commissioner_for_oaths', 'Commissioner for Oaths'),
    ('witness', 'Witness'),
)


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    errors: dict[str, str]


def _require_request_id(request_id: str) -> str:
    value = str(request_id or '').strip()
    if not value:
        raise OriginationError('A client request ID is required.')
    return value[:128]


def _schema_fields(schema: dict[str, Any]) -> list[dict[str, Any]]:
    fields = schema.get('fields', []) if isinstance(schema, dict) else []
    if not isinstance(fields, list):
        raise OriginationError('The product form schema is invalid.')
    return [field for field in fields if isinstance(field, dict)]


def validate_product_form_contract(
    form_schema: dict[str, Any], signer_rules: Any, *, require_signers: bool = True,
) -> None:
    """Validate a visual form contract before template calibration.

    Supporting PDFs use the same governed field schema as a primary LAF, but
    do not necessarily need a signature slot.  Primary callers retain the
    existing signer requirement by default.
    """
    fields = _schema_fields(form_schema)
    if not fields:
        raise OriginationError('An active origination product requires at least one form field.')
    keys = [str(field.get('key') or '').strip() for field in fields]
    if any(not key for key in keys) or len(keys) != len(set(keys)):
        raise OriginationError('Every origination field requires a unique key.')
    sections = form_schema.get('sections', []) if isinstance(form_schema, dict) else []
    if sections:
        if not isinstance(sections, list) or any(not isinstance(item, dict) for item in sections):
            raise OriginationError('Origination form sections must be a list of objects.')
        section_keys = [str(item.get('key') or '').strip() for item in sections]
        if any(not key for key in section_keys) or len(section_keys) != len(set(section_keys)):
            raise OriginationError('Every origination section requires a unique key.')
        expected_keys = []
        for index, item in enumerate(sections):
            label = str(item.get('label') or '').strip()
            if not label:
                raise OriginationError('Every origination section requires a title.')
            base = re.sub(r'[^a-z0-9]+', '_', label.casefold()).strip('_') or f'section_{index + 1}'
            expected = base
            suffix = 2
            while expected in expected_keys:
                expected = f'{base}_{suffix}'
                suffix += 1
            expected_keys.append(expected)
        if section_keys != expected_keys:
            raise OriginationError('Section keys must be generated from their section titles.')
        unknown_sections = sorted({
            str(field.get('section_key') or '').strip()
            for field in fields
            if str(field.get('section_key') or '').strip() not in set(section_keys)
        })
        if unknown_sections:
            raise OriginationError(f'Unknown origination sections: {", ".join(unknown_sections)}.')
    for field in fields:
        field_type = str(field.get('type') or 'text').strip()
        if field_type not in SUPPORTED_FIELD_TYPES:
            raise OriginationError(f'Field {field.get("key")} has an unsupported control type.')
        if field_type == 'choice':
            options = field.get('options')
            if not isinstance(options, list) or not options:
                raise OriginationError(f'Choice field {field.get("key")} requires at least one option.')
            codes = [
                str(item.get('code') if isinstance(item, dict) else item).strip()
                for item in options
            ]
            if any(not code for code in codes) or len(codes) != len(set(codes)):
                raise OriginationError(
                    f'Choice field {field.get("key")} requires unique option codes.',
                )
        if field_type == 'repeating_group':
            structure = field.get('structure') or {}
            columns = structure.get('columns') if isinstance(structure, dict) else None
            if not isinstance(columns, list) or not columns:
                raise OriginationError(f'Repeatable field {field.get("key")} requires child columns.')
            column_keys = [str(item.get('key') or '') for item in columns if isinstance(item, dict)]
            if len(column_keys) != len(columns) or any(not key for key in column_keys) or len(column_keys) != len(set(column_keys)):
                raise OriginationError(f'Repeatable field {field.get("key")} has invalid child columns.')
            minimum = int(structure.get('min_items', 0) or 0)
            maximum = int(structure.get('max_items', 0) or 0)
            if minimum < 0 or maximum < 1 or minimum > maximum or maximum > 50:
                raise OriginationError(f'Repeatable field {field.get("key")} has invalid item limits.')
        validation = field.get('validation') or {}
        if not isinstance(validation, dict):
            raise OriginationError(f'Field {field.get("key")} has invalid validation rules.')
        pattern = str(validation.get('pattern') or '')
        if len(pattern) > 200:
            raise OriginationError(f'Field {field.get("key")} has a validation pattern that is too long.')
        if pattern:
            try:
                re.compile(pattern)
            except re.error as exc:
                raise OriginationError(
                    f'Field {field.get("key")} has an invalid validation pattern.',
                ) from exc
        try:
            if field_type in {'number', 'money'}:
                minimum = validation.get('min')
                maximum = validation.get('max')
                minimum_value = Decimal(str(minimum)) if minimum not in (None, '') else None
                maximum_value = Decimal(str(maximum)) if maximum not in (None, '') else None
                if minimum_value is not None and maximum_value is not None and minimum_value > maximum_value:
                    raise OriginationError(f'Field {field.get("key")} has minimum above maximum.')
            elif field_type in {'text', 'textarea', 'phone', 'national_id', 'branch', 'county', 'sub_county'}:
                minimum_length = int(validation.get('min_length', 0) or 0)
                maximum_length = int(validation.get('max_length', 0) or 0)
                if minimum_length < 0 or maximum_length < 0:
                    raise OriginationError(f'Field {field.get("key")} has a negative length limit.')
                if maximum_length and minimum_length > maximum_length:
                    raise OriginationError(f'Field {field.get("key")} has minimum length above maximum length.')
            elif field_type == 'date':
                from datetime import date
                earliest = validation.get('min_date')
                latest = validation.get('max_date')
                earliest_value = date.fromisoformat(str(earliest)) if earliest else None
                latest_value = date.fromisoformat(str(latest)) if latest else None
                if earliest_value and latest_value and earliest_value > latest_value:
                    raise OriginationError(f'Field {field.get("key")} has earliest date after latest date.')
        except OriginationError:
            raise
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise OriginationError(f'Field {field.get("key")} has invalid validation limits.') from exc
    known_roles = {key for key, _label in SIGNER_ROLE_CATALOG}
    if not isinstance(signer_rules, list) or (require_signers and not signer_rules):
        raise OriginationError(
            'An active origination product requires signer rules.'
            if require_signers else 'Signer rules must be a list.',
        )
    roles = [str(item.get('role') or '').strip() for item in signer_rules if isinstance(item, dict)]
    if len(roles) != len(signer_rules) or any(role not in known_roles for role in roles):
        raise OriginationError('Every signer requires a role from the approved catalogue.')
    if len(roles) != len(set(roles)):
        raise OriginationError('Signer roles cannot be duplicated.')
    for rule in signer_rules:
        slots = rule.get('slots', [])
        if not isinstance(slots, list):
            raise OriginationError(f'Signer {rule.get("role")} requires a valid slot list.')
        if rule.get('required', False) and 'slots' in rule and not slots:
            raise OriginationError(f'Required signer {rule.get("role")} requires at least one signature or stamp slot.')
        slot_keys = []
        for raw_slot in slots:
            slot = {'key': raw_slot} if isinstance(raw_slot, str) else raw_slot
            if not isinstance(slot, dict) or not str(slot.get('key') or '').strip():
                raise OriginationError(f'Signer {rule.get("role")} has an invalid slot.')
            slot_keys.append(str(slot.get('key')).strip())
            if str(slot.get('type') or rule.get('slot_type') or 'signature') not in {'signature', 'stamp', 'date_signed'}:
                raise OriginationError(f'Signer {rule.get("role")} has an unsupported slot type.')
        if len(slot_keys) != len(set(slot_keys)):
            raise OriginationError(f'Signer {rule.get("role")} has duplicate slot keys.')


def validate_product_definition(definition: OriginationProductDefinition) -> None:
    """Reject activation of incomplete or ambiguous product contracts."""
    validate_product_form_contract(definition.form_schema, definition.signer_rules)
    if not definition.document_type.strip():
        raise OriginationError('An active origination product requires an e-sign document type.')
    if not definition.document_template_name.strip():
        raise OriginationError('An active origination product requires an approved document template.')
    digest = definition.document_template_sha256.strip().lower()
    if len(digest) != 64 or any(character not in '0123456789abcdef' for character in digest):
        raise OriginationError('The approved document template requires a valid SHA-256 digest.')


def validate_applicant_identity_contract(schema: dict[str, Any]) -> None:
    """Require the stable Applicant identity used by queues and review."""
    fields = {str(item.get('key') or ''): item for item in _schema_fields(schema)}
    full_name = next((fields[key] for key in APPLICANT_NAME_KEYS if key in fields), None)
    split_name = fields.get('applicant_first_name') and fields.get('applicant_surname')
    national_id = next((fields[key] for key in APPLICANT_ID_KEYS if key in fields), None)
    phone = next((fields[key] for key in APPLICANT_PHONE_KEYS if key in fields), None)
    missing = []
    if not full_name and not split_name:
        missing.append('Applicant name')
    if not national_id:
        missing.append('Applicant National ID')
    if not phone:
        missing.append('Applicant telephone')
    if missing:
        raise OriginationError(
            'Add the required canonical identity fields before publishing: '
            + ', '.join(missing) + '.',
        )
    required_fields = [national_id, phone]
    if full_name:
        required_fields.append(full_name)
    else:
        required_fields.extend([fields['applicant_first_name'], fields['applicant_surname']])
    optional = [
        str(item.get('label') or item.get('key') or '')
        for item in required_fields if not item.get('required')
    ]
    if optional:
        raise OriginationError(
            'Mark the Applicant identity fields as required before publishing: '
            + ', '.join(optional) + '.',
        )


def applicant_identity_snapshot(payload: dict[str, Any] | None) -> dict[str, str]:
    values = payload if isinstance(payload, dict) else {}
    full_name = next((
        str(values.get(key) or '').strip()
        for key in APPLICANT_NAME_KEYS if str(values.get(key) or '').strip()
    ), '')
    if not full_name:
        full_name = ' '.join(
            str(values.get(key) or '').strip()
            for key in ('applicant_first_name', 'applicant_middle_name', 'applicant_surname')
            if str(values.get(key) or '').strip()
        )
    national_id = next((
        str(values.get(key) or '').strip()
        for key in APPLICANT_ID_KEYS if str(values.get(key) or '').strip()
    ), '')
    phone = next((
        str(values.get(key) or '').strip()
        for key in APPLICANT_PHONE_KEYS if str(values.get(key) or '').strip()
    ), '')
    return {'name': full_name, 'national_id': national_id, 'phone': phone}


def _payload_has_value(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    return any(value not in (None, '', [], {}) for value in payload.values())


def correction_targets(application: LoanOriginationApplication) -> dict[str, set[str]]:
    correction = application.correction_requests.filter(status='open').prefetch_related('items').first()
    targets = {'field': set(), 'requirement': set(), 'document_field': set()}
    if correction:
        for item in correction.items.all():
            if item.target_type in targets:
                targets[item.target_type].add(item.target_key)
    return targets


def _changed_keys(before: dict[str, Any] | None, after: dict[str, Any] | None) -> set[str]:
    left = before if isinstance(before, dict) else {}
    right = after if isinstance(after, dict) else {}
    return {key for key in set(left) | set(right) if left.get(key) != right.get(key)}


def validate_form_payload(schema: dict[str, Any], payload: Any, *, require_complete: bool) -> ValidationResult:
    if not isinstance(payload, dict):
        return ValidationResult(False, {'form': 'Application data must be an object.'})
    errors: dict[str, str] = {}
    fields = _schema_fields(schema)
    known = {str(field.get('key') or '').strip(): field for field in fields}
    unknown = sorted(set(payload) - set(known))
    if unknown:
        errors['form'] = f'Unknown application fields: {", ".join(unknown)}.'
    for key, field in known.items():
        value = payload.get(key)
        if require_complete and field.get('required') and value in (None, '', []):
            errors[key] = 'This field is required.'
            continue
        if value in (None, ''):
            continue
        field_type = str(field.get('type') or 'text')
        validation = field.get('validation') if isinstance(field.get('validation'), dict) else {}
        if field_type == 'repeating_group':
            if not isinstance(value, list):
                errors[key] = 'Enter a valid list of items.'
                continue
            structure = field.get('structure') if isinstance(field.get('structure'), dict) else {}
            columns = [item for item in (structure.get('columns') or []) if isinstance(item, dict)]
            minimum = int(structure.get('min_items', 0) or 0)
            maximum = int(structure.get('max_items', 0) or 0)
            if require_complete and len(value) < minimum:
                errors[key] = f'Add at least {minimum} item.'
                continue
            if maximum and len(value) > maximum:
                errors[key] = f'Add no more than {maximum} items.'
                continue
            allowed_keys = {'row_id'} | {str(column.get('key') or '') for column in columns}
            row_ids = set()
            for index, row in enumerate(value):
                if not isinstance(row, dict) or set(row) - allowed_keys:
                    errors[key] = f'Row {index + 1} is invalid.'
                    break
                try:
                    row_id = str(uuid.UUID(str(row.get('row_id') or '')))
                except (TypeError, ValueError, AttributeError):
                    errors[key] = f'Row {index + 1} requires a stable identity.'
                    break
                if row_id in row_ids:
                    errors[key] = f'Row {index + 1} has a duplicate identity.'
                    break
                row_ids.add(row_id)
                for column in columns:
                    column_key = str(column.get('key') or '')
                    cell = row.get(column_key)
                    if require_complete and column.get('required') and cell in (None, ''):
                        errors[key] = f'Complete {column.get("label") or column_key} in row {index + 1}.'
                        break
                    if cell in (None, ''):
                        continue
                    if str(column.get('type') or '') in {'money', 'number'}:
                        try:
                            decimal_value = Decimal(str(cell))
                            if not decimal_value.is_finite():
                                raise InvalidOperation
                            minimum_value = (column.get('validation') or {}).get('min')
                            if minimum_value not in (None, '') and decimal_value < Decimal(str(minimum_value)):
                                raise InvalidOperation
                        except (InvalidOperation, TypeError, ValueError):
                            errors[key] = f'Enter a valid value in row {index + 1}.'
                            break
                if key in errors:
                    break
            continue
        if field_type in {'text', 'textarea', 'phone', 'national_id', 'date', 'choice', 'branch', 'county', 'sub_county'} and not isinstance(value, str):
            errors[key] = 'Enter a valid text value.'
        elif field_type == 'boolean' and not isinstance(value, bool):
            errors[key] = 'Choose yes or no.'
        elif field_type in {'money', 'number'}:
            try:
                decimal_value = Decimal(str(value))
            except (InvalidOperation, TypeError, ValueError):
                errors[key] = 'Enter a valid amount.'
            else:
                if not decimal_value.is_finite():
                    errors[key] = 'Enter a valid amount.'
                elif str(field.get('reporting_use') or 'unavailable') != 'unavailable':
                    digits = len(decimal_value.as_tuple().digits)
                    exponent = decimal_value.as_tuple().exponent
                    integer_digits = digits + exponent if exponent >= 0 else max(digits + exponent, 0)
                    decimal_places = max(-exponent, 0)
                    if integer_digits > 20 or decimal_places > 4:
                        errors[key] = 'Enter at most 20 whole-number digits and 4 decimal places.'
                if key not in errors:
                    minimum = validation.get('min')
                    maximum = validation.get('max')
                    try:
                        if minimum not in (None, '') and decimal_value < Decimal(str(minimum)):
                            errors[key] = f'Enter a value of at least {minimum}.'
                        elif maximum not in (None, '') and decimal_value > Decimal(str(maximum)):
                            errors[key] = f'Enter a value no greater than {maximum}.'
                    except (InvalidOperation, TypeError, ValueError):
                        errors[key] = 'This field has invalid configured limits.'
        if key in errors:
            continue
        if (
            field_type in {'text', 'textarea', 'phone', 'national_id', 'branch', 'county', 'sub_county'}
            and str(field.get('reporting_use') or 'unavailable') != 'unavailable'
            and len(value) > 500
        ):
            errors[key] = 'Enter no more than 500 characters for this reportable field.'
            continue
        if field_type in {'text', 'textarea', 'phone', 'national_id', 'branch', 'county', 'sub_county'}:
            minimum_length = validation.get('min_length')
            maximum_length = validation.get('max_length')
            if minimum_length not in (None, '') and len(value) < int(minimum_length):
                errors[key] = f'Enter at least {minimum_length} characters.'
                continue
            if maximum_length not in (None, '') and len(value) > int(maximum_length):
                errors[key] = f'Enter no more than {maximum_length} characters.'
                continue
            pattern = str(validation.get('pattern') or '')
            if pattern and re.fullmatch(pattern[:200], value[:2000]) is None:
                errors[key] = 'Enter the value in the required format.'
                continue
        if field_type == 'choice':
            allowed = {
                str(item.get('code') if isinstance(item, dict) else item).strip()
                for item in (field.get('options') or [])
            }
            if value not in allowed:
                errors[key] = 'Choose an available option.'
        elif field_type == 'date':
            from datetime import date, timedelta
            try:
                parsed_date = date.fromisoformat(value)
            except ValueError:
                errors[key] = 'Enter a valid date.'
            else:
                earliest = validation.get('min_date')
                latest = validation.get('max_date')
                try:
                    if earliest and parsed_date < date.fromisoformat(str(earliest)):
                        errors[key] = f'Choose a date on or after {earliest}.'
                    elif latest and parsed_date > date.fromisoformat(str(latest)):
                        errors[key] = f'Choose a date on or before {latest}.'
                except ValueError:
                    errors[key] = 'This field has invalid configured date limits.'
                if key == 'applicant_dob' and key not in errors:
                    today = timezone.localdate()
                    if parsed_date > today:
                        errors[key] = 'Applicant date of birth cannot be in the future.'
                    elif parsed_date < today - timedelta(days=366 * 120):
                        errors[key] = 'Applicant date of birth is outside the supported range.'
    return ValidationResult(not errors, errors)


def normalize_form_payload(schema: dict[str, Any], payload: Any) -> dict[str, Any]:
    """Canonicalize collection identities and Decimal cells before validation/storage."""
    if not isinstance(payload, dict):
        return payload
    normalized = dict(payload)
    for field in _schema_fields(schema):
        key = str(field.get('key') or '')
        if str(field.get('type') or '') != 'repeating_group' or key not in normalized:
            continue
        rows = normalized.get(key)
        if not isinstance(rows, list):
            continue
        columns = {
            str(item.get('key') or ''): str(item.get('type') or '')
            for item in ((field.get('structure') or {}).get('columns') or [])
            if isinstance(item, dict)
        }
        cleaned = []
        for raw in rows:
            if not isinstance(raw, dict):
                cleaned.append(raw)
                continue
            row = dict(raw)
            try:
                row['row_id'] = str(uuid.UUID(str(row.get('row_id') or '')))
            except (TypeError, ValueError, AttributeError):
                row['row_id'] = str(uuid.uuid4())
            for column_key, column_type in columns.items():
                if column_type in {'money', 'number'} and row.get(column_key) not in (None, ''):
                    try:
                        row[column_key] = format(Decimal(str(row[column_key])), 'f')
                    except (InvalidOperation, TypeError, ValueError):
                        pass
            cleaned.append(row)
        normalized[key] = cleaned
    return normalized


def synchronize_legacy_security_values(values: dict[str, Any], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    """Keep the legacy first-security scalars aligned with the canonical collection."""
    merged = {**(existing or {}), **values}
    assets = merged.get('secured_assets')
    if isinstance(assets, list) and assets:
        first = assets[0] if isinstance(assets[0], dict) else {}
        merged['security_1_description'] = first.get('description', '')
        merged['security_1_current_value'] = first.get('estimated_value', '')
    elif 'security_1_description' in values or 'security_1_current_value' in values:
        prior = assets[0] if isinstance(assets, list) and assets and isinstance(assets[0], dict) else {}
        row = {
            'row_id': str(prior.get('row_id') or uuid.uuid4()),
            'description': merged.get('security_1_description', ''),
            'estimated_value': merged.get('security_1_current_value', ''),
        }
        if row['description'] not in (None, '') or row['estimated_value'] not in (None, ''):
            merged['secured_assets'] = [row, *(assets[1:] if isinstance(assets, list) else [])]
    return merged


def _missing_application_requirements(
    application: LoanOriginationApplication, *, stage: str,
) -> list[dict[str, str]]:
    from core.services.origination_evidence import requirement_has_evidence
    result = []
    evidence = application.product_requirement_evidence or {}
    for item in (application.product_terms_snapshot or {}).get('requirements', []):
        if not isinstance(item, dict):
            continue
        if not (
            bool(item.get('required'))
            and str(item.get('enforcement_stage') or '') == str(stage or '')
            and str(item.get('workflow') or '') in {'', 'loan_origination'}
        ):
            continue
        key = str(item.get('key') or '')
        requirement_type = str(item.get('type') or 'text')
        value = evidence.get(key)
        valid = value not in (None, '', [], {})
        if requirement_type == 'document':
            valid = requirement_has_evidence(application, key)
        elif requirement_type in {'checkbox', 'eligibility'}:
            valid = value is True
        elif requirement_type in {'amount', 'money', 'number'} and valid:
            try:
                amount = Decimal(str(value))
                validation = item.get('validation') if isinstance(item.get('validation'), dict) else {}
                minimum = validation.get('min')
                maximum = validation.get('max')
                valid = (minimum in (None, '') or amount >= Decimal(str(minimum))) and (
                    maximum in (None, '') or amount <= Decimal(str(maximum))
                )
            except (InvalidOperation, TypeError, ValueError):
                valid = False
        if not valid:
            result.append({
                'key': key,
                'label': str(item.get('label') or key),
                'type': requirement_type,
            })
    return result


def _record_event(application, action: str, *, actor, request_id: str = '', before=None, after=None) -> None:
    event = OriginationApplicationEvent.objects.create(
        application=application,
        action=action,
        revision=application.revision,
        actor=actor,
        request_id=request_id,
        before_values=before or {},
        after_values=after or {},
    )
    from core.services.compliance_audit import record_event
    record_event(
        workflow='portal', action=f'portal.origination.{action}', category='workflow',
        origin='human' if actor else 'system', subject_type='loan_origination_application',
        subject_id=str(application.pk), actor=actor, authority_user=actor,
        request_id=request_id, source_model='OriginationApplicationEvent',
        source_event_id=str(event.pk),
        deduplication_key=f'portal:OriginationApplicationEvent:{event.pk}',
        after_values={'status': application.status, 'revision': application.revision},
        metadata={'product_key': application.product_definition.product_key}, sensitive=True,
        occurred_at=event.occurred_at,
    )


def preview_context(application: LoanOriginationApplication) -> dict[str, Any]:
    context = {
        **application.form_payload,
        'reference_number': application.reference_number,
        'branch_code': application.branch,
        'loan_officer_name': application.officer.get_full_name() or application.officer.get_username(),
        'application_date': timezone.localdate(application.created_at).isoformat(),
    }
    assets = context.get('secured_assets')
    if isinstance(assets, list):
        total = Decimal('0')
        for row in assets:
            try:
                total += Decimal(str(row.get('estimated_value') or '0')) if isinstance(row, dict) else Decimal('0')
            except (InvalidOperation, TypeError, ValueError):
                continue
        context['secured_assets_total'] = format(total, 'f')
    for field in _schema_fields(application.schema_snapshot):
        if str(field.get('type') or '') != 'choice':
            continue
        key = str(field.get('key') or '')
        stored = context.get(key)
        for option in field.get('options') or []:
            if not isinstance(option, dict):
                continue
            if str(option.get('code') or '') == stored:
                context[key] = str(option.get('label') or stored)
                break
    return context


def render_application_preview(application: LoanOriginationApplication) -> bytes:
    """Render the approved PDF locally; no signing package or file is persisted."""
    definition = application.product_definition
    # Until a signing package is prepared this endpoint is a live preview, so
    # it must reflect the latest published Admin calibration.  The signing
    # package remains immutable and continues to use its captured snapshot.
    if application.status in {
        LoanOriginationApplication.STATUS_DRAFT,
        LoanOriginationApplication.STATUS_CORRECTION_REQUIRED,
        LoanOriginationApplication.STATUS_READY_FOR_REVIEW,
        LoanOriginationApplication.STATUS_REVIEWED,
    }:
        latest_configuration = _published_template_configuration(definition)
        if latest_configuration and latest_configuration != application.template_configuration_snapshot:
            application.template_configuration_snapshot = latest_configuration
            application.save(update_fields=['template_configuration_snapshot', 'updated_at'])
    try:
        from core.services.partnership_laf_preview import (
            PartnershipLafPreviewError, render_origination_document, render_partnership_laf,
        )
        renderer = render_partnership_laf if definition.document_type == 'partnership_loan_application' else render_origination_document
        kwargs = {
            'version': definition.document_template_version,
            'expected_sha256': definition.document_template_sha256,
            'configuration': application.template_configuration_snapshot or None,
        }
        if renderer is render_origination_document:
            kwargs['document_type'] = definition.document_type
        return renderer(preview_context(application), **kwargs)
    except PartnershipLafPreviewError as exc:
        raise OriginationError(str(exc)) from exc


@transaction.atomic
def create_application(*, product_key: str, officer, branch: str, client_request_id: str) -> tuple[LoanOriginationApplication, bool]:
    client_request_id = _require_request_id(client_request_id)
    from core.services.location_catalog import resolve_location
    branch = str(branch or '').strip()
    branch_record = resolve_location(branch, location_type='branch')
    existing = LoanOriginationApplication.objects.filter(
        officer=officer, client_request_id=client_request_id,
    ).first()
    if existing:
        return existing, True
    definition = OriginationProductDefinition.objects.filter(
        product_key=product_key, is_active=True,
    ).first()
    if not definition:
        raise OriginationError('This origination product is not active.')
    validate_product_definition(definition)
    from core.services.product_catalog import (
        active_product_version, product_is_available, serialize_product_version,
    )
    if definition.product_version_id:
        current = active_product_version(definition.product_version.product)
        if current is None or current.pk != definition.product_version_id:
            raise OriginationError('This product version is not currently effective.')
        if not product_is_available(
            definition.product_version.product, branch=branch_record,
            workflow='loan_origination', channel='portal',
        ):
            raise OriginationError('This product is not available for the selected branch in Loan Origination.')
    terms_snapshot = (
        serialize_product_version(definition.product_version)
        if definition.product_version_id else {}
    )
    application_id = uuid.uuid4()
    from core.services.location_catalog import location_snapshot, validate_location_selection
    branch_record, _county, _sub_county = validate_location_selection(
        branch_value=branch,
        source_workflow='loan_origination',
        source_model='LoanOriginationApplication',
        source_record_id=application_id,
        actor=officer,
        request_id=client_request_id,
    )
    if branch_record:
        branch = branch_record.name
    try:
        with transaction.atomic():
            from core.services.origination_fields import snapshot_form_schema
            application = LoanOriginationApplication.objects.create(
                id=application_id,
                reference_number=f'ORG-{timezone.localdate():%Y}-{str(application_id)[:8].upper()}',
                product_definition=definition,
                product_version=definition.product_version,
                officer=officer,
                branch=branch,
                branch_ref=branch_record,
                location_snapshot=location_snapshot(branch=branch_record),
                schema_snapshot=snapshot_form_schema(definition.form_schema),
                signer_rules_snapshot=definition.signer_rules,
                template_configuration_snapshot=_published_template_configuration(definition),
                product_terms_snapshot=terms_snapshot,
                client_request_id=client_request_id,
            )
    except IntegrityError:
        existing = LoanOriginationApplication.objects.filter(
            officer=officer, client_request_id=client_request_id,
        ).first()
        if existing:
            return existing, True
        raise
    _record_event(application, 'created', actor=officer, request_id=client_request_id)
    from core.services.origination_documents import initialize_document_packet
    initialize_document_packet(application)
    return application, False


def _published_template_configuration(definition: OriginationProductDefinition) -> dict[str, Any]:
    from core.models import OriginationDocumentTemplate
    template = OriginationDocumentTemplate.objects.filter(
        document_type=definition.document_type,
        version=definition.document_template_version,
        source_sha256=definition.document_template_sha256,
        status=OriginationDocumentTemplate.STATUS_ACTIVE,
    ).first()
    if not template:
        return {}
    revision = template.published_configuration_revision
    return (revision.configuration if revision else template.placement_config) or {}
@transaction.atomic
def save_application_fields(
    *, application_id, actor, payload: Any, expected_revision: int, request_id: str,
    requirement_evidence: Any = None, custom_values: Any = None,
    selected_fee_keys: Any = None,
) -> LoanOriginationApplication:
    request_id = _require_request_id(request_id)
    application = LoanOriginationApplication.objects.select_for_update().select_related('product_definition').get(pk=application_id)
    if request_id and application.events.filter(request_id=request_id).exists():
        return application
    if application.officer_id != actor.pk:
        raise OriginationError('Only the assigned officer may edit this application.')
    if application.status not in {
        LoanOriginationApplication.STATUS_DRAFT,
        LoanOriginationApplication.STATUS_CORRECTION_REQUIRED,
    }:
        raise OriginationError('This application is no longer editable.')
    if int(expected_revision) != application.revision:
        raise OriginationConflict('This application changed on another device. Refresh before saving again.')
    correcting = application.status == LoanOriginationApplication.STATUS_CORRECTION_REQUIRED
    targets = correction_targets(application) if correcting else None
    if correcting and not any(targets.values()):
        raise OriginationError('This correction request has no editable targets. Ask the checker to replace it.')
    payload = normalize_form_payload(application.schema_snapshot, payload)
    schema_keys = {str(item.get('key') or '') for item in _schema_fields(application.schema_snapshot)}
    if isinstance(payload, dict) and (
        'secured_assets' in payload
        or ({'security_1_description', 'security_1_current_value'} & set(payload) and 'secured_assets' in schema_keys)
    ):
        synchronized = synchronize_legacy_security_values(payload, application.form_payload)
        payload = {key: value for key, value in synchronized.items() if key in schema_keys}
    result = validate_form_payload(application.schema_snapshot, payload, require_complete=False)
    if not result.valid:
        raise OriginationError(next(iter(result.errors.values())), errors=result.errors)
    if correcting:
        disallowed_fields = _changed_keys(application.form_payload, payload) - targets['field']
        if disallowed_fields:
            raise OriginationError(
                'Only fields requested by the checker may be changed.',
                errors={key: 'This field is locked for this correction.' for key in disallowed_fields},
            )
        incoming_requirements = (
            requirement_evidence if requirement_evidence is not None
            else application.product_requirement_evidence
        )
        disallowed_requirements = (
            _changed_keys(application.product_requirement_evidence, incoming_requirements)
            - targets['requirement']
        )
        if disallowed_requirements:
            raise OriginationError(
                'Only requirements requested by the checker may be changed.',
                errors={f'requirement:{key}': 'This requirement is locked.' for key in disallowed_requirements},
            )
        if custom_values is not None and custom_values != application.product_custom_values:
            raise OriginationError('Product-specific values are locked during this correction.')
        if selected_fee_keys is not None and selected_fee_keys != application.product_selected_fee_keys:
            raise OriginationError('Fee selections are locked during this correction.')
    if requirement_evidence is not None and not isinstance(requirement_evidence, dict):
        raise OriginationError('Product requirement evidence must be an object.')
    if custom_values is not None and not isinstance(custom_values, dict):
        raise OriginationError('Product custom values must be an object.')
    if selected_fee_keys is not None and not isinstance(selected_fee_keys, list):
        raise OriginationError('Selected product fees must be a list.')
    selected_fee_keys = (
        list(dict.fromkeys(str(value).strip() for value in selected_fee_keys if str(value).strip()))
        if selected_fee_keys is not None else application.product_selected_fee_keys
    )
    if application.product_version_id:
        allowed_fee_keys = set(application.product_version.fees.filter(mandatory=False).values_list('key', flat=True))
        if set(selected_fee_keys) - allowed_fee_keys:
            raise OriginationError('One or more selected fees are not available for this product version.')
    if custom_values is not None:
        from core.services.product_catalog import validate_custom_values
        errors = validate_custom_values(application.product_version, custom_values, workflow='loan_origination')
        if errors:
            raise OriginationError(
                next(iter(errors.values())),
                errors={f'custom:{key}': value for key, value in errors.items()},
            )
    quote_snapshot = application.product_quote_snapshot
    if application.product_version_id:
        amount_key = application.product_version.quote_amount_field_key
        tenor_key = application.product_version.quote_tenor_field_key
        amount_value = payload.get(amount_key)
        tenor_value = payload.get(tenor_key)
        if amount_value not in (None, '') and tenor_value not in (None, ''):
            match = re.search(r'\d+', str(tenor_value))
            if not match:
                raise OriginationError(f'{tenor_key.replace("_", " ").title()} must contain a whole number.')
            from core.services.product_catalog import ProductCatalogError
            from core.services.product_quotes import calculate_product_quote
            try:
                quote_snapshot = calculate_product_quote(
                    application.product_version, amount=amount_value, tenor=match.group(0),
                    optional_fee_keys=selected_fee_keys,
                )
            except ProductCatalogError as exc:
                raise OriginationError(str(exc)) from exc
    before = {'status': application.status, 'revision': application.revision}
    from core.services.location_catalog import location_snapshot, validate_location_selection
    location_keys = {
        str(field.get('type') or ''): str(field.get('key') or '')
        for field in _schema_fields(application.schema_snapshot)
        if str(field.get('type') or '') in {'branch', 'county', 'sub_county'}
    }
    county_key = location_keys.get('county') or next((
        key for key in ('county', 'applicant_county', 'business_county')
        if str(payload.get(key) or '').strip()
    ), '')
    sub_county_key = location_keys.get('sub_county') or next((
        key for key in ('sub_county', 'subcounty', 'applicant_sub_county', 'business_sub_county')
        if str(payload.get(key) or '').strip()
    ), '')
    branch_record, county_record, sub_county_record = validate_location_selection(
        branch_value=application.branch_ref or application.branch,
        county_value=payload.get(county_key, '') if county_key else '',
        sub_county_value=payload.get(sub_county_key, '') if sub_county_key else '',
        source_workflow='loan_origination',
        source_model='LoanOriginationApplication',
        source_record_id=application.pk,
        actor=actor,
        request_id=request_id,
    )
    branch_key = location_keys.get('branch', '')
    if branch_key and str(payload.get(branch_key) or '').strip():
        from core.services.location_catalog import resolve_location
        payload_branch = resolve_location(payload[branch_key], location_type='branch')
        if not payload_branch or not branch_record or payload_branch.pk != branch_record.pk:
            raise OriginationError('The form branch must match the application branch.')
        payload[branch_key] = branch_record.name
    if county_key and county_record:
        payload[county_key] = county_record.name
    if sub_county_key and sub_county_record:
        payload[sub_county_key] = sub_county_record.name
    application.form_payload = payload
    application.identity_snapshot = applicant_identity_snapshot(payload)
    application.branch_ref = branch_record
    application.county_ref = county_record
    application.sub_county_ref = sub_county_record
    application.location_snapshot = location_snapshot(
        branch=branch_record, county=county_record, sub_county=sub_county_record,
    )
    application.product_quote_snapshot = quote_snapshot
    if requirement_evidence is not None:
        application.product_requirement_evidence = requirement_evidence
    if custom_values is not None:
        application.product_custom_values = custom_values
    application.product_selected_fee_keys = selected_fee_keys
    application.revision += 1
    application.status = (
        LoanOriginationApplication.STATUS_CORRECTION_REQUIRED
        if correcting else LoanOriginationApplication.STATUS_DRAFT
    )
    application.save(update_fields=[
        'form_payload', 'identity_snapshot', 'product_quote_snapshot', 'product_requirement_evidence', 'product_custom_values',
        'product_selected_fee_keys',
        'branch_ref', 'county_ref', 'sub_county_ref', 'location_snapshot',
        'revision', 'status', 'updated_at',
    ])
    from core.services.origination_documents import refresh_document_applicability
    refresh_document_applicability(application)
    _record_event(application, 'fields_saved', actor=actor, request_id=request_id, before=before)
    return application


@transaction.atomic
def save_signing_requirements(
    *, application_id, actor, requirement_evidence: Any,
    expected_revision: int, request_id: str,
) -> LoanOriginationApplication:
    """Save only signing-stage product requirements after application review."""
    request_id = _require_request_id(request_id)
    application = LoanOriginationApplication.objects.select_for_update().get(pk=application_id)
    if application.events.filter(action='signing_requirements_saved', request_id=request_id).exists():
        return application
    if application.status != LoanOriginationApplication.STATUS_REVIEWED:
        raise OriginationError('Signing requirements can only be changed on a reviewed application.')
    if int(expected_revision) != application.revision:
        raise OriginationConflict('This application changed. Refresh before saving signing requirements.')
    if not isinstance(requirement_evidence, dict):
        raise OriginationError('Signing requirements must be an object.')
    snapshot_requirements = {
        str(item.get('key') or ''): item
        for item in (application.product_terms_snapshot or {}).get('requirements', [])
        if isinstance(item, dict)
        and str(item.get('workflow') or '') in {'', 'loan_origination'}
    }
    unknown = set(requirement_evidence) - set(snapshot_requirements)
    if unknown:
        raise OriginationError('One or more signing requirements are not part of this application.')
    signing_keys = {
        key for key, item in snapshot_requirements.items()
        if str(item.get('enforcement_stage') or '') == 'signing'
        and str(item.get('type') or '') != 'document'
    }
    original = dict(application.product_requirement_evidence or {})
    merged = dict(original)
    for key in signing_keys:
        if key in requirement_evidence:
            merged[key] = requirement_evidence[key]
    application.product_requirement_evidence = merged
    missing = [
        item for item in _missing_application_requirements(application, stage='signing')
        if item.get('type') != 'document'
    ]
    if missing:
        raise OriginationError(
            'Complete signing requirements: ' + ', '.join(item['label'] for item in missing),
            errors={f"requirement:{item['key']}": 'Required before signing' for item in missing},
        )
    if merged == original:
        return application
    application.revision += 1
    application.save(update_fields=['product_requirement_evidence', 'revision', 'updated_at'])
    _record_event(
        application, 'signing_requirements_saved', actor=actor, request_id=request_id,
        after={'requirement_keys': sorted(signing_keys)},
    )
    return application


@transaction.atomic
def submit_for_review(*, application_id, actor, expected_revision: int, request_id: str) -> LoanOriginationApplication:
    request_id = _require_request_id(request_id)
    application = LoanOriginationApplication.objects.select_for_update().select_related('product_definition').get(pk=application_id)
    if request_id and application.events.filter(request_id=request_id).exists():
        return application
    if application.officer_id != actor.pk:
        raise OriginationError('Only the assigned officer may submit this application.')
    if int(expected_revision) != application.revision:
        raise OriginationConflict('This application changed on another device. Refresh before submitting.')
    if application.status not in {LoanOriginationApplication.STATUS_DRAFT, LoanOriginationApplication.STATUS_CORRECTION_REQUIRED}:
        raise OriginationError('This application cannot be submitted from its current state.')
    if not _payload_has_value(application.form_payload):
        raise OriginationError('Enter the Applicant details before submitting this application.')
    result = validate_form_payload(application.schema_snapshot, application.form_payload, require_complete=True)
    if not result.valid:
        raise OriginationError(
            'Complete all required application fields before review.', errors=result.errors,
        )
    if application.schema_snapshot.get('identity_contract') == APPLICANT_IDENTITY_CONTRACT:
        identity = applicant_identity_snapshot(application.form_payload)
        identity_errors = {
            key: 'This Applicant identity value is required.'
            for key, value in identity.items() if not value
        }
        if identity_errors:
            raise OriginationError(
                'Complete the Applicant name, National ID, and telephone before review.',
                errors=identity_errors,
            )
    if application.primary_previewed_revision != application.revision and not application.events.filter(
        action='document_previewed', revision=application.revision,
    ).exists():
        raise OriginationError('Preview the filled document for this saved revision before submitting.')
    if application.packet_documents.exists():
        from core.services.origination_documents import serialize_packet
        packet = serialize_packet(application)
        if not packet['ready']:
            raise OriginationError(
                'Complete and preview every selected supporting document before submitting.',
            )
    missing = _missing_application_requirements(application, stage='review')
    if missing:
        raise OriginationError(
            'Complete required product evidence before review: ' + ', '.join(item['label'] for item in missing),
            errors={f"requirement:{item['key']}": 'Required before review' for item in missing},
        )
    application.status = LoanOriginationApplication.STATUS_READY_FOR_REVIEW
    application.revision += 1
    application.submitted_at = timezone.now()
    application.save(update_fields=['status', 'revision', 'submitted_at', 'updated_at'])
    application.correction_requests.filter(status='open').update(
        status='addressed', addressed_by=actor, addressed_at=timezone.now(),
    )
    _record_event(application, 'submitted_for_review', actor=actor, request_id=request_id)
    return application


@transaction.atomic
def review_application(
    *, application_id, actor, expected_revision: int, request_id: str,
    decision: str, reason: str = '', correction_items: Any = None,
) -> LoanOriginationApplication:
    request_id = _require_request_id(request_id)
    application = LoanOriginationApplication.objects.select_for_update().select_related('product_definition').get(pk=application_id)
    if request_id and application.events.filter(request_id=request_id).exists():
        return application
    if int(expected_revision) != application.revision:
        raise OriginationConflict('This application changed on another device. Refresh before reviewing.')
    if application.status != LoanOriginationApplication.STATUS_READY_FOR_REVIEW:
        raise OriginationError('This application is not ready for review.')
    if application.recheck_assigned_to_id and application.recheck_assigned_to_id != actor.pk:
        raise OriginationError(
            'This corrected application is assigned to its original checker. Take it over explicitly before reviewing.',
        )
    normalized = str(decision or '').strip().casefold()
    if normalized not in {'approve', 'request_correction', 'decline'}:
        raise OriginationError('Choose approve, request_correction, or decline.')
    if application.officer_id == actor.pk and not getattr(actor, 'is_superuser', False):
        raise OriginationError('The submitting officer cannot review their own application.')
    reason = str(reason or '').strip()
    if normalized != 'approve' and not reason:
        raise OriginationError('A reason is required for corrections or decline.')
    normalized_items: list[dict[str, str]] = []
    if normalized == 'request_correction':
        if not isinstance(correction_items, list) or not correction_items:
            raise OriginationError('Select at least one field or requirement to correct.')
        field_labels = {
            str(item.get('key') or ''): str(item.get('label') or item.get('key') or '')
            for item in _schema_fields(application.schema_snapshot)
        }
        requirement_labels = {
            str(item.get('key') or ''): str(item.get('label') or item.get('key') or '')
            for item in (application.product_terms_snapshot or {}).get('requirements', [])
            if isinstance(item, dict)
            and (not item.get('workflow') or item.get('workflow') == 'loan_origination')
        }
        document_field_labels = {}
        for document in application.packet_documents.filter(selected=True).exclude(document_role='primary'):
            for item in (document.schema_snapshot or {}).get('fields', []):
                if not isinstance(item, dict) or not item.get('key'):
                    continue
                field_key = str(item['key'])
                base_key = f'{document.document_key}.{field_key}'
                label = f'{document.name}: {item.get("label") or field_key}'
                document_field_labels[base_key] = label
        seen = set()
        for raw in correction_items:
            if not isinstance(raw, dict):
                raise OriginationError('Every correction target must be an object.')
            target_type = str(raw.get('target_type') or '').strip()
            target_key = str(raw.get('target_key') or '').strip()
            labels = (
                field_labels if target_type == 'field' else
                requirement_labels if target_type == 'requirement' else
                document_field_labels if target_type == 'document_field' else {}
            )
            if not target_key or target_key not in labels:
                raise OriginationError('One or more correction targets are not part of this application.')
            identity = (target_type, target_key)
            if identity in seen:
                raise OriginationError('Correction targets cannot be duplicated.')
            seen.add(identity)
            normalized_items.append({
                'target_type': target_type,
                'target_key': target_key[:240],
                'target_label': labels[target_key][:160],
                'instruction': str(raw.get('instruction') or '').strip()[:1000],
            })
    status_by_decision = {
        'approve': LoanOriginationApplication.STATUS_REVIEWED,
        'request_correction': LoanOriginationApplication.STATUS_CORRECTION_REQUIRED,
        'decline': LoanOriginationApplication.STATUS_DECLINED,
    }
    before = {'status': application.status, 'revision': application.revision}
    if normalized == 'request_correction':
        from core.models import OriginationCorrectionItem, OriginationCorrectionRequest
        correction = OriginationCorrectionRequest.objects.create(
            application=application,
            application_revision=application.revision,
            reviewer=actor,
            summary=reason[:2000],
        )
        OriginationCorrectionItem.objects.bulk_create([
            OriginationCorrectionItem(correction_request=correction, **item)
            for item in normalized_items
        ])
        application.recheck_assigned_to = actor
    elif normalized in {'approve', 'decline'}:
        application.recheck_assigned_to = None
    application.status = status_by_decision[normalized]
    application.revision += 1
    application.reviewed_by = actor
    application.reviewed_at = timezone.now()
    application.save(update_fields=[
        'status', 'revision', 'reviewed_by', 'reviewed_at',
        'recheck_assigned_to', 'updated_at',
    ])
    _record_event(
        application, f'review_{normalized}', actor=actor, request_id=request_id,
        before=before, after={'reason': reason} if reason else {},
    )
    return application


@transaction.atomic
def take_over_correction_review(
    *, application_id, actor, expected_revision: int, request_id: str, reason: str,
) -> LoanOriginationApplication:
    request_id = _require_request_id(request_id)
    application = LoanOriginationApplication.objects.select_for_update().get(pk=application_id)
    if application.events.filter(request_id=request_id).exists():
        return application
    if int(expected_revision) != application.revision:
        raise OriginationConflict('This application changed. Refresh before taking over its review.')
    if application.status != LoanOriginationApplication.STATUS_READY_FOR_REVIEW or not application.recheck_assigned_to_id:
        raise OriginationError('This application is not waiting for an assigned correction re-check.')
    if application.officer_id == actor.pk and not getattr(actor, 'is_superuser', False):
        raise OriginationError('The submitting officer cannot take over their own application review.')
    reason = str(reason or '').strip()
    if not reason:
        raise OriginationError('Give a reason for taking over this correction review.')
    previous_id = application.recheck_assigned_to_id
    if previous_id == actor.pk:
        return application
    application.recheck_assigned_to = actor
    application.revision += 1
    application.save(update_fields=['recheck_assigned_to', 'revision', 'updated_at'])
    _record_event(
        application, 'correction_review_taken_over', actor=actor, request_id=request_id,
        before={'reviewer_id': previous_id},
        after={'reviewer_id': actor.pk, 'reason': reason[:1000]},
    )
    return application


@transaction.atomic
def prepare_signing_package(
    *, application_id, actor, expected_revision: int, request_id: str,
) -> tuple[OriginationSigningPackage, bool]:
    """Freeze a reviewed revision locally; this deliberately performs no remote dispatch."""
    request_id = _require_request_id(request_id)
    application = LoanOriginationApplication.objects.select_for_update().select_related('product_definition').get(pk=application_id)
    if application.status == LoanOriginationApplication.STATUS_SIGNING_PENDING:
        existing = application.signing_packages.order_by('-created_at').first()
        if existing:
            from core.services.origination_fields import project_reporting_values
            project_reporting_values(application)
            return existing, True
    existing = OriginationSigningPackage.objects.filter(
        application=application, application_revision=application.revision,
    ).first()
    if existing:
        from core.services.origination_fields import project_reporting_values
        project_reporting_values(application)
        return existing, True
    if int(expected_revision) != application.revision:
        raise OriginationConflict('This application changed on another device. Refresh before preparing signing.')
    if application.status != LoanOriginationApplication.STATUS_REVIEWED:
        raise OriginationError('Only a reviewed application can be prepared for signing.')
    missing = _missing_application_requirements(application, stage='signing')
    if missing:
        raise OriginationError(
            'Complete required product evidence before signing: ' + ', '.join(item['label'] for item in missing),
            errors={f"requirement:{item['key']}": 'Required before signing' for item in missing},
        )
    package_id = uuid.uuid4()
    from core.services.origination_evidence import evidence_manifest
    from core.services.origination_documents import packet_signers, render_packet
    packet_pdf, document_manifest = (
        render_packet(application) if application.packet_documents.exists() else (b'', [])
    )
    packet_hash = hashlib.sha256(packet_pdf).hexdigest() if packet_pdf else ''
    from core.services.origination_signing import test_signing_enabled
    package = OriginationSigningPackage.objects.create(
        id=package_id,
        application=application,
        application_revision=application.revision,
        external_reference=f'ESIGN-{str(package_id)[:12].upper()}',
        document_type=application.product_definition.document_type,
        template_version=application.product_definition.document_template_version,
        template_sha256=application.product_definition.document_template_sha256,
        template_configuration_snapshot=application.template_configuration_snapshot,
        context_snapshot=preview_context(application),
        participants_snapshot=packet_signers(application),
        requirement_evidence_snapshot=evidence_manifest(application),
        document_manifest_snapshot=document_manifest,
        combined_document_hash=packet_hash,
        unsigned_document_hash=packet_hash,
        test_mode=test_signing_enabled(),
    )
    from core.services.origination_fields import project_reporting_values
    project_reporting_values(application)
    application.status = LoanOriginationApplication.STATUS_SIGNING_PENDING
    application.revision += 1
    application.save(update_fields=['status', 'revision', 'updated_at'])
    _record_event(
        application, 'signing_prepared', actor=actor, request_id=request_id,
        after={'signing_package_id': str(package.pk)},
    )
    return package, False


def _masked_form_payload(application: LoanOriginationApplication) -> dict[str, Any]:
    fields = {
        str(item.get('key') or ''): item
        for item in _schema_fields(application.schema_snapshot)
    }
    masked = {}
    for key, value in (application.form_payload or {}).items():
        policy = str(fields.get(key, {}).get('masking_policy') or 'full')
        if value in (None, '') or policy == 'none':
            masked[key] = value
        elif policy == 'partial':
            text = str(value)
            masked[key] = f'••••{text[-4:]}' if len(text) > 4 else '••••'
        else:
            masked[key] = '••••'
    return masked


def _serialize_correction(application: LoanOriginationApplication) -> dict[str, Any] | None:
    correction = application.correction_requests.filter(status='open').prefetch_related('items').first()
    if not correction:
        return None
    return {
        'id': str(correction.pk),
        'summary': correction.summary,
        'created_at': correction.created_at.isoformat(),
        'items': [
            {
                'target_type': item.target_type,
                'target_key': item.target_key,
                'target_label': item.target_label,
                'instruction': item.instruction,
            }
            for item in correction.items.all()
        ],
    }


def _mask_queue_identifier(value: Any, *, visible_end: int = 4) -> str:
    text = str(value or '').strip()
    if not text:
        return ''
    if len(text) <= visible_end:
        return '•' * len(text)
    return f'{"•" * (len(text) - visible_end)}{text[-visible_end:]}'


def serialize_application(
    application: LoanOriginationApplication, *, include_payload: bool = True,
    presentation: str = 'full',
) -> dict[str, Any]:
    payload = {
        'id': str(application.pk), 'reference_number': application.reference_number,
        'product_key': application.product_definition.product_key,
        'product_name': application.product_definition.name,
        'product_version': application.product_definition.version,
        'global_product_id': application.product_version.product_id if application.product_version_id else None,
        'global_product_version_id': str(application.product_version_id or ''),
        'branch': application.branch, 'status': application.status,
        'revision': application.revision, 'updated_at': application.updated_at.isoformat(),
        'officer_id': application.officer_id,
        'officer_name': application.officer.get_full_name() or application.officer.get_username(),
        'recheck_assigned_to_id': application.recheck_assigned_to_id,
        'recheck_assigned_to_name': (
            application.recheck_assigned_to.get_full_name()
            or application.recheck_assigned_to.get_username()
            if application.recheck_assigned_to_id else ''
        ),
    }
    identity = application.identity_snapshot or applicant_identity_snapshot(application.form_payload)
    payload['applicant_summary'] = {
        'name': str(identity.get('name') or '').strip(),
        'national_id': _mask_queue_identifier(identity.get('national_id')),
        'phone': _mask_queue_identifier(identity.get('phone')),
    }
    if include_payload:
        from core.services.origination_evidence import serialize_evidence
        evidence = [] if presentation == 'masked' else [
            serialize_evidence(item)
            for item in application.requirement_evidence_files.exclude(status='removed')
        ]
        payload.update({
            'form_payload': (
                _masked_form_payload(application)
                if presentation == 'masked' else application.form_payload
            ),
            'form_schema': application.schema_snapshot,
            'product_terms': application.product_terms_snapshot,
            'product_quote': application.product_quote_snapshot,
            'product_requirements': (
                {} if presentation == 'masked' else application.product_requirement_evidence
            ),
            'product_custom_values': (
                {} if presentation == 'masked' else application.product_custom_values
            ),
            'product_selected_fee_keys': application.product_selected_fee_keys,
            'requirement_evidence': evidence,
            'active_correction': _serialize_correction(application),
            'presentation': presentation,
        })
        from core.services.origination_documents import serialize_packet
        payload['document_packet'] = serialize_packet(application)
        package = application.signing_packages.order_by('-created_at').first()
        if package:
            from core.services.origination_signing import active_test_stamps, serialize_test_signing
            payload['signing_package'] = {
                'id': str(package.pk), 'reference': package.external_reference,
                'status': package.status,
                'test_signing': serialize_test_signing(package),
                'test_stamps': active_test_stamps(application) if package.test_mode else [],
            }
        else:
            payload['signing_package'] = None
    return payload
