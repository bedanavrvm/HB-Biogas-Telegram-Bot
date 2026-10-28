# TAT Mini App: UI, behavior and screenshot reference

Captured 28 October 2026. This is the Telegram TAT Mini App in `core`, not the dormant React browser workspace. All people, identifiers, amounts, cases, remarks and email addresses in this review are synthetic.

The [screenshot gallery](images/tat/full-ui-2026-10-28/index.html) groups the captures by UI state. The [capture manifest](images/tat/full-ui-2026-10-28/manifest.json) records each state's role, viewport, theme, description and visible controls, including dropdown options. The [state index](TAT_MINIAPP_SCREENSHOT_INDEX.md) links directly to every image. PNGs are local, ignored artifacts under the repository's data-artifact policy; they are not committed application assets.

## Contents

1. [Scope and evidence](#scope-and-evidence)
2. [Roles and access](#roles-and-access)
3. [Launch, shell and navigation](#launch-shell-and-navigation)
4. [Queues, search and filters](#queues-search-and-filters)
5. [Create case](#create-case)
6. [Case detail and timing](#case-detail-and-timing)
7. [Stage controls and outcomes](#stage-controls-and-outcomes)
8. [Corrections, remarks and activity](#corrections-remarks-and-activity)
9. [Tasks and private Telegram alerts](#tasks-and-private-telegram-alerts)
10. [Reports](#reports)
11. [Recognition](#recognition)
12. [Settings, recovery and configuration](#settings-recovery-and-configuration)
13. [Conditional appraisal and signing](#conditional-appraisal-and-signing)
14. [Failure, refresh and accessibility behavior](#failure-refresh-and-accessibility-behavior)
15. [Findings and boundaries](#findings-and-boundaries)
16. [Source map](#source-map)

## Scope and evidence

Playwright drives Chromium against the actual Django-rendered template, checked-in JavaScript/CSS, actual authentication validation and actual TAT endpoints. A fresh, disposable SQLite database was migrated from the checked-in migrations. Synthetic staff have separate owning-workflow grants. A local Telegram host bridge supplies properly test-signed `initData`, theme events and host methods; it does not replace business API responses. The pinned HTMX script is served from the identical-version checked-in vendor asset. Google Fonts are permitted as public GETs.

Each normal capture has light and dark variants at 390 × 844 and 1366 × 900. Additional 320, tablet and wide captures cover selected complex layouts. Full-page images include document content below the fold; section images make long forms and overlays easier to inspect. Scrollable fixed sheets have additional middle/bottom captures; report-grid horizontal ranges expose virtualized columns. Full-page browser capture alone cannot expand those inner scroll containers. Native select menus, date pickers, clipboard permission, operating-system file choosers, phone apps and Telegram's outer chrome are host/browser UI. Their web controls and options are recorded; these screenshots do not certify those native surfaces on physical phones.

**Observed** below means rendered or exercised through Playwright. **Source contract** means established by the owning backend or client implementation; it is not an assertion that an external delivery or every deployment configuration was exercised. Seeded historical/path/state variants are fixtures, not proof that Playwright traversed every prior workflow transition. Interaction results and interrupted/retried capture attempts remain in the manifest.

No application code, production flags, operational data, operational staff permissions or production schema were changed for this documentation. Provider connections from the capture host are blocked. Email, Sheets, Drive, Gmail, SMS and real Telegram delivery are not acceptance-tested by these images. Local fixture changes and native-session/browser-channel deployment are separate concerns.

## Roles and access

Telegram authentication establishes identity; TAT's active staff grants, capabilities, group, branch and product scope establish authority. Roles in Complaints, Portal or Origination grant no TAT authority. These screenshots use the checked-in policy with synthetic grants; an installation's governed matrix can narrow available actions.

| Persona | Default purpose and visible controls |
|---|---|
| BRO | Queue/search, case creation and permitted identity corrections; MPESA submission, BRO response and loan application outcome/final amount; own Recognition and task alerts. |
| Business Admin | Queue/search/create/correct, MPESA verification and disbursement-register processing; authorized settings reviews. UI label is distinct from Django Admin/staff status. |
| Credit Analyst (CA) | Credit-analysis stage and conditional appraisal analysis/validation. |
| Branch Manager (BM) | BM response, valuation/HOCC actions on the applicable frozen path; explicit BM analysis approval when present in the captured product version. |
| Secretary | HOCC scheduling, holding and minutes distribution. |
| Chair | HOCC decision. |
| Loan Approver | Sanctions and register approval. |
| Finance | Final disbursement timestamp. |
| Management | Authorized workload/performance reporting and named Recognition. No implicit case creation or arbitrary stage editing. |
| IT | TAT technical override, reports, stage corrections, direct target/escalation saves and permitted publication recovery. Scope still matters. |
| Active Django Superuser | Explicit technical override; separately governed configuration/Admin destinations. Not an ordinary Business Admin grant. |
| Bound staff without TAT grant | Launch is denied. Signed identity alone does not reveal cases or reports. |

All normal TAT operational roles can view their permitted queues and Recognition. Named people reporting is separately capability controlled. Captures beginning `r-`/`r01`–`r04` show role differences; consult the manifest rather than assuming that a hidden button exists for every persona.

## Launch, shell and navigation

The header contains the Jawabu logo, TAT Tracker title, current staff name/roles, **Work needing attention** bell and **Refresh tracker**. The loading brand appears while bootstrap runs. The header collapses on downward scrolling and returns when scrolling upward, near the top, or when header controls receive focus.

The primary workspace tabs are **Cases**, **TAT Reports** and **Recognition**. Reports and Recognition appear only with their required capabilities. Cases contains **Queue**, **Create** when authorized, and **Settings**. Opening a case replaces the working view with detail; **Back to Queue** returns to the queue. Report links may preselect the report view, branch, product and date range.

Launch accepts group parameters, signed launch context or an assigned-task token. A task launch resolves the task, consumes its launch URL and opens the accessible case/stage. Invalid/expired authentication, an unknown group, an unbound Telegram identity and missing/out-of-group grants return access errors. A form token does not confer staff authority.

Refresh requests fresh queue/task data and reconciles detail where safe. Loading indicators, disabled pending actions and staff-facing notices describe work in progress. Notices have a close control and may disappear automatically; a screenshot is a moment in that lifecycle.

## Queues, search and filters

See [role queue](images/tat/full-ui-2026-10-28/q01-role-queue--it--390--light.png), [filters](images/tat/full-ui-2026-10-28/q04-queue-filter-sheet--it--390--light.png) and [empty result](images/tat/full-ui-2026-10-28/q06-queue-empty--it--390--light.png).

| Element | Behavior and interaction |
|---|---|
| Ready for my role | Shows accessible cases whose current action is assigned to an applicable TAT role. Counter is server supplied. It is not the same as all cases or unread tasks. |
| All cases | Shows accessible cases across roles/statuses. Changing queues has its own saved page position. |
| Search field | Searches name, operational reference, ID, phone, branch or BRO. Input is debounced; a new search resets paging and invalidates older in-flight responses. Clearing it restores the broader queue. Maximum 120 characters. |
| Filters | Opens a modal sheet containing product, branch and status checkbox groups. Multiple selections are allowed; leaving a group empty includes all permitted values. |
| Apply / Reset / close | Apply submits selections and returns to results. Reset clears selected filters. Close/Escape/backdrop dismiss the sheet and restore focus. Checkbox changes remain in the form and can affect the next refresh even without Apply; dismissal is not a rollback. |
| Active filter chips | Name applied filters and provide remove controls. Counts/results change after the authorized server response. |
| Case card | Displays position, customer, reference, product, branch, amount, status, identifiers and next action/update time. Click the case title/card body to open detail. Phone is an independent `tel:` link and invokes the device calling flow. |
| Previous / Next | Server paging; unavailable boundaries are disabled. Result count and current page are announced. |
| Empty state | Explains that no accessible cases match; an empty filter/search result is not an authentication success for unrelated data. |
| Freshness | Shows the age of the last successful refresh and increasingly stale/retry guidance after failures. A failed refresh retains the last successful queue where available. |
| Compact cards | Personal preference shows customer, amount, product, branch and next action, omitting reference, identifiers and timestamps from cards. Reference search still works; detail remains available. |

Queue order is supplied by the backend. There is no arbitrary client-side queue sort menu. Report table sorting is a separate feature.

The template also retains a **Find Case** section with a search field, Search button and result list. Its client handler requires at least two characters, debounces input and supports Enter. The current visible navigation uses integrated queue search; the retained section is not a separate reachable tab. It is documented from source, not shown as an invented live page.

## Create case

See [blank create form](images/tat/full-ui-2026-10-28/c01-create-empty--it--390--light.png), [existing-loan context](images/tat/full-ui-2026-10-28/c03-existing-loan-context--it--390--light.png) and [created case](images/tat/full-ui-2026-10-28/c05-created-detail--it--390--light.png).

| Field/control | Rules and behavior |
|---|---|
| Product | Only available governed TAT products. Selection changes amount guidance and product-specific configuration. Product version and applicable stage plan are frozen on creation. |
| Branch | Allowed governed branch. Backend validates the exact branch/product combination independently of dropdown contents. |
| Client Name | Required; paste-friendly, uppercase normalization on save. |
| National ID | Required, digits only, 1–9 digits. Paste normalization removes formatting. Invalid values receive field validation. |
| Phone | Required valid Kenyan mobile number; normalized by the backend. The displayed phone is callable in queue/detail. |
| BRO | Required selection of an active, canonically identified TAT BRO. A display name alone is not an assignment identifier. Roster loading/failure is explained beside the select. |
| Requested amount | Required monetary amount within the selected version's bounds; browser uses numeric input and whole-KES step. Business minimum KES 5,000; Logbook KES 50,000–700,000; Mjengo KES 10,000–500,000; Micro Asset KES 10,000–300,000 in the built-in catalogue. The selected version remains authoritative. |
| Configured product details | Required evidence, typed custom fields and optional fees appear only when the product configuration supplies them. Required stage evidence can also appear beside the relevant stage control. |
| Existing-loan context | Checking entered ID/phone shows accessible existing loans. It distinguishes opening/correcting an existing case from deliberately creating another loan for the same person. A matching identity is context, not a universal duplicate-loan prohibition. |
| Draft feedback | Local draft/paste helpers and form-close protection support interrupted entry. Sensitive draft retention follows the shared helper's bounded behavior; it is not a server-created case. |
| Create case | Validates fields, disables duplicate pending submission, submits the explicit new-loan intent and opens returned detail. A retained request key makes an ambiguous retry safe. Correction-shaped payloads are rejected by the backend. |

The originally requested amount determines Standard, Standard + Valuation, HOCC or HOCC + Valuation. A later lower final loan amount does not change that frozen route. Configuration changes affect new cases or future stage targets according to the owning service, not historical signed/frozen bytes.

## Case detail and timing

The summary shows customer, operational reference, product, branch, status, requested amount (or final loan amount when recorded), National ID, clickable phone, next action and **Official TAT (wall clock)**. The workflow path is retained in backend evidence even where the summary does not print its name.

Each stage row has its label, responsible role, completion/lock/current indicator, recorded outcome/time, elapsed duration, target and SLA state where available. Completed rows use a check indicator. The current permitted action has an active indicator/control. Successor stages remain locked with a reason. A role restriction and an unmet predecessor are different blockers.

Official elapsed time is server anchored and ticks on the client every second. Active cases/stages continue; terminal case/stage timestamps stop their respective clocks. Server refresh corrects the anchor. Calendar/business-hours reporting is a separate governed presentation option and does not silently replace official wall-clock TAT. Missing targets display unavailable/neutral values rather than an invented SLA pass.

Staff-facing statuses are **Active**, **Stalled**, **Declined** and **Disbursed**. Negative decision/outcome values are normalized into the canonical reporting status; the exact recorded decision remains in history. SLA presentation distinguishes within target, near target, overdue and unavailable. Near-target threshold comes from governed presentation settings.

An unresolved product/configuration binding is read-only until audited reconciliation in TAT Control Center. Historical closed Pilot cycles are read-only. Their data is not silently copied into current work. The current UI's generic read-only banner can mislabel an unresolved binding as a closed Pilot cycle; see findings.

## Stage controls and outcomes

Timestamp stages have **Stamp Approval**. A click records server time after current role, scope, predecessor, revision and data-mode checks. It does not allow the staff member to choose a historical date. IT's separate correction editor does.

| Stage family | Applicable owner | Control and options |
|---|---|---|
| MPESA sent to Admin | BRO | Timestamp stamp. |
| BM analysis approval, when captured in the version | BM | Approved / Declined; independent TAT capability. |
| MPESA verified and sent to CA | Business Admin | Timestamp stamp. |
| Credit analysis sent | CA | Timestamp stamp; conditional appraisal can govern evidence/action availability. |
| BRO response to CA | BRO | Timestamp stamp. |
| BM response to CA | BM | Approved / Declined. |
| Valuation ready | BM | Timestamp stamp on valuation paths. |
| BM HOCC request | BM | Timestamp stamp on HOCC paths. |
| HOCC scheduled / held | Secretary | Separate sequential timestamp stamps. |
| Decision | Chair | Approved / Rejected / Deferred. |
| Minutes shared | Secretary | Yes / No. |
| Sanctions | Loan Approver | Met / Not Met. |
| BRO applied loan on system | BRO | Met / Not Met, final loan amount, explicit **Save outcome**. |
| Disbursement register | Business Admin | 10:00am / 1:00pm / 3:30pm. |
| Register approved | Loan Approver | Approved / Declined. |
| Finance disbursement | Finance | Timestamp stamp; finishes the case when valid. |

The precise stage labels/order come from the case's immutable product snapshot. This table describes supported built-in controls, not a promise that every product displays every stage. The screenshot manifest records the actual dropdown options rendered for each case.

The fresh migrated catalogue retained published versions without BM analysis approval. That step is documented from the current canonical stage catalogue; the capture run did not publish a successor merely to invent an additional live stage.

Most outcome selects submit immediately on change. **BRO applied** is different: select an outcome, enter final amount when Met, then press Save outcome. Missing final amount is blocked before writing; the backend also enforces it. Amount and outcome save together. Declined/Rejected/Deferred/No/Not Met terminal outcomes close the applicable route. Where later stages have not started, the responsible role can still revise the current dropdown; the No-to-Yes minutes journey was exercised. Otherwise, an authorized correction is required to change completed history.

Writes carry workflow revision, mode version and a retained request key. Double taps and ambiguous retries must not create two transitions. Stale writes are rejected for refresh/review. Success reloads authoritative detail, refreshes tasks/queue and reports a saved/stamped result. External notification/Sheet publication is separately tracked; it does not make an uncommitted UI update authoritative.

## Corrections, remarks and activity

**Correct case details** opens an inline form for name, ID, phone, branch and BRO. It preloads saved values, retains the legacy assignment if needed, submits only changes, and does not create another case. Cancel closes it. No changes produces an explanatory message. A saved correction is revision checked and audited.

IT can press **Correct** on a permitted completed stage. Timestamp edits use `datetime-local`, interpreted as Nairobi time, with displayed chronological minimum/maximum bounds. Dropdown corrections use the supported outcome list. Save validates nonempty input, legal bounds and server rules; Cancel returns to detail. Corrections retain history and may enqueue a reporting metric rebuild. They do not rewrite historical Recognition snapshots.

**Add a remark** accepts up to 5,000 characters. Empty text is rejected. Save appends an actor/time/role-attributed comment; it does not overwrite earlier remarks or advance a stage, change workflow revision/timing, create a signature or award an action score. Finished accessible cases can receive remarks where authorized. A failed/ambiguous retry reuses the same comment key; unsaved text is retained until confirmed success.

**Activity** expands/collapses an event list with count, stage/action, recorded change or comment, actor/authority and Nairobi time. Corrections show before/after facts where available. Linked artifacts open separately. Technical duplicate transition receipts are omitted by the owning timeline projection; customer-facing event history is not fabricated by the frontend.

## Tasks and private Telegram alerts

The bell opens **Needs your input** above the workspace. It shows assigned work and unread count, supports Load more, and has a close button. Opening a task rechecks current case access and focuses/highlights the relevant stage. Stale or already-acted links explain their current status rather than granting historical authority. Reading a task is separate from completing its stage. Task load failure exposes Retry.

Settings shows the private-alert connection status. **Connect private alerts** asks the Telegram host for write permission where supported, then checks the backend connection; rejection/unreachable bot does not remove in-app tasks. **Disconnect** changes optional private delivery while mandatory operational/security notices follow their own rules. Real Telegram permission and handset delivery are outside these browser captures.

## Reports

Only authorized reporting roles see **TAT Reports**. **Current Workload** answers what is waiting now; **Period Performance** answers what happened in a completed/selected period. They have different metric bases. Report filters, insights, table and exports share authorized scope; chart aggregates do not authorize named people data on their own.

### Overview, filters and dates

Current Workload summary: Active, Within Target, Near Target, Overdue, Target Unavailable. Period Performance summary: Created/Cases, Finished/Completed Actions, Disbursed, Declined, SLA Met %, Median TAT/Stage Time and P90 TAT/Stage Time. Labels change when a stage-action basis is selected.

Active is a canonical case-status count; SLA cards describe the unfinished report population, including Stalled cases. They should not be interpreted as subdivisions that necessarily sum to the Active card. Workload chart help separately explains its non-overdue Active series.

The filter bar names the focused insight, period and active-filter count. Its modal has Search, Branch, Product, Status and Dates. Dates supports Any time, Month, Quarter, Year and Date range; the selected mode reveals its corresponding month, quarter/year or from/to controls. Dates are presented in Nairobi context. **More options** expands Stage, Role, Target result, Compare by, Measure, Heatmap and Heatmap measure. Some controls are relevant only to the focused insight; guidance explains that relationship.

Target result options: All, Within target, Near target, Overdue, No target. Compare by: Stage, Role, Branch, Product. Measure: Workload, SLA Split, Median/P90 Duration, Percent of Target, SLA Met, Recorded Corrections, Cases per Configured Assignee, subject to report mode. Heatmap pairs: Stage × Branch, Product × Stage, Role × Branch. Heatmap measures: SLA Met, Completed actions, Median Duration, Percent of Target.

Report filters update live: most selects/dates queue a refresh after 140 ms; search uses 350 ms. Done closes the sheet and flushes a pending refresh; Reset restores defaults. Close/Escape restores focus but retains changed values and does not undo an already queued refresh. Filter chips/drill selections can be cleared. Freshness/loading/error states distinguish updating content from retained last-loaded results. Initial report failure exposes Try Again.

### Every supported insight

| Insight | View | Behavior |
|---|---|---|
| Workload over Time | Current | Line/bar history; bucket/series selection drills into applicable cases. |
| Case Stage Progression | Current | Line/bar actual stage duration versus frozen target for one exact case. Multiple matches prompt narrower filters/reference rather than combining unrelated timelines. |
| Current-stage Backlog Age | Current | Bar/doughnut/pie age distribution of current active work. |
| Operational Comparison | Current | Bar/line grouping by stage, role, branch or product with permitted measures; assignment context/warnings explain configured load. |
| Oldest Active Cases | Current | Ranked waiting work; case controls open detail. |
| SLA Compliance over Time | Performance | Line/bar on-time history with exclusions/basis. |
| Median and P90 TAT over Time | Performance | Line/bar duration distribution; P90 is not an average. |
| Stage Performance Against Target | Performance | Bar/line actual/target comparison and explanatory detail. |
| Operational Heatmap | Performance | Authorized cross-dimension cells, selectable where data exists; selection narrows the table and can be cleared. |
| Target Review Signals | IT / technical override | Performance insight identifying recurring delays that merit investigation; it does not alter targets. Ordinary matrix resolution removes it, while IT/Superuser override resolution returns the full capability catalogue. It is separate from Management's standard insight set. |

**Carousel** shows one insight, Previous/Next position controls, keyboard/touch navigation and per-chart graph-type toggles. **List** stacks permitted insights. Display/chart-type preferences are stored locally. Help controls explain the question, scope, interpretation and excluded records. Hovering a canvas point/bar displays a tooltip; clicking supported chart elements changes the drill selection. Empty charts explain absence of samples rather than proving zero elapsed time.

### Table, downloads and email

The authorized AG Grid report table supports allowed sorting, scrolling across identity/stage/target columns, selecting/opening a case, and copying supported cell text. Previous/Next uses server pagination. The grid's zoom/scroll affordance exists because stage columns exceed a phone's width; a page fitting the viewport does not imply that every column is visible simultaneously.

**Download Excel** requests an audited workbook for the selected report scope and available insights. Browser download/native Telegram handoff depends on host capability. **Email report** opens a dialog with the selected report scope, required email address, Cancel/close and Send. It validates the address, disables pending duplicates and reports queued/accepted/delivered/failed/uncertain results according to the delivery service. An accepted provider response is not proof of mailbox delivery. Retry must preserve an ambiguous attempt's identity.

## Recognition

Recognition is informational, not a pay/HR decision. The main screen shows **Your score**, period/status, authorized People/Branches standings, current user's pinned result when applicable, rank, action volume and on-time context. Ordinary staff's view is scoped; named cross-staff visibility requires the separate capability.

**Period** opens a sheet: Month, Quarter or Year reveals the respective month or quarter/year inputs; Show standings applies. **Filter** opens role/product/branch context where there are useful choices. Apply filters narrows the selected work, displays removable chips and a selected-work score/action/share summary. Clear removes contextual selection without altering historical actions.

Opening the personal score shows Score details, action count, on-time rate, personal-best context if available, **Score breakdown** and **How rankings work**. **Stage contributions** opens every counted stage, with stage/role, actions, on-time rate and score. It paginates ten rows when necessary. Back to my result returns to the personal summary; Back to standings returns to the list. Standings also page where necessary.

Live results may change with valid workflow evidence/corrections and can show movement compared with an expiring per-viewer checkpoint. Periods more than 30 days past their end use an immutable, first-authorized-view final snapshot; current grants still govern visible facts. A period with no counted evidence shows an explicit empty state. Unassigned/invalid/no-target evidence is explained in the breakdown rather than silently credited. Remarks never count as completed stage work.

## Settings, recovery and configuration

### Account and personal workspace

Settings displays current canonical staff access and instructions for administrative corrections. **Start on** selects Queue or authorized Create case. **Use compact case cards** affects only the current person's workspace. Save my settings persists to Django; editing another setting does not grant a capability. About & Support shows app release, Pilot/Production data mode and any dispatch attention warning.

### App status and recovery

App status lists unfinished case Sheet, remark Sheet, target Sheet, signature, staff-notification or report-delivery operations that the viewer can see. Each row gives status and saved-work context. Help opens **What to do**, repair steps and a copyable support reference. Refresh checks again; pagination appears for multiple pages. A status-load failure exposes Try again.

Where allowed, Retry sync opens an explicit confirmation dialog; Cancel preserves state. Confirm retries publication of already saved work, not the operational case action. IT authority, current case revision, workflow scope and valid configuration are checked again server-side. Missing/disabled Sheet configuration can show guidance without a retry button. Signature/notification recovery may instead direct an active Superuser to Django Admin. A failed provider attempt does not instruct staff to stamp/sign/create the case again.

### Target and escalation controls

Authorized IT sees a product card for every available product, optional total target and each stage's target in minutes. Inputs accept nonnegative whole minutes; blank total derives from applicable stages. Changes are governed and affect stage entry snapshots, not elapsed historical target facts. Target Sheet status explicitly states that saved app targets remain in use even when the mirror needs repair.

Overdue escalation has threshold percentage (100–1000), recipient (Responsible role, Branch manager, Management), branch (all or a named branch), Add escalation rule and Remove. Save validates the full rule set. A branch-specific rule supplements the global route. These settings do not themselves send the capture user a real alert.

Current IT saves apply directly with audit. Compatibility proposals submitted under earlier policy can remain pending. Authorized Business Admin reviews them with Approve/Reject; IT sees Apply change/Discard and an override confirmation. A different authorized reviewer is required unless an explicit IT/Superuser override applies. Already reviewed or stale proposals cannot overwrite newer configuration. The ordinary current UI does not expose a Business Calendar editor or global presentation editor; those are governed Admin/Control Center destinations, outside this capture scope.

### Email report schedules

Authorized settings includes Email reports, Manage reports/Refresh, existing schedules, Edit/Send and Add report. The editor contains Report name, Report preset, Frequency (daily/weekly/monthly/quarterly/yearly), Time in Nairobi, Branch, Product, approved recipient emails, Active and Skip empty reports. Save requires recipient/scope approval; Cancel discards editing. Send asks confirmation and is disabled when delivery is unconfigured. The saved schedule is not evidence that a provider sent email. Pending deliveries are checked separately; uncertain results warn against sending another copy.

### Pilot and Production

The data-mode switchboard is governed outside the Mini App. A case retains the mode/cycle captured at creation. Production remains operational; only the active Pilot cycle joins normal reads while Pilot is enabled. Returning from Production to Pilot starts a new Pilot cycle; it does not reopen the old one. Rotated/closed Pilot cases are retained read-only. A client with an outdated mode version must refresh before a write. Settings displays mode; it does not offer an ordinary user a mode-change switch. The capture database was reset to its original synthetic cycle between scenarios; that fixture reset is not a supported production procedure.

## Conditional appraisal and signing

The mailbox-backed **Credit assessment** shell is omitted from the HTML when `CREDIT_ASSESSMENT_GMAIL_ENABLED` is false. It is not a hidden tab to activate by styling. An explicitly isolated enabled-fixture phase, where captured, is labeled in the state index; it does not activate the production feature.

The `ca-*` screenshots use that enabled local phase. Historical assessment states were seeded explicitly; Start credit assessment was also exercised through the UI. The PDF viewer and document download use the real authorized document endpoint with a local storage-boundary substitution for one generated synthetic PDF. This verifies the web viewer and delivery of those local bytes, not Drive availability, real statement decryption, Gmail matching or a complete end-to-end appraisal approval. The pending certificate fixture was captured with signing enabled locally; signing was then disabled again to continue baseline stage interactions.

Supported conditional UI, derived from `renderCreditAssessment` and the owning assessment services:

| Assessment state | UI and interaction |
|---|---|
| Not started | Assigned BRO/IT may Start credit assessment at the permitted TAT stage; others see who must start it. |
| Pre-appraisal draft / returned before analysis | Matching forwarded-statement candidates with Use statement. Without a match, explains how to forward the original email and refresh. Once linked, required pre-appraisal PDF and statement passcode; Send for Branch Manager review. |
| Pending authorization | BM decision: authorize analysis for a full-year statement, or return for a full statement for shorter coverage; Decline and comment as applicable. |
| Analysis | Canonical Admin verification remains a normal TAT milestone. At the CA step, required consolidated analysis PDF, optional SPIN/CRB PDFs, one question per line, Send to BRO; Show passcode only when permitted. |
| BRO review / returned to BRO | Analyst questions and required answers, correction notes where present, Submit responses. With no questions: Confirm review. |
| Analyst validation | Each question/response with Accept/Return and correction note; Complete validation. |
| Pending decision | BM Approve / Return to BRO / Decline, required comment and Save decision. |
| Approved / declined | Retained evidence and decision, completed message. |
| Another role's step | Read-only summary names the responsible role. |

The summary can show statement holder, period/coverage, consent reference, forwarding/receipt/link timing and retained documents. Preview opens an in-app document sheet with PDF iframe, close, Done and Download. Download asks permission and preserves the original protected PDF; preview is rendered separately for mobile. Buttons disable while requests run; close revokes local object URLs. Uploads and decisions retain revision checks. Passcodes are shown only through a temporary native alert, not copied into persistent UI.

Approval-certificate status can appear under applicable stages when signing is configured. Pending required certificates can block the successor. Telegram/phone signing journeys and provider delivery are outside this Mini App-only screenshot scope; the default-off capture baseline does not establish working signature dispatch.

## Failure, refresh and accessibility behavior

The client contextualizes errors with the attempted action and support reference where supplied. It distinguishes field validation, permission/authentication denial, stale revision/mode conflicts, connection failures, provider publication failures and empty results. A success response from a write is authoritative even if its follow-up read fails; background refresh reconciles the retained detail.

Thirty-second visible refresh checks queue/tasks and open detail. Counters tick every second; freshness and Recognition revision checks run separately. Hidden documents suspend visible polling and resume reconciliation when visible. Dirty case-correction, create/settings forms and unsaved remarks are protected from unsafe background replacement; pending snapshots apply once safe. The stage-correction exception observed in this review is listed below.

Controls have labels, selected-state attributes, status announcements and keyboard-accessible buttons. Sheets/dialogs supply titles, modal state, close controls, Escape/backdrop handling where implemented and focus return. Native required/type/range validation coexists with staff-facing messages. Keyboard checks and viewport captures are evidence of those specific interactions, not a screen-reader or WCAG certification. Dark mode follows the Telegram theme and refreshes chart/grid visuals; it is not a separate Mini App preference switch.

## Findings and boundaries

The final capture coverage, observed defects, unsupported combinations and verification summary are recorded below after the browser run. Do not interpret image count as proof of functional correctness.

### Observed defects and important interaction details

| Finding | Evidence and practical effect |
|---|---|
| Reporting-role App status fails | [IT App status failure](images/tat/full-ui-2026-10-28/s02-recovery-section--it--390--light.png). Real endpoint returns 500. `tat_tracker_recovery_status` passes runtime `GroupConfig` into `tat_recovery.status_payload`; `report_delivery.recovery.recovery_rows` reads `group.pk`, which that object lacks. This blocks the whole status list for reporting-capable actors. Ordinary BRO recovery help was captured separately and works. It is not a SQLite-only error. |
| Unsaved inline stage edit can disappear after a case correction | [Before refresh](images/tat/full-ui-2026-10-28/f11-stage-edit-before-refresh--it--390--light.png), [after refresh](images/tat/full-ui-2026-10-28/f12-stage-edit-after-refresh--it--390--light.png). Reproduction: save a name correction, open a completed timestamp's Correct editor, change its seconds without Save, wait for the periodic detail refresh. The editor and unsaved value disappear. A run before saving case details retained the editor; the manifest distinguishes the two scenarios. The safe-render guard checks the case correction form and remarks, but does not include the inline stage editor. |
| Read-only reason can be misleading | [Unresolved binding](images/tat/full-ui-2026-10-28/d10-unresolved-read-only--it--390--light.png). An unresolved configuration binding renders the generic Closed Pilot cycle message even though reconciliation, rather than a closed cycle, is the blocker. |
| Initial reverse-tab navigation can escape the queue filter modal | [Focus escape](images/tat/full-ui-2026-10-28/k02-sheet-focus-escape--bro--390--light.png). On opening, focus is on `queueFilterSheet`; Shift+Tab can move outside it. The trap handles first/last controls but not reverse-tab from the initially focused sheet container. Escape still closes the sheet. |
| Queue filter dismissal does not undo selections | Checkbox state is the next request's filter source. Closing the sheet does not reset it; the next manual/periodic refresh can apply a selection that never received Apply. The reference describes this actual behavior rather than promising Cancel semantics. |
| Report filters update while the sheet is open | Changes are debounced and applied live. Done closes/flushes; close does not undo them. This differs from a staged Apply/Cancel form and matters when comparing screenshots or exports. |
| Private tasks depend on notification mode | The initial group-mode inbox was empty. The explicitly declared shadow-mode phase generated real task rows and exposed unread, load-more and task-focus interactions without real private delivery. Empty baseline tasks were not treated as a rendering failure. |

### Verification boundaries

Playwright exercised real creation, timestamp stamps, final amount/outcome saving, case correction, append-only remarks, negative outcome/revision, personal preferences, target/escalation saves, schedule saving/editing, rejecting a stale proposal, task paging/opening, report pagination/sorting, graph changes/drills, Excel export, appraisal start/preview and failure recovery. Historical/conditional states are clearly identified as seeded. No new unit tests were written as evidence for this task.

The Excel workbook was fetched through the actual authorized download URL and inspected as a workbook artifact. Document preview used locally generated synthetic PDF bytes. Network failure captures deliberately abort a request or take the browser offline; successful business responses are not replaced with hand-written JSON.

Not exercised as operational acceptance: physical Telegram/iOS/Android chrome, OS picker/calling/permission UI, screen readers, live email/Gmail/Sheets/Drive/SMS/signature providers, PostgreSQL races, deployment, or every possible custom product schema/permission matrix. The installed catalogue has no required custom product evidence/fee inputs to photograph; their generic renderer is documented from source. Recognition pagination beyond the available synthetic ranks/contribution rows and an actual signature completion remain source contracts. Admin/Control Center, Sheets and Telegram chat intake were deliberately excluded from page capture.

Capture-driver retries are preserved in the manifest, including stale selectors, an interrupted loading-request handler and a fixture-metric SQLite lock while the browser was active. Those are capture setup failures, not application regression findings. Metrics were persisted successfully after pausing browser reads, and the report was then captured with populated history.

<!-- CAPTURE_SUMMARY -->

Capture totals: **213 distinct recorded states, 834 PNGs, 673 observed DOM-control entries**, across 12 personas. Standard captures use 390/1366 pixels in light/dark; selected complex layouts also have 320/768/1920-pixel views. The element count includes record-specific controls and is not a count of independent product features.

Every referenced PNG was checked for presence, PNG dimensions and SHA-256 binding. The gallery was inspected with Playwright; representative phone/desktop, light/dark, report, Recognition, recovery and PDF captures received visual inspection. This is a capture inventory and interaction reference, not a claim that every image received a separate design audit or that every workflow/provider combination passed.

Source revision: `c26c3afe68528bea1c4049483a0a38e893e7e575`. Per-source-file hashes, interaction observations, setup retries and image hashes are in the manifest.

<!-- END_CAPTURE_SUMMARY -->

## Source map

| Concern | Current source |
|---|---|
| Actual page, sections and controls | [app.html](../core/templates/tat_tracker/app.html) |
| Interaction/state/rendering | [tat_tracker.js](../core/static/miniapp/tat_tracker.js) |
| Layout and responsive/theme rules | [tat_tracker.css](../core/static/miniapp/tat_tracker.css), [utils.js](../core/static/miniapp/utils.js), [runtime.js](../core/static/miniapp/runtime.js) |
| API boundary and request keys | [tat_api.js](../core/static/miniapp/tat_api.js), [views.py](../core/api/views.py) |
| Workflow authority, validation, stages, immutable path | [tat_tracker.py](../core/services/tat_tracker.py), [workflow_capabilities.py](../core/services/workflow_capabilities.py), [tat_configuration.py](../core/services/tat_configuration.py) |
| Reports and Recognition | [tat_reporting.py](../core/services/tat_reporting.py), [workflow_recognition.py](../core/services/workflow_recognition.py), [tat_presentation.py](../core/services/tat_presentation.py) |
| Remarks, tasks and recovery | [tat_comments.py](../core/services/tat_comments.py), [tat_notifications.py](../core/services/tat_notifications.py), [tat_recovery.py](../core/services/tat_recovery.py) |
| Settings and data modes | [miniapp_settings.py](../core/services/miniapp_settings.py), [workflow_data_mode.py](../core/services/workflow_data_mode.py) |
| Conditional appraisal | [services.py](../credit_assessments/services.py), [views.py](../credit_assessments/views.py) |
| Email schedules and delivery | [report_email_settings.js](../core/static/miniapp/report_email_settings.js), [report_email_export.js](../core/static/miniapp/report_email_export.js), [report_delivery](../report_delivery) |
| Related training guide | [TAT_TRACKER_MINI_APP_GUIDE.md](../TAT_TRACKER_MINI_APP_GUIDE.md) |

This reference leaves Admin, TAT Control Center, Sheets and Telegram chat/batch intake outside the visual capture scope, as selected for this task. Their effects are described only where they change the Mini App's visible behavior.
