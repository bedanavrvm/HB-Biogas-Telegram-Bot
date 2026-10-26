# Origination compact numbered cards

22 October 2026. User-requested refinement of the supplied main-page candidate:
use horizontal space, show more cards and match the existing Mini Apps' text
scale. This supersedes only the card-layout portion of
`origination-reference-header.md`. It is not Design Lab Phase 6 approval.

## Source and decisions

- `loan_origination.js`: show `#1`, `#2`, etc. beside the applicant name, using
  the TAT `case-number` pattern. Continue across pages using the canonical
  response's page and page size; reset with the filtered list. These are list
  positions, never new application identifiers. Retain the separate ORG reference.
- `origination_compact.css`: inline ID/phone labels and values on two columns;
  applicant/status above, product/branch/reference/officer metadata in one
  wrapping row. Remove the officer-only footer, extra identifier-label row and
  dividers. Preserve authorized attribution, specific review feedback and both
  missing-value slots. Card padding is 8px/9px; gaps between cards are 7px.
- Use TAT's normal queue type scale: 13px applicant name, 11px identifier values,
  10px metadata/list position and 9px captions/status at the default root size.
  The card font/fallback stack matches TAT and Complaints. The initial typeface
  was already Plus Jakarta Sans; larger values and mixed weights/sizing, not an
  introduced font family, caused the visible drift. Rem equivalents preserve
  text enlargement. Other apps and the application forms are not restyled.
- Retain independent 44px phone targets, keyboard card activation and focus
  outlines. At enlarged text the identifier columns can stack rather than
  squeeze or overlap. No repeated Complete/View application action is restored.
- `app.html`: cache-version updates only. No workflow, role, provider, customer
  identity, document or persistent-model changes.

## Evidence

The real Django Origination shell and its ordered assets are used with
synthetic API/Telegram I/O by `origination_application_forms.spec.js`.
Before-change captures and computed styles are retained under
`test-results/origination-card-density-before`; the ordinary attributed sample
card measured 166.28px high. The new sample measures 98.19px, about 41% shorter.
Long names and review feedback may correctly make a particular card taller.

Ten-item mobile fixtures check 320/360/390/430px in both themes. Five full normal
cards fit in the 844px-high viewport, keeping the existing page header/controls.
Missing identifiers retain aligned slots. The screenshot and `density.json`
record actual card bounds; the test requires at least four fully visible cards
and does not increase the old height allowance to mask a regression.

`card typography matches TAT and Complaint source styles without changing form
scale` builds non-operational CSS probes from each reference template's real
stylesheet order and compares browser-computed fonts. It does not claim those
apps' workflow journeys were exercised. `typography-comparison.json` records
the exact families, sizes and weights. Applicant names, values and metadata
match TAT's role sizes; Complaints uses the same font family but its own larger
title scale. The Origination form input remains 16px/40px and keeps its existing
font family before/after queue navigation. No form-scale migration is implied.

Pagination, refresh, search reset and empty-result numbering are exercised;
existing filter, direct phone, card tap/keyboard, draft and document tests remain
part of the focused regression set. Screenshot pixels are synthetic local
review artifacts, not approved shared visual baselines.

## Reproduce

```powershell
npx playwright test --config=playwright.config.js core/tests_browser/origination_application_forms.spec.js core/tests_browser/origination_phone_identity.spec.js core/tests_browser/origination_queues.spec.js --workers=1 --output=test-results/origination-card-density-verified
npm run check:js
.venv/Scripts/python.exe scripts/check_ui_standard.py
```

Final combined regression: **270 browser checks passed** under
`test-results/origination-review-downloads-verified`, including these card tests,
review/preview/download, phone identity, queue, Complaints, TAT and Portal media
contracts. JavaScript syntax (148 files), Ruff, UI source ratchet and whitespace
checks passed. Related server checks passed: 26 application-copy tests on
isolated SQLite plus six synthetic Portal download metadata/denial tests.

Inspected full ten-item captures include `compact-queue-320-light.png` and
`compact-queue-390-dark.png` under that final run. The earlier 320px dark header
screenshot timeout passed on the focused rerun and in the final combined run;
no baseline or application behaviour was changed to suppress it.

Real Telegram devices, PostgreSQL and production deployment remain unverified.
No live provider calls, external writes, deployment, commit or baseline approval
occurred. Normal code/static deployment is still needed.
