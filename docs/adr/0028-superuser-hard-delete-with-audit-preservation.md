# ADR 0028: Superuser hard delete with audit preservation

## Context

Django's ordinary User deletion is blocked by protected operational and audit
references. JBL nevertheless requires the active technical Superuser to be able
to physically remove another account without checker approval, while signed
documents, workflow history, and the hash-chained compliance ledger remain
verifiable.

## Decision

Provide one Superuser-only Admin hard-delete service with impact preview,
password reauthentication, typed confirmation, idempotency, and row locking.
The acting account cannot delete itself, the final active Superuser cannot be
removed, and every reverse User relation must have an explicit handling policy.

Compliance-ledger User fields become unconstrained historical references so
their original numeric IDs and hashes do not change. Protected historical rows
are redirected to a disabled, non-login tombstone after their original
relationship is captured in an immutable deletion manifest. Live access,
delivery state, and personal drafts are removed; active routing is explicitly
unassigned and resulting TAT coverage gaps remain visible.

## Consequences

- The selected `auth_user` row is physically deleted without a checker.
- Historical UI must use stored actor labels when the live User no longer exists.
- A successful deletion cannot be reversed from application data; recovery of
  the account itself requires an approved database restore or deliberate new
  onboarding.
- Adding a new User relation without classifying it makes hard deletion fail
  closed before mutation.
- Telegram notification is best effort and never rolls back the local deletion.

## Alternatives considered

- Soft deletion was rejected because the required outcome is physical account
  removal.
- Checker approval was rejected because Django Superuser is the deliberate
  unilateral technical authority for this operation.
- Cascading every relation was rejected because it would destroy operational
  and legal evidence.
- Setting compliance actors to null was rejected because actor IDs are part of
  the immutable hash payload.
