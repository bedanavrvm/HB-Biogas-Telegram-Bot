# Changelog

## Portal Reports wizard-route reliability - 04-August-2026

- Kept the live Reports controller mounted while moving between the Fields,
  Filters, and Review URLs. Those steps now reuse the already loaded local
  draft immediately instead of waiting for the report catalogue again.
- Bounded Portal route swaps to 20 seconds and show a clear retry instruction
  when a Telegram WebView navigation request stalls.

  Migration note: no schema migration is included. To undo, redeploy the
  prior application commit; report definitions, audit evidence, customer data,
  Sheets, Drive, and workflow state remain unchanged.

## Portal Reports mobile-first workspace - 04-August-2026

- Made the IT-only report builder operate as a phone-first three-step wizard:
  a safe-area-aware sticky action bar keeps Back/Continue/Save reachable, and
  Telegram Back now returns through setup steps before leaving the report.
- Made live charts defer rendering until they are near the visible viewport,
  adapt their height on Telegram viewport changes, use Telegram theme colours,
  and support ordinary touch interaction. Category-heavy bar charts use a
  horizontal layout for readable labels.
- Added compact phone result cards with the first report fields visible and
  remaining selected fields under an explicit More fields disclosure. Wider
  layouts retain the full, fixed-number-column table and XLSX export.

  Migration note: no schema migration is included. To undo, redeploy the
  prior application commit; report definitions, audit evidence, customer data,
  Sheets, Drive, and workflow state remain unchanged.

## Portal Reports recovery and live-rule reliability - 04-August-2026

- Made Reports route loading and live-result execution settle into a visible
  error-and-retry state if the client, network, API, or a stale screen swap
  fails. A single Chart.js rendering problem can no longer block the report
  rows or leave the screen on an indefinite loader.
- Made report filter/operator and ordering changes persist immediately in the
  browser draft. Date filters for Created at and Last updated now compare the
  selected calendar day rather than only midnight, and numeric ordering is
  covered by regression tests.
- Preserved live report availability when an old invalid chart configuration
  exists: the chart is marked for IT review while the approved rows remain
  available.

  Migration note: no schema migration is included. To undo, redeploy the
  prior application commit; report definitions, audit events, customer data,
  Sheets, Drive, and workflow state remain unchanged.

## Portal import source-preserving review - 04-August-2026

- Changed the IT-only FarmUp and SysUp review table to display the retained
  uploaded columns and values in their original order. The table no longer
  injects a number, status, match, cleaning, or other derived review column;
  import/archive state remains outside the source data.

  Migration note: no schema migration is included. To undo, redeploy the
  prior application commit; staged imports, source archives, customer records,
  and workflow state remain unchanged.

## JBL queue loader recovery - 04-August-2026

- Made the JBL Visit Queue load one server-rendered queue fragment instead of
  first fetching and serializing the same queue as JSON, then fetching it
  again as HTML. Queue cards now omit approval and evidence metadata that is
  only needed after opening an individual case, removing the per-card query
  fan-out from list rendering.
- Added latest-request protection so a delayed search/filter response cannot
  overwrite a newer JBL queue request or strand the current list on a loader.
  Timed-out/failed loads continue to show the visible Retry state. Bumped the
  Portal asset versions so Telegram WebViews receive this loader immediately.

  Migration note: no schema migration is included. To undo, redeploy the prior
  application commit; no customer, visit, approval, Sheet, or Drive data is
  changed.

## Portal Reports guided workspace - 03-August-2026

- Reworked the IT-only Portal Reports workspace into a searchable catalogue,
  focused definition detail page, and a three-step route-backed editor:
  approved fields, filters/order, then charts/review. This keeps reports
  readable on phones without changing the controlled reporting catalogue,
  access checks, branch scope, audit events, or report APIs.
- Added browser-session-only editor drafts so an unfinished definition survives
  normal movement between setup pages but is neither saved nor audited until
  the final Save action. A changed server version discards the stale local
  draft rather than overwriting it.
- Made live-result tables keep the opaque `No.` column fixed while horizontally
  scrolling, preventing header and row text from showing through each other.

  Migration note: no schema migration is included. To undo, redeploy the prior
  application commit; saved report definitions, audit evidence, Sheets, Drive,
  and customer/workflow data remain unchanged.

