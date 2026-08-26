"""Governed officer-entered commercial terms for Loan Origination.

The legal form values are authoritative.  ``ProductVersion`` is an immutable
validation envelope and quote reference; it must never silently replace what
the officer entered on the application.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, DecimalException, InvalidOperation, ROUND_HALF_UP
from typing import Any

from django.db import transaction

from core.models import OriginationDataField, OriginationDataFieldEvent, ProductFee


CENT = Decimal('0.01')
MONEY_MAX = Decimal('999999999999.99')
RATE_MAX = Decimal('999.999999')
COMMERCIAL_SECTION_KEY = 'commercial_terms'
COMMERCIAL_CONTRACT_VERSION = 2

TENOR_OPTIONS = ({'code': 'week', 'label': 'Weeks'}, {'code': 'month', 'label': 'Months'})
INTEREST_METHOD_OPTIONS = (
    {'code': 'flat', 'label': 'Flat rate'},
    {'code': 'reducing', 'label': 'Reducing balance'},
)
RATE_PERIOD_OPTIONS = ({'code': 'monthly', 'label': 'Monthly'}, {'code': 'annual', 'label': 'Annual'})
FREQUENCY_OPTIONS = (
    {'code': 'weekly', 'label': 'Weekly'},
    {'code': 'fortnightly', 'label': 'Fortnightly'},
    {'code': 'monthly', 'label': 'Monthly'},
)

LOAN_FEES_STRUCTURE = {
    'min_items': 0,
    'max_items': 20,
    'columns': [
        {'key': 'fee_key', 'label': 'Fee', 'type': 'text', 'required': True,
         'validation': {'max_length': 80}, 'editable': False},
        {'key': 'fee_label', 'label': 'Fee label', 'type': 'text', 'required': True,
         'validation': {'max_length': 160}, 'editable': False},
        {'key': 'collection_mode', 'label': 'Collection', 'type': 'choice', 'required': True,
         'options': [
             {'code': 'upfront', 'label': 'Upfront'},
             {'code': 'financed', 'label': 'Financed'},
         ], 'editable': False},
        {'key': 'amount', 'label': 'Amount', 'type': 'money', 'required': True,
         'validation': {'min': '0'}},
    ],
}


FIELD_SPECS = (
    ('loan_amount', 'Loan Amount', 'money', True, (), {'min': '0', 'max': str(MONEY_MAX)}, 'metric'),
    ('repayment_tenor', 'Repayment Tenor', 'number', True, (), {'min': '1'}, 'dimension'),
    ('repayment_tenor_unit', 'Tenor Unit', 'choice', True, TENOR_OPTIONS, {}, 'dimension'),
    ('contract_currency', 'Currency', 'choice', True, ({'code': 'kes', 'label': 'KES'},), {}, 'dimension'),
    ('contract_interest_rate_percent', 'Interest Rate (%)', 'number', True, (), {'min': '0', 'max': str(RATE_MAX)}, 'metric'),
    ('contract_interest_method', 'Interest Method', 'choice', True, INTEREST_METHOD_OPTIONS, {}, 'dimension'),
    ('contract_interest_rate_period', 'Interest Rate Period', 'choice', True, RATE_PERIOD_OPTIONS, {}, 'dimension'),
    ('contract_repayment_frequency', 'Repayment Frequency', 'choice', True, FREQUENCY_OPTIONS, {}, 'dimension'),
    ('installment_count', 'Number of Installments', 'number', True, (), {'min': '1'}, 'metric'),
    ('installment_amount', 'Regular Installment Amount', 'money', True, (), {'min': '0', 'max': str(MONEY_MAX)}, 'metric'),
    ('final_installment_amount', 'Final Installment Amount', 'money', True, (), {'min': '0', 'max': str(MONEY_MAX)}, 'metric'),
    ('financed_principal_amount', 'Financed Principal', 'money', True, (), {'min': '0', 'max': str(MONEY_MAX)}, 'metric'),
    ('total_interest_amount', 'Total Interest', 'money', True, (), {'min': '0', 'max': str(MONEY_MAX)}, 'metric'),
    ('total_repayment_amount', 'Total Repayment', 'money', True, (), {'min': '0', 'max': str(MONEY_MAX)}, 'metric'),
    ('financed_fee_total', 'Financed Fees Total', 'money', True, (), {'min': '0', 'max': str(MONEY_MAX)}, 'metric'),
    ('upfront_fee_total', 'Upfront Fees Total', 'money', True, (), {'min': '0', 'max': str(MONEY_MAX)}, 'metric'),
    ('loan_fees', 'Loan Fees', 'repeating_group', False, (), {}, 'unavailable'),
)

COMMERCIAL_KEYS = tuple(item[0] for item in FIELD_SPECS)
COMMERCIAL_INPUT_KEYS = ('loan_amount', 'repayment_tenor')
COMMERCIAL_DERIVED_KEYS = tuple(
    key for key in COMMERCIAL_KEYS if key not in COMMERCIAL_INPUT_KEYS
)
MONEY_KEYS = {
    'loan_amount', 'installment_amount', 'final_installment_amount',
    'financed_principal_amount', 'total_interest_amount',
    'total_repayment_amount', 'financed_fee_total', 'upfront_fee_total',
}


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=str,
    ).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def commercial_contract_enabled(schema: Any) -> bool:
    return isinstance(schema, dict) and any(
        isinstance(item, dict) and item.get('key') == 'repayment_tenor'
        for item in schema.get('fields', [])
    )


def commercial_contract_version(schema: Any) -> int:
    if not commercial_contract_enabled(schema):
        return 0
    try:
        return int(schema.get('commercial_contract_version') or 1)
    except (TypeError, ValueError):
        return 1


def ensure_commercial_catalogue(*, actor=None) -> dict[str, OriginationDataField]:
    """Idempotently ensure the future-input catalogue; never rewrites key/type."""
    resolved = {}
    for key, label, data_type, _required, options, _validation, reporting in FIELD_SPECS:
        is_input = key in COMMERCIAL_INPUT_KEYS
        defaults = {
            'label': label,
            'category': 'Commercial Terms',
            'data_type': data_type,
            'source_type': (
                OriginationDataField.SOURCE_USER_INPUT
                if is_input else OriginationDataField.SOURCE_SYSTEM
            ),
            'sensitivity': OriginationDataField.SENSITIVITY_FINANCIAL,
            'masking_policy': OriginationDataField.MASK_PARTIAL,
            'reporting_use': reporting,
            'export_allowed': False,
            'help_text': (
                'Enter the exact commercial value requested for this application.'
                if is_input else
                'Calculated from the immutable product policy and application amount and tenor.'
            ),
            'choice_options': list(options),
            'structure_schema': LOAN_FEES_STRUCTURE if key == 'loan_fees' else {},
            'active': True,
            'created_by': actor,
        }
        field = OriginationDataField.objects.filter(key=key).first()
        created = field is None
        if created:
            field = OriginationDataField.objects.create(key=key, **defaults)
        else:
            if field.data_type != data_type:
                raise ValueError(f'Canonical field {key} must use type {data_type}, not {field.data_type}.')
            changed = []
            # Existing semantic labels/reporting governance may be deliberately
            # curated.  Only enforce what the contractual input path requires.
            for attr in ('source_type', 'sensitivity', 'active'):
                if getattr(field, attr) != defaults[attr]:
                    setattr(field, attr, defaults[attr])
                    changed.append(attr)
            if data_type == OriginationDataField.TYPE_CHOICE:
                existing_codes = {str(item.get('code') or '') for item in field.choice_options or []}
                merged = list(field.choice_options or [])
                for option in options:
                    if option['code'] not in existing_codes:
                        merged.append(dict(option))
                        changed.append('choice_options')
                field.choice_options = merged
            if data_type == OriginationDataField.TYPE_REPEATING_GROUP and not field.structure_schema:
                field.structure_schema = json.loads(json.dumps(LOAN_FEES_STRUCTURE))
                changed.append('structure_schema')
            if changed:
                field.save()
        if created:
            OriginationDataFieldEvent.objects.create(
                data_field=field, action='commercial_contract_seeded', actor=actor,
                metadata={'key': key, 'contract_version': COMMERCIAL_CONTRACT_VERSION},
            )
        resolved[key] = field
    return resolved


def merge_commercial_contract(schema: Any, *, fields=None) -> dict[str, Any]:
    """Return an idempotently upgraded draft schema; callers decide persistence."""
    from core.services.origination_fields import _field_schema_item

    original = json.loads(json.dumps(schema or {}))
    upgraded = json.loads(json.dumps(schema or {}))
    upgraded.setdefault('_revision', 0)
    upgraded['commercial_contract_version'] = COMMERCIAL_CONTRACT_VERSION
    sections = [item for item in upgraded.get('sections', []) if isinstance(item, dict)]
    section_keys = {str(item.get('key') or '') for item in sections}
    target_section = str(upgraded.get('commercial_section_key') or '').strip()
    if target_section not in section_keys:
        target_section = next(
            (key for key in ('loan_details', 'invoice_details', 'facility_details') if key in section_keys),
            COMMERCIAL_SECTION_KEY,
        )
    upgraded['commercial_section_key'] = target_section
    if target_section == COMMERCIAL_SECTION_KEY and COMMERCIAL_SECTION_KEY not in section_keys:
        sections.append({
            'key': COMMERCIAL_SECTION_KEY,
            'label': 'Commercial Terms',
            'help_text': (
                'Enter the requested loan amount and repayment tenor. '
                'The published product policy calculates the read-only quote.'
            ),
        })
    elif target_section != COMMERCIAL_SECTION_KEY:
        sections = [item for item in sections if item.get('key') != COMMERCIAL_SECTION_KEY]
    upgraded['sections'] = sections
    current = [
        item for item in upgraded.get('fields', [])
        if isinstance(item, dict) and str(item.get('key') or '') not in COMMERCIAL_KEYS
    ]
    by_key = {str(item.get('key') or ''): item for item in current}
    fields = fields or {item.key: item for item in OriginationDataField.objects.filter(key__in=COMMERCIAL_KEYS)}
    commercial_inputs = []
    for key, _label, _data_type, required, _options, validation, _reporting in FIELD_SPECS:
        if key not in COMMERCIAL_INPUT_KEYS:
            continue
        if key not in fields:
            raise ValueError(f'Canonical commercial field {key} is not available.')
        replacement = _field_schema_item(fields[key], {
            'section_key': target_section,
            'required': required,
            'width': 'full' if key == 'loan_fees' else 'half',
            'validation': validation,
            'options': list(_options),
            'structure': LOAN_FEES_STRUCTURE if key == 'loan_fees' else {},
        })
        commercial_inputs.append({**by_key.get(key, {}), **replacement})
    # Derived and legacy commercial variables remain in the global catalogue
    # for PDF mapping, but are not presented as officer inputs in v2 schemas.
    legacy = {'repayment_period', 'interest_rate', 'repayment_frequency', 'daily_weekly_repayment_amount'}
    current = [
        item for item in current
        if str(item.get('key') or '') not in legacy | set(COMMERCIAL_INPUT_KEYS)
    ]
    insertion = next(
        (index for index, item in enumerate(current) if item.get('section_key') == target_section),
        len(current),
    )
    upgraded['fields'] = current[:insertion] + commercial_inputs + current[insertion:]
    original_comparable = {key: value for key, value in original.items() if key != '_revision'}
    upgraded_comparable = {key: value for key, value in upgraded.items() if key != '_revision'}
    upgraded['_revision'] = (
        int(original.get('_revision') or 0)
        if original_comparable == upgraded_comparable
        else int(original.get('_revision') or 0) + 1
    )
    return upgraded


def initial_fee_rows(product_version) -> list[dict[str, Any]]:
    if not product_version:
        return []
    return [
        {
            'row_id': str(fee.pk),
            'fee_key': fee.key,
            'fee_label': fee.label,
            'collection_mode': fee.collection_mode,
            'amount': '',
        }
        for fee in product_version.fees.all().order_by('position', 'id')
    ]


def _decimal(payload: dict[str, Any], key: str) -> Decimal | None:
    value = payload.get(key)
    if value in (None, ''):
        return None
    try:
        result = Decimal(str(value).replace(',', '').strip())
    except (InvalidOperation, AttributeError, ValueError):
        return None
    return result if result.is_finite() else None


def _money_equal(left: Decimal | None, right: Decimal | None) -> bool:
    return left is not None and right is not None and abs(left - right) <= CENT


def _finding(code, message, fields, *, category='policy', waivable=True, expected=None, entered=None):
    return {
        'code': code, 'message': message, 'field_keys': list(fields),
        'category': category, 'waivable': bool(waivable),
        'expected': '' if expected is None else str(expected),
        'entered': '' if entered is None else str(entered),
    }


def _entered_snapshot(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: payload.get(key) for key in COMMERCIAL_KEYS}


def _validate_policy_derived_terms(application, payload: dict[str, Any]) -> dict[str, Any]:
    """Validate v2 inputs and derive every other commercial value from policy."""
    entered = {key: payload.get(key) for key in COMMERCIAL_INPUT_KEYS}
    entered_hash = _stable_hash(entered)
    findings = []
    expected_quote = {}

    for key in COMMERCIAL_INPUT_KEYS:
        if payload.get(key) in (None, ''):
            findings.append(_finding(
                f'{key}_required',
                f'{key.replace("_", " ").title()} is required.',
                (key,), category='input', waivable=False,
            ))

    loan_amount = _decimal(payload, 'loan_amount')
    tenor = _decimal(payload, 'repayment_tenor')
    if payload.get('loan_amount') not in (None, ''):
        if loan_amount is None:
            findings.append(_finding(
                'loan_amount_invalid', 'Loan Amount must be a valid number.',
                ('loan_amount',), category='input', waivable=False,
                entered=payload.get('loan_amount'),
            ))
        elif loan_amount < 0:
            findings.append(_finding(
                'loan_amount_negative', 'Loan Amount cannot be negative.',
                ('loan_amount',), category='input', waivable=False, entered=loan_amount,
            ))
        elif loan_amount > MONEY_MAX:
            findings.append(_finding(
                'loan_amount_too_large', 'Loan Amount is too large.',
                ('loan_amount',), category='input', waivable=False, entered=loan_amount,
            ))

    tenor_is_valid = (
        tenor is not None and tenor == tenor.to_integral_value() and tenor >= 1
    )
    if payload.get('repayment_tenor') not in (None, '') and not tenor_is_valid:
        findings.append(_finding(
            'repayment_tenor_invalid',
            'Repayment Tenor must be a positive whole number.',
            ('repayment_tenor',), category='input', waivable=False,
            entered=payload.get('repayment_tenor'),
        ))

    version = application.product_version
    if version:
        from core.models import ProductVersion
        version = ProductVersion.objects.prefetch_related('fees').get(pk=version.pk)
    else:
        findings.append(_finding(
            'commercial_policy_unavailable',
            'This application has no governed product policy for calculating its quote.',
            COMMERCIAL_INPUT_KEYS, category='input', waivable=False,
        ))

    if version and loan_amount is not None and loan_amount >= 0:
        amount_within = loan_amount >= version.min_amount and (
            version.max_amount is None or loan_amount <= version.max_amount
        )
        if not amount_within:
            findings.append(_finding(
                'loan_amount_policy_mismatch',
                'Loan amount is outside the product policy range.',
                ('loan_amount',),
                expected=f'{version.min_amount} - {version.max_amount or "unlimited"}',
                entered=loan_amount,
            ))
    if version and tenor_is_valid:
        if not (version.min_tenor <= tenor <= version.max_tenor):
            findings.append(_finding(
                'repayment_tenor_policy_mismatch',
                'Repayment tenor is outside the product policy range.',
                ('repayment_tenor',),
                expected=f'{version.min_tenor} - {version.max_tenor}', entered=tenor,
            ))

    if version and loan_amount is not None and loan_amount >= 0 and tenor_is_valid:
        from core.services.product_catalog import ProductCatalogError
        from core.services.product_quotes import calculate_product_quote
        try:
            expected_quote = calculate_product_quote(
                version, amount=loan_amount, tenor=int(tenor),
                optional_fee_keys=[], enforce_policy_bounds=False,
            )
        except (ProductCatalogError, DecimalException, OverflowError, ValueError) as exc:
            findings.append(_finding(
                'commercial_quote_calculation_invalid',
                'The amount and tenor cannot produce a safe product quote.',
                COMMERCIAL_INPUT_KEYS, category='input', waivable=False,
                entered=str(exc),
            ))

    expected_hash = _stable_hash(expected_quote)
    policy_codes = [item['code'] for item in findings if item['category'] == 'policy']
    exception = None
    if policy_codes:
        from core.models import OriginationCommercialException
        exception = OriginationCommercialException.objects.filter(
            application=application,
            application_revision=application.revision,
            product_version=application.product_version,
            entered_terms_sha256=entered_hash,
            expected_quote_sha256=expected_hash,
        ).order_by('-approved_at').first()
    covered = set(exception.covered_mismatch_codes if exception else [])
    blocking = [
        item for item in findings
        if not item['waivable'] or item['code'] not in covered
    ]
    return {
        'enabled': True, 'ready': not blocking, 'findings': findings,
        'blocking_findings': blocking, 'policy_mismatch_codes': policy_codes,
        'entered_terms': entered, 'entered_terms_sha256': entered_hash,
        'expected_quote': expected_quote,
        'expected_quote_sha256': expected_hash,
        'exception': ({
            'id': str(exception.pk),
            'covered_mismatch_codes': list(exception.covered_mismatch_codes),
            'approval_reference': exception.approval_reference,
            'approved_at': exception.approved_at.isoformat(),
        } if exception else None),
    }


def validate_commercial_terms(application, *, payload=None, selected_fee_keys=None) -> dict[str, Any]:
    """Compare entered contract terms with arithmetic and the frozen policy."""
    payload = payload if isinstance(payload, dict) else application.form_payload or {}
    if commercial_contract_version(application.schema_snapshot) >= 2:
        return _validate_policy_derived_terms(application, payload)
    selected_fee_keys = list(selected_fee_keys if selected_fee_keys is not None else application.product_selected_fee_keys or [])
    entered = _entered_snapshot(payload)
    entered_hash = _stable_hash(entered)
    findings = []
    expected_quote = {}
    if not commercial_contract_enabled(application.schema_snapshot):
        return {
            'enabled': False, 'ready': True, 'findings': [], 'blocking_findings': [],
            'policy_mismatch_codes': [], 'entered_terms': entered,
            'entered_terms_sha256': entered_hash, 'expected_quote': {},
            'expected_quote_sha256': _stable_hash({}), 'exception': None,
        }

    missing = [key for key in COMMERCIAL_KEYS if key != 'loan_fees' and payload.get(key) in (None, '')]
    if missing:
        findings.append(_finding(
            'commercial_terms_incomplete', 'Complete all required Commercial Terms fields.',
            missing, category='input', waivable=False,
        ))

    numeric_keys = MONEY_KEYS | {
        'repayment_tenor', 'contract_interest_rate_percent', 'installment_count',
    }
    for key in sorted(numeric_keys):
        raw_value = payload.get(key)
        if raw_value in (None, ''):
            continue
        parsed_value = _decimal(payload, key)
        if parsed_value is None:
            findings.append(_finding(
                f'{key}_invalid', f'{key.replace("_", " ").title()} must be a valid number.',
                (key,), category='input', waivable=False, entered=raw_value,
            ))
        elif key in MONEY_KEYS | {'contract_interest_rate_percent'} and parsed_value < 0:
            findings.append(_finding(
                f'{key}_negative', f'{key.replace("_", " ").title()} cannot be negative.',
                (key,), category='input', waivable=False, entered=parsed_value,
            ))
        elif key in MONEY_KEYS and parsed_value > MONEY_MAX:
            findings.append(_finding(
                f'{key}_too_large', f'{key.replace("_", " ").title()} is too large.',
                (key,), category='input', waivable=False, entered=parsed_value,
            ))
        elif key == 'contract_interest_rate_percent' and parsed_value > RATE_MAX:
            findings.append(_finding(
                'contract_interest_rate_percent_too_large',
                'Interest Rate (%) is too large.', (key,), category='input',
                waivable=False, entered=parsed_value,
            ))

    loan_amount = _decimal(payload, 'loan_amount')
    financed_fees = _decimal(payload, 'financed_fee_total')
    upfront_fees = _decimal(payload, 'upfront_fee_total')
    financed_principal = _decimal(payload, 'financed_principal_amount')
    total_interest = _decimal(payload, 'total_interest_amount')
    total_repayment = _decimal(payload, 'total_repayment_amount')
    installment = _decimal(payload, 'installment_amount')
    final_installment = _decimal(payload, 'final_installment_amount')
    installment_count_value = _decimal(payload, 'installment_count')

    fee_rows = payload.get('loan_fees') or []
    if not isinstance(fee_rows, list):
        fee_rows = []
    row_totals = {'financed': Decimal('0'), 'upfront': Decimal('0')}
    entered_fee_by_key = {}
    seen_fee_keys = set()
    for row in fee_rows:
        if not isinstance(row, dict):
            findings.append(_finding(
                'loan_fee_row_invalid', 'Every loan fee must be a structured fee row.',
                ('loan_fees',), category='input', waivable=False,
            ))
            continue
        amount = _decimal(row, 'amount')
        key = str(row.get('fee_key') or '')
        mode = str(row.get('collection_mode') or '')
        raw_amount = row.get('amount')
        if raw_amount not in (None, '') and (amount is None or amount < 0):
            findings.append(_finding(
                'loan_fee_amount_invalid', 'Loan fee amounts must be valid non-negative numbers.',
                ('loan_fees',), category='input', waivable=False, entered=raw_amount,
            ))
        if key and key in seen_fee_keys:
            findings.append(_finding(
                'loan_fee_duplicate', f'The {key} fee appears more than once.',
                ('loan_fees',), category='input', waivable=False, entered=key,
            ))
        if key:
            seen_fee_keys.add(key)
        if key and amount is not None:
            entered_fee_by_key[key] = row
        if amount is not None and mode in row_totals:
            row_totals[mode] += amount
    if financed_fees is not None and not _money_equal(financed_fees, row_totals['financed']):
        findings.append(_finding(
            'financed_fee_total_inconsistent', 'Financed fee total does not equal the financed fee rows.',
            ('loan_fees', 'financed_fee_total'), category='arithmetic', waivable=False,
            expected=row_totals['financed'], entered=financed_fees,
        ))
    if upfront_fees is not None and not _money_equal(upfront_fees, row_totals['upfront']):
        findings.append(_finding(
            'upfront_fee_total_inconsistent', 'Upfront fee total does not equal the upfront fee rows.',
            ('loan_fees', 'upfront_fee_total'), category='arithmetic', waivable=False,
            expected=row_totals['upfront'], entered=upfront_fees,
        ))
    if None not in (loan_amount, financed_fees, financed_principal):
        expected = loan_amount + financed_fees
        if not _money_equal(financed_principal, expected):
            findings.append(_finding(
                'financed_principal_inconsistent', 'Financed principal must equal loan amount plus financed fees.',
                ('loan_amount', 'financed_fee_total', 'financed_principal_amount'),
                category='arithmetic', waivable=False, expected=expected, entered=financed_principal,
            ))
    if None not in (financed_principal, total_interest, total_repayment):
        expected = financed_principal + total_interest
        if not _money_equal(total_repayment, expected):
            findings.append(_finding(
                'total_repayment_inconsistent', 'Total repayment must equal financed principal plus total interest.',
                ('financed_principal_amount', 'total_interest_amount', 'total_repayment_amount'),
                category='arithmetic', waivable=False, expected=expected, entered=total_repayment,
            ))
    if None not in (installment, final_installment, installment_count_value, total_repayment):
        if installment_count_value != installment_count_value.to_integral_value() or installment_count_value < 1:
            findings.append(_finding(
                'installment_count_invalid', 'Number of installments must be a positive whole number.',
                ('installment_count',), category='input', waivable=False,
            ))
        else:
            expected = installment * (installment_count_value - 1) + final_installment
            if not _money_equal(total_repayment, expected):
                findings.append(_finding(
                    'installment_schedule_inconsistent',
                    'Regular installments and the final installment do not reconcile to total repayment.',
                    ('installment_amount', 'installment_count', 'final_installment_amount', 'total_repayment_amount'),
                    category='arithmetic', waivable=False, expected=total_repayment, entered=expected,
                ))

    version = application.product_version
    if version:
        # Normalize Decimal/model values through the database so hashes do not
        # depend on whether the caller holds a just-created or reloaded model.
        from core.models import ProductVersion
        version = ProductVersion.objects.prefetch_related('fees').get(pk=version.pk)
    if version:
        policy_pairs = (
            ('contract_currency', str(version.currency or '').lower(), 'currency_policy_mismatch'),
            ('repayment_tenor_unit', version.tenor_unit, 'tenor_unit_policy_mismatch'),
            ('contract_interest_method', version.interest_method, 'interest_method_policy_mismatch'),
            ('contract_interest_rate_period', version.interest_rate_period, 'interest_period_policy_mismatch'),
            ('contract_repayment_frequency', version.repayment_frequency, 'repayment_frequency_policy_mismatch'),
        )
        for key, expected, code in policy_pairs:
            entered_value = payload.get(key)
            if entered_value not in (None, '') and str(entered_value) != str(expected):
                findings.append(_finding(code, f'{key.replace("_", " ").title()} does not match product policy.', (key,), expected=expected, entered=entered_value))
        rate = _decimal(payload, 'contract_interest_rate_percent')
        if rate is not None and rate <= RATE_MAX and rate.quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP) != Decimal(version.interest_rate).quantize(Decimal('0.000001')):
            findings.append(_finding(
                'interest_rate_policy_mismatch', 'Interest rate does not match product policy.',
                ('contract_interest_rate_percent',), expected=version.interest_rate, entered=rate,
            ))
        tenor = _decimal(payload, 'repayment_tenor')
        amount_within = loan_amount is not None and loan_amount >= version.min_amount and (
            version.max_amount is None or loan_amount <= version.max_amount
        )
        tenor_is_valid = tenor is not None and tenor == tenor.to_integral_value() and tenor >= 1
        if tenor is not None and not tenor_is_valid:
            findings.append(_finding(
                'repayment_tenor_invalid', 'Repayment tenor must be a positive whole number.',
                ('repayment_tenor',), category='input', waivable=False, entered=tenor,
            ))
        tenor_within = tenor_is_valid and version.min_tenor <= tenor <= version.max_tenor
        if loan_amount is not None and not amount_within:
            findings.append(_finding(
                'loan_amount_policy_mismatch', 'Loan amount is outside the product policy range.',
                ('loan_amount',), expected=f'{version.min_amount} - {version.max_amount or "unlimited"}', entered=loan_amount,
            ))
        if tenor is not None and not tenor_within:
            findings.append(_finding(
                'repayment_tenor_policy_mismatch', 'Repayment tenor is outside the product policy range.',
                ('repayment_tenor',), expected=f'{version.min_tenor} - {version.max_tenor}', entered=tenor,
            ))
        if loan_amount is not None and loan_amount >= 0 and tenor_is_valid:
            from core.services.product_catalog import ProductCatalogError
            from core.services.product_quotes import calculate_product_quote
            try:
                expected_quote = calculate_product_quote(
                    version, amount=loan_amount, tenor=int(tenor), optional_fee_keys=selected_fee_keys,
                    enforce_policy_bounds=False,
                )
            except (ProductCatalogError, DecimalException, OverflowError, ValueError) as exc:
                expected_quote = {}
                findings.append(_finding(
                    'commercial_quote_calculation_invalid',
                    'The entered amount and tenor cannot produce a safe policy comparison.',
                    ('loan_amount', 'repayment_tenor'), category='input',
                    waivable=False, entered=str(exc),
                ))
            comparisons = ((
                ('installment_count', Decimal(expected_quote['installment_count']), 'installment_count_policy_mismatch', False),
                ('installment_amount', Decimal(expected_quote['installment_amount']), 'installment_amount_policy_mismatch', True),
                ('final_installment_amount', Decimal(expected_quote['final_installment_amount']), 'final_installment_policy_mismatch', True),
                ('financed_principal_amount', Decimal(expected_quote['financed_principal']), 'financed_principal_policy_mismatch', True),
                ('total_interest_amount', Decimal(expected_quote['interest']), 'total_interest_policy_mismatch', True),
                ('total_repayment_amount', Decimal(expected_quote['total_repayment']), 'total_repayment_policy_mismatch', True),
                ('financed_fee_total', Decimal(expected_quote['financed_fees']), 'financed_fee_policy_mismatch', True),
                ('upfront_fee_total', Decimal(expected_quote['upfront_fees']), 'upfront_fee_policy_mismatch', True),
            ) if expected_quote else ())
            for key, expected, code, money in comparisons:
                actual = _decimal(payload, key)
                matches = _money_equal(actual, expected) if money else actual == expected
                if actual is not None and not matches:
                    findings.append(_finding(code, f'{key.replace("_", " ").title()} does not match product policy.', (key,), expected=expected, entered=actual))
            expected_fees = {row['key']: row for row in expected_quote.get('fees', [])}
            unknown_fees = sorted(set(entered_fee_by_key) - set(expected_fees))
            if unknown_fees:
                findings.append(_finding(
                    'loan_fee_identity_policy_mismatch',
                    'One or more fee rows are not part of the selected product policy.',
                    ('loan_fees',), expected=', '.join(sorted(expected_fees)),
                    entered=', '.join(unknown_fees), category='input', waivable=False,
                ))
            for fee in version.fees.filter(mandatory=True) | version.fees.filter(key__in=selected_fee_keys):
                row = entered_fee_by_key.get(fee.key)
                expected_row = expected_fees.get(fee.key)
                if not row:
                    findings.append(_finding(
                        f'fee_{fee.key}_missing', f'Add the policy fee row for {fee.label}.',
                        ('loan_fees',), expected=fee.key, category='input', waivable=False,
                    ))
                    continue
                if str(row.get('fee_label') or '') != fee.label or str(row.get('collection_mode') or '') != fee.collection_mode:
                    findings.append(_finding(
                        f'fee_{fee.key}_identity_mismatch', f'{fee.label} identity or collection mode does not match policy.',
                        ('loan_fees',), expected=f'{fee.label}/{fee.collection_mode}', entered=f'{row.get("fee_label")}/{row.get("collection_mode")}',
                        category='input', waivable=False,
                    ))
                expected_amount = Decimal(expected_row['amount']) if expected_row else None
                actual_amount = _decimal(row, 'amount')
                if expected_amount is not None and not _money_equal(actual_amount, expected_amount):
                    findings.append(_finding(
                        f'fee_{fee.key}_amount_mismatch', f'{fee.label} amount does not match product policy.',
                        ('loan_fees',), expected=expected_amount, entered=actual_amount,
                    ))

    expected_hash = _stable_hash(expected_quote)
    policy_codes = [item['code'] for item in findings if item['category'] == 'policy']
    exception = None
    if policy_codes:
        from core.models import OriginationCommercialException
        exception = OriginationCommercialException.objects.filter(
            application=application,
            application_revision=application.revision,
            product_version=application.product_version,
            entered_terms_sha256=entered_hash,
            expected_quote_sha256=expected_hash,
        ).order_by('-approved_at').first()
    covered = set(exception.covered_mismatch_codes if exception else [])
    blocking = [
        item for item in findings
        if not item['waivable'] or item['code'] not in covered
    ]
    return {
        'enabled': True, 'ready': not blocking, 'findings': findings,
        'blocking_findings': blocking, 'policy_mismatch_codes': policy_codes,
        'entered_terms': entered, 'entered_terms_sha256': entered_hash,
        'expected_quote': expected_quote, 'expected_quote_sha256': expected_hash,
        'exception': ({
            'id': str(exception.pk), 'covered_mismatch_codes': list(exception.covered_mismatch_codes),
            'approval_reference': exception.approval_reference,
            'approved_at': exception.approved_at.isoformat(),
        } if exception else None),
    }


def quote_snapshot(validation: dict[str, Any]) -> dict[str, Any]:
    return {
        **(validation.get('expected_quote') or {}),
        'commercial_validation': {
            'contract_version': COMMERCIAL_CONTRACT_VERSION,
            'ready': validation.get('ready', False),
            'findings': validation.get('findings', []),
            'blocking_findings': validation.get('blocking_findings', []),
            'entered_terms_sha256': validation.get('entered_terms_sha256', ''),
            'expected_quote_sha256': validation.get('expected_quote_sha256', ''),
            'exception': validation.get('exception'),
        },
    }


@transaction.atomic
def approve_commercial_exception(*, application, actor, reason: str, approval_reference: str):
    from core.models import LoanOriginationApplication, OriginationCommercialException

    if not getattr(actor, 'is_active', False) or not getattr(actor, 'is_superuser', False):
        raise ValueError('Only an active Django Superuser may approve a commercial exception.')
    reason = str(reason or '').strip()
    approval_reference = str(approval_reference or '').strip()
    if not reason or not approval_reference:
        raise ValueError('A reason and external approval reference are required.')
    # ``product_version`` is nullable for legacy applications. Lock only the
    # application row so PostgreSQL does not apply FOR UPDATE to an outer join.
    application = LoanOriginationApplication.objects.select_for_update().get(pk=application.pk)
    if application.status not in {application.STATUS_DRAFT, application.STATUS_CORRECTION_REQUIRED}:
        raise ValueError('Commercial exceptions can only be approved for an editable application revision.')
    validation = validate_commercial_terms(application)
    if any(not item['waivable'] for item in validation['blocking_findings']):
        raise ValueError('Fix invalid or internally inconsistent terms before approving a policy exception.')
    codes = sorted(set(validation['policy_mismatch_codes']))
    if not codes:
        raise ValueError('This application has no commercial policy mismatch to approve.')
    exception, _created = OriginationCommercialException.objects.get_or_create(
        application=application,
        application_revision=application.revision,
        product_version=application.product_version,
        entered_terms_sha256=validation['entered_terms_sha256'],
        expected_quote_sha256=validation['expected_quote_sha256'],
        defaults={
            'covered_mismatch_codes': codes, 'reason': reason[:2000],
            'approval_reference': approval_reference[:255], 'approved_by': actor,
        },
    )
    return exception
