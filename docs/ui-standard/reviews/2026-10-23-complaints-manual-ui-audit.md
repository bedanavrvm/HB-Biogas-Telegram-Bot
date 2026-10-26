# Complaints browser UI: manual audit, 23 October 2026

The current candidate needs substantial layout and interaction correction. The worst problems are the crowded 1024px detail layout, ambiguous calendar dates at 320px, silent rejection of custom report dates, and mobile case information placed after long histories. The interface also spends too much space on controls, framing and repeated information. These are visible problems in the rendered application; component imports and earlier technical checks do not resolve them.

This is an audit, not a UI implementation or acceptance. **No tests were run. No application source, dependencies, permissions, production settings or screenshot baselines were changed.** The findings below describe this candidate. A historical before/after build was not rerun, so this report does not independently establish when each problem was introduced.

## What was inspected

- Branch `Platform-Interdependence`, commit `69d8d6107a4d0cd9cd8e7b4609fb81df61b002ab`.
- The current `browser/dist-complaints-operations` production-mode build, including native staff access. Its checked source/asset manifest was validated before serving. This was not the older no-account simulator on port 8767.
- Real rendered pages in headless Chrome 155 on Windows through **Playwright CLI 1.63.0**: navigation, clicks, keyboard input, scrolling, resizing, screenshots and DOM measurements. No Playwright test runner, Django test runner, assertions or automated pass/fail suite was invoked.
- An isolated loopback Django host using a private copy of the existing synthetic review SQLite database, native password/recovery authentication, and a synthetic account with scoped Complaints IT authority. Other users' role combinations were not exhaustively inspected.
- Synthetic cases with open, closed, reopened and historical missing-details states; a case with 61 activity entries; image/PDF attachment metadata; pending, failed and unavailable attachments. Customer names, numbers, identities and image content in this evidence are synthetic.
- Queue requests normally used the isolated backend. The queue-error display used an explicitly injected HTTP 503; offline display used Chrome's offline setting. Successful image/PDF preview responses used local synthetic image payloads, including a three-page PDF-shaped specimen. These preview captures establish the viewer layout, not Drive/PDF service reliability.

The normal review launcher was deliberately bypassed because it runs tests. No operational database, real email, Telegram message, Sheets write or Drive write was used.

### Viewports, inspected one by one

Each of the following sizes was captured in **light and dark** mode for all 46 matrix states. Every resulting contact sheet was visually inspected; full-size images and measured reproductions were used for important defects. A screenshot records a viewport at a particular scroll position, not every pixel of a long page; separate states cover the lower sections.

| CSS viewport | Main observations |
| --- | --- |
| 320 × 568 | Calendar numbers truncate; report date fields are too narrow; controls dominate the first screen; two-column inputs and stacked footers leave little form space. |
| 360 × 800 | Missing-details primary label truncates; reports remain vertically expensive; table hides operational columns. |
| 390 × 844 | Contact facts fall after long activity; menus detach on scroll; table loses case identity when scrolled right. |
| 430 × 932 | More width does not resolve action-label truncation, report hierarchy or the mobile table design. |
| 667 × 375 | Landscape provides very little usable form/viewer height after headers and toolbars. |
| 768 × 1024 | Signed-in branding clips to `J.`; access-page branding wraps vertically; full-width detail is otherwise more usable than at 1024px. |
| 1024 × 768 | Queue + detail + customer sidebar + two attachment columns compete for width; attachment cards measure 111px. |
| 1280 × 720 | Laptop height exposes oversized modal framing, chart spacing and sparse queue/detail use. |
| 1366 × 768 | The desktop composition remains sparse; report rows wrap despite the available screen. |
| 1440 × 900 | More room makes wasted canvas and unequal chart panels more conspicuous. |
| 1920 × 1080 | The fixed content width retains an empty detail area, narrow settings column and tall report rows instead of using the extra space effectively. |

There are **1,012 matrix screenshots**, 184 contact sheets, and 11 additional targeted screenshots. All screenshots and contact sheets are consolidated in [one folder](complaints-manual-audit-assets/), alongside the [evidence index](complaints-manual-audit-assets/index.html), [manifest](complaints-manual-audit-assets/audit-manifest.json) and [provenance](complaints-manual-audit-assets/provenance.json). The folder also includes three initial captures. Source/capture hashes and coverage remain unchanged; command logs and helper files remain under `test-results/complaints-manual-ui-audit/`.