## Portal loader recovery - 03-August-2026

- Made Portal JSON and queue-fragment requests time-bounded. A stalled or
  failed mobile request now resolves to a clear, recoverable error state rather
  than leaving queues, invoices, or payment candidates on a permanent loader.
- Added an in-place Retry action for operational queues and ensured Invoice
  loading is always unlocked after an unexpected request/render failure.
  No workflow, financial, access-control, customer, Sheet, or Drive data
  changed.

  Migration note: no schema migration is included. To undo, redeploy the prior
  application commit; no persisted data is affected.

## Portal Invoice workspace drill-down - 03-August-2026

- Reorganized the Portal Invoice experience into focused nested pages for the
  reconciliation inbox, matched invoices, ignored invoices, uploads, and an
  individual invoice record. The default view now shows only records requiring
  a decision rather than mixing uploads, all statuses, and full audit detail.
- Kept existing invoice parsing, matching, unmatching, ignore/restore, bulk
  review, payment-readiness, Drive-source, and audit-event behaviour intact.
  No financial or customer workflow data changed.

  Migration note: no schema migration is included. To undo, redeploy the
  prior application commit; parsed invoices, upload batches, and audit history
  remain unchanged.

## Portal Reports drill-down - 03-August-2026

- Split the IT-only Portal Reports workspace into ordinary nested pages for
  the catalogue, saved-report detail, editor, and live results. Phone and
  Telegram Back now return through those pages instead of forcing the full
  builder, charts, and table onto one crowded screen.
- Preserved the existing report field catalogue, capability checks, live-run
  audit behaviour, and XLSX export. No customer/workflow data, report schema,
  Sheets, or Drive data changed.

  Migration note: no schema migration is included. To undo, redeploy the
  prior application commit; report definitions and audit evidence remain
  unchanged.

## Portal navigation and layout foundation - 03-August-2026

- Reorganized the Portal navigation into role-aware sidebar groups: Overview,
  My work, Finance & documents, Cases, IT tools, and Account. Staff still see
  only the destinations their existing Portal capabilities allow.
- Reduced the mobile bottom bar to at most four role-relevant destinations;
  the complete authorized navigation remains in the scrollable sidebar.
- Made route navigation canonical for Dashboard cards, case-history drill-down,
  and retained workspace actions. Explicit Portal URLs now take precedence
  over stale local "last screen" state, improving Telegram and phone-back
  behaviour without changing workflow data.
- Added Portal semantic status tokens, a documented overlay stacking scale,
  shared labelled-value tile primitives, and wider reduced-motion coverage.
- Portal route changes now swap only the active screen fragment. The shared
  shell, filters, feedback, and workflow overlays remain mounted, preventing
  duplicate bindings and reducing mobile DOM weight without changing any
  workflow, customer, document, audit, Drive, or Sheets data.

  Migration note: no schema migration is included. To undo, redeploy the
  prior application commit; this does not alter customer, workflow, document,
  audit, Drive, or Sheets data.

## Table readability and numbering — 03-August-2026

- Standardized the staff review, Portal Imports, and Portal Reports data tables so their first column is always **No.** with visible, page-aware row numbering.
- Replaced transparent/inherited frozen-cell backgrounds with opaque Telegram-theme-aware surfaces. Sticky headers and the frozen No. column now remain readable while horizontally scrolling in either theme.

## Controlled Portal reporting workspace — 03-August-2026

- Added an **IT-only Reports** screen in the Portal. IT can create bounded live case reports from a reviewed field catalogue, apply validated filters/order, add constrained bar/doughnut/line charts, preview results, and export an XLSX workbook. No report operation writes customer, workflow, Google Sheets, or Google Drive data.
- Added a read-only relationship-inventory command, `python manage.py inspect_reporting_relationships --json`, to make model relationships visible before a future report source is approved. TAT, SPIN, complaint, raw-message, GPS, media, Drive, and audit payload data remain excluded from this first release.

  Migration note: `core.0099_portal_reporting` is accepted for merge and local/staging validation only. It is **not authorised for production application** until an explicit release approval. To undo a non-production application before use: `python manage.py migrate core 0098_portal_role_separation`. That removes only the report-definition/chart schema; the policy and compliance evidence remain append-only and must not be deleted or silently rewritten.

## Portal operational-role separation and technical break-glass — 03-August-2026

