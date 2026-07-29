# ADR 0002: Service-layer workflow integrity controls

Status: Accepted — 29-July-2026

## Context

Jawabu Pipeline and TAT have server-side validation, atomic writes, and
append-only events, but each workflow evolved its own transition conventions.
Neither has an optimistic-concurrency token, and their audit events cannot
consistently distinguish a state transition from a field correction. The
repository does not include `django-fsm`; replacing working services with a
new dependency would widen the migration and operational risk.

## Decision

Keep Django service functions as the workflow-state engine. Add shared
service-layer primitives for revision validation and structured transition
errors, then apply them to Jawabu Pipeline and TAT.

Jawabu receives an explicit current workflow state, state-entry timestamp,
and revision. TAT retains its configured stage model and `current_stage`, but
receives the same revision and transition-event contract. Existing event
models are extended rather than replaced so historical timelines remain
queryable. An actor and authority are both recorded; until a separately
approved delegation model exists, they are always the same canonical User.

SLA scans create idempotent, pending escalation records. They do not move,
approve, reject, or notify a customer automatically. A future delivery worker
or Render Cron setup requires separate production approval.

## Consequences

- Mini App writes must carry the case revision and receive a clear conflict
  response if another staff member has changed the case.
- Return-for-rework transitions are explicit and reasoned. Jawabu supports
  Credit → JBL Visit and Final Review → Credit; Deferred remains paused and
  still uses the existing 90-day reappraisal rule.
- Payment approval semantics, access grants, and the capability matrix are
  not changed by this decision.
- The change adds schema migrations `core.0073` through `core.0075` for
  workflow revisions, audit metadata, TAT retry receipts, backfilled current
  state, and SLA escalation records.

## Alternatives considered

1. Add `django-fsm` — rejected for this release because it is not installed,
   would require a broad lifecycle-field migration, and duplicates the tested
   service-layer authorization already present.
2. Use last-write-wins updates — rejected because a silent lost update is
   unacceptable for credit, review, and TAT records.
3. Auto-transition overdue cases — rejected because TAT breach is an
   escalation concern, not authority to make a decision for staff.

## Release and rollback

No production migration, Render deployment, or scheduled execution is
authorized by this ADR alone. Before production rollout, obtain explicit
approval, confirm a current PostgreSQL backup, and run the dry-run transition
health command against the intended database.

To undo the schema change after an approved deployment, first export any
post-release transition/escalation audit evidence that must be retained, then
run:

```powershell
python manage.py migrate core 0072_miniapp_drafts
```

The reverse migration removes only the new workflow-integrity columns and
records; it does not alter existing farmer, TAT, payment, access, Sheet, or
Drive records.
