# Portal Mini App: synthetic workflow and bulk-document review

The later [state and recovery follow-up](portal-state-recovery-review-2026-10-29.md)
covers the lost-response, simultaneous number-claim, expired-approval,
invoice-letter and changing-access gaps listed below. This document retains the
original bulk-review evidence and its point-in-time limits.

29 October 2026. The core intake-to-commissioning journey, negative outcomes,
bulk documents and recovery paths below were exercised. Reproducible defects
were corrected. This is local implementation evidence; it does not certify that
every Portal feature or a production deployment is free of issues.

Open the [screenshot and document gallery](../test-results/portal-workflow-review/index.html).
All screenshots, workbook bytes, Excel-exported PDFs, request observations and
the final reconciliation are in `test-results/portal-workflow-review/`.
That directory is intentionally ignored by Git and remains in this checkout.

## Method and scope

The review uses the real Django Portal shell, JavaScript, signed Telegram
identity verification, owning-workflow permissions, services and migrations.
Its dedicated PostgreSQL database is `portal_workflow_review_test`, on loopback
port 55476. Six ordinary scoped roles were used: JBL officer, Credit Analyst,
Head of Rural, Operations Administrator, HB and Portal IT. A seventh identity
has no Portal grant. A second group's case provides an explicit denial target.

Playwright drives actual forms, file inputs, paginated selection, confirmation
dialogs, navigation and retry controls. Authenticated browser requests exercise
larger cohorts and additional invalid/stale submissions; these are distinguished
from visible UI interactions below. No test runner, test files, assertions, lint
or type checks were written or run for this review.

Google Sheet and Drive transports are local substitutes; the durable operation
queue, workflow services, document generation and retained Django bytes are real.
The review server excludes deployment environment loading and blocks external
network connections in its process. Invoice parsing uses the real isolated PDF
worker with explicit synthetic database settings. This is not evidence of real
Google, Telegram, email or SMS delivery. No operational database, real group,
production configuration, browser release flag or approved UI baseline changed.

The final dataset has 3,378 cases: 3,377 in scope and one foreign-group case.
Many are deliberately pre-staged legacy/backlog fixtures. Their presence does
not establish that earlier intake steps were performed. Separately, 1,100 cases
were created through FarmUp commits and one office lead was taken through the
full real workflow. Only synthetic identity and document values were used.

Excel opened downloaded workbooks read-only and exported their actual print
layout. Independent PDF extraction compared every generated row's identity,
name and comment with the workbook. All pages of the final documents were
rendered to images; representative first, middle and final pages were visually
inspected. Existing signed/historical bytes were retained unchanged.

## Defects found and corrected

