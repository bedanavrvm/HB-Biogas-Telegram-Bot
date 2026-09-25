# Pipeline Portal Mini App — extended test inventory (reference)

The active human checklist is now [Portal QA human checks](portal-qa-human-checks.md), recorded in the Unfold QA tracker. This older inventory is retained for coverage review and automation-gap triage; do not copy it into a spreadsheet or treat every assertion below as a recurring manual step.

This is a **human-run acceptance checklist**, not a claim that the Portal has passed these tests. Use it after a deployment, for a release rehearsal, or when investigating a regression. It covers the Portal itself and the Portal-facing Google Sheets, Google Drive, document, and Telegram handoffs; it does not replace separate TAT, Complaints, SPIN, or Origination Mini App test plans.

## How to run and record a test

For each checkbox, record **Pass / Fail / Blocked / Not applicable**, tester, date/time, device, case reference, and a screenshot or short observation in the run log. Never paste customer IDs, phone numbers, tokens, signed files, or full error logs into a shared run log. Record the short support reference and retain sensitive evidence only in an approved restricted location. A test is **Blocked**, not passed, when the required role, feature flag, file, integration, or case state is unavailable.

Use the following run-log row for every failed or blocked item:

| Test ID | Result | Role / device | Test-case reference | Expected vs observed | Screenshot / support reference | Owner / retest |
|---|---|---|---|---|---|---|
| | | | | | | |

**Production safety:** Obtain approval for the specific test records and external writes before beginning. Do not reset the Portal, alter official number registers, upload a signed/stamped document, send a real notification, or issue a real payment merely to complete this checklist. Those are controlled checkpoints below; mark them Blocked if they are not authorized. Use clearly identified, consenting test records and approved files. Never reuse a real customer's identity, phone, or invoice. Record official numbers consumed during testing and arrange their formal voiding if applicable. Google Drive files can remain after a local reset, so do not assume a reset cleans external storage.

### Test roster and fixtures

Create or identify separate scoped accounts for a JBL/BRO officer, credit analyst, Head of Rural, Operations Administrator, HomeBiogas staff member, Management, Branch Manager (for linked Origination access), and IT. A Management or Branch Manager account with no Portal screen capability should be tested for its limited/denied Portal launch, not granted an extra role just to make the checklist work. Test with one ordinary role at a time; an IT or Superuser account cannot prove ordinary-role restrictions. Give at least one account a different branch/group scope for negative access tests. Record each account's approved group, branch, product, and capabilities before testing.

Prepare the following **controlled** records/files; reuse a case across stages only where its history will remain unambiguous:

| Fixture | Purpose |
|---|---|
| A — normal FarmUp lead | Full HB visit → JBL visit → credit → approval → order → installation → commissioning path. |
| B — JBL-created lead | Visit before FarmUp; later FarmUp update, including county preservation. |
| C — Eco-conserve lead | Nakuru and/or an Eco-conserve salesperson variant; partner-specific Sheet and order numbering. |
| D — identity difference | Invoice name/ID mismatch, household review, change-of-invoice letter and corrected replacement. |
| E — cash payment | Per-case switch from default Loan–Jawabu to Cash. |
| F — adverse/rework | Missing visit evidence, credit decline, final deferral, condition, correction, or reappraisal. |
| G — duplicate/retry | Re-uploaded FarmUp/SysUp row, repeated invoice, double tap, stale form, and refresh. |
| H — out-of-scope | A case owned by a different authorized branch/group. |

Prepare a FarmUp CSV plus changed second version, a SysUp CSV/XLSX plus unchanged and changed repeats, sample photo/PDF evidence, a multi-invoice PDF (including one unreadable page), a corrected invoice, an authorized signed/stamped order scan, and—only if approved—an authorized signed/stamped payment scan. Keep a private mapping of fixture IDs to actual test-case references; do not put PII in this document.

### Choose a starting track

