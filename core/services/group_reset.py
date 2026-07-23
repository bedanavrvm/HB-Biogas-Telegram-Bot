"""Utilities for clearing locally stored data for one Telegram group."""
from __future__ import annotations

from typing import Any

from django.db import transaction

from core.models import (
    CaseUpdate,
    ComplaintCaseEvidence,
    FcaImportRecord,
    InvoiceUploadBatch,
    JawabuFarmerMaster,
    JawabuFarmerUploadBatch,
    JawabuVisitRecord,
    LiveSheetRecordChange,
    MediaAttachment,
    OrderApprovalUpdate,
    PaymentDocument,
    ParsedMessage,
    ProcessedMessage,
    RawMessage,
    RequisitionBatch,
    SpinCreditRequest,
    TatTrackerCase,
    TatTrackerEvent,
)

DEFAULT_SPIN_LEGACY_BATCH_SHEET_NAME = 'SPIN Legacy Batch'


def group_data_counts(
    group_id: str,
    *,
    spin_legacy_batch_sheet_name: str = DEFAULT_SPIN_LEGACY_BATCH_SHEET_NAME,
) -> dict[str, int]:
    group_id = str(group_id or '')
    spin_legacy_name = _spin_legacy_batch_name(spin_legacy_batch_sheet_name)
    processed_ids, raw_ids = _case_processing_ids(group_id)
    return {
        'parsed_messages': ParsedMessage.objects.filter(group_id=group_id).count(),
        'case_updates': CaseUpdate.objects.filter(group_id=group_id).count(),
        'processed_messages': ProcessedMessage.objects.filter(id__in=processed_ids).count(),
        'raw_messages': RawMessage.objects.filter(id__in=raw_ids).count(),
        'order_updates': OrderApprovalUpdate.objects.filter(group_id=group_id).count(),
        'media_attachments': MediaAttachment.objects.filter(group_id=group_id).count(),
        'complaint_case_evidence': ComplaintCaseEvidence.objects.filter(group_id=group_id).count(),
        'jawabu_records': JawabuVisitRecord.objects.filter(group_id=group_id).count(),
        'farmer_upload_batches': JawabuFarmerUploadBatch.objects.filter(group_id=group_id).count(),
        'linked_farmer_master_records': _linked_farmer_master_queryset(group_id).count(),
        'all_farmer_master_records': JawabuFarmerMaster.objects.count(),
        'requisition_batches': RequisitionBatch.objects.count(),
        'invoice_upload_batches': InvoiceUploadBatch.objects.count(),
        'payment_documents': PaymentDocument.objects.count(),
        'fca_records': FcaImportRecord.objects.filter(group_id=group_id).count(),
        'spin_requests': _spin_live_queryset(group_id, spin_legacy_name).count(),
        'spin_legacy_batch_requests': _spin_legacy_queryset(group_id, spin_legacy_name).count(),
        'tat_tracker_cases': TatTrackerCase.objects.filter(group_id=group_id).count(),
        'tat_tracker_events': TatTrackerEvent.objects.filter(group_id=group_id).count(),
        'live_sheet_changes': LiveSheetRecordChange.objects.filter(group_id=group_id).count(),
    }


