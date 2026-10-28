# Browser and Telegram channel rollout

28 October correction: the seven audited browser workflow gaps are repaired and
verified through native-session Playwright journeys against the real production
artifact/routes on isolated loopback data. See the
[source-bound review](../ui-standard/reviews/2026-10-28-complaints-workflow-parity.md)
for task evidence, role/denied-path checks and verification limits. Global report
details/history remain read-only under current Reports authority; owning-workspace
write/evidence permissions are unchanged. No release flag or deployment was enabled.

27 October release update: [ADR 0075](../adr/0075-complaints-browser-production-activation.md)
adds conditional real production URLs, an integrity-bound native build and
audited Admin invitations/onboarding. Defaults remain off. Follow
[the production runbook](staff-browser-production.md) for deployment, `bedan`'s
first sign-in, MFA support and rollback. No production deployment/admission has
been performed. The dated sections below retain earlier candidate evidence and
exclusions; their unmounted-route statements describe those historical slices.

22 October 2026. Implementation candidate under [ADR 0073](../adr/0073-browser-channel-and-complaints-parity.md).

## Release boundary

23 October update: ADR 0074 selects PostgreSQL-only native authentication state;
Redis/Memcached is not a prerequisite for that route. The settings/schedule/email
recovery extension and current acceptance evidence are recorded at the end of
this runbook. Historical slice exclusions below describe their original scope.

Production remains **disabled and unmounted**. `config/urls.py` has no browser
auth or operations mount. M1, E006, deployed shared-state, named-reader and privacy
gates remain. No production migration, grant, provider configuration or deployment
was performed. One authorized synthetic provider check is recorded below; it is
not an operational browser rollout. Shared Django/database outages still affect both
channels; separate adapters/artifacts are not infrastructure fault isolation.

The native operations interface is
`/api/staff/complaints/operations/v1/groups/<key>/`. Restricted v1 reads and the
loopback simulator remain unchanged. Never use the simulator as a live fallback.

## Implemented candidate

- Native admission/password/MFA, CSRF, current owning-workflow authorization;
  no alternate Telegram/token fallback.
- Explicit identity/history/evidence projections; no wholesale serializer,
  raw message, source message ID, private storage ID or Drive-link disclosure.
- Name/reference/ID/phone/branch search in POST bodies, status/branch/category
  filters, paging, case details and canonical create/comment/resolve/reopen/
  missing-detail/publication-retry actions. Existing services retain role,
  revision, replay, validation and audit rules. External publication failure
  does not roll back a canonical save.
- Owner/workspace/revision-bound server drafts, restore/save/discard, without
  attachment bytes or customer data in persistent browser storage. The browser
  draft slot is deliberately separate from Telegram's recovery slot.
- Dependent locations, optional geolocation, camera/file selection, private
  media preview/download and optional reviewed voice transcription with typed
  fallbacks and no automatic paid retry.
- Report filters/grouping, count charts with keyboard/click drilldown and table
  focus, named filtered/all XLSX, one-off email/status, schedule editing,
  preferences and bounded publication-recovery information.
- History API queue/new/report/case URLs under `/staff/app/complaints/`.
  The isolated test URLconf exercises direct links/reload/Back/Forward. No
  production SPA fallback is mounted yet.

## Attribution and switches

`ChannelRequestMiddleware` distinguishes attempted route from authenticated
channel. Only successful company authentication or HMAC-verified Telegram binds
verification; client channel headers cannot. UUID correlation and verified
channel are returned in headers. Logs include symbolic route, workflow, status,
duration, bounded APP_RELEASE and optional untrusted build telemetry, not raw
paths/queries, customer values, credentials or initData.

New audit events retain `metadata.request_context`; historical/replayed hashes
remain unchanged. Async origin evidence such as `report.email.requested` retains
context before dispatch; workers do not gain browser assurance. Historical jobs
and signed Telegram downloads are not retroactively attributed by this change.

- `STAFF_BROWSER_AUTH_ENABLED=False`: existing release gate; do not bypass E006.
- `STAFF_BROWSER_COMPLAINTS_ENABLED=False`: operations-only kill switch (404).
- `STAFF_BROWSER_DEMO_ENABLED=False`: production true triggers E009; it never
  switches real screens to fixtures. Loopback demos remain separate servers.

## Build and test

Use pinned Node 22.23.3 in `browser/`: `npm ci`, `npm run typecheck`, `npm run lint`,
then `npm run build -- --complaints-operations` and the same with `--development`.
The distinct `dist-complaints-operations*` artifacts retain source/integrity
manifests and notices. Native builds reject simulator imports. No npm dependency
or proprietary font/image asset was added.

Set RUN_STAFF_BROWSER_E2E=1 and STAFF_BROWSER_TEST_NODE to the Node 22 executable.
Use `.venv\Scripts\python.exe manage.py test` with
`--settings=staff_auth.transport_test_settings --keepdb --noinput`, targeting:

- `core.tests_channel_context`, `core.tests_browser_complaints`,
  `core.tests_browser_complaint_operations`, `core.tests_compliance_audit`,
  `core.tests_telegram_authentication`, `staff_auth.tests_browser_api`;
- `staff_auth.tests_complaints_operations_transport.ComplaintsOperationsTransportTests`.

Only the isolated synthetic SQLite database and loopback are allowed. Screenshots
and layout evidence are in `test-results/complaints-browser-operations/`; light/
dark widths: 320, 360, 390, 768, 1280, 1366, 1440, 1920. Evidence is not approval.

## Remaining acceptance

M1/shared-cache multiworker operation, privacy/named readers, real mailbox/support,
production origin/static/CSP, PostgreSQL locking/audit serialization and real
provider paths remain unverified. SQLite does not verify PostgreSQL comments.
Authorize test destinations separately before real Drive/Sheets/voice/email IO.
Review actual devices, keyboard/enlarged text, assistive technology, camera,
microphone, dialer and PDF behavior. Screenshot fit alone is not design approval.

Full parity acceptance is not complete: the timing/outcome report slice below
now covers the existing chart populations; long history, schedule
send/status variants, applying stored preferences on entry and all offline/
history/session-expiry draft paths still need dedicated acceptance. Do not invent
general case-correction or evidence-deletion authority absent canonical services.
Before-unload and ordinary navigation warnings exist; exhaustive unsaved-form
protection is not claimed. No live production-readiness claim follows.

