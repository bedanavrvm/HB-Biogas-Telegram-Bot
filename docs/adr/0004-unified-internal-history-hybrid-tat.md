# ADR 0004: Unified internal history and hybrid TAT measurement

Status: Accepted - 29-July-2026

## Context

Jawabu Portal and TAT Tracker already retain append-only workflow events, but
their staff views expose those records separately from generated documents,
data-quality decisions, and synchronization provenance. Their TAT values are
wall-clock elapsed time, which overstates staff SLA time across evenings,
weekends, and public holidays. Existing overdue records are useful audit
evidence, but do not identify the escalation tier that must act next.

## Decision

Keep each workflow's existing event table authoritative and build one
query-time, internal-only timeline projection over them. The projection also
includes case-linked documents, customer-field provenance, data-quality
resolutions, and authorised timeline annotations. It never edits an original
event: a correction or redaction is a separate, append-only annotation.

Official staff SLA time is Monday-Friday, 08:00-17:00 Africa/Nairobi,
excluding active holidays configured in Django Admin. Wall-clock time remains
available for context and backwards-compatible API fields. The current
deferred/reappraisal exclusion remains the only pause rule; no new general
clock-pause state is introduced.

Overdue scans remain idempotent and in-app only. They promote one daily
escalation record through 100%, 150%, and 200% thresholds for the responsible
role, branch management, and central management respectively. The scan never
sends Telegram messages, changes a workflow state, or makes a payment
decision. A notification delivery worker needs separate approval.

## Consequences

- Case 360 and TAT detail responses gain a shared `timeline` and hybrid TAT
  values while retaining their current response fields during migration.
- Admin-managed holidays and new timeline/SLA records require a database
  migration. Existing workflow events, customer records, Sheets, Drive files,
  and generated documents are not modified or backfilled destructively.
- Daily operational snapshots record trend evidence without altering source
  events. A command defaults to dry-run and requires `--apply` to persist.
- History is internal only. Customer-facing status sharing requires a separate
  privacy/retention decision and endpoint review.

## Alternatives considered

1. Materialize a replacement timeline table - rejected because it duplicates
   authoritative audit data and makes correction/reconciliation harder.
2. Treat wall-clock time as the SLA - rejected because it counts non-working
   time as staff delay.
3. Introduce general clock pauses - rejected for now because only the existing
   deferred/reappraisal rule has an approved workflow meaning.
4. Send Telegram alerts from the scan - deferred pending approved recipient
   routing, retry/backoff, and Render scheduling.

## Release and rollback

No production migration, Render deployment, scheduler, or notification
delivery is authorised by this ADR alone. Before production rollout, confirm a
current PostgreSQL backup and run the SLA/snapshot commands in dry-run mode.

To undo the schema change after an approved deployment, first export any
timeline annotations, SLA records, and daily snapshot evidence that must be
retained, then run:

```powershell
python manage.py migrate core 0077_seed_operational_products
```

The reverse migration removes only the new calendar, annotation, escalation
metadata, and snapshot records. It does not alter existing workflow events,
farmers, TAT cases, Sheets, Drive files, or payment data.
