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

Remaining Complaints parity work includes long history, schedule send/status
variants, stored preference application and exhaustive offline/session-expiry/
history navigation protection for unsaved forms. No full parity claim yet.
Full workspace Refresh/reload currently returns to the default report view;
in-report Retry retains its report, grouping, filter and selection state. Saved
report-view/filter restoration belongs to the remaining navigation/preferences
acceptance, not a claim made by this slice.

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