Only after explicit operational acceptance mount an immutable artifact and bounded
SPA fallback, then regress both channels against the deployment. Rollback disables
browser operations/auth and restores its prior artifact, preserving canonical
records, audit history and Telegram access. Never regenerate approved baselines
merely to pass review.

## First-slice verification (22 October 2026)

- Final isolated run: **54 tests passed** (52 focused backend/auth/audit/read
  checks plus real React/native-session operations in production and development
  build modes). The existing restricted-read browser transport also passed
  separately: 24 interaction checks and 14 captures.
- TypeScript, full recommended ADS/styling lint, dependency/archive/notice guards,
  both operations builds, restricted-read build, Python compilation, UI source
  ratchet and `git diff --check` passed. No approved baseline was regenerated.
- Each operations build produced 35 captures: light/dark across eight widths,
  retained-input/draft/action states and reports. Desktop queue, dark mobile,
  form errors and report compositions were visually inspected and refined.
- One broader existing test remains failing:
  `core.tests_telegram_authentication.CanonicalTelegramAuthenticationTests.test_explicit_test_mode_can_use_logged_in_user_without_unsigned_identity`.
  It expects 200 but gets the owning permission check's 403. The same result was
  reproduced with the new middleware removed and channel binding replaced by a
  no-op, without modifying tracked sources. It was not counted as passing or
  fixed by weakening authorization.
- No PostgreSQL, real device, production deployment or real external provider
  acceptance was performed. Remaining parity/acceptance above is still open.

## Next slice: Complaints timing and outcome reports (22 October 2026)

The native operations build now has three report views, without changing the
restricted read build or the local role simulator:

- Complaints overview: Reported vs resolved, reported complaint types and the
  current Closed/Open-and-Reopened status of each reported cohort.
- Turnaround performance: median final resolution, recorded targets, resolution
  by complaint type and first Home Based response, with elapsed-hour units,
  readable durations and explicit sample/target denominators (no technical n=).
- Open-case follow-up: one age chart and distinct complaints reopened per period.

All values come from `complaint_report_summary`, `complaint_report_page` and
`complaint_timing`, not a second browser calculation. Reporting date controls the
cohort graphs; closure/first-response/reopening dates control their own graphs.
An earlier-period complaint resolved now is not falsely counted as newly reported.
The existing IT-only global report permission/scope is retained, not silently
converted into a group-specific or cross-workflow grant.

The closed POST reports adapter accepts an optional allowlisted `selection`
object. Summary receives report filters; table receives those filters merged
with the selected metric/date/category. Filtered export receives that same merged
selection. Legacy calls without selection keep their behavior. Chart selections
do not alter the source chart or overwrite the visible report filters; clearing
selection restores the base list. Week/month/year drilling never expands outside
the user-selected dates. Changing report filters invalidates the selection.

Chart dimensions observe the actual column width. Count axes use integer ticks;
timing axes use hours, with explicit unavailable/zero handling. Sparse series
default to bars; line mode positions points by actual dates. Top-ten category
views have full searchable selectors for every category. Keyboard point activation
and selectors apply the same selection and focus the matching table. Official ADS
references, installed API inspection and narrow SVG exception: browser/DESIGN.md.

### Change-specific phase handoff checklist

Based on `codebase-analysis-docs/assets/PLATFORM_INDEPENDENCE_RELEASE_CHECKLIST.md`:

- [x] Additions/scope: browser Complaint reporting only, under ADR 0073; no TAT,
  Origination or Portal migration. No operational financial functionality.
- [x] Canonical data: existing reporting/timing/filter/export functions; no new
  state transition, model, schema migration, grant, signature or money rule.
- [x] Channel compatibility: production routes remain unmounted and browser
  switches off. No Telegram endpoint, asset, authentication or role change.
- [x] Configuration/dependencies: none added. Same pinned Node/React/ADS build;
  no new package, chart library, external font or remote asset.
- [x] Synthetic safety: only opt-in isolated SQLite/native-session and loopback
  tests; no real Sheets/Drive/SMS/Telegram/email/voice side effects.
- [x] Verification: 68 focused native/backend tests and 22 tooling tests pass;
  both build modes, type/lint and source guards pass. 89 synthetic captures per
  build (178 total) include light/dark widths 320/360/390/768/1280/1366/1440/1920,
  chart close-ups, enlarged text, partial weeks, empty/error/retry states.
  Representative desktop/mobile/line/timing/follow-up captures were visually
  inspected. Candidate captures are not human approval.
- [x] Monitor/rollback: compare reported and closure cohorts, hour units,
  no-target denominators and chart/table/Excel selection counts. Restore the
  previous browser artifact/adapter or leave browser disabled. No data rollback.
- [ ] Unresolved release gates: M1, shared-cache/multiworker and PostgreSQL,
  privacy/named readers, real providers/devices/accessibility/design acceptance,
  production origin/static/CSP and deployment. No merge/deployment performed.

The subsequent continuity slice below handles long history, stored queue
preferences and safe report URL restoration. Schedule send/status variants and
exhaustive offline/session-expiry/history protection for unsaved forms remain
open. No full parity claim is made.

Main source pointers: `browser/src/complaints-report-charts.tsx` owns presentation
over canonical summary values; `complaints-operations-reports.tsx` owns filters,
selection, retry and export. `core/api/browser_complaint_operations.py` retains
the existing native company/Complaint authorization and delegates both cohorts.
Backend parity checks are in `core/tests_browser_complaint_operations.py`;
`staff_auth/tests_complaints_operations_transport.py` and
`scripts/test_complaints_operations_transport.js` exercise actual native sessions
and built assets. The UI registry records candidate hashes, not approved baselines.

### Reporting-slice tooling and environment notes

- Final isolated run: **68 tests passed** (66 backend/auth/audit/read/timing
  checks and both real React/native-session browser build modes). No tests were
  skipped in that run. Browser checks exercise sparse and zero-hour timing,
  separate cohorts, target denominators, keyboard and dropdown drill-down/focus,
  exact table/export selection, clipped partial weeks, retained retry filters,
  no document reload during soft navigation and empty persistent client storage.
  Native source/asset guards reject stale builds. Source-matched evidence:
  `test-results/complaints-browser-operations/<build>/layout.json` and PNGs.

- TypeScript, the full recommended ADS/styling lint sets and production/development
  operations builds pass. Native artifacts verify source/asset hashes and notices;
  no synthetic transport is in their import graph. Windows builds used
  `PARCEL_WORKERS=2` after an intermittent native Parcel worker exit.
