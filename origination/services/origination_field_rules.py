"""Small, snapshot-owned field rules shared by authoring and application validation.

These rules describe input, not lending eligibility. Never infer new rules while
reading an existing application: reviewed rules are attached before publication.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
import re
from typing import Any

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.utils import timezone


RULE_KEYS = frozenset({
    'min', 'max', 'min_length', 'max_length', 'pattern', 'min_date', 'max_date',
    'format', 'integer', 'decimal_places', 'no_future', 'parent_field',
})


def validate_rules(field: dict[str, Any]) -> None:
    """Reject invalid authoring metadata before it can be published."""
    rules = field.get('validation') or {}
    if not isinstance(rules, dict):
        raise ValueError('Validation rules must be an object.')
    kind = field.get('type', 'text')
    if rules.get('format') not in (None, '', 'email'):
        raise ValueError('Choose a supported input format.')
    if rules.get('format') == 'email' and kind != 'text':
        raise ValueError('Email format requires a text field.')
    for flag in ('integer', 'no_future'):
        if flag in rules and not isinstance(rules[flag], bool):
            raise ValueError('Use Yes or No for this validation rule.')
    if rules.get('integer') and kind not in {'number', 'money'}:
        raise ValueError('Whole-number validation requires a numeric field.')
    if rules.get('no_future') and kind != 'date':
        raise ValueError('Future-date validation requires a date field.')
    if 'decimal_places' in rules:
        places = rules['decimal_places']
        if isinstance(places, bool) or not isinstance(places, int) or not 0 <= places <= 4:
            raise ValueError('Choose between 0 and 4 decimal places.')
        if kind not in {'number', 'money'}:
            raise ValueError('Decimal-place validation requires a numeric field.')
    if rules.get('parent_field') and (
        kind != 'sub_county' or not re.fullmatch(r'[a-z0-9_]+', str(rules['parent_field']))
    ):
        raise ValueError('Choose the county field for this sub-county.')
    for bound in ('min', 'max'):
        if rules.get(bound) not in (None, ''):
            if kind not in {'number', 'money'}:
                raise ValueError('Numeric limits require a numeric field.')
            try:
                if not Decimal(str(rules[bound])).is_finite():
                    raise ValueError('Numeric limits must be finite.')
            except InvalidOperation as exc:
                raise ValueError('Enter a valid numeric limit.') from exc
    for bound in ('min_length', 'max_length'):
        if bound in rules and kind not in {'text', 'textarea', 'phone', 'national_id'}:
            raise ValueError('Character limits require a text field.')
        if bound in rules and (isinstance(rules[bound], bool) or not isinstance(rules[bound], int) or rules[bound] < 0):
            raise ValueError('Character limits must be non-negative whole numbers.')
    for bound in ('min_date', 'max_date'):
        if rules.get(bound):
            if kind != 'date' or not isinstance(rules[bound], str):
                raise ValueError('Date limits require a date field and an ISO date.')
            date.fromisoformat(rules[bound])
    pattern = str(rules.get('pattern') or '')
    if pattern and kind not in {'text', 'textarea', 'phone', 'national_id'}:
        raise ValueError('An input pattern requires a text field.')
    if len(pattern) > 200:
        raise ValueError('The input pattern is too long.')
    try:
        re.compile(pattern)
    except re.error as exc:
        raise ValueError('Enter a valid input pattern.') from exc
    # Reuse intersection checking for contradictory limits on a single field.
    merge_rules({}, rules)


def value_error(field: dict[str, Any], value: Any) -> str:
    """Additional typed rules; the existing validator owns completeness and limits."""
    if value is None or value == '':
        return ''
    rules = field.get('validation') or {}
    kind = field.get('type', 'text')
    if kind == 'boolean' and not isinstance(value, bool):
        return 'Choose yes or no.'
    if kind in {'text', 'textarea', 'phone', 'national_id', 'date', 'choice', 'branch', 'county', 'sub_county'} and not isinstance(value, str):
        return 'Enter a valid text value.'
    if rules.get('format') == 'email':
        try:
            validate_email(value)
        except ValidationError:
            return 'Enter a valid email address.'
    if kind in {'money', 'number'}:
        try:
            if isinstance(value, bool):
                raise InvalidOperation
            number = Decimal(str(value))
            if not number.is_finite():
                raise InvalidOperation
            if rules.get('integer') and number != number.to_integral_value():
                return 'Enter a whole number.'
            places = rules.get('decimal_places')
            if places is not None and max(-number.normalize().as_tuple().exponent, 0) > places:
                return f'Use no more than {places} decimal places.'
        except (InvalidOperation, TypeError, ValueError):
            return 'Enter a valid number.'
    if kind == 'date' and rules.get('no_future'):
        try:
            if date.fromisoformat(value) > timezone.localdate():
                return 'Choose today or an earlier date.'
        except ValueError:
            return 'Enter a valid date.'
    if kind == 'choice':
        allowed = {str(option.get('code')) if isinstance(option, dict) else str(option)
                   for option in field.get('options', [])
                   if not isinstance(option, dict) or option.get('active', True)}
        if value not in allowed:
            return 'Choose an available option.'
    return ''


def merge_rules(first: dict, second: dict) -> dict:
    """Intersect shared-field rules instead of letting the first PDF win."""
    result = dict(first)
    for key, value in second.items():
        if key not in result:
            result[key] = value
        elif key in {'min', 'min_length', 'min_date'}:
            result[key] = max(result[key], value, key=(lambda item: Decimal(str(item))) if key != 'min_date' else None)
        elif key in {'max', 'max_length', 'max_date', 'decimal_places'}:
            result[key] = min(result[key], value, key=(lambda item: Decimal(str(item))) if key != 'max_date' else None)
        elif key in {'integer', 'no_future'}:
            result[key] = bool(result[key] or value)
        elif result[key] != value:
            raise ValueError('Selected documents require different field formats. Review their rules.')
    for lower, upper in (('min', 'max'), ('min_length', 'max_length'), ('min_date', 'max_date')):
        if lower in result and upper in result:
            low, high = result[lower], result[upper]
            if lower != 'min_date':
                low, high = Decimal(str(low)), Decimal(str(high))
            if low > high:
                raise ValueError('Selected documents require incompatible field limits.')
    return result


def reviewed_rules(spec: dict) -> dict:
    """Explicit seed-time improvements; never run against application snapshots."""
    result = dict(spec.get('validation') or {})
    key, kind = spec['key'], spec['type']
    if kind == 'text' and (key.endswith('_email') or key.endswith('_email_address')):
        result.update(format='email', max_length=result.get('max_length', 254))
    if kind == 'number' and (key.endswith('_count') or 'number_of_children' in key or 'number_of_other_dependants' in key):
        result.update(integer=True, min=result.get('min', '0'))
    if kind == 'number' and (key in {'year_of_purchase', 'year_of_manufacture', 'year_manufactured'} or key.endswith('_year_manufactured')):
        result['integer'] = True
    if kind == 'date' and (key.endswith('_dob') or key.endswith('_date_of_birth')):
        result['no_future'] = True
    if key == 'applicant_sub_county' and kind == 'sub_county':
        result['parent_field'] = 'applicant_county'
    return result
