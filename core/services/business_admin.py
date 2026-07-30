"""Read-only cutover checks for the Business Administrator role rename."""
from __future__ import annotations

from dataclasses import dataclass

from core.services.access_policies import (
    BUSINESS_ADMIN_ROLE,
    BUSINESS_ADMIN_WORKFLOWS,
    LEGACY_BUSINESS_ADMIN_ROLE,
)


@dataclass(frozen=True)
class BusinessAdminCutoverIssue:
    code: str
    message: str


def legacy_business_admin_cutover_issues() -> list[BusinessAdminCutoverIssue]:
    """Report data that must be resolved before the role-code migration.

    The check is deliberately read-only.  Historic audit rows may retain the
    legacy label; only pending effective-policy requests and uniqueness
    collisions could make the migration ambiguous.
    """
    from core.models import AccessControlChangeRequest, AccessGrant

    issues: list[BusinessAdminCutoverIssue] = []
    pending_count = AccessControlChangeRequest.objects.filter(
        workflow__in=BUSINESS_ADMIN_WORKFLOWS,
        role=LEGACY_BUSINESS_ADMIN_ROLE,
        status=AccessControlChangeRequest.STATUS_PENDING,
    ).count()
    if pending_count:
        issues.append(BusinessAdminCutoverIssue(
            'pending-legacy-policy-request',
            f'{pending_count} pending access-policy request(s) still use legacy ADMIN. Review them before cutover.',
        ))

    grant_collision_count = 0
    for grant in AccessGrant.objects.filter(
        workflow__in=BUSINESS_ADMIN_WORKFLOWS,
        role=LEGACY_BUSINESS_ADMIN_ROLE,
    ).iterator():
        duplicate = AccessGrant.objects.filter(
            user_id=grant.user_id,
            workflow=grant.workflow,
            role=BUSINESS_ADMIN_ROLE,
            branch=grant.branch,
            product=grant.product,
            group_configuration_id=grant.group_configuration_id,
        ).exists()
        grant_collision_count += int(duplicate)
    if grant_collision_count:
        issues.append(BusinessAdminCutoverIssue(
            'access-grant-collision',
            f'{grant_collision_count} legacy ADMIN grant(s) already have the same BUSINESS_ADMIN scope.',
        ))

    # Capability-row collisions are expected where older seed migrations and
    # the current catalogue have both materialised a default.  Migration 0088
    # safely merges them by retaining the legacy row's effective allow/deny
    # value, so they are not a release blocker.
    return issues
