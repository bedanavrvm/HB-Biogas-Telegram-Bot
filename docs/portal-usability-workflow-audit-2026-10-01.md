# Portal usability and workflow audit

Date: 1 October 2026. Scope: the current local checkout, not the deployed service.

## Verdict

**Do not treat the Portal as fully verified yet.** The existing focused browser suite passes, but exploratory checks found gaps between individually working components:

- Background publication is incorrectly treated as a staff save and blocks navigation.
- Unrelated case revisions can invalidate payment review.
- Commissioning can be dated before installation; installation corrections can also reverse that chronology.
- Unsaved payment comments and installation-delay notes can be lost without warning.
- Older payment batches disappear from the list after its silent 100-batch limit.

These are workflow/recovery issues, not requests for a new architecture. Repair the existing boundaries and shared components. No product behavior was changed during this audit.

## How the audit was performed

- Read the current workflow services, capability boundaries, queue queries, navigation controllers, and publication behavior.
- Ran the existing focused Playwright tests, then separately rendered **17 full Django screen routes at 320, 390, and 1280px**: 51 screen/viewport combinations.
- Used long synthetic names, six-digit IDs, 50 payment cases, 50 payment batches, unmatched invoices, and installation queues.
- Opened payment cards and inspected their rendered screenshots, not just their DOM assertions.
- Simulated an offline refresh, a deliberately stalled publication request, and leaving two forms with unsaved text.
- Probed backend rules with impossible-but-accepted date combinations and a revision-only payment change.
- Ran two backend selections covering approvals, identity, imports, publication, reset, payments, HB actions, Home, navigation, authentication, signing, templates, and pipeline services.

Safety boundaries:

- Local server: `127.0.0.1:8007`, explicitly configured with an isolated temporary SQLite database and synthetic credentials.
- Exploratory browser APIs were intercepted; external requests were not forwarded. Staff mutations were blocked except synthetic publication responses.
- No production database, customer data, Google writes, Telegram messages, or Drive deletion was used.
- Full screen HTML and static assets were real. API data and queue fragments were synthetic; these screenshots do **not** prove backend scope enforcement or every live queue/card variation.
- An initial fragment-mock formatting issue was corrected and the screen matrix rerun. It was not counted as an application defect.

## Prioritized findings

| ID | Priority | Finding | Evidence level | Repair size |
|---|---|---|---|---|
| AUD-01 | High | Background sync blocks navigation; its request has no client timeout | Full-page browser reproduction + source | Small |
| AUD-02 | High | Unrelated case revision invalidates payment approval | Backend digest reproduction + serializer/HB source trace | Medium |
| AUD-03 | High | Installation/commissioning chronology can be impossible | Three-date backend validation reproduction | Small |
| AUD-04 | Medium | Payment comments and HB delay notes lack dirty-leave protection | Full-page browser reproduction | Small |
| AUD-05 | High | Payment list silently omits batches older than the newest 100 | API/controller source + 50-batch rendered stress check | Medium |
| AUD-06 | Medium | Expanded payment card still truncates the customer's full name | Actual 320px screenshot + card markup | Small |
| AUD-07 | Medium | Regression failures weaken confidence in important handoffs | Two backend test selections | Medium |
| AUD-08 | Low | Labels and workflow documentation disagree with current implementation | Current template/service/document comparison | Small |

High means an operational stall, incorrect approval dependency, inconsistent chronology, or hidden unfinished work. Medium means avoidable loss, ambiguity, or a material verification gap. These are not claims that every finding has already occurred in production.

### AUD-01 — Background work locks the foreground

Reproduction:

1. Open Home with a valid synthetic session.
2. Let the automatic `/api/portal/publication/pump/` POST start; delay its response.
3. Attempt to navigate to JBL visits.
4. `MiniAppUtils.canNavigatePage(...)` returns `false`; the app asks the user to wait for the current action.

Why:

- `core/static/miniapp/portal_api.js`, `runPublicationPump`, sends this request with `timeoutMs: 0`.
- `core/static/miniapp/utils.js`, `installWriteProtection`, wraps essentially every non-GET request in a `network-write` guard, including the pump.
- `canNavigatePage` rejects navigation while that guard exists.

Consequences:

- A user doing nothing but viewing a queue can be prevented from changing screens by unrelated publication.
- A hung request has no application-level client deadline to release the guard.
- Canonical saves may be asynchronous relative to Google, but foreground navigation is still coupled to Google work.

Repair:

