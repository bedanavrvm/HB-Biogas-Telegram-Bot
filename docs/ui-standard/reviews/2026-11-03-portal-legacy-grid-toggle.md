# Legacy Data: FarmUp table and Cards toggle

User requested AG Grid review like FarmUp, with a Cards/Table toggle. This
bounded Portal change reuses FarmUp's checked-in AG Grid Community 36.1.0
assets, loader, Quartz styling, compact rows and review-state colours. No new
dependency, backend workflow change, approved-baseline update or Phase 6
migration is involved.

Table is the default. The session remembers the chosen layout; no source data
is written to browser storage. Each view uses the existing 50-row server page.
Sorting and column filters apply to that page, while the existing review filter
and previous/next controls operate over the full upload. Displayed-row approval
honours the current grid filters; all-pending approval retains its explicit
whole-upload meaning.

Source facts are read-only columns, with the recorded name, identifiers,
phones, location, workflow proposal, warnings and historical fields exposed.
The pinned row number opens the existing source/history and reconciliation
controls in a native dialog. Only the existing case-link and explanation are
editable in the grid; this does not create a general data-correction route.
Blocked/imported records remain read-only. Both views share one row buffer, so
approvals and reconciliation text survive layout changes, and the existing
selection API saves them during page navigation/import actions.

The controls use the existing compact 32-pixel action pattern. The sticky
progress card and grid use native surface/text variables. The grid font settings
are scoped through AG Grid's generated Quartz wrapper so lazy-loaded vendor
defaults cannot replace the FarmUp density. Row links and checkbox labels have
usable click areas without increasing row height. If grid assets fail to load,
Cards stay available and Table can be retried.

## Actual browser evidence

`test-results/legacy-grid-review/index.html` links the real-shell Playwright
screenshots and observations. The review used isolated PostgreSQL and synthetic
staged uploads; no canonical import, deletion or provider write was performed.
No test suite was added or run.

- Table approvals survived switching to Cards and back. Card/dialog explanations
  and direct AG Grid edits remained identical, saved through pagination, and
  appeared again after reload. The original synthetic review values were restored.
- Native name sorting and column filtering worked. Approve displayed rows saved
  exactly the eleven filtered rows; unrelated rows remained unapproved.
- Blocked rows could not be selected. Imported rows remained read-only and
  paginated to rows 51-100. A 50,000-row staged upload rendered a bounded page
  with about 25 virtualized row elements.
- An aborted grid-script request displayed Cards and a visible recovery message.
  Retrying Table after restoring the asset loaded the actual grid.
- Captures at 320, 390 and 1280 pixels cover both layouts, plus row details,
  warnings, filtered approvals and asset failure. Browser document width stayed
  within each viewport. Captures establish the observed behaviour; physical
  Telegram devices, screen-reader review and production deployment are pending.

Source ratchet entries cover `portal_legacy_import.js`, its scoped CSS, the
legacy partial and cache-version changes in `base_shell.html`. Existing asset
baselines and the original importer review remain retained.
