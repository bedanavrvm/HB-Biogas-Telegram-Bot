# Changelog

## 7 October 2026 - Single-publish guided Origination setup

- Financial terms remain editable until final review. One transaction publishes
  both financial terms and the product profile, with full rollback on failure.
- Setup sections stay navigable; changed settings are review reminders rather
  than confirmation gates. Publication metadata no longer makes terms stale.
- Saves check relevant concurrency dependencies. Existing published terms can
  finish setup or use an editable successor; old Publish terms links go to review.
- No change to application approval/signing safeguards, models or migrations.

## 7 October 2026 - Shared report controls and focused TAT queues

- Portal and TAT report filters include month, quarter, year and date-range
  periods, shared with exports and emailed reports. County options and chart
  buckets consolidate capitalization and approved aliases without rewriting cases.
- Chart menus stay anchored; axes and tooltips identify counts, time, percentages
  and KES. Shared compact controls and email settings reduce layout drift.
- TAT queue search follows the selected role/all-case queue and current access,
  ignores stale responses, and preserves the query when returning from a case.
  Detail phones open the dialler; target-mirror health no longer claims success
  when work is pending and failed retries respect a cooldown.
- Invoice intake validates one invoice per file before Drive upload, allowing
  explicitly numbered continuations of that invoice and retaining upload recovery.
  Payment previews include verified continuation pages within the existing preview
  budget; historical collated files remain restricted to the selected invoice page.
- Document History cards are separated; Portal score details are more compact.
  Complaint national-ID text is centered in its badge, including six-digit IDs.
- Static asset versions refreshed. No migration or production-side action.

## 7 October 2026 - Compact orders, documents and shared phone actions

- Order selection keeps the number and date on one row, with Preview Form
  immediately below on phones and alongside on wider screens.
- Document History uses one compact list with aligned workbook and signed-copy
  actions, small icons and a green storage indicator beside the reference.
- Shared phone links cover displayed contacts in Portal, TAT, Complaints, SPIN
  and Origination, including dynamic phone cells. IDs, masked contacts and
  editable fields are not converted. Calling does not open the parent case.
- Presentation only: no workflow, permission, financial or database changes.

## 7 October 2026 — Invoice record layout

- Invoice actions share the available width evenly, with small icons, readable
  labels and a distinct delete action. Editing no longer removes its icon.
- Customer identity has a clear name/contact hierarchy; linked people appear
  before parsed fields, with readable IDs and wrapping names. Parsed fields
  are grouped into invoice details, amounts and balance checks.
- Empty action rows are omitted for read-only records. This is presentation-only:
  no matching, permissions, financial rules or database changes.

## 7 October 2026 — Direct order preparation

- Selecting approved cases immediately shows the order number, order date and
  Preview Form action. The extra Prepare order button is removed. Clearing the
  selection hides the section; selecting a different partner loads its number.
- Preview and final confirmation remain explicit; selecting cases does not
  allocate an order number or create an order. No migration or policy change.
- Queue filters use the shorter label Oldest cases instead of Needs attention first.

## 7 October 2026 — Compact Portal finance workspaces

- Document History groups metadata and signed-copy actions into compact rows;
  Orders/Payments and partner filtering share one toolbar. Details, retained
  versions and signed-scan replacement open on demand. Storage failures remain
  visible; routine successful storage no longer consumes a separate row.
- Invoice cards group customer and invoice identity, retain review warnings,
  omit empty phone placeholders, and keep selection/action touch targets at 44px.
- Editable payment batches keep Add cases above their members. One paginated
  search includes every authorized case state and explains unavailable cases;
  only payment-ready cases are selectable. Selection and payment mode survive
  searching/paging, and stale responses cannot replace current results.
- The new picker is scoped by payment preparation capability and exact batch
  group. Existing candidate callers keep their legacy response contract. Server
  addition also rejects inactive and previously paid cases instead of relying
  only on the picker to exclude them.
- No schema, financial calculation, approval policy or external-service change.

## 6 October 2026 — Portal signed agreements and consistent previews

- Editable payments retain their case search, including batches started from
  an invoice delivery. Other eligible cases may be added; active/completed
  payment membership and explicit Portal-group ownership remain protected.
- An accepted signed/agreed copy of the exact sent invoice-name letter clears
  the unchanged identity hold. Recording “sent” alone does not. Corrected
  invoices remain follow-ups; financial checks, current review, signed orders
  and payment finality remain mandatory. Original identities are not rewritten.
- Agreements retain private validated scan bytes, checksum, actor and exact
  identity evidence in the payments domain. Changed/revoked or superseded
  corrections cannot reuse that consent. Scoped Portal resets remove owned
  agreements before their protected letter artifacts.
- Needs review and Matched queues and their counts no longer overlap for held
  corrections. Cleared agreements remain visible in correction follow-ups.
- Portal previews share pinch zoom, swipe/page navigation and stale-view
  cleanup. Signed order/payment PDFs render bounded image pages rather than
  relying on a native WebView PDF frame; JPG/PNG scans remain supported.
  Complaints keeps its existing gesture controller without duplication.
- Correction dialogs align their Close/action controls; letter downloads name
  the file and give immediate feedback. The HB Send Reference input is removed.
  Letter previews constrain their tables/header to A4 width. Authorized
  Temporary Approval Cover is visible in Settings.