- [ ] **SET-01 · IT/Operations · Empty Portal:** Confirm this group is intentionally empty, the correct group configuration and Master Data/Eco-conserve tabs exist, and a backup/snapshot and owner are recorded. **Expect:** no operational cases or old batches appear; global catalogues, access grants, and other workflows remain intact. **Alternative:** existing records or ambiguous legacy ownership require investigation; do not reset or overwrite them casually.
- [ ] **SET-02 · IT/Operations · Existing Portal:** Inventory existing cases, batches, official next numbers, Sheet tabs and current sync health; reserve distinguishable test references. **Expect:** test data can be isolated from live work without changing existing records. **Alternative:** if isolation is impossible, mark affected destructive tests Blocked.
- [ ] **SET-03 · IT · Both tracks:** Confirm Telegram launchers, scoped AccessGrants, branch/product availability, sheet credentials, Drive access, document templates, order/payment number registers, and enabled feature flags. **Expect:** each prerequisite is either healthy or explicitly marked unavailable in the run log. **Alternative:** a missing integration is not a reason to bypass authorization or insert data directly into Sheets.
- [ ] **SET-04 · IT · Controlled reset only:** If a separately approved clean-slate reset is part of the run, preview its group-scoped manifest, confirm a verified backup reference, manually account for prior issued documents, and execute only for the selected group. **Expect:** Portal operational links are cleared, verified case-ID Sheet rows are removed, Drive objects and restricted compliance evidence remain, other groups/workflows are unchanged, and failure leaves Portal read-only for recovery. **Alternative:** unowned/cross-group data or unverifiable Sheet rows must stop the reset for review.

## 1. Launch, shell, navigation, and common behavior

- [ ] **NAV-01 · Every role:** Open the Portal from the approved Telegram launcher on a phone. **Expect:** the correct account and authorized landing screen load once, with readable loading feedback; no unexplained external browser is opened. **Alternative:** expired/missing identity gives a clear re-open or access action, not a blank screen.
- [ ] **NAV-02 · Every role:** Open the menu and bottom navigation, then visit every destination shown for that account. **Expect:** active destination, page title, icon, and Back behavior agree; unauthorized screens are absent. **Alternative:** a direct URL to a forbidden screen is denied server-side without exposing its data.
- [ ] **NAV-03 · Every role:** Move list → case/detail → preview → Back/Close, then use Android/Telegram Back and browser Back/Forward. **Expect:** one step returns to the immediate origin, preserving useful search/filter context where designed, without returning to an unrelated dashboard or closing the app unexpectedly. **Alternative:** refresh on a detail URL loads that detail or gives an actionable error.
- [ ] **NAV-04 · Every role:** Use the notification bell on a narrow phone. **Expect:** a compact, fixed-size tap target; badge and panel remain within the viewport, and a selected notification opens and focuses its exact case/action. **Alternative:** a refresh does not immediately erase the focus/highlight.
- [ ] **NAV-05 · Every role:** Receive a success, warning, validation error, and server error. **Expect:** one plain-language toast/dialog, a usable short support reference for server failures, no raw traceback or duplicate alert; controls recover after dismissal. **Alternative:** retrying an uncertain write must not create a second record.
- [ ] **NAV-06 · Every role:** Lose and restore network while a list is open. **Expect:** already loaded data remains readable with an offline notice; writes/uploads are prevented or fail clearly; refresh succeeds when online. **Alternative:** no offline action is silently reported as saved.
- [ ] **NAV-07 · Every role:** Leave a form open, switch apps, resume, and refresh. **Expect:** unsaved data is not silently overwritten by background polling; save/recovery behavior is explicit. **Alternative:** a stale revision produces a conflict/reload choice, not data loss or duplicate submission.
- [ ] **NAV-08 · Every role:** Test empty list, one item, many items, search with no result, pagination, reset/clear search, and list refresh. **Expect:** counts, visible rows, filters and page position are coherent; no stale item remains clickable after a status change.
- [ ] **NAV-09 · Every role:** Inspect dates/times in cards, details, history, toasts, and exports. **Expect:** Kenyan local display is consistent; date inputs and filters use the approved day-month-year presentation where applicable; relative time matches the displayed timestamp.
- [ ] **NAV-10 · Every role:** Open a document or image preview, then close it. **Expect:** an in-app authorized preview where supported, visible filename/type, usable zoom/scroll, and return to the exact prior screen; a download asks for confirmation and identifies the file. **Alternative:** missing file or denied access gives a clear message and no public Drive URL.

## 2. Home and performance

