"""Shared, format-only validation for Kenyan customer identifiers.

These helpers deliberately establish neither mobile-number ownership nor the
existence of a National ID.  Those require a separately governed verification
process; accepting a format must never be presented as verification.
"""
from __future__ import annotations

import re
from typing import Any


KENYAN_MOBILE_CANONICAL_PATTERN = re.compile(r'^254[17]\d{8}$')
KENYAN_NATIONAL_ID_PATTERN = re.compile(r'^\d{1,9}$')
_PHONE_VISUAL_SEPARATOR_PATTERN = re.compile(r'[\s()\-]')


def validate_kenyan_national_id(value: Any) -> str:
    """Return an issued Kenyan National ID/Maisha Namba in entered form.

    National IDs are numeric identifiers, not numbers: leading zeroes are
    meaningful and no formatting, padding, checksum, or character stripping is
    applied.  The accepted format covers legacy 1--8 digit values and modern
    9-digit Maisha identifiers.
    """
    text = str(value or '').strip()
    return text if KENYAN_NATIONAL_ID_PATTERN.fullmatch(text) else ''


def normalize_national_id(value: Any) -> str:
    """Legacy-tolerant lookup normalizer.

    Keep this behavior for historical matching/import inspection.  New and
    corrected staff input must use :func:`validate_kenyan_national_id` so a
    value containing letters is never silently converted into another ID.
    """
    return re.sub(r'\D', '', str(value or ''))


def normalize_kenyan_phone(value: Any) -> str:
    """Normalize a Kenyan *mobile* number to ``254XXXXXXXXX``.

    Accepted inputs are local 01/07 and nine-digit forms, ordinary/E.164
    country-code forms, pasted ``00254`` international access forms, and the
    East African ``005`` access form.  Only ordinary visual separators are
    tolerated.  This avoids accidentally accepting prose such as
    ``call-0712...`` simply because it contains enough digits.
    """
    text = str(value or '').strip()
    if not text or re.search(r'[^0-9+\s()\-]', text):
        return ''
    if text.count('+') > 1 or ('+' in text and not text.startswith('+')):
        return ''
    compact = _PHONE_VISUAL_SEPARATOR_PATTERN.sub('', text)
    if compact.startswith('+'):
        compact = compact[1:]
    if not compact.isdigit():
        return ''

    if compact.startswith('00254'):
        compact = compact[2:]
    elif compact.startswith('005'):
        # CA's East African regional access code is followed by Kenya's NSN,
        # i.e. the nine-digit mobile number without a national trunk zero.
        compact = f'254{compact[3:]}'

    # A common pasted form is +254 0712 345 678.  Retain the actual subscriber
    # number but remove the redundant national trunk prefix.
    if compact.startswith('2540') and len(compact) == 13 and compact[4] in {'1', '7'}:
        compact = f'254{compact[4:]}'
    elif compact.startswith('0') and len(compact) == 10:
        compact = f'254{compact[1:]}'
    elif len(compact) == 9:
        compact = f'254{compact}'

    if not KENYAN_MOBILE_CANONICAL_PATTERN.fullmatch(compact):
        return ''
    # 0199 is allocated to testing/research rather than ordinary subscribers.
    if compact.startswith('254199'):
        return ''
    return compact
