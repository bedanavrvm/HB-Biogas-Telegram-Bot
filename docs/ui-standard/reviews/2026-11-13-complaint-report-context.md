# Compact Complaints report context

The requested Mini App change removes the standalone historical timing paragraph
and its five summary lines. Historical chart series, report metrics, filters,
exports and their calculations remain unchanged.

Data origin / timing moves from the third column to just before Resolution
History. Cells show App workflow, App · Estimate, Historical · Estimate, or
Historical · No timing. Detailed provenance remains in the existing tooltip.
The column uses the normal single-line row height and a narrower width.

The shared Complaint Reports column catalogue follows the same default order.
Column IDs and numbering are unchanged, so saved personal layouts remain valid
and retain their explicit order/freezing choices. No preferences are reset.

Reported/resolved table dates now use dd/mm/yyyy, matching the user's standing
date rule. The script cache version advances to 81. No CSS, role, schema,
operational data or browser React workspace changes are included.

## Evidence

The actual Complaints shell ran on loopback with real Django/PostgreSQL, native
signed Telegram identity and a scoped Complaint IT grant. Two synthetic
historical records and one native record exercised include/exclude behavior.
External sockets were denied.

Playwright captures and observations remain ignored under
test-results/complaint-report-density/:

- before-desktop.png shows the former summary and early verbose column.
- after-desktop.png and after-origin-column.png show the removed summary,
  compact provenance cells, unchanged metrics and the column near the end.
- after-mobile-light.png and after-mobile-origin-dark.png cover 390px layouts.
  The native theme callback was exercised through the system-theme event.
- journeys.jsonl records no page exceptions, the penultimate column order,
  dd/mm/yyyy dates and the available provenance tooltip.

Screenshots were visually inspected at desktop 1280px and mobile 390px in light
and dark themes. The first mobile theme experiment changed CSS alone; the final
dark capture uses the actual native theme handler and dark grid class.

The Complaint reporting Playwright suite passes 23 tests. Its new regression
covers missing/estimated historical timing, captured native timing, unchanged
app metrics, column order and date display. An old chart-date assertion was
updated from dd-mm-yy to the already-approved dd/mm/yyyy contract; no image
baseline was changed. JavaScript syntax, Ruff, diff and source-ratchet checks pass.

Production deployment and live verification are not part of this local evidence.
The repository's separate production approval gate still applies. No design
migration or full-standard adoption is claimed.