- UI source ratchet, architecture boundaries, changed-Python Ruff/compilation,
  JavaScript syntax and diff checks pass. No legacy baseline was rewritten.
- 22 UI-ratchet/dependency-review tooling tests pass with TEMP/TMP set to the
  existing fully spelled Windows temporary-directory path. The machine's default
  ADMINI~1 short alias fails the unchanged fixture's resolved-path containment
  check; no security/path guard was weakened or source test skipped.
- The full repository suite, remote CI, PostgreSQL, real staff/devices/provider
  delivery and production deployment were not run. The previously documented
  Telegram permission-test failure is outside this reporting-only slice.

## Next slice: continuity and review availability (22 October 2026)

Saved Complaint queue status and branch preferences now arrive with bootstrap
and apply before the first queue query. An explicit queue-status link overrides
the saved default. Reads create no preference row; explicit saves reuse the
existing audited, workflow-specific preference service. Invalid status/types
and unsupported filter keys are rejected. A selected branch remains visible if
the current facets contain no matching cases. Settings loading/failure has a
bounded timeout and working retry rather than a false empty publication state.

Report view, grouping, date basis, status, real calendar dates and bounded page
numbers have allowlisted History URL state. Workspace Refresh no longer
unmounts the report during bootstrap loading. Soft navigation/Back/Forward and
reload restore these safe controls. Branch/category text and searches remain
in memory, never URL/history-state or persistent browser storage; they reset on
full reload or History reconstruction. A chart drill-down remains transient.
No document reload occurs for ordinary navigation/filter actions.

Native detail now loads 25 history events, followed by explicit older pages.
Signed one-hour keyset cursors bind the exact case and timestamp/UUID, never
grant authority, and recheck native/owning-group access on every POST. New
comments cannot shift already traversed older pages. Notes/affiliations still
use canonical history projection, not live role inference. Legacy resolution
notes appear once on the final page. Telegram and restricted-v1 defaults are
unchanged. Network failure retains loaded rows; invalid/expired cursors have
Refresh activity, which restarts at the newest page. Nothing is silently
written to Sheet or changes the case revision during browsing.

### Foreground local review

Run `scripts/start_complaints_local_review.ps1` from the repository root and
wait for the readiness message, then open http://127.0.0.1:8769/_review/.
The helper selects existing Node 22, builds the current native entry and runs
the exact opt-in isolated Django test host. It never mounts a production route
or alters production accounts. Native password/MFA sign-in uses only the
synthetic values shown on that loopback-only, no-store instruction page.

Each start gets a dedicated fresh SQLite test database, separate from automated
transport tests. This fixes duplicate synthetic users after an interrupted
previous run. Verified assets are pinned in memory so agent rebuilds do not
change the current review. Restart to see new changes; Ctrl+C stops it, with a
12-hour upper lifetime. The older no-account 8767 simulator is unchanged.
Full commands, behavior and connection-refused recovery: browser/README.md.

### Change-specific phase handoff checklist

- [x] Scope/canonical boundary: native Complaints continuity and isolated local
  review only. No new model, schema, dependency, money rule, policy or grant.
- [x] Channel isolation: native operations adapter is still separate from
  restricted-v1, simulator and Telegram. No operational URL/settings change.
- [x] Privacy/access: current native/Complaint authority on every history page;
  case-bound tamper/expiry checks; allowlisted safe URLs and no persistent
  customer values. No raw message or private storage identifier exposed.
- [x] Review availability: dedicated fixture DB and native sign-in smoke checked
  on a separate loopback port, without interrupting a user's review process.
  Startup instructions are private/no-store; fixture proof is not logged or
  captured. No real external-service request is authorized.
- [x] UI references: current official ADS Select/Button/SectionMessage usage,
  installed controls and token composition documented in browser/DESIGN.md.
  Candidate source hashes only; no approved baseline or Phase 6 migration.
- [x] Verification: 77 focused native/backend/auth/audit/timing/history tests
  passed, including both actual React build modes. Each mode captured 93 scenes
  (186 total) at the existing light/dark viewport matrix, with settings and
  history retry/expiry/61-event checks. Representative captures were visually
  inspected, including settled theme transitions. Both browser modes were
  rerun successfully after improving screenshot synchronization. No skip was
  counted as a pass. The earlier ambiguous Select test was corrected to choose
  the exact label, not by relaxing application behavior.
- [x] Static/tooling: both builds, TypeScript, full source ESLint, changed-Python
  Ruff/compilation, navigation allowlist tests, architecture/UI ratchets,
  PowerShell parser and diff checks pass. 22 tooling tests pass with the existing
  documented long-path TEMP/TMP workaround. Review-host HTTP/no-store and real
  native password/MFA were separately smoke-tested against synthetic data.
- [ ] Operational acceptance: M1/shared cache, PostgreSQL/multiworker, privacy/
  named readers, real providers/devices/assistive and human design acceptance,
  production origin/static/CSP and deployment remain gated.

Rollback: keep browser disabled or restore the prior browser artifact/adapter.
Preference rows already use the existing schema; no data/schema rollback is
needed. Do not modify historical audit records or Telegram role grants.

## UI correction before the next slice (22 October 2026)

`ui.txt` supersedes the previous layout, not the channel/security contracts.
The unfinished ambiguous-write/offline/session-recovery slice was parked before
this work; none of it is represented as completed by a cleaner interface.

Implemented review candidate:

- Actual ADS underline tabs for mutually exclusive Complaints and Reports;
  Settings is a separate reloadable destination. One primary Create opens a
  modal. Settings and Refresh are subtle icons, not competing view buttons.
- 1280px workspace; desktop queue about 384px, detail fills the remainder.
  Narrow screens open detail with Back. Full-row selection, readable
  Open/Reopened/Closed statuses, customer/complaint details, Description,
  Activity, Attachments, then valid contextual actions replace the dropdown.
- Account preferences are bounded to 480px with saved feedback. Pending
  Sheet work is one compact summary outside Settings; failure details can
  open the authorized complaint for its existing retry action.
- Reports default to Last 30 days, disclose custom dates and extra facets,
  simplify redundant/single-category charts, and show equal-period KPI
  comparisons. Labels use human dates. Legends, headroom and chart help are
  simplified without inventing targets or financial conclusions.
- Actual AG Grid Community 36.1.0: seven sortable/resizable columns, full-query
  canonical sort before paging, current-workspace row links and Enter opening.
  A small result set has no external pager; mobile horizontal scroll stays
  inside the grid. Chart selection still focuses that exact result cohort and
  export. Scheduling moves to Settings; one Export dialog owns Excel/email.
