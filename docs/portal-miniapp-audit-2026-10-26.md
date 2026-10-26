# Portal Mini App behavior and workflow audit

Date: 26 October 2026. Base checkout: `6bd755bf`. Updated after the requested remediation. Application fixes, regression tests and isolated diagnostic scripts are present in the working tree. No deployment, migration, operational-data change or external write was performed.

## Assessment

The Portal coordinates customer intake, visits, lending decisions, official orders, invoices, payments, and HomeBiogas fulfilment. Django owns the records and history; Sheets and Drive are publication destinations. The assumed operating model is several staff accounts working across stages and a separate publication worker.

**The identified defects are fixed and the affected backend gate is green: 984 passed, six PostgreSQL-only checks skipped.** Sheet aliases publish correctly, invoice phone discrepancies survive parsing, and Sheet timestamps use Nairobi time. Remediation also restored the Case History route and stopped TAT creation field errors from echoing submitted customer values. PostgreSQL concurrency and real provider behavior remain unverified.

The connected journey reaches payment completion and commissioning for both HB and Eco-conserve. Final publication succeeds with the original `Order No` and `Payment No` headings, without repairing headers or bypassing business rules. All 32 integration operations finish successfully.

## Verification results

| Check | Result |
| --- | --- |
| Consolidated backend run | 990 tests: 984 passed, no failures/errors, six PostgreSQL-only skips |
| Portal/FarmUp Chromium checks | 269 passed; no failures, skips, or retries needed |
| Connected synthetic journey | Passed with original alias headers and no workaround |
| Invoice phone probes | All five pass; regression tests additionally cover seven mismatch formats |
| Django system check | No issues |
| Migration drift | No changes detected |
| Correctness lint / UI source ratchet | Passed; no appearance changes or baseline updates |
| Mini App write-route inventory | Passed, 202 routes |
| Diagnostic Python compilation | Passed |
| Whitespace check | Passed |

The initial audit ran 978 tests with 38 failed assertion entries, four errors and six skips. Failure entries included subtests. The consolidated remediation run includes the former supplemental labels, new regressions and targeted TAT/message checks. Five retired-endpoint tests were consolidated into an explicit 426/no-write check; current finalize tests verify retained bytes, append history, replay, stale revisions and template failure. Counts are therefore not directly interchangeable.

Runtime: Python 3.14.6, Django 5.1.6, SQLite. The baseline was built using the checked-in migrations and retained 962 role-capability policy rows and two physical-signoff policies. Each connected rerun copies that customer-free baseline into a new local SQLite file. The test suite also restores a fresh baseline because transaction tests can flush migration-seeded policy data from a retained test database.

## Isolation and evidence

- The harness replaces python-decouple's repository with an empty repository, so the checkout's `.env` is not loaded.
- Database files, templates, Sheets, and Drive substitutes are under `test-results/portal-local-audit-2026-10-26/`.
- Python socket connections are blocked in the audit process. PDF processing uses the existing bounded local parser subprocess. Browser fixtures intercept or abort external requests.
- The real Google gateway methods are replaced with local byte storage and the repository's existing fake worksheet adapter. The production publishers, parsers, validators, workflow services, API handlers, and authorization rules run normally.
- Six independent ordinary staff accounts use locally signed Telegram HMAC payloads. No Superuser is used to carry the happy path past a role restriction.
- Grant-administration governance is disabled for synthetic fixture provisioning in this harness; request-time workflow capability and scope checks remain active.
- Telegram notification delivery is deliberately disabled. In-memory email is used for tests; no staff notification or external email is sent.
- Generated scans are explicitly synthetic staff attestations. This exercises source-version binding and retention, not physical handwriting/stamp authenticity.

The local Drive stores content-addressed blobs and a filename/type manifest. It can verify retained bytes and upload calls, but it does not reproduce Google's duplicate-file semantics, permissions, quotas, or latency. The Sheet adapter executes the real publisher's reads and cell writes in memory, then exports CSV files. It does not calculate spreadsheet formulas or model concurrent Google editors.

Evidence retained locally:

