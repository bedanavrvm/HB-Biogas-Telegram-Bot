"""Allowlisted Portal search; name words may occur in any order."""
from django.db.models import Q


def case_search(term, *, name_fields=('customer_name', 'lead_name'), fields=()):
    term = ' '.join(str(term or '').split())[:120]
    if not term:
        return Q()
    match = Q(pk__in=[])
    for field in name_fields:
        name = Q()
        for word in dict.fromkeys(term.split()):
            name &= Q(**{f'{field}__icontains': word})
        match |= name
    for field in fields:
        match |= Q(**{f'{field}__icontains': term})
    return match
