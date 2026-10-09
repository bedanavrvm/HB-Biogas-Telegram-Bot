"""Atomic, testing-gated selected global product and Origination-history deletion."""
from collections import Counter
import hashlib
import re

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q

from core.models import ComplianceAuditEvent, Product, ProductVersion
from core.services.compliance_audit import record_event
from core.services.product_deletion import (
    ProductDeletionError, _definition_ids, _shared_owned_templates, delete_product_family, preview_product_deletion,
)
from origination.models import (
    LoanOriginationApplication, OriginationApplicationDocument, OriginationCommercialException,
    OriginationDocumentTemplate, OriginationProductDefinition, OriginationProductDocumentAssignment, OriginationSigningPackage,
)
from origination.services.origination_god_mode import _purge_application


APPLICATION_RELATIONS = frozenset({
    'replacement_applications', 'commercial_exceptions', 'reporting_values', 'events',
    'reviewer_notices', 'correction_requests', 'requirement_evidence_files', 'packet_documents', 'signing_packages',
})


def _authorize(actor):
    if not (getattr(settings, 'ORIGINATION_PRODUCT_FAMILY_PURGE_ENABLED', False)
            and getattr(actor, 'is_active', False) and getattr(actor, 'is_superuser', False)):
        raise PermissionDenied('Permanent product deletion requires the purge setting and an active Superuser.')


def _selection(product_ids):
    # Product uses integer identities. Reject malformed scope instead of dropping it.
    try:
        values = list(product_ids)
        if any(isinstance(value, bool) or not re.fullmatch(r'[0-9]+', str(value)) for value in values):
            raise ValueError('Invalid product identity.')
        ids = sorted({int(value) for value in values})
    except (TypeError, ValueError) as exc:
        raise ProductDeletionError('Choose valid products to delete.') from exc
    if not ids or any(value <= 0 for value in ids):
        raise ProductDeletionError('Choose at least one product to delete.')
    return ids


def _plan(products):
    versions = list(ProductVersion.objects.filter(product_id__in=[p.pk for p in products]).values_list('pk', flat=True))
    definitions = sorted({pk for product in products for pk in _definition_ids(product)}, key=str)
    applications = list(LoanOriginationApplication.objects.filter(
        Q(product_definition_id__in=definitions) | Q(product_version_id__in=versions),
    ).order_by('pk').values_list('pk', flat=True))
    blockers = [f'{p.name}: {reason}' for p in products
                for reason in preview_product_deletion(p, include_origination_history=True).blockers]
    outside = OriginationProductDefinition.objects.filter(pk__in=definitions).exclude(
        Q(product_version_id__in=versions) | Q(product_version__isnull=True),
    ).exists()
    if outside:
        blockers.append('An Origination definition is linked to an unselected product.')
    if LoanOriginationApplication.objects.filter(pk__in=applications).exclude(product_definition_id__in=definitions).exists():
        blockers.append('An application has inconsistent product references. Correct its ownership before deletion.')
    if LoanOriginationApplication.objects.filter(supersedes_application_id__in=applications).exclude(pk__in=applications).exists():
        blockers.append('An unselected application retains a history link to a selected application.')
    if OriginationProductDefinition.objects.filter(supersedes_id__in=definitions).exclude(pk__in=definitions).exists():
        blockers.append('An unselected product definition retains a history link to selected configuration.')
    if ProductVersion.objects.filter(supersedes_id__in=versions).exclude(pk__in=versions).exists():
        blockers.append('An unselected product version retains a history link to selected terms.')
    assignments = OriginationProductDocumentAssignment.objects.filter(
        product_definition_id__in=definitions,
    ).values_list('pk', flat=True)
    if OriginationApplicationDocument.objects.filter(assignment_id__in=assignments).exclude(application_id__in=applications).exists():
        blockers.append('An unselected application still uses a selected document assignment.')
    if OriginationCommercialException.objects.filter(product_version_id__in=versions).exclude(application_id__in=applications).exists():
        blockers.append('An unselected application uses a selected commercial exception.')
    actual = {r.get_accessor_name() for r in LoanOriginationApplication._meta.related_objects}
    if actual != APPLICATION_RELATIONS:
        blockers.append('Unreviewed Origination application relationship policy. Ask IT to review deletion scope.')
    return {'versions': versions, 'definitions': definitions, 'applications': applications,
            'blockers': blockers}


