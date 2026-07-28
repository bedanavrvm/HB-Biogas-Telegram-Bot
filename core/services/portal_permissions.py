"""Portal action-to-role policy definitions.

The Mini App has several independently evolved endpoints.  Keeping the
action policy in one small module makes authorization reviewable without
duplicating role literals across views and navigation code.
"""

from __future__ import annotations


PORTAL_ACTION_ROLES: dict[str, frozenset[str]] = {
    'read': frozenset({'VIEWER', 'JBL_OFFICER', 'CREDIT_ANALYST', 'HB_STAFF', 'ADMIN'}),
    'health.read': frozenset({'HB_STAFF', 'ADMIN'}),
    'jbl_visit.write': frozenset({'JBL_OFFICER', 'ADMIN'}),
    'credit.write': frozenset({'CREDIT_ANALYST', 'ADMIN'}),
    'final_review.write': frozenset({'ADMIN'}),
    'requisition.write': frozenset({'HB_STAFF', 'ADMIN'}),
    'invoice.write': frozenset({'HB_STAFF', 'CREDIT_ANALYST', 'ADMIN'}),
    'payment.review': frozenset({'ADMIN'}),
}


def portal_action_roles(action: str) -> frozenset[str]:
    """Return canonical roles for an action, failing closed for unknown keys."""
    return PORTAL_ACTION_ROLES.get(str(action or '').strip(), frozenset())

