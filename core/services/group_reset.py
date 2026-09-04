"""Configuration-scoped local-data reset utilities.

Each reset profile is an explicit allowlist selected from the workflow stored on
one ``GroupSheetConfiguration``. A configuration reset must never infer that
all records in a shared/global table belong to that configuration.
"""
from __future__ import annotations

from typing import Any

from django.db import transaction

from core.models import (
    CaseUpdate,
    ComplaintCaseControl,
    ComplaintCaseEvidence,
    ComplaintCaseEvent,
    ComplaintCaseImportBatch,
    ComplaintCaseImportItem,
    FcaImportRecord,
    GroupSheetConfiguration,
    JawabuFarmerMaster,
    JawabuFarmerUploadBatch,
    JawabuPipelineEvent,
    JawabuVisitRecord,
    LiveSheetRecordChange,
    MediaAttachment,
    OrderApprovalUpdate,
    ParsedMessage,
    ProcessedMessage,
    RawMessage,
    SpinCreditRequest,
    TatTrackerCase,
    TatTrackerEvent,
)


DEFAULT_SPIN_LEGACY_BATCH_SHEET_NAME = 'SPIN Legacy Batch'
SUPPORTED_RESET_WORKFLOWS = {
    'case',
    'order_approval',
    'jawabu',
    'jawabu_homebiogas',
    'spin_credit_analysis',
    'tat_tracker',
}


def configuration_reset_scope(
    configuration: GroupSheetConfiguration,
) -> tuple[str, str]:
    """Return the routing values used by one reset operation."""
    if not isinstance(configuration, GroupSheetConfiguration):
        raise TypeError('A saved GroupSheetConfiguration is required for a local-data reset.')
    if not configuration.pk:
        raise ValueError('Save the group configuration before resetting its local data.')

    group_id = str(configuration.group_id or '').strip()
    workflow_type = str((configuration.workflow or {}).get('type') or 'case').strip()
    if not group_id:
        raise ValueError('The group configuration has no Telegram group ID.')
    if workflow_type not in SUPPORTED_RESET_WORKFLOWS:
        raise ValueError(
            f'Local-data reset is not supported for workflow {workflow_type or "unconfigured"!r}.'
        )
    return group_id, workflow_type


def group_data_counts(
    configuration: GroupSheetConfiguration,
    *,
    spin_legacy_batch_sheet_name: str = DEFAULT_SPIN_LEGACY_BATCH_SHEET_NAME,
) -> dict[str, int]:
    """Count only records owned by the selected configuration's workflow."""
    group_id, workflow_type = configuration_reset_scope(configuration)
    spin_legacy_name = _spin_legacy_batch_name(spin_legacy_batch_sheet_name)

    if workflow_type == 'case':
        processed_ids, raw_ids = _case_processing_ids(group_id)
        return {
            'parsed_messages': ParsedMessage.objects.filter(group_id=group_id).count(),
            'case_updates': CaseUpdate.objects.filter(parsed_message__group_id=group_id).count(),
            'processed_messages': ProcessedMessage.objects.filter(id__in=processed_ids).count(),
            'raw_messages': RawMessage.objects.filter(id__in=raw_ids).count(),
            'complaint_case_evidence': ComplaintCaseEvidence.objects.filter(
                parsed_message__group_id=group_id,
            ).count(),
            'complaint_case_controls': ComplaintCaseControl.objects.filter(
                parsed_message__group_id=group_id,
            ).count(),
            'complaint_case_events': ComplaintCaseEvent.objects.filter(
                case__parsed_message__group_id=group_id,
            ).count(),
            'complaint_import_batches': ComplaintCaseImportBatch.objects.filter(group_id=group_id).count(),
            'complaint_import_items': ComplaintCaseImportItem.objects.filter(
                batch__group_id=group_id,
            ).count(),
        }

    if workflow_type == 'order_approval':
        return {
            'order_updates': OrderApprovalUpdate.objects.filter(group_id=group_id).count(),
            'media_attachments': MediaAttachment.objects.filter(group_id=group_id).count(),
            'live_sheet_changes': LiveSheetRecordChange.objects.filter(group_id=group_id).count(),
        }

    if workflow_type in {'jawabu', 'jawabu_homebiogas'}:
        return {
            'jawabu_records': JawabuVisitRecord.objects.filter(group_id=group_id).count(),
            'farmer_upload_batches': JawabuFarmerUploadBatch.objects.filter(group_id=group_id).count(),
            'linked_farmer_master_records': _linked_farmer_master_queryset(group_id).count(),
            'fca_records': FcaImportRecord.objects.filter(group_id=group_id).count(),
            'media_attachments': MediaAttachment.objects.filter(group_id=group_id).count(),
            'live_sheet_changes': LiveSheetRecordChange.objects.filter(group_id=group_id).count(),
        }

    if workflow_type == 'spin_credit_analysis':
        return {
            'spin_requests': _spin_live_queryset(group_id, spin_legacy_name).count(),
            'spin_legacy_batch_requests': _spin_legacy_queryset(group_id, spin_legacy_name).count(),
        }

    return {
        'tat_tracker_cases': TatTrackerCase.objects.filter(group_id=group_id).count(),
        'tat_tracker_events': TatTrackerEvent.objects.filter(group_id=group_id).count(),
        'live_sheet_changes': LiveSheetRecordChange.objects.filter(group_id=group_id).count(),
    }


