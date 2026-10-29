# Portal invoice corrections

## Staff behaviour

- A flagged invoice corrected to exactly match the applicant national ID requires
  **Resolve identity flag**, with a verification note, from an existing identity
  manager (including Operations). The flag remains in history. Different or
  missing IDs cannot use that action.
- Current invoice detail exposes **Cancel request**, **Withdraw request** and
  **Start follow-up** where applicable. A follow-up needs fresh household
  verification before preparing its letter. Withdrawal confirms HB was told to
  disregard the sent request; it does not approve identity.
- Only the current sent letter's agreed copy clears its identity hold. Failed
  uploads keep their file, confirmation and inline error for retry. A superseded
  source invoice links to its current replacement.
- Upload each invoice PDF separately. A matching outstanding correction shows
  **Confirm corrected invoice** in the upload result and invoice detail.
- Check the selected invoice before confirming. National ID is mandatory and
  decisive. Different spelling/name order warns; a different phone requires the
  existing verification note. Multiple requests remain separate choices.
- Deleted and superseded invoices never appear in replacement selection.
  Ignored invoices remain explicit selectable candidates, restored by confirmation.
- Unmatch confirms both removing the link and closing this invoice's unfinished
  correction. Unsent requests become cancelled; sent requests become withdrawn.
  No manual note/communication reference is required for this combined action.
  Shared-batch neighbours, generated letters and accepted agreements survive.
- Editable payment membership remains, held until the current invoice is ready.
  Changing evidence invalidates existing review/workbook versions. Signed
  payment evidence is protected. Neither correction nor upload creates payment
  batches automatically.

## Duplicate versus similar

`core.services.invoice_duplicates` owns comparison for counts, filters, bulk
selection and duplicate deletion. National ID is compared first, followed by
number, date, name, phone, captured amounts and printed order reference. Identity
and invoice number must be present; missing money is distinct from zero. Case,
outer whitespace and ordinary phone/ID formatting are normalized, never fuzzy
names or different identities. Provider bytes still have their existing upload
hash protection. IDs/timestamps, filename, workflow state and parser diagnostics
are not invoice business values.

Similar IDs, phone numbers or invoice numbers alone remain review hints, not
authority to bulk-delete. A surviving original and existing retained-evidence
protections are required at the write boundary.

## Interfaces and safety

- Upload/detail responses add `correction_suggestions`, with authorized request
  and invoice IDs/revisions and the same warning/eligibility assessment as the
  write service. Pending correction uploads do not take the ordinary auto-match
  path. Existing receipt details are refreshed before payment creation.
- Replacement candidates return request `revision`; replacement POST accepts
  `revision` and `invoice_revision`. Unmatch accepts `revision`. Old callers
  retain compatibility, while current UI always sends its observed revision.
- `GET /api/portal/invoice-name-changes/<artifact-id>/download-link/` returns
  fresh authorized `download_url`, `filename`, `artifact_id`, `expires_at`.
  Existing token downloads remain GET/HEAD and recheck the actor's current access.
- Financial workspace locks precede case and invoice locks. No Sheet/Drive call
  is added to canonical matching or unmatching; publication remains queued.
- This patch uses existing states and tables, with no invoice data migration.
  Rollback is a code rollback; retained closure history is not rewritten.

## Verification

Use an isolated test database and synthetic fixtures; never point tests at live
Sheets, Drive or Telegram. Run identity, invoice upload, invoice letter, payment
agreement and payment-batch suites. Run `core.tests_invoice_concurrency` against
PostgreSQL to check simultaneous replacement and replacement-versus-unmatch.

Browser coverage: `portal_invoice_corrections.spec.js`,
`portal_invoice_transport.spec.js`, `portal_invoice_record_layout.spec.js`, and
payment-detail cases in `portal_nested_finance_layout.spec.js`. Inspect actual
screenshots at 320/390/430/desktop widths in both themes. Upload/confirmation
tests use real renderers, not a separately styled mockup. The old preview fixture
now supplies the supported server-rendered page-image HTML, not an empty HTML
page incorrectly expected to become an iframe.

On staging, verify a real Telegram download offer names the actual DOCX, Cancel
does not claim success, an unsupported client falls back, a stale link refreshes,
and revoked access cannot download. Confirm signed payments remain unchanged.

Local verification on 15 October 2026: 172 backend scenarios passed; two
pre-existing payment-document failures were reproduced against unchanged Portal
view code, and two PostgreSQL race tests were skipped because no PostgreSQL test
URL is configured. Invoice/transport/layout browser scenarios and the nine
payment-layout scenarios passed. Django configuration and migration-drift checks
passed. No live provider/deployment verification was performed.
