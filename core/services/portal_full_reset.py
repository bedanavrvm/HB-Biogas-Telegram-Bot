"""Superuser-only, configuration-scoped Portal clean-slate operation.

Drive objects and immutable compliance-ledger rows are deliberately untouched.
The caller must put Portal into read-only maintenance before invoking this
service: Sheet deletion cannot participate in a database transaction.
"""

from __future__ import annotations

import uuid

from django.db import connection, transaction
from django.db.models import Q

from core.models import (
    DocumentPhysicalSignoff, FcaImportRecord, GroupSheetConfiguration,
    IntegrationOperation, InvoiceNameChangeBatch, InvoiceNameChangeItem,
    InvoiceNameChangeLetterArtifact, InvoiceUploadBatch, JawabuApprovalRecord,
    JawabuCaseComment, JawabuCustomer, JawabuFarmerMaster, JawabuFarmerUploadBatch,
    JawabuMediaAccessEvent, JawabuPipelineEvent, LiveSheetRecordChange,
    LocationMappingIssue, MediaAttachment, ParsedInvoice, PaymentDocument,
    ProductMappingIssue, RequisitionBatch, ComplaintCaseControl,
    LoanOriginationApplication, JawabuRelatedPerson, JawabuHouseholdRelationship,
    WorkflowTimelineAnnotation, JawabuVisitRecord,
)
from hb_operations.models import HomeBiogasAction, HomeBiogasActionEvent
from payments.models import (
    PaymentBatch, PaymentBatchCase, PaymentBatchEvent, PaymentCaseReview,
    PaymentReceiptBatch, PaymentReceiptItem,
    PaymentSequenceEvent, PaymentSequenceState,
)
from requisitions.models import OrderSequenceEvent, OrderSequenceState


class PortalResetError(ValueError):
    """A reset cannot complete safely; no database rows were deleted."""


def _portal_configuration(configuration):
    if not isinstance(configuration, GroupSheetConfiguration) or not configuration.pk:
        raise PortalResetError('Choose a saved Portal group configuration.')
    configuration = GroupSheetConfiguration.objects.get(pk=configuration.pk)
    if (configuration.workflow or {}).get('type') not in {'jawabu', 'jawabu_homebiogas'}:
        raise PortalResetError('This action is available only for a Portal group.')
    return configuration


def _farmer_queryset(configuration):
    batch_ids = list(JawabuFarmerUploadBatch.objects.filter(
        group_id=configuration.group_id,
    ).values_list('pk', flat=True))
    # Legacy records have no owner key. The clean-slate policy deliberately
    # includes them, but never records explicitly assigned to another group.
    query = JawabuFarmerMaster.objects.filter(group_configuration=configuration)
    if _sole_portal_configuration(configuration):
        query = query | JawabuFarmerMaster.objects.filter(group_configuration__isnull=True)
    for batch_id in batch_ids:
        query = query | JawabuFarmerMaster.objects.filter(raw_data__upload_batch_id=str(batch_id))
    return query.distinct()


def _sole_portal_configuration(configuration):
    portal_ids = [
        row.pk for row in GroupSheetConfiguration.objects.only('pk', 'workflow')
        if (row.workflow or {}).get('type') in {'jawabu', 'jawabu_homebiogas'}
    ]
    return portal_ids == [configuration.pk]


def _owned_or_unowned(model, configuration):
    query = Q(group_configuration=configuration)
    if _sole_portal_configuration(configuration):
        query |= Q(group_configuration__isnull=True)
    return model.objects.filter(query)


