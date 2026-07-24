"""Canonical validation and typed normalization for the Jawabu portal pipeline."""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from django.utils import timezone

from core.models import JawabuDataQualityIssue, JawabuFarmerMaster
from core.services.identifiers import normalize_kenyan_phone, normalize_national_id


class JawabuValidationError(ValueError):
    def __init__(self, errors: dict[str, str]):
        self.errors = errors
        super().__init__('; '.join(f'{field}: {message}' for field, message in errors.items()))


def parse_business_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value or '').strip()
    for fmt in ('%Y-%m-%d', '%d-%B-%Y', '%d-%b-%Y', '%d/%m/%Y', '%d/%m/%y'):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_money(value: Any) -> Decimal | None:
    if value in (None, ''):
        return None
    try:
        amount = Decimal(re.sub(r'[^0-9.\-]', '', str(value)))
    except (InvalidOperation, ValueError):
        return None
    return amount.quantize(Decimal('0.01')) if amount >= 0 else None


def parse_repayment_day(value: Any) -> int | None:
    match = re.search(r'\d{1,2}', str(value or ''))
    day = int(match.group()) if match else None
    return day if day and 1 <= day <= 31 else None


def parse_tenor_months(value: Any) -> int | None:
    match = re.search(r'\d{1,3}', str(value or ''))
    months = int(match.group()) if match else None
    return months if months and 1 <= months <= 120 else None


def parse_coordinate(value: Any, *, latitude: bool) -> Decimal | None:
    if value in (None, ''):
        return None
    try:
        coordinate = Decimal(str(value)).quantize(Decimal('0.000001'))
    except (InvalidOperation, ValueError):
        return None
    limit = Decimal('90') if latitude else Decimal('180')
    return coordinate if -limit <= coordinate <= limit else None


def canonicalize_farmer(farmer: JawabuFarmerMaster, *, strict: bool = False) -> dict[str, str]:
    """Populate canonical fields and return field-level errors/warnings."""
    errors: dict[str, str] = {}
    national_id = normalize_national_id(farmer.national_id)
    if national_id and not 5 <= len(national_id) <= 12:
        errors['national_id'] = 'National ID must contain 5 to 12 digits.'
    elif national_id:
        farmer.national_id = national_id

    for field_name in ('primary_phone', 'secondary_phone'):
        raw = getattr(farmer, field_name)
        normalized = normalize_kenyan_phone(raw)
        if raw and not normalized:
            errors[field_name] = 'Enter a valid Kenyan mobile number.'
        elif normalized:
            setattr(farmer, field_name, normalized)

    if farmer.sign_date:
        farmer.hbg_visit_date = parse_business_date(farmer.sign_date)
        if farmer.hbg_visit_date is None:
            errors['sign_date'] = 'HBG visit date is not a recognized date.'
    if farmer.actual_receipts not in (None, ''):
        farmer.deposit_paid_hbg = parse_money(farmer.actual_receipts)
        if farmer.deposit_paid_hbg is None:
            errors['actual_receipts'] = 'HB deposit must be a non-negative amount.'
    if farmer.latitude not in (None, ''):
        farmer.latitude_value = parse_coordinate(farmer.latitude, latitude=True)
        if farmer.latitude_value is None:
            errors['latitude'] = 'Latitude must be between -90 and 90.'
    if farmer.longitude not in (None, ''):
        farmer.longitude_value = parse_coordinate(farmer.longitude, latitude=False)
        if farmer.longitude_value is None:
            errors['longitude'] = 'Longitude must be between -180 and 180.'
    if farmer.repayment_date:
        farmer.repayment_day = parse_repayment_day(farmer.repayment_date)
        if farmer.repayment_day is None:
            errors['repayment_date'] = 'Repayment day must be between 1 and 31.'
    if farmer.repayment_tenor:
        farmer.repayment_tenor_months = parse_tenor_months(farmer.repayment_tenor)
        if farmer.repayment_tenor_months is None:
            errors['repayment_tenor'] = 'Repayment tenor must be 1 to 120 months.'

    if strict and errors:
        raise JawabuValidationError(errors)
    return errors


def refresh_data_quality_issues(farmer: JawabuFarmerMaster) -> list[dict[str, str]]:
    errors = canonicalize_farmer(farmer, strict=False)
    now = timezone.now()
    active_keys = {(field, 'invalid_format') for field in errors}
    for issue in farmer.data_quality_issues.filter(active=True):
        if (issue.field_name, issue.code) not in active_keys:
            issue.active = False
            issue.resolved_at = now
            issue.save(update_fields=['active', 'resolved_at'])
    for field, message in errors.items():
        JawabuDataQualityIssue.objects.update_or_create(
            farmer=farmer,
            field_name=field,
            code='invalid_format',
            defaults={'severity': 'warning', 'message': message, 'active': True, 'resolved_at': None},
        )
    return [
        {'field': field, 'code': 'invalid_format', 'severity': 'warning', 'message': message}
        for field, message in errors.items()
    ]


def validation_warnings(farmer: JawabuFarmerMaster) -> list[dict[str, str]]:
    """Read-only validation projection for GET/detail endpoints."""
    errors = canonicalize_farmer(farmer, strict=False)
    return [
        {'field': field, 'code': 'invalid_format', 'severity': 'warning', 'message': message}
        for field, message in errors.items()
    ]