- Deploy the checked-in `payments.0007_invoicenameagreement` migration with
  these versioned assets. No deployment or live integration was performed.
  Policy and evidence-preserving rollback are in [ADR 0040](docs/adr/0040-signed-invoice-name-agreement.md).

## 6 October 2026 — Portal Operations workspaces

- Selecting cases shows a compact Prepare order action, not an automatic form.
  Proposed HB/ECO numbers are read-only and preview never allocates a number.
- Staff explicitly select an unsigned order for the same group, partner and
  request date to append cases. Every workbook version is retained. The exact
  current accepted signed scan locks the order; old scans cannot sign amendments.
- Confirmed unsigned order/payment cancellation releases cases and the number
  claim without deleting history, rewinding counters or invalidating credit/final
  approvals. The lowest explicitly released number can be reused. Batch UUIDs
  identify documents; ambiguous old number-only links fail safely.
- Invoice matching and new payment preparation require an exact signed current
  order. Historical financial evidence is preserved and has a read-only audit.
- Pending invoice deliveries omit empty/completed workspaces and support
  archive/restore without deleting invoices. Order details, invoice identities,
  Loan/Cash controls and action rows are more compact and consistently aligned.
- SysUp has inline candidate matching and per-field Keep Portal/Use SysUp choices,
  corrections, preserved source data, current scope/revision checks and retry
  protection. Supplemental data does not undo pipeline approvals; mismatched
  reviewed national IDs remain held. LGF stays separate from the JBL sheet deposit.
- Deploy migrations and versioned assets together. Deployment, PostgreSQL
  concurrency and real integration checks still require operator authorization.
  Migration, access-policy repair, legacy audit and exact rollback commands are
  in [ADR 0039](docs/adr/0039-unsigned-finance-workspaces.md).
- Local verification and outstanding broader-suite failures are recorded in
  KNOWN_GAPS.md; no production data or external system was changed.

## 6 October 2026 — Invoice upload confirmation and payment previews

- Invoice uploads await the authoritative response instead of inheriting the
  20-second queue/read timeout. Repeat submissions while uploading are ignored.
  Lost or unreadable responses advise checking Recent uploads; confirmed saves
  are not labelled failed if subsequent rendering fails.
- Payment-delivery invoice previews send the existing Telegram session header
  through Portal's shared API helper. Server authentication, scope checks and
  evidence-access auditing remain unchanged; no credential enters preview URLs.
- Deploy the versioned invoice/payment assets and shell together. No migration,
  setting, dependency, financial-data change or production write is included.
- Actual-module Playwright regressions cover slow success, repeated submission,
  connection loss, malformed responses, explicit rejection, rendering failure,
  bounded ordinary reads, authenticated preview, denial/retry and Back behaviour.
  Validation results and existing unrelated failures are recorded in KNOWN_GAPS.md.

## 6 October 2026 — Portal role views and review workflows

- Officers see read-only Orders; preparation controls remain capability-gated.
  No grant or saved capability policy is changed.
- Credit rejection/deferment no longer requires IMAB creation or approval-only
  product evidence, and never changes an existing system identity. Approval
  still requires IMAB and a customer number.
- Revisit filters current Deferred/Rejected outcomes within the viewer's scope.
  Expired deferrals remain visible; cash/other-partner withdrawals and progressed
  cases do not reappear because of old hold dates.
- Final Review has aligned repayment day/tenor controls, retaining legacy values,
  and an Approved-only READY FOR INSTALLATION & PAYMENT comment shortcut.
  Additional comments are preserved; the shortcut does not change a workflow status.
- Review documents have previous/next controls, a counter, photo swiping and retry.
  Close/Back preserves the review, cancels obsolete downloads and releases previews.
- Home uses a spinner and compact row placeholders; refresh preserves loaded work.
  Compact panel headings, camera captions, fixed Case History ordering and detailed
  street maps use the existing Portal components and providers.
- Credit comments reuse the existing voice workflow. Apply core.0201 and deploy
  the versioned assets together. Reversal: stop new credit dictation, resolve/expire
  outstanding attempts, then run
  `python manage.py migrate core 0200_alter_accesscontrolchangerequest_workflow_and_more`
  before restoring the prior code. The migration changes choices, not stored audio.
- Validation: 113 focused backend tests, 87 browser checks, JavaScript syntax
  and all Node tests pass using isolated/synthetic data. Screenshots inspected.
  Broader baseline failures and live-integration limitations are recorded in KNOWN_GAPS.md.

## 5 October 2026 — Readable report emails and static graphs

- Preserves the approved Jawabu design with larger Segoe UI font fallbacks:
  16px body/tables, 14px labels and 30px figures. Long amounts use wider cards.
- New Portal, TAT and Complaints emails embed up to three offline PNG graphs;
  full HTML breakdowns remain readable with blocked images or rendering failures.
  No unreliable interactive tabs, public links, new dependencies or migration.
- Excel bytes, scoped report facts and frozen retry payloads are unchanged.
  Actual Gmail/Outlook rendering remains an authorized operator check.
- Validation: 77 email-domain tests passed using isolated SQLite and mocked
  delivery; 29 Playwright checks passed. Mobile/desktop screenshots inspected
  for Complaints, TAT and Finance, including blocked images and long amounts.

