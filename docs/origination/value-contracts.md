# Origination shared field values

## What changes

The Document editor can explicitly opt an editable document into shared values.
The Product workspace still owns terms and document choices, not PDF authoring.
Existing keys remain flat. A dotted name such as `applicant.national_id` is a
domain vocabulary, not an automatic database/model rewrite.

For an opted-in application, the selected packet compiles one entered form from
its shared fields. Supporting screens collect only document-instance inputs and
show generated values read-only. Editing an applicant value updates all selected
documents and invalidates their old previews within the same revision-controlled
transaction. Unchanged supporting saves preserve previews. A public retry key binds the actor
and exact payload; retries cannot silently submit different values.

The catalogue records a definition, subject, ownership, source, unit and reporting
period. Selection rejects inconsistent meanings, types, choices and repeating
structures. The smallest schema or mapped table capacity governs row limits.
Rendering fails explicitly instead of dropping rows or truncating values.

Quote values use the frozen Decimal quote. A requested amount never substitutes
for approval, disbursement, receipt or visit evidence. Existing final approval may
project its exact approved terms; this change adds no new collection workflow for
later events. Missing authoritative events display unavailable, not zero or today.
Income, expenses and surplus remain distinct; missing inputs are not invented zeros.

An officer may explicitly reuse spouse/next-of-kin/referee identity for a supported
guarantor slot. Changing the original person propagates while linked. Unlinking
retains a copy. Name/phone similarity never links people automatically. Every
signature still binds its document, packet revision, consent and bytes.

Deselecting a document retains its saved values for later reselection, while
excluding them from active validation, calculations and signed content. If a linked person role
is no longer represented, selection detaches that link, retains the copied identity
and records the affected role in the selection audit. Main-form edits remain usable.

## Operator workflow

1. Open a new document or an editable copy. Never modify a published source.
2. Select **Share application values across documents** under PDF.
3. Review any field-meaning tasks. Select the subject, shared/document ownership,
   unit, reporting period and reviewed automatic source where applicable.
4. Configure existing permitted signers, place fields, preview realistic synthetic
   values and publish through the established single Publish action.
5. Explicitly connect compatible documents to the intended products. New
   applications opt in by selecting them; existing applications remain legacy.

Default meaning suggestions are exact-key conveniences, not approval of ambiguous
paper wording. The Generic duplicate Net Income labels, combined spouse/next-of-kin
fields and Micro Asset Code remain review tasks. Printed Type/Box, malformed
transfer-location labels and legal attestations need business/compliance clarification.
These are draft repair items, not requests to introduce more operational gates.

## Reviewed seeds

Main sources reuse the existing dry-run command with optional `--shared-values`.
The root eleven-document set contains five of the existing Main seed sources;
select their individual keys (`generic`, `sme_logbook`, `micro_asset`,
`invoice_finance`, `lipa_mdogo_mdogo`). Main `--laf all` additionally requires the existing
Water Tank PDF, which is not in that eleven-document set.
Supporting sources use:

```powershell
.\.venv\Scripts\python.exe manage.py seed_origination_support_lafs --laf-root .\LAFS --laf all --actor admin
```

The default is read-only. Explicit `--apply` writes database drafts and private
Drive PDFs; do not run it on a real environment without authorization. It never
publishes coordinates, changes approval policy or adds product allowlists.
Supporting references include their known field/page labels and required signers.
The full occurrence-by-occurrence register for all eleven PDFs is not yet visually
certified: existing Main references remain field-level, and repeated date/signature
and legal blanks require human placement review. Do not label these drafts ready
for operational legal use solely because the source hash or unit tests pass.

Grantor, asset-owner, advocate, seller and proposed-owner roles are not silently
mapped onto borrower/witness roles. Where current signing policy cannot represent
them, publication reports the exact missing signer. Confirm that policy separately;
do not edit the required-role declaration merely to suppress the warning.

## Migration, rollout and rollback

Migration `origination.0006_originationdatafield_value_contract` adds one JSON
metadata column to the existing bounded-domain field catalogue with a PostgreSQL
column comment. It creates no new persistent entity and performs no backfill.

Apply through the normal reviewed release/migration process. Do not run production
migrations from a development session. Deploy the matching backend/assets together;
verify legacy cases first, then a synthetic v2 packet. Production activation remains
an explicit reviewed publication, not a seed side effect.

Before any v2 document/application is operational, the additive migration can be
reversed in an isolated deployment:

```powershell
.\.venv\Scripts\python.exe manage.py migrate origination 0005_consent_sequence_isolation
```

Rollback drops the new catalogue metadata column: preserve its data before doing
so, and coordinate application rollback. Once v2 snapshots exist, do not remove the
resolver or downgrade their contract markers; use a forward fix. Retiring a document
stops new selections but never deletes existing packets, history or signed files.

## Verification

`origination.tests_value_contracts` covers shared/local saves, actor-bound retries,
read-only values, semantic conflicts, row limits, person links and frozen contexts.
`origination.tests_support_laf_seeds` covers references, exact source aliases and
idempotent unassigned drafts with mocked Drive. Existing Origination, field,
catalogue, editor, commercial, approval and Main-seed suites remain applicable.

The real-admin synthetic browser journey supports `ORIGINATION_AUTHORING_MODE=value-contract`.
It uses a local isolated Django server and existing mocked uploads; artifacts go
to ignored `test-results/origination-authoring/`. Traces/screenshots must never
contain real customer data. PostgreSQL-specific concurrency tests require the
dedicated local test profile; SQLite passes are not PostgreSQL parity evidence.