- Classify the publication pump as background coordination, not an unsaved staff mutation.
- Permit navigation while it runs; retain guards for actual saves/uploads.
- Give the pump a bounded request timeout and preserve durable retry/lease semantics.
- Test a stalled pump alongside an ordinary save: navigation should be allowed for the former and protected for the latter.

Evidence: `test-results/portal-journey-audit/background-pump-blocks-navigation.png`, `behavior.json`.

### AUD-02 — Installation progress can reopen payment review

Reproduction at the payment-fact boundary:

1. Compute `case_payment_digest` for a farmer with revision 1.
2. Change only `workflow_revision` to 2; leave every payment fact unchanged.
3. The digest changes.

Cross-workflow trace:

- `payments/services.py`, `case_payment_digest`, includes the global `workflow_revision`.
- `hb_operations/services.py`, `_sync_farmer`, increments that revision during HB updates.
- `payments/services.py`, `serialize_batch`, converts a reviewed case to Pending when its digest changes; qualifying batches are marked for re-review.

This couples installation/commissioning activity to a payment decision even when amount, invoice, order, customer, mode, and repayment facts did not change. The re-review destination exists, which prevents one form of soft lock, but the dependency is unnecessarily broad.

Repair:

- Bind payment review to the specific facts actually reviewed, not an unrelated global revision counter.
- Keep optimistic revision checks for concurrent edits.
- Define the material-change list explicitly: amount, mode, relevant identity/invoice/order, commercial terms, and eligibility.
- Verify real financial changes still reopen review and supersede the workbook.
- Verify HB notes, installation, commissioning, and permitted non-material history corrections do not.

Evidence: `scripts/portal_audit_contract_probes.py`; service/serializer trace. A complete accepted signed-order → HB transition → payment API reproduction was not executed; the digest and downstream comparison were verified separately.

### AUD-03 — Early commissioning acknowledgement bypasses chronology

Accepted combinations:

- Installed ten days ago; commissioned eleven days ago; early acknowledgement checked.
- Already commissioned two days ago; installation corrected to yesterday.

Both pass the relevant backend validators. Future dates are rejected, but the relationship between the two historical dates is not enforced.

Repair:

- Enforce `commissioning_date >= installation_date` server-side.
- Preserve the intended early-commissioning acknowledgement only for dates between installation and its normal 21-day readiness date.
- Reject installation corrections that put installation after recorded commissioning, or provide an explicit paired audited correction; never silently erase commissioning evidence.
- Test installation day, day 20, day 21, future dates, missing installation, and changes across the Nairobi date boundary.

Evidence: `_validate_commissioning` and `_validate_installation` in `hb_operations/services.py`; two characterization probes.

### AUD-04 — Unsaved staff reasoning can disappear

Full-page reproductions:

- Open a payment review case, change its approval comment, then ask the shared navigation guard to leave: allowed with no discard prompt.
- Open an HB installation record, select Report delay, type a pending comment, then leave: also allowed with no discard prompt.

These are full-page forms, not the modal forms already watched by the dialog controller. Neither page registers the shared dirty-form protection for these edits.

Repair:

- Register both surfaces with the existing shared form protection.
- Establish the clean baseline after loading; reset it only after a confirmed successful save.
- Retain text after validation/network failure.
- Confirm visible Back, sidebar links, Telegram Back, and browser reload follow the same policy.
- Do not introduce a new draft system merely to fix navigation protection.

Evidence: `unsaved-payment-review.png`, `unsaved-hb-delay.png`, `behavior.json`.

### AUD-05 — Payment batch list has a silent cutoff

`portal_payment_batches` in `core/api/portal_views.py` orders batches newest-first and slices `[:100]`. Its response has no next-page mechanism or true total. `portal_payments.js` renders the returned list and applies the page's status grouping locally.

Consequences:

- At 101+ batches, an older unfinished batch may be absent even when the user selects Open.
- An empty category can mean “none in the returned newest 100,” not “none in your authorized scope.”
- Fifty synthetic batches already produce an unnecessarily long scrolling list without batch search or pagination.

Repair:

- Apply status and permission scope before paginating.
- Return scoped totals and page metadata; use the existing Portal pagination pattern.
- Add compact batch search by payment number, with customer search only if explicitly supported.
- Preserve the chosen status/search/page when returning from a batch.
- Test 101+ mixed-status batches, including an old unfinished one outside the first page.

Evidence: `payments-320.png`; endpoint and list-controller implementation. The 101-batch omission was source-confirmed, not populated against a live database.

### AUD-06 — Expanding a payment case does not reveal its full name

