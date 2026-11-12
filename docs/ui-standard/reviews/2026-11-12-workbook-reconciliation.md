# External workbook reconciliation in the existing Legacy workspace

The user approved non-destructive reconciliation of the refreshed Master Data and
Eco-conserve workbook. This extends the existing Update Existing Cases table and
row dialog; it does not authorize a design migration or expand workflow grants.

## Source and interaction

Changed portal_legacy_import.js reuses the existing AG Grid, legacy-row-select
checkbox layout, case360-grid controls, row dialog, bulk confirmation and durable
progress pattern. Virtual Current position and Additional Comments to append
columns show the actual proposed update. Current position allows a reviewed
override/keep choice; Rescheduled reveals a dd/mm/yyyy next-visit field.
The base shell advances only this script's cache version.

No new CSS, frontend dependency, persistent model or role is introduced.
Source guidance remains evidence; Final Position is ignored. The new profile
does not expose new-current-case creation as a historical bypass.

## Browser evidence

Local Playwright Chromium exercised the actual /portal/s/legacy/ shell against
Django/PostgreSQL with signed synthetic Telegram identity. External connections
were blocked, and only Google transport was replaced by the in-memory Book
implementation. Native mapping, authorization, selection, transitions, durable
publication/schema checks and Sheet readback ran normally.

Ignored evidence: test-results/reconciliation-review/browser-evidence.jsonl
and desktop/mobile screenshots in the same directory.

Verified:

- Both Decision/Action headers map separately; Final Position does not map.
- Changed-only table exposes proposed position and append-only note differences.
- Rescheduled requires an exact date; the saved dd/mm/yyyy value survives row
  reopen, page refresh and saved-upload resume.
- Three selected synthetic cases apply through the UI: FarmUp Approved becomes
  Credit Analysis, historical family follow-up stays Deferred, and Rescheduled
  retains the exact date. Native intake origins and empty approval actors/times
  remain unchanged.
- Native publication reaches 3/3 verified rows in the substituted provider.
  Reload/resume leaves all case revisions at 2 and exactly three data rows.
- Desktop 1280x900 and mobile 390x844 screenshots were inspected; the mobile
  dialog stays within the viewport at 358px wide. Light and Telegram dark palette
  captures retain readable fields and review controls. No page exceptions occurred.

These checks establish local behavior, not production deployment, live Google
delivery or full UI-standard adoption. Customer production-copy rehearsal
artifacts and backups remain outside the repository.

## Validation boundaries

The 37 focused reconciliation/update tests pass, including explicit scoped IT
allow/deny, identity conflict, original-source retention, stale revision rejection,
linked-order protection, safe replay, provenance and reporting precision.
Eight additional report tests, the Portal recognition projection test and six
Case 360 regression tests pass: 52 tests in the final release run.
Three broader report tests have existing failures: county capitalization,
invalid-selection expectations, and an ungoverned AccessGrant fixture. The first
two were reproduced using unchanged HEAD modules; the third independently fails
in its unchanged permission fixture. They are not counted as passes.

Ruff, JavaScript syntax, migration-drift and UI source-ratchet checks passed.
Production approval remains separate under AGENTS.md.

## Production-copy rehearsal

A fresh read-only production backup was restored into a dedicated loopback-only
PostgreSQL database. The full supplied workbook was staged and compared through
the native importer; only the independently reviewed field selection was applied.
The rehearsal amended 117 cases: 108 current-position changes and 104 comment
additions (overlapping). It retained all 4,302 cases, including all unselected
cases, identities, financial references, original LegacyRows and approval actors/
times. The changed cases retained 112 historical and five FarmUp origins.

All six reviewed newly Approved cases entered Credit Analysis. The explicitly
confirmed family-decision case stayed Deferred. Eighteen changed rows were held;
six current intakes and two identity/unit exceptions remain separate. No
Eco-conserve amendment was selected. Three unnamed source rows remained staged
and unapplied; staging a source row does not create a case.

The latest transition guards were rechecked against the selection, then all 117
apply calls were replayed without changing case/event/comment/publication counts.
Customer-level manifests, before/after review workbook and backup receipts remain
private outside Git. No production deploy, database mutation or Sheet write has
occurred. After approved release, recompare against live case revisions before
applying; the rehearsal is not authority to overwrite intervening app changes.

Operator instructions: [Reviewed workbook reconciliation](../../runbooks/portal-workbook-reconciliation.md).