- The existing safe History routes remain instead of a second hash router.
  Prior explicit visibility of authorized National IDs is preserved. No fake
  app switcher, reporter, target colour or production capability is added.

References and narrow native-dialog/SVG/AG Grid composition exceptions are in
browser/DESIGN.md. Exact dependency/archive/licence records and the unchanged
peer exception are in browser/DEPENDENCIES.md. No schema, grant, real provider,
operational database or Telegram implementation is changed. Candidate source
hashes change; approved baselines and Phase 6 remain on hold.

Local human review: restart `scripts/start_complaints_local_review.ps1`, wait for
readiness and open http://127.0.0.1:8769/_review/. Its fresh synthetic seed now
varies branches, complaint types, dates and statuses. The foreground helper
pins assets at startup; builds intentionally do not replace a running review.
Use only the synthetic login on that private loopback instruction page.

UI verification record:

- Native production and development/StrictMode journeys each capture 87 scenes
  (174 total): queue/detail, history failure/expiry/full paging, creation errors,
  report views/charts/table, settings, both themes and 320/360/390/768/1280/
  1366/1440/1920 widths where applicable. Enlarged text is checked at 200%.
  Keyboard modal Escape restores the real opener. Table sorting and row Enter,
  KPI filters, custom-date validation, report retry, safe URLs, preferences,
  History Back/Forward and an Excel filename are exercised, not inferred.
  A separately labelled synthetic paging-response check verifies that applying
  AG Grid's initial sort does not reset a restored report page. It is not
  claimed as a live 100-record dataset or a substitute for canonical paging tests.
- 29 focused canonical browser/API tests plus the two native build-mode journeys
  pass together on isolated full-schema SQLite. The previous foreign-group
  denial remains 400; no authorization rule was relaxed to make a test pass.
  Canonical table facts are compared without the newly added workspace link
  metadata, whose group ownership is tested separately.
- A separate temporary loopback host verified the varied 47-case seed through
  actual native password/MFA and produced 19 additional synthetic captures at
  390/768/1366 in both themes. Representative paired charts, table, modal,
  settings and mobile/dark screens were visually inspected. Platform-font
  diagnostics confirmed the actual system font rather than only CSS names.
  That varied-data review preceded the final KPI-button/copy polish; the
  production/development transport captures cover the final native sources.
- TypeScript, full ADS/style lint, both builds and the 173-peer dependency guard
  pass. Production/development outputs contain 82/83 noticed packages; nested
  archive ownership and reviewed licence hashes are retained. No font/image
  asset or Enterprise Grid is emitted. UI/architecture ratchets, changed-Python
  Ruff, navigation/calendar-date tests and diff checks pass. The 22 existing
  ratchet/dependency tooling tests pass with the documented long TEMP path.
- Initial screenshot checks exposed unused detail width, enlarged-text overflow
  and dialog typography inheritance; these were corrected and rechecked. No
  approved screenshot baseline was changed to accommodate them.

These are technical and synthetic visual checks, not user design acceptance,
real-device/assistive-technology testing, PostgreSQL/multiworker validation or
production sign-off. M1 and the previously listed release gates remain open.

## Complaint form recovery handoff (22 October 2026)

This resumes the reliability work parked for `ui.txt`. It completes the bounded
creation/case-update recovery slice, not all settings/email recovery or release
acceptance. The codebase-design skill informed the one-task recovery module;
the two forms use the same retained-value and exact-submission handling.

### Change-specific checklist

- [x] Additions/scope: creation and case-action text, chosen File objects,
  captured revision and pending request survive same-tab native session expiry
  and same-account password/MFA reauthentication. Offline editing is permitted;
  no offline save or automatic reconnection/credential/write retry is claimed.
- [x] Authorization/privacy: bootstrap returns an opaque account/password-hash/
  admission-revision HMAC after current Complaint authorization. It is not an
  access token. Other owners/security generations, explicit logout/discard and
  confirmed saves clear the one-task tab memory and invalidate stale callbacks.
  Values/files/credentials are never put in browser storage, URLs or history.
  A successful response arriving during unmount is retained as a confirmation,
  not converted into a new complaint on return.
- [x] Retry/drafts/history: a lost response keeps the exact request key, values,
  file objects and expected revision. Explicit retry confirms the canonical
  result without a second case/comment. Draft save/discard reads the current
  server revision before another write and does not overwrite a newer device's
  draft. Back/Forward cancellation restores the actual same-document cursor;
  history contains only that numeric cursor and existing safe route controls.
- [x] UI: preserve the revised shell/dialogs/AG Grid. One persistent uncertain-
  save message scrolls into view, has keyboard focus and explicit retry/leave
  actions. Temporary read-only submitted fields are the documented exception;
  ordinary editing is not locked. The leave confirmation explains that a save
  may already have completed. ADS references are in browser/DESIGN.md.
- [x] Affected workflows: closed native browser Complaints only. Shared
  StaffAccess adds opt-in network-failure retention and logout cleanup; other
  entries retain their existing defaults. Telegram endpoints/assets/grants and
  the synthetic simulator remain unchanged. Shared process/DB outages still
  affect both channels; this is not infrastructure fault isolation.
- [x] Migrations/configuration/dependencies: none. No new model, package, grant,
  production mount, enabled browser flag or external provider side effect.
  Restart the foreground local-review helper to load the newly built assets;
  a running review intentionally keeps its startup-pinned version.
- [x] Executed focused checks: 20 native API/canonical tests and two actual
  password/MFA React-to-Django journeys pass on isolated full-schema SQLite.
  Production and development/StrictMode each produce 101 synthetic captures
  (202 total). New offline/uncertain states cover 390/1366 in both themes;
  existing scenes cover 320/360/390/768/1280/1366/1440/1920 where applicable,
  including enlarged text. Representative final recovery screenshots were
  visually inspected, not just checked for viewport fit.
- [x] Tests exercise actual session ending/fresh MFA with retained text/file,
  canceled/accepted History Back and Forward, a committed comment with its
  response discarded, draft lost-response read reconciliation, and creation
  returning 201 then 200 under the same request key. Database assertions prove
  exactly one comment and one created complaint. Pure recovery tests also
  cover different owners/tasks, explicit clear and stale callback denial.
  A final two-build rerun advances the client clock through quiet session polls:
  network failure keeps the current editor, whereas an injected HTTP 403 hides
  customer content and requires a real native session recheck before recovery.
