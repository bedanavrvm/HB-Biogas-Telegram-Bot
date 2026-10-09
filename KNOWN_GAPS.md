# Known Gaps and Verified Workarounds

## Origination field rules and country choices - 9 October 2026

Main and supporting documents now share typed controls and server validation,
including repeating cells. New reviewed schemas use active country choices,
integer counts/years, email/date rules and explicit county/sub-county bindings.
The document editor can remove rules and make ordinary fields optional. Shared
fields remain required when another selected document needs them; the form
explains this. Existing font/spacing and inline-only errors are retained.

No migration or new persistent model is needed. Published canonical keys/types,
application snapshots and frozen signed values are not rewritten. Review changes
in an editable document version, publish it, and use that version for new
applications. Nationality adopts replacement choice keys; old text keys survive.
PDF placements are human-reviewed, not automatically guessed or published.

Verification used synthetic fixtures and a separate local PostgreSQL 18 cluster:
112 focused tests passed, with no skips. The additional existing template/Generic
seed suite ran 65 tests: 60 passed, three failed and two errored. All five failures
reproduce on unchanged HEAD `f7bb59b7`; they concern older product-owned Admin
upload expectations and an empty supporting-document publication fixture.
No new regression was found. All 42 focused browser checks passed, including
320-430px forms, desktop controls, both Mini App themes, inline errors, drafts,
supporting fields and independent person/location dropdowns. Screenshots and a
rendered synthetic PDF were visually inspected. JavaScript syntax and the Node
suite passed; Django checks and migration checks passed.

The tracked-artifact audit still reports 19 existing logo/screenshot hash
mismatches. The findings are identical in the unchanged HEAD archive; this
change does not alter those assets or relax their allowlist.

Evidence is under `test-results/`: `origination-field-validation-focused-final.txt`,
`origination-field-validation-browser-final.txt`,
`origination-field-validation-regression.txt`,
`origination-field-validation-baseline.txt`,
`origination-field-artifact-baseline.txt`, `origination-fields-final/` and
`origination-field-validation/`. Full-suite, live Telegram device verification
and deployment remain unverified. No production records or integrations changed.

## Selected testing deletion across Mini Apps - 9 October 2026

Completed the shared selected-deletion action for reviewed Origination, Portal,
Complaints, TAT and SPIN Admin models. It is disabled by default and requires
`MINIAPP_TEST_DELETION_ENABLED=True` plus an active Superuser. Configuration can
keep linked operational history; deleting selected evidence includes its owning
workspace, disclosed in the confirmation. No mandatory note is added.

Exact impact fingerprints, current row locks, actor-bound retries and independent
compliance evidence protect deletion. Unknown links and stale confirmations block
the whole transaction. Shared identities/access grants, raw ingestion, Drive files
and captured recognition facts survive. Deleted finance claims remain consumed.
Sheet cleanup is DB-first, starts in a bounded server background task, and can be
retried through Integration operations. There is no cron or browser dependency.

Verification used synthetic data, a separate local PostgreSQL 18.6 cluster and
mocked Google integrations. All 99 focused deletion, finance and real-browser
tests passed on PostgreSQL with no skips. The affected existing workflow suite ran 394 tests:
381 passed, seven failed and six errored. The exact same 13 test failures reproduce
in an isolated worktree at unchanged HEAD `43974c63`; no new failure was introduced.
An initial reuse of a flushed test database also lost migration-seeded fixtures;
fresh database runs were used for the final comparison.

The real Admin selection/confirmation journey passed at 320, 430 and 1280px in
light/dark themes; screenshots were inspected for wrapping and overflow. JavaScript
syntax passed for 120 files, affected Python compiled, Django checks passed and
`makemigrations --check --dry-run` reported no missing migration.

Evidence: `test-results/miniapp-deletion-focused-postgres.txt`,
`test-results/miniapp-deletion-regression-postgres.txt`,
`test-results/miniapp-deletion-baseline-postgres.txt`,
`test-results/miniapp-deletion-js.txt`, and
`test-results/miniapp-deletion-live/`.

