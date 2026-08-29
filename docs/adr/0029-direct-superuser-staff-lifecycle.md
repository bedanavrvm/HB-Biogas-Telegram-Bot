# ADR 0029: Direct Superuser staff lifecycle decisions

## Context

ADR 0027 required an independent checker for every staff lifecycle plan. That
made even an active technical Superuser's deliberate creation of an ordinary
staff account wait in a separate approval state. It also made the location of
the checker decision unclear in Django Admin.

The approved operating model treats active Django Superuser authority as the
technical break-glass root for ordinary staff accounts. A Superuser therefore
does not require a checker to onboard, change, transfer, place on leave,
return, or offboard a non-Superuser account. Independent review is still useful
when the Superuser deliberately wants a second decision.

## Decision

- **Apply now** is the default Staff Lifecycle Workspace path for an active
  Django Superuser. The server presents the exact action, target, grants,
  routing impact, and reason before requiring the Superuser's current password.
- Direct execution creates and applies one durable
  `StaffLifecycleChangePlan` transactionally. It retains revision checks,
  request-key idempotency, append-only lifecycle/compliance evidence, and
  server-side authorization.
- **Send for independent review** is an explicit optional choice. Those plans
  remain pending until an eligible Access Control Checker approves or rejects
  them from **Configuration > Staff approvals**.
- Existing pending checker plans may be approved by a checker, or directly
  applied/cancelled by an active Superuser after password confirmation.
- Reusing a request key with identical bytes returns the original plan and
  account. Reusing it with different details is rejected. Raw passwords never
  enter plan snapshots, audit metadata, or request fingerprints.
- Django Superuser accounts remain outside this workspace.

## Consequences

- Ordinary staff onboarding no longer depends on checker availability.
- Checker review remains available without being silently imposed.
- The approvals queue is a named navigation destination instead of being
  hidden inside the creation workspace.
- Existing plans default to `checker_review` during migration, preserving their
  original semantics.
- ADR 0027 is superseded only for the mandatory-review rule. Its atomicity,
  segregation rules for plans deliberately sent to review, immutable evidence,
  Telegram activation, and governed AccessGrant requirements remain in force.

## Rollback

Before any direct-decision rows exist, migration `0143` may be reversed to
`0142`. After direct decisions are recorded, retain the columns and ship a
forward policy/UI change if mandatory review must be restored; removing the
decision evidence would make historical interpretation ambiguous.
