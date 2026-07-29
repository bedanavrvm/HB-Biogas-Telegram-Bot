"""Read-only reconciliation reporting for the governed Jawabu data boundary."""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from core.models import JawabuFarmerMaster, JawabuFarmerUploadBatch
from core.services.branches import global_branch_choices
from core.services.identifiers import normalize_kenyan_phone
from core.services.jawabu_customer_quality import (
    configured_operational_products,
    national_id_quality_message,
)
from core.services.jawabu_validation import validation_warnings
from core.services.locations import global_county_choices


def _active_duplicate_values(field_name: str) -> set[str]:
    """Return identifiers shared by different people, not extra units.

    A JawabuCustomer can legitimately have a second or third application.  A
    duplicate case count alone would therefore mislabel correct repeat-unit
    applications as an identity collision.  Unlinked legacy rows remain
    independently reviewable until the canonical customer link is established.
    """
    owners_by_value: dict[str, set[str]] = defaultdict(set)
    for value, customer_id, farmer_id in (
        JawabuFarmerMaster.objects.filter(status='active')
        .exclude(**{field_name: ''})
        .values_list(field_name, 'customer_id', 'id')
    ):
        owner = f'customer:{customer_id}' if customer_id else f'unlinked:{farmer_id}'
        owners_by_value[str(value)].add(owner)
    return {value for value, owners in owners_by_value.items() if len(owners) > 1}


def active_jawabu_quality_report(*, limit: int = 100) -> dict[str, Any]:
    """Inspect active customer data without changing Django, Sheets, or Drive."""
    branches = set(global_branch_choices())
    counties = set(global_county_choices())
    products = configured_operational_products()
    duplicate_ids = _active_duplicate_values('national_id')
    duplicate_customer_numbers = _active_duplicate_values('customer_no')
    findings: list[dict[str, str]] = []
    codes: Counter[str] = Counter()
    total = 0
    valid_national_ids = 0
    normalized_primary_phones = 0

    for farmer in JawabuFarmerMaster.objects.filter(status='active').only(
        'id', 'national_id', 'primary_phone', 'secondary_phone', 'county', 'branch',
        'customer_no', 'payment_product', 'sign_date', 'actual_receipts', 'latitude',
        'longitude', 'repayment_date', 'repayment_tenor',
    ):
        total += 1
        if farmer.national_id and not national_id_quality_message(farmer.national_id):
            valid_national_ids += 1
        if farmer.primary_phone and normalize_kenyan_phone(farmer.primary_phone) == farmer.primary_phone:
            normalized_primary_phones += 1
        entries: list[tuple[str, str, str]] = []
        entries.extend((field, issue['code'], issue['message']) for field, issue in (
            (item['field'], item) for item in validation_warnings(
                farmer, product_catalog=products, branch_catalog=list(branches), county_catalog=list(counties),
            )
        ))
        if farmer.national_id and farmer.national_id in duplicate_ids:
            entries.append(('national_id', 'duplicate_active_identity', 'National ID appears on multiple active cases.'))
        if farmer.customer_no and farmer.customer_no in duplicate_customer_numbers:
            entries.append(('customer_no', 'duplicate_active_customer_no', 'Customer number appears on multiple active cases.'))
        for field_name, code, message in entries:
            codes[code] += 1
            if len(findings) < limit:
                findings.append({
                    'farmer_id': str(farmer.pk), 'field': field_name, 'code': code, 'message': message,
                })

    return {
        'active_cases': total,
        'valid_national_ids': valid_national_ids,
        'normalized_primary_phones': normalized_primary_phones,
        'finding_count': sum(codes.values()),
        'by_code': dict(sorted(codes.items())),
        'findings': findings,
        'truncated': sum(codes.values()) > len(findings),
    }


def system_export_batch_quality_report(batch: JawabuFarmerUploadBatch) -> dict[str, Any]:
    """Summarise staged `/sysup` rows without committing any one of them."""
    rows = list(batch.parsed_rows or [])
    statuses = Counter(str(row.get('Import Status') or 'unknown') for row in rows)
    match_bases = Counter(str(row.get('Match Basis') or 'unmatched') for row in rows)
    notes = [
        {'source_row': row.get('Source Row'), 'notes': row.get('Cleaning Notes', '')}
        for row in rows if row.get('Cleaning Notes')
    ]
    return {
        'batch_id': str(batch.pk),
        'source_filename': batch.source_filename,
        'total_rows': len(rows),
        'by_status': dict(sorted(statuses.items())),
        'by_match_basis': dict(sorted(match_bases.items())),
        'review_rows': notes[:100],
        'truncated': len(notes) > 100,
    }
