# Complaints browser UI repair, 23 October 2026

This corrects F01-F39 from the [manual UI audit](2026-10-23-complaints-manual-ui-audit.md) in the closed native browser candidate. The six repair passes cover shared controls, queue/detail, forms, attachments, reports, and settings/account/sync. This record describes the local candidate, not a deployed release or human design acceptance.

All before/after images are together in [the screenshot folder](complaints-manual-audit-assets/). Open [the repair comparison index](complaints-manual-audit-assets/repair-index.html) to choose a state, theme and viewport. Original captures retain their names; repaired captures start with `repair-after-`. Intermediate `repair-pass1-` images are explicitly excluded from the final matrix.

## Scope and implementation

Existing ADS components, tokens, navigation and recovery contracts are reused. No dependencies, migrations, workflow roles, write permissions, authentication routes or production switches change. The only backend change adds safe existing record/sync timestamps to the already authorized, bounded recovery projection; raw provider errors are not exposed. Current official usage references and deliberate layout compositions are recorded in [browser/DESIGN.md](../../../browser/DESIGN.md#complaints-manual-audit-corrections-23-october-2026).

The source ratchet records candidate hashes, retaining `migration_authorized: false`. The original audit/provenance and approved baselines remain historical evidence. Relevant business writes retain revision checks, idempotency, uncertain-save recovery and explicit submission.

## Finding disposition

Each finding has an implementation correction. Evidence links below select a representative repaired image; the comparison index supplies both themes and all eleven viewports for every matrix state.

| Finding | Correction | Repaired evidence |
| --- | --- | --- |
| F01 | One working pane below 90rem; facts precede content; attachment columns follow available container width. | [1024px gallery](complaints-manual-audit-assets/repair-after-38-gallery-success-light-1024x768.png) |
| F02 | Numeric calendar days use padding-free ADS Pressable cells with complete labels and selected state. | [320px calendar](complaints-manual-audit-assets/repair-after-40-calendar-light-320x568.png) |
| F03 | Filters retain a draft; invalid dates disable Apply; Cancel retains the applied range. | [Invalid range](complaints-manual-audit-assets/repair-after-39-invalid-dates-light-390x844.png) |
| F04 | ID, copy action, phone, branch, type and timing appear directly below the case heading, before activity. | [Long history](complaints-manual-audit-assets/repair-after-22-long-activity-light-390x844.png) |
| F05 | Concise Save details label; shared footer stacks when measured labels need more room. | [Missing details](complaints-manual-audit-assets/repair-after-25-missing-details-light-390x844.png) |
| F06 | Remove unused middle navigation slot on access and workspace pages. | [Tablet access](complaints-manual-audit-assets/repair-after-access-signin-light-768x1024.png) |
| F07 | Menus reposition during ancestor scrolling and close when their trigger leaves the viewport. | [Repositioned menu](complaints-manual-audit-assets/repair-target-menu-repositioned-390x844.png) |
| F08 | Year text retains partial typing; only a valid completed year updates calendar geometry. | [Calendar](complaints-manual-audit-assets/repair-after-40-calendar-dark-390x844.png) |
| F09 | Validation moves focus/scroll to the first invalid field. | [Invalid Create](complaints-manual-audit-assets/repair-after-05-create-invalid-light-390x844.png) |
| F10 | Required choices have visible markers, required semantics and linked errors. | [Create location](complaints-manual-audit-assets/repair-after-06-create-bottom-light-390x844.png) |
| F11 | Form grids fit the available width and enlarged text rather than forcing two columns. | [Narrow Create](complaints-manual-audit-assets/repair-after-04-create-dark-320x568.png) |
| F12 | Case task dialogs display the complaint reference and customer name before inputs. | [Resolve](complaints-manual-audit-assets/repair-after-20-resolve-light-390x844.png) |
| F13 | County and Constituency remain disabled until their respective parent is chosen, with instructions. | [Create](complaints-manual-audit-assets/repair-after-04-create-light-430x932.png) |
| F14 | Active task dialogs display live offline guidance before their fields. | [Offline Create](complaints-manual-audit-assets/repair-after-31-create-offline-dark-390x844.png) |
| F15 | File selection has inline pending-upload feedback instead of an obstructing success toast. | [Selected file](complaints-manual-audit-assets/repair-after-42-file-selected-light-390x844.png) |
| F16 | Compact page heading/action; settings, refresh and sync move to labelled workspace tools. | [Phone queue](complaints-manual-audit-assets/repair-after-01-queue-light-390x844.png) |
| F17 | Overview shows counts, Turnaround timing metrics, and Open follow-up its open count. | [Turnaround](complaints-manual-audit-assets/repair-after-10-turnaround-light-390x844.png) |
| F18 | One-point charts show complete wrapping values/coverage and a separate View complaints action. | [First response](complaints-manual-audit-assets/repair-after-36-first-response-light-390x844.png) |
| F19 | Mobile results retain reference, customer, status and relevant fields in readable rows; desktop reference stays pinned. | [Phone register](complaints-manual-audit-assets/repair-after-09-report-table-light-390x844.png) |
| F20 | Compact desktop rows; only selected long narrative columns wrap; full short values have tooltips. | [Desktop register](complaints-manual-audit-assets/repair-after-09-report-table-light-1366x768.png) |
| F21 | Explicit prior period, eligible timing denominator, inline missing coverage, Unchanged wording and accurate small deltas. | [Timing metrics](complaints-manual-audit-assets/repair-after-10-turnaround-light-1024x768.png) |
| F22 | Shorter plot geometry, aligned multi-point panels, and compact single-value sections. | [Charts](complaints-manual-audit-assets/repair-after-35-turnaround-charts-light-1366x768.png) |
| F23 | Radial legend swatches match token-backed slice colours. | [Pie legend](complaints-manual-audit-assets/repair-after-41-pie-chart-dark-390x844.png) |
| F24 | Email shows the captured count, period, date basis, branch, type, status, search and selected subset when applicable. | [Email scope](complaints-manual-audit-assets/repair-after-15-email-light-390x844.png) |
| F25 | Email report opens directly into one focused email task with Send report. | [Email task](complaints-manual-audit-assets/repair-after-15-email-dark-390x844.png) |
| F26 | Desktop preferences and schedules sit alongside each other; schedules use a focused editor with timing/scope context. | [Settings](complaints-manual-audit-assets/repair-after-16-settings-light-1366x768.png) |
| F27 | Schedule dirty state compares with its initial values; untouched cancellation closes directly, actual edits retain the discard guard. | [Edited schedule guard](complaints-manual-audit-assets/repair-after-24-schedule-discard-light-390x844.png) |
| F28 | Default status uses a labelled ADS Select with an actual selected value. | [Settings](complaints-manual-audit-assets/repair-after-16-settings-dark-390x844.png) |
| F29 | Add note uses Feedback note; history says Feedback added. | [Add note](complaints-manual-audit-assets/repair-after-19-add-note-light-390x844.png) |
| F30 | Upload/pending/preview states explain the next step; one preview retry, human file types, reference/filename guidance for IT. | [Attachment states](complaints-manual-audit-assets/repair-after-26-gallery-light-390x844.png) |
| F31 | Fit page is the default, controls use available space, metadata follows the document, and Fit width/zoom remain available. | [PDF viewer](complaints-manual-audit-assets/repair-after-28-pdf-preview-light-390x844.png) |
| F32 | Queue uses the working width until a case is selected; no blank companion detail panel. | [Desktop queue](complaints-manual-audit-assets/repair-after-01-queue-light-1366x768.png) |
| F33 | Empty feedback and clear filters sit inside the result area without a tall empty pane. | [Empty queue](complaints-manual-audit-assets/repair-after-29-empty-queue-light-390x844.png) |
| F34 | One persistent read error with Retry; no duplicate read-error toast or tall blank working pane. | [Read failure](complaints-manual-audit-assets/repair-after-30-queue-error-light-390x844.png) |
| F35 | Default dialog width follows the form width; full-width readable footer actions. | [Desktop Create](complaints-manual-audit-assets/repair-after-04-create-light-1366x768.png) |
| F36 | Search complaints is concise; the accessible name retains the searchable fields. | [320px queue](complaints-manual-audit-assets/repair-after-01-queue-light-320x568.png) |
| F37 | Account menu identifies the existing authenticated actor by name. | [Account](complaints-manual-audit-assets/repair-after-21-account-light-390x844.png) |
| F38 | Sync includes record-update/last-sync dates and status-specific recovery guidance; narrow rows stack. | [Sync](complaints-manual-audit-assets/repair-after-18-sync-light-320x568.png) |
| F39 | Open next shows a checked/unchecked icon while retaining checkbox role/state and keyboard operation. | [Resolve preference](complaints-manual-audit-assets/repair-after-20-resolve-dark-390x844.png) |

## Verification

The evidence contains 1,012 matrix screenshots and 184 contact sheets for the 46 states. The matrix uses Chrome 155 through Playwright CLI 1.63.0, sequentially resizing through 320×568, 360×800, 390×844, 430×932, 667×375, 768×1024, 1024×768, 1280×720, 1366×768, 1440×900 and 1920×1080 in light and dark. Original state names and synthetic content are reused. Visual inspection of phone/landscape and representative desktop contact sheets is supplemented by full-size images and recorded geometry; captures alone do not establish design acceptance.

Final image review caught an omitted empty-result message. That branch was corrected and its full 22-image state recaptured; unrelated populated/dialog/report states retain their earlier source binding. `captureRevisions` in the manifest preserves both build/source bindings instead of claiming every image came from the last build. All targeted interaction journeys were repeated on the final build.

Seventeen recorded interaction observations confirm first-invalid-field focus, disabled dependent locations, invalid-range blocking, cancelled-range retention, valid date application, sequential year typing, untouched/edited schedule cancellation, retained schedule text, scrolling menu placement/dismissal, enlarged-text scrolling, facts before history, 227px attachment cards at 1024px, image aspect preservation, PDF page/fit controls, keyboard checkbox state and empty-search recovery. The 320px clear action restored ten queue rows. At 200% text, the dialog remained within its width and its body scrolled. No automatic pass/fail browser assertions were used.

The isolated native host uses a private copy of the existing synthetic SQLite seed, memory-only credential handling, loopback-only network access and synthetic image/three-page-PDF-shaped previews. The queue failure is an injected 503; offline state uses Chrome's network setting. These establish UI behaviour and layout, not PostgreSQL concurrency or Drive/PDF service reliability. No provider publication, report email, operational record mutation or production access was exercised.

Executed static checks: full browser TypeScript and ESLint, production and development operations builds, production shared authentication/restricted-read builds, changed Python syntax/Ruff, UI source ratchet and diff whitespace. Exact build/source/screenshot hashes are retained in [repair-manifest.json](complaints-manual-audit-assets/repair-manifest.json).

**No automated tests were added or run**, as requested. Earlier runbook test results belong to earlier source. Physical devices, screen readers, deployed M1/privacy/support review and human design acceptance remain unverified. The browser channel stays disabled/unmounted in production; no deployment is performed.
