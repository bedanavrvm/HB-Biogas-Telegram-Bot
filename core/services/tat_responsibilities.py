"""Canonical TAT responsibility configuration and audit helpers.

AccessGrant answers whether a person may act.  This module answers who should
receive a TAT task first; it must never grant access as a side effect.
"""

from __future__ import annotations

from collections import defaultdict

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone


def stage_catalog(workflow: dict | None = None):
    """Return canonical product/stage rows without inventing another policy."""
    from core.services.tat_tracker import configured_products

    rows = []
    for product in configured_products(workflow or {}):
        for position, stage in enumerate(product.stages, start=1):
            rows.append({
                'product_key': product.key,
                'product_label': product.label,
                'position': position,
                'stage_key': stage.key,
                'stage_label': stage.label,
                'role': str(stage.role or '').strip().upper(),
                'capability_key': f'tat.stage.{stage.key}.update',
            })
    return rows


def canonical_stage_role(*, stage_key: str, product_key: str = '', workflow: dict | None = None) -> str:
    """Resolve one stage owner, requiring a product when definitions disagree."""
    stage_key = str(stage_key or '').strip()
    product_key = str(product_key or '').strip().lower()
    matches = [row for row in stage_catalog(workflow) if row['stage_key'] == stage_key]
    if product_key:
        matches = [row for row in matches if row['product_key'].casefold() == product_key.casefold()]
    if not matches:
        raise ValidationError({'stage_key': 'Choose a stage configured for the selected TAT product scope.'})
    roles = {row['role'] for row in matches if row['role']}
    if len(roles) != 1:
        raise ValidationError({
            'stage_key': 'This stage has different responsible roles across products. Choose one product first.',
        })
    return roles.pop()


def assignment_snapshot(assignment) -> dict:
    backups = list(assignment.backups.order_by('rank', 'created_at').values(
        'user_id', 'rank', 'threshold_percent', 'active',
    )) if assignment.pk else []
    return {
        'id': str(assignment.pk),
        'group_configuration_id': assignment.group_configuration_id,
        'branch': assignment.branch,
        'role': assignment.role,
        'product_key': assignment.product_key,
        'stage_key': assignment.stage_key,
        'primary_user_id': assignment.primary_user_id,
        'active': assignment.active,
        'effective_from': assignment.effective_from.isoformat() if assignment.effective_from else None,
        'effective_until': assignment.effective_until.isoformat() if assignment.effective_until else None,
        'backups': backups,
    }


def eligible_responsibility_users(*, group_configuration, branch: str, role: str, product_key: str = ''):
    """Return active users whose explicit TAT grant covers this routing scope.

    This query is shared by the Admin form and its dependent-select endpoint so
    changing a scope in the browser cannot make its displayed choices diverge
    from server-side validation.
    """
    from core.models import AccessGrant

    users = get_user_model().objects.none()
    branch = str(branch or '').strip()
    role = str(role or '').strip().upper()
    product_key = str(product_key or '').strip().lower()
    if not group_configuration or not branch or not role:
        return users

    grants = AccessGrant.objects.filter(
        workflow='tat_tracker', role__iexact=role, active=True,
        user__is_active=True,
    ).filter(
        Q(group_configuration__isnull=True)
        | Q(group_configuration=group_configuration)
    ).filter(
        Q(branch='') | Q(branch__iexact=branch)
    )
    if product_key:
        grants = grants.filter(Q(product='') | Q(product__iexact=product_key))
    else:
        # An all-products roster must not nominate someone whose permission is
        # limited to only one product.
        grants = grants.filter(product='')
    return get_user_model().objects.filter(
        access_grants__in=grants, is_active=True,
    ).distinct().order_by('first_name', 'last_name', 'username')


def configuration_issues(assignments) -> dict:
    """Classify routing problems for the Admin workspace without changing data."""
    issues = defaultdict(list)
    for assignment in assignments:
        if assignment.stage_key:
            try:
                expected = canonical_stage_role(
                    stage_key=assignment.stage_key,
                    product_key=assignment.product_key,
                    workflow=assignment.group_configuration.workflow,
                )
            except ValidationError as exc:
                issues['invalid_stage'].append((assignment, '; '.join(exc.messages)))
            else:
                if assignment.role.upper() != expected:
                    issues['role_conflict'].append((assignment, f'Expected {expected}.'))
        now = timezone.now()
        if assignment.active and assignment.effective_until and assignment.effective_until <= now:
            issues['expired_assignment'].append((
                assignment,
                'This active roster has expired and must be deactivated before a replacement can be activated.',
            ))
        if assignment.active and assignment.effective_from <= now and (
            assignment.effective_until is None or assignment.effective_until > now
        ):
            from core.services.tat_notifications import user_can_receive_scope
            if not user_can_receive_scope(
                assignment.primary_user,
                group=assignment.group_configuration,
                branch=assignment.branch,
                product_key=assignment.product_key,
                role=assignment.role,
            ):
                issues['invalid_primary'].append((assignment, 'Primary user lacks matching active TAT access.'))
    return dict(issues)