## 5 October 2026 — Branded report email layout

- Report emails follow the reviewed Jawabu navy/green reference, using the
  existing logo as an inline image, aligned summary tiles and paired breakdowns.
- Mobile figures wrap into two columns; tables stack. Durations and percentages
  use concise labels and readable values without changing the source/export data.
- Retains JBL BOT sender naming, the Excel attachment, scope warnings and exact
  frozen retry payloads. No fake download URL, new dependency or migration.
- 69 email-domain backend tests and 28 browser checks passed; the final
  presentation helpers also passed a focused 7-test rerun. Screenshots inspected
  at 320px and desktop, including large Finance values and TAT durations.
- Local validation uses synthetic reports and mocked delivery; live inbox
  rendering and provider acceptance of the inline logo remain operator checks.

## 5 October 2026 — Compact Portal workspaces and decision reasons

- JBL Visit, Credit and Final Review use separate rejection/deferment reasons.
  Codes stay internal; Other reason requires a comment. Historical reasons and
  payment-review options are preserved, with server validation before visit uploads.
- FarmUp offers paged, read-only original source rows. Visit drafts retain the reason.
- Settings summaries, archive/document actions, invoice comparisons and Case History
  use compact Portal spacing. Routine invoice matching no longer asks for a review
  note; existing protected conflict confirmation still does. Chart grouping is in options.
- No schema migration or new dependency. Deploy the versioned assets together.
  Validation uses synthetic browser fixtures and an isolated SQLite test database;
  production PostgreSQL, live Telegram and external integrations remain unverified.

## 5 October 2026 — Branded report emails and filtered sends

- New report emails provide a JBL management overview with the detailed Excel attached; PDF attachments are removed. Bare sender addresses display as JBL BOT.
- Portal, TAT and Complaints report screens share a compact envelope dialog. Export-authorized users may send their current filtered report to one address without creating a schedule or recipient approval.
- One-off disclosure retains requester/destination evidence, idempotency, current-access checks, suppression and background dispatch. Download exporters remain the source for attachment structure and filtering.
- Apply report_delivery.0004; see report_delivery/README.md for the guarded reversal command. Live PostgreSQL, Gmail/Outlook rendering and provider sending require operator verification; no production emails or migrations are performed here.

## 5 October 2026 — Workflow-owned report email settings

- Portal and TAT Settings, plus a header Settings panel in Complaints, now let IT configure their own report schedules and recipients without Admin navigation.
- Shared delivery retains per-app recipient approvals, complete-grant scope checks, revision conflicts and idempotent background sends. TAT and Complaints adapters reuse their own report sources.
- Migration report_delivery.0003 assigns existing settings to Portal. Sending remains disabled by default; production migrations, PostgreSQL locking and live provider delivery require operator verification. See report_delivery/README.md for reversal precautions.

## Scheduled Portal email reports - 5 October 2026

- Added scoped approved recipients, daily/weekly/monthly/quarterly schedules,
  background Resend delivery, PDF/Excel previews and delivery history in Admin.
- Portal IT Settings can queue active report schedules immediately without
  waiting for email generation or delivery in the app.
- Retries retain exact payloads and provider keys; signed delivery events
  suppress bounced/complained-about destinations. Customer payload retention
  is 30 days and delivery metadata retention is 180 days.
- Sending remains disabled by default. Apply the reviewed new-app migration,
  configure verified-domain secrets/webhooks and provision the email runner
  before enabling it; no live emails or production migrations were performed.

## Activity value comparisons - 2 October 2026

- Portal case and invoice history, payment activity, Complaints history and
  TAT activity share compact old-to-new comparisons from recorded evidence.
- Recorded blanks remain distinct from unavailable historical values; long
  notes and larger changesets expand without duplicating actors or times.
- Payment changes and future Complaint/approval actions retain relevant prior
  facts in their existing audit records. Redactions omit comparisons and files.
- No historical event rewrite, schema migration or live external write is needed.

## Invoice cleanup, compact finance actions and chart controls - 2 October 2026

- Delete removes eligible invoice records; Ignore remains reversible. Payment
  and identity evidence are protected, shared PDFs are retained, and unused
  Drive PDFs have durable cleanup with explicit retry. Local deletion does not
  wait for Drive, and independent deletion audit evidence remains.
- Document history uses aligned preview/download/Drive icons. Payment cards
  and invoice-delivery actions are compact; each delivery invoice can be
  previewed without closing the preparation dialog or losing Cash choices.
- Complaints time-series charts share synchronized Day/Week/Month/Year
  controls. Filled chart bars and segments no longer have unrelated borders;
  line charts retain their series-coloured strokes.
- Synthetic mobile screenshots and PostgreSQL tests cover these changes.
  No schema migration or real external-service mutation is introduced.

## Portal shared controls and complete inbox - 2 October 2026

- Performance, score details, notification inbox and filter headings now reuse
  shared Portal layout rules: right-aligned controls, 44px touch targets and
  20px icons. Legacy screen CSS no longer overrides these components.
- The bell counts distinct authorized tasks and exposes all of them in pages
  of ten. Payment batches and import worklists each count once; overlapping
  grants cannot borrow another grant's branch scope for actions.
- Failed refreshes preserve the inbox, stale responses cannot replace newer
  data, and Escape/Telegram Back close it and restore bell focus. Existing
  Home sync-repair controls remain available.