- Portal **Business Administrator** is now labelled **Head of Rural** and is limited to final/payment review, approval delegation, and authorised document sign-off. A new **Operations Administrator** role owns operational credit, orders, invoices, payment preparation, and document regeneration, without JBL visit logging or Head of Rural review authority.
- JBL Officers can view their own submitted JBL visits and the Orders queue, but cannot select cases, preview a batch, or generate a requisition. Credit Analysts can view JBL evidence for credit review without media-upload rights.
- An active Django Superuser is now the requested, auditable technical break-glass override for all Mini App capabilities and Portal branch scopes. This supersedes the earlier changelog statement that a technical Superuser had no Mini App bypass; ordinary Django `is_staff` users remain non-bypass technical-admin users.
- Physical requisition/payment sign-off policy can name both Head of Rural and Operations Administrator through the existing independent maker-checker request process.

  Migration note: `core.0097_document_signoff_approval_roles` and `core.0098_portal_role_separation` are not authorised for production application by this code change. Apply only through an approved release. To undo `0097` before multi-role policy use: `python manage.py migrate core 0096_portal_import_archives`. Do not blindly reverse `0098`; restore the prior matrix through an audited maker-checker request using its recorded before/after evidence.

## Django Superuser Access Grant override - 03-August-2026

- An active Django Superuser can now add, edit, activate, deactivate, or
  remove a staff member's Mini App Access Grants directly from the User admin
  page. Each immediate change remains recorded with before/after evidence,
  an applied access-control request, compliance audit event, policy snapshot,
  and a refreshed access-policy version. This does not grant the technical
  Superuser any Mini App role or bypass maker-checker controls for capability
  matrix, document-signoff, or TAT configuration changes.

  Migration note: no schema migration is included. To undo, redeploy the
  prior application commit; do not delete the direct-override audit evidence.

## Current requisition Drive links - 03-August-2026

- Generating a requisition no longer opens the temporary local Excel download.
  The Portal now waits for the bounded Drive publication attempt and opens only
  the current generated workbook's Drive link. While publication is pending,
  Batches clearly shows **Saving to Drive**; a failed attempt remains retryable
  without presenting an older workbook as the current version.

  Migration note: no schema migration is included. To undo, redeploy the
  prior application commit; generated workbooks already retained in Drive are
  not deleted.

## Portal Imports staging and source archive - 03-August-2026

- An IT-only **Imports** tab stages and reviews FarmUp CSV and SysUp CSV/XLSX
  files through the existing validated parsers. It intentionally has no Portal
  customer-commit control: staging changes no customer, case, order, payment,
  or Sheet record.
- FarmUp and SysUp now always resolve to the single configured **Jawabu
  HomeBiogas** workflow. IT no longer selects a Telegram group in the Mini
  App; a missing, duplicate, or out-of-scope configuration returns a clear
  server-side error before the source is staged.
- Every accepted Portal source retains bounded local archive metadata and makes
  a separate, durable Drive-archive attempt beneath the existing approved
  Shared Drive root, in an `Imports/YYYY/MM-Month/Batch_<id>` path. The Portal
  shows whether that archive is pending, retained, or needs attention without
  exposing a direct Drive URL.

  Migration note: `core.0096_portal_import_archives` has not been applied to
  production by this change. To undo after an explicitly approved migration:
  `python manage.py migrate core 0095_jawabucasecomment`. This reverse never
  deletes customer data, audit evidence, or Drive files.

## Portal final-review queue tabs - 03-August-2026

- Head of Rural Review now uses two direct, touch-sized tabs: **Orders** for
  final decisions before a case can move to Orders, and **Payments** for cases
  captured in pending payment files. The selected tab is retained across queue
  fragment refreshes and sends its server-validated stage with every request.

  Migration note: no schema migration is included. To undo, redeploy the prior
  application commit; this only changes the Portal presentation and queue
  selection control.

## Portal JBL Visit recovery drafts - 03-August-2026

- Unfinished JBL Visit fields now autosave to a private, verified staff draft as
  the officer types and when Telegram hides or closes the WebView. Closing the
  sheet or opening case history no longer clears unfinished work; only a
  successful visit completion clears the draft.
- The form restores the newest secure/server or device-local field copy when
  the case is reopened. LAF/photo file handles cannot be restored by Telegram
  or Android, so the form states clearly that evidence must be selected again.