def preview_permanent_product_deletion(*, product_ids, actor) -> dict:
    _authorize(actor)
    ids = _selection(product_ids)
    products = list(Product.objects.filter(pk__in=ids).order_by('pk'))
    if len(products) != len(ids):
        raise ProductDeletionError('The selection changed. Refresh the product list.')
    plan = _plan(products)
    return {'products': products, 'product_ids': ids, 'blockers': plan['blockers'],
            'applications': len(plan['applications']), 'versions': len(plan['versions']),
            'definitions': len(plan['definitions']),
            'signing_packages': OriginationSigningPackage.objects.filter(application_id__in=plan['applications']).count()}


@transaction.atomic
def delete_selected_products_permanently(*, product_ids, actor, request_id: str) -> dict:
    _authorize(actor)
    ids = _selection(product_ids)
    key = str(request_id or '').strip()
    if not re.fullmatch(r'[A-Za-z0-9._-]{1,128}', key):
        raise ProductDeletionError('A valid, stable request ID is required.')
    dedup = f'product-permanent-delete:{key}'
    digest = hashlib.sha256(','.join(map(str, ids)).encode()).hexdigest()

    def replay():
        event = ComplianceAuditEvent.objects.filter(deduplication_key=dedup).first()
        if event:
            if event.actor_id != actor.pk or event.subject_id != digest:
                raise ProductDeletionError('This request ID was already used by a different actor or selection.')
            return {**event.after_values, 'replayed': True}
        return None

    previous = replay()
    if previous:
        return previous
    products = list(Product.objects.select_for_update().filter(pk__in=ids).order_by('pk'))
    previous = replay()
    if previous:
        return previous
    if len(products) != len(ids):
        raise ProductDeletionError('The selection changed. No products were deleted; refresh the list.')
    plan = _plan(products)
    # Parent locks prevent new FK references while child sets are stabilized.
    list(ProductVersion.objects.select_for_update(of=('self',)).filter(pk__in=plan['versions']).order_by('pk'))
    list(OriginationProductDefinition.objects.select_for_update(of=('self',)).filter(pk__in=plan['definitions']).order_by('pk'))
    list(LoanOriginationApplication.objects.select_for_update(of=('self',)).filter(pk__in=plan['applications']).order_by('pk'))
    list(OriginationDocumentTemplate.objects.select_for_update(of=('self',)).filter(
        product_definition_id__in=plan['definitions'],
    ).order_by('pk'))
    list(OriginationProductDocumentAssignment.objects.select_for_update(of=('self',)).filter(
        product_definition_id__in=plan['definitions'],
    ).order_by('pk'))
    plan = _plan(products)
    if plan['blockers']:
        raise ProductDeletionError('No products were deleted. ' + '; '.join(plan['blockers']))
    application_manifest = list(LoanOriginationApplication.objects.filter(
        pk__in=plan['applications'],
    ).order_by('pk').values('id', 'status', 'revision'))
    counts = Counter()
    for application_id in plan['applications']:
        _purge_application(application_id, counts)
    retained_templates = []
    for product in products:
        definitions = _definition_ids(product)
        templates = list(OriginationDocumentTemplate.objects.filter(product_definition_id__in=definitions).values_list('pk', flat=True))
        shared = list(_shared_owned_templates(product=product, definition_ids=definitions,
                                             template_ids=templates).values_list('pk', flat=True))
        OriginationDocumentTemplate.objects.filter(pk__in=shared).update(product_definition=None)
        retained_templates.extend(map(str, shared))
    family_key = 'permanent-' + hashlib.sha256(key.encode()).hexdigest()
    outcomes = [delete_product_family(product_id=product.pk, actor=actor, request_id=family_key)
                for product in products]
    result = {'product_ids': ids, 'origination_deleted': dict(sorted(counts.items())),
              'products_deleted': len(ids), 'external_files_untouched': True}
    record_event(
        workflow='product_catalog', action='product.selection_permanently_deleted', category='configuration',
        subject_type='ProductSelection', subject_id=digest, actor=actor, authority_user=actor,
        request_id=key, deduplication_key=dedup,
        before_values={'product_ids': ids, 'applications': application_manifest}, after_values=result,
        metadata={'families': outcomes, 'retained_shared_templates': retained_templates,
                  'deletion_mode': 'selected_products_and_origination_history'}, sensitive=True,
    )
    return result
