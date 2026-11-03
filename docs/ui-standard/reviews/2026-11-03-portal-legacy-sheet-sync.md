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
- An upload with saved cases keeps **Sync imported rows to Sheet** visible;
  it enables after every source row is imported. A separate **saved / source
  rows** count distinguishes a fifty-row page from the whole workbook.
  A fully imported upload explains
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

## Follow-up: hidden sync after fifty imports

The user saw **0 / 50 synced**, fifty saved cases and no sync button. The real
Playwright journey reproduced that symptom with fifty of sixty-one source
rows imported: the button's hidden property followed full-replacement
eligibility. Red evidence: `test-results/portal-legacy-hidden-sync-red.log`.
This reproduces the reported UI symptom locally; the user's exact live
upload, phase and remaining-row count have not been inspected.

The button now remains visible after a canonical import, with its existing
eligibility check controlling whether it is enabled. Its accessible description
names the remaining-row prerequisite and the **Review unimported rows**,
approval and **Import approved rows** actions. A **committing** checkpoint
instead directs the operator to **Resume processing**. Counts show **50 / 61
saved in database** alongside **0 / 50 synced**. Existing compact controls,
layout, confirmations and server-side replacement rules are retained. The
shell script version is incremented; no permission, database, publication
execution or remote replacement policy changes.

The expanded actual-shell Playwright journey covers the visible disabled
action at fifty imports, Pending review's eleven remaining rows, an aborted
advance request, reload/resume of the saved import, enabled sync after all
sixty-one imports, confirmation cancellation and uncertain remote-acknowledgement
recovery. Only Google transport is simulated; signed Django HTTP and the
isolated PostgreSQL database are real. The existing five signed-HTTP sync
checks also verify incomplete replacement is rejected and receipt/recovery
counts remain accurate. Final log:
`test-results/portal-legacy-hidden-sync-final.log`.
All six focused checks passed, including the real browser journey. JavaScript
syntax, Django checks, the 217-route inventory and UI source ratchet also passed.

Captures are in `test-results/legacy-importer-automated-browser/`:
`sync-50-before.png`, `sync-50-imported.png`,
`sync-50-imported-{320,390}.png`, `sync-import-paused.png`,
`sync-awaiting-confirmation.png` and the completion captures. The gallery and
`observations.json` record the journey. No live deployment, production Sheet
write, physical Telegram-device acceptance or human design approval is claimed.