### Page and state coverage

| Area | Evidence state names |
| --- | --- |
| Staff access | `access-signin`, `access-mfa`, `access-recovery` |
| Queue and navigation | `01-queue`, `02-detail`, `03-queue-filters`, `21-account`, `29-empty-queue`, `30-queue-error`, `34-status-dropdown` |
| Create | `04-create`, `05-create-invalid`, `06-create-bottom`, `31-create-offline`, `42-file-selected` |
| Existing case tasks | `19-add-note`, `20-resolve`, `23-reopen`, `25-missing-details`, `22-long-activity` |
| Attachments | `26-gallery` (provider unavailable), `38-gallery-success` (mixed fixture states), `27-photo-preview`, `28-pdf-preview` (page 2 of 3) |
| Reports | `07-reports-overview`, `08-overview-charts`, `09-report-table`, `10-turnaround`, `11-open-followup`, `35-turnaround-charts`, `36-first-response`, `37-open-charts` |
| Report controls | `12-date-range`, `13-report-filters`, `14-export-menu`, `15-email`, `32-chart-options`, `33-columns`, `39-invalid-dates`, `40-calendar`, `41-pie-chart`, `43-doughnut-chart` |
| Settings and sync | `16-settings`, `17-schedule`, `24-schedule-discard`, `18-sync` |

## Findings

P1 means correct before the next UI acceptance review because a key task is unreadable, misleading or substantially obstructed. P2 means a material usability or accessibility problem. P3 means a smaller clarity or presentation problem. **Reproduced defect** distinguishes observed interaction/geometry failures from **design assessment**, which records a usability judgement with visible evidence.

### F01 · P1 · The 1024px detail layout collapses the working content

**Reproduced defect.** Open Synthetic Customer 00 and scroll to Attachments at 1024 × 768. The queue is 384px wide. Inside the remaining detail panel, the customer sidebar takes another large fixed allocation, and the attachment area still insists on two columns. Each attachment card measures **111px**. Ordinary filenames wrap word by word; `Retry thumbnail` and `Download` truncate. The 768px layout is substantially more usable because it uses the full width for the detail.

Use the available detail-container width to decide when to place facts beside the content and when to show two attachment columns. Preserve readable content before retaining extra columns. Source: `complaints-operations-workspace.tsx` (`columns`, `detailColumns`) and `complaints-operations-media.tsx` (`EvidenceGallery`).

[Evidence: light 1024](complaints-manual-audit-assets/38-gallery-success-light-1024x768.png) · [dark 1024](complaints-manual-audit-assets/38-gallery-success-dark-1024x768.png) · [768 comparison](complaints-manual-audit-assets/38-gallery-success-light-768x1024.png)

### F02 · P1 · The 320px calendar makes dates indistinguishable

**Reproduced defect.** Reports → date range → Custom dates → Choose from. At 320 × 568, many two-digit calendar buttons show `1.`, `2.` or `3.` instead of the whole day. The selected 24 is also abbreviated. The full date exists in the accessible label, but the visual calendar no longer lets a person confidently choose a day.

Reduce button padding or change the narrow calendar composition so every day remains visible. Do not shorten numeric date labels. Source: `complaints-date-control.tsx`.

[Evidence: light 320](complaints-manual-audit-assets/40-calendar-light-320x568.png) · [dark 320](complaints-manual-audit-assets/40-calendar-dark-320x568.png)

### F03 · P1 · “Done” silently abandons an invalid custom report range

**Reproduced defect.** Enter From `30 Oct 2026`, To `1 Oct 2026`, then click Done. The error correctly appears, but Done remains available and dismisses the dialog. The report continues using **24 Sep–23 Oct**, its previous dates. There is no explicit message that the entered range was not applied. Someone can export or read the report believing their new dates were accepted.

Keep the invalid range in the editor and resolve it before applying. Make Apply versus Cancel explicit, or clearly identify the rejected change. Source: `complaints-report-filters.tsx` (`dates`, Done handler).

