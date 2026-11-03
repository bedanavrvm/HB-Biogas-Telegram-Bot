# Portal Legacy Data importer

Implemented 3 November 2026 for the reviewed Master Data v5 workbook. This is
the Telegram Portal's **Legacy Data** menu alongside FarmUp and SysUp. It replaces
the earlier All Cases upload path for this changeover. Eco-conserve is excluded
from ingestion and Sheet replacement, even if its tab exists in the workbook.

## Before starting

Deploy the checked-in `portal_legacy` migrations 0004 and 0005 through the normal
release process. Migration 0005 adds the built-in Portal IT capability. A role
in another Mini App supplies no authority. The importing IT account needs
whole-owner Portal authority; branch-only grants cannot perform an owner-wide
changeover. Existing Operations legacy-case continuation remains separate.

Back up the database and source spreadsheet. Confirm the exact Portal owner and
its configured Master Data spreadsheet/tab/header row. Arrange a window that
pauses manual Master Data edits, intake and numbered paperwork. The app holds
Portal mutations and publication for that owner during cutover; it cannot stop
people or independent integrations editing Google Sheets directly.

Test-data deletion requires an active Superuser and the existing
`MINIAPP_TEST_DELETION_ENABLED` deployment setting. It uses the governed deletion
registry and impact confirmation. Do not enable deletion merely to bypass an
unexpected live record. This route is a one-time conversion of an owner whose
existing cases are confirmed test data; a completed cutover prevents repeating
that deletion on imported live cases.

## Operator sequence

1. Open **Legacy Data**. Choose the Portal owner, a stable namespace such as
   `master-data-changeover`, and the reviewed XLSX. Keep Source Row unchanged.
   The source must contain exactly one `Master Data` or `Master Data Compare`
   tab, with Source Row and Customer Name. Original columns may be removed.
   If operational cells contain formulas, paste their reviewed values first.
2. Inspect **Source-to-Portal mapping** and accept it to stage rows. Historical
   columns, including `LEGACY | Constituency | Cleaned` and
   `LEGACY | Location detail | Cleaned`, remain reference facts. They do not
   overwrite the current Sub-County dropdown meaning.
3. Review the 50-row pages and Ready/Warnings/Blocked filters. Source facts,
   proposed state, warnings and explicit identity reconciliation are available
   on each row. Invalid money blocks import; incomplete historical identity,
   dates or workflow evidence are retained with warnings or Legacy review.
   Correct blocked values/field limits in a new workbook version before test
   cleanup is allowed. Approve the intended records. Approval persists across
   page navigation.
4. Have the Superuser select **Review test-data deletion**, inspect the owner,
   case count and dependent-model impact, and confirm. This deletes the selected
   owner's Portal test cases, including its Eco test cases in Django, through
   the existing governed deletion service. Shared/independent evidence follows
   that service's disclosed retention rules. No Master Data or Eco-conserve
   Sheet cleanup is queued by this deletion. Other Portal owners are excluded.
5. Select **Import approved rows**. Commits retain per-row provenance and audit
   evidence. A problematic row is held with its reason while saved rows survive.
   Reconcile the source or exact case linkage before approving it again. Nothing
   fabricates historical approval actors, signatures or missing dates.
6. Account for every source row before selecting **Preview Master Data
   replacement**. All imported rows must bind to distinct cases, and this
   owner must have no cases outside the import. Review the exact spreadsheet,
   tab, replacement count and headers. Confirm that manual edits are paused.
7. Keep the workspace open or resume it later. The app snapshots old data rows,
   writes and verifies a hidden staging tab, checks the old rows again, then
   replaces Master Data's data values in one provider batch. Existing headers
   and formatting survive; Case ID is added if absent. Old unmatched data rows
   are cleared. Eco-conserve is untouched. Every new row is read back before
   its normal publication is enabled. The owner is released only at Complete.
8. Reconcile counts, sampled identities, dates, money, Legacy review and HB
   worklists against the reviewed source. Review consumed order/payment numbers
   and allocator settings against the paper trail before resuming numbered work.

## Capacity and interruption recovery

- Source limit: 20 MiB compressed, 256 MiB expanded, 256 mapped columns and
  50,000 case rows. Uploads use 512 KiB checksum-verified database chunks.
- Staging advances by at most 250 records or five seconds; canonical commits
  advance by at most 50 records or five seconds. Each case commits independently.
- Sheet steps use bounded snapshot/staging/readback pages, an eight-second
  external-call budget and at least four seconds between publication advances.
  Spreadsheet capacity is checked including the temporary staging copy.
- Closing/backgrounding Telegram stops the client loop after the current
  request. Choose **Resume saved import**, then **Resume processing**. A partial
  upload requires reselecting the same workbook; retained chunks are reused.
- Lost responses do not mean an unsaved case. Refresh progress first. Expiring
  database leases stop concurrent workers advancing the same source. A lost
  replacement response is checked against the sheet-scoped completion marker
  before another destructive batch is allowed.
- A pre-deletion preview can be cancelled. Once deletion/import begins, finish
  the held cutover; discard cannot remove its recovery evidence. Changed
  deletion impact requires another review of the remaining selection.
- If Master Data changes during backup/staging/verification, pause processing,
  choose **Review replacement again**, inspect the new destination preview and
  confirm again. Earlier snapshot attempts remain retained. This action is
  unavailable once a replacement may have been sent; refresh/resume checks its
  marker instead.

## Recovery evidence and limits

Source bytes and compressed pre-replacement cell values are private database
`LegacyChunk` records, keyed by each projection attempt's snapshot kind.
`LegacyUpload.state.projection` records the destination,
old grid dimensions, source headers, staging tab, snapshot hashes and progress.
Committed `LegacyRow`/`LegacyEvent` records retain provenance. The hidden staging
tab and snapshot remain available after completion; avoid deleting recovery
evidence during acceptance. The private disk decode cache is disposable.

A changed snapshot or readback mismatch keeps the owner held. Stop manual
edits and have IT inspect the saved destination, source and snapshot. Snapshot
restoration is an operator recovery task, not an automatic rollback button.
Never roll back the database after subsequent real staff activity; use audited
corrections. Do not restart the import under another namespace to evade a hold.

The provider marker is sheet-scoped, following the
[Google Sheets Sheet resource](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/sheets#Sheet).
Staging uses the installed gspread `Worksheet.hide()` API. Pausing manual edits
remains necessary: Google does not provide a compare-and-swap condition across
the snapshot verification and replacement requests.

Local evidence is described in the
[UI and workflow review](../ui-standard/reviews/2026-11-03-portal-legacy-importer.md).
No production deletion, import, Sheet write or deployment was performed during
implementation. Local synthetic scale evidence does not establish production
instance headroom or live provider performance.
