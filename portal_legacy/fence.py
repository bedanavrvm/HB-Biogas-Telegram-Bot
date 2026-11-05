"""Case readiness during incremental import; register holds for destructive steps."""
import json
import uuid
from contextlib import contextmanager
from django.db import transaction

from django.db.models import Case, CharField, Exists, OuterRef, Q, Value, When

from .models import LegacyRow, LegacyUpload

REPLACEMENT_PHASES = ('backup', 'projecting', 'verifying', 'replacing', 'readback')


def active(group_id):
    """Owner-wide administrative operations still require all cutovers to finish."""
    return bool(group_id and LegacyUpload.objects.filter(batch__group_id=group_id, frozen=True).exists())


def blocked_cases(queryset):
    """One SQL predicate shared by request admission and durable publication."""
    holding = LegacyUpload.objects.filter(batch__group_id=OuterRef('group_configuration_id'),
                                          source_sheet=OuterRef('_cutover_register'), frozen=True)
    verified = LegacyRow.objects.filter(farmer_id=OuterRef('pk'), batch__group_id=OuterRef('group_configuration_id'),
        source_sheet=OuterRef('_cutover_register'), committed_at__isnull=False, publication_ready=True).filter(
            Q(draft_versions__reconciliation__sheet_receipt__verified=True)
            | Q(draft_versions__upload__phase='complete'))
    incomplete = LegacyRow.objects.filter(farmer_id=OuterRef('pk')).filter(
        Q(committed_at__isnull=True) | Q(publication_ready=False))
    return queryset.alias(_cutover_register=Case(
        When(legacy_fulfillment_partner='ECOCONSERVE', then=Value('Eco-conserve')),
        When(legacy_fulfillment_partner='HB', then=Value('Master Data')),
        When(Q(county__iexact='NAKURU') | Q(hb_sales_person__iregex=r'^\s*ECO[\s._/-]*CONSERVE(?:[\s._/-]*JAWABU)?\s*$'), then=Value('Eco-conserve')),
        default=Value('Master Data'), output_field=CharField(),
    )).alias(_cutover_held=Exists(holding), _cutover_verified=Exists(verified),
        _cutover_incomplete=Exists(incomplete),
        _cutover_exclusive=Exists(holding.filter(Q(phase__in=REPLACEMENT_PHASES) | Q(phase='deleting') | Q(state__cleanup_complete__isnull=True) | Q(state__cleanup_complete=False))),
    ).filter(Q(_cutover_held=True) & (Q(_cutover_exclusive=True) | Q(_cutover_verified=False) | Q(_cutover_incomplete=True)))


def case_blocked(farmer):
    from core.models import JawabuFarmerMaster
    return blocked_cases(JawabuFarmerMaster.objects.filter(pk=farmer.pk)).exists()


