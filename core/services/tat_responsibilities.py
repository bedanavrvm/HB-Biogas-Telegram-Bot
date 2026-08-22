"""Canonical TAT responsibility configuration and audit helpers.

AccessGrant answers whether a person may act.  This module answers who should
receive a TAT task first; it must never grant access as a side effect.
"""

from __future__ import annotations

from collections import defaultdict

from django.core.exceptions import ValidationError
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
