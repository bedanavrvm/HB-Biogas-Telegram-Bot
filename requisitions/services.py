"""Persistence boundaries for official order finalization and sequence evidence."""
from django.db import connection
from core.models import RequisitionBatch
from requisitions.models import OrderSequenceEvent


def _require_transaction():
    if not connection.in_atomic_block:
        raise RuntimeError('Official order persistence requires its governing transaction.')


def retain_finalized_requisition(**values):
    _require_transaction()
    if not values.get('finalized_at') or not values.get('file_content') or not values.get('content_checksum'):
        raise ValueError('A finalized requisition requires its exact retained workbook and checksum.')
    return RequisitionBatch.objects.create(**values)


def record_sequence_event(**values):
    _require_transaction()
    return OrderSequenceEvent.objects.create(**values)