- Full-shell synthetic browser tests cover six viewport widths, both themes,
  alignment, paging and visual regression baselines. Portal asset versions
  are bumped; no database migration or external service is added.

## Complaint history role colours - 2 October 2026

- HB history badges are red and JBL badges green, with readable light/dark
  theme colours. Unattributed legacy actions show Role unknown rather than Staff;
  actor names remain visible. No historical roles are guessed or rewritten.

## Complaints unified history - 2 October 2026

- Comment now has the same heading structure as Resolve, with voice input and
  independent drafts preserved. Saving feedback still leaves the complaint open.
- Removed the separate HB comments and Resolution History panels. Complaint
  History retains feedback, resolution and reopening notes in one place,
  including legacy resolution notes and authorized read-only register details.
- New history actions retain an immutable JBL/HB affiliation in their existing
  audit event. Older actions without reliable affiliation evidence show Staff;
  changing live access grants does not relabel past actions.
- Removed the redundant officer-source label. Sheet and export comments now
  contain the comment first, followed by the Nairobi timestamp and actor.
  Existing Sheet cells adopt this format on their next successful synchronization.
- No migration, environment setting, or live Google/Telegram write is required.
  Refresh existing Mini App sessions to load the versioned frontend assets.
- Verified: 92 of 94 complaint PostgreSQL tests passed on a fresh synthetic
  database; two stale National ID assertions remain documented in KNOWN_GAPS.
  The browser regression passed at 320/360/390/430px, with inspected mobile,
  dark and desktop screenshots. All nine Node groups, JS syntax and migration
  drift checks passed.

## Portal compact controls and document cleanup - 2-October-2026

- Performance filters and score details use compact, content-sized sheets with
  right-aligned close controls. Notification tasks scroll inside their panel.
  Secondary document actions use distinct preview/Drive icons with accessible labels.
- Queue contact numbers open the dialler without opening the case. Mobile paging
  shows previous/current/next instead of crowding the row. HB status pills share
  the available width; payment Refresh is right-aligned and order totals share a row.
- Document History partner selection now lives in a filter. Order invoice status
  uses actual matched counts rather than a missing upload-log message. Removed
  the two unwanted National ID/FarmUp helper labels without weakening validation.
- Duplicate selection works without first applying a duplicate filter. Bulk cleanup
  retains an original and protects payment/identity-change evidence; skipped items
  have specific explanations. Removal hides the invoice but retains audit evidence;
  existing Drive archival rules do not move a PDF with other active invoice pages.
- Signed-scan replacement requires confirmation, not a note. Previous scans stay
  retained, previews recheck access, and successful replacement does not replay
  installation release or payment completion. Late preview responses are discarded.
- Deploy migration `core.0198_physical_scan_replacement` with the new code, then
  refresh Mini App sessions. No environment variables or external setup changed.
  Do not roll back scan-status support after replacements without reconciling the
  retained superseded scans; never delete their evidence to make rollback fit.
- Verified: 77 focused PostgreSQL tests, 59 browser tests (including 320–430px,
  larger screens and light/dark Performance layouts), nine Node groups and JS syntax.
  Mobile screenshots were inspected. Broader pipeline failures are recorded in
  `KNOWN_GAPS.md`; live Telegram/Drive behavior was not exercised.

## Complaint HB comments - 2-October-2026

- HB staff can save timestamped resolution comments without closing a complaint,
  including voice input. Queue badges show the total comments; officers can read
  them. Comment and Resolve forms have separate drafts.
- Resolution Comments follows Resolution Details in the complaint Sheet and
  export. Insert that column in existing Sheets without replacing existing data.
  Comments publish as a complete canonical history; retry cannot append duplicates.
- Migration 0197 grants the separate comment capability to Complaint HB/IT and
  updates voice choices. Refresh existing sessions after deployment. Rollback:
  `python manage.py migrate core 0196_parsed_invoice_deleted_choices` then restore
  the previous code; existing comment audit records remain stored.

## Portal engineering remediation - 1-October-2026

- Locked integration claims now recheck terminal state, retry deadlines and
  remaining budget. Unique attempt tokens fence late successes/failures and
  publication failure evidence. The execution lease is shared with queue selection.
- New Sheet reservations bind to group/spreadsheet/tab, preserving FIFO inside
  each destination without holding up unrelated Master/Eco work. Changed targets
  supersede the old reservation rather than writing under the wrong FIFO claim.
- Assisted publication exposes its next retry and respects circuit cooldowns.
  Canonical saves remain independent of Google; no cron or hosted worker was added.
- Invoice retries resume retained Drive files and unfinished content hashes.
  New uploads carry a stable Drive recovery marker; ambiguous legacy acceptance
  requires reconciliation rather than an unsafe duplicate upload. Parsed rows,
  events and completion checkpoint are committed together.
- PDF parsing/preview use disposable, time-limited local processes. Delivery
  count/bytes, parser pages, preview pixel allocations and delivery continuation
  have explicit limits and actionable failure messages.
- Payment authorization, queue filtering and counts precede database pagination;
  only ten batches are serialized. Exact stale review digests remain actionable.
- Fixed direct-dependency/domain discovery and the five architecture-gate
  mutations; extended domain lint/coverage and added disposable PostgreSQL CI
  locking/upgrade tests. Pinned the installed psycopg version without upgrading it.