@transaction.atomic
def reset_group_data(
    group_id: str,
    *,
    include_farmer_uploads: bool = False,
    include_all_farmer_master: bool = False,
    include_order_records: bool = False,
    include_drive_upload_records: bool = False,
    include_spin_legacy_batch: bool = False,
    spin_legacy_batch_sheet_name: str = DEFAULT_SPIN_LEGACY_BATCH_SHEET_NAME,
) -> dict[str, Any]:
    """Delete all local DB records owned by one Telegram group.

    Google Sheets and actual Google Drive files are intentionally not modified.
    Raw and processed dedup records are removed only when they are no longer
    referenced by parsed rows after the group rows are deleted.
    """
    group_id = str(group_id or '')
    spin_legacy_name = _spin_legacy_batch_name(spin_legacy_batch_sheet_name)
    before = group_data_counts(group_id, spin_legacy_batch_sheet_name=spin_legacy_name)
    processed_ids, raw_ids = _case_processing_ids(group_id)

    MediaAttachment.objects.filter(group_id=group_id).delete()
    if include_drive_upload_records:
        ComplaintCaseEvidence.objects.filter(group_id=group_id).delete()
        InvoiceUploadBatch.objects.all().delete()
    if include_order_records:
        PaymentDocument.objects.all().delete()
        RequisitionBatch.objects.all().delete()
    OrderApprovalUpdate.objects.filter(group_id=group_id).delete()
    JawabuVisitRecord.objects.filter(group_id=group_id).delete()
    if include_farmer_uploads:
        if include_all_farmer_master:
            JawabuFarmerMaster.objects.all().delete()
        else:
            _linked_farmer_master_queryset(group_id).delete()
        JawabuFarmerUploadBatch.objects.filter(group_id=group_id).delete()
    FcaImportRecord.objects.filter(group_id=group_id).delete()
    _spin_live_queryset(group_id, spin_legacy_name).delete()
    if include_spin_legacy_batch:
        _spin_legacy_queryset(group_id, spin_legacy_name).delete()
    TatTrackerCase.objects.filter(group_id=group_id).delete()
    LiveSheetRecordChange.objects.filter(group_id=group_id).delete()
    CaseUpdate.objects.filter(group_id=group_id).delete()
    ParsedMessage.objects.filter(group_id=group_id).delete()

    ProcessedMessage.objects.filter(
        id__in=processed_ids,
        parsed_records__isnull=True,
    ).delete()
    RawMessage.objects.filter(
        id__in=raw_ids,
        processed_records__isnull=True,
    ).delete()

    after = group_data_counts(group_id, spin_legacy_batch_sheet_name=spin_legacy_name)
    return {
        'group_id': group_id,
        'before': before,
        'after': after,
        'deleted': {
            key: max(before.get(key, 0) - after.get(key, 0), 0)
            for key in before
        },
    }


def _spin_legacy_batch_name(value: str) -> str:
    name = str(value or DEFAULT_SPIN_LEGACY_BATCH_SHEET_NAME).strip()
    return name or DEFAULT_SPIN_LEGACY_BATCH_SHEET_NAME


def _spin_live_queryset(group_id: str, legacy_sheet_name: str):
    return SpinCreditRequest.objects.filter(group_id=str(group_id or '')).exclude(sheet_name=legacy_sheet_name)


def _spin_legacy_queryset(group_id: str, legacy_sheet_name: str):
    return SpinCreditRequest.objects.filter(group_id=str(group_id or ''), sheet_name=legacy_sheet_name)


def _linked_farmer_master_queryset(group_id: str):
    batch_ids = [
        str(value)
        for value in JawabuFarmerUploadBatch.objects
        .filter(group_id=str(group_id or ''))
        .values_list('id', flat=True)
    ]
    if not batch_ids:
        return JawabuFarmerMaster.objects.none()
    query = JawabuFarmerMaster.objects.none()
    for batch_id in batch_ids:
        query = query | JawabuFarmerMaster.objects.filter(raw_data__upload_batch_id=batch_id)
    return query.distinct()


def _case_processing_ids(group_id: str) -> tuple[list[str], list[str]]:
    parsed = ParsedMessage.objects.filter(group_id=str(group_id or ''))
    processed_ids = list(
        parsed
        .exclude(processed_message_id=None)
        .values_list('processed_message_id', flat=True)
        .distinct()
    )
    raw_ids = list(
        ProcessedMessage.objects
        .filter(id__in=processed_ids)
        .values_list('raw_message_id', flat=True)
        .distinct()
    )
    return processed_ids, raw_ids