- [ ] **HOME-01 · Dashboard-capable role:** Open Home before and after adding a test case. **Expect:** queue counts, current pipeline, completed-work statistics, recent/urgent cases, scope, and Updated time reflect authorized data, not click or screen-visit counts. **Alternative:** zero-data sections have plain empty states.
- [ ] **HOME-02 · Dashboard-capable role:** Tap each visible queue, urgent case, and recent case. **Expect:** the destination matches the card and focuses the relevant case where possible; unavailable destinations are not offered to the role.
- [ ] **HOME-03 · Dashboard-capable role:** Change a case stage, then refresh Home. **Expect:** it leaves the old queue, enters the right new queue, and is counted once. **Alternative:** an external Sheet/Drive publication delay does not falsely move the canonical case backward.
- [ ] **PERF-01 · Authorized staff:** Change the performance month and compare a month with no completed visits, a low sample, and an eligible sample. **Expect:** clear on-time rate, counted visits/stages, ranking eligibility, and provisional/live wording; no technical formula wall in ordinary rows.
- [ ] **PERF-02 · Head of Rural/IT versus ordinary staff:** Compare the same standings. **Expect:** named-person breakdown appears only with its capability; ordinary users see their own result and permitted anonymized standings, not hidden names, raw cohort IDs, or audit-only calculations.
- [ ] **PERF-03 · IT · Controlled correction:** Correct an eligible historical stage/visit, then revisit the month. **Expect:** displayed results update under the existing retrospective policy; any frozen/recognition result remains visibly distinguished from live figures.

## 3. FarmUp monthly worklists and SysUp imports

- [ ] **FARM-01 · Operations/IT:** Upload the approved FarmUp CSV. **Expect:** a named monthly batch/version is staged, not committed automatically; mapping summary, row counts and review states are visible. **Alternative:** wrong file type, empty file, malformed headers or network failure leave no partial customer commits.
- [ ] **FARM-02 · Operations/IT:** Inspect or change column mappings, ignored columns, and a staged row. **Expect:** source value and canonical field remain distinguishable; validation pinpoints the field and row; the original uploaded file remains unchanged.
- [ ] **FARM-03 · Operations/IT:** Search, sort, filter and switch compact/table presentation on phone; open a row. **Expect:** names and status stay readable, frozen columns are opaque, table viewport shows useful rows, and edit controls do not cover data. **Alternative:** long text is readable in detail/copy, without overlap.
- [ ] **FARM-04 · Operations/IT:** Select only reviewed rows and commit. **Expect:** selected valid rows enter Django; unselected/held rows do not block the commit and remain available for later review; repeated tap does not duplicate cases.
- [ ] **FARM-05 · Operations/IT:** Upload an identical second version, then a version with legitimate changes. **Expect:** unchanged committed rows are recognized; changed rows show the difference and update the same case only after review. **Alternative:** ambiguous identity or conflicting source data is held with an actionable reason.
- [ ] **FARM-06 · Operations/IT:** Check FarmUp lead name, deposit paid to HB, salesperson, branch/county and source after commit. **Expect:** HB deposit is a whole number in the Sheet, not the JBL LGF balance; salesperson variations route Eco-conserve where applicable; canonical county collected by JBL is not overwritten on later FarmUp reconciliation.
- [ ] **FARM-07 · Operations/IT:** Check publication after a successful local commit. **Expect:** Django case exists immediately and the correct Master Data or Eco-conserve row is eventually updated by immutable Case ID. **Alternative:** Sheet failure is shown as a retryable publication problem with affected case/field, not as a failed local commit or duplicate row.
- [ ] **FARM-08 · Operations/IT:** Archive a completed worklist, then search history and attempt an old version. **Expect:** records remain traceable and read-only according to archive policy; archive does not delete operational cases or external files.
- [ ] **SYS-01 · Operations/IT:** Upload a valid SysUp export and map its columns. **Expect:** rows are staged, matched against existing cases, and not committed until selected; source identity and proposed applicant/loan-officer fields are clear.
- [ ] **SYS-02 · Operations/IT:** Commit a selected matched row whose name order/spelling differs but whose identity is confirmed. **Expect:** a non-selected or unrelated review warning does not block it; SysUp applicant name remains separate from the FarmUp lead name; JBL BRO is updated from the loan-officer value.
- [ ] **SYS-03 · Operations/IT:** Re-upload identical and changed SysUp rows. **Expect:** identical already-committed rows are not selected for another commit; changed values can be reviewed and update the existing case once. **Alternative:** unresolved identity/duplicate conflict identifies the row and field, without changing a different customer.
- [ ] **SYS-04 · Operations/IT:** Upload missing/invalid columns, mixed valid and invalid rows, and a non-catalogue product label. **Expect:** actionable row-level feedback; valid selected rows can proceed where policy allows, and a source product label alone is not an unnecessary hard blocker.