- EQ-06 invoice diagnostic privacy and EQ-11 broad maintainability cleanup were
  explicitly excluded. See the remediation plan for verification and rollout limits.

## Portal audit repairs - 1-October-2026

- Background Sheet coordination no longer counts as a foreground save. Its
  request times out after 20 seconds and releases the browser lease; canonical
  saves and the existing durable queue remain unchanged. No cron was added.
- New payment reviews bind to material payment facts, not the global case
  revision. Real financial/identity changes still require review and supersede
  generated workbooks. Existing historical digests are not migrated or restored.
- Commissioning cannot precede installation, including acknowledged early
  commissioning. Installation is permanently read-only in HB after commissioning.
- Payment comments and HB forms/notes now use shared unsaved-leave protection.
  Saving one comment preserves other unsaved comments; failed HB saves retain
  input and restore the Save button.
- Payment lists have scoped counts, payment-number search, 10-item pagination,
  filter/page-aware Back links and stale-response protection. Expanded case names
  wrap without shrinking the text.
- Corrected final-review queue null handling for legacy approved credit records;
  reconciled outdated test evidence fixtures and compact staff-facing labels.
- No database migration, access-policy change or production external write.

## Portal payment detail density and case context - 21-September-2026

- Rebuilt the payment-detail header and count strip to keep the batch total
  beside the payment identity and remove the separate full-width total tile.
- Payment rows now show the reviewed case context directly: case reference,
  customer national ID and phone, branch, loan officer, invoice, order,
  amount, repayment day, and payment mode. The existing case-detail link,
  approvals, return comments, cash switch and removal controls are unchanged.
- Approved cases remain behind one compact expandable section; redundant
  all-approved copy and a nested summary card were removed.
- Payment preparation now starts directly with search and compact candidate
  filters; repeated introductory copy, result-count chrome and the full-width
  Loan/Cash control were removed in favour of the accessible mode icon toggle.
- No migrations, access-policy changes, or external writes are required.

## Portal FarmUp review and navigation refinement - 21-September-2026

- Reworked the FarmUp review presentation into a compact, table-first mobile
  workspace: one search field, a compact review filter, grouped secondary row
  actions, a concise selected-row summary and a bottom commit dock.
- The current-file/mapping area now uses a small, readable setup strip rather
  than competing with the review table. Mapping, reconciliation, selected-row
  commit, and separate Sheet publication rules are unchanged.
- Reworked the FarmUp landing upload into a compact month, CSV-file and upload
  control group; the full review table now begins sooner on a small phone.
- Updated the Portal header with a compact JBL HomeBiogas brand treatment, a
  stable notification bell and an unobtrusive connection state that stays
  usable on narrow phones.
- No migrations, access-policy changes, or external writes are required.

## HB action, payment and SysUp review simplification - 21-September-2026

- HB Action installation now exposes only Not installed and Installed work.
  Historical Closed records are retained for audit but are hidden from active
  queues and cannot be edited.
- Commissioning search now occupies the released toolbar space when its
  installation-only filter is hidden. Completed payment cases collapse into a
  compact expandable list while pending and returned cases remain actionable.
- SysUp now lets a reviewer commit each selected matched row independently:
  safe nonblank source values update the selected case, missing or invalid
  values preserve existing data, unknown product names no longer block SysUp,
  duplicate source rows show as already current, and raw source rows are
  collapsed below the review grid.
- No migrations, capability changes, or external writes are required. Deploy
  frontend and backend together because the review presentation relies on the
  new server-side safe-update preview.

## Governed credit assessment inside TAT - 18-September-2026

- Added a bounded, revision-controlled credit-assessment workflow linked to a
  TAT case: statement matching, pre-appraisal evidence, manager authorization,
  analyst report/questions, BRO responses, analyst validation, and final Branch
  Manager decision.
- Added idempotent Gmail attachment intake, restricted Drive archival, encrypted
  short-lived statement passcodes, exact evidence hashes, maker-checker guards,
  append-only decisions/events, and a dormant future analysis-engine contract.
- Added a compact mobile TAT detail panel and an optional hard cutover that
  redirects/rejects legacy SPIN UI, API, and WhatsApp-import writes while
  retaining historical SPIN records.
- Requires migration `credit_assessments.0001_initial`, the pinned
  `cryptography` package, the dedicated personal Gmail address and authorized-
  user OAuth JSON, plus the existing service-account-backed media Drive folder.


## Portal order validation, finalization control and workbook download - 14-September-2026

- Order validation guidance survives the safe-message boundary and lists the
  affected customer and missing details in the preview. Template failures direct
  staff to IT while retaining internal exception diagnostics.
- Telegram shows one main Finalize Order action; browser clients retain the
  ordinary button fallback. Failed attempts retain their retry key.
- Workbook downloads use Telegram's native download or the system browser,
  matching the Complaints approach. Expired links direct users to Batches,
  never to regenerate or finalize an existing order.
- No migrations or settings changes; deploy backend and frontend together.
  Actual device downloads remain an operator verification step.

## Portal Case History inspection fix - 14-September-2026

- Opening Case History no longer starts a draft save that blocks its own
  navigation. Background visit, credit and final-review field recovery saves
  may finish during the retained-form detour; actual workflow submissions,
  uploads and ordinary page navigation remain protected.