| Defect and observed effect | Correction and follow-up evidence |
|---|---|
| Group-scoped queues appeared empty for all six ordinary roles. | Supply the missing group relation to the canonical query scoper. Initially all six recovered their 2,026 authorized cases; foreign-group reads remained 403. `role-scope.js.result.json`, `scope.js.result.json`. |
| Orders and payments generated more rows than Excel printed. A 125-case order printed only 16 IDs; a 60-case payment printed only 17 rows and omitted the total. Footer merges also hid county values. | Resize merged ranges, row dimensions, print boundaries, image anchors and page breaks with the table. Repeat headings and use one-page-wide, multiple-page-high printing. Final 252-case order and 61-case payment include every row. |
| Long order names and comments were clipped, including after the print-area repair. | Calculate wrapped row height from each text column's width and font instead of the old 60-point ceiling. The final 252-row PDF contains every full name and comment. Payment comments use the same helper. |
| Unlinked legacy cases could reuse another case's iMAB number. | Do not exclude all null-customer records from the duplicate query. Only a real shared customer permits that exclusion. Actual credit UI accepted a duplicate before repair and rejected a subsequent legacy duplicate afterward. |
| Expected decision/import/cancellation/signoff errors lost their explanation. | Add explicit safe domain codes at the HTTP boundary so reviewed messages survive response normalization. Uncaught exceptions retain generic errors. Screenshots show the duplicate-number reason and retained-scan retry guidance. |
| A signed scan could be accepted against a workbook amended after its upload form opened. | Bind History and Payment forms to source version/checksum; compare under the existing source lock. An actual v1-to-v2 amendment now produces 409 from the stale open form, retaining the selected file. Missing HTTP binding is rejected. |
| Merged, repeated or unrecognized invoice files produced generic failures. | Preserve the PDF worker's safe policy error and return specific 400 guidance. The one-invoice-per-file rule and delivery limits remain enforced. `invoice-negative-ui-after.js.result.json`. |
| Invoice auto-matching checked official-order eligibility for every unrelated lead. | Compare exact identity first, then prove order finality for possible matches. A 20-file delivery improved from 4 processed files / 13,443 SQL calls to 13 files / approximately 760 calls. Time-budget partial receipts remain necessary. |
| Document History did thousands of authorization queries for large workbooks. | Scope the entire retained membership in one query; fail closed for missing members. Observed calls fell from 3,110 to 47-52, with later local responses around 0.2-0.4 seconds. |
| A 500-row FarmUp commit took 46.3 seconds, beyond the browser request deadline. | Save the confirmed selection in 50-row requests, showing progress and retaining remaining selections. The actual 500-row UI run completed in ten requests; an interrupted worklist resumed without duplicates. |
| SysUp said zero remaining while 995 rows still awaited review. | Count remaining review rows rather than FarmUp dispositions. After 50 updates, the UI and response retain 995 unresolved rows. |
| Completed payment workbooks disappeared from History and their retained preview was unavailable. | Include Awaiting scan and Completed in read/archive statuses with accurate labels. The completed 61-case workbook opens with its retained scan; completed regeneration stays blocked. |
| A slow Orders response overwrote Payments after changing the History tab. | Ignore superseded loads. Playwright delayed the actual Orders response: before repair Payments displayed Orders; after repair it retained Payment #1. Both captures remain in the gallery. |

The shared workbook helper is `core/services/workbook_layout.py`. Other changes
stay in owning Portal API, identity, invoice, import, document and Mini App modules.
No schema migration, dependency, permission addition or product configuration
change is required.

## Large documents and throughput

| Cohort / action | Actual result | Retained evidence |
|---|---|---|
| 250 HB leads, selected across 25 visible UI pages | One order. Initial generation 13.206 seconds / 9,787 SQL calls locally. | `generate-250.js.result.json`, `order-250-selected-390.png` |
| Explicit unsigned amendments to 251 and then 252 leads | Same order identity; successive versions. The 251 amendment took 6.820 seconds. Final 252-case workbook: 19 pages, headings on all 19, no missing IDs, names or comments. | [252-case workbook](../test-results/portal-workflow-review/order-252-final.xlsx), [actual Excel PDF](../test-results/portal-workflow-review/order-252-final.pdf), `order-252-final-observations.json` |
| 60 cases through actual credit and final approvals, then one order | All 60 IDs print across five pages. | `approve60.js.result.json`, `order-60-after.xlsx`, `order-60-after.pdf` |
| 75 Eco-conserve cases | Separate partner order, six pages. Cancellation released its number; re-finalization reused ECO-1 under a new UUID. Concurrent finalization returned one 200 and one 409. | `orders-cancel-concurrent.js.result.json`, `order-75-reused-number.xlsx`, `order-75-reused-number.pdf` |
| Mixed-mode payment, initially 60 then 61 cases | Real return/correction/approval and generation. Adding the office lead invalidated old reviews/workbook; all 61 were reviewed again. Final v2: 42 Loan-Jawabu and 19 Cash, KES 2,891,500. Every name, customer number and full comment appears in the three-page PDF, including total. | [61-case workbook](../test-results/portal-workflow-review/payment-61-after.xlsx), [actual Excel PDF](../test-results/portal-workflow-review/payment-61-after.pdf), `payment-61-after-observations.json` |
| FarmUp 505-row worklist | Actual UI committed 500 selected valid rows in ten requests, about 4.4-5.9 seconds each / 49.266 seconds overall. Five invalid rows stayed held. | `farmup-500-ui-after.js.result.json`, `farmup-500-ui-progress.json` |
| FarmUp 105-row worklist, interrupted after first chunk | 50 saved; next request deliberately aborted before server receipt. Remaining 50 stayed selected. Retry finished 100 total, five held, no duplicate cases. | `farmup-interruption-recovery-ui.js.result.json`, interruption/resume screenshots |
| SysUp 1,045 rows | 50 matched rows selected and committed in bounded deliveries; 995 unmatched rows remained disabled/held. SysUp created no new cases. | `sysup-review-ui.js.result.json`, `sysup-50-committed-995-held-390.png` |