Apply payments.0008 and requisitions.0005 before enabling the setting. See
[the operator instructions](docs/origination-admin-guide.md#selected-testing-deletion-across-mini-apps)
and [ADR 0044](docs/adr/0044-selected-miniapp-testing-deletion.md) for ownership,
numbering, retry and safe rollback boundaries. Missing immutable Sheet IDs require
repair; no name/phone/row guess is made. No real customer record, production Sheet
or Drive file was removed. Live provider cleanup, full-suite validation, deployment
and physical Telegram devices remain unverified.

## Published LAF attachment in guided setup - 9 October 2026

Fixed the circular chooser rule that hid published documents until they were
already assigned to the product. Explicit attachment now retains the original
published document and alignment, validates compatibility transactionally and
does not silently create an unpublished copy. An empty allowlist still grants
no application availability; the catalogue explains it as "No products assigned".
Selected cards update after confirmed autosave without requiring refresh.

- The original missing-document reproduction failed before the fix and passed
  afterward; its regression coverage is now checked in.
- All 95 focused tests passed against a separate local PostgreSQL 18.6 cluster,
  with no skipped tests. This includes simultaneous first attachments, retries,
  permission denial, incompatible-selection rollback, immutable application
  snapshots, guided publication and the existing document authoring/maintenance
  browser journeys. The initial focused SQLite run also passed all 91 tests.
- Real Admin screenshots at 320, 430 and 1280px include light/dark views. The
  chooser, immediate selected cards, catalogue label and published Product
  were checked; mobile light/dark screenshots were visually inspected.
- First-party JavaScript syntax passed for 119 files; affected Python files
  compile and `git diff --check` passes.

Text evidence: `test-results/origination-attachment-postgres.txt`,
`test-results/origination-attachment-tests.txt` and
`test-results/origination-attachment-js.txt`. Screenshots:
`test-results/origination-attachment-live/`.

No deployment or production-data change occurred. No migration, setting or
external dependency is required for this attachment fix. After deployment,
open the Product's Documents task, select the published LAF, wait for Saved,
then publish the Product when its tasks are ready. Do not recalibrate the same
published PDF merely to attach it. The full repository suite, real provider
delivery and physical Telegram devices were not exercised in this change.
The separately completed cross-Mini-App deletion work is documented above.

## Origination testing, bootstrap and selected deletion - 9 October 2026

Implemented non-blocking deployment setup warnings, provider-configured OTP
availability, opt-in one-time release seeding of eleven private blank LAFs, and
Superuser-only permanent selected-product/Origination deletion. Authentication,
consent integrity, OTP verification/limits and independent approvals remain
enforced. No new model, migration, scheduler or simulator was introduced.

Verification used isolated SQLite, synthetic records and mocked integrations:

- The focused acceptance run completed 121 tests: 119 passed and two
  PostgreSQL-only concurrent-first-request tests were skipped.
- The real local Admin confirmation passed at 320, 430 and 1280px in light and
  dark themes, including Cancel, a protected selection and confirmed deletion.
  Final 320px light and 1280px dark screenshots were visually inspected after
  fixing the confirmation buttons' touch targets and focus states.
- All eleven sanitized PDFs retain pixel-identical rendering across 25 pages;
  author/XMP metadata and filled-widget checks pass. The blank bundle contains
  no customer submissions and is not exposed through static-file URLs.
- Seven artifact-audit unit tests and syntax checks for 118 first-party
  JavaScript files pass. Migration inspection reports no changes.
- An additional 43-test regression run had 39 passes, one PostgreSQL-only skip,
  and three existing failures: two BM permission/notice fixtures and the
  environment-template line-count assertion. They were reproduced with the
  previous signing/dispatch functions and unchanged environment template.
- Five older template-lifecycle/Admin tests also fail with the previous upload
  implementation; their product-owned assumptions or missing supporting schemas
  predate this change. These unrelated tests were not rewritten to pass.
- The new blank assets pass privacy/hash checks. The repository-wide artifact
  audit still reports 19 existing hash mismatches in the unchanged logo and
  Portal screenshot fixtures; the same mismatches are present in HEAD.

Text evidence is retained in ignored
`test-results/origination-plan-acceptance.txt`,
`test-results/origination-plan-browser.txt`,
`test-results/origination-plan-additional-regression.txt`,
`test-results/origination-existing-template-baseline.txt`,
`test-results/origination-existing-additional-baseline.txt`,
`test-results/origination-plan-privacy.txt` and
`test-results/origination-plan-migrations.txt`.

PostgreSQL locking/concurrency, real SMS delivery, physical Telegram devices and
the full repository suite remain unverified. No deployment, live seed upload,
external file deletion or real product deletion occurred. Enable the two gates
deliberately; bootstrap uses the existing release command and seeds unpublished,
unassigned drafts only. Alignment, signer/legal review and publication are still
human-owned. Permanent deletion cannot be undone through the app. Already-started
external requests cannot be recalled; subsequent queued dispatches skip deleted
Origination sources, while compliance history and external files remain intact.

## Canonical Origination values - 8 October 2026

Implemented explicit version-2 shared/document field meanings, scoped inputs,
allowlisted calculations, exact frozen document contexts, person-role reuse,
compatible selection and non-truncating rendering. Legacy applications are not
backfilled. Six supporting-LAF seeds remain unpublished and unassigned drafts.
Migration `origination.0006_originationdatafield_value_contract` is additive and
has only been exercised in isolated test databases, not a deployed database.

Verification used synthetic local fixtures and mocked external integrations:

- All 45 focused value-contract and supporting-seed tests pass, including a real
  signing-package freeze, rollback, identity separation, actor-bound retries,
  document deselection, retained financial-input exclusion and row-capacity checks.
- The broader 199-test regression run had 197 passes, one PostgreSQL-only skip
  and one existing Admin-label assertion failure. The unchanged published-document
  template says "Published document"; the assertion still expects "Published
  reusable document". That unrelated label/test was not changed.
- All nine Node suites and syntax for 118 first-party JavaScript files pass.
- The real Admin custom-PDF browser journey passes: upload, signer pack/edit,
  field meanings, placement, preview, publication and explicit Product attachment.
  Screenshot coverage includes 320, 390, 430 and 1280px; 320px field meanings,
  390px dark mode and desktop preview were visually inspected.
- All 10 Origination Mini App browser checks pass, covering queue widths,
  navigation, native validation and shared/local inputs. Final supporting-document
  screenshots at 320px were visually inspected in light and dark mode.
- Text evidence is retained in ignored
  `test-results/origination-value-contract-acceptance.txt`,
  `test-results/origination-value-contract-regression.txt`,
  `test-results/origination-value-contract-browser.txt` and
  `test-results/origination-value-contract-migrations.txt`. Synthetic Admin
  artifacts are under `test-results/origination-authoring/`.

The complete occurrence-by-occurrence register across the eleven paper PDFs is
not visually certified. Ambiguous paper fields and native legal signer roles
still need business/compliance review and real PDF placement checks; passing
seed hashes does not certify a document for legal use. Actual disbursement,
receipt collection, company applicants and arbitrary guarantor counts are not
introduced by this change. PostgreSQL parity, physical Telegram devices,
screen-reader verification and the full repository suite remain unverified.
No production deployment, live seed application or real external writes occurred.

## Complaints report controls and date cohorts - 8 October 2026

Implemented the Specific Quarter filter, compact chart-type icons, automatic
chart selection, selection feedback above search, and a five-card KPI row.
Date Type affects cards/table only; graphs retain their intrinsic date bases.
Reported vs resolved counts each reported complaint once under its current
Closed or Open & Reopened status, rather than counting repeat closures.
Complaint duration labels include hours/days; graph dates use dd-mm-yy across
Complaints, TAT and Portal without changing table dates or ISO filter keys.

Verification used synthetic local fixtures and mocked integrations:

- 75 focused Playwright checks pass, including real graph clicks, dropdowns,
  quarter selection, grouping/type alignment, keyboard paths and export parity.
- 186 focused Django tests completed: 185 passed and one PostgreSQL-specific
  test skipped on isolated SQLite. Coverage includes timing, register access,
  complaints and report delivery. A fresh migrated test database resolved the
  missing seed rows caused by reusing a previously flushed test database.
- All nine Node suites and syntax checks for 118 first-party JavaScript files pass.
- Screenshot coverage includes 320, 360, 390, 430, 768 and 1280px in both themes.
  Final 320px chart controls/quarter filters and mobile/tablet/desktop report
  screenshots were visually inspected. Artifacts remain under the ignored
  `test-results/playwright/` directory and are replaced by later browser runs.

PostgreSQL parity, physical Telegram devices, assistive technology and the full
repository suite remain unverified. No production deployment or real external
integration writes were performed. No migrations, settings or dependencies changed.

## Shared controls, media and TAT chart selection - 8 October 2026

Implemented shared native primary-action ownership, compact draft recovery,
right-aligned correction/status controls, fixed media zoom/pan and scoped chart
point selection. Form typography, workflow transitions and authorization remain
unchanged. Historical workload snapshots cannot identify their original cases;
clicking them explains this limitation instead of showing today's unrelated cases.

Verification used only synthetic local fixtures and mocked integrations:

- 80 focused Playwright checks pass, covering native-button validation/fallback,
  unavailable complaint types, real select taps/keyboard input, dependent locations,
  image corners at three aspect ratios, preview cleanup, chart series selection,
  historical totals and existing form/report/navigation regressions.
- 44 focused Django/report-email checks pass on isolated SQLite, including scope,
  distinct cohorts, measurement denominators and matching Excel/email filters.
- All nine Node suites and syntax checks for 118 first-party JavaScript files pass.
- Screenshot checks cover 320, 360, 390, 430, 768 and 1280px in both themes.
  Final mobile/tablet/desktop Complaint and TAT screenshots and a zoomed photo
  corner were visually inspected; the tablet draft-retry alignment was corrected.
- Text logs: `test-results/miniapp-controls-browser.txt` and
  `test-results/miniapp-controls-backend.txt`. Synthetic screenshots remain under
  `test-results/playwright/` (a later Playwright run replaces that output).

The original Complaint Type "does not open" symptom was not reproduced in local
Chromium: native tap/keyboard selection works in the real form shell. Catalogue
unavailability now has an explicit recoverable state; this is not proof of the
original device-specific cause. Physical Telegram Android/iOS picker, keyboard
and pinch behavior, assistive technology, PostgreSQL parity and the full repository
suite remain unverified. No production deployment or real integration writes were
performed. See `docs/miniapp-ux-parity-notes.md` for the shared component contract.

## Independent Origination authoring - 8 October 2026

Product setup now has three non-linear tasks: Details, Lending terms and Documents.
The independent Document editor owns PDF, signers, fields, placement and preview.
Both save drafts with server-confirmed feedback and have one Publish action each.
Product publication never publishes a document. Shared edits and product-only
copies preserve existing applications and their exact signing snapshots.

Verification completed with synthetic local data and mocked integrations:

- 71 focused Django checks pass, including two real localhost browser journeys.
  A subsequently added published-copy retry regression passes separately.
- Seven focused Playwright layout checks, all nine Node suites and JavaScript
  syntax checks (116 files) pass. Django checks pass; no migration drift.
- A custom PDF was uploaded, signers added and edited, lending fields added,
  nine fields/signatures placed, the rendered preview checked and the document
  published. The draft product was then linked and published without a dead end.
- Screenshots were inspected at mobile and desktop sizes, including dark mode.
  Published documents remain read-only while the mobile panel can still close.
- The before-change evidence is a synthetic post-upload editor checkpoint,
  not a recording of the entire original upload journey.

The broader fresh-database selection is not fully green: 183 of 188 tests pass.
The remaining three failures and two errors were reproduced against unchanged
HEAD Python code. They concern older template-admin expectations and an incomplete
supporting-document fixture, not the new independent-authoring flow. Evidence:
`test-results/origination-workspaces-final.txt`, `origination-copy-retry.txt`,
`origination-workspaces-fresh.txt` and `origination-baseline-check.txt`.
Screenshots and the final trace are under `test-results/origination-authoring/`.

Backend verification used isolated SQLite. PostgreSQL row-lock and concurrency
parity, production Python 3.12, physical Telegram devices and the full repository
suite remain unverified. Ruff/Black are not installed locally. No new models,
migrations, dependencies, settings, production deployment or real integration
writes were involved. See `docs/origination_product_setup_workspace.md`.

## Form presentation correction and Portal camera - 8 October 2026

Restored the existing per-app form text and control scale; validation now uses
inline errors and first-field focus without a repeated top list. Non-field
failures remain visible as one notice. Restore is green and Discard red in both
themes. Required markers, input preservation, recovery and workflow rules remain.

The inert Create lead camera was reproduced: media listeners were installed only
inside existing-case recovery. Camera/gallery/preview/removal now have separate
wiring for both new and existing cases. Synthetic tests cover ID/LAF/supporting
captures, one reused stream, permission denial, unsupported cameras and file picks.

57 focused Playwright checks pass, plus the existing full camera flow (58 total).
JavaScript syntax and all nine existing Node suites pass. Mobile/desktop screenshots
were inspected, including inline errors, both draft themes and the camera overlay.
Browser log: `test-results/forms-correction-browser.txt`.

The full repository suite and PostgreSQL tests were not rerun for these frontend-only
changes. Earlier broad-suite gaps below remain separate. Physical Telegram camera,
keyboard and screen-reader verification remains required. No migrations, new settings,
production deployment, customer data or real integration writes were involved.

## Shared Mini App forms verification — 8 October 2026

The shared submission-time validation, accessible error summaries and field-only
Complaint/TAT creation recovery were verified with synthetic local fixtures.
44 focused Playwright checks pass, including the actual Origination signing
template and Portal decision forms. Mobile screenshots were inspected; required
marker placement, field alignment and readable error text were corrected.
76 focused Complaint/draft backend tests pass on isolated SQLite. JavaScript
syntax and the existing Node suite pass.

The full browser run is not green: 399 passed and 9 failed. Eight failures were
reproduced against unchanged HEAD: obsolete camera text, complaint chart fixture
visibility, invoice iframe expectations and the superseded Prepare-order button
contract. The ninth was a fractional-pixel assertion; its corrected check passes
in the focused run. A broader backend selection also has an existing Complaint
asset assertion expecting the retired “Received vs resolved” label.

PostgreSQL transaction parity, physical Telegram WebViews, real screen-reader
sessions and real autofill/voice services remain unverified. No production data,
external integrations, schema or workflow permission changes were made.

## Portal agreement and preview verification — 6 October 2026

85 focused SQLite backend tests pass for agreement acceptance/retry, changed
identity, review flags, revoked/superseded corrections, financial holds,
disjoint invoice queues/counts, payment membership, letter rendering and scoped
reset cleanup and permission-checked signed-scan previews. Evidence:
`test-results/portal-agreements-tests.txt`.

64 Playwright checks pass with actual Portal components/styles and synthetic
offline API/Telegram data: pinch versus swipe, PDF page navigation, late-view
cleanup, retained receipt-origin search, attested file upload, named downloads,
320–430px mobile, 768px and 1280px layouts. Screenshots were inspected at 320px
and 1280px; Close icon sizing and wrapping action labels were corrected.
Evidence: `test-results/portal-media-browser.txt`; 19 further Portal media and
Complaints compatibility checks pass in `test-results/portal-media-final-browser.txt`.

Node checks and JavaScript syntax pass; migration checking reports no drift.
Logs: `portal-agreements-node.txt`, `portal-agreements-javascript.txt`, and
`portal-agreements-migrations.txt` under `test-results/`.

PostgreSQL lock/concurrent-acceptance tests and physical Telegram-device
verification are not run. The full repository suite is not claimed green;
earlier documented broader-suite failures remain separate. No production
migration, payment execution, Drive/Sheets write or real notification was made.
The new migration must ship with the code before signed agreements are used.

## Portal Operations verification — 6 October 2026

Focused backend checks cover order preview/append/cancel/reuse, exact signed
versions, protected invoice/payment evidence, SysUp choices and retries,
Operations policy repair, physical sign-off and configuration-scoped reset.
The latest complete focused run has 165 passing tests; final guard results are
in `test-results/portal-operations-focused.txt`.

42 Playwright checks pass using actual Portal modules and the production shell
stylesheet cascade with synthetic, offline API/Telegram fixtures. Screenshot
review covers 320, 430, 768 and 1280px order actions, invoice records, deliveries
and SysUp field review. This caught and corrected action heights, duplicated
SysUp headings, Close icon rendering and animation-time screenshot captures.
Evidence: `test-results/portal-operations-browser.txt` and
`test-results/playwright/portal_operations_workspac-*/`.

JavaScript syntax and Node checks pass; migration checking reports no changes.
Logs: `portal-operations-javascript.txt`, `portal-operations-node.txt` and
`portal-operations-migrations.txt` under `test-results/`.

The broader 302-test SQLite selection is not green: 31 failures and one error
remain in `test-results/portal-operations-python.txt`. It includes already
documented retired-route/report expectations, old automatic daily-order merge
contracts now superseded by explicit append, unsigned invoice fixtures, and
payment-document fixture failures. Not all failures have been independently
classified against unchanged HEAD; do not claim the repository suite passes.
The six pre-existing document-button geometry failures remain documented below.

PostgreSQL row locks, concurrent transactions, migrations/rollback on a copy of
the production schema, real Telegram and Google integrations remain unverified.
The local PostgreSQL test account was not available with usable credentials;
these backend runs used isolated SQLite. Before release, run the configuration-
scoped legacy finance audit and PostgreSQL checks described in ADR 0039.
Unowned legacy documents need explicit ownership review. Completed historical
payments are never auto-repaired or deleted to satisfy new signed-order gates.

## Invoice transport verification — 6 October 2026

The slow-upload and missing-authentication symptoms were reproduced with the
actual Portal modules and synthetic browser fixtures, then fixed. Invoice upload
does not use the browser's ordinary 20-second timer: the browser awaits the
server/network outcome while the upload button remains busy. This does not turn
parsing into a durable background task; closing the app or losing connectivity
can still lose the response. Check Recent uploads before retrying in that case.

27 related browser checks pass, including eight new transport regressions.
JavaScript syntax and all Node checks pass. Synthetic mobile screenshots were
inspected for upload feedback and invoice previews. No real Telegram device,
production invoice, Google integration, deployment or database suite was used
for this frontend-only change.

Six existing `portal_finance_actions.spec.js` document-button geometry checks
fail at 320/360/390/430/768/1280px (40px instead of the expected 44px). All six
also fail in an isolated, unchanged HEAD archive. Baseline evidence:
`C:/Users/Administrator/AppData/Local/Temp/portal-invoice-transport-baseline-e14f11a9ab6042ada90b9779f0898450/baseline-results.txt`.
They are excluded from the passing 27-check selection, not silently marked green.

## Portal role-workflow verification — 6 October 2026

113 focused backend tests and 87 browser checks pass. JavaScript syntax and all
Node checks pass; migrations report no uncommitted model changes. The backend
log is `test-results/portal-remediation-focused.txt`, and synthetic screenshots
are under `test-results/playwright/`. Apply core.0201 as documented in CHANGELOG.md.

The broader SQLite selection still has 25 failures and one error. An isolated
archive of unchanged HEAD reproduces exactly the same failing test names across
192 existing pipeline tests. These include retired route expectations and invoice
fixtures without finalized requisitions. Current evidence is in
`test-results/portal-remediation-django.txt`; baseline evidence is in
`C:/Users/Administrator/AppData/Local/Temp/portal-remediation-baseline-100512ad44094ada8dd2e3e6163015a7/baseline-tests.txt`.
Do not interpret focused passing checks as a fully green repository suite.

Local browser fixtures use the actual Portal markup, modules and stylesheet cascade
with synthetic API/evidence responses. Screenshots are checked at 320–430px,
tablet and desktop in light/dark themes. Real Telegram device camera permissions,
native PDF scrolling/gestures, map coverage and live voice-provider/Drive cleanup
remain authorized operator checks. Existing external Maps fallback remains available.
PostgreSQL and production integrations are not exercised by these SQLite tests.

## Report email client rendering — 5 October 2026

Browser screenshots use synthetic captured reports and substitute embedded
Content-ID images with data URLs for local preview only. They verify layout,
not actual Gmail/Outlook Content-ID handling, font fallback, or automatic dark
mode. Verify new emails in authorized test inboxes before broad rollout; no
live emails are sent during local tests. Report tables remain available when
images are blocked or dense charts cannot be drawn legibly. Retried frozen
emails deliberately keep their original typography and attachments.

## Portal density validation — 5 October 2026

The isolated SQLite pipeline selection is not green. A comparison with HEAD
backend modules reproduced 25 failures and one error across 192 existing tests,
including stale screen-route expectations, invoice fixtures missing official
requisitions, preview availability and legacy generation assertions. Logs:
`test-results/portal-density-baseline.txt` and `portal-density-backend.txt`.
The current 215-test selection has exactly the same failing test names.
Do not treat the focused passing tests as full pipeline certification; use the
current supported routes and finalized-order fixtures for manual verification.

The new reason/source-row and affected approval/location/draft checks pass
(26 tests). The combined 72 browser layout/interaction checks pass using synthetic
fixtures, including narrow widths, dark themes, source paging and report controls.
PostgreSQL, device Telegram WebView and live Sheets/Drive are not verified.
The local Python environment is 3.14 while the project targets 3.12; Ruff is
not installed locally. Run the pinned CI environment for release certification.

## Immediate report sending - 5 October 2026

Send now wakes a bounded worker after commit; it no longer relies on an operator
running a command. Pending work survives restarts in Django and is woken on
Settings/status requests. This is best-effort process-local execution, not an
always-on scheduler: unattended recurring reports and retries while no one uses
the app still need the existing runner. Provider acceptance is distinct from
verified delivery. Local validation passed 49 backend and 11 browser tests with
synthetic data/mocked Resend; live inbox delivery and local PostgreSQL execution
have not been verified in this session.

## Workflow-owned email settings - 5 October 2026

Portal, TAT and Complaints now provide IT-only schedule and recipient settings
for their own reports. A fresh isolated SQLite selection passed 78 backend
tests; the focused browser selection passed 15 tests, including mobile widths
and Complaints Settings navigation. PostgreSQL concurrency and real Resend
delivery remain unverified; sending remains off by default.

An additional broader selection exposed an existing clock-sensitive Complaints
timing fixture: it fixes case dates at 2 October but evaluates ages against the
current date. Its expected age bucket no longer holds on 5 October. This is not
a passing test and was not silently changed as part of email settings.

## Scheduled Portal email rollout - 5 October 2026

Resend delivery is disabled by default. Local checks use synthetic cases and
mocked provider responses; they do not establish verified-domain DNS, inbox
delivery, production webhook reachability or scheduler operation. Configure
and verify these using [the operator steps](report_delivery/README.md) before
enabling sending. PostgreSQL lease/isolation parity has not been run in this
session because no local `TEST_DATABASE_URL` was configured; use the existing
PostgreSQL test runner before production rollout. No production migrations or
real report emails were sent.

## Complaints, TAT and Portal depth review - 3 October 2026

See [the focused implementation review](docs/miniapp-depth-review-2026-10-03.md)
for source locations, reproduction details, test selections and failure
classification. Python 3.12.10, the pinned Python dependencies, Playwright
1.62.1 and Chromium are now installed locally. This supersedes the initial
source assessment's unavailable-runtime limitation below.

- Reproduced a TAT report authorization defect: its queryset combines scopes
  from grants that do not authorize reports. Report access must retain the
  capability and scope of one complete eligible grant.
- Reproduced an empty Portal case queue for group-scoped staff even though
  individual case permission allows their owned case. The central queryset
  omits the group relation required by the generic scope resolver.
- Reproduced complaint file-selection loss after a failed finish-created
  upload, Pending cursor traversal dropping newer rows, and changed TAT retry
  payloads returning unchanged state as successful receipt replays.
- The full browser suite ran 186 tests: 185 passed and one stale Complaints
  report fixture failed. The fixture lacks the current report summary/module
  contract and assumes two chart slides; the current report has eight.
- Two broad isolated SQLite backend selections ran 960 tests. Initial results
  were 12 failure entries/6 errors/2 skips and 25 failure entries/3 errors/3
  skips. Two logging failures came from the diagnostic harness and passed after
  correcting it. Other failures/errors remain classified in the review.
  Selected complaint modules had no failure/error entries; their concurrency
  check was skipped. No PostgreSQL concurrency success is claimed.
- Four focused synthetic database reproductions and the additional Node
  finish-upload probe passed by asserting the observed defects. These are
  reproduction results, not evidence of fixes.
- System checks, migration drift, migration graph, architecture boundaries,
  dependency parity, Python compilation and package consistency pass. The
  official write inventory fails with 27 routes; environment-template parity
  fails with 116 entries; the dependency exception expired before audit runs.
- Local Node 26 is outside the repository's supported range, and Windows
  Pango is absent, so native WeasyPrint import/layout is not verified. No live
  Telegram/Google integration or production resource was changed.

## Cross-workflow source assessment — 3 October 2026

See [the codebase assessment](docs/codebase-review-2026-10-03.md) for the
reviewed commit, source evidence, functional map and priorities. This was an
analysis session; application behavior and production resources were not changed.

- Legacy message deduplication hashes sender/content/time without group context.
  Identical inputs in separate groups can share a globally unique processing
  key. No production incident was reproduced. Review the intended scope and
  historical retry compatibility before changing the key.
- Unparsed invoice pages can log a 300-character document-text preview. Avoid
  treating ordinary logs as sanitized evidence; review access/retention and
  replace content diagnostics in a separately scoped fix.
- Legacy deposit fallback parsing uses `float` before document preparation.
  Canonical product quotes use Decimal; this finding does not establish an
  incorrect payment. Review fallback normalization and output compatibility.
- Database catalogue/checker app-label lists do not cover all installed local
  apps. QA models are outside the checked-in catalogue, and the additional
  bounded-model metadata checks omit the installed extracted-app labels.
- Legacy unbound Telegram profiles can retain username-based initial binding
  without activation proof. Review eligible enrollments before changing the
  identity contract. Atomic rejection tests also deliberately retain no raw
  intake rows; clarify rejection-evidence policy separately from case creation.
- The dependency exception expired on 30 September. A supplemental source
  cross-check identified 28 write-route inventory candidates; the official
  Python checker and a fresh dependency audit were not run in this shell.
- Fresh JavaScript syntax checks passed for 91 files, all nine Node test groups
  passed, and all seven tracked Apps Scripts passed syntax checks. Python
  discovery was retried but found only Windows Store aliases. Playwright was
  unavailable. No fresh backend, browser, PostgreSQL, migration, restore or
  live-integration success is claimed.

## Portal shared controls verification - 2 October 2026

- The focused PostgreSQL inbox/dashboard suite passes all 18 tests; JavaScript
  syntax and all nine Node test commands pass. No migration is generated.
- All 77 Portal browser tests pass on the final implementation without
  updating baselines. Results: `test-results/portal-shared-controls-browser.txt`;
  database results: `test-results/portal-inbox-postgres-final.txt`.
- Full-shell visual fixtures use synthetic API responses, not a live Django
  page/Telegram session. Browser coverage checks mobile/desktop geometry and
  light/dark themes. Linux CI rendering and production behavior are not yet
  verified by this local Windows run.
- Reviewed synthetic visual baselines are SHA-256-pinned. The tracked-artifact
  audit cannot count these new files until they are added to Git. Separately,
  HEAD already has a logo hash mismatch: `jawabu-logo.png` is `23a08f62...`
  while the existing allowlist expects `06c1d7e3...`. This unrelated asset was
  neither replaced nor re-approved by this UI change.
- Inbox responses are paginated, but their scoped task list is assembled in
  memory before pagination. Very large workloads may warrant a separately
  measured server-side task-query optimization; no new persistent inbox model
  has been introduced here.

## Complaints unified history verification - 2 October 2026

- Fresh PostgreSQL run: 94 tests, 92 passed, two failures. The local ignored
  log is `test-results/complaint-history-postgres-fresh-final.txt`.
- `test_customer_id_is_digits_only_and_preserves_leading_zeroes` expects
  "numbers only" while the unchanged validator says "1 to 9 digits only".
- `test_compact_two_state_workspace_has_only_supported_actions` expects the
  old `[0-9]*` template pattern. HEAD already uses `[0-9]{1,9}`; later assertions
  also contain outdated input labels and asset versions. These unrelated tests
  were not weakened to obtain a green suite.
- Browser feedback/draft/voice/queue regression, nine Node groups, JavaScript
  syntax and migration checks passed. Screenshots were inspected. No live
  Telegram or Google integration was exercised.
- Old history without immutable affiliation evidence is labelled Staff, not
  guessed from current grants. Existing Sheet comment cells change format on
  their next successful synchronization, not through an automatic bulk rewrite.

## Portal compact controls verification - 2 October 2026

The focused document-signoff/payment PostgreSQL suite passed 77 tests using
synthetic data and mocked integrations. Scan replacements retain previous bytes
and preserve workflow progress; preview scope and removable-duplicate selection
have regression coverage. No production Google/Telegram integration was called.
The 59 selected browser tests passed, including compact finance layouts,
notification scrolling, phone links and nested navigation. Performance screenshots
were manually inspected at 320px after the compact-height correction.

The wider `core.tests_pipeline` PostgreSQL run is not green: 192 tests ran with
25 failures and one error. Evidence is in the local ignored artifact
`test-results/portal-pipeline-postgres.txt`. Failures include outdated-client 426
responses, stale shell assertions and invoice fixtures without official orders.
This pass has not independently reproduced those failures on unchanged HEAD;
do not classify all of them as unrelated or claim a full-repository pass.

Duplicate removal is operational soft deletion, not evidence erasure. Payment
receipt, payment-history and identity-change references remain protected. Real
Drive movement and dialler handoff inside Telegram still need deployment smoke tests.

## Portal engineering remediation — 2 October 2026

Local prevention/recovery changes cover EQ-01/02/03/04/05/07/08/09/10/12.
EQ-06 (invoice diagnostic privacy) and EQ-11 (broad refactor) were excluded by
the user and remain open. See the implementation table in
[the remediation plan](docs/portal-engineering-remediation-plan-2026-10-01.md).

Focused PostgreSQL verification now includes real separate-connection claims,
fresh migrations and a representative prior payment schema upgrade. The earlier
197-test PostgreSQL selection and final 199-test run passed.
The 134 browser tests and nine Node groups passed. These are scoped results,
not a full-repository pass. The interrupted coverage run has no completed
verdict; its replacement focused run completed with bounded-domain reporting
(22.52% overall, not full-suite coverage). A reviewed full-suite coverage
baseline is still absent, and working-tree changed-branch gaps remain recorded
in `remediation-working-tree-coverage.txt`.

Existing full-suite failures were reproduced on unchanged HEAD. The existing
unsafe Mini App route inventory gaps and the dependency exception that expired
on 30 September still block full CI. They were not waived. Supported Python
3.12/PostgreSQL 16 Linux CI execution, clean dependency installation, physical
Telegram behavior, hosted capacity and an isolated backup restore drill remain
release checks (local verification used Python 3.14/PostgreSQL 18 on Windows).

Request-assisted publication does not guarantee progress when all clients are
closed. Legacy invoice attempts with unknown Drive outcomes require reviewed
reconciliation, not blind resend. Windows PDF workers have parent-enforced
timeouts and render budgets, but not Linux `RLIMIT_AS` memory enforcement.
Drain old workers at rollout; no production repairs or Google writes were made.

## Portal usability and cross-workflow audit - 1-October-2026

The audit's identified product defects have local fixes: background publication
is non-blocking and timeout-bounded, payment reviews bind to payment facts,
commissioning chronology is enforced, payment/HB edits have unsaved-leave
protection, payment lists are paginated, and expanded names wrap. Final-review
null handling was also corrected. Historical payment review digests have not
been migrated or restored; affected old open reviews need an explicit new review.

See [the audit report](docs/portal-usability-workflow-audit-2026-10-01.md) for
reproductions, priorities and the repair evidence. The post-repair selection
passed 318 backend tests on isolated SQLite, 84 browser tests and all nine Node
test groups. The 51 local rendered-page samples had no document overflow or
page exceptions; targeted interactions confirmed timeout lease release and
preservation of a second unsaved payment comment. PostgreSQL parity is still
unverified because local test credentials were unavailable. Live Telegram,
Google integration and physical-device checks remain separate release checks;
these results are not a claim that the entire repository suite passed.

## TAT credit assessment first release - 18-September-2026

SPIN and Metropol reports are still produced manually outside this platform;
the platform governs their evidence, questions, responses, and decisions after
upload. The future engine job boundary is deliberately dormant. Gmail polling
uses scheduled command execution rather than push notifications. Enable
`SPIN_HARD_CUTOVER` only after the new migration, personal Gmail OAuth, existing
restricted media Drive folder, staff roles, and live-device smoke test pass.


## JBL Visit document capture - 14-September-2026

Client ID currently uses existing protected Portal media-view scope, not a new
ID-only permission. No role matrix was changed. Local captures survive Case
History inspection but not closing/reloading the app; recapture after a reload.
Camera framing does not certify legibility or that the two images are distinct
document sides; staff must review both before submitting.

Local Windows rendering was verified with WeasyPrint 68.0 and MSYS2 UCRT Pango,
using `WEASYPRINT_DLL_DIRECTORIES=C:\msys64\ucrt64\bin`. The focused test checks
actual one-page Client ID and two-page LAF PDFs, embedded image draw commands,
and deterministic retry output. Live Telegram camera behavior still requires
device validation before release.

## Portal validation scope - 14-September-2026

Case-inspection navigation is locally covered with intercepted browser tests,
including the actual Portal card controllers. Live Android/iOS Telegram device
validation remains an operator release check. A cold/reloaded case link cannot
recover in-memory search or an unfinished local attachment selection; its
visible/Telegram Back uses the allowed source route instead.

The older Django test
`JblPipelineApiTestCase.test_portal_requisition_generate_requires_a_revision_for_each_new_assignment`
targets the retired `/requisition-queue/generate/` path. With a current request
key it returns 426 before revision validation, rather than the old expected
428. It is not evidence for the current preview/finalize path. New inspection
tests verify captured revisions through preview, and a service test verifies
that a changed case cannot be assigned an order. Unrelated old generation
fixtures were not rewritten as part of this navigation change.

The full intercepted browser run passed 49/50 tests. Its unrelated Complaints
report test (`miniapp_flows.spec.js`, date_reported assertion) still expects
`01-09-26`, while the approved current UI renders `01-Sep-2026`. Complaint
formatting was not changed in this Portal-only work.

## Portal reporting v1 scope

The IT-only Portal reporting workspace is deliberately limited to live
`JawabuFarmerMaster` case data, a server-owned field catalogue, named safe
aggregate counts, in-app aggregate visualisations, and local XLSX export. It is not an
arbitrary query builder and currently has no cross-workflow customer joins,
PDF/print output, Drive/Sheets publishing, scheduled delivery, saved data
snapshots, or historical version-diff renderer. TAT, SPIN, Complaint Case and
raw message models are listed through a read-only relationship inventory only;
they must not be joined by name, phone, national ID, or another mutable identity
until a separate ADR, data-owner rule, and release approval exist.

## Free Render publication reliability

The free Render service has no durable worker process. Portal writes therefore
do not wait for Google Sheets or Drive before committing canonical Django
state. A still-open Mini App performs one bounded follow-up publication
attempt; pending work is retained in `IntegrationOperation` or the document
sync fields and resumes on a later relevant Portal visit. This is durable but
not a replacement for a dedicated worker: a Render background worker remains
the recommended future upgrade for guaranteed scheduled retries and alerting.

## Portal import staging is intentionally not a commit workflow

The IT-only Portal Imports screen parses, stores, and reviews FarmUp/SysUp
source files only. It does not expose the existing customer-commit routines.
A future commit workflow needs its own approved maker-checker decision,
explicit row selection, and separate release authorization. Until then, any
Drive archive marked `needs attention` remains retriable from the authorised
Imports screen or support tooling. Archives use their own Imports path beneath
the existing approved Shared Drive root and remain visible only to its
approved members.

## JBL visit evidence after a Telegram/WebView return

Portal restores the current JBL visit's text, date, location and GPS-fallback
reason while the same browser session remains available. Telegram/mobile
browsers do not permit selected `FileList` handles to be retained or restored,
so an officer who temporarily opens the media selector or another screen may
need to reselect the LAF and visit photo before completing the atomic request.
The server validates both categories before it uploads either one; it never
records a forwarded visit without the required evidence.

## Android PDF rendering inside Telegram

Telegram's Android WebView can render a protected image stream in the Portal,
but may display a blank panel for a PDF served through a blob iframe. The
Portal therefore renders the authorized PDF server-side as bounded page images
inside its client-media overlay. It does not use an external Drive link,
browser activity, or Google document viewer. Very large or unusually detailed
PDFs may be rejected for in-app preview and can be retried after a smaller scan
is uploaded through the normal evidence process.

## Pending JBL scheduling backfill

`backfill_jbl_schedule_status` is intentionally dry-run by default. It may be
reviewed locally/staging with `python manage.py backfill_jbl_schedule_status`.
Its `--apply` and `--revert-run` paths change canonical Django status only and
are not authorised for production use until a separate rollout approval.

## Personal notification delivery preferences

`UserMiniAppPreference.alert_mode` remains stored for backward compatibility,
but recipient-level Telegram delivery does not yet apply immediate, digest, or
quiet choices. The Mini Apps intentionally do not render that selector until a
delivery worker enforces the shared mandatory-alert catalogue. Assignment,
approval, security, and overdue-breach alerts are not suppressible.

## Sentry production verification

The Django SDK is pinned, installed, initialized from `SENTRY_DSN`, and tested
with a synthetic DSN. Render's strict production-readiness gate passed on
31-July-2026 after Sentry configuration. The remaining operator verification
is a safe staging synthetic exception: confirm its alert rule fires and that
the event contains no customer/staff payload.

## Business Administrator role cutover

`core.0088_business_admin_role_cutover` was applied in production by the
31-July-2026 recorded migration baseline. It renames effective Portal/TAT/SPIN workflow access from legacy
`ADMIN` to `BUSINESS_ADMIN`, without rewriting historical audit evidence. Run
`python manage.py check_business_admin_cutover --strict` before the production
migration; it blocks unresolved pending legacy access-policy requests or
duplicate effective grant scopes. Capability seed-row overlaps are merged by
preserving the existing allow/deny policy. To undo after a controlled release, run
`python manage.py migrate core 0087_repair_tat_stage_target_snapshot_backfill`;
the reverse migration stops if a legacy-role collision would make rollback
ambiguous.

## Access-control checker bootstrap

`core.0090_accesscontrolcheckerassignment` is accepted for code merge and
local/staging validation only. It records independent checker appointments and
backfills legacy approver-group members without changing Users, Access Grants,
workflow state, financial records, or Mini App access. Before any approved
production rollback, export checker appointment and compliance-audit evidence,
then run `python manage.py migrate core 0089_portalcaseworkspace_portalsavedview`.

## Portal private workspace hold

`core.0091_pause_portal_workspace_to_it` is accepted for code merge and
local/staging validation only. It preserves existing private saved views, pins,
and recents. The Portal Mini App does not render any workspace control for any
role, including IT. The retained endpoint remains IT-gated only for controlled
technical validation; it is not a staff-facing feature. The migration
increments the policy version when it creates policy rows, forcing connected
Mini Apps to refresh permissions on their next metadata poll. It does not
alter customer cases, financial values, Drive/Sheets, or workspace records.

Do not roll back application code to re-open this feature. A future UI
re-enable requires an explicitly approved rollout and the existing capability
review; it must preserve the IT server-side gate. The migration's reverse is
intentionally a no-op so policy and compliance evidence remain retained.

## Portal workspace migration and retention

`core.0089_portalcaseworkspace_portalsavedview` was applied in production by
the 31-July-2026 recorded migration baseline. It adds only private, user-owned saved-view and case-workspace
metadata; it never changes Jawabu cases, workflow state, financial values, or
audit evidence. Django live scope checks hide inaccessible/closed pins
immediately. Until an authorised scheduler is configured, an operator may run
the read-only preview `python manage.py prune_portal_workspace`, then the
explicitly approved `python manage.py prune_portal_workspace --apply` on the
agreed daily cadence to release pins unavailable for 30 days and remove
un-pinned recent metadata older than 90 days. To undo after an approved
release, run:

```powershell
python manage.py migrate core 0088_business_admin_role_cutover
```

The reverse migration drops only the two private workspace tables; it does not
alter case, workflow, financial, or audit tables.

## TAT Settings migration

`core.0085_tattrackercase_stage_target_snapshots_and_more`,
`core.0086_seed_tat_target_snapshots`, and
`core.0087_repair_tat_stage_target_snapshot_backfill` were applied in
production by the 31-July-2026 recorded migration baseline. They add user-owned Mini App
preferences, maker-checker TAT setting proposals, escalation-rule storage, and
target snapshots for active stages. Before any rollback, export approved
configuration requests for audit evidence. To undo the schema locally or after
an approved release, run `python manage.py migrate core 0084_integrationcircuitstate_integrationoperation`.

## Mini App notification preferences

TAT stores an individual user's immediate/daily-digest/quiet preference for
non-critical alerts. Durable TAT action tasks now support shadow evaluation,
existing group alerts, and private delivery with retry and ranked backup
escalation. Production private delivery still requires the approved one-minute
platform scheduler and must pass `check_tat_production_readiness --strict`.
Legacy non-task TAT stage alerts may still be posted to the
configured shared Telegram group, not to individual recipients, so this
preference does not suppress, digest, or reroute those group alerts yet. A
recipient-level notification delivery ledger and scheduled business-day digest
job must be approved and implemented before enabling that behavior. Mandatory
assignment, security, approval, and overdue-breach alerts must remain outside
personal suppression in that future design.

## Bounded integration reliability

`core.0084_integrationcircuitstate_integrationoperation` was applied in
production by the 31-July-2026 recorded migration baseline. It records redacted external
operation/circuit state only; it does not start Celery, Redis, a scheduler, or
any automatic retry worker. Operators can run `probe_integrations` without
side effects for a configuration dry-run. `--execute` makes real read-only
metadata calls and must be an explicitly authorised maintenance action.

The current release routes shared Google Sheets batch writes, Drive uploads,
and Telegram launcher publishing through the durable register. Other legacy
direct outbound calls remain outside it and are listed in `TECH_DEBT.md`; they
must be migrated one bounded workflow at a time with replay tests. Strict Mini
App retry-key enforcement remains disabled until all refreshed cached clients
are verified in real Telegram clients. Do not set
`REQUIRE_MINIAPP_IDEMPOTENCY_KEY=True` during a production release without
that explicit verification and approval.

Last reviewed: 27-August-2026

## Compliance audit evidence

`core.0083_complianceauditchainstate_complianceauditcheckpoint_and_more` is
included in the pending release worktree but is not authorised for production
application. It adds an
append-only cross-workflow ledger, a PostgreSQL application-role immutability
trigger, read-only Admin investigation/export tools, and explicitly generated
daily checkpoint records. PostgreSQL database owners can still alter database
objects, so the ledger is tamper-evident rather than an absolute guarantee.

No automated retention deletion is implemented: every new compliance event is
on legal hold until JBL approves a legally validated retention schedule. No
mailbox delivery, scheduler, or scheduled sampling is enabled. Before enabling
those operations, approve a controlled recipient and mail configuration, test
the PostgreSQL trigger in staging, name an evidence owner, and record a tested
response path for failed delivery. Use `verify_compliance_audit --strict` and
`sample_compliance_audit --strict` only as supervised read-only checks.

## Sheet/Drive publication governance

`core.0082_sheet_register_governance` is committed but is not authorised for
production application. It adds local, publication-only Sheet contracts and
audit evidence; it does not alter Google Sheets/Drive or re-enable inbound
Sheet imports. Before relying on strict audit results, an authorised operator
must review each target tab and create contracts with
`python manage.py seed_sheet_register_contracts` (dry run) followed by the
explicit `--apply` only after the layout is confirmed. Run
`python manage.py audit_sheet_registers --strict` and
`python manage.py audit_drive_permissions --strict` as supervised read-only
checks. No scheduled audit, alert routing, automatic Drive-permission repair,
or periodic Sheets snapshot export is introduced; those need approved
recipients, a durable scheduler, rate-limit handling, and a retention design.

The TAT duplicate repair now verifies and re-publishes each linked survivor,
but it still deletes rows from the chosen live Sheet when `--apply` is used.
Use a copied Sheet first and keep the resulting `LiveSheetRecordChange` audit
evidence. A failed post-delete verification must be investigated manually; do
not rerun a destructive cleanup blindly.

## Portal approval controls and visit evidence

`core.0081_jawabuapprovalcondition_jawabuapprovaldelegation_and_more` is
committed but is not authorised for production application. Approval records,
conditions, temporary delegation, direct case-media links, and retrieval audit
are live only after the approved migration. Legacy farmer decisions and media
remain visible through compatibility reads; they are not retrospectively
asserted to meet the new evidence or authority controls.

The release deliberately does not delete Drive media. Run
`python manage.py audit_jawabu_visit_media --strict` to report unlinked
controlled evidence; it never changes attachments or Drive. Candidate review
and a separately approved retention/deletion policy are still required.
In-app SLA escalation remains an operational signal;
automatic Telegram/SMS/email delivery requires approved recipients, retry
handling, and a scheduled production job.

## Cross-workflow customer data cleanup

The governed customer-resolution rollout currently covers active Jawabu cases
and staged `/sysup` system exports. Complaint Cases, TAT, and SPIN retain
their present records and validations until a separately approved migration
maps their identity fields into the same customer-resolution service. Run
`python manage.py audit_jawabu_data_quality --strict` before a controlled
Jawabu cleanup; the command is read-only and must not be mistaken for a merge
or backfill tool.

## Telegram WebView printing

Telegram's mobile WebView does not provide a dependable browser print stack;
live canvas/browser print previews can be blank. The supported workflow is:
preview the document values in-app, then use **Open Excel** to download/open
the generated workbook in a proper spreadsheet application for printing. Do
not reintroduce `window.print()` as a production document workflow without a
new verified Telegram-client test and ADR.

## Physical document signing

Requisitions and final payment schedules support retention of a physically
signed-and-stamped PDF/JPG/PNG scan. The system records the authorised staff
attestation, source-workbook hash, scan hash, and Drive outcome; it does **not**
verify handwritten signatures, stamps, or legal e-signature validity. The
external e-signature integration remains deliberately on hold. Existing
documents without locally retained source workbook bytes are legacy records and
must be regenerated before a new traceable physical sign-off can be attached.

## Mini App recovery drafts

`core.0072_miniapp_drafts` is applied in the current production migration
baseline. Recovery requires verified Telegram identity and the form's existing
scoped authorization; it cannot promise an offline save. Offline edits remain
in the current open screen and become durable only after the UI shows that the
server saved the draft. Attachments are intentionally excluded.

Required verification before release:

1. A real Telegram mobile test for Portal JBL Visit, SPIN, FCA, FarmUp, and
   System Export draft restore, conflict behaviour, expiration, and attachment
   re-selection.
2. A future form must reuse the shared server draft service and enforce its
   own capability/scope before saving any field state.

### Order Approval browser draft remains

During the draft audit, `core/templates/order_approval/form.html` was found to
retain its own browser-local recovery draft. It was not converted in this
change because its form-token/Telegram authorization path and customer/media
field boundary need a dedicated review before server persistence is introduced.
Do not copy that local-storage pattern into another Mini App. A follow-up must
reuse the `MiniAppDraft` service only after it has a capability/scoped-token
authorization test and confirms attachments stay out of the draft.

## Workflow SLA delivery

The workflow-integrity command records or previews overdue-stage escalations
without sending Telegram messages by default. This is intentional: automatic
notification delivery needs approved recipient routing, rate-limit/backoff
handling, and an explicitly approved Render schedule. Until that operating
change is approved, run the command in dry-run mode and use the resulting
pending escalation records for supervised follow-up.

## Business-calendar and TAT trend operations

Official TAT/SLA time now excludes only dates entered and kept active in Django
Admin under **Business calendar holidays**. The platform deliberately does not
download Kenya public holidays from an external source, so an authorised
operator must confirm the year’s dates before relying on SLA reporting. Run
`python manage.py snapshot_workflow_tat --json` to review the current
projection; `--apply` is an internal, idempotent database write and still
needs an explicitly approved scheduler before it becomes a routine job.
Individual trend rows are emitted only where a workflow has recorded a named
responsible actor. They must be interpreted with the recorded branch, role,
product and paused/deferred-time context; absent attribution stays
role/branch-level rather than being guessed.

## Backup and recovery evidence

The production runbook requires Render daily PostgreSQL backups and quarterly
restore drills, but this repository contains no recorded successful drill or
measured recovery time. Treat the following as operating targets, **not proven
service levels**, until a drill is recorded:

| Store | RPO target | RTO target | Evidence required |
|---|---:|---:|---|
| PostgreSQL | 24 hours | 4 hours | Restore a current backup to staging and record elapsed time. |
| Google Sheets / Drive | 24 hours | 8 hours | Restore a copied/versioned spreadsheet or Drive document to staging and record the result. |

No production data reset, destructive Sheet cleanup, or migration is routine
until the relevant recovery path has been checked.

## Origination separation verification (4 October 2026)

See [the ownership and reference release notes](docs/origination-separation-release.md)
for the independent grant cutover, migration sequence and rollback limits.
Local verification uses synthetic SQLite databases with external network access
blocked. PostgreSQL table/column comments require the wired PostgreSQL CI job
or staging verification; Windows also lacks the native Pango libraries needed
for a full local WeasyPrint integration run.

Six existing Origination tests fail on the unchanged `092ead8` baseline as well
as the separated implementation: three legacy template-add presentation tests,
the former product-bound template upload test, the supporting-document activation
fixture with an empty form contract, and the packet-demo application fixture
without a governed product version. These remain separate from the ownership
change and must be reconciled with the current document catalogue contract.
The repository also retains pre-existing broad gate failures in the Portal
Ruff check, Mini App write inventory, environment parity and dependency exception
expiry. A passing focused check does not establish a passing full release gate.
