# Portal legacy register importer

## Updating previously imported cases

Use **Update Existing Cases** in the upload form to compare a newer raw workbook
with current Django records. This mode never deletes records or clears a Sheet.
Select Master Data or Eco-conserve; upload the same workbook separately for each
register. Review Changed rows, open Row to choose fields, and apply the selected
changes together. Unchanged rows need no action. New cases and ambiguous matches
have separate filters and explicit selection. Original evidence is retained,
concurrent edits require a refreshed comparison, and saved updates queue for
normal Sheet publication. See the [update workflow and validation evidence](../ui-standard/reviews/2026-11-06-legacy-update-import.md).

Deploy migration `portal_legacy.0007_update_mode` before using this option.

Open **Legacy changeover → Legacy import** in the Telegram Portal sidebar.
This dedicated page is separate from Pipeline Intake and All Cases; All Cases
has no importer. Select **Master Data** or **Eco-conserve** before uploading.
Each source is reviewed, cleaned up, imported and projected independently.
The other register's cases and sheet are preserved.

## Historical credit and current status

The Sheet's overall `Current Pipeline State` now has a compact twelve-value
catalogue shared by initial loading and later publication. Rejected and Deferred
reported outcomes remain visible when their decision stage is unknown;
explicit physical completion remains visible with date warnings in the Mini App.
Unqualified historical approval without an order number and conflicting facts
remain Legacy. A recorded legacy order number implies historical approval and
completed order processing: it displays Installation in Progress until later
physical completion is known. Approved — Order Processing means awaiting the
order number.
Handover evidence, the action gate and outstanding import review do not
change. See the [status meanings](../operations/portal-sheet-publication.md#compact-current-pipeline-status).

Imported cases without a recorded credit decision display **Legacy** in Credit
Analysis and its Sheet projection. Recorded decisions remain intact. Legacy is
a presentation marker, not an operational credit decision or approval; unknown
decision dates/actors stay blank. A source workbook containing that marker can
be imported again without inventing a credit decision. Once actual app visit or
credit-decision activity exists, its current pending/recorded decision takes
precedence over the historical marker.

Confirming a continuation immediately updates the displayed current pipeline
status and stage number from the canonical workflow state. Missing historical
HBG/JBL dates and older visit outcomes no longer send a confirmed JBL/credit/
final-review/order case back to an earlier displayed step. Actual HB installation
and commissioning evidence still controls delivery progress. Normal new-case
requirements and the HB minimum-deposit gate remain in force.

Local browser/Sheet evidence is recorded in
`docs/ui-standard/reviews/2026-11-05-portal-legacy-credit-and-current-status.md`.
No bulk production rewrite occurs; existing Sheet rows adopt the labels through
their normal publication path.

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
intake and numbered paperwork during destructive test cleanup. Once a case is
imported and its initial Sheet write is verified, it can be edited and continued
through normal Portal actions while the remaining source rows are reviewed. Run
the two imports concurrently if needed: each register has its own cutover lock,
review progress and Sheet destination. A second cutover for the same register is
blocked. Unverified cases remain held; mixed selections containing an unverified
case cannot proceed. Owner-wide administrative changes remain held until all
cutovers finish or are safely cancelled. Full-register replacement temporarily
pauses case changes in that register until readback succeeds. The other register
remains available. The app cannot stop people or independent integrations
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
   workflow evidence are retained with warnings or Legacy review. Double-click a
   pending field and choose **Save corrections** to fix blocked values/field limits.
   Original values and correction history remain available; changed rows require
   fresh approval. Source Row, Case ID and imported records stay read-only.
   Approve intended records; choices persist across page navigation.
   Table is the default FarmUp-style AG Grid view; use **Cards** to switch back.
   Column sorting/filtering applies to the current 50-row page. Open a row number
   for source facts/history or edit the existing case ID/explanation in the grid.
   Affected cells are highlighted and identity matches name the conflicting
   source rows/cases and values. Both layouts retain the same review choices.
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
   historical approval actors, signatures or missing dates. **Imported** means
   saved in Django; it does not mean synced to Google Sheets. The separate
   indicator shows verified/saved rows, awaiting sync and not-yet-imported rows.
6. Each saved chunk starts **automatic FIFO Sheet sync**, oldest commit first,
   before the next import chunk continues. Previously saved cases are included
   when you resume the saved upload. You can have **52 / 52 synced** while
   **4,025 not imported** remain for review; those remaining Sheet rows are
   preserved. You do not need to upload again. **Sync imported rows to Sheet**
   and **Resume processing** remain recovery controls for saved unsynced work.
   Review the remaining rows with **Review unimported rows**. Approving displayed
   rows selects only the current page; **Approve all pending rows** selects all
   eligible remaining records, which still process in bounded chunks.
7. Keep the workspace visible or resume it later. The app verifies destination
   row identities and updates only confirmed imported cases, preserving the
   counterpart tab and unimported rows. The synced count increases only after
   readback. Lost acknowledgements retain the exact write plan; resume verifies
   it before retrying. A failing oldest write holds newer writes in FIFO order.
   Once all source cases are saved and verified, the import completes and releases
   its hold. Full-register replacement remains a separate **Replace entire
   register?** action on a fully imported, held upload: it requires exact
   destination review and confirmation, snapshots and stages the destination,
   then clears unmatched old rows. Ordinary FIFO sync never clears unrelated rows.
   Verified cases use the normal Portal publication queue for later edits and
   workflow changes. Initial unverified writes still run through the owning
   importer. Resume retains the saved source and approvals; no re-upload is needed.
   Continuation confirmation is audited and queues a new canonical publication.
   A resumed old import checkpoint cannot overwrite a newer case correction.
   Summary refresh is read-only.
   Existing UUID or readable-reference bindings update their current row. A
   matching raw source row is also retained in place. When no existing row is
   bound and the source position is empty, the case uses the first fully empty
   destination row in FIFO order, starting at row 2 on a header-only sheet.
   **Source Row** is retained in Django and does not create empty destination
   rows. Formula-only rows are occupied. Old projected gaps are reused by new
   cases; existing case rows are not moved. Visible **Case ID** contains `JBL-…`;
   the exact UUID is retained in hidden **Master Record ID**.
   Older partial uploads whose receipts predate this identifier format are
   shown as awaiting sync once more. Resume the saved upload to correct the
   visible IDs in place and verify them; the database cases are still saved.
   An uncertain old write is verified before any identifier correction.
8. Reconcile counts, sampled identities, dates, money, Legacy review and HB
   worklists against the reviewed source. Review consumed order/payment numbers
   and allocator settings against the paper trail before resuming numbered work.

## Legacy cases awaiting the minimum HB deposit

Accepted operating behaviour (5 November 2026): use the existing **JBL visit**
continuation and deposit gate. There is no separate Awaiting HB Deposit
continuation choice or additional pipeline stage.

For an imported historical case awaiting its first JBL visit:

1. Ensure the case is saved in Django and its initial Sheet write is verified.
   The remaining source rows may still be under review; the whole import need
   not finish before this case can continue.
2. Operations/IT opens the case's **Legacy Continuation · Review Required**
   disclosure. Review the existing Case Notices, choose **JBL visit**, and
   confirm. No additional evidence/explanation entry is required. The audit
   records the actor, selected stage and source sheet/row automatically.
   Use this action only where continuation has not
   already been confirmed; a case already awaiting a JBL visit needs no rerouting.
   Saving automatically updates the case page; confirming from a queue drawer
   opens the updated case details. No manual page refresh is required. If the
   save succeeds but the updated details cannot load, use **Retry loading case**;
   this retries the read without submitting the confirmation again.
3. HB opens **HB Actions → Deposits → Awaiting Deposit** and finds the case.
   A legacy-review case can already appear in that list, but its deposit editor
   remains unavailable until it is in an editable pre-visit state.
4. Authorized Portal HB staff record the **cumulative deposit received by HB**.
   For example, if KES 2,000 was recorded and a further KES 3,000 is received,
   enter **5,000**, not 3,000. Updates retain revision checks, audit history and
   normal queued Sheet publication. A decrease requires a reason.
5. Blank, unknown, zero or totals below **KES 5,000** keep the JBL visit action
   blocked. A total of KES 5,000 or more clears the deposit gate and places the
   case in the deposit workstream's **Cleared** filter. Other queue/workflow
   requirements still apply.

These are overlapping worklists, not an exclusive transfer: a case meeting JBL
queue eligibility can remain visible there as **Deposit pending**, with its
recorded amount and shortfall. Staff cannot activate/log the visit while held;
the server independently enforces the same gate. HB manages the outstanding
amount through the Deposits workstream. This follows the existing
[HB deposit decision](../adr/0059-hb-deposit-gate.md).

Only the HB deposit clears this gate. A historical amount recorded as **Deposit
Paid to JBL** remains separate evidence; do not relabel or combine it with HB
receipts merely to reach the minimum. Deposits do not create a signed order,
installation action or approval. Cases with an already recorded JBL visit are
not sent backwards merely because historical deposit information is incomplete;
the pre-visit deposit editor is locked after a recorded JBL visit.

### Client withdrawal after continuation

Once a case has a confirmed continuation stage, choose **Withdrawn** in that
stage's normal Outcome/Decision dropdown and explain the client's decision in
Comment. In case details, use **Status** inside the current JBL Visit, Credit
Analysis, Final Review or Order section. This also permits an authorized JBL
stage owner to record withdrawal before the deposit gate clears. There is no
standalone Mark Withdrawn section.

The original stage, intake dates and existing evidence are retained. **Resume
Case** appears for withdrawn cases with a confirmed originating stage and
returns the same case to that stage with a required note. It does not bypass
normal deposit or approval requirements. Unknown historical withdrawal stages
still require source reconciliation before resumption. Order, invoice, payment
and fulfilment protections remain in force.

### Missing-date limitation

For legacy cases, the JBL queue currently also requires an **HB visit date** or
nonblank **sign date**. Consequently, a case missing both may appear in HB
Deposits and clear the KES 5,000 gate while still remaining absent from the JBL
queue. Confirming JBL visit continuation does not create either date. Retain
unknown dates as unknown; use an authorized correction only when source evidence
establishes the actual value. Refer unresolved cases to Operations/IT rather than
inventing a date to force queue entry.

This section records the current behaviour and its accepted limitation, checked
against the continuation service, HB deposit policy/list and JBL queue code. No
routing change or additional browser verification was performed for this
documentation update.

## Capacity and interruption recovery

- Source limit: 20 MiB compressed, 256 MiB expanded, 256 mapped columns and
  50,000 case rows per selected register. Uploads use 512 KiB checksum-verified
  database chunks. Excel namespace attributes and self-closing blank rows are
  supported; blank worksheet formatting is not imported as a customer.
  Historical formula expressions remain source evidence across batch/cache
  restarts; they are not executed or imported as workflow facts.
- Staging advances by at most 250 records or five seconds; canonical commits
  advance by at most 50 records or five seconds. Each case commits independently.
- FIFO sync scans up to 250 rows per step, including formulas in every column
  to prove an allocation target is empty. It prepares up
  to fifty imported cases / three seconds / 512 KiB per write batch and retains target/checksum/readback receipts in the DB.
  Provider calls have an eight-second budget with at least ten seconds between
  FIFO advances (four seconds for full replacement). Full replacement additionally needs temporary staging capacity.
- Closing/backgrounding Telegram stops the client loop after the current request.
  Select the original register and **Resume saved import**. Its unsynced saves
  start syncing; **Resume processing** continues a paused stage or failed write.
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

## Resetting Portal after legacy intake

The confirmed Admin reset now includes the selected owner?s legacy uploads,
private chunks, drafts and provenance in its disclosed deletion closure. It
removes their cutover holds in the database transaction. A historical HB action
without a signed requisition is valid legacy history, not a foreign signed order.
Real cross-group order/provenance links still block before Sheet deletion. Raw
spreadsheet rows without provable case UUID ownership remain in the Sheet.

The reset still needs an active Superuser, verified backup reference and explicit
confirmation. If an earlier reset failed, maintenance remains enabled until the
operator resolves it; successful retry does not infer permission to change a
pre-existing maintenance mode. Check the maintenance state before resuming
imports. This document does not authorize a production reset.