[Invalid range](complaints-manual-audit-assets/39-invalid-dates-light-390x844.png) · [after Done](complaints-manual-audit-assets/target-invalid-range-dismissed-390x844.png)

### F04 · P1 · Mobile contact details come after the entire displayed activity history

**Reproduced layout; design assessment.** Open Synthetic Customer 01 at 390px. With the first 25 activity entries displayed, National ID starts at document position **y=3153px**, and Primary phone at **y=3213px**. Both come after Attachments, Activity and Load older activity. Staff must pass several screens of historical comments to identify or call the person they are handling. Loading more history moves those facts still farther away.

Put key case/customer facts directly after the case heading on narrow screens. Keep the history below the information needed to act. Preserve the full authorized identifier and copy action. Source: `complaints-operations-workspace.tsx` detail ordering.

[Top of long case](complaints-manual-audit-assets/22-long-activity-light-390x844.png) · [contact details after history](complaints-manual-audit-assets/target-contact-after-activity-390x844.png)

### F05 · P1 · The missing-details primary action truncates on ordinary phones

**Reproduced defect.** Complete missing details at 360, 390 and 430px shows an abbreviated primary label such as `Complete missing d...`. The narrower 320px version stacks the footer and displays the full label, so the breakpoint behaviour is inconsistent. The important task action should remain readable.

Use a concise label such as Save details or allow the footer to reflow when its actual content needs more width. Source: shared `DialogFooter` and `CaseActions` in `complaints-operations-workspace.tsx`.

[Evidence: 390](complaints-manual-audit-assets/25-missing-details-light-390x844.png) · [320 comparison](complaints-manual-audit-assets/25-missing-details-light-320x568.png)

### F06 · P2 · Tablet navigation branding breaks on both access and business pages

**Reproduced defect.** At 768px the staff access header wraps `JBL Staff workspace` into a vertical column down the left side, while the theme button appears lower on the right. The authenticated header clips its name to `J.`. Both light and dark modes reproduce it. This is a broken navigation layout at a normal tablet width, not merely a long label.

Correct allocation of the actual TopNav start/middle/end slots at this breakpoint. Source: `staff-access.tsx`, `complaints-operations-workspace.tsx`, `HeaderGutter` in `complaints-ui.tsx`.

[Access evidence](complaints-manual-audit-assets/access-signin-light-768x1024.png) · [signed-in evidence](complaints-manual-audit-assets/01-queue-light-768x1024.png)

### F07 · P2 · Chart menus remain floating after their trigger scrolls away

**Reproduced defect.** At 390px, open Complaint types → Chart options, then scroll down 180px. The trigger moves from y=65 to **y=-115**, but the menu stays at **y=101**. It now overlaps unrelated report/table content. Resize/scroll captures also show it separated from its chart. Escape does restore focus to the trigger in the inspected interaction.

Reposition with the owning scroll container or close the menu when its anchor leaves view. Source: `ActionMenu` in `complaints-ui.tsx` observes window resize, not scrolling.

[Evidence](complaints-manual-audit-assets/target-chart-menu-scrolled-390x844.png)

### F08 · P2 · Replacing the calendar year by typing does not work

**Reproduced defect.** In Choose from, focus Year, select all and type `2025` with ordinary sequential keystrokes. The field remains **2026**. Its controlled change handler rejects intermediate incomplete years, making normal replacement impossible. Pasting/filling a complete value or using alternate controls is not an adequate substitute for typing.

Retain editable text and validate/commit the year at an appropriate boundary. Source: `complaints-date-control.tsx` Year handler.

[Evidence](complaints-manual-audit-assets/target-year-keyboard-390x844.png) · [recorded values](../../../test-results/complaints-manual-ui-audit/target-year-cli.log)

### F09 · P2 · Invalid Create submissions leave keyboard focus on Submit

**Reproduced defect.** Submit the empty form. Multiple errors appear, but `document.activeElement` remains the Submit complaint button. There is no error summary or movement to the first invalid field. On the scrolled form, staff have to find which earlier fields failed.

Move focus to an error summary or the first invalid input and ensure it is visible inside the modal. Source: Create validation in `complaints-operations-workspace.tsx`.

[Validation evidence](complaints-manual-audit-assets/05-create-invalid-light-390x844.png) · [focus observation](../../../test-results/complaints-manual-ui-audit/targeted-cli.log)

