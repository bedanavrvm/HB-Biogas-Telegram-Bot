"""Utilities for clearing locally stored data for one Telegram group."""
from __future__ import annotations

from typing import Any

from django.db import transaction

from core.models import (
    CaseUpdate,
    FcaImportRecord,
    JawabuFarmerMaster,
    JawabuFarmerUploadBatch,
    JawabuVisitRecord,
    LiveSheetRecordChange,
    MediaAttachment,
    OrderApprovalUpdate,
    ParsedMessage,
    ProcessedMessage,
    RawMessage,
)


def group_data_counts(group_id: str) -> dict[str, int]:
    group_id = str(group_id or '')
    processed_ids, raw_ids = _case_processing_ids(group_id)
    return {
        'parsed_messages': ParsedMessage.objects.filter(group_id=group_id).count(),
        'case_updates': CaseUpdate.objects.filter(group_id=group_id).count(),
        'processed_messages': ProcessedMessage.objects.filter(id__in=processed_ids).count(),
        'raw_messages': RawMessage.objects.filter(id__in=raw_ids).count(),
        'order_updates': OrderApprovalUpdate.objects.filter(group_id=group_id).count(),
        'media_attachments': MediaAttachment.objects.filter(group_id=group_id).count(),
        'jawabu_records': JawabuVisitRecord.objects.filter(group_id=group_id).count(),
        'farmer_upload_batches': JawabuFarmerUploadBatch.objects.filter(group_id=group_id).count(),
        'linked_farmer_master_records': _linked_farmer_master_queryset(group_id).count(),
        'all_farmer_master_records': JawabuFarmerMaster.objects.count(),
        'fca_records': FcaImportRecord.objects.filter(group_id=group_id).count(),
        'live_sheet_changes': LiveSheetRecordChange.objects.filter(group_id=group_id).count(),
    }


@transaction.atomic
def reset_group_data(
    group_id: str,
    *,
    include_farmer_uploads: bool = False,
    include_all_farmer_master: bool = False,
) -> dict[str, Any]:
    """Delete all local DB records owned by one Telegram group.

    Google Sheets and Google Drive files are intentionally not modified. Raw and
    processed dedup records are removed only when they are no longer referenced
    by parsed rows after the group rows are deleted.
    """
    group_id = str(group_id or '')
    before = group_data_counts(group_id)
    processed_ids, raw_ids = _case_processing_ids(group_id)

    MediaAttachment.objects.filter(group_id=group_id).delete()
    OrderApprovalUpdate.objects.filter(group_id=group_id).delete()
    JawabuVisitRecord.objects.filter(group_id=group_id).delete()
    if include_farmer_uploads:
        if include_all_farmer_master:
            JawabuFarmerMaster.objects.all().delete()
        else:
            _linked_farmer_master_queryset(group_id).delete()
        JawabuFarmerUploadBatch.objects.filter(group_id=group_id).delete()
    FcaImportRecord.objects.filter(group_id=group_id).delete()
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

    after = group_data_counts(group_id)
    return {
        'group_id': group_id,
        'before': before,
        'after': after,
        'deleted': {
            key: max(before.get(key, 0) - after.get(key, 0), 0)
            for key in before
        },
    }


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