- Draft reads and writes require the existing `portal.jbl_visit.write`
  capability and the staff member's branch scope. Drafts remain field-only,
  staff-private, revision-protected, and expire through the existing
  `MiniAppDraft` retention policy.

  Migration note: this reuses already-applied `core.0072_miniapp_drafts`; no
  new schema migration is included. To undo, redeploy the prior application
  commit. Existing recovery drafts are disposable and may be deleted through
  their normal seven-day expiry.

## Safer `/sysup` budgets and conditional GPS fallback - 03-August-2026

- The JBL Visit form now hides the GPS-unavailable explanation until location
  capture is unsupported, denied, unavailable, or times out. A restored draft
  shows it only when it contains a prior fallback explanation.
- `/sysup` now has configurable file, staging-row, and per-commit row limits.
  Oversized exports are rejected before expensive matching; approved rows are
  committed in safe chunks, and register publication is reserved for later
  bounded processing rather than calling Google Sheets inside the request.

  Migration note: no schema migration is included. To undo the code change,
  redeploy the prior application commit; no customer data migration is needed.

## Atomic JBL visit completion and Telegram viewport recovery - 03-August-2026

- A single JBL visit submission now carries its own evidence-link revisions
  through to the final visit transition. This removes the false
  "case changed" conflict caused by the submission's own LAF/photo links,
  while retaining rejection of a genuine concurrent case edit.
- Portal sheets now use Telegram's reported viewport height after Android file
  picker return instead of stale `100vh` sizing, preventing the blank native
  canvas below the fixed visit action bar.

  Migration note: no schema migration is included. To undo the code change,
  redeploy the prior application commit; no customer data migration is needed.

## Portal additive case comments - 03-August-2026

- `Additional Comments` is now a Django-owned, oldest-to-newest history of
  new human remarks recorded from the JBL visit onward. Each entry includes
  the Kenya-local timestamp, staff member, and responsible Portal function.
- Existing Sheet-only text is deliberately replaced on the next Django
  publication; it is not treated as canonical history. JBL visit, final
  review, rework, and per-case payment call-up comments are added only when
  the authorised existing workflow action includes non-empty text.
- The Master Data Apps Script warning-protects `Additional Comments` alongside
  `Current Pipeline State` as a backend-owned value.

  Migration note: `core.0095_jawabucasecomment` creates an empty append-only
  comment ledger and does not backfill or rewrite cases, Sheets, or Drive.
  It has not been applied to production by this change. To undo after an
  approved migration: `python manage.py migrate core 0094_alter_jawabuapprovalrecord_decision_and_more`.

## Master Data lifecycle publication - 03-August-2026

- Master Data can now receive Django's backend-owned `Current Pipeline State`
  without replacing the historical JBL visit, Credit, or Head of Rural
  decision columns. It distinguishes JBL reschedules/halts, the 90-day
  reappraisal rule, order/invoice waiting, payment processing, and payment
  finalization.
- Conditional approvals are retired from active Portal decisions. Credit and
  Head of Rural now accept only the supported through/defer/reject outcomes;
  conditional input from cached clients is rejected safely.
- `master_data_script.gs` now resolves its operational columns from row-3
  headers, so a manually inserted business column cannot shift dropdowns,
  formulas, duplicate checks, or formats into the wrong column. Deploy the
  script manually to a copied Sheet before production use.

  Migration note: `core.0094_remove_conditional_jawabu_decisions` changes
  Django choice metadata only; it does not rewrite stored case data. It has
  not been applied to production by this change. To undo after an approved
  migration: `python manage.py migrate core 0093_requisition_publication_retry_key`.

## Portal durable register publication - 31-July-2026

- Portal case changes now commit to Django before any Google Sheet publication.
  The Mini App makes one short, authenticated follow-up attempt per register;
  pending or failed work remains durable and visible instead of holding the
  free Render web worker through a full Sheets/Drive round trip.
- Requisition generation now saves the workbook locally and returns its
  protected download immediately. Drive publication is retried separately and
  exposes pending/failed status on the batch, while the same retry key safely
  replays the committed generation instead of creating a second version.

  Migration note: `core.0093_requisition_publication_retry_key` is code/local
  validation only until a separately approved production release. To undo it
  before dependent production data exists: `python manage.py migrate core
  0092_portal_maintenance_state`.

