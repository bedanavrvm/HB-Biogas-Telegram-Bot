# Browser and Telegram channel rollout

22 October 2026. Implementation candidate under [ADR 0073](../adr/0073-browser-channel-and-complaints-parity.md).

## Release boundary

Production remains **disabled and unmounted**. `config/urls.py` has no browser
auth or operations mount. M1, E006, shared-cache, named-reader and privacy gates
remain. No production migration, grant, provider configuration, deployment or
real delivery was performed. Shared Django/database outages still affect both
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