On the 320px rendered screen the expanded header still reads “Synthetic Customer 1 With …”. The expanded detail area shows ID, phone, branch, officer, order/invoice and repayment context, but not the untruncated customer name.

Collapsed ellipsis is useful. Keeping it as the only visible name after expansion is not: staff need to distinguish similar people before financial review.

Repair:

- Allow the name to wrap in the expanded state, or show it once in expanded identity details.
- Keep amount/mode aligned independently; do not shrink the name to tiny text.
- Test long names and two customers sharing the same first words.

Evidence: `payment-expanded-320.png`. Missing case/order/repayment values in that screenshot were deliberately incomplete mock fields and are **not** reported as application defects.

### AUD-07 — Test failures need triage, not a blanket “all clear”

Existing test results:

| Selection | Passed | Failed | Errors |
|---|---:|---:|---:|
| Focused Playwright Portal/FarmUp/payment/invoice/HB selection | 82 | 0 | 0 |
| Approval controls, invoice identity, SysUp, publication, full reset, payments, HB | 146 | 2 | 1 |
| Dashboard, navigation, Portal auth, pipeline services, signing, templates, imports | 143 | 11 | 0 |
| Read-only defect characterization probes | 3 | 0 | 0 |

The characterization probes pass because they reproduce current defects; they are not desired-behavior acceptance tests.

Identified stale fixtures/expectations:

- SysUp tests still expect six-digit IDs and unknown products to require review, although those blockers were deliberately removed.
- A payment preview mock omits `farmer_id` from a ready row; the real readiness service supplies it. Its `KeyError` is not proof of a production preview failure.
- Several visit tests supply `b'x' * 5000` as a PDF. Document validation rejects it before the revision/evidence boundary those tests intend to exercise.
- A saved-view drift test removes Head of Rural but leaves an IT grant in place, so continued access is expected under the current role policy.
- Two template/CSS tests assert exact old source strings instead of rendered behavior.
- Pending-credit wording/default expectations and final-review queue fixture readiness also disagree with current results; these need contract review rather than automatically weakening implementation.

Required follow-up:

- Repair synthetic fixtures to exercise the intended path; preserve strict evidence validation.
- Replace brittle markup-string checks with behavior where practical.
- Reconcile queue/default expectations against the approved contract, then rerun.
- Add acceptance regressions for AUD-01 through AUD-06.
- Run PostgreSQL validation before claiming concurrency/locking safety. SQLite does not validate nullable-join `FOR UPDATE`, database comments, PostgreSQL triggers, or actual concurrent lock behavior.

Logs: `test-results/portal-journey-audit/backend-access-intake.txt`, `contract-probes.txt`. The first backend selection's output was reviewed in the terminal and is not stored as a complete log in this evidence directory.

### AUD-08 — Label and documentation drift

Examples:

- Home shortcuts still use labels such as My submitted visits, FarmUp review, SysUp review, and Payment approvals while navigation uses newer labels such as My Visits, Monthly List, Customer Updates, and Payment Review.
- Document Archive navigation leads to a Document History heading.
- `KNOWN_GAPS.md` describes Portal Imports as staging-only, but `portal_import_commit` now exposes a scoped SysUp commit workflow.
- The AGENTS payment glossary says the number is allocated at first submission; the current model/service allocate it when the reviewed workbook is generated.

Repair:

- Reuse one short display label per destination.
- Update obsolete documentation only after confirming the intended contract.
- Confirm numbering policy explicitly; do not move allocation merely to match old prose.

## Workflow and handoff assessment

| Journey | Evidence obtained | Remaining risk/check |
|---|---|---|
| Role-tailored Home and queue access | Focused role, scope, navigation, and browser tests | Full live mixed-role sessions and real launcher access changes |
| FarmUp → canonical intake → Sheet publication | Import/publication/reset tests; rendered upload screen | Large multi-file reconciliation with real synthetic committed data; rate-limit/restart recovery |
| Officer-created lead → FarmUp reconciliation | Existing implementation reviewed; related intake tests | Complete end-to-end case merge with canonical county preservation |
| JBL visit → credit → final review | API/service tests; queue rendering and recovery/navigation tests | Repair invalid-PDF fixtures; recheck evidence/revision handoffs using valid generated documents |
| SysUp after approval | Approval controls and SysUp tests | Recheck non-material updates against payment digest, not only credit/final gates |
| Order preparation → official workbook → signed scan | Approval/signoff/template tests and preview/navigation browser tests | PostgreSQL number allocation races; replacement/superseded scan across multiple sessions |
| Invoice upload → match → receipt → payment membership | Identity/payment tests, invoice browser tests | Large mixed-quality bundles and interrupted Drive archival on real synthetic backend state |
| Payment review → workbook → signed completion | Payment service/browser tests | AUD-02, AUD-04, AUD-05; full generated workbook/scan handoff |
| Signed order → installation → commissioning | HB service/browser tests | AUD-03, AUD-04; cross-flow payment interaction |
| Case History corrections → queues/timeline | Existing correction services/tests inspected; browser inspection tests | Explicitly distinguish material financial edits from presentation/contact corrections |
| Master/Eco-conserve routing and FIFO retries | Publication selection and current service review | Actual synthetic Google quota/timeout/row placement verification, no production writes |
| Configuration-scoped reset → fresh Portal | Existing full-reset tests in passing backend selection | PostgreSQL protected relations/triggers and external-link cleanup on a disposable database |

