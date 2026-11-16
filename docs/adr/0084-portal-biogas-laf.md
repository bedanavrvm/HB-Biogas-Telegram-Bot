# Portal-owned digital Biogas LAF

Accepted implementation scope — 16/11/2026. Production activation requires separate review.

## Context

Portal officers can upload a signed LAF but must otherwise fill, scan and upload
paper. Origination already owns the published Biogas PDF, placed fields and
signature rendering. Its application lifecycle and grants are independent of Portal.

## Decision

Keep upload/camera primary and provide secondary form filling inside Portal.
The bounded `portal_lafs` app owns versioned case documents, requests and signing
evidence. Reuse Origination's published document contract, validation, PDF and
signature primitives, without creating Origination applications or borrowing grants.
Portal stage capabilities govern staff signing; configured external signers use
in-person signing on the officer's device with personal consent and an authenticated
officer witness. No OTP or SMS is required. Remote Portal signing
is explicitly deferred. BRO, credit and final-review signatures apply at
their respective stages. Negative outcomes do not require approval signatures.

Freeze answers and the base PDF at first signature. Preserve every superseded
version; replacement invalidates affected Portal approvals. Durable local bytes
satisfy evidence checks independently of retriable Drive archival. Existing uploads
and historical cases are not converted. The feature defaults off.

## Consequences

There is one active LAF source per case, while uploads and abandoned drafts survive.
Unsigned template successors may be adopted on an explicit draft save; signed
versions never change. Portal dates remain dd/mm/yyyy. No new dependency is needed.
No permission catalogue additions or Origination queues are introduced.

The user additionally selected a shared signing component for both Mini Apps.
`document_signing` owns common appearance, PDF ink and the in-app signing dialog; existing
Origination import paths delegate to it without changing retained records, links
or workflow authority. Portal's form and version lifecycle stay in `portal_lafs`.

Rollback: disable `PORTAL_LAF_FORM_ENABLED`, export the new document/signature
tables and retained bytes, then `python manage.py migrate portal_lafs zero`.
That reversal removes the new tables and must never precede the evidence export.

## Alternatives considered

Creating a normal Origination application would impose a second approval flow
and unrelated grants. Reimplementing PDF layout and signature rendering would
create two document engines. The owner-specific lifecycle shares those primitives.
