# ADR 0008: Cross-workflow compliance audit ledger and checkpoints

Status: Accepted - 30-July-2026

## Context

Portal, Complaint Cases, TAT, SPIN, finance sign-off, and access-control
workflows already retain useful operational events. They do not share one
investigation-ready event taxonomy, and Django Admin read-only controls alone
cannot detect a database-level alteration. JBL needs evidence that identifies
the actor, accountable authority, source, subject, before/after state, and
time across the staff Mini Apps.

## Decision

Add an additive, hash-chained `ComplianceAuditEvent` ledger. Existing
workflow-specific event tables remain the detailed operational record; their
central write paths project an idempotent copy into the ledger. The ledger is
append-only in Django and guarded by a PostgreSQL trigger against application
role `UPDATE` and `DELETE` statements. A singleton chain cursor serializes
concurrent inserts.

Sensitive record views/downloads and audit-ledger searches/exports are also
recorded. Evidence is searchable in Django Admin and exportable only through
the dedicated Django permission or superuser access. Exports deliberately log
their own access event.

Retention begins as `legal_hold`: no automatic deletion occurs until JBL has a
separately approved and legally validated retention schedule. Daily checkpoint
records capture the chain position/hash. Mailbox delivery is disabled by
default and requires both explicit configuration and a supervised
`--apply --deliver` command; the implementation does not send external email
during ordinary use.

Physical signatures remain the approved document model. The ledger records the
authenticated actor and the source/scan checksums already retained by the
physical sign-off service. It does not introduce, imply, or validate an
electronic signature.

## Consequences

- PostgreSQL application-role mutation is rejected. A database owner can still
  change a trigger or data, so the external checkpoint is tamper-evidence, not
  an inaccurate claim of absolute immutability.
- Historical rows are not fabricated into the ledger: missing before/after or
  identity evidence stays in the original event tables. Any future backfill
  must be labelled as legacy projection.
- The compliance control matrix is a technical evidence map only. CBK/DPA
  clause citations require legal/compliance validation before being represented
  as a regulatory conclusion.
- No new package, scheduler, automatic email, or production deployment is
  introduced by this change.

## Alternatives considered

1. Keep four independent event tables only - rejected because cross-system
   investigations and control exports remain manual reconciliation.
2. Rely on Sentry/application logs - rejected because operational logs have
   different retention, mutability, and data-minimization goals.
3. Send a checkpoint for every event - rejected because it creates avoidable
   external side effects and mailbox noise; a controlled daily checkpoint is
   easier to supervise.

## Release and rollback

No production migration or Render deployment is authorized by this ADR. Before
production use, back up PostgreSQL; test a permitted and denied export,
verified Mini App writes in all four workflows, the PostgreSQL trigger, an
integrity command, and a disabled checkpoint delivery attempt.

To undo an approved migration: first export legally required audit evidence and
record why rollback is necessary, then run:

```powershell
python manage.py migrate core 0082_sheet_register_governance
```

The reverse migration removes the new ledger, checkpoint, and trigger schema.
It does not modify existing Portal, Complaint Case, TAT, SPIN, document, or
access-control records.
