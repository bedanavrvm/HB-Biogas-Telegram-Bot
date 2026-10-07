"""Read-only payment picker projection; never substitutes for add_cases validation."""
from core.models import JawabuPipelineEvent
from core.services.payment_documents import payment_readiness
from payments.models import PaymentBatch, PaymentBatchCase


_MISSING_LABELS = {
    'Cust No': 'Customer number missing', 'Matched invoice': 'No matched invoice',
    'Balance Due': 'Invoice balance missing', 'Repayment Dates': 'Repayment day missing',
    'Tenor': 'Repayment term missing', 'Current final approval': 'Final approval needed',
}

def payment_candidate_rows(farmers, *, batch, pending_reviews):
    ids = [farmer.pk for farmer in farmers]
    readiness = payment_readiness(farmer_ids=[str(value) for value in ids]) if ids else {}
    facts = {
        item['farmer_id']: item
        for kind in ('ready', 'blocked') for item in readiness.get(kind, [])
    }
    memberships = PaymentBatchCase.objects.filter(
        farmer_id__in=ids, is_active=True,
    ).exclude(batch__status=PaymentBatch.STATUS_CANCELLED).select_related('batch').order_by('added_at')
    membership_map = {str(item.farmer_id): item.batch for item in memberships}
    paid = set(JawabuPipelineEvent.objects.filter(
        farmer_id__in=ids, action='payment_finalized',
    ).values_list('farmer_id', flat=True))
    editable = batch.status not in {PaymentBatch.STATUS_COMPLETED, PaymentBatch.STATUS_CANCELLED}
    rows = []
    for farmer in farmers:
        key = str(farmer.pk)
        item = facts.get(key, {
            'farmer_id': key, 'customer_name': farmer.customer_name,
            'national_id': farmer.national_id, 'primary_phone': farmer.primary_phone,
            'invoice_number': farmer.invoice_number, 'row': {}, 'warnings': [], 'missing': [],
        })
        membership = membership_map.get(key)
        reason = ''
        state = 'ready'
        if membership and membership.pk == batch.pk:
            state, reason = 'included', 'Already in this payment'
        elif farmer.pk in paid or (membership and membership.status == PaymentBatch.STATUS_COMPLETED):
            state, reason = 'paid', 'Already paid'
        elif membership:
            label = f"Payment #{membership.payment_number}" if membership.payment_number else 'another draft payment'
            state, reason = 'assigned', f'Already in {label}'
        elif key in pending_reviews:
            state, reason = 'assigned', 'Awaiting approval in another payment'
        elif farmer.status != 'active':
            state, reason = 'closed', 'Case is no longer active'
        elif item.get('missing'):
            state, reason = 'blocked', '; '.join(dict.fromkeys(
                _MISSING_LABELS.get(value, value) for value in item['missing']
            ))
        elif key not in facts:
            state, reason = 'blocked', 'Payment details need review'
        if not editable:
            state, reason = 'closed', 'This payment is no longer editable'
        rows.append({**item, 'selectable': state == 'ready', 'availability': state,
                     'unavailable_reason': reason})
    return rows