## 4. JBL visit and customer case creation

- [ ] **VISIT-01 · BRO:** Find FarmUp fixture A in the Visit Queue using search, branch/product and HB/JBL date filters. **Expect:** only eligible, in-scope cases appear; date ranges include their endpoints, clear correctly, and use the approved display format.
- [ ] **VISIT-02 · BRO:** Open the visit form and inspect all identity, contact, product, location and HB-source fields before editing. **Expect:** values are labeled by source, missing fields are obvious, and the form does not imply that FarmUp and SysUp names must match textually.
- [ ] **VISIT-03 · BRO:** Save a partial visit draft, leave, return and complete it. **Expect:** recoverable text fields return to the same case; attachment selection is not falsely shown as persisted; completion writes one visit with a clear confirmation.
- [ ] **VISIT-04 · BRO:** Exercise required-field, invalid mobile/ID, invalid amount/date, and future/impossible date validation. **Expect:** inline, specific guidance before submit and the same rejection server-side; Kenyan 01/07 mobile formats and 1–9 digit National ID/Maisha numbers are accepted structurally where those fields apply.
- [ ] **VISIT-05 · BRO:** Capture a visit photo, attach required ID/LAF evidence, preview each, then cancel and retry. **Expect:** camera permissions and file alternatives are understandable; previews are in-app; cancelling does not upload unsubmitted media; completed files attach to the right case.
- [ ] **VISIT-06 · BRO:** Use voice input for a supported narrative field, then edit the transcription before saving. **Expect:** the resulting text is visible and editable, recording/cancel state is clear, and an unsupported device or permission denial leaves typed input usable.
- [ ] **VISIT-07 · BRO:** Complete a visit, double-tap submit, and refresh. **Expect:** one completed visit, one current case revision, correct next queue, and no duplicate media/events. **Alternative:** an uncertain network response offers a safe status check or retry.
- [ ] **VISIT-08 · BRO:** Open My Submitted Visits, then a case and its timeline. **Expect:** the officer's submissions and current outcomes are visible within scope; the timeline groups same-action uploads under the visit rather than repeating near-identical top-level entries.
- [ ] **VISIT-09 · BRO:** Create fixture B directly from the Visit Queue, including HB deposit and HB salesperson, then later reconcile it through FarmUp. **Expect:** source is JBL initially; subsequent HB fields may update from FarmUp, while the JBL-collected canonical county remains unchanged and no second case is created.
- [ ] **VISIT-10 · Different-branch BRO:** Search/open fixture H and attempt a direct visit URL. **Expect:** scope is enforced server-side, not just by a hidden card.

## 5. Credit analysis, final decision, and rework

- [ ] **CREDIT-01 · Analyst:** Open a completed JBL visit in Credit Analysis. **Expect:** needed visit evidence, applicant identity, source data and previous actions are accessible within scope; no incomplete or unauthorized case is silently actionable.
- [ ] **CREDIT-02 · Analyst:** Save a partial decision, return, then submit an allowed outcome and comment. **Expect:** draft recovery, clear validation, one audit entry, correct next queue and updated TAT; stale/duplicate submission does not create two decisions.
- [ ] **CREDIT-03 · Analyst:** Decline or raise a condition on fixture F. **Expect:** the reason/condition is visible to the next responsible person; the case goes to the appropriate deferred/rework state, not straight to order preparation.
- [ ] **FINAL-01 · Head of Rural:** Review a credit-approved case with its visit evidence and conditions, then approve it. **Expect:** decision authority, identity and evidence revision are clear; the case enters Ready for Order once, with audit and notification.
- [ ] **FINAL-02 · Head of Rural:** Defer/decline or return fixture F for rework with a reason. **Expect:** owner and next action are visible in Deferred/Reappraisal and notifications; the earlier approval is not treated as current after material correction.
- [ ] **FINAL-03 · Unauthorized role:** Attempt credit or final decision via direct URL or stale tab. **Expect:** a permission denial with no state change; Operations' processing access does not silently grant Head of Rural authority.
- [ ] **FINAL-04 · Authorized delegate, if configured:** Exercise an active delegation, then expiry/revocation. **Expect:** only the delegated scope/action works while valid, and the timeline records acting and authorizing identities without duplicative display.