| Artifact | Contents |
| --- | --- |
| [journey.json](../test-results/portal-local-audit-2026-10-26/journey.json) | Connected steps, HTTP outcomes, successful alias publication and final database path |
| [suite-summary.json](../test-results/portal-local-audit-2026-10-26/suite-summary.json) | Consolidated green labels and exact skipped PostgreSQL checks |
| [audit-before-suite-summary.json](../test-results/portal-local-audit-2026-10-26/audit-before-suite-summary.json), [failure-index.json](../test-results/portal-local-audit-2026-10-26/failure-index.json) | Original audit failures, retained for comparison |
| [original journey log](../test-results/portal-local-audit-journey.txt) | Initial alias failure and local-header recovery evidence |
| [browser summary](../test-results/portal-local-audit-2026-10-26/browser-summary.json), [full browser output](../test-results/portal-fixes-browser.json) | Portal/FarmUp Playwright results |
| [Master Data.csv](../test-results/portal-local-audit-2026-10-26/sheets/Master%20Data.csv) | Completed HB projection, header row 1, customer row 2 |
| [Eco-conserve.csv](../test-results/portal-local-audit-2026-10-26/sheets/Eco-conserve.csv) | Completed Eco-conserve projection, header row 1, customer row 2 |
| [drive manifest](../test-results/portal-local-audit-2026-10-26/drive/manifest.json) | Original imports, visit evidence, invoices, generated payment workbook and accepted scans |
| [HB-1.xlsx](../test-results/portal-local-audit-2026-10-26/HB-1.xlsx), [ECO-1.xlsx](../test-results/portal-local-audit-2026-10-26/ECO-1.xlsx) | Real generated partner-specific order workbooks from synthetic blank templates |
| [payment.xlsx](../test-results/portal-local-audit-2026-10-26/payment.xlsx) | Reviewed mixed-mode workbook, Eco-conserve first |
| [invoice-phone-probes.json](../test-results/portal-local-audit-2026-10-26/invoice-phone-probes.json) | Passing phone extraction and mismatch comparisons |

These artifacts are ignored by Git. The diagnostic source and this report are the repository deliverables. Retain the local evidence directory when sharing the report; it is not recreated merely by checking out this Markdown file.

## The connected business process

SysUp is enrichment of an existing Portal case, not a way to create a new lead. Starting with an empty database therefore stages SysUp first, creates leads through FarmUp, and then commits the matched SysUp rows.

| Stage | Actor and action exercised | Observed outcome |
| --- | --- | --- |
| SysUp source | IT uploads a synthetic system export | Two source rows retained; no customer cases created |
| FarmUp intake | Operations uploads, validates, and commits a monthly CSV | Two cases created; repeating the exact commit key creates no additional cases |
| SysUp review | Operations commits exact matched rows and current case revisions | System customer numbers, names, product labels and zero LGF values saved; source archive retained locally |
| Initial publication | Real durable operations run against local worksheets | One HB row in Master Data and one Eco-conserve row in its tab |
| JBL visit | JBL Officer submits distinct ID front/back, LAF pages and visit photo | Three resulting evidence categories retained; case enters credit |
| Credit | Credit Analyst approves with IMAB confirmation and system number | Case enters Head of Rural review; an old revision receives 409 |
| Final decision | Head of Rural approves repayment day and tenor | Case becomes order-ready; Operations attempting this decision receives 403 |
| Official orders | Operations previews and finalizes partner-specific workbooks | Independent HB-1 and ECO-1 allocated; workbook membership verified |
| Order signature | Head of Rural uploads an attested scan of each current order | Exact version accepted; HB action created; unsigned orders were ineligible for invoices |
| Invoice delivery | Operations uploads real synthetic PDF files through the invoice API | Parser subprocess extracts and automatically matches both invoices; governed receipts created |
| Payment preparation | Operations creates a payment from the first receipt and adds the other eligible case | One LOAN-JAWABU case and one CASH case in the same batch |
| Payment review | Head of Rural reviews each case and generates the workbook | Operations review attempts receive 403; each case has its own approval; Eco-conserve appears first |
| Payment signature | Head of Rural attests the exact current payment workbook | Payment 1 completes; both memberships retained |
| Installation | HB staff records installation | Attempting commissioning before installation receives 400 |
| Commissioning | HB staff records commissioning with early-completion acknowledgement | Earlier-than-installation dates and missing early acknowledgement receive 400; both cases finish as Commissioned |
| Final publication | Latest durable revisions publish to local Sheets | Original alias headings work; both rows show Commissioned, Payment 1 and Nairobi timestamps without duplicates |

