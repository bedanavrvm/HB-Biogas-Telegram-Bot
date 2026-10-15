"""Exact invoice-content comparison, separate from identity suggestions."""
from collections import defaultdict
from decimal import Decimal

from django.db.models.functions import Lower, Trim

from core.services.identifiers import normalize_kenyan_phone, normalize_national_id


AMOUNT_FIELDS = ('invoice_amount', 'total_after_discount', 'discount', 'payment', 'balance_due')
COMPARISON_FIELDS = (
    'id', 'batch__group_configuration_id', 'customer_id', 'invoice_no',
    'invoice_date', 'invoice_date_raw', 'customer_name', 'customer_phone',
    *AMOUNT_FIELDS, 'raw_payload',
)


def _text(value):
    return str(value or '').strip().casefold()


def fingerprint(invoice):
    """Missing identity/number never proves a duplicate; absent money is not zero."""
    get = invoice.get if isinstance(invoice, dict) else lambda key: getattr(invoice, key)
    national_id = normalize_national_id(get('customer_id'))
    number = _text(get('invoice_no'))
    if not national_id or not number:
        return None
    date = get('invoice_date')
    date_value = date.isoformat() if date else _text(get('invoice_date_raw'))
    amounts = tuple(None if get(key) is None else Decimal(str(get(key))) for key in AMOUNT_FIELDS)
    payload = get('raw_payload') or {}
    return (national_id, number, date_value, _text(get('customer_name')),
            normalize_kenyan_phone(get('customer_phone')) or _text(get('customer_phone')), *amounts,
            _text(payload.get('order_reference')))


def exact_peers(invoice, queryset):
    expected = fingerprint(invoice)
    if expected is None:
        return []
    candidates = queryset.annotate(_duplicate_number=Lower(Trim('invoice_no'))).filter(
        _duplicate_number=_text(invoice.invoice_no),
    ).exclude(pk=invoice.pk).exclude(status__in=['deleted', 'superseded'])
    return [peer for peer in candidates if fingerprint(peer) == expected]


def duplicate_ids(rows, peers):
    groups = defaultdict(set)
    for peer in peers:
        key = fingerprint(peer)
        if key is not None:
            groups[(peer['batch__group_configuration_id'], key)].add(peer['id'])
    return {row['id'] for row in rows if fingerprint(row) is not None
            and len(groups[(row['batch__group_configuration_id'], fingerprint(row))]) > 1}
