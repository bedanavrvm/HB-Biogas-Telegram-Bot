"""Persistence boundaries for official order finalization and sequence evidence."""
from django.db import connection, transaction
from django.utils import timezone
from core.models import RequisitionBatch, DocumentPhysicalSignoff, JawabuFarmerMaster
from requisitions.models import OrderSequenceEvent, OrderSequenceState, OrderNumberClaim, OrderWorkbookVersion, OrderWorkspaceEvent


def _require_transaction():
    if not connection.in_atomic_block:
        raise RuntimeError('Official order persistence requires its governing transaction.')


def retain_finalized_requisition(**values):
    _require_transaction()
    if not values.get('finalized_at') or not values.get('file_content') or not values.get('content_checksum'):
        raise ValueError('A finalized requisition requires its exact retained workbook and checksum.')
    batch = RequisitionBatch.objects.create(**values)
    retain_workbook_version(batch)
    return batch


def record_sequence_event(**values):
    _require_transaction()
    return OrderSequenceEvent.objects.create(**values)


def signed_order(batch):
    return DocumentPhysicalSignoff.objects.filter(
        requisition_batch=batch, source_version=batch.version,
        source_checksum=batch.content_checksum,
        status=DocumentPhysicalSignoff.STATUS_SIGNED_APPROVED,
    ).exists()


def resolve_order(reference):
    """UUID is canonical. A legacy number must identify exactly one workspace."""
    import uuid
    try:
        return RequisitionBatch.objects.get(pk=uuid.UUID(str(reference)))
    except (ValueError, RequisitionBatch.DoesNotExist):
        matches = list(RequisitionBatch.objects.filter(order_number=str(reference))[:2])
        if len(matches) != 1:
            raise ValueError('Open this order from Order Archive; its old link is no longer unique.')
        return matches[0]


def order_for_farmer(farmer, *, lock=False):
    """Resolve exact assignment, never the newest holder of a reused number."""
    query = RequisitionBatch.objects.select_for_update() if lock else RequisitionBatch.objects
    if farmer.requisition_batch_id:
        return query.filter(pk=farmer.requisition_batch_id).first()
    candidates = [batch for batch in query.filter(
        order_number=farmer.order_number, requisition_date=farmer.requisition_date,
    ) if str(farmer.pk) in {str(value) for value in (batch.farmer_ids or [])}]
    return candidates[0] if len(candidates) == 1 else None


def proposed_number(sequence, *, excluding_batch=None):
    released = sequence.number_claims.filter(batch__isnull=True, retired=False).order_by('number').first()
    if released:
        return released.number
    # An IT sequence adjustment may place the counter on an occupied slot.
    number = sequence.next_number
    occupied = set(sequence.number_claims.filter(number__gte=number).values_list('number', flat=True))
    from core.services.requisition_partners import order_number_for_partner
    prefix = order_number_for_partner(sequence.partner, 1).rsplit('-', 1)[0] + '-'
    # Legacy workbooks without an allocator claim remain occupied forever;
    # only an explicit released claim is permission to reuse a slot.
    for display in RequisitionBatch.objects.filter(
            group_configuration_id=sequence.group_configuration_id,
            fulfillment_partner=sequence.partner).exclude(pk=excluding_batch).values_list('order_number', flat=True):
        suffix = str(display).removeprefix(prefix)
        if (str(display).startswith(prefix) or str(display).isdigit()) and suffix.isdigit():
            occupied.add(int(suffix))
    while number in occupied:
        number += 1
    return number


def claim_number(sequence, batch, *, actor=None, request_id=''):
    _require_transaction()
    number = proposed_number(sequence, excluding_batch=batch.pk)
    from core.services.requisition_partners import order_number_for_partner
    if batch.order_number != order_number_for_partner(sequence.partner, number):
        raise ValueError('The proposed order number changed. Preview again.')
    claim, _ = OrderNumberClaim.objects.get_or_create(sequence=sequence, number=number)
    if claim.batch_id or claim.retired:
        raise ValueError('This order number is already in use. Preview again.')
    claim.batch = batch
    claim.save(update_fields=['batch'])
    before = sequence.next_number
    sequence.next_number = max(before, number + 1)
    sequence.revision += 1
    sequence.updated_by = actor
    sequence.save()
    record_sequence_event(sequence=sequence, action='allocated', number_before=before,
                          number_after=sequence.next_number, revision_after=sequence.revision,
                          actor=actor, reason='Generated unsigned order workbook.', request_id=request_id)
    return number


def retain_workbook_version(batch):
    _require_transaction()
    return OrderWorkbookVersion.objects.create(
        batch=batch, version=batch.version, filename=batch.filename,
        file_content=batch.file_content, checksum=batch.content_checksum,
        farmer_ids=batch.farmer_ids, actor=batch.finalized_by,
    )