## Portal Mini App navigation safety - 31-July-2026

- Telegram Back now stays within the Portal. A cold/direct case screen with no
  Portal history returns to an allowed Portal queue instead of sending Android
  back to Telegram and closing the Mini App. Screen changes also clear stale
  Telegram BackButton handlers before registering the current one.
- Requisition previews now refresh the selected cases' server revision
  snapshot before enabling generation. A background queue refresh no longer
  causes a false “case changed while you were working” message; a genuine
  change after the preview remains blocked.

## Batch-only order assignment - 31-July-2026

- Orders can now be assigned only from the selected-cases checkbox panel in
  the Orders queue. Individual case cards no longer expose order number or
  requisition-date fields, and cached clients are safely directed to the
  batch flow without changing a case.
- Payment product is no longer accepted during order assignment. It remains
  controlled by the later system-export import.

## Portal in-app client-media viewer - 31-July-2026

- Signed LAF documents and JBL visit photos now open in a protected Portal
  viewer instead of calling Android's external Chrome/Drive chooser. The
  current Mini App and case remain open; every successful view remains
  access-audited. Older URL-only evidence is clearly labelled as unavailable
  for in-app preview rather than launching an uncontrolled external intent.
- PDFs are converted server-side into bounded, Portal-owned page images before
  display. This avoids Android Telegram WebView's blank PDF canvas and blocked
  Google viewer while keeping the original Drive file, workflow state, and
  access controls unchanged.
- Client media now also offers a separate `Open externally` action for phone
  download controls. It refreshes
  the attachment-scoped external link immediately before launch, while `View
  in app` remains the default context-preserving action.

## Portal queue and final-review usability - 31-July-2026

- Empty Portal queues now use a compact, consistent completion state rather
  than a large plain panel with a text-only `OK` marker. Queue messages explain
  the next expected work in staff language.
- Final Review uses a two-column mobile-friendly field grid where space
  permits. The phone action is a 44px high-contrast control with an enforced
  white phone glyph and `Call` label on Android Telegram WebView, and
  normalizes Kenyan `07...` numbers for the dialler.

## JBL visit evidence foldering - 31-July-2026

- Future signed LAF documents and JBL visit photos now share one permissioned
  `ID_<National ID>` folder inside the relevant
  `Jawabu/JBL Visits/YYYY/MM-Month` path. Human-readable names use `LAF` or
  `PHOTO`, `JBL Visit`, and the client National ID; customer names and
  internal category enums are excluded.
- Existing Drive evidence remains unchanged for audit continuity.

## Authenticated client-media opening - 31-July-2026

- Client-media links are now short-lived, case- and item-scoped links issued
  only after the Portal authorizes the media list. They open correctly through
  Telegram's external browser without dropping Mini App authentication, while
  retaining the staff access event in the audit trail.

## Focused Final Review and client media - 31-July-2026

- Final Review no longer shows unrequested decision-reason or approval-
  condition controls. It retains the operational decision, repayment, and
  after-call inputs only.
- The former LAF-only control is now Client media, showing the signed LAF
  document and JBL visit photo uploaded by field officers as separately
  labelled links.

## Reliable Head of Rural review switching - 31-July-2026

- The Final Review selector now carries its chosen decision/payment lens
  through the JSON request, htmx fragment fallback, and pagination links.
  Selecting payment review can no longer silently render the final-decision
  queue instead.

## Focused Credit decision form - 31-July-2026

- The Portal Credit form now contains only the analyst's operational inputs:
  credit decision, IMAB creation status, and IMAB customer number. The
  unrequested status guide, decision-reason field, and approval-condition
  controls no longer burden staff. Historical approval evidence is retained.

## Internal order-register reliability - 31-July-2026

- Internal order-sheet publication now converts Django `Decimal` values to
  JSON-safe numeric cells at the Google Sheets boundary, so a valid JBL visit
  is not rejected solely because it includes an HBG or JBL deposit amount.

## Atomic JBL visit completion - 31-July-2026

- Portal JBL visits now validate the form, LAF document and JBL visit photo in
  one retry-safe multipart completion request. Cached two-step upload/log
  clients receive an upgrade message instead of creating orphaned evidence.
