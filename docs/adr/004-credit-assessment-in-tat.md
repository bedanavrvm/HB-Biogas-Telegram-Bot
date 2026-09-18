# Credit assessment is governed inside TAT

## Context

Pre-appraisal forms, M-PESA statements, SPIN/CRB exports, analyst questions,
and Branch Manager decisions have historically moved through WhatsApp, email,
the standalone SPIN Mini App, and Google Drive links.  A timestamp in TAT can
therefore imply progress without proving which evidence or decision revision
it represents.

## Decision

Credit assessment is a bounded Django domain linked one-to-one to a TAT case.
TAT owns elapsed time, role routing, and the operational queue.  The bounded
domain owns evidence versions, protected statement matching, clarification
revisions, and decisions.  Staff use the TAT Mini App throughout.  The first
release accepts manually produced analysis reports and exposes a disabled
versioned interface for a future extraction engine.

The dedicated Gmail inbox is a collection source, not workflow authority.
Google Drive stores file bytes, while Django owns hashes, versions, state, and
access decisions.  Legacy SPIN writes are retired at cutover; existing rows and
files are retained without migration.

## Consequences

- Every approval is bound to an exact assessment and document revision.
- The consolidated analysis report is mandatory; source SPIN and CRB exports
  are optional evidence.
- BRO review is mandatory even when the analyst raises no questions.
- New persistent state lives outside the legacy `core` app.
- Authorized-user OAuth for the configured personal Gmail mailbox and the
  existing restricted Drive media folder are prerequisites before mailbox
  intake is enabled. The Google service account remains Drive-only.
  Passcode encryption uses a domain-separated key derived from the existing
  stable Django secret, so it needs no additional deployment secret.

## Alternatives considered

- Extending `SpinCreditRequest` would preserve a timestamp-and-JSON model that
  cannot safely represent the required gates or revisions.
- Importing the separate analysis Django project would duplicate customer,
  permission, and document ownership.
- Calling Spin/Metropol APIs immediately would make the workflow depend on
  credentials and contracts that are not currently available.
