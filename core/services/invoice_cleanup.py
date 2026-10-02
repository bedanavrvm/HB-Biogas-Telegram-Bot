"""Scoped invoice removal, independent audit evidence and durable Drive cleanup."""
from django.db import transaction
from django.db.models import Q
from core.models import IntegrationOperation, InvoiceUploadBatch, ParsedInvoice, PaymentDocument

DELETE_OPERATION = 'portal_invoice_pdf_delete'


def protection_error(invoice):
    from payments.models import PaymentBatch, PaymentBatchCase, PaymentReceiptItem
    if invoice.name_change_requests.exists() or invoice.replacement_for_name_changes.exists():
        return 'This invoice is retained invoice-name-change evidence.'
    receipts = PaymentReceiptItem.objects.filter(Q(invoice=invoice) | Q(replacement_invoice=invoice))
    if PaymentBatch.objects.filter(receipt_batch_id__in=receipts.values('receipt_batch_id')).exists():
        return 'This invoice belongs to a payment batch. Its evidence is protected.'
    if invoice.matched_farmer_id and PaymentBatchCase.objects.filter(farmer_id=invoice.matched_farmer_id).exists():
        return 'This matched case has payment history. Its invoice is protected.'
    if invoice.matched_farmer_id:
        documents = PaymentDocument.objects.filter(order_number=invoice.matched_farmer.order_number).exclude(
            status__in=['preview', 'failed']).values_list('farmer_ids', flat=True)
        if any(str(invoice.matched_farmer_id) in (members or []) for members in documents):
            return 'This invoice supports a retained payment workbook. Its evidence is protected.'
    return ''


@transaction.atomic
def delete_invoice(invoice, *, actor='', expected_revision=None, duplicate_only=False):
    from core.models import GroupSheetConfiguration
    from core.services.compliance_audit import record_event
    from core.services.external_resilience import reserve_operation
    from core.services.invoice_parser import duplicate_deletion_error, refresh_invoice_batch_counts, unmatch_invoice
    from payments.models import PaymentReceiptBatch, PaymentReceiptItem
    group_id = invoice.batch.group_configuration_id
    if group_id:
        GroupSheetConfiguration.objects.select_for_update().get(pk=group_id)
    invoice = ParsedInvoice.objects.select_for_update().select_related('batch').get(pk=invoice.pk)
    if invoice.matched_farmer_id:
        from core.models import JawabuFarmerMaster
        JawabuFarmerMaster.objects.select_for_update().get(pk=invoice.matched_farmer_id)
    if expected_revision is not None and int(expected_revision) != invoice.revision:
        raise ValueError('This invoice changed. Refresh before deleting it.')
    error = duplicate_deletion_error(invoice) if duplicate_only else protection_error(invoice)
    if error:
        raise ValueError(error)
    batch = InvoiceUploadBatch.objects.select_for_update().get(pk=invoice.batch_id)
    invoice_id = str(invoice.pk)
    cleanup_scope = {
        'group_id': batch.group_configuration.group_id if batch.group_configuration_id else '',
        'branch': invoice.matched_farmer.branch if invoice.matched_farmer_id else '',
        'product': invoice.matched_farmer.product.code if invoice.matched_farmer_id and invoice.matched_farmer.product_id else '',
    }
    record_event(workflow='portal', action='invoice.deleted', subject_type='parsed_invoice',
        subject_id=invoice_id, deduplication_key=f'invoice-delete:{invoice_id}', actor_label=actor,
        before_values={'status': invoice.status, 'revision': invoice.revision},
        after_values={'deleted': True}, metadata={'batch_id': str(batch.pk), 'page': invoice.page,
        'content_sha256': batch.content_sha256,
        'events': list(invoice.events.values('action', 'actor', 'created_at'))})
    if invoice.matched_farmer_id:
        unmatch_invoice(invoice, actor=actor, note='Invoice deleted.')
    receipt_ids = list(PaymentReceiptItem.objects.filter(invoice=invoice).values_list('receipt_batch_id', flat=True))
    PaymentReceiptItem.objects.filter(invoice=invoice).delete()
    for receipt in PaymentReceiptBatch.objects.select_for_update().filter(pk__in=receipt_ids):
        receipt.revision += 1
        receipt.save(update_fields=['revision', 'updated_at'])
    invoice.delete()
    refresh_invoice_batch_counts(batch)
    # Retain the upload envelope for retry identity and independent audit. Never
    # remove a combined PDF while even one surviving invoice needs its bytes.
    empty = not batch.invoices.exists() and not batch.payment_receipt_items.exists()
    if empty:
        batch.metadata = {**(batch.metadata or {}), 'invoice_rows_deleted': True}
        batch.content_sha256 = ''
        batch.save(update_fields=['metadata', 'content_sha256', 'updated_at'])
    shared = InvoiceUploadBatch.objects.filter(drive_file_id=batch.drive_file_id).exclude(pk=batch.pk).filter(
        Q(invoices__isnull=False) | Q(payment_receipt_items__isnull=False)).exists() if batch.drive_file_id else False
    if empty and batch.drive_file_id and not shared:
        reserve_operation(integration=IntegrationOperation.INTEGRATION_GOOGLE_DRIVE,
            operation_type=DELETE_OPERATION, source_model='InvoiceUploadBatch', source_id=str(batch.pk),
            deduplication_key=f'invoice-pdf-delete:{batch.pk}:{batch.drive_file_id}',
            requested_by_label=actor, metadata={'file_id': batch.drive_file_id, 'group_configuration_id': group_id, **cleanup_scope})
    return {'id': invoice_id, 'batch_id': str(batch.pk), 'deleted': True,
            'shared_pdf': bool(batch.drive_file_id and (shared or not empty))}


def attempt_pdf_delete(operation):
    from core.services.external_resilience import execute_operation
    from core.services.order_approval import GoogleDriveMediaStorage
    if operation.operation_type != DELETE_OPERATION:
        raise ValueError('Not an invoice cleanup operation.')
    def remove():
        batch = InvoiceUploadBatch.objects.get(pk=operation.source_id)
        if batch.invoices.exists() or batch.payment_receipt_items.exists():
            raise ValueError('The source PDF is still referenced.')
        file_id = (operation.metadata or {})['file_id']
        if InvoiceUploadBatch.objects.filter(drive_file_id=file_id).exclude(pk=batch.pk).filter(
                Q(invoices__isnull=False) | Q(payment_receipt_items__isnull=False)).exists():
            raise ValueError('Another invoice still needs this source PDF.')
        try:
            GoogleDriveMediaStorage().service.files().delete(fileId=file_id, supportsAllDrives=True).execute()
        except Exception as exc:
            if getattr(getattr(exc, 'resp', None), 'status', None) != 404:
                raise
        InvoiceUploadBatch.objects.filter(drive_file_id=file_id, invoices__isnull=True,
            payment_receipt_items__isnull=True).update(drive_file_id='', drive_url='')
        return {'deleted': True}
    return execute_operation(operation, remove, attempt_budget=1)