Each invoice has gross KES 54,000, discount KES 4,500, invoice payment KES 5,000, and balance due KES 44,500. The payment batch contains two cases totalling KES 89,000. These are synthetic document amounts; a completed payment here means the governed signed-workbook workflow completed, not that a bank transfer was executed.

Final evidence: two cases, two signed official orders, two matched invoices, two invoice receipts, one completed mixed-mode payment, two commissioned HB actions, 14 local Drive upload calls representing 11 unique blobs, and 32 succeeded integration operations. Each register contains one customer row, a visible JBL reference, a hidden exact Master Record ID, its order/invoice, Payment 1, and the expected balance.

The queue is drained after intake/SysUp and after fulfilment. Earlier intermediate publication reservations are retained and superseded by later revisions, as designed. This proves eventual final projection; it is not a latency measurement for a production scheduler.

## Resolved findings

### 1. Supported Sheet aliases could prevent the entire case update — fixed

**What this is:** The publication contract explicitly lists `Order No` and `Payment No` as accepted headings. Header identification accepts punctuation variants, while the final cell writer performs a stricter lookup.

**Problem:** With `Order No` present, `first_existing_header()` returns `Order No.`. `update_master_sheet_row()` then asks `NamedColumns` for that literal heading and raises `SheetColumnError`. The connected run completed canonically but the final publication became retryable. This is a publisher inconsistency, not a fake-Sheet transport failure.

**Resolution:** The writer resolves named cells with the same punctuation normalization used by publication. Duplicate/ambiguous-column rejection and schema-drift checks remain. Regression tests update order/payment aliases while retaining a staff formula, and reject missing or ambiguous columns before writing.

**If skipped:** A perfectly recognizable register can stop receiving all changes for the affected case, and its destination's FIFO queue can be delayed behind retries. Canonical payment and fulfilment remain saved, leaving staff with an outdated register.

