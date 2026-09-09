"""Guarded clean-slate reset for the global product catalogue.

The reset removes unused draft-only Product families. Products connected to
operational/history records, or carrying governed non-draft versions, are
retained as inactive tombstones so historical foreign keys remain valid.
"""

from __future__ import annotations

from collections import Counter
import hashlib
from typing import Any

from django.db import transaction
from django.utils import timezone

from core.models import (
    AccessGrant,
    ComplianceAuditEvent,
    EmergencyAccessGrant,
    JawabuApprovalDelegation,
    OriginationDocumentProductEligibility,
    Product,
    ProductAvailability,
    ProductMappingIssue,
    ProductVersion,
)
from core.services.access_grant_governance import governed_access_grant_mutation
from core.services.product_deletion import (
    ProductDeletionError,
    delete_product_family,
    preview_product_deletion,
)


class ProductCatalogFullResetError(ValueError):
    """Stable validation failure exposed by the guarded Admin reset UI."""


def _child_request_id(reset_request_id: str, product_id: object) -> str:
    digest = hashlib.sha256(f'{reset_request_id}:{product_id}'.encode('utf-8')).hexdigest()
    return f'product-reset:{digest}'


def preview_full_product_catalog_reset() -> dict[str, Any]:
    """Return hard-deletion, tombstone, and live-authority impact counts."""
    delete_counts: Counter[str] = Counter()
    detach_counts: Counter[str] = Counter()
    tombstone_products = []
    deletable_products = []
    products = list(Product.objects.order_by('sort_order', 'name', 'pk'))
    for product in products:
        preview = preview_product_deletion(product)
        detach_counts.update(preview.detach_counts)
        legacy_statuses = list(product.versions.exclude(
            status=ProductVersion.STATUS_DRAFT,
        ).values_list('status', flat=True).distinct())
        if preview.blockers or legacy_statuses:
            reasons = list(preview.blockers)
            if legacy_statuses:
                reasons.append(
                    'governed legacy version status: ' + ', '.join(sorted(legacy_statuses))
                )
            tombstone_products.append({
                'id': str(product.pk),
                'name': product.name,
                'code': product.code,
                'reasons': reasons,
                'already_inactive': not product.active,
            })
        else:
            deletable_products.append(str(product.pk))
            delete_counts.update(preview.delete_counts)
    delete_counts['products'] = len(deletable_products)
    deletion_rows = [
        {'label': key.replace('_', ' ').title(), 'count': count}
        for key, count in sorted(delete_counts.items())
    ]
    detachment_rows = [
        {'label': key.replace('_', ' ').title(), 'count': count}
        for key, count in sorted(detach_counts.items())
    ]
    return {
        'product_count': len(products),
        'delete_counts': dict(sorted(delete_counts.items())),
        'detach_counts': dict(sorted(detach_counts.items())),
        'groups': [
            {
                'label': 'Unused draft products and owned configuration to hard-delete',
                'count': sum(delete_counts.values()),
                'models': deletion_rows,
            },
            {
                'label': 'Connected or legacy products retained as tombstones',
                'count': len(tombstone_products),
                'models': [{
                    'label': 'Inactive product tombstones',
                    'count': len(tombstone_products),
                }],
            },
            {
                'label': 'Retained records whose product link will be removed or revoked',
                'count': sum(detach_counts.values()),
                'models': detachment_rows,
            },
        ],
        'total': sum(delete_counts.values()),
        'tombstone_products': tombstone_products,
        'tombstone_count': len(tombstone_products),
        'deletable_product_ids': deletable_products,
        'can_reset': True,
    }


def _tombstone_product(*, product: Product, actor, reason: str, request_id: str) -> dict[str, int]:
    """Remove live authority while preserving stable historical references."""
    deduplication_key = f'product-tombstone:{product.pk}:{request_id}'
    existing = ComplianceAuditEvent.objects.filter(deduplication_key=deduplication_key).first()
    if existing:
        return dict((existing.after_values or {}).get('changed') or {})

    now = timezone.now()
    before = {
        'product_id': product.pk,
        'code': product.code,
        'name': product.name,
        'active': product.active,
        'availability_assignments': product.availability_assignments.count(),
        'document_product_eligibilities': product.origination_document_eligibilities.count(),
        'active_access_grants': AccessGrant.objects.filter(
            product_ref=product, active=True,
        ).count(),
        'active_emergency_grants': EmergencyAccessGrant.objects.filter(
            product_ref=product, revoked_at__isnull=True,
        ).count(),
        'active_approval_delegations': JawabuApprovalDelegation.objects.filter(
            product_ref=product, revoked_at__isnull=True,
        ).count(),
    }
    changed = {
        'products_deactivated': int(product.active),
        'availability_assignments_deleted': ProductAvailability.objects.filter(
            product=product,
        ).count(),
        'document_product_eligibilities_deleted': OriginationDocumentProductEligibility.objects.filter(
            product=product,
        ).count(),
        'access_grants_deactivated': AccessGrant.objects.filter(
            product_ref=product, active=True,
        ).count(),
        'emergency_grants_revoked': EmergencyAccessGrant.objects.filter(
            product_ref=product, revoked_at__isnull=True,
        ).count(),
        'approval_delegations_revoked': JawabuApprovalDelegation.objects.filter(
            product_ref=product, revoked_at__isnull=True,
        ).count(),
        'mapping_issues_detached': ProductMappingIssue.objects.filter(product=product).count(),
    }
    ProductAvailability.objects.filter(product=product).delete()
    OriginationDocumentProductEligibility.objects.filter(product=product).delete()
    with governed_access_grant_mutation('product catalogue tombstone reset'):
        AccessGrant.objects.filter(product_ref=product).update(product_ref=None, active=False)
    EmergencyAccessGrant.objects.filter(
        product_ref=product, revoked_at__isnull=True,
    ).update(
        product_ref=None, revoked_at=now, revoked_by=actor,
        revocation_reason='Product retained as a tombstone during catalogue reset.',
    )
    EmergencyAccessGrant.objects.filter(product_ref=product).update(product_ref=None)
    JawabuApprovalDelegation.objects.filter(
        product_ref=product, revoked_at__isnull=True,
    ).update(
        product_ref=None, revoked_at=now, revoked_by=actor,
        revocation_reason='Product retained as a tombstone during catalogue reset.',
    )
    JawabuApprovalDelegation.objects.filter(product_ref=product).update(product_ref=None)
    ProductMappingIssue.objects.filter(product=product).update(product=None)
    Product.objects.filter(pk=product.pk).update(active=False, updated_at=now)

    from core.services.compliance_audit import record_event

    record_event(
        workflow='product_catalog',
        action='product.tombstoned',
        category='configuration',
        subject_type='Product',
        subject_id=str(product.pk),
        actor=actor,
        authority_user=actor,
        request_id=request_id,
        source_model='Product',
        deduplication_key=deduplication_key,
        before_values=before,
        after_values={
            'active': False,
            'changed': changed,
            'historical_references_preserved': True,
        },
        metadata={
            'reason': reason,
            'deletion_mode': 'inactive_historical_tombstone',
        },
        sensitive=True,
    )
    return changed


