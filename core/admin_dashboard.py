from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from django.db.models import Count, Q, QuerySet
from django.urls import reverse
from django.utils import timezone

from core.models import (
    ComplaintCaseEvidence,
    FcaImportRecord,
    GroupSheetConfiguration,
    JawabuDataQualityIssue,
    JawabuFarmerMaster,
    JawabuFarmerUploadBatch,
    JawabuVisitRecord,
    MediaAttachment,
    OrderApprovalUpdate,
    ParsedMessage,
    PaymentDocument,
    RequisitionBatch,
    SpinCreditRequest,
    TatTrackerCase,
    TatTrackerEvent,
    UserProfile,
)


@dataclass(frozen=True)
class StatusGroup:
    label: str
    count: int
    tone: str = 'muted'


def dashboard_callback(request, context: dict[str, Any]) -> dict[str, Any]:
    """Populate the Unfold index with aggregate operational state only.

    The dashboard is intentionally an exception-first control surface.  It
    links to the existing Admin changelists, but never renders customer names,
    raw messages, phone numbers, document contents, or other private payloads.
    """
    now = timezone.now()
    last_day = now - timezone.timedelta(hours=24)
    last_week = now - timezone.timedelta(days=7)

    active_tat_cases = TatTrackerCase.objects.filter(is_deleted=False)
    enabled_groups = GroupSheetConfiguration.objects.filter(enabled=True)
    active_farmers = JawabuFarmerMaster.objects.filter(status='active')
    pending_spin = SpinCreditRequest.objects.filter(import_status='review_needed')
    pending_payment_review = PaymentDocument.objects.filter(status='pending_review')
    pending_uploads = JawabuFarmerUploadBatch.objects.filter(status='pending_review')
    open_orders = RequisitionBatch.objects.exclude(status='completed')
    active_quality_issues = JawabuDataQualityIssue.objects.filter(active=True)

    context['ops_dashboard'] = {
        'generated_at': timezone.localtime(now),
        'cards': [
            {
                'title': 'Complaint Cases',
                'value': ParsedMessage.objects.count(),
                'detail': f"{ParsedMessage.objects.filter(created_at__gte=last_week).count()} created in 7 days",
                'url': reverse('admin:core_parsedmessage_changelist'),
            },
            {
                'title': 'SPIN Requests',
                'value': SpinCreditRequest.objects.count(),
                'detail': f"{pending_spin.count()} need analyst review",
                'url': reverse('admin:core_spincreditrequest_changelist'),
            },
            {
                'title': 'Active TAT Cases',
                'value': active_tat_cases.count(),
                'detail': f"{TatTrackerEvent.objects.filter(created_at__gte=last_day).count()} stage events in 24h",
                'url': reverse('admin:core_tattrackercase_changelist'),
            },
            {
                'title': 'Enabled Groups',
                'value': enabled_groups.count(),
                'detail': 'Configured Telegram workflows',
                'url': reverse('admin:core_groupsheetconfiguration_changelist'),
            },
            {
                'title': 'Jawabu Pipeline',
                'value': active_farmers.count(),
                'detail': f'{pending_uploads.count()} upload batch(es) awaiting review',
                'url': reverse('admin:core_jawabufarmermaster_changelist'),
            },
            {
                'title': 'Orders and Payments',
                'value': open_orders.count(),
                'detail': f'{pending_payment_review.count()} payment document(s) awaiting review',
                'url': reverse('admin:core_requisitionbatch_changelist'),
            },
            {
                'title': 'Data Quality',
                'value': active_quality_issues.count(),
                'detail': 'Active issues requiring attention',
                'url': reverse('admin:core_jawabudataqualityissue_changelist'),
            },
            {
                'title': 'Staff Access',
                'value': UserProfile.objects.filter(user__is_active=True).count(),
                'detail': 'Active canonical staff profiles',
                'url': reverse('admin:auth_user_changelist'),
            },
        ],
        'status_sections': [
            {
                'title': 'Complaint Status',
                'items': _status_counts(ParsedMessage.objects.all(), 'complaint_status', empty_label='Unspecified'),
            },
            {
                'title': 'SPIN Import Status',
                'items': _status_counts(SpinCreditRequest.objects.all(), 'import_status'),
            },
            {
                'title': 'TAT Case Status',
                'items': _status_counts(active_tat_cases, 'status'),
            },
            {
                'title': 'Workflow Groups',
                'items': _status_counts(enabled_groups, 'workflow__type', empty_label='Unspecified'),
            },
            {
                'title': 'Payment Documents',
                'items': _status_counts(PaymentDocument.objects.all(), 'status'),
            },
        ],
        'alerts': [
            {
                'label': 'Complaint sheet sync failures',
                'count': ParsedMessage.objects.filter(Q(synced_to_sheets=False) | ~Q(last_sync_error='')).count(),
                'url': reverse('admin:core_parsedmessage_changelist'),
            },
            {
                'label': 'SPIN sheet sync failures',
                'count': SpinCreditRequest.objects.exclude(sync_error='').count(),
                'url': reverse('admin:core_spincreditrequest_changelist'),
            },
            {
                'label': 'TAT sheet sync failures',
                'count': active_tat_cases.exclude(sync_error='').count(),
                'url': reverse('admin:core_tattrackercase_changelist'),
            },
            {
                'label': 'Unsynced TAT events',
                'count': TatTrackerEvent.objects.filter(synced_to_sheet=False).count(),
                'url': reverse('admin:core_tattrackerevent_changelist'),
            },
            {
                'label': 'Failed media uploads',
                'count': _failed_media_count(),
                'url': reverse('admin:core_mediaattachment_changelist'),
            },
            {
                'label': 'Failed imports',
                'count': _failed_import_count(),
                'url': reverse('admin:core_fcaimportrecord_changelist'),
            },
            {
                'label': 'Jawabu upload batches awaiting review',
                'count': pending_uploads.count(),
                'url': reverse('admin:core_jawabufarmeruploadbatch_changelist'),
            },
            {
                'label': 'Payment documents awaiting review',
                'count': pending_payment_review.count(),
                'url': reverse('admin:core_paymentdocument_changelist'),
            },
            {
                'label': 'Active data quality issues',
                'count': active_quality_issues.count(),
                'url': reverse('admin:core_jawabudataqualityissue_changelist'),
            },
            {
                'label': 'Orders still in progress',
                'count': open_orders.count(),
                'url': reverse('admin:core_requisitionbatch_changelist'),
            },
        ],
    }
    return context