## 6. Order preparation, signed order, and HB release

- [ ] **ORDER-01 · Operations:** Find approved cases in Order Preparation; select multiple eligible cases and preview the workbook. **Expect:** selected names/IDs, partner, amounts, warnings and next official number are reviewable before finalization; non-blocking warnings do not prevent a draft workbook.
- [ ] **ORDER-02 · Operations/IT:** Verify HB and Eco-conserve next-number settings against the official registers before generating. **Expect:** distinct partner sequences, reasoned changes with audit, and no duplicate official number. **Alternative:** unauthorized roles cannot see or change sequence settings.
- [ ] **ORDER-03 · Operations:** Generate and download a workbook, including a case with a corrected invoice pending or non-identical FarmUp/SysUp name. **Expect:** the workbook uses the intended lead and SysUp name columns; download confirmation identifies the file; only true finalization blockers stop the action and name the case/field.
- [ ] **ORDER-04 · Operations:** Review the order batch and document archive, then submit an authorized printed/stamped/signed scan of that exact order version. **Expect:** a scan of different file type/content is accepted through human attestation, not rejected for hash mismatch with the workbook; the exact official version becomes signed and fixture A appears in HB Installation.
- [ ] **ORDER-05 · Operations:** Retry the same scan submission and attempt an old/superseded version. **Expect:** repeat is idempotent; a wrong version or unsupported file is rejected without double-releasing HB work.
- [ ] **ORDER-06 · HB staff:** Open the signed order preview from a case they can access. **Expect:** in-app preview works and does not expose the document for another group/case; HB does not need a separate Finalized Orders navigation item just to reach its authorized documents.

## 7. HB installation and commissioning

- [ ] **HB-01 · HB staff:** Open HB Action after the accepted signed order. **Expect:** fixture A starts **Not installed** in Installation; Commissioning is not separately actionable until installation is recorded. Search uses available width and the two workstream tabs are distinct.
- [ ] **HB-02 · HB staff:** Report an installation delay without marking installed. **Expect:** only the pending installation comment and relevant save control appear; the case remains Not installed, with the new comment in history and Sheet projection.
- [ ] **HB-03 · HB staff:** Choose Mark as installed. **Expect:** only actual installation date, optional serial number and optional two-state report-submitted checkbox are requested; planning/readiness fields and commissioning inputs stay hidden. A valid save moves the case to Commissioning as Not commissioned.
- [ ] **HB-04 · HB staff:** Try a future installation date, missing required actual date, duplicate save and a completed-record correction. **Expect:** clear field validation, idempotent or conflict-safe saving, and a correction reason only in actual correction mode.
- [ ] **HB-05 · HB staff:** Open Commissioning immediately after installation. **Expect:** installation date and the standard 21-day readiness date are correct; “ready in” uses the current Nairobi date and never shows a contradictory number. Early commissioning requires explicit acknowledgement; it is not silently accepted or categorically hidden.
- [ ] **HB-06 · HB staff:** Add a pending commissioning comment and optional additional remarks without completing commissioning. **Expect:** the case remains Not commissioned; both notes remain distinguishable, and remarks project to the CS Remarks column.
- [ ] **HB-07 · HB staff:** Record actual commissioning after the readiness date. **Expect:** actual date is required, future date is rejected, the case becomes Commissioned, and the Installation tab does not grow a second commissioning form.
- [ ] **HB-08 · HB staff versus Operations:** Compare HB Action permissions and document previews. **Expect:** HB can update its work and preview in-scope order/invoice evidence; Operations can inspect as authorized but cannot impersonate an HB action merely because it can view the queue.
- [ ] **HB-09 · Both roles:** Open a case with an invoice received before installation. **Expect:** the invoice is visible as supporting evidence; it does not falsely mark the unit installed or remove it from the Installation queue.