def portal_reset_manifest(configuration):
    configuration = _portal_configuration(configuration)
    farmers = _farmer_queryset(configuration)
    farmer_ids = list(farmers.values_list('pk', flat=True))
    orders = _owned_or_unowned(RequisitionBatch, configuration)
    payments = PaymentBatch.objects.filter(group_configuration=configuration)
    order_ids = list(orders.values_list('pk', flat=True))
    payment_ids = list(payments.values_list('pk', flat=True))
    invoice_uploads = _owned_or_unowned(InvoiceUploadBatch, configuration)
    counts = {
        'cases': len(farmer_ids),
        'farmup_sysup_uploads': JawabuFarmerUploadBatch.objects.filter(group_id=configuration.group_id).count(),
        'visits': JawabuVisitRecord.objects.filter(group_id=configuration.group_id).count(),
        'orders': orders.count(),
        'invoice_uploads': invoice_uploads.count(),
        'parsed_invoices': ParsedInvoice.objects.filter(batch__in=invoice_uploads).count(),
        'approvals': JawabuApprovalRecord.objects.filter(farmer_id__in=farmer_ids).count(),
        'payments': payments.count(),
        'payment_cases': PaymentBatchCase.objects.filter(batch_id__in=payment_ids).count(),
        'signed_scans': DocumentPhysicalSignoff.objects.filter(requisition_batch_id__in=order_ids).count(),
        'hb_actions': HomeBiogasAction.objects.filter(farmer_id__in=farmer_ids).count(),
        'media_links': MediaAttachment.objects.filter(jawabu_farmer_id__in=farmer_ids).count(),
        'audit_access_events': JawabuMediaAccessEvent.objects.filter(farmer_id__in=farmer_ids).count(),
    }
    return {'configuration_id': configuration.pk, 'counts': counts, 'total': sum(counts.values())}


def _sheet_targets(configuration):
    workflow = configuration.workflow or {}
    sheet_id = str(workflow.get('master_sheet_id') or configuration.sheet_id or '').strip()
    if not sheet_id:
        return []
    names = [
        str(workflow.get('master_sheet_name') or 'Master Data').strip(),
        str(workflow.get('eco_conserve_sheet_name') or 'Eco-conserve').strip(),
    ]
    return [(sheet_id, name) for name in dict.fromkeys(names) if name]


def _delete_verified_sheet_rows(configuration, farmer_ids):
    if not farmer_ids:
        return 0
    from core.services.sheets import GoogleSheetsService
    from core.services.jawabu_master import normalize_header

    workflow = configuration.workflow or {}
    header_row = int(workflow.get('master_header_row') or 1)
    data_start = int(workflow.get('master_data_start_row') or header_row + 1)
    target_ids = {str(value).casefold() for value in farmer_ids}
    deleted = 0
    for sheet_id, tab in _sheet_targets(configuration):
        service = GoogleSheetsService.get_instance(sheet_id=sheet_id, sheet_name=tab)
        if not service.is_available():
            raise PortalResetError(f'Cannot open the {tab} Sheet; Portal remains read-only for a safe retry.')
        sheet = service._sheet
        values = sheet.get_all_values()
        if len(values) < header_row:
            raise PortalResetError(f'The {tab} Sheet has no expected header row.')
        headers = {normalize_header(value): index for index, value in enumerate(values[header_row - 1])}
        id_column = headers.get(normalize_header('Master Record ID'))
        if id_column is None:
            raise PortalResetError(f'The {tab} Sheet has no immutable Master Record ID column.')
        row_numbers = [
            row_number for row_number, row in enumerate(values, start=1)
            if row_number >= data_start and len(row) > id_column
            and str(row[id_column] or '').strip().lstrip("'").casefold() in target_ids
        ]
        if row_numbers and not hasattr(sheet, 'delete_rows'):
            raise PortalResetError(f'The {tab} Sheet does not support verified row deletion.')
        for row_number in reversed(row_numbers):
            current = sheet.row_values(row_number)
            if len(current) <= id_column or str(current[id_column] or '').strip().lstrip("'").casefold() not in target_ids:
                raise PortalResetError(f'The {tab} Sheet changed during reset; no further rows were deleted.')
            sheet.delete_rows(row_number)
            deleted += 1
        remaining = sheet.get_all_values()
        if any(
            row_number >= data_start and len(row) > id_column
            and str(row[id_column] or '').strip().lstrip("'").casefold() in target_ids
            for row_number, row in enumerate(remaining, start=1)
        ):
            raise PortalResetError(f'Could not verify all {tab} rows were removed.')
        # Row deletion shifts the indexes of surviving groups. Keep their
        # immutable-ID publication pointers aligned with the live tab.
        for row_number, row in enumerate(remaining, start=1):
            if row_number < data_start or len(row) <= id_column:
                continue
            record_id = str(row[id_column] or '').strip().lstrip("'")
            if record_id:
                LiveSheetRecordChange.objects.filter(
                    sheet_id=sheet_id, sheet_tab=tab, record_key=record_id,
                ).exclude(row_number=row_number).update(row_number=row_number)
    return deleted