### F10 · P2 · Required dropdowns are not marked as required

**Reproduced defect.** The form says required fields are marked `*`, but Branch, County, Constituency and Complaint type have no asterisk and all reject a blank submit. Text inputs do show their markers. Invalid dropdowns also retain their ordinary outline while nearby textfields receive a clear red outline.

Make required and invalid presentation consistent for all control types. Source: `Choice`, `Input` and Create in `complaints-operations-workspace.tsx`.

[Evidence](complaints-manual-audit-assets/target-dependent-field-empty-390x844.png)

### F11 · P2 · Two-column forms do not adapt to narrow widths or enlarged text

**Design assessment with reproduced geometry.** Create and Complete missing details retain side-by-side inputs at 320px. Labels wrap unevenly and input widths become uncomfortable for names, identifiers and locations. In the missing-details dialog the phone label wraps while National ID does not, misaligning the input row. At 200% root text on a 390px viewport, the same two columns leave very narrow input boxes below large wrapped labels.

Stack form fields based on usable width and text size. Keep the semantic grouping without forcing two columns. Source: `styles.fields` in `complaints-operations-workspace.tsx`.

[320 form](complaints-manual-audit-assets/04-create-light-320x568.png) · [200% text](complaints-manual-audit-assets/target-enlarged-text-create-390x844.png)

### F12 · P2 · Case-action dialogs omit the case they will change

**Design assessment.** Add note, Resolve, Reopen and Complete missing details show a generic task heading and fields, without the complaint reference or customer name inside the modal. The obscured background is the only context. This is especially weak after moving among cases or when the dialog occupies most of a phone screen.

Include a compact, readable reference/customer summary in every case-changing task. Do not rely on the page behind the blanket.

[Resolve](complaints-manual-audit-assets/20-resolve-light-390x844.png) · [Reopen](complaints-manual-audit-assets/23-reopen-light-1366x768.png)

### F13 · P2 · Dependent location fields appear usable before a parent is selected

**Reproduced behaviour; design assessment.** Open Constituency before County is selected. It looks enabled and opens a plain `No options` menu. It neither explains the dependency nor directs the person to County. The blank location dropdowns otherwise provide little guidance.

Disable unavailable dependent choices with a clear prerequisite hint, then enable them when a parent supplies options. Source: Create/`Choice`.

[Evidence](complaints-manual-audit-assets/target-dependent-field-empty-390x844.png)

### F14 · P2 · Offline guidance is placed behind the active form

**Reproduced behaviour; design assessment.** Open Create, then go offline. The workspace displays You are offline behind the modal, while the task itself still presents Draft and its normal Submit complaint action. The connection instruction is not at the point of saving. This finding concerns feedback placement; no lost save or data loss was established.

Put the current connection/save constraint inside the active task and explain what saving will do while offline. Keep editable entries available.

[Evidence](complaints-manual-audit-assets/31-create-offline-light-390x844.png)

### F15 · P2 · The “Files attached” notification covers the newly attached file

**Reproduced behaviour; design assessment.** Immediately after selecting a synthetic file, the information flag sits above the dialog footer, over the selected-file row. On 320–430px it conceals the filename/removal area that the person needs to verify. At laptop widths it still covers the start of the row. The flag is dismissible and transient; the problem is its initial placement.

Confirm attachment selection inline or reserve space for notifications so the confirmation does not obstruct its own result. Source: `Files` and `ToastHost` positioning.

[390 evidence](complaints-manual-audit-assets/42-file-selected-light-390x844.png) · [1280 evidence](complaints-manual-audit-assets/42-file-selected-light-1280x720.png)

### F16 · P2 · Small-screen workspace controls consume too much of the first view

**Design assessment.** Branding, the page title, Create, Settings, two main tabs, refresh/sync, search/filter and queue ordering occupy much of a 320 × 568 screen before case content starts. Reports add date/filter/export controls and another tab row. Landscape is also dominated by the same chrome. At 200% text on 390px, the first screen does not reach a case row at all.

Reduce the number of stacked control rows and give the page's working content priority. Keep core actions and scope understandable; move secondary utilities into an appropriate menu.

