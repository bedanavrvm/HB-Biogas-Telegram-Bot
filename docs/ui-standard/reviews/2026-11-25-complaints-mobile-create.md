# Complaints mobile creation - 25/11/2026

The user requested aligned customer suggestions, removal of the copied-biodata
notice, an inline selection-clear icon beside Customer name, and supporting
document buttons that fill the available row.

## Changes and source patterns

- Suggestion buttons retain the existing grid, border, type and wrapping. An
  explicit full-width grid track overrides shared button centring so short and
  wrapped results have the same left inset.
- The name field reuses `label-line` and the shared compact Lucide control. Its
  borderless x has an accessible name and a 44px touch target. It appears only
  for a selected Master Data source; clearing retains entered values and returns
  focus to Customer name.
- The copied-biodata status and standalone Clear Portal selection button are
  removed on selection and draft restoration. Actual source warnings and field
  review notes remain available, including notes beside the name field.
- The existing create-evidence grid gets one full-width parent track. The two
  equal-width camera/file buttons retain their existing handlers and labels.
- Asset versions advance. No workflow, permission, source attribution, backend
  validation or date-formatting rule changes.

## Browser evidence

`core/tests_browser/complaint_create_mobile.spec.js` renders the actual Complaints
Django template and current CSS/JavaScript in Playwright with synthetic API
fixtures. It exercises real DOM events and the browser file chooser; it does not
authenticate against Django or contact production/providers.

Before the fix, all three original checks failed: suggestion text was indented
by 37.39px at 320px, the inline clear control was absent, and evidence actions
ended before their container edge. Before screenshots are retained locally in
`test-results/complaint-create-mobile/before/`.

Four focused scenarios pass after the fix: suggestion alignment at 320/390/768px;
selection clearing, identity edits, draft restoration and form reset; retained
warnings and keyboard clearing; full-width evidence actions and file selection.
Existing HB comment/evidence interaction coverage also passes. The opt-in native
correction journey's selection expectation is updated but that PostgreSQL-backed
journey was not run for this layout fix.

After screenshots are in `test-results/playwright/complaint_create_mobile-*/`:
`suggestions-320.png`, `suggestions-390.png`, `suggestions-768.png`,
`selected-mobile.png` and `evidence-320.png` (plus wider evidence views).
The short/wrapped suggestions, inline x and full-width evidence row were visually
inspected, not inferred only from geometry assertions.

No approved baseline, candidate token, Phase 6 migration, live data, deployment
or physical-device camera acceptance is included.