def _sequence_start(sequence, event_model):
    first = event_model.objects.filter(sequence=sequence).order_by('created_at', 'pk').first()
    if first is None:
        return int(sequence.next_number)
    # IT initialization is recorded as an adjustment; the configured baseline
    # is the resulting value, not the allocator's temporary default of 1.
    return int(first.number_after if first.action == 'adjusted' else first.number_before)


def _restart_case_references_if_globally_empty() -> bool:
    """Restart staff-facing numbering only after every Portal case is gone."""
    if connection.vendor == 'postgresql':
        # Keep nextval/insert out until the emptiness check and transactional
        # RESTART are complete. UUIDs and historical audit identities do not
        # change; this affects only future JBL-# labels.
        with connection.cursor() as cursor:
            cursor.execute('LOCK TABLE core_jawabufarmermaster IN ACCESS EXCLUSIVE MODE')
            if JawabuFarmerMaster.objects.exists():
                return False
            cursor.execute('ALTER SEQUENCE core_jawabu_case_reference_seq RESTART WITH 1')
        return True
    # SQLite's local/test allocator uses MAX(case_reference_number) + 1.
    return not JawabuFarmerMaster.objects.exists()


def reset_portal_configuration(configuration, *, actor, backup_reference: str):
    """Delete verified Sheet projections, then all linked local Portal state.

    Re-running after an interrupted Sheet deletion is safe: the case UUIDs stay
    in Django until the final atomic database phase commits.
    """
    configuration = _portal_configuration(configuration)
    if not actor or not actor.is_active or not actor.is_superuser:
        raise PortalResetError('Only an active Superuser can reset Portal data.')
    if not str(backup_reference or '').strip():
        raise PortalResetError('Record a verified database backup reference before resetting Portal.')
    from core.services.portal_maintenance import maintenance_write_blocked
    if not maintenance_write_blocked()[0]:
        raise PortalResetError('Put Portal into read-only maintenance before resetting data.')
    if not _sole_portal_configuration(configuration) and (
        JawabuFarmerMaster.objects.filter(group_configuration__isnull=True).exists()
        or RequisitionBatch.objects.filter(group_configuration__isnull=True).exists()
        or InvoiceUploadBatch.objects.filter(group_configuration__isnull=True).exists()
    ):
        raise PortalResetError(
            'Some legacy Portal records have no group owner. Assign their group before resetting one of multiple Portal groups.'
        )

    farmer_ids = list(_farmer_queryset(configuration).values_list('pk', flat=True))
    customer_ids = list(_farmer_queryset(configuration).exclude(customer_id=None).values_list('customer_id', flat=True).distinct())
    related_person_ids = list(JawabuHouseholdRelationship.objects.filter(farmer_id__in=farmer_ids).values_list('related_person_id', flat=True))
    upload_ids = list(JawabuFarmerUploadBatch.objects.filter(group_id=configuration.group_id).values_list('pk', flat=True))
    order_ids = list(_owned_or_unowned(RequisitionBatch, configuration).values_list('pk', flat=True))
    order_numbers = [
        str(value).strip() for value in
        RequisitionBatch.objects.filter(pk__in=order_ids).values_list('order_number', flat=True)
        if str(value or '').strip()
    ]
    invoice_upload_ids = list(_owned_or_unowned(InvoiceUploadBatch, configuration).values_list('pk', flat=True))
    payment_ids = list(PaymentBatch.objects.filter(group_configuration=configuration).values_list('pk', flat=True))
    receipt_ids = list(PaymentReceiptBatch.objects.filter(group_configuration=configuration).values_list('pk', flat=True))
    document_ids = set()
    document_ids.update(PaymentBatch.objects.filter(pk__in=payment_ids).exclude(current_document=None).values_list('current_document_id', flat=True))
    document_ids.update(JawabuApprovalRecord.objects.filter(farmer_id__in=farmer_ids).exclude(payment_document=None).values_list('payment_document_id', flat=True))
    selected_farmer_ids = {str(pk) for pk in farmer_ids}
    for document in PaymentDocument.objects.filter(order_number__in=order_numbers).only('pk', 'farmer_ids'):
        members = {str(pk) for pk in (document.farmer_ids or [])}
        if members and not members.issubset(selected_farmer_ids):
            if members & selected_farmer_ids:
                raise PortalResetError('A payment workbook contains cases from multiple groups. Review ownership before resetting.')
            continue
        if members or _sole_portal_configuration(configuration) or document.pk in document_ids:
            document_ids.add(document.pk)
        else:
            raise PortalResetError('A legacy payment workbook has no case owner. Review ownership before resetting one of multiple Portal groups.')
    for member_ids in RequisitionBatch.objects.filter(pk__in=order_ids).values_list('farmer_ids', flat=True):
        if any(str(pk) not in selected_farmer_ids for pk in (member_ids or [])):
            raise PortalResetError('An order includes a case owned by another group. Review ownership before resetting.')
    name_batch_ids = list(InvoiceNameChangeItem.objects.filter(farmer_id__in=farmer_ids).exclude(batch_id=None).values_list('batch_id', flat=True))
    if InvoiceNameChangeItem.objects.filter(batch_id__in=name_batch_ids).exclude(farmer_id__in=farmer_ids).exists():
        raise PortalResetError('An invoice-name-change letter includes another group’s case. Review ownership before resetting.')
    # Cross-group links must be reviewed rather than silently cascading across
    # another configuration's operational data.
    if PaymentBatchCase.objects.filter(farmer_id__in=farmer_ids).exclude(batch_id__in=payment_ids).exists():
        raise PortalResetError('A case belongs to another group’s payment batch. Review ownership before resetting.')
    if PaymentBatchCase.objects.filter(batch_id__in=payment_ids).exclude(farmer_id__in=farmer_ids).exists():
        raise PortalResetError('A payment batch contains a case owned by another group. Review ownership before resetting.')
    if HomeBiogasAction.objects.filter(farmer_id__in=farmer_ids).exclude(source_requisition_batch_id__in=order_ids).exists():
        raise PortalResetError('A case belongs to another group’s signed order. Review ownership before resetting.')
    if HomeBiogasAction.objects.filter(source_requisition_batch_id__in=order_ids).exclude(farmer_id__in=farmer_ids).exists():
        raise PortalResetError('A signed order contains an HB action owned by another group. Review ownership before resetting.')
    if PaymentReceiptItem.objects.filter(farmer_id__in=farmer_ids).exclude(receipt_batch_id__in=receipt_ids).exists():
        raise PortalResetError('A case belongs to another group’s invoice delivery. Review ownership before resetting.')
    if PaymentReceiptItem.objects.filter(receipt_batch_id__in=receipt_ids).exclude(farmer_id__in=farmer_ids).exclude(farmer_id=None).exists():
        raise PortalResetError('An invoice delivery contains a case owned by another group. Review ownership before resetting.')
    if PaymentReceiptItem.objects.filter(source_upload_id__in=invoice_upload_ids).exclude(receipt_batch_id__in=receipt_ids).exists():
        raise PortalResetError('An invoice upload belongs to another group’s invoice delivery. Review ownership before resetting.')
    if ParsedInvoice.objects.filter(
        Q(matched_farmer_id__in=farmer_ids) | Q(proposed_farmer_id__in=farmer_ids),
    ).exclude(batch_id__in=invoice_upload_ids).exists():
        raise PortalResetError('A case has an invoice in another group. Review ownership before resetting.')
    if ParsedInvoice.objects.filter(batch_id__in=invoice_upload_ids).exclude(
        Q(matched_farmer_id__in=farmer_ids) | Q(matched_farmer_id=None),
    ).exists():
        raise PortalResetError('An invoice upload is matched to another group’s case. Review ownership before resetting.')
    if ParsedInvoice.objects.filter(batch_id__in=invoice_upload_ids).exclude(
        Q(proposed_farmer_id__in=farmer_ids) | Q(proposed_farmer_id=None),
    ).exists():
        raise PortalResetError('An invoice upload proposes another group’s case. Review ownership before resetting.')
    if JawabuApprovalRecord.objects.filter(payment_document_id__in=document_ids).exclude(farmer_id__in=farmer_ids).exists():
        raise PortalResetError('A payment document is approved against another group’s case. Review ownership before resetting.')
    if MediaAttachment.objects.filter(group_id=configuration.group_id).exclude(
        Q(jawabu_farmer_id__in=farmer_ids) | Q(jawabu_farmer_id=None),
    ).exists():
        raise PortalResetError('A media attachment belongs to another group’s case. Review ownership before resetting.')
    if JawabuMediaAccessEvent.objects.filter(attachment__group_id=configuration.group_id).exclude(farmer_id__in=farmer_ids).exists():
        raise PortalResetError('A media access record crosses group ownership. Review it before resetting.')

    deleted_sheet_rows = _delete_verified_sheet_rows(configuration, farmer_ids)
    with transaction.atomic():
        GroupSheetConfiguration.objects.select_for_update().get(pk=configuration.pk)
        order_sequences = list(OrderSequenceState.objects.select_for_update().filter(group_configuration=configuration))
        payment_sequence = PaymentSequenceState.objects.select_for_update().filter(group_configuration=configuration).first()
        starts = {row.pk: _sequence_start(row, OrderSequenceEvent) for row in order_sequences}
        payment_start = _sequence_start(payment_sequence, PaymentSequenceEvent) if payment_sequence else None

        actions = HomeBiogasAction.objects.filter(farmer_id__in=farmer_ids)
        HomeBiogasActionEvent.objects.filter(action__in=actions).delete()
        actions.delete()

        signoffs = DocumentPhysicalSignoff.objects.filter(
            Q(requisition_batch_id__in=order_ids) | Q(payment_document_id__in=document_ids),
        )
        signoffs.delete()

        name_items = InvoiceNameChangeItem.objects.filter(farmer_id__in=farmer_ids)
        name_items.delete()
        name_batches = InvoiceNameChangeBatch.objects.filter(pk__in=name_batch_ids)
        name_batches.update(sent_artifact=None)
        InvoiceNameChangeLetterArtifact.objects.filter(batch_id__in=name_batch_ids).delete()
        name_batches.delete()

        PaymentSequenceEvent.objects.filter(sequence__group_configuration=configuration).delete()
        PaymentCaseReview.objects.filter(membership__batch_id__in=payment_ids).delete()
        PaymentBatchCase.objects.filter(batch_id__in=payment_ids).delete()
        PaymentBatchEvent.objects.filter(batch_id__in=payment_ids).delete()
        PaymentBatch.objects.filter(pk__in=payment_ids).update(current_document=None, receipt_batch=None)
        PaymentBatch.objects.filter(pk__in=payment_ids).delete()
        PaymentReceiptItem.objects.filter(receipt_batch_id__in=receipt_ids).delete()
        PaymentReceiptBatch.objects.filter(pk__in=receipt_ids).delete()

        JawabuApprovalRecord.objects.filter(farmer_id__in=farmer_ids).delete()
        PaymentDocument.objects.filter(pk__in=document_ids).delete()
        OrderSequenceEvent.objects.filter(sequence__group_configuration=configuration).delete()
        RequisitionBatch.objects.filter(pk__in=order_ids).delete()
        InvoiceUploadBatch.objects.filter(pk__in=invoice_upload_ids).delete()

        access = JawabuMediaAccessEvent.objects.filter(
            Q(farmer_id__in=farmer_ids) | Q(attachment__group_id=configuration.group_id),
        )
        for event in access.only('pk', 'farmer_id', 'attachment_id').iterator():
            access.filter(pk=event.pk).update(
                farmer_id_snapshot=str(event.farmer_id or ''),
                attachment_id_snapshot=str(event.attachment_id or ''),
            )
        access.update(farmer=None, attachment=None)
        MediaAttachment.objects.filter(
            Q(jawabu_farmer_id__in=farmer_ids) | Q(group_id=configuration.group_id),
        ).delete()
        JawabuPipelineEvent.objects.filter(farmer_id__in=farmer_ids).delete()
        JawabuCaseComment.objects.filter(farmer_id__in=farmer_ids).delete()
        WorkflowTimelineAnnotation.objects.filter(workflow='jawabu_pipeline', subject_id__in=[str(pk) for pk in farmer_ids]).delete()
        IntegrationOperation.objects.filter(source_model='JawabuFarmerMaster', source_id__in=[str(pk) for pk in farmer_ids]).delete()
        IntegrationOperation.objects.filter(source_model='JawabuFarmerUploadBatch', source_id__in=[str(pk) for pk in upload_ids]).delete()
        ProductMappingIssue.objects.filter(source_workflow='jawabu_portal', source_model='JawabuFarmerMaster', source_record_id__in=[str(pk) for pk in farmer_ids]).delete()
        LocationMappingIssue.objects.filter(source_model='JawabuFarmerMaster', source_record_id__in=[str(pk) for pk in farmer_ids]).delete()
        JawabuFarmerMaster.objects.filter(pk__in=farmer_ids).delete()
        case_references_restarted = _restart_case_references_if_globally_empty()
        # Customer identity is shared with Complaints and Origination. Only
        # delete identities that became truly orphaned after this Portal reset.
        for customer_id in customer_ids:
            if (
                JawabuFarmerMaster.objects.filter(customer_id=customer_id).exists()
                or LoanOriginationApplication.objects.filter(customer_id=customer_id).exists()
                or ComplaintCaseControl.objects.filter(customer_id=customer_id).exists()
                or JawabuRelatedPerson.objects.filter(linked_customer_id=customer_id).exists()
            ):
                continue
            JawabuCustomer.objects.filter(pk=customer_id).delete()
        for person_id in related_person_ids:
            if not JawabuHouseholdRelationship.objects.filter(related_person_id=person_id).exists():
                JawabuRelatedPerson.objects.filter(pk=person_id).delete()
        JawabuFarmerUploadBatch.objects.filter(group_id=configuration.group_id).delete()
        JawabuVisitRecord.objects.filter(group_id=configuration.group_id).delete()
        FcaImportRecord.objects.filter(group_id=configuration.group_id).delete()
        LiveSheetRecordChange.objects.filter(group_id=configuration.group_id).delete()
        for row in order_sequences:
            row.next_number = starts[row.pk]
            row.revision += 1
            row.updated_by = actor
            row.adjustment_reason = 'Portal clean-slate reset; prior issued numbers manually voided.'
            row.save(update_fields=['next_number', 'revision', 'updated_by', 'adjustment_reason', 'updated_at'])
        if payment_sequence:
            payment_sequence.next_number = payment_start
            payment_sequence.revision += 1
            payment_sequence.updated_by = actor
            payment_sequence.adjustment_reason = 'Portal clean-slate reset; prior issued numbers manually voided.'
            payment_sequence.save(update_fields=['next_number', 'revision', 'updated_by', 'adjustment_reason', 'updated_at'])
        from core.services.compliance_audit import record_event
        record_event(
            workflow='portal', action='portal.group.full_reset', category='operations', origin='human',
            deduplication_key=f'portal-full-reset:{configuration.pk}:{uuid.uuid4()}',
            actor=actor, subject_type='group_configuration', subject_id=str(configuration.pk),
            source_model='GroupSheetConfiguration', source_event_id=str(configuration.pk),
            before_values={'case_count': len(farmer_ids), 'order_count': len(order_ids), 'payment_count': len(payment_ids)},
            after_values={'case_count': 0, 'order_count': 0, 'payment_count': 0},
            metadata={
                'backup_reference': str(backup_reference)[:255],
                'sheet_rows_deleted': deleted_sheet_rows,
                'case_references_restarted': case_references_restarted,
            },
            sensitive=False,
        )
    return {
        'cases_deleted': len(farmer_ids), 'sheet_rows_deleted': deleted_sheet_rows,
        'case_references_restarted': case_references_restarted,
    }