def _status_counts(queryset: QuerySet, field: str, *, empty_label: str = 'Blank') -> list[StatusGroup]:
    groups = queryset.values(field).annotate(total=Count('pk')).order_by('-total', field)[:8]
    return [
        StatusGroup(
            label=str(row[field] or empty_label),
            count=row['total'],
            tone=_status_tone(str(row[field] or '')),
        )
        for row in groups
    ]


def _status_tone(value: str) -> str:
    normalized = value.lower().strip().replace(' ', '_')
    if normalized in {'completed', 'closed', 'success', 'synced', 'imported', 'disbursed'}:
        return 'success'
    if normalized in {'failed', 'rejected', 'declined', 'duplicate', 'duplicate_review'}:
        return 'danger'
    if normalized in {
        'pending', 'review_needed', 'pending_docs', 'active', 'in_progress',
        'awaiting_review', 'awaiting_analysis', 'awaiting_signature', 'under_review',
    }:
        return 'warning'
    return 'muted'


def _failed_media_count() -> int:
    return (
        MediaAttachment.objects.filter(upload_status='failed').count()
        + ComplaintCaseEvidence.objects.filter(upload_status='failed').count()
        + OrderApprovalUpdate.objects.filter(update_status='failed').count()
    )


def _failed_import_count() -> int:
    models: Iterable[type] = (FcaImportRecord, JawabuVisitRecord)
    return sum(model.objects.filter(import_status='failed').count() for model in models)