## 8. Invoice delivery, extraction, reconciliation, and name change

- [ ] **INV-01 · HB/Operations:** Receive a controlled multi-invoice PDF delivery. **Expect:** each page/record is represented in the upload batch, with source preview and separate parsing/matching status; a failed page is identifiable without losing successful pages.
- [ ] **INV-02 · HB/Operations:** Upload an invoice bearing an order label and a mismatching number. **Expect:** the order-number mismatch is prominently flagged, but parsing and identity matching can continue; the source text and parsed value remain reviewable.
- [ ] **INV-03 · HB/Operations:** Open an invoice record and inspect every parsed field, including missing ID. **Expect:** every extracted field is listed, editable through an explicit toggle, and saving a manual correction updates the draft with audit evidence. A missing ID is not incorrectly described as extracted.
- [ ] **INV-04 · HB/Operations:** Match a valid invoice to fixture A. **Expect:** the candidate list gives enough name/ID/order context, a confirmed match is visible, and the invoice is linked once. **Alternative:** ambiguous candidates require human choice; no name-only auto-match crosses identities.
- [ ] **INV-05 · Operations:** Use fixture D with spouse/household identity. **Expect:** original invoice and applicant identities remain distinct; the change-of-invoice flow shows letter preview/download, sent/follow-up state, and replacement candidates; payment remains blocked until the corrected replacement is confirmed.
- [ ] **INV-06 · HB/Operations:** Ignore, restore, unmatch and re-match a test invoice. **Expect:** each action changes the right list/count and is audited; ignored invoices are not payment candidates; bulk actions state exactly which records will change.
- [ ] **INV-07 · HB/Operations:** Upload duplicate, invalid, password-protected or unparseable files. **Expect:** clear batch-level and page-level errors, safe retry, no duplicated matched invoice, and no misleading “success” for a failed extraction.
- [ ] **INV-08 · HB/Operations:** Search/filter Needs action, Matched, Ignored and All; open a card, its top-right actions and source preview. **Expect:** compact cards, clear count pills, whole-card detail opening, correct Back destination, accessible three-dot menu, and no horizontal overflow.

## 9. Payment preparation, review, signed scan, and Sheet projection

- [ ] **PAY-01 · Operations/HB:** Begin payment from a received invoice delivery containing multiple invoices. **Expect:** eligible matched invoices are selectable together; held/unmatched items stay visible with reasons but are not payable; one delivery remains traceable to its batch.
- [ ] **PAY-02 · Operations/HB:** Open an invoice-matched candidate card. **Expect:** the compact collapsed card identifies the case and state; expanded detail shows name, national ID, phone, branch, officer and relevant invoice/payment context with aligned actions.
- [ ] **PAY-03 · Operations/HB:** Add fixture A and fixture E. **Expect:** each defaults to Loan–Jawabu; switching E to Cash is obvious and affects only E; remove/re-add and duplicate tap do not create duplicate membership.
- [ ] **PAY-04 · Operations/HB:** Submit the batch for review. **Expect:** an official payment number follows the governed allocation point; membership and modes remain traceable; a mismatch or missing required case field names the affected case and field rather than presenting a generic error.
- [ ] **PAY-05 · Head of Rural:** Review each case and its mode, approve/return as allowed, then generate the approved workbook. **Expect:** per-case decisions are visible; unresolved cases prevent a final approved workbook but not unrelated draft review; generated version reflects the exact approved membership and comments.
- [ ] **PAY-06 · Operations/Head of Rural:** Change membership/mode after a workbook version, where policy permits. **Expect:** the old version is visibly superseded and cannot be used as the current signed artifact; a fresh review/workbook is required.
- [ ] **PAY-07 · Authorized signer · Explicit approval required:** Upload the signed/stamped payment scan and confirm its version. **Expect:** payment becomes final only on accepted sign-off, Payment No # projects to the correct Sheet row, and the case does not appear payable twice. **Alternative:** wrong version/file or missing attestation is rejected without finality.
- [ ] **PAY-08 · All payment roles:** Search Open, Completed, Cancelled and All; inspect 50+ card layout or a paginated equivalent. **Expect:** closed batches are compact, counts match, first-screen space is useful, cards open reliably on small phones, and Back returns to the right filtered list.
- [ ] **PAY-09 · Operations/IT:** Compare the official payment register and Sheet projection; test a permitted sequence adjustment with a reason only under separate authorization. **Expect:** no automatic number reuse, currency/Decimal values are unchanged, and LGF Balance is not confused with deposit paid to HB.
- [ ] **PAY-10 · Operations/HB:** Replace a wrong invoice item inside a received delivery before payment. **Expect:** the replacement points to the corrected invoice, preserves the delivery's history, and recalculates candidate eligibility without silently retaining the old item as payable.