No evidence here proves every possible state permutation. The table separates inspected/test-covered behavior from unexecuted integrated scenarios.

## Integrated scenario matrix for the next verification pass

Use complete synthetic cases and actual backend endpoints with Google/Telegram gateways mocked. These are the highest-value combinations, not a duplicate of every screen test.

| Scenario | Expected invariant |
|---|---|
| Installation finishes while payment is awaiting review/scan | Installation progresses independently; unchanged payment facts remain approved |
| SysUp follows credit/final approval | Additional system data does not retract unrelated decisions; material payment changes are clearly identified |
| Same ID, reordered names across FarmUp/SysUp/invoice | Matching remains ID-led; spelling/order variation alone does not create a payment hold |
| Different invoice ID, similar name | Parsing remains possible; identity discrepancy is explicit and payment follows the governed correction route |
| Same invoice uploaded twice, then ignore/restore/delete | No duplicate payable membership; ignored/deleted state and Drive references stay consistent |
| Old order scan uploaded after a new workbook | Superseded artifact cannot release HB work or finalize the wrong version |
| Two operators finalize orders/payments simultaneously | Unique numbers; deterministic conflict/replay; no duplicated official artifact |
| Staff edits a note while background sync stalls | Navigation protection reflects the staff edit, not the sync request |
| Save succeeds but response is lost | Same request key replays one result; UI does not invite a duplicate new submission |
| First Sheet update fails, later Master/Eco work queues | Visible reason and permitted recovery; no false “synced” status, duplicate row, or silent FIFO bypass |
| Case changes routing after officer adds county | Canonical county preserved; one intended row per case; no stale duplicate in the old register |
| Access changes while a page/preview is open | Subsequent server reads/writes reauthorize; unauthorized data/action does not survive through cached scope |
| Empty/filtered queue versus API failure | Caught-up state never disguises a failed request; previous successful data is retained where appropriate |
| Browser closes during upload/save | Durable outcome identifiable on reopen; attachment recovery limitations stated honestly |
| Installation date corrected after commissioning | Chronology preserved or explicit audited paired correction required |
| 101+ batches and 50+ cases with long names | Unfinished work remains discoverable; identity readable; selection and paging survive Back |
| Reset one Portal configuration | Other workflows/groups/access/catalogues preserved; DB links removed; external Drive files retained |

## Usability scorecard

- **Hierarchy:** Home's first useful action appears near the top; no four-card KPI wall in the sampled view. Keep this pattern.
- **Density/alignment:** Collapsed payment cards and inline Back are improved. Expanded long-name identity and batch scalability still need work.
- **Responsive layout:** No whole-document horizontal overflow or page JavaScript errors in the 51 intercepted screen samples. Horizontal invoice tables and tab rails were intentional and not counted as overflow defects.
- **Feedback/recovery:** Offline refresh retains visible Home content. Background sync and unsaved full-page comments are the main recovery failures.
- **Consistency:** Reuse the shared dirty-form, pagination, date/filter, preview, and toast primitives; do not build another interaction vocabulary.
- **Accessibility:** Geometry sampling found no visible buttons below 24px in the captured pages. This is not a complete accessibility audit: screen-reader, focus order, contrast, and physical touch behavior still need dedicated checks.
- **Theme/device:** Existing selected browser tests include additional viewport/theme cases. The new full-screen matrix was light-theme desktop Chromium; it does not substitute for Android/iOS Telegram validation.

## Recommended repair order

1. Separate background publication from user-save navigation protection.
2. Enforce installation/commissioning chronology, including correction mode.
3. Narrow payment review invalidation to material facts; verify installation/SysUp/history interactions.
4. Protect full-page unsaved payment/HB edits.
5. Paginate payment batches server-side and reveal full identity on expanded cards.
6. Repair stale test fixtures, reconcile labels/docs, then rerun PostgreSQL and integrated synthetic journeys.

