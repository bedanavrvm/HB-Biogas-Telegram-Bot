# ADR 0024: Portal Invoice Workspace Drill-down

- Status: Accepted for code merge and local/staging verification.
- Date: 03-August-2026

## Context

The Portal Invoice page combined invoice upload, every reconciliation state,
bulk actions, filters, and full parsed-record history in one screen. This made
the mobile staff experience hard to scan and left no natural Back path from a
record review to the relevant list.

Parsed invoice records, matching actions, payment-readiness calculation, and
the append-only invoice-event trail already have protected Portal API routes.
This change must not alter their data model, matching rules, financial values,
or Drive behaviour.

## Decision

Use normal Portal routes for focused Invoice workspace views:

- `/portal/s/invoices/` — reconciliation inbox for draft, unmatched, and
  ambiguous parsed invoices.
- `/portal/s/invoices/matched/` — reconciled invoice list.
- `/portal/s/invoices/ignored/` — intentionally excluded records.
- `/portal/s/invoices/upload/` — controlled upload and recent upload history.
- `/portal/s/invoices/<invoice-id>/` — one invoice's source, parsed values,
  duplicate checks, audit trail, and state-appropriate reconciliation action.

The existing protected invoice API remains the source of all data. The
`workspace` query parameter is a read-only list convenience: it selects the
appropriate existing ParsedInvoice states without changing a record. Batch
parse failures remain batch history because no ParsedInvoice exists to display.

The match sheet stays an overlay because choosing a customer is a short,
single-purpose action. All other review work moves to route-backed pages so
Telegram and phone Back are predictable.

## Consequences

- The default Invoice destination becomes a compact decision inbox instead of
  a mixed upload/reconciliation screen.
- Existing matching, unmatching, ignore/restore, bulk actions, audit events,
  and capability checks are reused unchanged.
- Upload history retains parsed and failed source-file visibility without
  fabricating invoices for failed parsing.
- A branch-limited user is not shown parse-failure counts because a failed
  source file has no trusted branch scope yet.
- No dependency, schema change, migration, Sheets write, Drive write, or
  external message is introduced by this navigation/UI change.

## Alternatives considered

- Keep one page and hide sections with more accordions: rejected because the
  mobile screen would still have competing tasks and the phone Back button
  would not describe a meaningful review path.
- Build a separate Invoice Mini App: rejected because Invoice reconciliation
  is a Portal workflow and already shares Portal authorization and case data.
- Replace matching with a multi-step wizard: rejected because the existing
  match overlay is focused, guarded, and keeps the smallest action local to
  the invoice being reviewed.

## Rollback

No migration is included. To undo, redeploy the prior application commit. This
does not modify invoice records, batches, financial values, audit history,
Drive files, Sheets registers, or staff access.