[Queue 320](complaints-manual-audit-assets/01-queue-light-320x568.png) · [reports 320](complaints-manual-audit-assets/07-reports-overview-light-320x568.png) · [200% queue](complaints-manual-audit-assets/target-enlarged-text-queue-390x844.png)

### F17 · P2 · Every report tab repeats the same large summary before its own content

**Design assessment.** Overview, Turnaround and Open follow-up start with the same six metrics and timing warning. On small phones the selected tab's distinctive charts are below several screens of common information. Open follow-up begins with closed-resolution metrics rather than immediately showing the open work it names.

Give each report view a focused hierarchy. A shared summary can be compact or available on Overview without repeating the full block before every task.

[Turnaround top](complaints-manual-audit-assets/10-turnaround-light-320x568.png) · [Open follow-up top](complaints-manual-audit-assets/11-open-followup-light-390x844.png)

### F18 · P2 · Single-point charts truncate the only useful value

**Reproduced defect.** First response time becomes a single subtle button when the fixture has one data point. At 320px its text cuts off as `Oct 2026 · Median first response: 1...`, concealing the actual duration and sample count. Wider phone sizes still truncate part of the statement. Complaints reopened uses the same format, including the redundant `Reopened: 1 complaint · 1 complaint`.

Use a wrapping metric/statement with its value and coverage separately visible. Avoid a long, truncating button as the sole representation of a one-point report. Source: `Chart` (`count===1`) in `complaints-report-charts.tsx`.

[320 evidence](complaints-manual-audit-assets/36-first-response-light-320x568.png) · [reopened evidence](complaints-manual-audit-assets/37-open-charts-light-360x800.png)

### F19 · P2 · The mobile register hides status and loses case identity when scrolled

**Reproduced layout; design assessment.** At 390px the initial register shows Reference and Customer. Branch, type, reported date, status and timing sit off-screen. Scrolling to the far right shows timing/target but sends Reference to x=-1017px and Customer to x=-857px. No identifying column remains fixed, so staff cannot reliably associate a far-right value with its case without moving back and forth.

Use a mobile case-row presentation or retain a compact case identifier while showing the operational columns. Make horizontal overflow discoverable. Source: `complaints-report-table.tsx`.

[Initial register](complaints-manual-audit-assets/09-report-table-light-390x844.png) · [right edge](complaints-manual-audit-assets/target-report-table-scroll-right-390x844.png)

### F20 · P2 · Register rows become unnecessarily tall

**Reproduced geometry; design assessment.** The inspected mobile rows measure **92px**. The ordinary branch label `Synthetic Other Branch` wraps with `Branch` on a separate line and adds a large amount of height across the row. Similar wrapping remains visible on wide screens. The register presents few cases at a time despite extensive blank cell space.

Allocate readable widths to the columns that actually wrap, or deliberately present their second line. Avoid allowing one narrow cell to dictate excessive height throughout the table.

[1366 evidence](complaints-manual-audit-assets/36-first-response-light-1366x768.png) · [measured rows](../../../test-results/complaints-manual-ui-audit/targeted-cli.log)

### F21 · P2 · Metric comparisons and denominators need clearer wording

**Design assessment.** `Based on 7 of 7` does not name the denominator, while `→ 0 days · Unchanged · was 2 days` puts a zero next to a current two-day metric. The previous comparison period is not explicitly dated. A large 12-hour first-response metric is based on only 1 of 18 cases; the warning is present, but the value, sample limitation and explanation require the reader to assemble several separate pieces.

Name the eligible population and comparison dates, and distinguish the current value from its change. Keep incomplete coverage visibly tied to the affected metric. No timing calculation error is alleged.

[Evidence](complaints-manual-audit-assets/07-reports-overview-light-1366x768.png)

### F22 · P2 · Charts use excessive space for very small amounts of information

**Design assessment.** The 320px resolution trend uses almost a full screen for two dots, with a large gap before the axis caption and a further instructional line. Adjacent desktop charts have markedly different heights, leaving empty areas within a two-column grid. One-point chart cards shrink to a text strip beside full-height charts. The result is a collection of independently sized boxes with weak visual rhythm.

Set chart dimensions and annotation spacing according to the actual available width and data. Use a deliberate one-value presentation. Preserve honest gaps and recorded timing semantics.