- Case History and media buttons share aligned heights, margins and padding.
- No migrations or configuration changes. Refresh frontend assets after deploy;
  live Telegram WebView verification remains an operator check.

## JBL Visit guided document capture - 14-September-2026

- Separate Client ID, LAF and Supporting Photos sections. ID has named front/back
  slots; LAF has exactly two page slots, each with camera/gallery and review/retake.
- Server validates image content, corrects orientation and collates ID onto one
  PDF page and LAF into a two-page PDF using existing WeasyPrint. Supporting
  photos remain separate, with their own count and a combined upload budget.
- Forwarding requires all three evidence categories. Half-selected documents
  cannot submit; failed storage leaves the visit unlogged and captures retained.
- No schema or permission-matrix changes. Redeploy frontend and backend together;
  old unstructured LAF upload clients receive an explicit refresh instruction.

## Portal queue actions and case-inspection return - 14-September-2026

- Visit, credit and final-decision cards retain direct work forms. All Cases,
  Submitted Visits and Order Preparation cards inspect complete Case History;
  Order Preparation checkboxes and the main batch action stay separate.
- Case inspection retains the source screen, search, filters, scroll and open
  form in memory. Visible, Telegram and browser Back restore that context.
  Top-level screens still use full page loads. Cold history links use an
  allowlisted return screen; an action deep link is consumed once.
- Selection retains its captured revisions across rendering and inspection,
  shows selections outside the current page/filter, and optionally recovers
  IDs/revisions/date for 30 minutes within the same signed Telegram launch.
- Deferred review shows its reason and due date and offers only existing,
  authorized stage actions before reappraisal is due.
- No migrations, capabilities or external integration writes changed. Live
  Telegram-device validation is required before production release.

## Portal navigation, search, and visit camera refinement - 13-September-2026

- Removed the redundant top stage rail and mobile bottom hubs; the existing
  capability-filtered sidebar is the Portal's screen navigation.
- Standardized Portal search surfaces so the queue field renders one border
  across mobile and Telegram dark mode.
- Moved JBL visit capture into a dedicated camera sheet with multi-shot capture,
  review/retake, permission fallback, and stream cleanup. Selected evidence
  remains local until submission; closing with files now asks for confirmation.
- No workflow rules, authorization, schema, or external integrations changed.

## Portal full-page navigation reliability fix - 13-September-2026

- Switched Portal screen, stage, invoice, dashboard, and detail navigation to
  complete GET page loads after live reports showed that HTMX screen swaps
  could still leave Telegram WebViews on a blank or loading screen. Retained
  HTMX for navigation and in-screen data fragments only.
- Kept Telegram Back within an authorized Portal route, guarded unsaved edits
  and in-flight actions, and opened newly assigned orders in the current
  durable detail sheet. Added mobile browser and template regression coverage.
- No capability, workflow write, or schema changed.

## Portal screen navigation regression fix - 13-September-2026

- Activate Portal controllers from the newly rendered screen during HTMX swaps,
  even before browser history updates; navigation-only fragment refreshes no
  longer restart the current workflow. Restored correct active-state handling
  for four mobile hubs and bumped script cache keys for Telegram WebViews.
- Added browser coverage for an actual hub click and for the HTMX swap/history
  race. No routes, capabilities, workflow writes, or schema changed.

## Portal pipeline UI standardization - 12-September-2026

- Reorganized Portal navigation around the actual loan cycle: Intake, Field
  Visit, Credit, Approval, Fulfilment, and Finance. Mobile navigation now uses
  four stable Home, Pipeline, Cases, and More hubs while every route remains
  guarded by its existing capability.
- Added reusable Mini App workspace tabs, filter sheets/chips, feedback,
  pagination, single-flight action, list-state, and table-zoom primitives. This
  release adopts them in Portal only so TAT and Complaints remain visually
  unchanged until a separately reviewed rollout.
- Standardized Portal card queues on server-backed search, county, branch, and
  ordering filters before ten-record pagination. Search values remain
  memory-only; non-sensitive filters and queue position survive navigation.
- Added 20-200% report-table zoom and lazy loading for the vendored Leaflet map
  runtime. Removed the unused eager Chart.js download from the active Portal
  shell without introducing a CDN dependency.
- Recorded the navigation/component decision in ADR 0032. No workflow state,
  authorization rule, model, or database schema changed.

## Direct Superuser staff lifecycle and visible approvals - 29-August-2026

- Made active-Superuser staff onboarding, access changes, transfers, leave,
  return, and offboarding direct by default. The exact server-derived impact is
  reviewed before current-password confirmation; no checker is required.
- Preserved independent review as an explicit **Send for independent review**
  choice and added **Configuration > Staff approvals (N)** as the clear queue
  where eligible checkers approve or reject those plans.
- Added decision-mode and request-fingerprint evidence to lifecycle plans.
  Identical retries return the original plan/account; changed payloads cannot
  reuse the same request key, and raw passwords are never retained in the plan
  or audit trail.
- Added password-protected Superuser actions to apply or cancel existing pending
  lifecycle plans without waiting for a checker. Existing rows retain their
  original independent-review meaning after migration.

  Migration note: apply `core.0143_direct_superuser_staff_lifecycle`. Before any
  direct-decision rows exist it may be reversed to `0142`; afterward prefer a
  forward policy change so historical decision evidence remains interpretable.

