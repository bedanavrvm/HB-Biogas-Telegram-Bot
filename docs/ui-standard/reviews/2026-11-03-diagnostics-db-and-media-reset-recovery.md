# Diagnostic connection recovery and retained media reset

The production logs showed independent conditions: a deliberate Portal
maintenance 503, a dropped PostgreSQL connection during diagnostic ingestion,
and a reset guard treating a retained media-access event with no live farmer
as a foreign-case link. Public static JS/CSS reads matched the current legacy
importer hashes; old version query strings alone were not evidence of old code.

## Changes

- Reset ownership checks ignore an absent farmer FK on retained access evidence,
  still reject a live foreign farmer, and also reject an owned case accessing a
  foreign attachment. Existing immutable farmer/attachment snapshots survive
  detachment. Raw external files and other owners remain outside the reset.
- Native diagnostic start and signal routes reconnect and retry at most once,
  after their transaction has unwound. Their existing client session/event UUIDs
  make complete replay idempotent, including a committed response lost before
  acknowledgement. Authorization is repeated on retry. Active outer transactions
  are never disconnected or silently replayed. No business write route is wrapped.
- A second database failure returns structured `service_unavailable` HTTP 503,
  empty acknowledged events and `Retry-After: 5`. It never reports unsaved events
  as accepted. Persistent Django connections enable native per-request health
  checks; this does not replay financial or workflow transactions.
- The existing diagnostics client honors retry timing for 503 as well as 429,
  retaining its bounded local event queue. The shared script URL advances to v6.
  The UI remains usable while telemetry is delayed.
- The legacy cutover fence permits the existing maintenance-control route through
  to its own authorization checks. Authorized IT can restore global Live mode
  without releasing the legacy upload hold; ordinary writes remain fenced.
- The maintenance selector reads `health.maintenance.mode`, independently of
  overall readiness. Missing document templates can make readiness Down while
  maintenance remains enabled. The shared Portal script URL advances to v136.

These are behavior corrections to `core/static/miniapp/diagnostics.js`,
`core/static/miniapp/portal.js`, `core/templates/miniapp_diagnostics.html` and
`core/templates/base_shell.html`, with real-shell behavior evidence.
There is no appearance redesign, new dependency/schema/model, approved baseline
change or Phase 6 migration. Portal maintenance remains an independent audited
operator control; no automatic unlock is added.

## Evidence

`test-results/diagnostics-media-reset-red.log` reproduced the exact missing-farmer
reset guard and a real PostgreSQL connection close at the query in the supplied
traceback. `test-results/maintenance-cutover-recovery-red.log` reproduced the
maintenance-control route incorrectly returning 503 during a cutover.
`test-results/diagnostics-media-reset-final.log` passed 43 checks:
reset allowed/denied ownership and snapshot retention, existing diagnostics,
native disconnect after a row lock and after inserts, bounded failure without
false acknowledgement, unknown-commit session deduplication, reauthorization,
and allowed/denied maintenance recovery while retaining the cutover hold.

Playwright exercised the actual Admin reset form with a retained media event
and an imported HB case, preserving the other owner's case and audit snapshots.
It also loaded the real Portal shell, physically closed two diagnostic database
connections, observed one 503 and later 200, verified the server backoff and
acknowledgement of the original UUIDs, and interacted with the page during the
outage. The global maintenance record remained enabled during telemetry recovery.
The browser then opened Settings with overall readiness Down, confirmed that
the selector still showed Under maintenance, and explicitly saved Live mode.
The publication pump continued to report the independent legacy cutover hold.
The measured retry delay was 5,127 ms, and no browser script errors occurred.

Artifacts: `test-results/legacy-importer-reset-browser/`,
`test-results/diagnostics-connection-recovery-browser/`, and the combined gallery
`test-results/diagnostics-media-reset/index.html`. Google transport was simulated;
PostgreSQL, signed Telegram access, native Admin and browser requests were real.

No production database, reset, maintenance toggle, Sheet write or deployment
was performed. A live network's exact disconnect cause and cloud throughput
were not established from the supplied traceback.