@transaction.atomic
def reset_group_data(
    configuration: GroupSheetConfiguration,
    *,
    include_farmer_uploads: bool = False,
    include_spin_legacy_batch: bool = False,
    spin_legacy_batch_sheet_name: str = DEFAULT_SPIN_LEGACY_BATCH_SHEET_NAME,
) -> dict[str, Any]:
    """Delete local records allowlisted for one saved group configuration.

    Google Sheets rows and actual Google Drive files are intentionally not
    modified. Shared/global records without a configuration ownership key are
    never deleted here.
    """
    # Resolve the saved row again under a lock. Unsaved mutations on a stale
    # model instance must not be able to change the reset profile or group.
    configuration_reset_scope(configuration)
    configuration = GroupSheetConfiguration.objects.select_for_update().get(pk=configuration.pk)
    group_id, workflow_type = configuration_reset_scope(configuration)
    spin_legacy_name = _spin_legacy_batch_name(spin_legacy_batch_sheet_name)
    before = group_data_counts(
        configuration,
        spin_legacy_batch_sheet_name=spin_legacy_name,
    )

    if workflow_type == 'case':
        _reset_complaint_configuration(group_id)
    elif workflow_type == 'order_approval':
        MediaAttachment.objects.filter(group_id=group_id).delete()
        OrderApprovalUpdate.objects.filter(group_id=group_id).delete()
        LiveSheetRecordChange.objects.filter(group_id=group_id).delete()
    elif workflow_type in {'jawabu', 'jawabu_homebiogas'}:
        MediaAttachment.objects.filter(group_id=group_id).delete()
        JawabuVisitRecord.objects.filter(group_id=group_id).delete()
        FcaImportRecord.objects.filter(group_id=group_id).delete()
        LiveSheetRecordChange.objects.filter(group_id=group_id).delete()
        if include_farmer_uploads:
            linked_farmers = _linked_farmer_master_queryset(group_id)
            JawabuPipelineEvent.objects.filter(farmer__in=linked_farmers).delete()
            linked_farmers.delete()
            JawabuFarmerUploadBatch.objects.filter(group_id=group_id).delete()
    elif workflow_type == 'spin_credit_analysis':
        _spin_live_queryset(group_id, spin_legacy_name).delete()
        if include_spin_legacy_batch:
            _spin_legacy_queryset(group_id, spin_legacy_name).delete()
    elif workflow_type == 'tat_tracker':
        TatTrackerCase.objects.filter(group_id=group_id).delete()
        LiveSheetRecordChange.objects.filter(group_id=group_id).delete()

    after = group_data_counts(
        configuration,
        spin_legacy_batch_sheet_name=spin_legacy_name,
    )
    return {
        'configuration_id': str(configuration.pk),
        'group_id': group_id,
        'workflow_type': workflow_type,
        'before': before,
        'after': after,
        'deleted': {
            key: max(before.get(key, 0) - after.get(key, 0), 0)
            for key in before
        },
    }


def _reset_complaint_configuration(group_id: str) -> None:
    processed_ids, raw_ids = _case_processing_ids(group_id)

    # Complaint events and import attribution intentionally use PROTECT during
    # normal operation. This explicitly confirmed reset is the sole destructive
    # path, so clear configuration-owned dependants before their cases.
    ComplaintCaseEvent.objects.filter(case__parsed_message__group_id=group_id).delete()
    ComplaintCaseImportItem.objects.filter(batch__group_id=group_id).delete()
    ComplaintCaseImportBatch.objects.filter(group_id=group_id).delete()
    ComplaintCaseControl.objects.filter(parsed_message__group_id=group_id).delete()
    ComplaintCaseEvidence.objects.filter(parsed_message__group_id=group_id).delete()
    CaseUpdate.objects.filter(parsed_message__group_id=group_id).delete()
    ParsedMessage.objects.filter(group_id=group_id).delete()

    # Deduplication envelopes are removed only when no parsed row from another
    # configuration still references them.
    ProcessedMessage.objects.filter(
        id__in=processed_ids,
        parsed_records__isnull=True,
    ).delete()
    RawMessage.objects.filter(
        id__in=raw_ids,
        processed_records__isnull=True,
    ).delete()


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