## Superuser user hard deletion with retained audit - 28-August-2026

- Replaced Django's protected-object User deletion dead end with a full-width,
  active-Superuser-only impact preview and hard-delete confirmation. No checker
  is required; self-deletion and removal of the final active Superuser are
  rejected.
- Added immutable deletion batches and deleted-identity manifests. Live access,
  sessions, drafts, locators, and routing recipients are removed; active TAT
  ownership is force-unassigned and resulting coverage gaps are retained in the
  batch result.
- Preserved original compliance-ledger actor IDs and hash bytes through
  unconstrained historical references. Other protected history is retained via
  a disabled evidence tombstone rather than cascading business records.
- Fixed the browser confirmation POST so disabling the submit button for visual
  feedback cannot remove the confirmation marker and silently re-open the
  impact preview instead of deleting the selected accounts.
- Replaced the TAT open-task reverse join used during deletion with an
  existence-based row-lock query. This avoids PostgreSQL's prohibition on
  combining `FOR UPDATE` with outer `DISTINCT` while retaining transactional
  task rerouting.

  Migration note: `core.0142_user_hard_delete_audit` changes only historical
  User-reference constraints and adds the two evidence tables. Before any hard
  deletion has run, reverse with
  `python manage.py migrate core 0141_staff_lifecycle_workspace`. After a hard
  deletion has created orphan historical actor IDs, do not reverse this schema;
  restore an approved pre-deletion backup or ship a reviewed forward repair.

## TAT private-delivery reliability - 24-August-2026

- Fixed private TAT Telegram delivery on PostgreSQL by locking only the task-recipient row instead of applying `FOR UPDATE` across nullable profile and group joins. Due recipients now advance beyond `Pending` and record their delivery attempt.
- Made DM task locators one-shot Mini App navigation state. Back now restores the cached queue with a quiet background reconciliation, and Refresh updates the current view without reloading and refocusing the original DM task.
- Renamed the overlapping queue surfaces to **Assigned to me** for durable responsibility recipients and **Available to my role** for the broader capability-authorized work pool.

## Centralized TAT access and responsibility routing - 22-August-2026

- Added one Superuser workspace showing canonical TAT stage ownership, scoped
  user AccessGrants, role rosters, stage overrides, private-alert health, and
  configuration warnings without merging authorization and task assignment.
- Stage overrides now derive and lock their responsible role from the active
  TAT product configuration. Multi-role users are routed under the exact role
  required by the current stage; routine task delivery always requires a
  matching explicit TAT AccessGrant.
- Hardened routing with deterministic specificity, fail-closed ambiguity,
  recipient deduplication, strictly increasing ranked-backup SLA thresholds,
  safe shared-role/unassigned fallback, and append-only responsibility events.
- Added the canonical administrator/developer guide for multi-role grants,
  routing precedence, governed thresholds, Shadow-to-Hybrid testing,
  troubleshooting, migration, and rollback.
- Fixed responsibility Primary/Backup selectors so scope changes reload every
  exactly eligible multi-role user, explain empty results, and link directly
  to AccessGrant administration. The form now remains contained beside the
  open Unfold sidebar at desktop widths.

  Migration note: `core.0127_tat_responsibility_canonical_routing` adds the
  responsibility-event audit table and deactivates only conflicting or unknown
  legacy stage-specific routes for Admin review. It does not modify access
  grants, cases, Sheets, Drive, or Telegram. Before operational use, review the
  new workspace. To reverse a non-production application:
  `python manage.py migrate core 0126_tatprivatealertconnection_and_more`.

## SPIN and TAT Pilot data isolation - 22-August-2026

- Added independent, Superuser-controlled Pilot/Production modes for SPIN and
  TAT. New records retain an immutable creation-mode/cycle snapshot, while
  Mini Apps visibly identify Pilot data and reject stale writes after a mode
  or cycle change with a reload-safe conflict response.
- Centralized operational visibility so Production data and only the active
  Pilot scope reach live queues, Portal references, dashboards, repairs, SLA
  candidates, escalations, and daily metrics. Closed Pilot records remain
  Admin-visible and read-only.
- Added protected Pilot-cycle rotation and durable, resumable cleanup of closed
  cycles. Cleanup uses non-PII manifests, exact stable Sheet IDs, bottom-up row
  deletion, post-delete verification, row-pointer repair, concurrency locks,
  and formula/layout acknowledgements. Production/current-cycle records and all
  Drive/media objects are hard-excluded.

  Migration note: `core.0125_workflow_pilot_modes` classifies all existing
  SPIN and TAT operational data as Pilot, creates separate protected active
  cycles, and seeds a durable TAT case-number sequence. Applying the migration
  performs no Google Sheet, Drive, or Telegram side effect. Review both Admin
  modes before allowing new operational entries.

## Origination verified packet signing and Africa's Talking OTP - 21-August-2026

- Added revocable self-service and staff-assisted signer sessions for immutable
  Origination document packets. A signer reviews every page, draws or types one
  signature, accepts versioned atomic-packet consent, and verifies one OTP for
  all signature slots assigned to their role.
