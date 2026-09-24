"""Canonical HomeBiogas fulfilment-partner routing for orders and Sheets."""

from __future__ import annotations

import re


PARTNER_HB = 'HB'
PARTNER_ECO = 'ECOCONSERVE'
PARTNER_CHOICES = (
    (PARTNER_HB, 'HB'),
    (PARTNER_ECO, 'Eco-conserve'),
)


def normalize_partner_value(value) -> str:
    return re.sub(r'\s+', ' ', str(value or '').strip()).upper()


def is_eco_conserve_sales_person(value) -> bool:
    """Accept the common FarmUp spellings without matching unrelated staff."""
    return bool(re.fullmatch(r'ECO[\s._/-]*CONSERVE(?:[\s._/-]*JAWABU)?', normalize_partner_value(value)))


def fulfillment_partner_for_farmer(farmer) -> str:
    """Resolve the sole partner from canonical case fields, never client input."""
    county = normalize_partner_value(getattr(farmer, 'county', ''))
    sales_person = normalize_partner_value(getattr(farmer, 'hb_sales_person', ''))
    if county == 'NAKURU' or is_eco_conserve_sales_person(sales_person):
        return PARTNER_ECO
    return PARTNER_HB


def fulfillment_partner_label(partner: str) -> str:
    return dict(PARTNER_CHOICES).get(str(partner), 'HB')


def order_number_for_partner(partner: str, number) -> str:
    prefix = 'ECO' if partner == PARTNER_ECO else 'HB'
    return f'{prefix}-{int(number)}'


def require_single_fulfillment_partner(farmers) -> str:
    partners = {fulfillment_partner_for_farmer(farmer) for farmer in farmers}
    if not partners:
        raise ValueError('Select at least one customer for this order.')
    if len(partners) != 1:
        raise ValueError('Selected cases belong to different fulfilment partners. Use the HB or Eco-conserve tab to prepare one order.')
    return next(iter(partners))