@transaction.atomic
def reset_full_product_catalog(*, actor, reason: str, request_id: str) -> dict[str, Any]:
    """Delete unused products and tombstone connected or legacy products."""
    if not getattr(actor, 'is_active', False) or not getattr(actor, 'is_superuser', False):
        raise ProductCatalogFullResetError(
            'The product catalogue reset is available only to an active Django Superuser.'
        )
    normalized_reason = str(reason or '').strip()
    if not normalized_reason:
        raise ProductCatalogFullResetError('Provide a reason for this permanent reset.')
    if len(normalized_reason) > 500:
        raise ProductCatalogFullResetError('The reset reason must be 500 characters or fewer.')
    stable_request_id = str(request_id or '').strip()
    if not stable_request_id:
        raise ProductCatalogFullResetError('A stable reset request ID is required.')
    if len(stable_request_id) > 128:
        raise ProductCatalogFullResetError('The reset request ID must be 128 characters or fewer.')

    deduplication_key = f'product-catalog:full-reset:{stable_request_id}'
    existing = ComplianceAuditEvent.objects.filter(deduplication_key=deduplication_key).first()
    if existing:
        existing_reason = str((existing.metadata or {}).get('reason') or '')
        if existing_reason != normalized_reason:
            raise ProductCatalogFullResetError(
                'This reset request ID was already used with a different reason.'
            )
        return {
            'before': dict(existing.before_values or {}),
            'after': preview_full_product_catalog_reset(),
            'deleted': dict((existing.after_values or {}).get('deleted') or {}),
            'detached': dict((existing.after_values or {}).get('detached') or {}),
            'tombstoned': dict((existing.after_values or {}).get('tombstoned') or {}),
            'replayed': True,
        }

    products = list(Product.objects.select_for_update().order_by('pk'))
    before = preview_full_product_catalog_reset()

    deleted: Counter[str] = Counter()
    detached: Counter[str] = Counter()
    tombstoned: Counter[str] = Counter()
    tombstone_ids = {item['id'] for item in before['tombstone_products']}
    for product in products:
        preview = preview_product_deletion(product)
        if str(product.pk) in tombstone_ids:
            tombstoned.update(_tombstone_product(
                product=product,
                actor=actor,
                reason=normalized_reason,
                request_id=_child_request_id(stable_request_id, product.pk),
            ))
            continue
        deleted.update(preview.delete_counts)
        detached.update(preview.detach_counts)
        try:
            delete_product_family(
                product_id=product.pk,
                actor=actor,
                request_id=_child_request_id(stable_request_id, product.pk),
            )
        except ProductDeletionError as exc:
            raise ProductCatalogFullResetError(str(exc)) from exc
    deleted['products'] += len(products)
    deleted['products'] -= len(tombstone_ids)

    after = preview_full_product_catalog_reset()
    if Product.objects.filter(active=True).exists() or after['deletable_product_ids']:
        raise ProductCatalogFullResetError(
            'The reset left active or safely deletable product catalogue records behind.'
        )

    from core.services.compliance_audit import record_event

    record_event(
        workflow='product_catalog',
        action='database_reset',
        category='administration',
        subject_type='product_catalog',
        subject_id='all',
        actor=actor,
        authority_user=actor,
        request_id=stable_request_id,
        source_model='Product',
        deduplication_key=deduplication_key,
        before_values=before,
        after_values={
            'deleted': dict(sorted(deleted.items())),
            'detached': dict(sorted(detached.items())),
            'tombstoned': dict(sorted(tombstoned.items())),
            'tombstone_product_ids': sorted(tombstone_ids),
            'external_systems_untouched': True,
        },
        metadata={
            'reason': normalized_reason,
            'scope': 'global_product_catalogue_only',
            'operational_records_deleted': False,
            'historical_references_tombstoned': True,
            'drive_files_untouched': True,
        },
        sensitive=True,
    )
    return {
        'before': before,
        'after': after,
        'deleted': dict(sorted(deleted.items())),
        'detached': dict(sorted(detached.items())),
        'tombstoned': dict(sorted(tombstoned.items())),
        'replayed': False,
    }