## 10. Case inspection, documents, reports, and settings

- [ ] **CASE-01 · Authorized staff:** Search All Cases by name, ID, phone and case reference; apply HB/JBL visit date ranges and stage/status filters. **Expect:** filters show relevant available options, combine predictably, clear fully, and do not leak out-of-scope cases.
- [ ] **CASE-02 · Authorized staff:** Open fixture A's Case History from several originating screens. **Expect:** identity, current pipeline state, visits, grouped timeline, TAT, comments, documents and data-quality issues agree with source actions; Back returns to the originating list.
- [ ] **CASE-03 · Operations/IT:** Correct a permitted case field. **Expect:** old and new values, reason, actor and time appear in history; unrelated canonical fields remain unchanged; ordinary staff see read-only values.
- [ ] **CASE-04 · Authorized staff:** Inspect Deferred/Reappraisal and a condition cleared later. **Expect:** reason, responsible party, date/next step and current status are plain; resolved cases do not remain as urgent without a new reason.
- [ ] **CASE-05 · Authorized staff:** Inspect a case with GPS, media, comments and a missing-location counterpart. **Expect:** the map and evidence belong to the opened case, map failure has a usable fallback, comments have clear author/time, and absent coordinates do not display a false location.
- [ ] **DOC-01 · Authorized roles:** Open Document Archive for generated order and payment artifacts; open an invoice-name-change letter from its invoice workflow. **Expect:** filenames, version/finality, preview/download actions, sign-off status and related case/order are understandable; inaccessible files fail safely.
- [ ] **REPORT-01 · IT:** Open curated reports and a saved report; change scoped filters, run, inspect charts/table, and export. **Expect:** figures match current Django records and selected scope, empty states are clear, tables are readable, and export confirmation names the file. **Alternative:** unauthorized roles cannot access report definitions or data by direct URL.
- [ ] **REPORT-02 · IT:** Create/edit/archive a report definition where enabled. **Expect:** only catalogue-approved fields/charts are offered, version changes are evident, and an archived report cannot masquerade as current.
- [ ] **SETTINGS-01 · Every role:** Open Settings. **Expect:** account/access summary and personal start screen/queue preferences are available; save and clear persist across relaunch; only authorized destinations can be chosen.
- [ ] **SETTINGS-02 · Operations/IT versus ordinary roles:** Compare panels. **Expect:** official number settings, sync/health controls and TAT target controls appear only with their specific capability; ordinary HB/BRO/Management accounts do not see unrelated administrative sections.
- [ ] **SETTINGS-03 · IT · Separate authorization:** Change a future Portal TAT target and inspect an old and new stage. **Expect:** new work uses the new target; already-started work keeps its frozen target; change is audited.
- [ ] **SETTINGS-04 · Operations/IT:** Inspect a Google Sheets publication warning and open its resolution path. **Expect:** affected operation, case/field/tab and retry action are identifiable where available; retry is capability-gated and idempotent, not an unexplained redirect to Settings.
- [ ] **WORK-01 · IT, if private workspace is enabled:** Pin/unpin a case, inspect recent cases, clear recents, save a filtered view, make it the start view, then revoke the underlying access. **Expect:** these remain private to the user, clearing recents does not delete cases, and a saved view that is no longer authorized is unavailable rather than leaking data. **Alternative:** if the retained IT-only workspace is disabled, record Not applicable rather than expecting it for ordinary staff.
- [ ] **HEALTH-01 · Operations/IT:** Inspect Portal health and maintenance state; test an IT-authorized maintenance change only during an approved window. **Expect:** read-only mode prevents writes with a clear explanation while safe reads remain available; restoring live mode requires the proper capability and leaves an audit trail.

