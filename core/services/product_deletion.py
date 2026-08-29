"""Audited deletion of one unused global product and its owned configuration.

Deleting a Product is intentionally broader than Django's default collector:
product-owned setup may be removed, reusable/audit-bearing associations are
detached, and operational records remain hard blockers.  Google Drive files
are never deleted by this service.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.models import (
    AccessGrant,
    EmergencyAccessGrant,
    JawabuApprovalDelegation,
    JawabuFarmerMaster,
    LoanOriginationApplication,
    OriginationCommercialException,
    OriginationDocumentTemplate,
    OriginationDocumentTemplateEvent,
    OriginationFieldReviewIssue,
    OriginationProductDefinition,
    OriginationProductDefinitionEvent,
    OriginationProductDocumentAssignment,
    OriginationTemplateConfigurationRevision,
    Product,
    ProductAvailability,
    ProductCustomAttribute,
    ProductFee,
    ProductMappingIssue,
    ProductRequirement,
    ProductTatConfiguration,
    ProductVersion,
    ProductVersionEvent,
    SpinCreditRequest,
    TatRepairJob,
    TatTrackerCase,
    WorkflowTatDailyMetric,
)
from core.services.access_grant_governance import governed_access_grant_mutation


class ProductDeletionError(ValueError):
    """Stable, staff-readable reason that a product cannot be deleted."""


# Keep this inventory executable. A future Product FK must receive an explicit
# delete/detach/block policy instead of unexpectedly breaking the Admin action.
REVIEWED_PRODUCT_RELATION_ACCESSORS = frozenset({
    'spin_credit_requests', 'tat_cases', 'tat_repair_jobs',
    'jawabu_farmer_records', 'jawabu_approval_delegations',
    'tat_daily_metrics', 'aliases', 'versions', 'availability_assignments',
    'mapping_issues', 'access_grants', 'emergency_access_grants',
})
REVIEWED_PRODUCT_VERSION_RELATION_ACCESSORS = frozenset({
    'spin_credit_requests', 'tat_cases', 'jawabu_farmer_records',
    'superseded_by_versions', 'fees', 'requirements', 'custom_attributes',
    'tat_configuration', 'events', 'origination_definitions',
    'origination_applications', 'origination_commercial_exceptions',
})
REVIEWED_ORIGINATION_DEFINITION_RELATION_ACCESSORS = frozenset({
    'superseded_by_versions', 'events', 'field_review_issues',
    'document_templates', 'document_assignments', 'applications',
})
REVIEWED_ORIGINATION_TEMPLATE_RELATION_ACCESSORS = frozenset({
    'product_assignments', 'events', 'configuration_revisions',
    'application_documents',
})


@dataclass(frozen=True)
class ProductDeletionPreview:
    product_id: object
    product_code: str
    product_name: str
    blockers: tuple[str, ...]
    delete_counts: dict[str, int]
    detach_counts: dict[str, int]

    @property
    def can_delete(self) -> bool:
        return not self.blockers


def _definition_queryset(product: Product):
    """Include FK-linked definitions and legacy definitions keyed to the product."""
    version_ids = product.versions.values_list('pk', flat=True)
    return OriginationProductDefinition.objects.filter(
        Q(product_version_id__in=version_ids) | Q(product_key=product.code),
    ).distinct()


def _definition_ids(product: Product) -> list[object]:
    # UNION querysets are awkward to reuse in related filters on every
    # supported database. Materialize the small configuration identifier set.
    return list(_definition_queryset(product).values_list('pk', flat=True))


def preview_product_deletion(product: Product) -> ProductDeletionPreview:
    """Classify every known Product relationship before a destructive write."""
    version_ids = list(product.versions.values_list('pk', flat=True))
    definition_ids = _definition_ids(product)
    owned_templates = OriginationDocumentTemplate.objects.filter(
        product_definition_id__in=definition_ids,
    )
    owned_template_ids = list(owned_templates.values_list('pk', flat=True))

    blocker_counts = {
        'SPIN request(s)': SpinCreditRequest.objects.filter(
            Q(product_id=product.pk) | Q(product_version_id__in=version_ids),
        ).distinct().count(),
        'TAT case(s)': TatTrackerCase.objects.filter(
            Q(product_id=product.pk) | Q(product_version_id__in=version_ids),
        ).distinct().count(),
        'TAT repair job(s)': TatRepairJob.objects.filter(product_id=product.pk).count(),
        'farmer/customer workflow record(s)': JawabuFarmerMaster.objects.filter(
            Q(product_id=product.pk) | Q(product_version_id__in=version_ids),
        ).distinct().count(),
        'TAT daily metric(s)': WorkflowTatDailyMetric.objects.filter(
            product_id=product.pk,
        ).count(),
        'loan origination application(s)': LoanOriginationApplication.objects.filter(
            Q(product_definition_id__in=definition_ids)
            | Q(product_version_id__in=version_ids),
        ).distinct().count(),
        'commercial exception(s)': OriginationCommercialException.objects.filter(
            product_version_id__in=version_ids,
        ).count(),
        # A template used by any frozen application is operational evidence,
        # even if a malformed legacy row associates it with another product.
        'application document(s) using a product-owned template': (
            OriginationDocumentTemplate.objects.filter(
                pk__in=owned_template_ids,
                application_documents__isnull=False,
            ).distinct().count()
        ),
    }
    blockers = tuple(
        f'{count} {label}' for label, count in blocker_counts.items() if count
    )
    reviewed_models = (
        (Product, REVIEWED_PRODUCT_RELATION_ACCESSORS),
        (ProductVersion, REVIEWED_PRODUCT_VERSION_RELATION_ACCESSORS),
        (
            OriginationProductDefinition,
            REVIEWED_ORIGINATION_DEFINITION_RELATION_ACCESSORS,
        ),
        (
            OriginationDocumentTemplate,
            REVIEWED_ORIGINATION_TEMPLATE_RELATION_ACCESSORS,
        ),
    )
    unreviewed = []
    for model, reviewed in reviewed_models:
        actual = {relation.get_accessor_name() for relation in model._meta.related_objects}
        unreviewed.extend(
            f'{model.__name__}.{accessor}' for accessor in sorted(actual - reviewed)
        )
    if unreviewed:
        blockers += (
            'unreviewed product relationship policy: ' + ', '.join(unreviewed),
        )

    outside_template_count = 0
    if definition_ids and owned_template_ids:
        outside_template_count = OriginationDocumentTemplate.objects.filter(
            pk__in=owned_template_ids,
            product_assignments__isnull=False,
        ).exclude(
            product_assignments__product_definition_id__in=definition_ids,
        ).distinct().count()

    delete_counts = {
        'aliases': product.aliases.count(),
        'availability_assignments': product.availability_assignments.count(),
        'product_versions': len(version_ids),
        'product_version_events': ProductVersionEvent.objects.filter(
            product_version_id__in=version_ids,
        ).count(),
        'origination_definitions': len(definition_ids),
        'product_owned_templates': max(len(owned_template_ids) - outside_template_count, 0),
    }
    detach_counts = {
        'mapping_issues': ProductMappingIssue.objects.filter(product_id=product.pk).count(),
        'access_grants': AccessGrant.objects.filter(product_ref_id=product.pk).count(),
        'emergency_access_grants': EmergencyAccessGrant.objects.filter(
            product_ref_id=product.pk,
        ).count(),
        'approval_delegations': JawabuApprovalDelegation.objects.filter(
            product_ref_id=product.pk,
        ).count(),
        'shared_templates': outside_template_count,
    }
    return ProductDeletionPreview(
        product_id=product.pk,
        product_code=product.code,
        product_name=product.name,
        blockers=blockers,
        delete_counts=delete_counts,
        detach_counts=detach_counts,
    )


def _rows(queryset) -> list[dict]:
    return list(queryset.order_by('pk').values())


def _configuration_snapshot(
    *, product: Product, version_ids: list[object], definition_ids: list[object],
) -> dict:
    """Copy deleted configuration and native audit rows into compliance evidence."""
    template_ids = list(OriginationDocumentTemplate.objects.filter(
        product_definition_id__in=definition_ids,
    ).values_list('pk', flat=True))
    return {
        'aliases': _rows(product.aliases.all()),
        'availability_assignments': _rows(
            ProductAvailability.objects.filter(product_id=product.pk)
        ),
        'product_versions': _rows(ProductVersion.objects.filter(pk__in=version_ids)),
        'fees': _rows(ProductFee.objects.filter(product_version_id__in=version_ids)),
        'requirements': _rows(ProductRequirement.objects.filter(
            product_version_id__in=version_ids,
        )),
        'custom_attributes': _rows(ProductCustomAttribute.objects.filter(
            product_version_id__in=version_ids,
        )),
        'tat_configuration': _rows(ProductTatConfiguration.objects.filter(
            product_version_id__in=version_ids,
        )),
        'product_version_events': _rows(ProductVersionEvent.objects.filter(
            product_version_id__in=version_ids,
        )),
        'origination_definitions': _rows(OriginationProductDefinition.objects.filter(
            pk__in=definition_ids,
        )),
        'origination_definition_events': _rows(
            OriginationProductDefinitionEvent.objects.filter(
                product_definition_id__in=definition_ids,
            )
        ),
        'origination_field_review_issues': _rows(OriginationFieldReviewIssue.objects.filter(
            product_definition_id__in=definition_ids,
        )),
        'origination_document_assignments': _rows(
            OriginationProductDocumentAssignment.objects.filter(
                product_definition_id__in=definition_ids,
            )
        ),
        'product_owned_document_templates': _rows(OriginationDocumentTemplate.objects.filter(
            pk__in=template_ids,
        )),
        'document_template_events': _rows(OriginationDocumentTemplateEvent.objects.filter(
            template_id__in=template_ids,
        )),
        'document_template_configuration_revisions': _rows(
            OriginationTemplateConfigurationRevision.objects.filter(
                template_id__in=template_ids,
            )
        ),
    }


@transaction.atomic
def delete_product_family(*, product_id, actor, request_id: str = '') -> dict:
    """Delete an unused Product and configuration while preserving operations/audit."""
    if not getattr(actor, 'is_active', False) or not getattr(actor, 'is_superuser', False):
        raise PermissionDenied('Only an active Django Superuser may delete products.')

    stable_request_id = str(request_id or '').strip()
    if not stable_request_id:
        raise ProductDeletionError('A stable request ID is required for product deletion.')
    deduplication_key = f'product-delete:{product_id}:{stable_request_id}'
    from core.models import ComplianceAuditEvent

    existing = ComplianceAuditEvent.objects.filter(
        deduplication_key=deduplication_key,
    ).first()
    if existing:
        if existing.subject_id != str(product_id):
            raise ProductDeletionError('This deletion request ID belongs to another product.')
        after = existing.after_values or {}
        return {
            'product_id': product_id,
            'deleted': after.get('deleted_configuration') or {},
            'detached': after.get('detached') or {},
            'origination_deleted': after.get('origination_deleted') or {},
            'drive_files_untouched': bool(after.get('drive_files_untouched')),
            'replayed': True,
        }

    product = Product.objects.select_for_update().get(pk=product_id)
    preview = preview_product_deletion(product)
    if preview.blockers:
        raise ProductDeletionError(
            f'{product.name} cannot be deleted because it is used by: '
            + '; '.join(preview.blockers)
            + '. Retire the product instead to preserve operational history.'
        )

    now = timezone.now()
    version_ids = list(product.versions.values_list('pk', flat=True))
    definition_ids = _definition_ids(product)
    configuration_snapshot = _configuration_snapshot(
        product=product,
        version_ids=version_ids,
        definition_ids=definition_ids,
    )
    before_values = {
        'product_id': product.pk,
        'code': product.code,
        'name': product.name,
        'category': product.category,
        'active': product.active,
        'description': product.description,
        'sort_order': product.sort_order,
        'delete_counts': preview.delete_counts,
        'detach_counts': preview.detach_counts,
        'configuration_snapshot': configuration_snapshot,
    }

    # Preserve reusable templates. Their assignments to this product are
    # removed with the definitions; ownership is detached first so the
    # Origination cleanup cannot delete a template shared by another product.
    shared_template_ids = list(OriginationDocumentTemplate.objects.filter(
        product_definition_id__in=definition_ids,
        product_assignments__isnull=False,
    ).exclude(
        product_assignments__product_definition_id__in=definition_ids,
    ).distinct().values_list('pk', flat=True))
    if shared_template_ids:
        OriginationDocumentTemplate.objects.filter(
            pk__in=shared_template_ids,
        ).update(product_definition=None)

    # Remove product-specific Origination configuration only. Operational
    # applications and application documents were verified absent above.
    from core.services.origination_god_mode import _purge_product_definition

    origination_counts: Counter[str] = Counter()
    for definition_id in definition_ids:
        _purge_product_definition(definition_id, origination_counts)

    # Version lifecycle events are copied into the immutable compliance chain
    # before their product-owned rows are removed.
    ProductVersionEvent.objects.filter(product_version_id__in=version_ids).delete()
    ProductVersion.objects.filter(supersedes_id__in=version_ids).update(supersedes=None)
    ProductVersion.objects.filter(pk__in=version_ids).delete()

    # These records have their own historical meaning, so retain them while
    # removing live authority and the FK that would block the Product delete.
    with governed_access_grant_mutation('product family deletion'):
        AccessGrant.objects.filter(product_ref_id=product.pk).update(
            product_ref=None,
            active=False,
        )
    EmergencyAccessGrant.objects.filter(product_ref_id=product.pk).update(
        product_ref=None,
        revoked_at=now,
        revoked_by=actor,
        revocation_reason='Product deleted by active Superuser.',
    )
    JawabuApprovalDelegation.objects.filter(product_ref_id=product.pk).update(
        product_ref=None,
        revoked_at=now,
        revoked_by=actor,
        revocation_reason='Product deleted by active Superuser.',
    )
    ProductMappingIssue.objects.filter(product_id=product.pk).update(product=None)

    product_pk = product.pk
    product.delete()  # aliases and availability are product-owned CASCADE rows

    from core.services.compliance_audit import record_event

    record_event(
        workflow='product_catalog',
        action='product.deleted',
        category='configuration',
        subject_type='Product',
        subject_id=str(product_pk),
        actor=actor,
        authority_user=actor,
        request_id=stable_request_id,
        source_model='Product',
        source_event_id=stable_request_id,
        deduplication_key=deduplication_key,
        before_values=before_values,
        after_values={
            'product_deleted': True,
            'deleted_configuration': preview.delete_counts,
            'detached': preview.detach_counts,
            'origination_deleted': dict(sorted(origination_counts.items())),
            'drive_files_untouched': True,
        },
        metadata={'deletion_mode': 'django_admin_superuser_product_family'},
        sensitive=True,
    )
    return {
        'product_id': product_pk,
        'deleted': preview.delete_counts,
        'detached': preview.detach_counts,
        'origination_deleted': dict(sorted(origination_counts.items())),
        'drive_files_untouched': True,
    }