The Eco fixture uses sanitized HB template geometry: partner routing, numbering
and row growth are exercised, but this does not certify a deployed Eco-branded
template. The 125-row and intermediate 250-row PDFs are failure evidence, not
the corrected release output.

## Full case journey and realistic alternatives

The new office lead was visibly created with zero deposit and saved on hold.
HB recorded KES 5,000; JBL selected ID front/back, a two-page LAF and applicant
photo, and supplied GPS. A simulated Drive outage retained selected files and
left the visit unrecorded. Retrying recorded the visit and evidence. Credit and
Head of Rural approvals, a 252-case order amendment, accepted signed-order
evidence, invoice 779992, the 61-case payment, installation and commissioning
then completed. The actual early-commissioning confirmation was used. History
retains actors and transitions. Final serial is `SYNTHETIC-779992` and the case
displays Commissioned. Its canonical pipeline state remains `ordered`; HB Action
and Payment own their completed states.

The bulk cohort uses real authenticated approval requests rather than 60
repetitions of every visible form. Representative accepted and invalid forms
were exercised through the UI. Additional outcomes were verified using actual
authenticated browser requests and retained state:

| Boundary | Outcomes exercised and observed |
|---|---|
| Authorization | Ordinary role navigation and own-scope reads; foreign-group 403 for all six roles including IT; ungranted user denied. Wrong-role credit, final, deposit, payment review and reports denied. This is not a complete branch/product capability matrix. |
| Deposit | Negative amount and stale edit rejected; decrease requires reason and attribution; 4,999.99 leaves a 0.01 shortfall; recorded JBL visit locks editing. |
| Visit | Missing evidence, future date, chronology and stale revision rejected. Rescheduled, Deferred, Rejected, Cash and Other partner stay distinct. Exact reschedule retry does not advance revision. Rejected intake cannot be forwarded normally. |
| Credit / final | Missing/duplicate iMAB, missing rejection reason, Other without comment, expired deferral, repayment day 32 and stale revisions rejected. Rejection without iMAB valid. Rework requires reason; subsequent deferral retains stage ownership and existing identity. |
| Order finality | Accepted current scan locks the order; signed cancellation rejected with reason. Unsigned cancellation needs current version. Cancel/reuse preserves historical UUID and uses a new workspace. Concurrent finalization does not allocate duplicate live orders. |
| Signed evidence | Missing attestation, invalid file, wrong role, missing binding and superseded source rejected. Drive failure returns 202 with retained-scan guidance; retry accepts retained bytes. A full three-page synthetic payment scan replaced the initial state-machine fixture without replaying completion or changing payment revision 135. |
| Invoice | Separate invoice PDFs accepted. Merged/repeated and unrecognized content rejected with guidance. Duplicate delivery adds no file. Missing/mismatched identity stays in manual review; unsigned-order matching blocked. Ignore/restore works; wrong-role ignore denied. Completed-payment unmatching blocked. |
| Payment | Return needs comment; invalid mode rejected; correction can be approved. Generation before all reviews blocked. Membership amendment requires new reviews and supersedes old workbook. Completed batch rejects cancellation, removal and mode edits. |
| HB Action | Commission before installation, missing not-ready reason, future installation, stale edit, commission before install date, future commissioning and early commissioning without acknowledgement rejected. Delay/not-ready retained. Commissioned installation read-only; repeat commissioning denied; wrong-role access unavailable. |
| FarmUp / SysUp | Invalid rows held; warnings need explicit acknowledgement; exclusions remain excluded. Changed-source reconciliation, stale revision, exact replay and interrupted progress exercised. An initial source missing all mandatory alternate phones was correctly blocked and retained as fixture evidence. |
| Reports / shell | Pipeline, outcomes and finance opened; rejected filter returned three records. Credit Analyst's IT report returned 403. Navigation, settings, performance, media, reload and offline banner exercised. Reconnection restored queue refresh. Captures include 320/390/1280 widths and dark History. |

