# Portal chronology, name search and order numbers - 17/11/2026

## Source-bound change

The user requested seven chronological Portal stages, one active stage timer,
name searches independent of word order, and consistent configured order numbers.
Their selected policy ends the order stage at signed HB handover, and gives an
explicit Settings adjustment precedence over older released numbers.

- `jawabu_case360.py` supplies the seven stage states and timing; reports and TAT
  target settings use those same boundaries. Missing/bad timestamps stay unknown.
  Known historical HB completion closes earlier progress without fabricating
  dates. Rework, approval invalidation, holds and terminal outcomes are respected.
- `portal_farmer_sheet.js` retains the current progress strip and TAT rows and
  renders their server-owned states consistently. Null elapsed values no longer
  become zero counters. Mobile progress labels may use three lines.
- `portal_search.py` is the shared allowlisted name-word predicate. Existing
  identifier matching, filters, permissions and pagination boundaries remain.
- `requisitions/services.py` uses existing adjustment/cancellation evidence to
  resolve reusable numbers. It preserves claims and historical workbooks; no
  migration or destructive retirement/backfill is needed.
- `portal_requisitions.js` reuses the paired field layout, inline status and
  existing Retry controls. Selection resolves the group/partner; late lookup
  responses cannot overwrite a later preview. Settings offers the existing group
  scope when several groups are accessible. The date reuses the fixed-format
  Portal calendar pattern; errors stay outside the number field.
- `core/api/urls.py` places the static options route before the dynamic farmer
  route. The previous order caused an authenticated GET to reach assign-order
  and return 405. Direct-view tests had missed this; the regression uses the
  actual URL and signed Telegram authentication.

The shell increments the affected asset versions. No dependency, permission,
schema or feature-flag change. Existing source patterns are reused. Candidate
foundations and Phase 6 migration remain on hold.

## Browser evidence

Playwright exercised the native Django shell and normal signed Telegram APIs on
isolated PostgreSQL. External sockets were blocked; no production data or
provider was used. The journey checked seven rows, one active stage, three name
permutations and matching Settings-derived options/preview numbers. It also
checked visible `23/11/2026` and the month boundary `01/12/2026` against ISO picker
values. Captures were inspected at 390px and 1280px; the order form retains paired
fields and a full-width mobile preview action. TAT pending/unknown values show a
dash rather than a zero timer. The progress strip and TAT agree on Final Decision.

- [Mobile TAT](portal-ux-options-2026-10-29/assets/portal-chronology-2026-11-17/tat-390.png)
- [Desktop TAT](portal-ux-options-2026-10-29/assets/portal-chronology-2026-11-17/tat-1280.png)
- [Mobile order fields](portal-ux-options-2026-10-29/assets/portal-chronology-2026-11-17/order-390.png)
- [Desktop order fields](portal-ux-options-2026-10-29/assets/portal-chronology-2026-11-17/order-1280.png)

The regression browser suite checks selection, failed lookup and Retry, preserved
selection/date state, source-controlled TAT progress, known/unknown timing,
permissions and existing navigation/media interactions. Optional remote font
imports are removed only in offline fixtures, using the existing helper. Three
stale deferred-page wording assertions now match the current native labels; no
deferred-page behavior was changed.

## Validation boundaries

The focused backend run passed 111 tests on a freshly migrated PostgreSQL test
database. All 88 navigation/review Playwright tests passed. The native API/browser
journey passed without page errors. Selected Ruff checks, the UI source ratchet,
221-route write inventory, 180-file JavaScript syntax check, migration drift and
233-table database catalogue checks passed. Generated catalogue changes describe
code usage only; they do not change database schema.

Focused PostgreSQL tests cover the state projection, holds/rework/expiry,
historical missing timestamps, upstream chronology, unchanged valid decisions,
HB installation order dates, scoped options/preview, settings precedence and
cancellation reuse. A separate two-worker, independent-connection PostgreSQL test
verifies distinct allocated numbers. Report timing parity and batched-query
checks cover the shared projection. External document/Sheet writes are mocked.
The final numbering run passed all 15 operations/concurrency tests, including
an explicitly selected slot that already has a free claim. Run these with the
normal isolated PostgreSQL test settings:

```text
python manage.py test core.tests_portal_chronology requisitions.tests requisitions.tests_operations_api hb_operations.tests
python manage.py test requisitions.tests_number_concurrency
node node_modules/playwright/cli.js test --config=playwright.config.js core/tests_browser/portal_case_navigation.spec.js core/tests_browser/portal_role_remediation.spec.js --workers=1
```

The tracked-artifact audit reports pre-existing hash mismatches and unreviewed
artifacts in unchanged files, including the logo and older UI captures. None of
the four new screenshots is a finding; each is reviewed and hash-pinned under
the existing synthetic-review path policy. No existing image/hash was changed
to silence the audit.

Three broader assertions also failed when run against the unchanged HEAD source:
report county capitalization, rejection of an unknown chart series, and a
withdrawal Sheet-label expectation. These remain separate baseline issues; the
whole backend suite is not claimed as passing. Logs are retained locally under
`test-results/portal-chronology-*`, including the isolated baseline comparison.

No production deployment, live Sheet/Drive delivery, physical Telegram handset or
historical data repair was performed. New merged TAT boundaries need explicit
targets; old split target snapshots are retained. Operator details are in
`docs/runbooks/portal-timing-search-order-numbers.md`.