- [x] Source/build checks: types, full ADS/style lint, production/development
  builds and dependency/asset guards pass; 22 existing ratchet/dependency
  tooling tests pass. UI/architecture ratchets, Python Ruff, navigation/calendar
  and recovery checks are required with the final candidate hashes. CI now
  builds/exercises the closed operations entry as well; remote CI was not run.
- [x] Shared-entry regression: nine native auth/read transport tests pass,
  including both build modes. Eleven existing complaint-timing tests pass alone
  and in the final combined 33-test recovery/timing run. An earlier exploratory
  combined invocation was red (four timing assertions and two setup errors);
  do not count that attempt as passed. No reporting rule was changed to
  accommodate it. The final focused/combined runs are the verification record.
- [x] Monitor/rollback: inspect request outcome/retry and field retention on
  reconnection; keep normal auth rate limits. Restore the prior browser asset
  and operations adapter with browser still disabled. No schema/data rollback
  is required; never reverse canonical records or rewrite their audit history.
- [ ] Remaining gates: unsaved preferences, schedule editors and report-email
  tasks are outside this recovery contract. Reload/tab closure loses unsaved
  memory; use Save draft for server-retained text and reselect files. After an
  uncertain save followed by reload, check the queue before submitting again.
  PostgreSQL/shared workers, real providers/devices/assistive technology,
  privacy/retention and human design acceptance, M1 and production integration
  remain unverified. No merge/deployment or real staff admission was performed.

Reproduction commands (Node 22, isolated test settings only):

```powershell
node scripts/test_workspace_navigation.js
node scripts/test_workspace_recovery.js
node browser/scripts/build.cjs --complaints-operations
node browser/scripts/build.cjs --complaints-operations --development
$env:RUN_STAFF_BROWSER_E2E = '1'
python manage.py test core.tests_browser_complaint_operations staff_auth.tests_complaints_operations_transport --settings=staff_auth.transport_test_settings --noinput
```

Use the repository `.venv` and a synthetic test-only secret. Current loopback
review credentials were verified through ordinary password/recovery-code MFA.
Refresh `http://127.0.0.1:8769/_review/` for the running fixture and unused code;
normal rate limiting may apply after failed attempts. Never weaken auth to
make the review available. No credentials are recorded in this handoff.

## Responsive Complaints correction (22-23 October 2026)

This supersedes the earlier seven-column/manual-draft UI descriptions above,
not the native authentication, workflow authorization or release boundaries.

- The queue fills the remaining viewport and scrolls independently. Desktop
  detail has its own scroll area; returning from mobile detail retains the
  queue position. Pagination stays outside the scrolling list. Hidden panes
  are not measured as though they were visible.
- Queue and report filters open from one Filters button. Related inputs use
  two columns without changing ADS typography. Report controls retain search,
  status, branch, complaint type, date basis and grouping, plus current or
  historical calendar month/quarter/year and custom dates. Invalid/incomplete
  ranges do not trigger report requests. Active choices remain visible.
- Creation autosaves server drafts after a short pause; Saved means the server
  confirmed it. There is no manual Save draft button. Draft conflicts, offline
  state and uncertain saves retain the existing explicit recovery path, never
  automatically replay a business submission. Files remain memory-only and
  must be selected again after a reload. Draft restore/discard is still explicit.
- Light/dark/system control stays visible in the header, including phones.
  Only the non-sensitive theme choice is persisted in local storage.
- Outcome notifications use icon/word/message toasts. Errors and warnings are
  dismissible; routine confirmed autosaves use the small Saved indicator.
  Field errors and persistent recovery instructions remain with their task.
  Toasts inside modals remain interactive; closing an export dialog cannot
  attempt to show a detached popover.
- Chart help is a contextual dialog. Appropriate charts offer line/bar or
  pie/doughnut choices. Bar values sit inside when they fit, line values sit
  above centred points and dense dates angle diagonally. Drill-down smoothly
  focuses the filtered table, respecting reduced-motion preferences.
- AG Grid Community remains the table: ten default columns, all 23 selectable,
  bounded internal scrolling, canonical supported sorting and page-aware row
  numbers. Phone links dial and National IDs copy without also opening the row.
  Activity uses two logical rows, with wrapped notes rather than empty repeats.
- Evidence has a large zoomable/pannable preview, opposite-end navigation,
  original download, and clear timeout/error/retry feedback. Browser-only
  POST `evidence/<uuid>/preview/` checks native CSRF and current Complaint
  evidence access, validates the page and reuses the existing bounded PDF
  subprocess renderer. It returns one page and page count, not a public URL.
  Telegram's preview appearance and original-download route are unchanged.

### Verification and review evidence

- Production and development/StrictMode native operations journeys passed,
  together with both responsive CLI journeys: four tests, no skips. Each full
  journey produced 101 synthetic captures; each responsive journey produced 25.
  The CLI checks six widths (320/360/390/768/1366/1920), both themes, bounded
  scrolling, restored position, wrapped errors, autosave, quarter filtering,
  selectable columns, real Excel download, chart selection and media controls.
- The focused native API suite passed all 23 tests on isolated full-schema
  SQLite, including PDF-page access/CSRF/invalid-page checks, a real two-page
  renderer fixture and failure recovery. Drive reads were mocked; no real
  provider, customer record or operational database was used.
- TypeScript, full ADS/style lint, six native entry/build-mode artifacts,
  dependency/notice/asset guards, changed-Python Ruff, architecture/UI source
  ratchets, pure navigation/recovery tests and diff checks pass. All 28 tooling
  tests pass with the previously documented long-path TEMP/TMP workaround.
- Early red runs exposed hidden-pane scroll resets, modal-inert/detached toast
  handling and silent preview timeouts. Regression checks exercise those
  paths; a successful rerun is not inferred from screenshots. The operations
  fixture's short resolutions now start at 06:00 UTC to prevent a late-evening
  test run from crossing Nairobi midnight and merging different daily medians.
  No reporting calculation was changed to accommodate that test-clock defect.
- Source-bound captures: `test-results/complaints-browser-operations/<build>/`
  and `test-results/complaints-responsive/<build>/`. Mobile queue, wrapped-error
  alignment, desktop/dark reports and preview failure were visually inspected.
  These are temporary review evidence, not approved baselines or user approval.