- Added fail-closed Africa's Talking Sandbox/production configuration, hashed
  OTPs, token/IP/phone throttles, attempt lockouts, informational-only delivery
  receipts, audited session reset/reissue, and Superuser-governed shared-phone
  exceptions. Raw OTPs and signing-link tokens are not stored.
- Added authenticated staff signature capture, governed production stamps, and
  retryable restricted-Drive archival of the exact retained signed PDF bytes and
  hash. The existing watermarked no-OTP simulator remains separate.

  Migration note: `core.0123_origination_verified_signing` adds Origination-only
  signing-session/challenge/throttle records and signed-package archival state.
  It does not dispatch SMS, upload to Drive, alter existing applications, or
  touch another Mini App. Keep `ORIGINATION_ESIGN_ENABLED=False` until Sandbox
  configuration and a controlled deployment test are complete.

## Workflow reliability test-contract repair - 04-August-2026

- Corrected Portal approval delegation so the documented active Django
  Superuser break-glass override is treated as all-branch authority, including
  when delegating an approval gate. The actor remains identified and audited.
- Updated workflow tests to assert the current contracts: immutable migration
  audit evidence may precede test events, invoice reconciliation reserves a
  durable register publication instead of blocking on Google Sheets, and each
  Portal role is offered only its permitted queues and saved views.

  Migration note: no schema migration, data backfill, or external integration
  action is included. To undo, redeploy the prior application commit.

## Portal report and import archival - 04-August-2026

- Added an Archive action to each saved-report card as well as the report
  detail page. Archive is non-destructive: the definition and immutable audit
  history stay retained, while the report leaves the active catalogue.
- Added an IT-only **Archive from Imports** action for staged FarmUp/SysUp
  uploads. It removes only the selected batch from the active Imports list;
  the original source, raw review data, Drive archive status and audit history
  remain retained. It never commits customer records or calls Drive.
- Fixed repeat entry/run of Reports failing with `render is not a function` by
  preventing route-load options from shadowing the Reports renderer.

  Migration note: `core.0100_portal_import_working_list_archival` adds only
  nullable archive metadata and an index; existing batches remain active and
  no backfill or external action runs. To undo a non-production application:
  `python manage.py migrate core 0099_portal_reporting`. Prefer a code rollback
  after production use so retained audit evidence is preserved.

## Portal Reports assisted live chart builder - 04-August-2026

- Reworked chart setup around the operational question: choose an approved
  comparison field, choose the measure, then choose from only chart displays
  that fit that data. Customer identifiers, names, phones, villages, and
  uncontrolled fields cannot become chart dimensions.
- Added a debounced, cancellable, branch-scoped live aggregate preview before
  saving. It returns at most twelve groups and never stores a report, emits a
  reporting audit event, or exposes case rows. Date trends now require an
  explicit Day or Month choice; crowded doughnuts clearly fall back to bars.
- Collapsed multiple chart configurations into compact, one-open-at-a-time
  cards so the active chart has room for its preview on a phone.

  Migration note: no schema migration is included. To undo, redeploy the
  prior application commit; saved reports, audit evidence, customer data,
  Sheets, Drive, and workflow state remain unchanged.

## Portal Reports mobile-density pass - 04-August-2026

- Reduced report-builder chrome on phones: a compact Step n of 3 indicator,
  tappable progress dots, and one editor action bar now replace the bulky
  segmented controls and competing bottom navigation.
- Made report field selection quicker to scan: categories have natural-height
  disclosures and selected counts, search filters the approved catalogue, and
  selected fields appear as removable chips.
- Compacted filters, ordering, and review; the chart editor now hides the
  irrelevant numeric-field selector for case counts and makes chart removal a
  secondary icon action.

  Migration note: no schema migration is included. To undo, redeploy the
  prior application commit; report definitions, audit evidence, customer data,
  Sheets, Drive, and workflow state remain unchanged.

## Portal Reports wizard step activation - 04-August-2026

- Fixed route-backed Filters and Charts/Review steps remaining on their loading
  placeholder: the Portal route signature now distinguishes the report editor
  step and therefore initialises each newly swapped root.

  Migration note: no schema migration is included. To undo, redeploy the
  prior application commit; report definitions, audit evidence, customer data,
  Sheets, Drive, and workflow state remain unchanged.

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
# Report schedule editor recovery - 5 October 2026

- Report manual queuing, scheduled reservation and retry lock only their owned
  row, avoiding PostgreSQL's nullable-authorizer outer-join FOR UPDATE error.

- Fixed Portal email Settings' doubled API prefix and unpacked its actual
  response/error envelope. Browser regression now uses the real API client.
- Complaints header actions stay right-aligned on one row; Settings has a
  compact section divider, aligned fields and equal-width Save/Cancel actions.
- Removed the Group dropdown and replaced free-text Branch with scoped choices.

- Add report tolerates unavailable/restricted WebView crypto helpers, scrolls
  to and focuses the editor, and reports opening failures visibly. Regression
  coverage includes the actual Portal Settings shell with sending disabled.
# Immediate manual email dispatch - 5 October 2026

- Send now starts bounded, post-commit processing for its exact durable delivery
  IDs in Portal, TAT and Complaints; it no longer requires a shell command.
- Settings shows provider acceptance or a safe failure reason and wakes pending
  work on reopening. Unattended recurring schedules still require the runner.