def request_cases(request, kwargs):
    """Resolve actual case membership, never trust a supplied group as case evidence."""
    from core.models import (DocumentPhysicalSignoff, IntegrationOperation, InvoiceUploadBatch,
                             JawabuFarmerMaster, ParsedInvoice, PaymentDocument, RequisitionBatch)
    from hb_operations.models import HomeBiogasAction
    from payments.models import PaymentBatch
    try:
        body = json.loads(request.body or '{}') if request.content_type == 'application/json' else request.POST
    except (ValueError, UnicodeDecodeError):
        body = {}
    if not hasattr(body, 'get'): body = {}
    ids = set()
    def add(value):
        try: ids.add(str(uuid.UUID(str(value))))
        except (ValueError, TypeError, AttributeError): pass
    for key in ('farmer_id', 'case_id'):
        add(kwargs.get(key))
    route = getattr(getattr(request, 'resolver_match', None), 'url_name', '')
    selection_routes = {'portal_requisition_preview', 'portal_requisition_workbook_preview',
                        'portal_requisition_generate', 'portal_payment_batch_cases', 'portal_payment_selection'}
    if route in selection_routes:
        values = body.get('farmer_ids', [])
        if isinstance(values, list):
            for value in values: add(value)
    if route == 'portal_requisition_finalize':
        from django.core.signing import BadSignature, TimestampSigner
        try:
            preview=json.loads(TimestampSigner(salt='portal-requisition-finalize').unsign(str(body.get('preview_token') or ''),max_age=900))
            for value in preview.get('farmer_ids',[]):add(value)
        except (ValueError, TypeError, AttributeError, BadSignature):pass
    if route == 'portal_publication_attempt':
        try:
            operation=IntegrationOperation.objects.filter(pk=uuid.UUID(str(body.get('operation_id'))),source_model='JawabuFarmerMaster').first()
            if operation:add(operation.source_id)
        except (ValueError, TypeError):pass
    if route == 'portal_invoice_match':
        add(body.get('farmer_id'))
    if kwargs.get('invoice_id'):
        for invoice in ParsedInvoice.objects.filter(pk=kwargs['invoice_id']):
            add(invoice.matched_farmer_id)
            add(invoice.proposed_farmer_id)
    if kwargs.get('row_id'):
        ids.update(str(value) for value in LegacyRow.objects.filter(pk=kwargs['row_id']).exclude(farmer_id=None).values_list('farmer_id', flat=True))
    action_id = kwargs.get('action_id')
    if action_id:
        ids.update(str(value) for value in HomeBiogasAction.objects.filter(pk=action_id).values_list('farmer_id', flat=True))
    batch_id = kwargs.get('batch_id')
    if batch_id:
        try:
            batch_id = uuid.UUID(str(batch_id))
            for batch in RequisitionBatch.objects.filter(pk=batch_id):
                for value in batch.farmer_ids or []: add(value)
            ids.update(str(value) for value in PaymentBatch.objects.filter(pk=batch_id,case_memberships__is_active=True).values_list('case_memberships__farmer_id', flat=True) if value)
            if route == 'portal_invoice_batch_confirm':
                ids.update(str(value) for value in InvoiceUploadBatch.objects.filter(pk=batch_id,
                    invoices__matched_farmer_id__isnull=False).values_list('invoices__matched_farmer_id', flat=True))
        except (ValueError, TypeError): pass
    document_id = kwargs.get('document_id')
    document_type = kwargs.get('document_type', 'payment')
    if document_id:
        model = {'requisition': RequisitionBatch, 'payment': PaymentDocument}.get(document_type)
        if model:
            for document in model.objects.filter(pk=document_id):
                for value in document.farmer_ids or []: add(value)
    if kwargs.get('signoff_id'):
        for signoff in DocumentPhysicalSignoff.objects.filter(pk=kwargs['signoff_id']).select_related('requisition_batch', 'payment_document'):
            document = signoff.requisition_batch or signoff.payment_document
            for value in document.farmer_ids or []: add(value)
    order = kwargs.get('order_number')
    if order:
        from requisitions.services import resolve_order
        try:
            batch = resolve_order(order)
            for value in batch.farmer_ids or []: add(value)
        except (ValueError, RequisitionBatch.DoesNotExist): pass
    return JawabuFarmerMaster.objects.filter(pk__in=ids)


def request_blocked(request, kwargs):
    if not LegacyUpload.objects.filter(frozen=True).exists(): return False
    if request.path.startswith('/api/portal/legacy/uploads/'): return False
    if request.path in {'/api/portal/publication/pump/', '/api/portal/health/maintenance/'}: return False
    cases = request_cases(request, kwargs)
    if cases.exists():
        blocked = blocked_cases(cases)
        if not blocked.exists(): return False
        request.portal_cutover_code = 'legacy_case_awaiting_sync'
        if blocked.filter(_cutover_exclusive=True).exists():
            request.portal_cutover_code = 'legacy_register_replacing'
        return True
    # Non-case operations and unresolvable targets retain the administrative fence.
    return True


@contextmanager
def case_write_guard(request, kwargs):
    """Serialize admission with replacement entry, not with the entire import."""
    if not LegacyUpload.objects.filter(frozen=True).exists():
        yield False
        return
    with transaction.atomic():
        from core.services.miniapp_deletion_sheets import lock_sheet_mutations
        # Same lock order as import projection: Sheet mutex, then canonical cases.
        lock_sheet_mutations()
        list(request_cases(request, kwargs).order_by('pk').select_for_update().values_list('pk', flat=True))
        yield request_blocked(request, kwargs)
