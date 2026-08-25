"""Decimal-only quote calculations for published global product terms."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_HALF_UP
from typing import Any

from core.models import ProductFee, ProductVersion
from core.services.product_catalog import ProductCatalogError, serialize_product_version


CENT = Decimal('0.01')
ONE = Decimal('1')
FREQUENCY_PERIODS = {'weekly': Decimal('52'), 'fortnightly': Decimal('26'), 'monthly': Decimal('12')}


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _decimal(value: object, label: str) -> Decimal:
    try:
        return Decimal(str(value).replace(',', '').strip())
    except (InvalidOperation, AttributeError, ValueError) as exc:
        raise ProductCatalogError(f'Enter a valid {label}.') from exc


def installment_count(version: ProductVersion, tenor: int) -> int:
    periods_per_year = FREQUENCY_PERIODS[version.repayment_frequency]
    years = Decimal(tenor) / (Decimal('52') if version.tenor_unit == ProductVersion.TENOR_WEEK else Decimal('12'))
    return max(1, int((years * periods_per_year).to_integral_value(rounding=ROUND_CEILING)))


def periodic_interest_rate(version: ProductVersion) -> Decimal:
    stated = Decimal(version.interest_rate) / Decimal('100')
    annual = stated * Decimal('12') if version.interest_rate_period == ProductVersion.RATE_MONTHLY else stated
    return annual / FREQUENCY_PERIODS[version.repayment_frequency]


def _fee_amount(fee: ProductFee, bases: dict[str, Decimal]) -> Decimal:
    if fee.fee_type == ProductFee.TYPE_FIXED:
        amount = Decimal(fee.fixed_amount or 0)
    else:
        amount = bases[fee.calculation_basis] * Decimal(fee.percentage or 0) / Decimal('100')
    if fee.minimum_amount is not None:
        amount = max(amount, Decimal(fee.minimum_amount))
    if fee.maximum_amount is not None:
        amount = min(amount, Decimal(fee.maximum_amount))
    return _money(amount)


def calculate_product_quote(
    version: ProductVersion, *, amount: object, tenor: object,
    optional_fee_keys: list[str] | tuple[str, ...] | None = None,
    enforce_policy_bounds: bool = True,
) -> dict[str, Any]:
    principal = _decimal(amount, 'loan amount')
    try:
        tenor_value = int(str(tenor).strip())
    except (TypeError, ValueError) as exc:
        raise ProductCatalogError('Enter a valid whole-number tenor.') from exc
    if enforce_policy_bounds:
        if principal < version.min_amount:
            raise ProductCatalogError(f'Amount must be at least {version.currency} {version.min_amount:,.2f}.')
        if version.max_amount is not None and principal > version.max_amount:
            raise ProductCatalogError(f'Amount must not exceed {version.currency} {version.max_amount:,.2f}.')
        if tenor_value < version.min_tenor or tenor_value > version.max_tenor:
            raise ProductCatalogError(f'Tenor must be between {version.min_tenor} and {version.max_tenor} {version.tenor_unit}s.')
    if principal < 0 or tenor_value < 1:
        raise ProductCatalogError('Loan amount cannot be negative and tenor must be at least one.')

    selected = set(optional_fee_keys or [])
    fees = [fee for fee in version.fees.all() if fee.mandatory or fee.key in selected]
    financed_fee_total = Decimal('0')
    fee_rows = []
    for fee in fees:
        if fee.collection_mode != ProductFee.COLLECTION_FINANCED:
            continue
        bases = {
            ProductFee.BASIS_PRINCIPAL: principal,
            ProductFee.BASIS_FINANCED: principal + financed_fee_total,
            ProductFee.BASIS_INTEREST: Decimal('0'),
            ProductFee.BASIS_TOTAL: principal,
        }
        value = _fee_amount(fee, bases)
        financed_fee_total += value
        fee_rows.append({'key': fee.key, 'label': fee.label, 'amount': str(value), 'collection_mode': fee.collection_mode})

    financed_principal = principal + financed_fee_total
    payments = installment_count(version, tenor_value)
    rate = periodic_interest_rate(version)
    if version.interest_method == ProductVersion.INTEREST_FLAT:
        interest = financed_principal * rate * Decimal(payments)
        installment = (financed_principal + interest) / Decimal(payments)
    elif rate == 0:
        interest = Decimal('0')
        installment = financed_principal / Decimal(payments)
    else:
        factor = (ONE + rate) ** payments
        installment = financed_principal * rate * factor / (factor - ONE)
        interest = installment * Decimal(payments) - financed_principal
    interest = _money(interest)
    installment = _money(installment)

    upfront_fee_total = Decimal('0')
    for fee in fees:
        if fee.collection_mode != ProductFee.COLLECTION_UPFRONT:
            continue
        bases = {
            ProductFee.BASIS_PRINCIPAL: principal,
            ProductFee.BASIS_FINANCED: financed_principal,
            ProductFee.BASIS_INTEREST: interest,
            ProductFee.BASIS_TOTAL: financed_principal + interest,
        }
        value = _fee_amount(fee, bases)
        upfront_fee_total += value
        fee_rows.append({'key': fee.key, 'label': fee.label, 'amount': str(value), 'collection_mode': fee.collection_mode})

    # Keep the contractual total tied to principal plus interest. A rounded
    # regular instalment can otherwise introduce a few cents of drift when it
    # is multiplied across the schedule; the last instalment absorbs that
    # bounded rounding adjustment.
    total_repayment = _money(financed_principal + interest)
    final_installment = _money(
        total_repayment - (installment * Decimal(max(0, payments - 1)))
    )
    return {
        'terms': serialize_product_version(version, include_configuration=False),
        'inputs': {'amount': str(_money(principal)), 'tenor': tenor_value, 'tenor_unit': version.tenor_unit},
        'installment_count': payments,
        'periodic_interest_rate': str(rate),
        'financed_principal': str(_money(financed_principal)),
        'interest': str(interest),
        'installment_amount': str(installment),
        'final_installment_amount': str(final_installment),
        'total_repayment': str(total_repayment),
        'financed_fees': str(_money(financed_fee_total)),
        'upfront_fees': str(_money(upfront_fee_total)),
        'fees': fee_rows,
        'currency': version.currency,
    }
