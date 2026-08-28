# ADR 0027: Checker-approved staff lifecycle plans

## Decision

Permanent operational access and staff lifecycle changes are represented by
one durable `StaffLifecycleChangePlan`. A different Access Control Checker must
approve the unchanged plan before access, routing, delegation, activation, or
offboarding effects apply in one transaction.

The sole root Superuser may bootstrap the first independent checker but may not
self-approve operational access. Four-hour emergency access is the only
deliberate immediate exception. Django Superuser status remains outside the
workspace.

## Consequences

- Authorization and TAT routing remain distinct sources of truth.
- Transfers cannot stop halfway through several grant and roster edits.
- Direct runtime AccessGrant writes are rejected outside governed services.
- Telegram onboarding requires signed identity, enrolled username, and a
  short-lived single-use activation code.
- ADR 0019's immediate Admin-inline grant override is superseded for normal
  operations; historical audit records remain valid.