[320 trend](complaints-manual-audit-assets/35-turnaround-charts-light-320x568.png) · [desktop mismatch](complaints-manual-audit-assets/35-turnaround-charts-light-1366x768.png)

### F23 · P2 · Pie/doughnut legends do not identify their colours

**Design assessment.** The radial charts show numeric values inside coloured sectors and text such as `Maintenance: 2 (11%)` below, without matching colour keys in that legend. With several sectors all labelled `2`, the visible text does not tell a touch user which sector belongs to which complaint type. The chart has accessible labels and SVG titles; that does not fix the visible association.

Provide matching swatches or direct category labels. Keep the accompanying textual counts.

[Pie evidence](complaints-manual-audit-assets/41-pie-chart-light-390x844.png) · [doughnut evidence](complaints-manual-audit-assets/43-doughnut-chart-dark-390x844.png)

### F24 · P2 · Emailing a report does not show a concrete scope summary

**Design assessment.** The email task lacks a clear summary of the report dates, branch, status, selected chart/table search and result count to be sent. Its generic current-filters wording is weak when table-only search and chart selection can narrow the register independently of the KPI cards.

Show the captured scope and recipient at the point of sending, using business terms. Keep the existing server-owned access and scope checks.

[Email evidence](complaints-manual-audit-assets/15-email-light-1366x768.png)

### F25 · P2 · Selecting Email opens another general Export task

**Design assessment.** Export → Email report opens an Export report dialog that repeats export choices before the email field. The person must find the chosen task a second time. On short landscape screens the email field sits below the visible body while the Send report footer remains visible. Its left-aligned footer and lack of a Cancel button also differ from the other form tasks.

Open a focused email task with its recipient, scope and send/cancel actions. Keep file exports in their own immediate actions.

[390 evidence](complaints-manual-audit-assets/15-email-light-390x844.png) · [landscape](complaints-manual-audit-assets/15-email-light-667x375.png)

### F26 · P2 · Settings waste desktop space and bury scheduled-report management

**Design assessment.** Your preferences occupy a narrow left column on a large empty canvas; scheduled reports sit below rather than using a deliberate page layout. The new schedule form is another long narrow block. Its frequency/time defaults do not provide a prominent next-send/covered-period summary, which would make the scheduled action easier to understand.

Group account defaults and report schedules into clear sections, with purposeful width and concise schedule summaries. Avoid expanding the editor before the user needs it.

[Settings](complaints-manual-audit-assets/16-settings-light-1920x1080.png) · [schedule](complaints-manual-audit-assets/17-schedule-light-1366x768.png)

### F27 · P2 · Cancelling an untouched new schedule asks to discard changes

**Reproduced behaviour; design assessment.** Settings → New schedule → Cancel, without typing anything, opens Discard changes. Navigating away from the untouched editor can also trigger the browser's leave-page guard. Merely opening a blank form should not create a meaningful unsaved-change decision for the user.

Compare to the initial editor state and protect actual edits or pending requests. Preserve protection once the user has entered data.

[Evidence](complaints-manual-audit-assets/24-schedule-discard-light-390x844.png)

### F28 · P2 · Default-status selection has no programmatic selected state

**Reproduced accessibility defect.** Settings → Default status renders three ordinary buttons. DOM inspection found no `aria-pressed`, `aria-checked` or selection role on any of them, even though one is visually selected. The enclosing group has a label, but assistive technology cannot determine the saved choice from those buttons' selection semantics.

Use a radio group or correctly exposed mutually exclusive selected controls. Source: `complaints-operations-settings.tsx`.

[Settings evidence](complaints-manual-audit-assets/16-settings-light-390x844.png) · [DOM observation](../../../test-results/complaints-manual-ui-audit/targeted-more-cli.log)

### F29 · P2 · “Add note” calls its field a “Resolution comment”

**Design assessment.** The Add note task uses Resolution comment, and the activity feed repeats that term for feedback that leaves the complaint open. Resolve is a separate action. This terminology makes ordinary feedback sound like completion and weakens the distinction between commenting and resolving.

Use a note/feedback label for the non-closing action and a resolution label for actual resolution. Preserve their separate workflow effects.