The final combined shared sign-in/restricted-read and responsive rerun passed
all 11 tests in 129 seconds, with no skips. Initial unsuccessful invocations
are not counted as passing.
The final 23-test API plus development-responsive run also passed together
(24 tests, 36 seconds). Additional Chromium platform-font checks passed in
both build modes, alongside the declared-font and wrapped-control alignment
assertions. These do not substitute for real-device font/accessibility review.

Restart `scripts/start_complaints_local_review.ps1` to review the new artifact
at `http://127.0.0.1:8769/_review/`. A running review deliberately retains its
startup-pinned assets; rebuilding does not silently replace them. Use only the
fresh synthetic credentials shown on that local page.

No production routes/flags were enabled, no role grants or schema changed and
no Telegram appearance was migrated. Real devices/assistive technology,
PostgreSQL/shared workers, real delivery, privacy/named readers, M1 and explicit
human design/release acceptance remain outstanding. No commit or deployment
was performed. Rollback restores the prior browser artifact/adapter while
keeping the browser release switches disabled; canonical records are retained.

## Complaints composition and interaction correction (23 October 2026)

The user approved the whole browser Complaints correction and an explicit
green-positive/red-destructive action convention. This supersedes the earlier
theme-popup and in-flow save-indicator presentation, not its security contracts.

- Dialogs have a persistent titled header with X, independently scrolling body
  and separate action footer. Header status has reserved height from initial
  render; Saving/Saved cannot insert a row above form fields. Spinner/check/
  warning/error icon plus concise text convey state. Saved remains a confirmed
  server draft; detailed recovery/validation stays in the task.
- Filter dialogs use a 720px maximum width, available phone width, grouped date
  and complaint criteria and a separate Reset/Done footer. Searchable option
  menus portal into the active dialog's accessible layer, outside its scrolling
  body. The menu itself adapts to viewport space and scrolls independently.
- Heading/Create, tabs/utility controls and search/filter occupy distinct rows.
  A compact sync control replaces the sentence above results. The native
  recovery endpoint additively returns exact pending/failed/suspended/total
  counts over the same existing group query; disclosed records stay capped at
  50, failed first. Counts represent complaints, not individual queued updates.
- Attachment capture buttons pair symmetrically. File rows keep their name and
  Preview/Download controls aligned. Copy/Next are detail utilities; workflow
  actions have their own divided section. Modal Cancel/Submit no longer look
  like attachment controls. Section titles, metadata colours and light dividers
  provide hierarchy without changing the existing type family or type scale.
- Positive buttons use the documented local success-token adapter, destructive
  buttons use ADS danger and utilities remain neutral. Direct theme switching
  sits at the navbar's far right, follows system initially and persists only
  the explicit theme enum. There is no theme dialog.
- Turnaround metrics share three equal columns at ordinary phone sizes and
  reflow for enlarged text. Header utilities and footer actions also reflow
  rather than clipping. Error toasts remain dismissible and are positioned
  above a modal footer so that Submit is never hidden behind a notification.

Native dialog/select composition, local positive-action token mapping and
measured accessibility layout are explicit exceptions in browser/DESIGN.md.
No new dependency, font, model, migration, workflow permission or operational
channel mount is introduced. Production stays off/unmounted and Telegram
assets/authentication are unchanged. The API counts are additive; rollback may
restore the old browser artifact without deleting any canonical records.

Verification (23 October 2026): all 37 focused tests passed with no skips:
24 operations API tests, nine authentication/restricted-read transport tests,
and four operations browser tests covering production and development builds.
The full native-session journeys captured 101 screenshots per build; the
responsive CLI journeys additionally covered 320/360/390/768/1366/1920 px,
200% text, light/dark, 100-option searchable menus, unchanged field positions
during autosave, offline/failed-save recovery, media and real Excel downloads.
Screenshots and layout geometry were inspected, including the repaired
development desktop width. They remain synthetic candidates under
`test-results/complaints-browser-operations/<build>/` and
`test-results/complaints-responsive/<build>/`, never approved baselines.
TypeScript, recommended ADS/style lint, dependency/notice/build guards, 28
tooling unit tests, architecture/UI ratchets, changed-Python Ruff and whitespace
checks also passed. Authentication, restricted-read and operations artifacts
were rebuilt in both modes; the final development operations build used one
Parcel worker after a native multi-worker build exited without diagnostics.

The regression loop initially caught dropped Grid aria-label forwarding,
200% header clipping and a toast intercepting Submit. These were corrected in
the actual composition rather than hiding overflow, shrinking text, forcing
test clicks or weakening the assertions. An early foreign-group denial test
was corrected to expect the existing 403, not by relaxing access checks.
The development run additionally caught the documented ADS atomic-class order
collision: local single-column declarations now use `repeat(1, minmax(0, 1fr))`
instead of reusing Root's base class. A real Main-width assertion protects
against empty desktop gutters; waiting for virtualized headers alone was not
treated as a fix. Error notifications now clear with their owning error, not
an unrelated notification or a successful task on another screen.

Restart the existing local-review command to load this build. A running host
keeps startup-pinned assets. Real devices, assistive technology, PostgreSQL,
shared-worker/provider operation and human design/release acceptance remain
separate gates; no remote CI, deployment or real external IO is claimed.

## PostgreSQL-only security state and remaining task recovery (23 October 2026)

User scope: finish settings, schedule and report-email recovery; exercise real
PostgreSQL/concurrency and native worker authentication; prepare delivery,
support, privacy and device acceptance. The user explicitly chose PostgreSQL
instead of a new paid cache. ADR 0074 supersedes ADR 0069's cache-only choice.

### Delivered scope and handoff

- Preferences, schedule drafts/recipients and report-email address/filter scope/request/status
  survive same-owner native password/MFA reauthentication in this tab. Recovery
  remains bound to the existing account/security-generation receipt. Navigation
  guards, explicit discard/logout and account changes invalidate retained tasks.
- `workspace-task.tsx` captures one exact JSON request before dispatch. A lost
  response retains it for explicit retry; sign-in/reconnect never resubmits.
  Schedule IDs/revisions and report-delivery request IDs are retained, preventing
  duplicate schedules or emails. An uncertain email can be explicitly closed
  with a warning to check the inbox before sending another.
- Stale preference snapshots return 409 rather than overwriting another save.
  An exact lost-response retry returns the current values without another audit
  write. Reload saved preferences retains local edits for deliberate review;
  loading a saved schedule explicitly discards its local draft.
