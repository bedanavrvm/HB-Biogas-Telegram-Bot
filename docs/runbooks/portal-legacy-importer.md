# Portal legacy register importer

Open **Legacy changeover → Legacy import** in the Telegram Portal sidebar.
This dedicated page is separate from Pipeline Intake and All Cases; All Cases
has no importer. Select **Master Data** or **Eco-conserve** before uploading.
Each source is reviewed, cleaned up, imported and projected independently.
The other register's cases and sheet are preserved.

## Before starting

Deploy the checked-in portal_legacy migrations through **0006_selected_register**
through the normal release process. Migration 0005 adds the built-in Portal IT
capability; 0006 binds each upload to a selected register. Existing uploads keep
Master Data as their source. A role in another Mini App supplies no authority.
The importing IT account needs whole-owner Portal authority; branch-only grants
cannot perform an owner-wide changeover. Operations legacy-case continuation
remains separate.

Back up the database and source spreadsheet. Confirm the exact Portal owner,
configured spreadsheet, both destination tab names and header row. Eco-conserve
uses the existing Eco-conserve tab configuration in that spreadsheet; the two
destination names must differ. Arrange a window that pauses manual edits,
intake and numbered paperwork. The app holds Portal mutations and publication
for the whole owner during either cutover and releases it on completion. Run
the two imports sequentially. It cannot stop people or independent integrations
editing Google Sheets directly.

Test-data deletion requires an active Superuser and the existing
MINIAPP_TEST_DELETION_ENABLED setting. It uses the governed deletion registry
and signed impact confirmation. Never enable deletion to bypass an unexpected
live record. A completed cutover prevents repeating that deletion for the same
owner/register, while allowing the other register's separate cutover. Old pending
group-wide cleanup previews must be reviewed again under the selected register.

For reviewed v5, use **Master Data Live - Original vs Cleaned v5 - Import Ready.xlsx**.
Its sole correction names the extra Eco AN1 invoice placeholder as historical
evidence; no data values change. See the
[header review](legacy-eco-v5-header-review-2026-11-03.md). The original is retained.

## Operator sequence

1. Open **Legacy changeover → Legacy import**. Select the register, Portal owner,
   stable namespace such as master-data-changeover or eco-changeover, and reviewed
   XLSX. Keep Source Row unchanged. The file must contain exactly one selected
   source tab: Master Data / Master Data Compare, or Eco-conserve / Eco-conserve
   Compare. Other tabs are ignored. Source Row and Customer Name are required;
   Original columns may be removed. Paste reviewed values over operational
   formulas before uploading. The same workbook and namespace may be used for
   both sources; they create separate uploads. Source selection is immutable
   after creation, including when resuming an upload.
2. Inspect **Source-to-Portal mapping** and accept it to stage rows. Historical
   columns, including LEGACY | Constituency | Cleaned and LEGACY | Location
   detail | Cleaned, remain reference facts. They do not overwrite the current
   Sub-County dropdown meaning. Duplicate operational headers are rejected.
3. Review 50-row pages and Ready/Warnings/Blocked filters. Source facts, proposed
   state, warnings and explicit identity reconciliation are available on each
   row. Invalid money blocks import; incomplete historical identity, dates or
   workflow evidence are retained with warnings or Legacy review. Correct blocked
   values/field limits in a new workbook version before test cleanup is allowed.
   Approve intended records; choices persist across page navigation.
   Table is the default FarmUp-style AG Grid view; use **Cards** to switch back.
   Column sorting/filtering applies to the current 50-row page. Open a row number
   for source facts/history or edit the existing case ID/explanation in the grid.
   Source values remain read-only. Both layouts retain the same review choices.
4. Have the Superuser select **Review test-data deletion**, inspect the owner,
   selected register, case count and dependent-model impact, and confirm. This
   deletes only that owner's test cases assigned to the selected register's
   fulfillment partner through the existing governed deletion service. Other
   owners and counterpart cases remain. Shared/independent evidence follows the
   disclosed retention rules. No Sheet cleanup is queued by this deletion;
   selected-sheet replacement occurs later. Review unexpected partner assignments
   before proceeding; the app does not silently delete counterpart cases.
