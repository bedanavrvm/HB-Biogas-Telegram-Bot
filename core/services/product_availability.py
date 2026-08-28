"""Governed bulk availability management for the global product catalogue."""

from __future__ import annotations

import re

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from core.models import OperationalLocation, Product, ProductAvailability


CANONICAL_PRODUCT_CHANNEL = 'portal'
PRODUCT_WORKFLOW_CHOICES = (
    ('jawabu_portal', 'Jawabu Portal'),
    ('loan_origination', 'Loan Origination'),
    ('tat_tracker', 'TAT Tracker'),
    ('spin_credit_analysis', 'SPIN / Credit Analysis'),
    ('order_approval', 'Order Approval'),
    ('complaint_cases', 'Complaint Cases'),
)
PRODUCT_WORKFLOWS = {key for key, _label in PRODUCT_WORKFLOW_CHOICES}


def _guard(actor) -> None:
    if not getattr(actor, 'is_active', False) or not getattr(actor, 'is_superuser', False):
        raise PermissionDenied


def _request_id(value: object) -> str:
    request_id = re.sub(r'[^A-Za-z0-9._-]', '', str(value or ''))[:128]
    if not request_id:
        raise ValidationError('Reload this page before saving; its request identifier is missing.')
    return request_id


def _audit(*, product, actor, request_id, action, assignment_ids, branches, workflows):
    from core.services.compliance_audit import record_event
    return record_event(
        workflow='portal',
        action=f'product_availability.{action}',
        category='configuration',
        subject_type='product',
        subject_id=str(product.pk),
        actor=actor,
        authority_user=actor,
        request_id=request_id,
        source_model='ProductAvailability',
        source_event_id=request_id,
        deduplication_key=f'product-availability:{product.pk}:{action}:{request_id}',
        after_values={
            'assignment_ids': [str(value) for value in assignment_ids],
            'branch_ids': [str(value) for value in branches],
            'workflows': list(workflows),
            'channel': CANONICAL_PRODUCT_CHANNEL,
        },
    )


@transaction.atomic
def add_product_coverage(
    *, product: Product, branch_ids, workflows, actor, request_id: str,
) -> dict:
    """Idempotently add/reactivate the selected branch x workflow coverage."""

    _guard(actor)
    request_id = _request_id(request_id)
    normalized_workflows = sorted({str(value or '').strip() for value in workflows})
    invalid = [value for value in normalized_workflows if value not in PRODUCT_WORKFLOWS]
    if invalid or not normalized_workflows:
        raise ValidationError('Choose at least one supported workflow.')
    try:
        normalized_branch_ids = sorted({int(value) for value in branch_ids})
    except (TypeError, ValueError):
        raise ValidationError('Choose valid product branches.')
    branches = list(OperationalLocation.objects.filter(
        pk__in=normalized_branch_ids, location_type='branch', active=True,
    ).order_by('sort_order', 'name'))
    if len(branches) != len(normalized_branch_ids) or not branches:
        raise ValidationError('Choose at least one active branch.')

    product = Product.objects.select_for_update().get(pk=product.pk)
    assignment_ids = []
    created_count = 0
    reactivated_count = 0
    for branch in branches:
        for workflow in normalized_workflows:
            signature = (
                f'branch:{branch.pk}|workflow:{workflow}|channel:{CANONICAL_PRODUCT_CHANNEL}'
            )
            assignment = ProductAvailability.objects.filter(
                product=product, scope_signature=signature,
            ).first()
            if assignment is None:
                assignment = ProductAvailability.objects.create(
                    product=product, branch=branch, workflow=workflow,
                    channel=CANONICAL_PRODUCT_CHANNEL, active=True,
                    scope_signature=signature,
                )
                created_count += 1
            elif not assignment.active:
                assignment.active = True
                assignment.save(update_fields=['active', 'scope_signature'])
                reactivated_count += 1
            assignment_ids.append(assignment.pk)

    _audit(
        product=product, actor=actor, request_id=request_id, action='coverage_added',
        assignment_ids=assignment_ids,
        branches=normalized_branch_ids, workflows=normalized_workflows,
    )
    return {
        'selected_count': len(assignment_ids),
        'created_count': created_count,
        'reactivated_count': reactivated_count,
    }


@transaction.atomic
def deactivate_product_coverage(
    *, product: Product, assignment_ids, actor, request_id: str,
) -> int:
    """Deactivate only explicitly selected canonical coverage rows."""

    _guard(actor)
    request_id = _request_id(request_id)
    try:
        normalized_ids = sorted({int(value) for value in assignment_ids})
    except (TypeError, ValueError):
        raise ValidationError('Choose valid availability assignments.')
    if not normalized_ids:
        raise ValidationError('Choose at least one coverage assignment to deactivate.')
    product = Product.objects.select_for_update().get(pk=product.pk)
    assignments = list(ProductAvailability.objects.select_for_update().filter(
        pk__in=normalized_ids, product=product,
        workflow__in=PRODUCT_WORKFLOWS, channel=CANONICAL_PRODUCT_CHANNEL,
    ))
    if len(assignments) != len(normalized_ids):
        raise ValidationError('One or more selected assignments are no longer editable here.')
    active_ids = [item.pk for item in assignments if item.active]
    ProductAvailability.objects.filter(pk__in=active_ids).update(active=False)
    _audit(
        product=product, actor=actor, request_id=request_id,
        action='coverage_deactivated', assignment_ids=normalized_ids,
        branches=sorted({item.branch_id for item in assignments if item.branch_id}),
        workflows=sorted({item.workflow for item in assignments}),
    )
    return len(active_ids)