[Add note evidence](complaints-manual-audit-assets/19-add-note-light-390x844.png) · [activity evidence](complaints-manual-audit-assets/22-long-activity-light-390x844.png)

### F30 · P2 · Upload failures offer little usable recovery information

**Design assessment on explicit fixture states.** A failed attachment says Ask your administrator to check this attachment without showing what staff should do next or an actionable reference beyond its filename. Pending files have no visible age or progress explanation. Unavailable thumbnails display Preview, Retry thumbnail and Download together, making recovery noisier than necessary.

Separate upload failure, preview failure and unsupported type. Give the current actor a useful next step and retain the original-download path where allowed. These screenshots intentionally simulate provider states and are not evidence that the live provider is failing.

[Mixed-state gallery](complaints-manual-audit-assets/38-gallery-success-light-390x844.png)

### F31 · P2 · The attachment viewer prioritizes toolbars over the document

**Design assessment.** Metadata, attachment navigation, PDF page navigation, zoom controls and a separate page-count line sit before the preview. A short landscape viewport leaves only a small strip for the image. The default 100% fits width rather than the complete page, so tall documents immediately require scrolling. A photo still receives disabled PDF page controls and Page 1 of 1.

Simplify the toolbar by media type and provide a whole-page fit when the task is to inspect a page. Keep explicit download and multi-page navigation available.

[Photo landscape](complaints-manual-audit-assets/27-photo-preview-light-667x375.png) · [PDF laptop](complaints-manual-audit-assets/28-pdf-preview-light-1280x720.png)

### F32 · P2 · The default desktop queue leaves most of the working canvas empty

**Design assessment.** Before selection, a narrow queue occupies the left side and a large otherwise empty detail area shows only Select a complaint. There is no useful overview or deliberate empty-detail composition. At large widths the interface still feels like a small list placed inside a much larger blank page.

Choose a purposeful starting composition. A wider queue with relevant columns, or a well-composed empty detail state, would use the space more effectively without selecting a case implicitly.

[Evidence](complaints-manual-audit-assets/01-queue-light-1920x1080.png)

### F33 · P2 · No-results feedback appears at the bottom of a tall empty queue

**Reproduced layout; design assessment.** Search for a value with no matches. On desktop the queue retains its tall blank list area and puts No complaints match these filters at the bottom. The adjacent panel still says Select a complaint. The message is visually remote from the search that caused it and offers no clear reset action there.

Place an actionable empty state near the top of the result area and adapt the companion detail state to zero results.

[Evidence](complaints-manual-audit-assets/29-empty-queue-light-1366x768.png)

### F34 · P2 · A queue read failure produces duplicate feedback and a blank working area

**Reproduced display using injected 503.** The same failure appears in a page SectionMessage and a bottom error flag. At 320px these messages occupy most of the available screen around an empty queue. The persistent message does not put a Retry action beside its explanation; the global Refresh control is elsewhere. The fixture supplied the word `unavailable`; the report does not attribute that exact wording to a real outage.

Give the failed area one clear, persistent recovery message with Retry. Use a notification only if it adds a distinct purpose.

[Evidence](complaints-manual-audit-assets/30-queue-error-light-320x568.png)

### F35 · P2 · Desktop Create combines an oversized frame with a narrow internal form

**Design assessment.** The modal can be about 960px wide while its form stays in a narrower centred column. On a 720px-high laptop it consumes almost the full window yet still requires scrolling to reach description and attachments. The broad header, reserved Draft row, introduction, repeated section rules and footer consume substantial height without making the form easier to scan.

Size the frame to its working content and reduce unnecessary vertical framing. Keep the task status and protected footer readable, including at enlarged text sizes.

[1280 evidence](complaints-manual-audit-assets/04-create-light-1280x720.png) · [enlarged text](complaints-manual-audit-assets/target-enlarged-text-create-1280x720.png)

### F36 · P3 · The queue search instruction truncates at narrow widths

**Reproduced layout; design assessment.** Search name, ID, phone or branch is the only visible explanation of the search scope. At 320–360px much of it is hidden. The search does have an accessible name; this is a visible clarity issue rather than an unlabelled-control finding.

Use a shorter visible label/placeholder and provide the supported scope in a concise hint where needed.