Keep each repair bounded with its own regression tests. Avoid mixing these fixes with new screens, scoring, catalogues, or workflow states.

## Reproduction assets

- `scripts/portal_journey_audit.js`: local-only full-screen screenshot matrix with intercepted synthetic APIs.
- `scripts/portal_behavior_audit.js`: stalled-pump and unsaved-comment reproductions.
- `scripts/portal_audit_contract_probes.py`: read-only backend defect characterization.
- `test-results/portal-journey-audit/`: local screenshots, JSON observations, and captured test logs; ignored by Git.

For reuse, start a local Django server on port 8007 with a disposable SQLite database, synthetic credentials, and real external integrations disabled. Then run the two Node scripts. Never point these harnesses at production or real customer data. The scripts are audit tools, not additions to the acceptance suite; their mocks are deliberately limited.

## Repair implementation and verification — 1 October 2026

The original findings above are retained as the audit record. The following
repairs are now implemented locally; no production data was modified.

- **Background sync:** exact same-origin publication-pump requests no longer
  hold the foreground navigation guard. A 20-second timeout releases the
  browser lease and allows the existing durable retry mechanism to resume.
  No cron, hosting service or new worker was introduced.
- **Payment review:** versioned payment-fact bindings exclude unrelated global
  workflow revisions. Financial, identity, invoice, mode, product and final
  approval changes still require review and prevent stale workbook acceptance.
  New review events retain the binding facts so warnings can identify the
  changed field group. Historical digests are not migrated or auto-restored.
- **HB chronology:** commissioning cannot predate installation, even with an
  early acknowledgement. Installation becomes permanently read-only in HB
  after commissioning; commissioning corrections retain chronology validation.
- **Unsaved work:** shared protection covers payment comments and HB forms and
  notes. Saving one payment comment retains other unsaved comments. Network
  errors retain HB input and release the Save button. Preview detours remain
  read-only and retain the existing nested Back behavior.
- **Payment lists:** search and current capability scope apply before counts and
  10-item pages. Effective re-review states remain in Payment Review. Back links
  retain status, page and payment-number search; late responses are discarded.
- **Layout:** expanded customer names wrap at readable text size. Existing
  compact cards, shared search, pagination and notification patterns are reused.
- **Queue correctness:** final review explicitly includes cases without a newer
  approval-ledger row while still excluding invalidated/expired credit approvals.
- **Test/document drift:** synthetic PDFs/images now meet current evidence
  requirements, mock uploaders model case linking, six-digit IDs and operational
  product rules match the current contracts, and cached group configuration is
  isolated between tests. Labels and AGENTS/CHANGELOG/KNOWN_GAPS were reconciled.

### Evidence

- **318 backend tests passed** across payments, HB operations, case corrections,
  dashboard/navigation/auth, pipeline, signed documents, template storage,
  FarmUp/SysUp, approval controls, invoice identity, publication and reset.
  Database: isolated SQLite, not PostgreSQL.
- **84 selected Playwright tests passed**, including new foreground/background
  write-protection and independent-comment tests, expanded long-name geometry,
  existing nested previews, mobile widths and light/dark layout checks.
- **Nine Node test groups passed; 82 first-party JavaScript files passed syntax.**
- **51 local rendered-page samples:** 17 routes at 320, 390 and 1280px, with
  synthetic intercepted APIs, had no document overflow or page exceptions.
  Viewport screenshots of expanded payment cards were visually inspected.
  Queue-fragment fixtures remain simplified, so this matrix does not establish
  live queue API-to-template correctness on every screen.
- **Targeted rendered interactions passed:** unsaved payment/HB edits prompt
  before leaving; a second comment survives another case's approval; stalled
  sync permits navigation and releases its lease after timeout.
- Logs/screenshots: `test-results/portal-journey-audit/repair-*.txt`,
  `behavior.json`, `observations.json` and payment viewport screenshots.

### Remaining verification boundaries

- Local PostgreSQL is reachable but requires credentials not available to this
  session (`no password supplied`). No authentication changes were attempted.
  PostgreSQL-specific locking/concurrency parity remains a release prerequisite.
- No live Telegram/Google operations, staging/production testing, physical
  Android/iOS Telegram testing or complete screen-reader audit was performed.
- This was an affected-workflow test selection, not the entire repository suite.
- Historical review restoration and data reconciliation are deliberately out of
  scope for the agreed hard cutover. Existing historical records remain retained.
