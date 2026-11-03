# Legacy import: saved cases and verified Sheet sync

The user reported repeated `legacy_cutover_maintenance` 503 responses from
`/api/portal/publication/pump/` and imported cases absent from the Sheet.
The changeover guard correctly held normal publication, but the UI showed
database imports without a separate Sheet status or clear next step.

This bounded fix preserves the owner hold, reviewed destination replacement,
case/role scope, existing compact Portal shell, FarmUp table/cards and dialogs.
No candidate tokens, approved baselines, Phase 6 gate or schema changes.

## Behavior

- A compact panel in the existing sticky feedback section shows **verified /
  saved rows synced**, **awaiting sync**, and **not imported**.
- Remaining source rows have an explanation and **Review unimported rows**.
  A Ready filter cannot conceal why full replacement is unavailable.
- A fully imported upload shows **Sync imported rows to Sheet** and explains
  that import saved Django records. The existing exact-destination confirmation
  still precedes any replacement. Cancelling leaves verified sync unchanged.
- Backup, staging, verification, replacement, readback, paused and complete
  states have distinct messages. Verified counts use the upload's confirmed
  readback cursor, never the imported count or permission to publish a case.
- A failed provider step retains a safe error beside the saved checkpoint.
  Reload/resume preserves verified progress. An uncertain remote outcome is not
  labelled a definite per-row failure or success.
- Visible incomplete imports refresh a summary every 15 seconds, without
  downloading review rows or discarding current edits. Manual refresh remains.
- The authenticated shared publication pump returns HTTP 200 with an explicit
  cutover pause and 60-second polling guidance. It performs no remote work while
  an owner is held; other Portal mutation guards remain in effect.

Source-bound UI files: `core/templates/base_shell.html`,
`core/templates/portal/partials/legacy_import.html`,
`core/static/miniapp/portal_legacy_import.js` and its CSS. The shell versions the
updated assets so existing sessions can obtain them after deployment/reload.

## Evidence

The initial signed-HTTP reproduction returned the same 503/unexpected-error
response and had no Sheet status field. Evidence:
`test-results/portal-legacy-sync-red.log`. Focused regression tests cover partial
imports, publication permission versus receipts, 100/151 verified rows during a
readback failure, recovery and pause-without-provider-write.

Real Playwright uses the actual Django shell, signed API and isolated PostgreSQL,
with only the Google transport simulated. The 61-case Eco-conserve workflow
checks 1 imported/60 not imported, 61 imported/0 synced, cancellation, automatic
summary refresh, lost acknowledgement after atomic apply, reload/resume and
61/61 verified. Exactly one replacement occurs; the Master Data counterpart
survives. All observed pump responses were HTTP 200. Captures at 320, 390 and
1280 pixels fit the viewport. Provider delivery to production is not claimed.

Artifacts: `test-results/legacy-importer-automated-browser/observations.json`,
`sync-partial-import.png`, `sync-awaiting-confirmation.png`,
`sync-unconfirmed-acknowledgement.png`, and `complete-{320,390,1280}.png`.
Logs: `test-results/portal-legacy-sync-final-api.log` and
`test-results/portal-legacy-sync-browser.log`.

The scoped PostgreSQL API/navigation/publication run passed 84 tests; both the
real browser journey and independent-worker contention check passed. Django,
migration drift, generated catalogue, UI-source ratchet, route inventory and
syntax checks passed. The additional publication-endpoint class passed 7/8:
its older HB-reader automatic-status assertion still returns 403 instead of
202. Running that test with the unchanged HEAD `portal_publication_attempt`
handler reproduces the failure; this fix does not relax those access rules.
Baseline evidence: `test-results/portal-legacy-sync-existing-reader-baseline.log`.