- New LAF and photo uploads now attach to the canonical case using the same
  case-reference key used during storage. A forward visit missing either
  required multipart category is rejected before any Drive upload begins.
- Portal detail sheets now use the stable layout viewport rather than a
  JavaScript-measured dynamic height, preventing Android's file-picker return
  from leaving a blank area below the JBL visit action bar.
- On return from Android's native file picker, the Mini App now explicitly
  asks Telegram to re-expand its WebView; this fixes the native contracted
  canvas that CSS alone cannot cover.
- FarmUp imports can label an HBG-visited, unvisited case `JBL to Schedule
  Visit`; the conservative backfill command defaults to a dry run and never
  writes to Sheets or Drive.
- Portal queues now show temporary per-filter card positions, while IT has an
  audited read-only maintenance switch. The migration remains pending separate
  production-release approval.

## Mini App settings hub - 31-July-2026

- Portal, TAT, Complaint Cases, and SPIN now present settings as a compact,
  role-aware hub with a read-only account/access summary, dependable workspace
  defaults, and an app release/support section.
- The unimplemented Telegram digest/quiet selector is no longer shown. Existing
  stored preference values remain compatible, while mandatory operational alerts
  remain unaffected.
- Portal health and temporary delegation, and TAT's maker-checker configuration
  cards, remain visible only to their existing authorised roles. Private Portal
  workspace controls remain dormant while the private-workspace rollout is on
  hold.

## Portal workspace hold - 31-July-2026

- Private Portal saved views, pins, recents, and automatic case-open tracking
  are not rendered in the Portal Mini App for any role, including IT. Existing
  backend records and IT-guarded endpoints remain dormant for a future
  approved rollout; no workspace data was deleted.
- `IT` is now a controlled role choice in Portal, Complaint Cases, TAT, and
  SPIN. Django `is_staff` and `is_superuser` remain unrelated to Mini App
  access, and no additional operational write access was granted.

## Access-control bootstrap - 31-July-2026

- The Django Superuser is now the root technical access-policy approver and
  can appoint/revoke independent Access Control Checkers from the user record.
  Appointment/revocation require a reason and create immutable compliance
  evidence; they do not grant Mini App workflow access.
- A sole Superuser may use one explicitly reasoned, audit-labelled bootstrap
  self-approval only while no independent checker or different Superuser
  exists. Once a checker exists, normal maker-checker separation is enforced.

## Release safeguards - 31-July-2026

- Render's reviewed pre-deploy command now fails on any production-readiness
  warning, and the runbook includes a current Portal release-record template
  with explicit cumulative-migration and rollback guidance.
- The existing Django Sentry integration is now privacy-filtered: no request
  body, query string, headers, cookies, user identity, arbitrary context, or
  exception message leaves the application with an error event.

## Workflow integrity - 30-July-2026

- Workflow `ADMIN` has been renamed to `BUSINESS_ADMIN` across Portal, TAT,
  and SPIN. Django technical superusers now require an explicit scoped Mini
  App grant like every other staff member; legacy evidence remains unchanged.

- Portal, Complaint Cases, TAT, and SPIN now each have a personal Settings
  screen for saved workflow defaults, compact cards, and non-critical alert
  intent. Settings are user-owned and do not change workflow access.
- TAT additionally has a role-aware Settings screen: IT proposes target,
  future holiday, and branch/role escalation changes; a different Business Admin
  approves or rejects them. Stage target values are frozen at entry so
  approved future changes do not rewrite an in-flight SLA.
- TAT Settings now resolves the runtime Telegram group configuration to its
  database row before reading pending proposals or escalation rules, avoiding
  a settings-page server error for configured groups.
- TAT compact case cards now visibly hide secondary identifiers and timestamps
  in queues, provide an immediate preview before save, and preserve full
  details inside the opened case.
- TAT corrections are now explicitly update-only and retain one retry key for
  a failed/resubmitted correction. The new-loan form clearly distinguishes a
  separate loan from an existing case and shows exact National ID/phone loan
  context without blocking legitimate repeat loans.
- FarmUp review now requires a reason before an explicit additional unit is
  created. Additional-unit imports bypass the normal duplicate-key update
  fallback, allocate the next linked unit number, and record the reason in
  the case timeline.
- The TAT case screen now keeps technical audit/update rows out of the
  staff-facing interface. Workflow stages remain visible for operations;
  the append-only audit history remains available to authorized audit and
  administration views.