def unsigned_daily_orders(sequence, request_date):
    return [batch for batch in RequisitionBatch.objects.filter(
        group_configuration_id=sequence.group_configuration_id,
        fulfillment_partner=sequence.partner, requisition_date=request_date,
    ).exclude(status__in=['cancelled', 'preview']).order_by('created_at')
        if not signed_order(batch) and not order_has_finance_evidence(batch)]


def order_has_finance_evidence(batch):
    """Pre-cutover financial work must not be silently amended or released."""
    from django.db.models import Q
    from payments.models import PaymentBatchCase
    farmers = JawabuFarmerMaster.objects.filter(Q(requisition_batch=batch) | Q(pk__in=batch.farmer_ids or []))
    return (farmers.exclude(invoice_number='').exists()
            or PaymentBatchCase.objects.filter(farmer__in=farmers).exists())


@transaction.atomic
def cancel_order(batch_id, *, expected_version, actor, request_id):
    # Lock the allocator before the workspace, matching generation lock order.
    source = RequisitionBatch.objects.get(pk=batch_id)
    sequence = OrderSequenceState.objects.select_for_update().filter(
        group_configuration_id=source.group_configuration_id, partner=source.fulfillment_partner)
    sequence = sequence.first()
    if not sequence:
        raise ValueError('This order has no number sequence. Ask IT to configure it before cancelling.')
    batch = RequisitionBatch.objects.select_for_update().get(pk=batch_id)
    replay = OrderWorkspaceEvent.objects.filter(request_id=request_id).first() if request_id else None
    if replay:
        if replay.batch_id != batch.pk or replay.action != 'cancelled' or replay.actor_id != actor.pk:
            raise ValueError('This request was used for another order change.')
        return batch
    if int(expected_version) != batch.version:
        raise ValueError('This order changed. Refresh before cancelling it.')
    if signed_order(batch):
        raise ValueError('A signed order is final and cannot be cancelled.')
    if batch.status == 'cancelled':
        return batch
    if batch.assigned_cases.exclude(pk__in=batch.farmer_ids or []).exists():
        raise ValueError('This order’s case list needs repair. Ask IT to check it before cancelling.')
    farmers = list(JawabuFarmerMaster.objects.select_for_update().filter(pk__in=batch.farmer_ids).order_by('pk'))
    # Never reverse historical finance evidence or release a different batch.
    from payments.models import PaymentBatchCase
    if any(f.invoice_number for f in farmers) or PaymentBatchCase.objects.filter(farmer__in=farmers).exists():
        raise ValueError('This legacy order has financial evidence. IT must review it before cancellation.')
    from core.services.jawabu_case360 import record_pipeline_event
    from core.services.portal_publication import reserve_farmer_publication
    for farmer in farmers:
        if farmer.requisition_batch_id not in (None, batch.pk):
            raise ValueError('A case belongs to another order. Refresh the archive.')
        if farmer.order_number != batch.order_number:
            raise ValueError('An order assignment changed. Refresh the archive.')
        before = farmer.workflow_revision
        farmer.order_number = ''
        farmer.requisition_date = None
        farmer.requisition_batch = None
        farmer.workflow_state = 'order'
        farmer.workflow_state_entered_at = timezone.now()
        farmer.workflow_revision += 1
        farmer.save(update_fields=['order_number', 'requisition_date', 'requisition_batch', 'workflow_state', 'workflow_state_entered_at', 'workflow_revision', 'updated_at'])
        record_pipeline_event(farmer, action='order_cancelled', stage_key='order', actor=actor.get_username(), actor_user=actor,
                              request_id=f'{request_id}:{farmer.pk}', old_values={'order_number': batch.order_number},
                              new_values={'order_number': ''}, revision_before=before, revision_after=farmer.workflow_revision)
        reserve_farmer_publication(farmer, request_id=request_id, requested_by=actor)
    # Only claims created by the new allocator can be recycled.
    OrderNumberClaim.objects.filter(sequence=sequence, batch=batch).update(batch=None)
    batch.status = 'cancelled'
    batch.drive_next_retry_at = None
    batch.save(update_fields=['status', 'drive_next_retry_at', 'updated_at'])
    sequence.revision += 1
    sequence.updated_by = actor
    sequence.save(update_fields=['revision', 'updated_by', 'updated_at'])
    OrderWorkspaceEvent.objects.create(batch=batch, action='cancelled', version=batch.version,
        actor=actor, request_id=request_id, metadata={'reason': 'Unsigned order cancelled by staff confirmation.', 'order_number': batch.order_number})
    return batch