## 11. Access, resilience, accessibility, and layout matrix

- [ ] **ACCESS-01 · Every test account:** Compare visible navigation/actions against assigned capabilities; also try one forbidden deep link and one out-of-scope case. **Expect:** server and UI agree, with no data leak or state change. Specifically distinguish HB from Operations, Head of Rural from Operations, named performance from ordinary standings, and personal Settings from operational Settings.
- [ ] **ACCESS-02 · IT:** Revoke or expire a controlled grant/delegation while its user has the Portal open. **Expect:** subsequent reads/writes respect the new policy; cached screens cannot submit privileged actions.
- [ ] **RES-01 · Every write workflow:** Tap twice, retry after a timeout, refresh after success, and submit an old revision. **Expect:** one authoritative result; an explicit conflict or status check when uncertain; no duplicate visit, approval, order, invoice, payment or HB event.
- [ ] **RES-02 · IT/Operations:** Simulate or observe a permitted Sheet/Drive outage without disrupting production service. **Expect:** local committed state remains honest, external operation is retryable/visible, pending vs failed is clear, and a later retry updates the same destination row/file reference.
- [ ] **RES-03 · Every role:** Exercise loading, empty, forbidden, validation, unavailable media, session-expired, offline and server-error states. **Expect:** plain language, a next action, compact reference if support is needed, and no customer data or stack trace in the message.
- [ ] **UX-01 · Every representative screen:** Check 320×568, 360×800 and 430×932 phones; portrait and landscape where supported; one desktop width. **Expect:** no horizontal page scroll, clipped action, full-width bell/filter icon, transparent overlapping table column, oversized card, or orphaned Back button row.
- [ ] **UX-02 · Every representative screen:** Check light/dark themes, large text, keyboard-only navigation on desktop, focus order, labels, expanded/collapsed state, and screen-reader names for icon-only buttons. **Expect:** readable contrast and at least one discernible way to operate every essential action without relying on color alone.
- [ ] **UX-03 · Lists and forms:** Check long names, long comments, missing optional values, 50+ records, an empty result, an opened card, and an on-screen mobile keyboard. **Expect:** text wraps/clamps without hiding identity, controls remain aligned, sticky actions do not cover fields, and the user can reach the bottom of every form.
- [ ] **UX-04 · Document/table surfaces:** Long-press/copy a permitted table value, close a preview, and open a download confirmation. **Expect:** copied value is confirmed, the modal chain returns correctly, filenames are clear, and protected media does not escape into a public link.

## 12. End-of-run reconciliation and sign-off

- [ ] **END-01:** Re-open each fixture's current Portal state and reconcile its expected stage, owner, official numbers, invoices, payment mode, installation/commissioning status, TAT and grouped timeline. Record discrepancies by test ID.
- [ ] **END-02:** Compare test-case rows in Master Data and Eco-conserve using immutable Case ID. Confirm correct routing, no duplicate rows, no misplaced payment number, and source-specific name/deposit fields. Record any pending publication operation separately from canonical Django state.
- [ ] **END-03:** Inventory uploaded media and generated/signed documents in the restricted document history. Arrange authorized cleanup/voiding under retention policy; **do not** delete Drive objects or reset the Portal as an automatic test teardown.
- [ ] **END-04:** Reconfirm official next order/payment numbers with their register owner, revoke temporary access/delegations, close controlled test notifications, and attach the completed run log and defects to the release decision.
- [ ] **END-05:** Mark the release **not fully verified** if any high-risk item (identity, permissions, signing, official numbering, payment values, Sheet routing, or cross-group isolation) is Failed or Blocked. Retest fixes with the same fixture and a new clean fixture.

### Defect report template

**Test ID / severity:**  
**Role, group/branch and device:**  
**Fixture reference (no PII):**  
**Starting case state and screen:**  
**Actions taken:**  
**Expected / observed:**  
**Short support reference and time:**  
**Screenshot or restricted evidence location:**  
**Was a write or external publication attempted?**  
**Current canonical case state, Sheet state, and document state:**  
**Safe retry/cleanup owner:**