## Publication failure and recovery

Django commits and Google publication remain distinct. Simulated Sheet failure
left cases/files intact. Restoring the local transport and using existing bounded
publication services completed queued projections. One current operation
exhausted four outage attempts; actual IT Settings > App status > Retry sync
queued a successful successor. The old dead-letter entry remains as audit history.
Four retained order uploads were retried without allocating new numbers or
changing workbook versions.

Final read-only reconciliation in `final-state.json` records:

- All 1,101 newly created worklist/office cases have Sheet projections, with no
  missing case and no duplicate projected case ID in either local case register.
- All five import sources archived; no pending archive operation.
- 2,584 successful case-publication operations. One historical failed operation
  remains; its current case was successfully republished through IT recovery.
- Completed 61-case payment; mode totals sum to KES 2,891,500.
- Office lead installed and commissioned. Every retained order checksum matches
  its bytes; all 83 local Drive blobs match their content hash.
- No remaining App status storage/publication recovery action. Email delivery is
  intentionally unconfigured in the isolated environment.

These counts include publication revisions, not distinct customers. Early
pre-staged legacy fixtures were not all published; the projection reconciliation
covers newly created cases. Current request-assisted publication and scheduler
behavior follow checked-in code; this is not a scheduler-only production claim.

## Remaining limits and release implications

- Bulk evidence reaches 252 cases per order and 61 per mixed payment. Large-order
  generation still made 9,787 SQL calls in the observed 250-case run. Production
  latency, simultaneous bulk generation, memory limits and larger cohorts remain
  unverified. Local success does not establish unlimited scale.
- A permitted 20-file invoice delivery can exceed its 35-second work budget
  because each PDF starts an isolated parser. Partial receipts and five-file
  retries recovered all 60 cohort invoices plus the office invoice. This is not
  a promise of 20/20 completion in one production request. File-count, byte and
  one-invoice-per-file policies were not relaxed.
- FarmUp interruption was before server receipt of its second request. An
  accepted request whose response is lost was not separately reproduced.
  Sequential duplicate-iMAB rejection was verified; simultaneous first claims
  on two unlinked legacy cases were not established.
- Corrected geometry applies to new generation or an explicit unsigned
  successor. Signed/historical workbooks remain immutable; no production history
  rewrite occurred. Excel retains its 409.5-point row-height ceiling; arbitrarily
  long cell content is not certified.
- Synthetic signed scans prove version binding, retained bytes, preview and
  finality. They do not prove real signatures/stamps, scan completeness or staff
  attestation quality.
- Physical Telegram, camera/GPS hardware, assistive technology, real Google
  quotas/permissions, real email/SMS and deployed-worker configuration were not
  exercised. The specialized invoice-name/household-letter chain and scheduled
  email delivery were not replayed end to end in this run.
- The previously deferred policy decision about HB visibility of internal JBL
  deposit information remains unchanged. No new workflow grant was assumed.

Changes reuse the existing controls and shell. The
[source-bound UI record](ui-standard/reviews/2026-10-29-portal-workflow-review.md)
records intentional behavior/status changes. No candidate-token adoption,
approved visual baseline update, Phase 6 migration or deployment follows from
these screenshots.
