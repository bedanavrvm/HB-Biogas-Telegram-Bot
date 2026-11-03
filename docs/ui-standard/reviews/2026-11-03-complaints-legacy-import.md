# Complaints legacy import

User-authorized dedicated historical workbook importer, 3 November 2026. Reuses
the compact Complaints surfaces/controls, sticky feedback, dialogs and FarmUp's
pinned AG Grid Community assets; default Table plus Cards, 50 rows per page.
No new dependency, candidate tokens, approved baseline or Phase 6 changes.
The user's Stitch styling authority remains in effect.

Telegram Settings opens the dedicated same-origin page in a full-viewport frame
with the existing signed launch kept in parent memory. The native browser's
Workspace tools entry opens the same review page using existing cookie/MFA/CSRF
authority. Back retains the selected workspace. No launch proof or customer
values are persisted to browser storage or put into URLs.

Mapping precedes staging; source/proposed status and dates appear side by side.
Individual approval persists immediately. Table/Cards share saved choices;
blocked rows cannot be approved. The original/proposed dialog exposes retained
unknown columns and notes. Commit cancellation leaves all rows unimported.
Sheet publication is a separate reviewed action naming the configured target.
Sticky feedback reports saved stages, imported/approved/queued totals and errors.
Dark surfaces reuse current Complaints variables. Scoped overflow handling keeps
the progress panel visible while scrolling, including mobile Cards.

Imported case detail shows its legacy origin. History has one clearly labelled
import snapshot with the actual importer/time and separately labelled historical
notes; no old author, closure date or verification is manufactured. Unknown
closure timing remains unknown in detail, reports and register projection.

Source-bound files: new `complaint_legacy/templates/complaint_legacy/app.html`,
`core/static/miniapp/complaint_legacy.{css,js}`; existing Complaints template,
CSS/JS; browser operations workspace/transport, detail and history. Backend
bootstrap adds a capability-filtered menu flag. Existing auth and publication
paths remain the owners of their respective behavior.

Real-shell Playwright: `scripts/test_complaint_legacy_transport.js`, driven by
`complaint_legacy.tests_browser` against actual Django/PostgreSQL. Synthetic
62-case/61-publication workflow includes a blocked source row, replay/reload,
cancelled confirmation, Table/Cards, 320/390/1280 widths, dark mode, native
password/MFA, missing-CSRF and foreign-workspace denial, template download and
imported history. Evidence: `test-results/complaints-legacy-browser/`.
The operator contract and verification commands are in
`docs/runbooks/complaints-legacy-import.md`. No production import/deployment,
live Google write or physical-device acceptance is represented by this review.
