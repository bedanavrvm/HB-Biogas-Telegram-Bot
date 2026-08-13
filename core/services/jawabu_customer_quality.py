"""Canonical identity, reference-data, and provenance rules for Jawabu.

This module intentionally produces candidates rather than merging uncertain
customers.  KYC/CRB identity errors are more costly than a supervised review.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable

from django.db import DatabaseError
from django.db.models import Q
from django.utils import timezone

from core.models import (
    JawabuCustomer,
    JawabuCustomerFieldProvenance,
    JawabuCustomerPhoneHistory,
    JawabuFarmerMaster,
    OperationalProduct,
)
from core.services.identifiers import normalize_kenyan_phone, normalize_national_id


SUPPORTED_NATIONAL_ID_LENGTHS = frozenset({7, 8, 9})


@dataclass(frozen=True)
class FarmerMatch:
    """Exact and review-only evidence for a system/customer import row."""

    farmer_ids: tuple[str, ...]
    match_basis: str
    conflicts: tuple[str, ...]
    name_candidates: tuple[str, ...]

    @property
    def exact_farmer_id(self) -> str:
        return self.farmer_ids[0] if not self.conflicts and len(self.farmer_ids) == 1 else ''


def normalize_customer_name(value: object) -> str:
    """Order-independent comparison key; never used as an automatic identity key."""
    tokens = re.sub(r'[^a-z0-9]+', ' ', str(value or '').casefold()).split()
    return ' '.join(sorted(tokens))


def national_id_quality_message(value: object) -> str:
    national_id = normalize_national_id(value)
    if not national_id:
        return ''
    if len(national_id) not in SUPPORTED_NATIONAL_ID_LENGTHS:
        return 'National ID should contain 7 to 9 digits; confirm this exception before use.'
    return ''


def configured_operational_products() -> list[str]:
    try:
        return list(
            OperationalProduct.objects.filter(active=True)
            .order_by('sort_order', 'name')
            .values_list('name', flat=True)
        )
    except DatabaseError:
        # Keeps pre-migration diagnostics safe; the resulting review warning
        # tells operators that the controlled catalog must be applied.
        return []


def configured_operational_product_options() -> list[tuple[str, str]]:
    """Return stable catalog keys for scoped access forms without a hard dependency on migration state."""
    try:
        return [
            (str(code or name), str(name))
            for code, name in OperationalProduct.objects.filter(active=True)
            .order_by('sort_order', 'name')
            .values_list('code', 'name')
        ]
    except DatabaseError:
        return []


def normalize_operational_product(value: object) -> str:
    return ' '.join(str(value or '').split())


def product_quality_message(value: object, *, configured_products: list[str] | None = None) -> str:
    product = normalize_operational_product(value)
    if not product:
        return ''
    configured = configured_products if configured_products is not None else configured_operational_products()
    if not configured:
        return 'Global product catalogue has not been configured.'
    if product.casefold() not in {item.casefold() for item in configured}:
        return f'Product Name "{product}" is not in the operational product catalog.'
    return ''


def _farmer_ids(queryset: Iterable[JawabuFarmerMaster]) -> set[str]:
    return {str(value) for value in queryset.values_list('pk', flat=True).distinct()}


def resolve_farmer_match(
    *, national_id: object = '', customer_no: object = '', primary_phone: object = '', name: object = '',
) -> FarmerMatch:
    """Resolve exact identifiers; leave every uncertain identity for review."""
    normalized_id = normalize_national_id(national_id)
    normalized_customer_no = re.sub(r'\D', '', str(customer_no or ''))
    normalized_phone = normalize_kenyan_phone(primary_phone)
    matches_by_basis: dict[str, set[str]] = {}

    if normalized_id:
        matches_by_basis['national_id'] = _farmer_ids(
            JawabuFarmerMaster.objects.filter(
                Q(national_id=normalized_id) | Q(customer__national_id=normalized_id),
            )
        )
    if normalized_customer_no:
        matches_by_basis['customer_no'] = _farmer_ids(
            JawabuFarmerMaster.objects.filter(
                Q(customer_no=normalized_customer_no) | Q(customer__customer_no=normalized_customer_no),
            )
        )
    if normalized_phone:
        matches_by_basis['primary_phone'] = _farmer_ids(
            JawabuFarmerMaster.objects.filter(
                Q(primary_phone=normalized_phone)
                | Q(customer__primary_phone=normalized_phone)
                | Q(customer__phone_history__phone=normalized_phone),
            )
        )

    all_ids = set().union(*matches_by_basis.values()) if matches_by_basis else set()
    conflicts: list[str] = []
    for basis, ids in matches_by_basis.items():
        if len(ids) > 1:
            conflicts.append(f'{basis} matched multiple cases')
    non_empty_sets = [ids for ids in matches_by_basis.values() if ids]
    if len(set().union(*non_empty_sets)) > 1:
        conflicts.append('National ID, Customer ID, and Mobile No identify different cases')

    name_candidates: list[str] = []
    if not all_ids and name:
        wanted = normalize_customer_name(name)
        if wanted:
            for farmer in JawabuFarmerMaster.objects.only('id', 'customer_name', 'imab_customer_name'):
                candidate_names = (farmer.customer_name, farmer.imab_customer_name)
                best = max(
                    (SequenceMatcher(None, wanted, normalize_customer_name(candidate)).ratio() for candidate in candidate_names if candidate),
                    default=0.0,
                )
                if best >= 0.84:
                    name_candidates.append(str(farmer.pk))
                if len(name_candidates) >= 10:
                    break
        if name_candidates:
            conflicts.append('Name candidate requires manual confirmation')

    basis = next((item for item in ('national_id', 'customer_no', 'primary_phone') if matches_by_basis.get(item)), '')
    return FarmerMatch(
        farmer_ids=tuple(sorted(all_ids)),
        match_basis=basis or ('name_candidate' if name_candidates else ''),
        conflicts=tuple(conflicts),
        name_candidates=tuple(name_candidates),
    )


def record_customer_phone(customer: JawabuCustomer, phone: object, *, source: str) -> None:
    """Track observed phones so a replaced SIM remains a reviewable match key."""
    normalized_phone = normalize_kenyan_phone(phone)
    if not normalized_phone:
        return
    now = timezone.now()
    JawabuCustomerPhoneHistory.objects.filter(customer=customer, is_current=True).exclude(phone=normalized_phone).update(is_current=False)
    JawabuCustomerPhoneHistory.objects.update_or_create(
        customer=customer,
        phone=normalized_phone,
        defaults={'source': source, 'is_current': normalized_phone == customer.primary_phone, 'last_seen_at': now},
    )


def record_field_provenance(
    farmer: JawabuFarmerMaster,
    *, old_values: dict[str, object], new_values: dict[str, object], source: str,
    source_reference: str = '', source_row_number: int | None = None, actor: str = '',
) -> int:
    """Persist only actual changes so provenance remains compact and meaningful."""
    created = 0
    for field_name, new_value in new_values.items():
        old_value = old_values.get(field_name, '')
        old_text = '' if old_value is None else str(old_value)
        new_text = '' if new_value is None else str(new_value)
        if old_text == new_text:
            continue
        JawabuCustomerFieldProvenance.objects.create(
            farmer=farmer,
            field_name=field_name,
            old_value=old_text,
            new_value=new_text,
            source=source,
            source_reference=source_reference,
            source_row_number=source_row_number,
            actor=actor,
        )
        created += 1
    return created
