"""Shared vocabulary and semantic-name helpers for Loan Origination.

Applicant is the operational role. Customer is reserved for the matched global
identity, while borrower remains a contractual/signing role. Historical field
keys are never rewritten; these helpers only identify equivalent catalogue
names and keep new configuration consistent.
"""

from __future__ import annotations

import re
from typing import Iterable


ORIGINATION_TERMINOLOGY = {
    'applicant': 'Person or entity applying for a loan.',
    'customer': 'Canonical global customer identity matched to an applicant.',
    'borrower': 'Contractual obligor or signer in a legal document.',
    'party': 'Collective term for applicants, guarantors, spouses, and other signers.',
    'client': 'Reserved for technical request or browser concepts, not a person label.',
    'farmer': 'Product-specific occupation or a legacy Jawabu workflow term.',
}

PERSON_ROLE_SYNONYMS = frozenset({'applicant', 'borrower', 'client', 'customer', 'farmer'})
PERSON_ATTRIBUTE_TOKENS = frozenset({
    'address', 'birth', 'county', 'dob', 'email', 'first', 'full', 'id',
    'identification', 'last', 'middle', 'mobile', 'name', 'national', 'phone',
    'postal', 'residence', 'subcounty', 'surname', 'town',
})
TECHNICAL_CONTEXT_TOKENS = frozenset({
    'api', 'browser', 'device', 'idempotency', 'pointer', 'request', 'session',
})


def terminology_signature(value: object) -> str:
    """Return a conservative semantic signature for a catalogue name.

    Person-role synonyms are standardized only when the value also describes a
    person attribute. This deliberately leaves terms such as ``borrower_signature``
    and technical names such as ``client_request_id`` unchanged.
    """

    normalized = re.sub(r'[^a-z0-9]+', '_', str(value or '').strip().casefold()).strip('_')
    if not normalized:
        return ''
    tokens = normalized.split('_')
    token_set = set(tokens)
    is_person_attribute = bool(token_set & PERSON_ATTRIBUTE_TOKENS)
    is_technical = bool(token_set & TECHNICAL_CONTEXT_TOKENS)
    if is_person_attribute and not is_technical:
        tokens = ['applicant' if token in PERSON_ROLE_SYNONYMS else token for token in tokens]
    return '_'.join(tokens)


def field_terminology_signatures(*values: object) -> set[str]:
    """Return the non-empty semantic signatures represented by field names."""

    return {signature for value in values if (signature := terminology_signature(value))}


def aliases_with_legacy_terms(label: str, key: str, aliases: Iterable[object]) -> list[str]:
    """Build a stable, case-insensitive alias list for an explicit consolidation."""

    combined = [str(item).strip() for item in aliases if str(item).strip()]
    combined.extend(value for value in (label.strip(), key.strip()) if value)
    result: list[str] = []
    seen: set[str] = set()
    for value in combined:
        folded = value.casefold()
        if folded in seen:
            continue
        seen.add(folded)
        result.append(value)
    return result