- PostgreSQL conditional upserts implement native atomic add, database-clock
  expiry and owner-bound lock release. A stale lease cannot overwrite a successor's
  history. Only the pinned allauth rate-limit and used-TOTP namespaces are routed
  to this state; ordinary workflow keys keep their previous local-cache behaviour.
  No vendor monkeypatch, Redis package/service or new external dependency.
- Raw native keys are HMAC-digested before persistence. Values are bounded JSON
  timestamp histories/opaque markers, not pickle, credentials or customer values.
  Live rows cannot be cleared/culled. The existing factor-seed TOTP replay table
  remains defence in depth. Native store failure fails closed, never to local state.
- Normal deployment must apply `staff_auth.0004_staffbrowsersecuritystate`.
  There is no data backfill, workflow grant or production migration performed here.
  Browser-on selects the adapter automatically; browser-off configuration and
  Telegram remain unchanged. E006 and production URL closure remain deliberate.
- Maintenance: `purge_staff_browser_security` previews by default; `--apply`
  removes one expiry-rechecked batch, maximum 10,000. Run it only against the
  intended environment. No live security-state reset is a supported repair.
- Rollback: disable browser access and drain browser workers first. Restore the
  previous artifact/configuration; only then, if needed, reverse the temporary
  table with `python manage.py migrate staff_auth 0003_staffbrowsersetupgrant`.
  Preserve accounts, admissions, durable replay claims, sessions and audit evidence.

### Executed evidence

- All 118 focused tests passed, with no skips, on the final source-bound
  PostgreSQL run (`test-results/browser-acceptance-current.log`). Coverage includes
  the security-state adapter, durable replay claims, native password/MFA/CSRF,
  owning Complaint access and operations, channel context and report-delivery
  reservations. Five independent processes share native rate limits and atomic
  used-code state; two native password/MFA processes accept the same OTP once.
- The six browser journeys passed in production and development/StrictMode:
  task recovery, complete operations and responsive controls. Tests exercise
  offline/session loss, same-owner native reauthentication, lost committed
  responses and exact retries. Email scope survives reauthentication; schedule
  and email retries do not create another job. Full operations captured 101
  synthetic screenshots per build; responsive checks cover 320/360/390/768/1366/
  1920 px, light/dark, enlarged text, modal controls, media and Excel downloads.
- The separate browser-off/native abuse regression passed all 19 tests on
  isolated SQLite (`test-results/browser-abuse-current.log`). This complements,
  and does not substitute for, the actual PostgreSQL concurrency results.
- Both operations artifacts built successfully. TypeScript, recommended ADS/UI
  lint, changed-Python Ruff, architecture/UI-source ratchets, all 28 tooling unit
  tests, navigation/recovery scripts, whitespace and the 216-table catalogue
  check passed. `makemigrations --check --dry-run` reports no missing migration.
- Migration 0004 was successfully unapplied and reapplied on the exact empty
  isolated PostgreSQL test table after test completion. The rollback plan touched
  no other model; PostgreSQL table comments were verified. No production schema
  was changed. The temporary cluster was stopped after verification, not deleted.

The red/green loops caught lost email-filter scope and a Playwright autosave
route released before it arrived. The fixes retain the original scope and await
the actual intercepted request; no forced click, weakened assertion, credential
bypass or production activation was used. Fresh recovery screenshots were
inspected to confirm that a stale session-error toast does not survive sign-in.

All database evidence uses a separate PostgreSQL 18 loopback cluster and explicit
`staff_auth.acceptance_test_settings`, never the installed operational database.
Independent subprocesses use the same ephemeral test encryption key through
stdin, not separately generated keys or logged credentials. Native wrong-key
configuration was observed to fail closed during diagnosis.

Live provider smoke check, 23 October 2026 at 10:11 EAT: the existing Resend
adapter accepted exactly one synthetic report to the privately authorized Gmail
destination (provider ID `01a1679a-254a-7161-9be4-b2cd7f377971`). Its real generated
`complaints-report-2026-10-23.xlsx` attachment was 4,935 bytes, SHA-256
`aac2837d2faf56e069a716fd6f7ccacae1489510e9d49bf0ad7b1591ca729cd9`.
No customer data or database reads/writes were used. The delivery flag was
overridden only inside that one process; the configured deployment flag remains
off. Evidence is in ignored `test-results/synthetic-provider-acceptance.log`.
The mailbox owner confirmed receipt and successful Excel opening in this session.
This completes the bounded synthetic provider/recipient check, not the complete
browser-to-live-provider workflow, onboarding delivery or support drill.

Builds and captures remain candidates, not approved baselines. Recovery screenshots
are under `test-results/complaints-task-recovery/<build>/`; full workflows retain
their existing source-bound screenshot directories. Keyboard checks distinguish
browser chrome (no DOM focus) from forbidden focus in the inert page background.

Reproduce with the repository environment and Node 22 after building both native
operations artifacts:

```powershell
$env:RUN_STAFF_BROWSER_E2E='1'
# Set TEST_DATABASE_URL to a separately authorized local PostgreSQL test DB.
# Never substitute DATABASE_URL from deployment or use customer records.
.venv/Scripts/python.exe manage.py test staff_auth.tests_security_cache core.tests_browser_complaint_operations staff_auth.tests_complaints_tasks_transport --settings=staff_auth.acceptance_test_settings --keepdb --noinput
```

### Operational acceptance still requiring external evidence

| Check | Required evidence / operator action |
|---|---|
| Render topology | Staging with intended PostgreSQL version, real workers, origin/cookie/CSRF/CSP/static configuration and agreed proxy/IP policy. Local worker tests are not a deployed-staging sign-off. |
| Gmail delivery | The single authorized synthetic submission was provider-accepted, and the mailbox owner confirmed receipt and a readable Excel attachment. The complete browser-to-live-provider/support drill and email-client display review remain outstanding. Keep credentials and the recipient address outside Git/chat. Queued/mock/locmem/provider-accepted status alone is not inbox delivery. |
| Account onboarding/support | Real invitation delivery and a supervised existing-staff enrollment/recovery drill, named primary/backup support owner and escalation procedure. The closed setup preparation is not a commissioned mail-dispatch product. |
| Privacy/access | Named reviewer acceptance of identifiers, evidence, location, report/export/recipient scope and retention; no automatic legal or organizational approval from code/tests. Existing Complaint role/group rules and IT report authority are unchanged. |
| Real devices/accessibility | Named physical phone/browser and desktop assistive technology: keyboard/large text, camera permission/cancel, file/PDF download, dialer, offline/reauth and return focus. Playwright viewport emulation is supporting evidence, not a physical-device or screen-reader pass. |

