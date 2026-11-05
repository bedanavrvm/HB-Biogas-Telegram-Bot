# Compact Portal case notices

User request: collapse the Legacy record and other case-detail warnings to save
space, and clearly label imported historical cases as Legacy.

## Source-bound change

- `portal_farmer_sheet.js` groups legacy source facts, rejected/deferred/withdrawn
  decision context and SLA escalation into one **Case Notices (count)** disclosure,
  collapsed by default. Expanded content retains the original dates, stage,
  reasons, receipts, source rows, historical fields and missing-data explanations.
- A small **Legacy** badge remains beside the case reference even while notices
  are collapsed. It uses the existing committed legacy-import payload, rather
  than guessing origin from incomplete biodata or case age. Native cases receive
  no badge.
- Outstanding legacy continuation uses its own collapsed **Legacy Continuation ·
  Review Required** disclosure, retaining the existing controls and save action.
- TAT timing limitations and unavailable-evidence notices use the same compact
  disclosure. Data Quality remains in its existing counted tab. Active form
  errors and failed case-load feedback remain visible at their point of action.
- `portal.css` adapts the existing Case 360 native details/summary and chevron
  pattern: 36 px summaries, small text, existing surface/border tokens and no new
  dependencies. Browser keyboard expansion and focus indicators remain available.
- `base_shell.html` bumps the affected assets' cache versions. No workflow,
  authorization, stored data, historical evidence or schema changes.

## Browser evidence

Real Django pages, signed Telegram authentication and isolated PostgreSQL were
used with synthetic imported, native and rejected cases. Playwright captured the
original page before edits and both expanded/collapsed results at 1280 px and
390 px. It checked default collapse, keyboard Enter expansion, mobile overflow,
Legacy provenance, timing disclosure, a successful continuation POST and retained
rejection stage/comment. No page script errors occurred.

- [Before/after screenshot gallery](../../../test-results/case-notices-browser/index.html)
- [Journey result](../../../test-results/case-notices-browser/result.json)

No production deployment or live provider write was performed. This is a bounded
adaptation of existing Portal controls; approved baselines, candidate tokens and
the Phase 6 migration hold remain unchanged.
