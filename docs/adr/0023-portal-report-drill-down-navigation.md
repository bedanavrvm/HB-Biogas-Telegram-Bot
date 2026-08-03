# ADR 0023: Portal Report Drill-Down Navigation

**Status:** Accepted for merge and local/staging validation. Production release
requires the normal named release approval; no schema migration is involved.

## Context

The initial controlled Reports screen rendered the saved-report catalogue,
definition editor, live charts, result table, and export actions in one page.
This was technically functional but overcrowded on mobile and made ordinary
review actions compete with report configuration.

Portal already has route-first htmx navigation, browser-history handling, and
Telegram BackButton integration. The reporting API already enforces the
existing `portal.reports.view` and `portal.reports.manage` capabilities.

## Decision

The Portal uses these Reports drill-down routes:

1. `/portal/s/reports/` — saved report catalogue.
2. `/portal/s/reports/new/` — new report editor.
3. `/portal/s/reports/<report-id>/` — report detail.
4. `/portal/s/reports/<report-id>/edit/` — definition editor.
5. `/portal/s/reports/<report-id>/run/` — live result and charts.

Each route replaces only the active Portal screen root. Back therefore follows
the normal path from results to detail to catalogue, rather than stacking
modals or rendering every report surface together. Report data still comes
only from the existing constrained APIs; the route itself does not create,
run, export, or mutate a report.

## Consequences

- Mobile staff see one report task at a time.
- Existing view/manage capabilities and server-side authorization remain
  unchanged.
- A direct link or Telegram/browser Back can restore the correct report
  sub-screen without retained client-side selection state.
- Running a report remains a live, audited read; revisiting the result route
  intentionally runs the current report again rather than presenting a stale
  customer-data snapshot.

## Alternatives considered

- **More tabs or an accordion inside the original page:** rejected because it
  preserves the same overloaded screen and creates another local navigation
  system.
- **A modal-over-modal report editor/results flow:** rejected because it is
  difficult to recover with Telegram and phone Back controls.
- **A new frontend framework:** rejected; the established Django/htmx/vanilla
  stack already provides route-aware screen replacement safely.

## Migration and rollback

No schema migration is included.

To undo, redeploy the prior application commit. This only changes Portal
presentation and route handling; it does not alter report definitions,
customer data, workflow records, audit evidence, Google Sheets, or Drive.