- Portal Settings now saves a staff member's landing screen, first work queue,
  branch lens, review list, compact-card preference, and non-critical alert
  intent. Business Admins additionally see safe document readiness and can
  issue or revoke audited, branch-scoped approval delegation for up to 14 days.
- Portal now has a private workspace: staff can save up to ten validated queue
  views, pin active cases, and return to their ten most recently opened cases.
  Saved views never bypass the holder's current scope; inaccessible or closed
  pins hide immediately, and convenience records are retained only for the
  documented bounded period.

## Reliability hardening - 30-July-2026

- Portal, Complaint Cases, TAT, and SPIN Mini App writes now accept a shared
  retry key while cached legacy clients remain supported until strict mode is
  explicitly enabled. Shared Google Sheets batch writes, Drive uploads, and
  Telegram launcher publishing leave redacted durable operation records and
  use bounded transient retry/circuit protection. Protected `/api/readiness/`
  reads stored status only; `probe_integrations` is manual and configuration-
  only unless an operator supplies `--execute`.

Migration `core.0084_integrationcircuitstate_integrationoperation` has **not**
been applied to production. It adds only local integration-operation/circuit
tables. To undo after an approved migration, export needed operation evidence,
then run:

```powershell
python manage.py migrate core 0083_complianceauditchainstate_complianceauditcheckpoint_and_more
```

This file records notable, user-visible and operational changes. Entries are
added while work is performed; deployment remains a separate, explicitly
approved action.

## Unreleased — 30-July-2026

- Audit & compliance: Portal, Complaint Cases, TAT, SPIN, document sign-off,
  and access-policy actions now project evidence into one append-only,
  hash-chained compliance ledger. Django Admin supports investigation filters,
  controlled CSV/PDF exports, and integrity verification; sensitive media and
  audit-log access/export events are recorded. Daily checkpoints are retained
  locally by an explicit command, while compliance-mailbox delivery remains
  disabled by default. No automatic retention deletion, external email, or
  production deployment is included.

Migration `core.0083_complianceauditchainstate_complianceauditcheckpoint_and_more`
adds the ledger, chain cursor, checkpoints, permissions, and a PostgreSQL
append-only trigger. It has **not** been applied to production by this change.
To undo after an approved migration, export required evidence, then run:

```powershell
python manage.py migrate core 0082_sheet_register_governance
```

- Render build reliability: the application build no longer runs `apt-get` in
  Render's read-only native build environment. The existing WeasyPrint PDF
  preflight remains, so a base-image library problem still fails clearly
  before deployment.

- Django startup and static collection are now quiet in Render builds: access
  catalog queries are deferred until their Admin forms are rendered, and the
  intentional django-unfold overrides of stock Django Admin assets no longer
  produce duplicate-file build noise.

- Sheets/Drive integration governance: Admin-managed publication contracts now
  define per-register header/field ownership, while explicit read-only audits
  record schema drift, row-pointer/value divergence, and media-root sharing
  posture without copying raw customer values. TAT duplicate-row cleanup now
  proves the surviving immutable Case ID after deletion and re-publishes the
  canonical case before it reports success; failed verification or re-publish
  is retained as failed local audit evidence.
  TAT publication contracts now resolve the runtime configuration by immutable
  Telegram group ID, so Mini App updates are not blocked by the in-memory
  `GroupConfig`/database foreign-key boundary.

Migration `core.0082_sheet_register_governance` adds the local contract and
audit evidence schema only. It has **not** been applied to production by this
change. To undo after an approved migration, export required audit evidence,
then run:

```powershell
python manage.py migrate core 0081_jawabuapprovalcondition_jawabuapprovaldelegation_and_more
```

- Portal approval and media integrity: credit, final-review, and payment-review
  decisions are now append-only, reason-coded approval records with 90-day
  validity, condition clearing, material-change invalidation, scoped temporary
  delegation, and a separate per-case payment review. A forward JBL visit now
  needs a LAF, a JBL visit photo, and captured location or a stated
  unavailability reason. New visit media uses a non-PII case storage reference
  and retrievals are auditable. `audit_jawabu_visit_media` reports orphan
  candidates without deleting or relinking Drive files.

