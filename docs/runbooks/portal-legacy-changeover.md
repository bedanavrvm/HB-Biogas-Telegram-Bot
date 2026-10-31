# Portal legacy changeover

Implemented 31 October 2026. Live import waits for the user's reviewed workbook.
This changes the existing Telegram Portal, not standalone browser access.

## Workbook handover

The Original columns can be deleted. Retain Source Row, the Master Data / Eco-conserve
sheet identities (the existing Compare names also work), cleaned headers, Legacy
Outcome, Legacy Reason/Code, Decision Stage and Reviewer Notes. Never renumber
Source Row when sorting or removing records. Keep the raw/v3 workbooks separately.

All Cases → Legacy Master Data changeover accepts XLSX, previews values and
commits only selected rows, at most 50 per request. Refresh saved progress and
resume the same namespace after interruption. Use one stable namespace per
reviewed source dataset, without customer details. Colours and previous review
flags are not validation evidence. Formula results use Excel's saved cache only, with the formula retained as source
evidence; the Portal never executes or recalculates a workbook. Recalculate or
paste reviewed values if a mapped field lacks a usable cache. Derived-only blank
rows are not cases. Duplicate mapped headers/source rows, unreadable files and
oversized workbooks are rejected. Opaque legacy columns remain source evidence,
not inferred JBL customer IDs, financial balances or dates.

The preview shows the proposed state, its evidence, issues and existing identity
matches. Blank old identity/date/document fields are permitted; invalid monetary
values must be corrected. Distinct identities are never merged by name/phone.
An existing Case ID requires an explicit link and explanation. A matching identity
requires either an exact existing-case link or an explained separate unit. Linking
adds source evidence without overwriting current case facts. Corrections to
already committed source facts use the owning correction/identity workflow;
re-uploading cannot silently replace newer operational records.

## Historical policy

- Django owns operational state. `portal_legacy` retains batches, immutable
  committed source snapshots and append-only import/confirmation evidence.
- Known stage decisions and unambiguous matching statements in Additional
  Comments, reviewer notes and HB notes support proposed continuation. Conflicts,
  bare Approved and unclear cancellations remain Legacy review. No approval
  actor, signature, stage timestamp, intake event or activity point is invented.
- Revisit Cases and Case History expose source evidence and explicit scoped
  Operations/IT stage confirmation. Known legacy orders can receive an audited
  HB handover without creating a fake signed scan. Role, branch, product and group
  checks still apply; another Mini App's IT grant provides no Portal authority.
- Explicit physical completion is retained even without historical dates. Missing
  commissioning status is **Not recorded (legacy)**, separately visible in HB
  follow-up. A new commissioning requires its actual date; known installation
  dates enforce chronology and the existing early-commissioning acknowledgement.
  Unknown historical dates produce no invented readiness countdown. Recording
  new installation still requires its actual date. Historical gaps do not block
  saving unrelated metadata on an already installed legacy record.
- HB/Eco-conserve register ownership is captured from the reviewed source tab,
  independently of incomplete historical county/salesperson values.
- Old invoice references/amounts remain reported facts, not parsed-invoice,
  identity, payment-review or settlement evidence. Existing invoice parsing can
  enrich them later through its normal reviewed matching flow. Missing old PDFs
  do not block the historical import or HB continuation. New financial actions
  retain their current evidence/identity/approval requirements.
- Existing FarmUp and office-lead intake validators remain unchanged. A legacy
  record is not a global bypass flag or a way to grant an operational role.

## Cutover procedure

1. Back up the scoped database and source registers. Agree a window that pauses
   manual register edits and new numbered paperwork while finance references are
   reconciled. Apply the checked-in Django migrations through normal deployment.
2. Stage the final reviewed workbook under its exact Portal group. Inspect
   state proposals, ambiguous identities/units and reference formats. Resolve
   existing case links explicitly. Commit selected rows and resume until all
   intended rows are accounted for. Unknown stages may remain in Legacy review.
3. Reconcile imported counts and known dates/amounts against the reviewed file.
   Confirmed old numbers are retained as consumed allocator claims; this does not
   generate batches or documents. Current governed allocations/releases win
   when explicitly linking an existing case. Incomplete imports containing known
   finance references block new number claims until reconciled. Review allocator
   settings against the actual paper trail, including references absent from the
   workbook, before resuming numbered work.
4. New imported cases remain held from Sheet publication. Preview live bindings:

   ```powershell
   .venv/Scripts/python.exe manage.py bind_portal_legacy --batch BATCH_UUID --actor USER_PK --manifest test-results/legacy-bindings.json
   ```

   This reads configured Master Data/Eco-conserve tabs and exports source/target
   rows, Case IDs and live row hashes; it performs no Sheet writes. Review every
   binding against the source and live register. Source Row is a proposed target,
   not proof the live sheet has never been sorted. Correct target rows and their
   verified live row hashes in the reviewed manifest if needed. Existing-case
   links retain the existing live row; duplicate legacy Sheet rows require review
   and are never automatically deleted.
5. After explicit approval, apply the exact manifest with an accountable note:

   ```powershell
   .venv/Scripts/python.exe manage.py bind_portal_legacy --batch BATCH_UUID --actor USER_PK --manifest test-results/legacy-bindings.json --apply --note "Reviewed source-to-live row bindings" --limit 50
   ```

   The command checks current ownership and unchanged row hashes, rejects other
   Case IDs/duplicate target rows, adds the Case ID header if absent, writes only
   reviewed UUID bindings and reads them back. Only verified rows are enabled
   for the existing durable publisher. Repeat the same manifest to resume.
   A stale manifest stops further application; prior verified bindings remain.
6. Drain the existing publication queue through the supported bounded publisher,
   then reconcile registers and the canonical database again. Resume operations
   only after checking finance allocation, Legacy review and HB worklists. Restore
   the pre-cutover backup only before any subsequent real staff actions; afterward
   use attributed corrections rather than deleting history.

## Verification and limits

Manual Playwright, actual API/database observations and a separate local PostgreSQL
cluster are used for this change. Evidence and review notes:
[UI review](../ui-standard/reviews/2026-10-31-portal-legacy-changeover.md).
No automated test suite was added or run. Synthetic provider transports cannot
certify production credentials, live row bindings, real documents or delivery.
