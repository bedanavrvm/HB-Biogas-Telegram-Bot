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

Full parity acceptance is not complete: the report candidate emphasizes reported
counts/types rather than every Mini App timing graph; long history, schedule
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

## Executed verification (22 October 2026)

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