[Evidence](complaints-manual-audit-assets/01-queue-light-320x568.png)

### F37 · P3 · Account does not identify the signed-in person

**Design assessment.** The generic Account icon opens a menu containing only Sign out. The header says JBL workspace but does not identify the active staff account. Someone reviewing a shared machine or multiple browser sessions has no quick way to confirm who is signed in from this menu.

Show the staff identity in the account menu and keep Sign out easy to find. Do not expose unnecessary personal information.

[Evidence](complaints-manual-audit-assets/21-account-light-1366x768.png)

### F38 · P3 · Sync status lists records without enough diagnostic context

**Design assessment.** Google Sheets sync distinguishes canonical saves from publication correctly, but its list is mainly reference + Waiting + Review complaint. It does not explain waiting age or the last attempt in the inspected state, and a long partial list gives little help deciding which record needs attention first.

Lead with the state that requires action and show a useful age/attempt summary where available. Keep normal queued publication separate from a failed canonical save.

[Evidence](complaints-manual-audit-assets/18-sync-light-390x844.png)

### F39 · P3 · Resolve's “Open next” preference looks like another action button

**Design assessment.** Open next complaint after resolving is implemented with checkbox semantics, but visually resembles an ordinary text button, without a conventional checkbox indicator. It is a persistent choice within the task, not an immediate command. The long label and subtle state are harder to interpret than a labelled checkbox.

Use a visible checkbox/toggle presentation, retaining its existing accessible checked state and resolve-and-open-next behaviour. This finding is visual; its checkbox semantics are present.

[Evidence](complaints-manual-audit-assets/20-resolve-light-390x844.png)

## What should be corrected first

1. Repair the width rules for case detail, facts, attachments, calendar and action footers. Fix F01–F08 before polishing colours or adding features.
2. Put case identity/contact facts and action context where staff can see them; repair form requirements, validation focus and dependent-field guidance.
3. Reduce repeated report chrome/metrics, replace the mobile register composition, and make chosen dates/export scope explicit.
4. Simplify notification, attachment and settings layouts, then revisit the smaller wording and account/sync clarity issues.

The recurring cause is composition: viewport breakpoints retain more columns than the content can support, shared modal/button patterns truncate meaningful text, and repeated controls are given more room than the work itself. These corrections belong in the existing shared components and page compositions. They do not require a new design system or dependency set.

## References and interpretation

The current official [ADS form guidance](https://atlassian.design/components/form/usage), [modal guidance](https://atlassian.design/components/modal-dialog/usage), [button guidance](https://atlassian.design/components/button/usage) and [typography guidance](https://atlassian.design/foundations/typography/applying-typography) were consulted as review criteria. The observations above are this audit's assessment of the rendered composition, not an assertion that every judgement is a formally measured ADS or WCAG violation. The repository's documented first-party modal/calendar compositions and explicitly requested positive-action colours remain part of the existing product contract.

Useful existing behaviour was also observed: both explicit themes render; dialogs provide internal scrolling; menu Escape restores trigger focus in the inspected case; case-action Escape restores focus to its opener; the ID copy/phone actions exist; incomplete timing coverage is disclosed; attachment upload states are distinguished; and canonical Complaint saves are explained as separate from Sheet publication. These features should survive the corrections.

## Limits

No tests, rebuild, deployment, operational data inspection, successful workflow submission, real email export, provider download or Drive preview acceptance was performed. Invalid/blank form submission was used only to inspect local validation. An image was selected locally to inspect its form row and then discarded.

This audit used Chrome with CSS viewport resizing, not physical phones/tablets or other rendering engines. It did not establish software-keyboard behaviour, touch-target usability on hardware, screen-reader announcements, contrast compliance, print/export layout or every permission combination. The 200% examples enlarge root text; they are not a claim of OS text-scaling or actual browser-zoom acceptance. First-time staff enrollment and unrelated browser workspaces are outside this Complaints audit.

Environment-injected antivirus-script network failures and the ADS feature-gate diagnostic were excluded from product findings. The isolated host used fixture-only safety settings and a private synthetic database copy; production browser access remains disabled/unmounted. Include the consolidated screenshot folder when sharing this document. Referenced command logs remain in the ignored `test-results/complaints-manual-ui-audit/` directory.
