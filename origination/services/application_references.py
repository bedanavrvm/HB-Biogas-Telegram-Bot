"""Application display numbers are allocated with creation, never from row counts."""
from django.db import transaction
from django.db.models import Q

from origination.models import LoanOriginationApplication, OriginationApplicationReferenceSequence


def next_application_reference() -> str:
    # Call inside the application creation transaction, so replay/rollback cannot
    # allocate another number. get_or_create also fences singleton initialization.
    with transaction.atomic():
        OriginationApplicationReferenceSequence.objects.get_or_create(pk=1)
        sequence = OriginationApplicationReferenceSequence.objects.select_for_update().get(pk=1)
        while True:
            sequence.last_number += 1
            reference = f'ORG-{sequence.last_number}'
            if not LoanOriginationApplication.objects.filter(
                Q(reference_number=reference) | Q(display_reference=reference),
            ).exists():
                break
        sequence.save(update_fields=['last_number'])
        return reference
