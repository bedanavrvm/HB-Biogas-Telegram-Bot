"""Explicit Superuser-only destructive cleanup for Origination test records.

This service deliberately touches only Origination database models.  It never
calls Drive, so a purge leaves restricted Drive files in place as requested.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from django.db import transaction
from django.db.models import Q

from core.models import (
    ComplianceAuditEvent,
    LoanOriginationApplication,
    OriginationApplicationDocument,
    OriginationApplicationEvent,
    OriginationCommercialException,
    OriginationCorrectionItem,
    OriginationCorrectionRequest,
    OriginationDataField,
    OriginationDataFieldEvent,
    OriginationDocumentTemplate,
    OriginationDocumentTemplateEvent,
    OriginationFieldReviewIssue,
    OriginationProductDefinition,
    OriginationProductDefinitionEvent,
    OriginationProductDocumentAssignment,
    OriginationReportingValue,
    OriginationRequirementEvidence,
    OriginationReviewerNotice,
    OriginationSigningPackage,
    OriginationSigningAction,
    OriginationSignerSession,
    OriginationOtpChallenge,
    OriginationSigningRequestEvent,
    OriginationStampAsset,
    OriginationTemplateConfigurationRevision,
)


class OriginationGodModeError(ValueError):
    """Stable error exposed by the deliberate Origination-only purge UI."""


ORIGINATION_RESET_MODEL_GROUPS = (
    ('Applications and document packets', (
        LoanOriginationApplication,
        OriginationApplicationDocument,
        OriginationApplicationEvent,
        OriginationCommercialException,
        OriginationCorrectionRequest,
        OriginationCorrectionItem,
        OriginationRequirementEvidence,
        OriginationReviewerNotice,
        OriginationSigningPackage,
        OriginationSigningAction,
        OriginationSignerSession,
        OriginationOtpChallenge,
        OriginationSigningRequestEvent,
        OriginationReportingValue,
    )),
    ('Products and PDF configuration', (
        OriginationProductDefinition,
        OriginationProductDefinitionEvent,
        OriginationDocumentTemplate,
        OriginationProductDocumentAssignment,
        OriginationDocumentTemplateEvent,
        OriginationTemplateConfigurationRevision,
        OriginationFieldReviewIssue,
        OriginationStampAsset,
    )),
    ('Canonical field catalogue', (
        OriginationDataField,
        OriginationDataFieldEvent,
    )),
)
ORIGINATION_RESET_MODELS = tuple(
    model
    for _group_label, models in ORIGINATION_RESET_MODEL_GROUPS
    for model in models
)


def preview_full_origination_reset() -> dict[str, Any]:
    """Count every Origination row that the clean-slate reset will remove."""
    groups = []
    counts = {}
    total = 0
    for group_label, group_models in ORIGINATION_RESET_MODEL_GROUPS:
        model_rows = []
        group_total = 0
        for model in group_models:
            count = model.objects.count()
            counts[model._meta.label] = count
            group_total += count
            model_rows.append({
                'model': model._meta.label,
                'label': str(model._meta.verbose_name_plural).title(),
                'count': count,
            })
        total += group_total
        groups.append({
            'label': group_label,
            'count': group_total,
            'models': model_rows,
        })
    return {'groups': groups, 'counts': counts, 'total': total}


def preview_origination_purge(record: Any) -> list[dict[str, Any]]:
    """Return a concise impact preview without reading or changing Drive."""
    rows: list[tuple[str, int]] = []
    if isinstance(record, OriginationProductDefinition):
        rows = [
            ('Product definition', 1),
            ('Applications', record.applications.count()),
            ('PDF templates', record.document_templates.count()),
            ('Document assignments', record.document_assignments.count()),
            ('Product audit events', record.events.count()),
            ('Field review issues', record.field_review_issues.count()),
        ]
    elif isinstance(record, OriginationDocumentTemplate):
        rows = [
            ('PDF template', 1),
            ('Application document snapshots', record.application_documents.count()),
            ('Product assignments', record.product_assignments.count()),
            ('Calibration revisions', record.configuration_revisions.count()),
            ('Template audit events', record.events.count()),
        ]
    elif isinstance(record, LoanOriginationApplication):
        rows = [
            ('Application', 1),
            ('Packet documents', record.packet_documents.count()),
            ('Application events', record.events.count()),
            ('Commercial exceptions', record.commercial_exceptions.count()),
            ('Requirement evidence records', record.requirement_evidence_files.count()),
            ('Signing packages', record.signing_packages.count()),
            ('Correction requests', record.correction_requests.count()),
            ('Reporting values', record.reporting_values.count()),
        ]
    elif isinstance(record, OriginationProductDocumentAssignment):
        rows = [('Document assignment', 1), ('Application document snapshots', record.application_documents.count())]
    elif isinstance(record, OriginationDataField):
        rows = [
            ('Canonical data field', 1),
            ('Field audit events', record.events.count()),
            ('Reporting values', record.reporting_values.count()),
            ('Review issues', OriginationFieldReviewIssue.objects.filter(
                Q(suggested_field=record) | Q(resolution_field=record),
            ).count()),
        ]
    else:
        rows = [(str(record._meta.verbose_name).title(), 1)]
    return [
        {'label': label, 'count': count}
        for label, count in rows
        if count
    ]


def preview_product_family_purge(product_key: str) -> list[dict[str, Any]]:
    """Preview every Origination-owned row for all versions of one product key."""
    definitions = OriginationProductDefinition.objects.filter(product_key=product_key)
    definition_ids = list(definitions.values_list('pk', flat=True))
    application_ids = LoanOriginationApplication.objects.filter(
        product_definition_id__in=definition_ids,
    ).values_list('pk', flat=True)
    template_ids = OriginationDocumentTemplate.objects.filter(
        product_definition_id__in=definition_ids,
    ).values_list('pk', flat=True)
    rows = [
        ('Product versions', len(definition_ids)),
        ('Applications', application_ids.count()),
        ('Owned PDF templates', template_ids.count()),
        ('Document assignments', OriginationProductDocumentAssignment.objects.filter(product_definition_id__in=definition_ids).count()),
        ('Product audit events', OriginationProductDefinitionEvent.objects.filter(product_definition_id__in=definition_ids).count()),
        ('Application events', OriginationApplicationEvent.objects.filter(application_id__in=application_ids).count()),
        ('Signing packages', OriginationSigningPackage.objects.filter(application_id__in=application_ids).count()),
        ('Requirement evidence records', OriginationRequirementEvidence.objects.filter(application_id__in=application_ids).count()),
    ]
    return [{'label': label, 'count': count} for label, count in rows if count]


def _delete(queryset, counts: Counter[str]) -> int:
    """Delete a queryset without calling model-level immutable ``delete`` hooks."""
    count = queryset.count()
    if count:
        label = queryset.model._meta.verbose_name_plural
        queryset.delete()
        counts[label] += count
    return count


def _purge_application(application_id, counts: Counter[str]) -> None:
    request_ids = OriginationCorrectionRequest.objects.filter(
        application_id=application_id,
    ).values_list('pk', flat=True)
    _delete(OriginationCorrectionItem.objects.filter(correction_request_id__in=request_ids), counts)
    _delete(OriginationCorrectionRequest.objects.filter(application_id=application_id), counts)
    _delete(OriginationRequirementEvidence.objects.filter(application_id=application_id), counts)
    _delete(OriginationApplicationDocument.objects.filter(application_id=application_id), counts)
    package_ids = OriginationSigningPackage.objects.filter(
        application_id=application_id,
    ).values_list('pk', flat=True)
    _delete(OriginationReviewerNotice.objects.filter(application_id=application_id), counts)
    _delete(OriginationSigningAction.objects.filter(package_id__in=package_ids), counts)
    session_ids = OriginationSignerSession.objects.filter(package_id__in=package_ids).values_list('pk', flat=True)
    _delete(OriginationSigningRequestEvent.objects.filter(session_id__in=session_ids), counts)
    _delete(OriginationOtpChallenge.objects.filter(session_id__in=session_ids), counts)
    _delete(OriginationSignerSession.objects.filter(package_id__in=package_ids), counts)
    _delete(OriginationSigningPackage.objects.filter(application_id=application_id), counts)
    _delete(OriginationCommercialException.objects.filter(application_id=application_id), counts)
    _delete(OriginationApplicationEvent.objects.filter(application_id=application_id), counts)
    _delete(OriginationReportingValue.objects.filter(application_id=application_id), counts)
    _delete(LoanOriginationApplication.objects.filter(pk=application_id), counts)


def _purge_assignment(assignment_id, counts: Counter[str]) -> None:
    _delete(OriginationApplicationDocument.objects.filter(assignment_id=assignment_id), counts)
    _delete(OriginationProductDocumentAssignment.objects.filter(pk=assignment_id), counts)


def _purge_template(template_id, counts: Counter[str]) -> None:
    assignment_ids = OriginationProductDocumentAssignment.objects.filter(
        template_id=template_id,
    ).values_list('pk', flat=True)
    _delete(
        OriginationApplicationDocument.objects.filter(
            Q(template_id=template_id) | Q(assignment_id__in=assignment_ids),
        ),
        counts,
    )
    _delete(OriginationProductDocumentAssignment.objects.filter(pk__in=assignment_ids), counts)
    OriginationDocumentTemplate.objects.filter(
        published_configuration_revision__template_id=template_id,
    ).update(published_configuration_revision=None)
    _delete(OriginationDocumentTemplateEvent.objects.filter(template_id=template_id), counts)
    _delete(OriginationTemplateConfigurationRevision.objects.filter(template_id=template_id), counts)
    _delete(OriginationDocumentTemplate.objects.filter(pk=template_id), counts)


def _purge_product_definition(product_id, counts: Counter[str]) -> None:
    for application_id in LoanOriginationApplication.objects.filter(
        product_definition_id=product_id,
    ).values_list('pk', flat=True):
        _purge_application(application_id, counts)
    for template_id in OriginationDocumentTemplate.objects.filter(
        product_definition_id=product_id,
    ).values_list('pk', flat=True):
        _purge_template(template_id, counts)
    for assignment_id in OriginationProductDocumentAssignment.objects.filter(
        product_definition_id=product_id,
    ).values_list('pk', flat=True):
        _purge_assignment(assignment_id, counts)
    _delete(OriginationFieldReviewIssue.objects.filter(product_definition_id=product_id), counts)
    _delete(OriginationProductDefinitionEvent.objects.filter(product_definition_id=product_id), counts)
    # A later product version retains its own snapshots, so its history link
    # must not prevent a deliberate test cleanup of an earlier version.
    OriginationProductDefinition.objects.filter(supersedes_id=product_id).update(supersedes=None)
    _delete(OriginationProductDefinition.objects.filter(pk=product_id), counts)


def _purge_data_field(data_field_id, counts: Counter[str]) -> None:
    _delete(OriginationReportingValue.objects.filter(data_field_id=data_field_id), counts)
    _delete(
        OriginationFieldReviewIssue.objects.filter(
            Q(suggested_field_id=data_field_id) | Q(resolution_field_id=data_field_id),
        ),
        counts,
    )
    _delete(OriginationDataFieldEvent.objects.filter(data_field_id=data_field_id), counts)
    _delete(OriginationDataField.objects.filter(pk=data_field_id), counts)


@transaction.atomic
def purge_origination_product_family(
    *, product_key: str, actor, reason: str, request_id: str,
) -> tuple[dict[str, int], bool]:
    """Purge every Origination version/application for one key; never touch Drive or global Product."""
    if not getattr(actor, 'is_active', False) or not getattr(actor, 'is_superuser', False):
        raise OriginationGodModeError('Product-family purge is available only to an active Django Superuser.')
    key = str(product_key or '').strip()
    normalized_reason = str(reason or '').strip()
    stable_request_id = str(request_id or '').strip()
    if not key or not normalized_reason:
        raise OriginationGodModeError('Choose a product family and provide a reason for this permanent purge.')
    if not stable_request_id:
        raise OriginationGodModeError('A stable request ID is required for an idempotent purge.')
    deduplication_key = f'origination:product-family-purge:{stable_request_id}'
    existing = ComplianceAuditEvent.objects.filter(deduplication_key=deduplication_key).first()
    if existing:
        if existing.subject_id != key:
            raise OriginationGodModeError('This request ID was already used for another product family.')
        return dict((existing.after_values or {}).get('deleted') or {}), True

    definitions = list(
        OriginationProductDefinition.objects.select_for_update().filter(product_key=key).order_by('-version')
    )
    if not definitions:
        existing = ComplianceAuditEvent.objects.filter(deduplication_key=deduplication_key).first()
        if existing and existing.subject_id == key:
            return dict((existing.after_values or {}).get('deleted') or {}), True
        raise OriginationGodModeError('No Origination product family exists for that key.')
    counts: Counter[str] = Counter()
    versions = [item.version for item in definitions]
    for definition in definitions:
        _purge_product_definition(definition.pk, counts)
    from core.services.compliance_audit import record_event
    record_event(
        workflow='loan_origination',
        action='product_family_purged',
        category='administration',
        subject_type='origination_product_family',
        subject_id=key,
        deduplication_key=deduplication_key,
        actor=actor,
        authority_user=actor,
        request_id=stable_request_id,
        before_values={'versions': versions},
        after_values={'deleted': dict(sorted(counts.items())), 'drive_files_untouched': True},
        metadata={'reason': normalized_reason[:500], 'scope': 'origination_only'},
        sensitive=True,
    )
    return dict(sorted(counts.items())), False


@transaction.atomic
def reset_all_origination_data(*, actor, reason: str) -> dict[str, Any]:
    """Empty every Origination model without touching Drive or shared models."""
    if not getattr(actor, 'is_active', False) or not getattr(actor, 'is_superuser', False):
        raise OriginationGodModeError('The full reset is available only to an active Django Superuser.')
    normalized_reason = str(reason or '').strip()
    if not normalized_reason:
        raise OriginationGodModeError('Provide a reason for this permanent reset.')

    before = preview_full_origination_reset()
    deleted: Counter[str] = Counter()

    # Application-owned rows must go before their protected application links.
    _delete(OriginationCorrectionItem.objects.all(), deleted)
    _delete(OriginationCorrectionRequest.objects.all(), deleted)
    _delete(OriginationRequirementEvidence.objects.all(), deleted)
    _delete(OriginationApplicationDocument.objects.all(), deleted)
    _delete(OriginationReviewerNotice.objects.all(), deleted)
    _delete(OriginationSigningAction.objects.all(), deleted)
    _delete(OriginationSigningRequestEvent.objects.all(), deleted)
    _delete(OriginationOtpChallenge.objects.all(), deleted)
    _delete(OriginationSignerSession.objects.all(), deleted)
    _delete(OriginationSigningPackage.objects.all(), deleted)
    _delete(OriginationCommercialException.objects.all(), deleted)
    _delete(OriginationApplicationEvent.objects.all(), deleted)
    _delete(OriginationReportingValue.objects.all(), deleted)
    _delete(LoanOriginationApplication.objects.all(), deleted)

    # Product/template configuration uses protected links in both directions.
    _delete(OriginationProductDocumentAssignment.objects.all(), deleted)
    _delete(OriginationDocumentTemplateEvent.objects.all(), deleted)
    OriginationDocumentTemplate.objects.update(published_configuration_revision=None)
    _delete(OriginationTemplateConfigurationRevision.objects.all(), deleted)
    _delete(OriginationDocumentTemplate.objects.all(), deleted)
    _delete(OriginationFieldReviewIssue.objects.all(), deleted)
    _delete(OriginationProductDefinitionEvent.objects.all(), deleted)
    OriginationProductDefinition.objects.update(supersedes=None)
    _delete(OriginationProductDefinition.objects.all(), deleted)
    _delete(OriginationStampAsset.objects.all(), deleted)

    # Canonical fields are last because reporting values and review issues
    # protect them. Their embedded JSON references disappear with the setup.
    _delete(OriginationDataFieldEvent.objects.all(), deleted)
    _delete(OriginationDataField.objects.all(), deleted)

    after = preview_full_origination_reset()
    remaining = {
        label: count for label, count in after['counts'].items() if count
    }
    if remaining:
        raise OriginationGodModeError(
            f'The reset left Origination records behind: {remaining}'
        )
    return {
        'before': before,
        'deleted': dict(sorted(deleted.items())),
        'after': after,
        'reason': normalized_reason,
    }


@transaction.atomic
def purge_origination_record(*, record: Any, actor, reason: str) -> dict[str, int]:
    """Permanently remove one Origination record and required descendants.

    ``actor`` must be an active Django Superuser.  The caller records the
    confirmation/reason in its operational log; keeping it in an Origination
    event would defeat a request to purge that entire record family.
    """
    if not getattr(actor, 'is_active', False) or not getattr(actor, 'is_superuser', False):
        raise OriginationGodModeError('God mode is available only to an active Django Superuser.')
    if not str(reason or '').strip():
        raise OriginationGodModeError('Provide a reason for this permanent purge.')

    counts: Counter[str] = Counter()
    if isinstance(record, OriginationProductDefinition):
        _purge_product_definition(record.pk, counts)
    elif isinstance(record, OriginationDocumentTemplate):
        _purge_template(record.pk, counts)
    elif isinstance(record, OriginationProductDocumentAssignment):
        _purge_assignment(record.pk, counts)
    elif isinstance(record, OriginationDataField):
        _purge_data_field(record.pk, counts)
    elif isinstance(record, LoanOriginationApplication):
        _purge_application(record.pk, counts)
    elif isinstance(record, OriginationCorrectionRequest):
        _delete(OriginationCorrectionItem.objects.filter(correction_request_id=record.pk), counts)
        _delete(OriginationCorrectionRequest.objects.filter(pk=record.pk), counts)
    elif isinstance(record, OriginationCorrectionItem):
        _delete(OriginationCorrectionItem.objects.filter(pk=record.pk), counts)
    elif isinstance(record, OriginationRequirementEvidence):
        _delete(OriginationRequirementEvidence.objects.filter(pk=record.pk), counts)
    elif isinstance(record, OriginationApplicationDocument):
        _delete(OriginationApplicationDocument.objects.filter(pk=record.pk), counts)
    elif isinstance(record, OriginationSigningPackage):
        _delete(OriginationReviewerNotice.objects.filter(package=record), counts)
        _delete(OriginationSigningAction.objects.filter(package=record), counts)
        session_ids = OriginationSignerSession.objects.filter(package=record).values_list('pk', flat=True)
        _delete(OriginationSigningRequestEvent.objects.filter(session_id__in=session_ids), counts)
        _delete(OriginationOtpChallenge.objects.filter(session_id__in=session_ids), counts)
        _delete(OriginationSignerSession.objects.filter(package=record), counts)
        _delete(OriginationSigningPackage.objects.filter(pk=record.pk), counts)
    elif isinstance(record, OriginationSigningAction):
        _delete(OriginationSigningAction.objects.filter(pk=record.pk), counts)
    elif isinstance(record, OriginationStampAsset):
        _delete(OriginationSigningAction.objects.filter(stamp_asset=record), counts)
        _delete(OriginationStampAsset.objects.filter(pk=record.pk), counts)
    elif isinstance(record, OriginationReportingValue):
        _delete(OriginationReportingValue.objects.filter(pk=record.pk), counts)
    elif isinstance(record, OriginationTemplateConfigurationRevision):
        OriginationDocumentTemplate.objects.filter(
            published_configuration_revision_id=record.pk,
        ).update(published_configuration_revision=None)
        _delete(OriginationTemplateConfigurationRevision.objects.filter(pk=record.pk), counts)
    elif isinstance(record, OriginationDataFieldEvent):
        _delete(OriginationDataFieldEvent.objects.filter(pk=record.pk), counts)
    elif isinstance(record, OriginationDocumentTemplateEvent):
        _delete(OriginationDocumentTemplateEvent.objects.filter(pk=record.pk), counts)
    elif isinstance(record, OriginationProductDefinitionEvent):
        _delete(OriginationProductDefinitionEvent.objects.filter(pk=record.pk), counts)
    elif isinstance(record, OriginationApplicationEvent):
        _delete(OriginationApplicationEvent.objects.filter(pk=record.pk), counts)
    elif isinstance(record, OriginationFieldReviewIssue):
        _delete(OriginationFieldReviewIssue.objects.filter(pk=record.pk), counts)
    else:
        raise OriginationGodModeError('God mode is not configured for this record type.')
    return dict(sorted(counts.items()))
