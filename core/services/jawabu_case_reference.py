"""Stable staff-facing references for Portal cases.

The database UUID remains the canonical key.  This projection is deliberately
display-only so existing records gain a short reference without a migration or
another mutable identity sequence.
"""

from __future__ import annotations

import base64
import uuid


def display_case_reference(value) -> str:
    text = str(value or '').strip()
    if not text:
        return ''
    try:
        encoded = base64.b32encode(uuid.UUID(text).bytes).decode('ascii').rstrip('=')[:10]
    except (ValueError, AttributeError, TypeError):
        return text
    return f'JBL-{encoded[:5]}-{encoded[5:]}'