Migration `core.0081_jawabuapprovalcondition_jawabuapprovaldelegation_and_more`
adds the approval/delegation/media-audit schema and seeds only
`portal.approval.delegation.authorize` for the current Portal `ADMIN` role. It
has **not** been applied to production by this change. To undo after an
approved migration, first export required approval/delegation/media audit
evidence, then run:

```powershell
python manage.py migrate core 0080_physical_document_signoffs
```

## Unreleased — 29-July-2026

- Documents & finance: generated requisitions and final payment workbooks can
  now retain an authorised, physically signed-and-stamped PDF/JPG/PNG scan
  without overwriting the Excel source. The scan and exact source workbook are
  hash-bound, Drive retries are auditable, and the responsible Portal role is
  maker-checker configurable. E-signatures remain intentionally disabled.

Migration `core.0080_physical_document_signoffs` adds retained payment source
bytes, document sign-off policy, append-only sign-off attempts/events, and the
Admin-only `portal.documents.sign` capability. It has **not** been applied to
production by this change. To undo after an approved migration, export any
sign-off evidence that must be retained, then run:

```powershell
python manage.py migrate core 0079_remove_workflowtatdailymetric_unique_workflow_tat_daily_metric_and_more
```

- Customer History and TAT: Portal and TAT now present a single internal
  chronological history for each case, including operational events, customer
  provenance, documents, decisions, corrections/redactions, accountable
  actors, and related customer units. Official SLA status now uses the shared
  Nairobi business calendar while retaining wall-clock time as context.
  Overdue work gains idempotent in-app escalation tiers and a dry-run daily
  trend snapshot command; no Telegram notifications or automated transitions
  are introduced.

Migrations `core.0078_businesscalendarholiday_and_more` and
`core.0079_remove_workflowtatdailymetric_unique_workflow_tat_daily_metric_and_more`
add the managed holiday calendar, append-only timeline annotations,
escalation accountability, and daily TAT projections with branch/role and
known-staff attribution. They have **not** been applied to production by this
change. To undo after an approved migration, preserve any required audit
evidence, then run:

```powershell
python manage.py migrate core 0077_seed_operational_products
```

- Jawabu data quality: `/sysup` and FarmUp now share governed customer identity
  normalization, retain historical phone observations, flag 7-9 digit ID
  exceptions for review, preserve system-export field provenance, and validate
  system products against one Admin-managed catalog. The Admin dashboard now
  reports active-case data-quality coverage and a dry-run command can audit
  active Jawabu cases or a staged `/sysup` batch without writing data.

Migration: `core.0076_governed_jawabu_data_quality` and
`core.0077_seed_operational_products` are required for governed phone history,
provenance, review evidence, and the product catalog. They have **not** been
applied to production by this change. To undo after an approved migration,
first export any provenance/review evidence that must be retained, then run:

```powershell
python manage.py migrate core 0075_tat_workflow_receipts
```

- Workflow integrity: Jawabu Pipeline and TAT now reject stale Mini App
  updates, record explicit transition metadata, preserve reasoned rework
  routes, and expose safe SLA-escalation dry runs. Payment approval behaviour
  and access-policy assignments are unchanged.

- Mini Apps: added shared touch-friendly controls, consistent status semantics,
  skeleton queue loading, Telegram haptic feedback, and session-only restoration
  of harmless Portal/Complaint queue context.
- FCA, FarmUp/System Export, and SPIN forms: replaced browser-local sensitive
  recovery drafts with short-lived, verified, server-owned field drafts. File
  attachments are intentionally excluded and must be selected at submission.
- Operations: added the shared glossary, ADR process, known-gap register, and
  repository operating standards for approvals, migrations, audit evidence,
  and release safety.

Migration: `core.0072_miniapp_drafts` is required before this recovery feature
works. It has **not** been applied to production by this change. To undo after
an approved migration, confirm drafts are disposable and run:

```powershell
python manage.py migrate core 0071_accesscontrolpolicystate_and_more
```

Migration: `core.0073_workflow_integrity`,
`core.0074_backfill_workflow_integrity`, and
`core.0075_tat_workflow_receipts` are required before workflow revision checks,
transition receipts, and SLA records work. They have **not** been applied to
production by this change. To undo after an approved migration, first export
any new transition/SLA audit evidence that must be retained, then run:

```powershell
python manage.py migrate core 0072_miniapp_drafts
```