5. Select **Import approved rows**. Commits retain source/register provenance,
   canonical partner and audit evidence. A problematic row is held with its
   reason while saved rows survive. Reconcile source or exact case linkage before
   approving it again. Cross-register case links are rejected. Nothing fabricates
   historical approval actors, signatures or missing dates.
6. Account for every source row before selecting **Preview register replacement**.
   Imported rows must bind to distinct cases and cover every case belonging to
   the selected register for that owner. Counterpart cases remain untouched.
   Review the exact spreadsheet, destination tab, count and headers.
   Confirm that manual edits are paused.
7. Keep the workspace open or resume it later. The app snapshots old data rows,
   writes and verifies a hidden staging tab, checks the old rows again, then
   replaces only the selected tab's data values in one provider batch. Existing
   headers and formatting survive; Case ID is added if absent. Old unmatched
   data rows in that destination are cleared. Every new row is read back before
   normal publication is enabled. The owner is released only at Complete.
8. Reconcile counts, sampled identities, dates, money, Legacy review and HB
   worklists against the reviewed source. Review consumed order/payment numbers
   and allocator settings against the paper trail before resuming numbered work.

## Capacity and interruption recovery

- Source limit: 20 MiB compressed, 256 MiB expanded, 256 mapped columns and
  50,000 case rows per selected register. Uploads use 512 KiB checksum-verified
  database chunks. Excel namespace attributes and self-closing blank rows are
  supported; blank worksheet formatting is not imported as a customer.
  Historical formula expressions remain source evidence across batch/cache
  restarts; they are not executed or imported as workflow facts.
- Staging advances by at most 250 records or five seconds; canonical commits
  advance by at most 50 records or five seconds. Each case commits independently.
- Sheet steps use bounded snapshot/staging/readback pages, an eight-second
  external-call budget and at least four seconds between publication advances.
  Spreadsheet capacity includes the temporary staging copy.
- Closing/backgrounding Telegram stops the client loop after the current request.
  Select the original register, **Resume saved import**, then **Resume processing**.
  A partial upload requires reselecting the same workbook; retained chunks are
  reused. Source toggles save pending review choices before switching.
- Lost responses do not mean an unsaved case. Refresh progress first. Expiring
  database leases stop concurrent workers advancing the same source. A lost
  replacement response is checked against the sheet-scoped completion marker
  before another destructive batch is allowed.
- A pre-deletion preview can be cancelled. Once deletion/import begins, finish
  the held cutover; discard cannot remove recovery evidence. Changed deletion
  impact requires another review of the remaining selection.
- If the selected sheet changes during backup/staging/verification, pause,
  choose **Review replacement again**, inspect the destination preview and confirm
  again. Earlier snapshots remain retained. This action is unavailable once a
  replacement may have been sent; refresh/resume checks its marker instead.

## Recovery evidence and limits

Repeatable API, PostgreSQL-worker and real Django/Playwright commands are in the
[regression-suite runbook](portal-legacy-importer-tests.md).

Source bytes and compressed pre-replacement cell values are private LegacyChunk
records keyed by projection attempt. LegacyUpload state records the selected
source, destination, old grid dimensions, source headers, staging tab, snapshot
hashes and progress. Committed LegacyRow/LegacyEvent records retain provenance.
The hidden staging tab and snapshot remain after completion; avoid deleting
recovery evidence during acceptance. The source-bound private decode cache is
disposable.

A changed snapshot or readback mismatch keeps the owner held. Stop manual edits
and have IT inspect saved destination/source/snapshot facts. Snapshot restoration
is an operator task, not an automatic rollback button. Never roll back the
database after subsequent staff activity; use audited corrections. Do not start
another namespace to evade a hold.

The provider marker is sheet-scoped, following the
[Google Sheets Sheet resource](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/sheets#Sheet).
Staging uses the installed gspread Worksheet.hide() API. Pausing manual edits
remains necessary: Google provides no compare-and-swap across snapshot verification
and replacement requests.

Local evidence: [original importer review](../ui-standard/reviews/2026-11-03-portal-legacy-importer.md),
[table/cards review](../ui-standard/reviews/2026-11-03-portal-legacy-grid-toggle.md),
and [register/navigation review](../ui-standard/reviews/2026-11-03-portal-legacy-eco-register.md).
No production deletion, import, Sheet write or deployment was performed. Local
synthetic scale evidence does not establish production headroom or live provider
performance; a full 50,000-case commit/projection remains unverified.