Privacy engineering scope reviewed: identity/search values stay out of URLs,
history state, persistent browser storage and channel logs. Native endpoints
require current browser admission/MFA plus owning Complaint capabilities; raw
source messages, private Drive identifiers and unreviewed fields are excluded.
Evidence access is rechecked per request. Reports retain their canonical IT-only
authority; this change does not silently make global report data group-local.
Named disclosure/retention approval is still required.

Support handoff: a current active Superuser uses the existing audited admission
actions for authorize/suspend/revoke-sessions/reset-MFA. First verify the exact
existing staff identity and scope; never disable MFA or clear live security state
to resolve a login problem. On an uncertain write, confirm/retry the captured
request; never create a replacement email merely because its response was lost.
The complete live browser/delivery workflow, named owners, physical devices and
production release remain unaccepted until their evidence above exists. The
bounded synthetic Gmail check is confirmed; it does not close those gates.
Nothing here authorizes deployment.

## Specification 18 verification

23 October 2026: the browser Complaints candidate now implements the queue and
detail hierarchy, protected evidence gallery, shared dismissal/notification
controls and cohort-correct reports in
[Specification 18](https://github.com/bedanavrvm/HB-Biogas-Telegram-Bot/issues/18).
The previously authorized recovery/security work is included. The current
[review record](../ui-standard/reviews/2026-10-23-complaints-spec18.md) documents
before/after provenance, official design references, scoped exceptions and
rollback. This entry records current execution; older counts above describe
their own earlier verification.

Current isolated checks:

- The final PostgreSQL run covered 48 checks: 47 native security/operations/
  recovery tests and one source-bound visual comparison. It passed 47 of 48;
  the production Specification 18 journey counted AG Grid rows before rendering
  finished. After adding a wait for the last row, both production and
  development journeys passed (2 tests, 59.502 seconds), retaining the exact
  25-row-plus-header assertion. All 48 checks have passing coverage across
  these runs; the full suite was not repeated after this test-only wait.
  Logs: `test-results/spec18-retry-postgres.log` and
  `test-results/spec18-retry-final-journeys.log`. No tests were skipped.
- A regression reproduced positive durations rounding to zero on a days axis.
  Both native build modes now verify `<0.1 days` for a small positive duration,
  `0 days` for an exact zero and broken lines for missing timing periods.
  Both operations artifacts were rebuilt from the final source.
- 77 additional PostgreSQL tests passed: complaint timing, shared Mini App
  preferences, channel isolation, native browser authentication, abuse controls
  and TOTP replay/concurrency. No tests were skipped. Log:
  `test-results/spec18-final-regression.log`.
- Both production and development/StrictMode browser builds passed using pinned
  Node 22; TypeScript, browser lint and context/selector-parser checks passed.
  No dependencies were added or upgraded.
- First-party JavaScript syntax (162 files) and all root Node regression suites
  passed. Ruff, architecture, UI source ratchet, database governance/catalogue,
  the write-route inventory and migration graph passed. `makemigrations --check
  --dry-run` found no changes; 216 application tables and 291 migrations were
  checked. No production migration was run.
- Final Standards and Spec reviews have no remaining source findings. Their
  fixes include normalized preference retry under the shared row lock,
  attachment-owner binding for colliding group-local message IDs, independent
  notice ownership, and blocking sign-out/Excel dismissal of uncertain saves.

Reproduce the native suite after building both operations artifacts:

```powershell
$env:RUN_STAFF_BROWSER_E2E='1'
# TEST_DATABASE_URL must select an isolated loopback PostgreSQL test database.
# Set STAFF_BROWSER_TEST_NODE to the pinned Node 22 executable if needed.
.venv/Scripts/python.exe manage.py test staff_auth.tests_security_cache core.tests_browser_complaint_operations staff_auth.tests_complaints_operations_transport staff_auth.tests_complaints_tasks_transport --settings=staff_auth.acceptance_test_settings --keepdb --noinput
```

The native journeys cover password/MFA and real Django endpoints, protected
image/PDF rendering, cross-group denial, queue page positions, canonical saves,
table/search/export scope, dialog focus and recoverable lost responses. Both
build modes include light/dark responsive and enlarged-text checks. Provider
transport is synthetic/blocked; no further live delivery was attempted.
The final comparison captured 20 screenshots per source; current desktop and
phone captures, both themes, the evidence gallery and timing labels were
inspected. Comparison manifests retain source/artifact/screenshot hashes and
the rendered system-font evidence. No approved baseline was changed.

Broader exploratory checks are **not all green**. The tooling suite passed 74
of 75 tests; its unchanged dependency parser misclassifies the first-party
`scripts` namespace. Environment-template parity reports 119 discrepancies,
identical to clean `f4a37ded` when checked with the same parser. The unchanged
strict Sheet-header test
`ComplaintRegisterCutoverTests.test_strict_sheet_contract_accepts_only_exact_row_one_headers`
also failed in the broader earlier run because a previously validated header
was cached. These are recorded existing issues, not additional fixes or a
claim of whole-repository CI success. A SQLite responsive run hit a database
lock; final native concurrency/browser acceptance uses PostgreSQL.

The physical-device, assistive-technology, deployed M1, privacy and support
acceptance gates above remain open. No Telegram UI, roles or approval baseline
was migrated, and no human review service was restarted. Production remains
disabled/unmounted. UI rollback never clears native security rows or weakens
evidence authorization; use the review record and ADR 0074 boundaries.


### 23 October 2026: manual Complaints UI audit repair

The user requested UI corrections after the exhaustive manual audit and
explicitly requested no tests. This follow-up uses Playwright CLI journeys and
static type/lint/build/source-integrity checks; the earlier test results above
were not rerun and must not be attributed to this source revision.

The current change/disposition/evidence record is
[2026-10-23-complaints-ui-repair.md](../ui-standard/reviews/2026-10-23-complaints-ui-repair.md).
All before/after screenshots live in the same
[evidence folder](../ui-standard/reviews/complaints-manual-audit-assets/).
Review remains local, native, synthetic and provider-blocked. The repair adds
safe existing-record sync timestamps to the authorized recovery projection;
no write, role, authentication or production-mount contract is changed.
Physical-device, assistive-technology, M1, privacy and human acceptance remain
separate gates. Rolling back UI code does not clear security or workflow rows.
