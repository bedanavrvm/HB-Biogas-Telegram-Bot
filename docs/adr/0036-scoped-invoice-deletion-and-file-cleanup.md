# Scoped invoice deletion and file cleanup

Date: 2 October 2026

## Decision

Delete physically removes eligible ParsedInvoice rows and disposable delivery
items. Ignore remains a reversible queue action. Neither is an alternative to
removing protected payment or invoice-name-change evidence.

Deletion requires the invoice-write capability and one complete matching grant;
it locks the group and matched case before checking payment links. It retains
independent compliance evidence, including source hash and event summaries.
An upload envelope survives for request identity and cleanup coordination,
not as an operational invoice tombstone.

Only when no surviving invoice or delivery item uses a source PDF is a durable
Drive deletion operation reserved. Django commits first. The existing
request-assisted worker or an explicit cleanup retry advances a bounded,
leased attempt. Drive failures never undo local deletion or block navigation.
File-not-found is an idempotent success. Combined and cross-upload shared PDFs
are checked again before removal.

## Consequences

- Deleted invoices cannot be restored; staff must confirm the action.
- Ignored invoices remain available for restore and matching.
- A shared PDF can remain after one of its invoice rows is deleted.
- Drive cleanup can remain pending while no Portal session is active; no new
  scheduler, external service, persistent model or schema migration is added.
- Protected items are skipped with a specific explanation, not silently removed.