Sources: [alias contract](../core/services/sheet_publication.py#L96), [first_existing_header](../core/services/jawabu_master.py#L1197), [cell writer](../core/services/jawabu_master.py#L1340), [publisher](../core/services/jawabu_pipeline.py#L2706).

Before: the original journey log identifies missing `Order No.`. After: `final_sheet_publication` in the current journey publishes both cases with unchanged alias headings.

### 2. A printed phone mismatch could disappear during invoice parsing — fixed

**What this is:** Automatic matching compares invoice identity with an eligible case. Phone comparison is applied only when the parser extracted a phone.

**Problem:** `PHONE_RE` accepts `+254...` and `07...`, but misses `254...`. For an otherwise identical synthetic name and National ID, a different printed phone with `+254` correctly prevents matching; the same different phone without `+` becomes an empty parsed value and the exact-match helper returns true. A visible contradiction can therefore bypass manual matching review.

**Resolution:** Extract country-code, local, international-access and visually separated mobile forms, then reuse the existing Kenyan phone normalizer before comparison. Parser-to-matcher regressions prove a printed mismatch cannot disappear in these formats; matching phones still pass. Missing phone evidence retains its existing treatment.

**If skipped:** Invoices can be automatically linked despite a supplied phone discrepancy. Name and National ID checks still apply; this experiment does not establish an authorization bypass or a merge of unrelated National IDs.

Sources: [phone extraction](../core/services/invoice_parser.py#L246), [parse_invoice_text](../core/services/invoice_parser.py#L562), [automatic identity comparison](../core/services/invoice_parser.py#L1167).

Evidence: every variant in the current `invoice-phone-probes.json` has `passes_expected_behavior: true`; the bare-country-code mismatch is extracted and rejected. Regression tests also cover international access prefixes, visual separators and a redundant national trunk prefix using the existing Kenyan phone normalizer.

### 3. Sheet update timestamps were three hours behind Nairobi — fixed

**What this is:** The publisher writes an unzoned date/time into `Last Updated At` in an application configured for Africa/Nairobi.

**Problem:** It formats `timezone.now()` directly. In the connected run, the Sheet displayed `26-Oct-2026 05:37` while Nairobi time was `26-Oct-2026 08:37`. These values do not tell staff they are UTC. Similar direct formatting exists in the internal-order and FarmUp writers.

**Resolution:** Convert staff-facing timestamps to local time in Master Data, internal-order, FarmUp conflict/update and import-log writers. A fixed-UTC regression verifies the Nairobi date boundary; the connected journey asserts the displayed time is within two minutes of the real clock.

**If skipped:** Staff can misread publication freshness, and an update near local midnight can appear on the wrong date. This finding concerns the projected display value; it does not show corrupt timezone-aware database timestamps.

Sources: [Master publisher](../core/services/jawabu_pipeline.py#L2593), [internal-order publisher](../core/services/jawabu_pipeline.py#L3017), [FarmUp timestamps](../core/services/jawabu_master.py#L373). Evidence: `sheet_timestamp_zone_probe` in `journey.json`.

### 4. Backend tests did not provide a green Portal acceptance gate — reconciled

**What this is:** The backend suite mixes current workflow contracts with older expectations. A failing suite cannot reliably distinguish a new regression from already stale coverage.

**Problem:** Forty failure/error entries are in Portal-related modules; another two are TAT checks in the shared reliability module. Several current paths pass, but the full affected scope remains red.

**Resolution:** Invoice fixtures retain an exact signed order; visit fixtures declare deposits and current refresh behavior; data-quality tests use actually invalid identifiers. Order tests enforce explicit workspace append, exact membership, preview/finalize, local retention and no writes from retired endpoints. Shell, catalogue-report and date assertions follow the current interfaces. Authorization and financial-finality rules were preserved.

**If skipped:** A change can ship with meaningful regressions hidden among known failures. The successful synthetic journey proves its exercised path, not every branch represented by a failing test.

| Module | Failure/error entries | Character of observed mismatch |
| --- | --- | --- |
| `core.tests_pipeline` | 34 | Retired order endpoints return 426; old number-based order/membership and date assumptions; changed shell/route expectations; legacy invoice fixtures without current accepted order evidence; one protected preview returns 503 |
| `core.tests_portal_case_corrections` | 1 | Expected field set excludes the now-present post-visit HB deposit correction field |
| `core.tests_jawabu_data_quality` | 2 | Old identifier-validity expectations differ from current validation |
| `core.tests_jbl_visit_documents` | 3 | SimpleNamespace fixtures lack current deposit fields or `refresh_from_db`; tests error before reaching their intended assertion |
| `core.tests_reliability` | 2 | TAT creation exposed submitted input in field errors; its retry fixture lacked the current dispatch lookup context. Both now pass |

This table records the original failures. The protected-preview fixture now supplies a synthetic media root before using the mocked downloader. Every entry was investigated; the full consolidated run has no failures or errors. Original names/traces remain in `failure-index.json` and `audit-before-suite-summary.json`.

### 5. Case History route and TAT error privacy — fixed during remediation

The generic Portal screen allowlist omitted the existing Case History screen, producing a 404 despite its renderer and authorization rules being present. It now includes that screen; existing scope checks still apply. TAT creation now renders field messages from the safe message catalogue rather than returning raw exception text that can include submitted values. The existing privacy regression, message-contract suite and allowed/invalid-BRO creation checks pass. This response-only TAT fix changes no workflow grants or stage rules.

## Functional and edge-case coverage

The executed backend labels are retained in the summaries. The main run covers SysUp, FarmUp imports, pipeline queues, approvals, corrections, role separation, dashboards/navigation, publication scheduling, execution leases, orders, invoice identity/corrections, payments, HB actions/deposits, reporting, recognition, report delivery and Sheet validation. Supplemental tests cover visit-document preparation, data quality, physical signoffs, Portal reset, voice and template storage.

| Boundary | Evidence and remaining qualification |
| --- | --- |
| Import identity and replay | Connected FarmUp exact replay creates two cases once; existing tests exercise source preservation, partial commits, stale reviews and scope rejection |
| Zero and financial values | Connected SysUp preserves zero LGF; invoice and payment values remain Decimal-backed; no real money moves |
| HB deposit eligibility | Deposit tests execute blank/zero/under-threshold holds, edited totals, audit and visit lock behavior; two real-lock tests skip on SQLite |
| Visit evidence | Real image captures are collated, retained and linked before advancing; missing/duplicate capture validation passes with complete current fixtures |
| Approval authority | Connected Operations final/payment-review attempts receive 403; separate analyst and Head of Rural approve; stale credit revisions receive 409 |
| Order finality | Both partner sequences and retained workbooks run; unsigned-order invoice eligibility is rejected; accepted scans create HB work. Cancellation, reuse, stale versions and append boundaries are covered in requisition tests |
| Invoice parsing and identity | Real generated PDFs go through the parser subprocess and API; both match; duplicate and household/name-change branches execute in dedicated tests. Phone-format regressions pass |
| Payment lifecycle | Receipt-based creation, mixed membership, individual reviews, chronology, workbook generation, signed acceptance and completion all execute. No bank/payment-provider transaction is part of this workflow |
| HB timing | Connected attempts before installation, before the installation date, and without an early acknowledgement are rejected. Both actions end commissioned |
| Publication and recovery | Original alias headings publish without a workaround; scheduler tests cover failures, leases and retry behavior; canonical saves remain independent of publication |
| Reporting, documents and recovery | Scoped reports, local email generation, signoff/version controls, templates, voice and reset tests run; no provider delivery, production download or restoration drill is claimed |
| UI behavior | 269 synthetic Chromium contracts pass, including navigation/context, async guards, deposits, invoice/payment controls, uploads, confirmations, media gestures and responsive layouts |

The browser checks use synthetic API responses. The connected real-backend journey uses Django's HTTP test client, not browser clicks. Together they cover both surfaces, but they do not establish a complete browser-to-backend, real Telegram device acceptance run.

## Run it locally

Use the repository's existing virtual environment and installed Node dependencies. No deployment credentials are needed.

```powershell
.\.venv\Scripts\python.exe scripts\portal_local_audit.py --prepare
.\.venv\Scripts\python.exe scripts\portal_local_audit.py
.\.venv\Scripts\python.exe scripts\portal_local_audit.py --journey
npx.cmd playwright test --config=playwright.config.js portal_ farmup --workers=2 --reporter=json
```

The default backend command includes the former supplemental suites and the new regressions. The connected command asserts successful publication using the original alias headings, correct timestamps, phone mismatch handling and an empty unfinished-operation set. It retains a new local database for each run.

The harness reuses existing fake Sheets and the synthetic payment-template builder. This keeps the audit small, but changes to those test helpers may require a diagnostic update. Do not point this harness at operational files or reuse its synthetic authentication values in deployment.

## Limits and operator implications

- PostgreSQL was not available in this run. The six skipped checks cover competing operation claims, a PostgreSQL schema upgrade, concurrent invoice confirmation/unmatch, and deposit/visit races. SQLite success does not establish those locking guarantees.
- Real Sheets/Drive APIs, credentials, sharing, quota exhaustion, Telegram/WebView sessions, device cameras, email transport and production latency were not exercised.
- The legacy internal Orders tab was not enabled in the connected configuration. Master Data and Eco-conserve publication were exercised; internal-order unit paths and timestamp source were inspected.
- No production scheduler state was inspected. Current code has both the bounded drain command and a visible-session publication pump. Verify actual scheduling and deployment assets before making a scheduler-only or unattended-progress claim.
- Rejection, deferral, rework, invoice-name agreements, cancellations, reset and reporting were tested through their focused suites, not all woven into the same two-case happy path.
- No load test, backup restoration or live security/access audit was performed. No migration, dependency, deployment setting or production row needs changing for this patch. Deployment and live acceptance remain outside the executed work.

**Verdict:** The reported defects are repaired, the local backend gate is green, and the complete two-partner synthetic process finishes with correct Sheet projections. This establishes the exercised local contracts; PostgreSQL locking and real-provider/device acceptance remain separate checks.
