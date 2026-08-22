# ADR 0026: Separate TAT access authority from operational responsibility

**Status:** Accepted for code merge and local/staging validation only.
Production migration application requires separate explicit release approval.

## Context

The shared `AccessGrant` model already allows one staff user to hold multiple
workflow roles and scopes. TAT stage definitions separately declare the role
responsible for each stage, and the capability service converts those
definitions into enforceable stage permissions.

The first private-task routing form repeated both role and stage as editable
values. That allowed an administrator to construct a contradictory mapping,
such as assigning a Finance responsibility to a Secretary-owned stage. It also
made access, stage policy, routing, escalation, and private-alert readiness
difficult to understand across separate Admin pages.

## Decision

- Keep `AccessGrant` as the shared cross-workflow authorization source. A
  responsibility assignment never creates or expands access.
- Keep TAT responsibility routing TAT-specific. A role roster supplies the
  normal primary and ranked backups for a scope; a stage override is allowed,
  but its role is derived from the canonical TAT stage definition.
- Resolve responsibility from most to least specific: product-stage override,
  general stage override, product-role roster, general role roster, then the
  eligible shared role pool. Ambiguous same-tier matches fail closed into the
  discoverable unassigned-task path.
- Present stage policy, scoped TAT grants, duty rosters, escalation thresholds,
  and private-alert health in one Superuser-only Admin workspace while keeping
  their underlying authority and audit records separate.
- Preserve responsibility changes as append-only events. Existing conflicting
  stage assignments are disabled for review rather than silently reinterpreted.

## Consequences

A person can hold several TAT roles without ambiguity: the case stage chooses
the responsibility role, and every task records that acting role. Operators get
one configuration surface, while authorization continues to be checked at task
creation, delivery, locator opening, and action time.

The roster remains intentionally TAT-shaped. Origination review ownership,
SPIN review, Portal queues, and Complaint Cases are not forced into a generic
responsibility table. The private-task delivery service may be reconsidered for
extraction only after a second workflow demonstrates the same lifecycle.

## Alternatives considered

- **Make assignments grant access:** rejected because notification ownership
  must not bypass maker-checker access policy.
- **Send every task to the whole role:** retained only as the safe fallback;
  rejected as the normal route because it weakens accountability.
- **Create a generic cross-workflow roster:** rejected as premature because the
  workflows have materially different ownership and hand-off rules.
- **Create another global grant model:** rejected because `AccessGrant` already
  provides the required shared workflow/role/scope authority.

## Migration and rollback

The migration adds append-only responsibility-event evidence. Role-level rows
remain unchanged. Recognized stage rows whose stored role conflicts with the
canonical stage role are deactivated and recorded for review; no tasks, access
grants, cases, Sheet rows, Drive files, or Telegram messages are changed.

To undo a non-production application before relying on the new audit records:

```text
python manage.py migrate core 0126_tatprivatealertconnection_and_more
```

Do not reverse after responsibility events become operational evidence. Prefer
restoring the prior application code while retaining the audit table.
