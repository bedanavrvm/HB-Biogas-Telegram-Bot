"""Shared normalization helpers for Kenyan customer identifiers."""
from __future__ import annotations

import re
from typing import Any


def normalize_national_id(value: Any) -> str:
    return re.sub(r'\D', '', str(value or ''))


def normalize_kenyan_phone(value: Any) -> str:
    digits = re.sub(r'\D', '', str(value or ''))
    if digits.startswith('254') and len(digits) == 12 and digits[3] in {'1', '7'}:
        return digits
    if digits.startswith('0') and len(digits) == 10 and digits[1] in {'1', '7'}:
        return '254' + digits[1:]
    if len(digits) == 9 and digits[0] in {'1', '7'}:
        return '254' + digits
    return ''