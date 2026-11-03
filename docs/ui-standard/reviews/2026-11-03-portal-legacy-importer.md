# Portal Legacy Data import workspace

The subsequent [register and navigation review](2026-11-03-portal-legacy-eco-register.md)
supersedes the Master-only scope below: both reviewed registers are supported
through a dedicated **Legacy changeover → Legacy import** sidebar page.
Deletion and replacement now preserve the other register, including its cases.

The subsequent user-requested [AG Grid and Cards toggle](2026-11-03-portal-legacy-grid-toggle.md)
replaces the cards-only review presentation described below.

User-authorized Master Data-only changeover, completed 3 November 2026. Retains
the existing compact Portal shell, cards, forms, feedback, pagination and
capability-filtered navigation. No candidate design tokens or approved baseline
changes; the Phase 6 migration hold remains unchanged.

The dedicated IT-only Legacy Data menu replaces the All Cases upload block.
The workspace exposes source mapping, durable row approval, warnings, raw facts,
optional identity reconciliation, deletion impact and exact replacement target.
Sticky progress/actions remain visible while reviewing compact row cards.
Completed records remain browsable; closing Telegram pauses processing with a
saved resume point. Confirmation dialogs distinguish database test cleanup from
the later Master Data replacement. Eco-conserve Sheet exclusion is explicit.

Source-bound registry entries cover `portal.js`, `portal_farmer_sheet.js`,
`portal_legacy_import.js`, `portal_legacy_import.css`, `base_shell.html`,
`portal.html` and `partials/legacy_import.html`. The farmer detail retains
historical location fields and invalid original phone numbers with warnings.
All controls reuse existing Portal typography/density. The scoped hidden rule
prevents old shared button styling exposing unavailable actions.

## Evidence and boundaries

The local evidence gallery is
`test-results/portal-legacy-import-2026-11-03/index.html`. All operational rows
committed in this rehearsal were synthetic, in isolated PostgreSQL database
`hb_legacy_cutover_20261102` on loopback port 5543. The reviewed v5 workbook was
also staged through Playwright: 4,077 rows, no blocked rows, 208 warning rows
and zero canonical commits. Warnings preserve original phone values,
chronology/decision conflicts and uncommon references for operator review.
Google transport used a separate SQLite simulation, identified in the gallery.
No test suite was added or run. Playwright drove the actual Django shell,
requests and saved state; readback examined database and simulated sheet values.

- A 5,000-record workflow completed upload, mapping, staging, governed cleanup,
  canonical import, staging replacement and target readback. It retained 5,000
  distinct cases, provenance and publication-ready bindings. A server restart
  after partial commit resumed saved progress. Another owner's case survived.
- The deletion removed 122 prior synthetic cases with disclosed dependencies.
  Real PostgreSQL exposed an HB constraint during deletion; dependency ordering
  was corrected and the confirmed selection resumed.
- Separate 10,000- and 50,000-record staging runs retained checkpoints across
  pause/reload. The 50,000-record run did not exercise full canonical commit or
  Sheet replacement. Timed scale requests peaked at 1.26 seconds locally;
  this is not a production latency guarantee.
- Scoped Portal IT saw the menu; Operations and Origination-only IT were denied.
  Stale revisions, conflicting chunk replay, invalid XLSX, concurrent leases
  and repeat replacement of a completed import were rejected. Identical chunk
  replay retained its saved source.
- Simulated readback found exactly one atomic Master Data replacement, no
  Eco-conserve calls, unchanged Eco sentinel cells and another owner intact.
  Original malformed phone values and historical location facts survived.
- Follow-up 130-record browser rehearsals rejected a changed snapshot, exposed
  the fresh-review recovery action, retained both backup attempts and resumed.
  Simulating a lost acknowledgement after replacement kept the owner held;
  refresh/resume found nested sheet metadata, avoided a second replacement and
  finished readback. Completed-import pagination advanced to rows 51-100.
- Expired leases resumed, and replaying test cleanup after completion was denied.
  Invalid money and excessive field precision blocked cleanup before any hold
  or deletion. The publisher's queue/readback showed held cases excluded,
  zero consumed attempts and eligibility restored after release. This last
  check used the actual service/database boundary, not a provider delivery.
- Final 320/390/1280-pixel captures and follow-up recovery observations are in
  the gallery. Captured viewport fit is not human design acceptance or a
  physical Telegram/device/accessibility review.

The [operator runbook](../../runbooks/portal-legacy-importer.md) records release,
roles, limits, recovery and manual-edit boundaries. Live Google behavior,
production memory headroom, full 50,000-case commit/projection and physical
devices remain unverified. No production data was deleted/imported or deployed.
