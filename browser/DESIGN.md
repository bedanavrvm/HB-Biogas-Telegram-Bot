# Browser design references and application decisions

The current component-adoption decisions are in
[`STITCH-DESIGN-DECISIONS.md`](STITCH-DESIGN-DECISIONS.md), including the new
Stitch state references and the user's explicit backend-feature choices.

The queue now follows `Stitch/Main Page/code.html`, `screen.png` and `DESIGN.md`.
[Main Page review](../docs/ui-standard/reviews/2026-10-28-complaints-main-page.md)
records its live card/search/filter/pagination/navigation behavior and adaptations.
The previously corrected case detail remains its separate destination.

## Current styling authority (28 October 2026)

The user explicitly replaced ADS styling for this and future browser work.
`AGENTS.md` governs this instruction. Complaints follows both the complete
`Stitch/Create Complaint/code.html` interactive export and `screen.png`.
Earlier ADS full-adoption requirements below are historical.

The image guides the resting state; the HTML guides expanded attachment,
thread, mention, recording/transcription and resolve states. Real case content
replaces sample values; staff initials replace stock portraits. The prior
read-only description, excluded assignment and staff-only conversation remain.
Empty attachments do not reserve a card; success feedback requires a confirmed
operation. Dark mode retains the geometry with readable colors.

Inter 4.1 comes unchanged from the [official font source](https://github.com/rsms/inter/tree/v4.1),
is served locally with its SIL OFL licence and build/source hashes, and has no
runtime CDN dependency. See `vendor/inter/README.md` and `DEPENDENCIES.md`.
Evidence: `../docs/ui-standard/reviews/2026-10-28-complaints-stitch-visual-match.md`.

## Complaint workflow corrections (28 October 2026)

The user authorized correction of the seven audited browser workflow gaps, with
incremental Playwright review. Current official guidance consulted:

- [Form usage](https://atlassian.design/components/form/usage/): the historical
  completion task includes every required input, including the complaint type.
- [Section message usage](https://atlassian.design/components/section-message/usage/):
  failed location loading stays beside the affected inputs with a working Retry;
  dependent choices cannot retain stale options or allow an uncertain submission.
- [Modal dialog usage](https://atlassian.design/components/modal-dialog/usage/):
  the read-only report detail retains the underlying report, case identity,
  bounded body, named close controls, existing native focus/escape behavior and
  a right-aligned Close action. Long activity uses explicit pagination.
- [Navigation layout](https://atlassian.design/components/navigation-system/layout/code/):
  existing Root/TopNav/Main areas retain the application shell. Within Main,
  the working area expands to 120rem and the queue/detail split uses the supported
  64rem breakpoint. Narrow layouts retain Back navigation.

Shared case facts/location use the installed ADS Text, Anchor, IconButton and
layout primitives. Phone numbers remain actionable, map anchors accept only
HTTP(S), and immutable changes use their server-provided labels and values.
The existing TaskDialog/AG Grid compositions remain deliberate bounded choices;
there is no new component dependency, theme, font or Telegram visual migration.
The source-bound review and actual browser evidence are recorded in
`docs/ui-standard/reviews/2026-10-28-complaints-workflow-parity.md`.

## Settings, schedules and email recovery (23 October 2026)

The existing task-local recovery contract now covers preferences, schedule
editors and report-email requests, with no new page design or type scale.
Current official Form, SectionMessage and Button usage was rechecked:
https://atlassian.design/components/form/usage ;
https://atlassian.design/components/section-message/usage ;
https://atlassian.design/components/button/usage .
Persistent errors retain an explicit repair next to the task; toasts communicate
outcomes. Reauthentication never retries a write. Ambiguous responses freeze
the captured request for explicit exact-request retry. Reload saved preferences
retains edits for review; loading a saved schedule explicitly discards edits.
Closing an uncertain email explains that a report may already be queued.
The existing guarded native confirmation is reused; no new dependency or theme.

## Complaints composition correction (23 October 2026)

The user explicitly approved this correction across the browser Complaints
workspace, including green positive actions. It does not migrate Telegram or
enable production. Current official guidance was rechecked:

- https://atlassian.design/components/modal-dialog/usage — persistent header,
  close control, content and right-aligned action footer; focus and Escape.
- https://atlassian.design/components/button/usage — one primary action per
  task, meaningful labels, deliberate secondary/utility groups.
- https://atlassian.design/components/select/usage — labelled searchable
  options; long lists remain in their own bounded menu.
- https://atlassian.design/foundations/typography/applying-typography — retain
  the installed type scale, distinguish headings/body/secondary metadata.

`TaskDialog` retains native modal focus/inert semantics while separating its
header, scrollable body and footer. Named portal slots put a fixed-height draft
status and form-associated submit controls outside the scrolling body. X and
Escape use the same existing close/unsaved-change guard. `AdaptiveSelect` portals
to the active dialog (not inert document.body), bounds its own list to available
viewport space, and never enlarges the dialog. No modal/select package or
platform feature flag was added. Native-layer composition remains intentional.

The reserved status shows Draft/Saving/Saved/Offline/Not saved, with icon and
text. Saved still requires server confirmation. Saving animation uses the Web
Animations API only while in flight and respects reduced motion. Routine status
changes do not insert content above fields. Existing uncertain-write, conflict,
offline and session-recovery rules remain authoritative.

The green `ActionButton` is an explicit JBL deviation: its wrapper locally maps
only ADS brand-background normal/hover/pressed variables to existing success
tokens. It keeps the pinned Button's focus, disabled, loading and keyboard
behaviour. Destructive uses ADS danger; utility uses neutral. It does not change
the global theme or create a second font/spacing scale. Imperative token-variable
assignment is confined to that wrapper because typed cssMap does not expose
custom-property declarations. No broad lint exception was introduced.

The heading/Create row, tabs/utility row and search/filter row are deliberately
separate. A compact sync control replaces the misleading full-width sentence;
exact counts cover all matching complaints, not the first 50 disclosed rows.
Attachment capture and file rows are separate from workflow footer actions.
Section dividers and semantic text colours add hierarchy without boxing fields.

Theme switching is now direct, at the navbar's far right: no theme modal. System
preference remains the initial default until an explicit light/dark choice.
Only that non-sensitive enum is persisted. Three turnaround metrics share a row
at ordinary mobile sizes. Their layout reflows below 20 root-font units, using
measured geometry because that application breakpoint is not in the pinned ADS
cssMap media-query schema; typography is never reduced to force a fit.

Verification and remaining acceptance are recorded in
docs/runbooks/browser-channel-parity.md. Source ratchet entries remain candidates,
not approved screenshots or permission to bypass the Phase 6 hold.

## Responsive Complaints correction (22 October 2026)

This source-bound candidate implements the user's approved responsive plan,
not a Telegram migration or production activation. Current official usage
references consulted for this change:

- https://atlassian.design/components/form/usage
- https://atlassian.design/components/popup/usage
- https://atlassian.design/components/flag/usage
- https://atlassian.design/components/app-provider/code
- https://atlassian.design/foundations/color/data-visualization-color
- https://atlassian.design/foundations/typography (rechecked 23 October)

The queue consumes the measured remaining viewport, with its own scrolling and
pagination. Desktop detail scrolls independently; returning from mobile detail
retains queue position. Dynamic geometry uses DOM measurement, not a new type
or spacing scale. Compatible field pairs retain ADS controls and typography;
wrapped labels are measured per row to align their actual control borders.

Queue/report filters are short native-dialog compositions with labelled ADS
Select/Textfield controls. Valid selections apply immediately; incomplete or
reversed custom dates do not issue a report request. Historical month, quarter
and year choices project canonical date ranges. Help opens a small contextual
dialog instead of displacing chart content. ADS's installed popup/modal peer
limitations remain: no new dependency or feature-flag override was introduced.

The pinned TopNavEnd collapses its ordinary children on phones; its persistent
items API requires an unavailable platform flag. A small grid-end composition
keeps ThemeControl outside that overflow, alongside the unchanged TopNavEnd.
The provider owns light/dark/system themes. The sole device-storage exception
is `jbl.browser.colorMode`, containing only `light` or `dark`; System removes
the key. Customer values, answers, credentials and session proof are never stored.

One tokenized toast replaces an older event notification. Success/information
expires; warning/error remains dismissible. Persistent field/session/uncertain
save feedback remains in the affected task. A native manual popover is hosted
inside the current modal when necessary, avoiding both stacking and modal-inert
failures. Icon, plain severity and message convey the result without colour
alone. This existing-primitive composition is a narrow Flag-package exception.
Routine draft autosaves use the compact server-confirmed Saved indicator,
not repeated toasts. Restore/discard and explicit workflow results use toasts.

AG Grid remains Community with a bounded viewport, ten default columns and a
Columns selector for the complete 23-column register. Only canonical server-sort
fields advertise sorting. Phones dial; IDs copy; those actions never also open
the row. Row numbers include the canonical page offset. SVG marks retain keyboard
drill-down, accessible values, chart/text tokens and explicit units. Bars place
contrasting labels inside when they fit; line labels centre above points; dense
dates angle diagonally and charts scroll horizontally rather than shrinking text.
Composition charts offer pie/doughnut only where the underlying counts support
them, with separated small-slice labels and a textual legend.

Evidence opens in a large native dialog, with fit/zoom/reset/pan and opposite-end
PDF navigation. Raster images are not restyled form controls; runtime image width
is zoom geometry. The browser-only, CSRF-protected page adapter reuses the existing
bounded PDF subprocess renderer, rechecks owning Complaint evidence access and
returns one JPEG page plus page count. Original downloads are unchanged. No raw
PDF plugin, external viewer, customer-storage cache or new renderer dependency.

Evidence and actual executed checks belong in the runbook below; screenshots
are review candidates, not automatic approval of a design standard.

## Queue preferences and long activity (ADR 0073)

Official usage guidance consulted live on 22 October 2026:

- https://atlassian.design/components/select/usage
- https://atlassian.design/components/button/usage
- https://atlassian.design/components/section-message/usage

The installed Select/Label, Button, Heading, Box, Stack and Text contracts are
reused, without another library or new typography. Settings expose two labelled
single-choice defaults: queue and branch, one Save preferences primary action,
and inline persistent failure with Retry settings. Defaults apply on entry;
an explicit queue link wins. A selected branch remains visible even when the
current result facets have no matching cases. Normal loading never claims there
are no pending updates before the response is confirmed.

Activity stays in the existing case-detail reading order with token dividers,
plain action/author/time text and wrapped notes. Load older activity reveals 25
older events per request; an expiring cursor has a working Refresh activity
repair, distinct from retrying a temporary network failure. No timeline dots,
new badge system, repeated timestamp rows or separate history destination.

Report state lives above transient request/loading panels. Only enumerated
view/group/date-basis/status, validated dates and bounded page numbers enter
History URLs. Search text, branch/category names and answers remain in memory.
Refresh/Back/Forward/reload preserve the safe report selection, not confidential
free-text facets. Pending chart drill-down is intentionally transient.

The `/_review/` host is an isolated fixture/instructions page, not a production
screen or approved component. It uses native semantic HTML, explicitly outside
the ADS business interface; credentials are synthetic, transient, loopback-only
and excluded from captures/logging. Its assets are startup-pinned so subsequent
builds do not disrupt a review in progress. Technical/visual evidence remains
candidate evidence, never a standard approval or Telegram migration.

## Complaints reporting slice (ADR 0073)

Consulted live on 22 October 2026:

- https://atlassian.design/components/select/usage
- https://atlassian.design/components/primitives/grid/code
- https://atlassian.design/foundations/color/data-visualization-color

The Grid overview returned no usable text; its code page and installed pinned
GridProps were inspected. The older color-new URL failed; the current canonical
data-visualization page above succeeded. No extra chart/control dependency.

Three named report views limit dashboard clutter. Labelled ADS Selects own
report, grouping and chart choices. Related charts pair on desktop and stack on
phones; an unpaired chart spans the available width. Counts and elapsed hours
have distinct axes; durations also have readable day equivalents. Sparse time
series start as bars, longer series as lines. Missing timing is not zero.
Chart coordinates use actual period spacing, not evenly spaced missing dates.

Marks use chart brand/success/danger tokens; axes/text use border/text tokens.
Separate series have gaps, direct accessible names and distinct line textures/
point shapes. Every point is keyboard operable and has an equivalent searchable
ADS selection with its full value, unit and case count. Resizing preserves text
at real CSS size instead of shrinking a fixed desktop SVG on phones. The one
scoped no-html-button exception describes interactive SVG marks only; there is
no HTML-image exception and other recommended lint rules remain blocking.

Chart selection changes the case list and filtered Excel, retaining the source
chart population. Reporting-date cohorts, resolution events and current closed
resolution medians are explicitly distinguished. Partial weeks are clipped to
the requested date range on drill-down. This is a source-bound browser candidate,
not human approval or permission to migrate the Telegram UI.

## Native Complaints operations candidate (ADR 0073)

The separate entry composes actual ADS Root/TopNav/Main, token typography, Grid,
Form/Field/MessageWrapper, Textfield, Select, Button, Anchor and persistent
SectionMessage feedback. A fluid desktop queue/detail workspace replaces the
read pilot's width bound. Mobile stacks with selected-case focus. Native form
constraint popups are disabled in favor of inline field errors. No simulator,
milestone or implementation-status prose appears in the native workspace.

Official references consulted 22 October 2026:

- https://atlassian.design/components/form/usage
- https://atlassian.design/components/button/usage
- https://atlassian.design/components/select/usage
- https://atlassian.design/components/navigation-system/layout/code
- https://atlassian.design/components/primitives/anchor
- https://atlassian.design/components/textarea

Form/Button/Select guidance was retrieved live. Layout/Anchor/textarea fetches
intermittently failed; previously consulted layout guidance and installed typed
APIs were also inspected. This is not a claim of ADS design certification.

Intentional candidate exceptions, not approved baseline changes:

- Related staff identity/location inputs pair on desktop and stack on mobile.
- Hidden native camera/file inputs retain the existing chooser exception.
- Long notes use native textarea inside ADS Field/Box, with ADS tokens and
  explicit error associations. The exact approved dependency graph has no
  textarea package; no new dependency is silently installed. Human review remains.
- Interactive SVG charts retain keyboard points, textual values/units and ADS
  colors. They are not static images/buttons; only their implementation scopes
  two explained lint exceptions. All other recommended rules remain blocking.

Source-bound evidence and acceptance limits are in
`docs/runbooks/browser-channel-parity.md`. None authorizes Telegram migration.

Consult current official guidance before changing a pattern. This document maps
our decisions to references; it does not replace the documentation or prove
visual acceptance. Package APIs come from the pinned workspace and its review.

| Pattern | Official guidance | Application decision |
|---|---|---|
| Access forms | [Form usage](https://atlassian.design/components/form/usage) | One column: title, concise description, persistent feedback, fields and action. The 500px maximum is a local content-width choice, not a universal ADS requirement. |
| Workspace grid | [Grid](https://atlassian.design/foundations/grid-beta/applying-grid) | Fixed-wide 1296px including margins; 32px desktop/16px mobile inline margins. Content stays within the grid. |
| Navigation | [Layout](https://atlassian.design/components/navigation-system/layout), [migration guide](https://atlassian.design/components/navigation-system/migration-guide) | Actual Root/TopNav slots/Main; workspace SideNav with current side-nav-items. Access tasks do not inherit business navigation. |
| Persistent feedback | [Section Message](https://atlassian.design/components/section-message/usage), [Inline Message](https://atlassian.design/components/inline-message/usage) | One visible SectionMessage for form-wide authentication/service failures. No duplicated paragraph or required popup interaction. Future field-specific errors belong to their field. |
| Surfaces | [Elevation](https://atlassian.design/foundations/elevation) | Default page surfaces, flat bordered groups and adaptive neutral backgrounds. No nested sunken-on-raised surface or full-page decorative shadow. |
| Review selection | [Select usage](https://atlassian.design/components/select/usage) | Labelled Page/Theme/Response selects on a separate review entry; no button collections or staff-facing scenario controls. |
| Type and spacing | [Typography](https://atlassian.design/foundations/typography), [spacing](https://atlassian.design/foundations/spacing) | Heading/Text and semantic spacing tokens; no reduced text scale to force viewport fit. System-font fallbacks remain under the asset decision. |
| Initial theme | [Token setup](https://atlassian.design/foundations/tokens/use-tokens-in-code/), [App provider](https://atlassian.design/components/app-provider/examples) | Await the supported default theme initializer before mounting controls, then hand listener ownership to AppProvider. This local startup decision avoids a light-input flash with dark text. AppProvider handles later system/theme changes. |
| Actions | [Button usage](https://atlassian.design/components/button/usage) | One primary task action, links for navigation, meaningful loading feedback and no dead disabled workflow links. |

ADR 0072 / P2a.2 applies these current official references to the local role
demo: labelled Selects choose persona and one permitted action; Form/Field,
Textfield and MessageWrapper supply required inputs and validation; SectionMessage
keeps save failures in the task reading sequence. Two short customer/complaint
steps use a side summary/evidence column on desktop and stack on mobile. Draft
values and selected files survive Back; sample-fill helpers are local demo
shortcuts, positioned before fields so blur validation cannot move them during
pointer activation. The ordinary queue uses four rows to leave room for real
role/action controls at 1280x720. Longer history/forms and enlarged text scroll.

The hidden native file input is an intentional narrow exception: the approved
dependency graph contains no upload component. Its visible Choose files/Remove/
preview controls use ADS Button; no extra package or alternate visual palette.
Selected image/PDF bytes are validated by the simulator, stay in memory, and
are inspected through transient blob URLs. Role selection/reset are explicitly
synthetic controls. No company credential, real permission or P3 write is implied.
Source-bound candidates/evidence live in decision section 15; no approved
baseline or Telegram migration approval changes.

`/` is the synthetic staff presentation. `/review.html` is a separate local
design harness using the same components and in-memory state transitions.
Both have one clear fixed-values/no-account-changes notice. Inputs remain
read-only because this preview must never collect credentials. That narrow
exception is documented and is not an operational-form design pattern.

ADR 0067's separate `access.html` build is a dormant real transport candidate,
exercised only by isolated Django tests. It reuses the same focused ADS task
composition with editable, labelled fields, required-field legend, field error
MessageWrapper, standard username/current-password/one-time-code autofill and
persistent form-wide feedback. This is separate from the fixed-value preview.
Preserve the username after mistakes; clear proof after submission/navigation.
Routine sign-in has two short steps. Refresh resumes the server-owned stage;
recovery stays on the code screen. Recheck an uncertain session without replaying
proof or asking for routine confirmations. Background checks must not interrupt
typing or flash the page. ADR 0068 adds guided initial-password, QR enrollment
and one-time recovery handoff in the same dormant client. Invitation proof is
removed from the fragment before rendering/network. Native new-password autofill
and field errors apply; no duplicate password prompt between creation and setup.
One saved-codes action enters the fresh sign-in required by the native policy.
Delivery, real devices and operational acceptance remain separate.

The credential QR is generated locally by the existing allauth MFA adapter,
rendered with Box as an image, and has a manual setup-key fallback. Its intrinsic
white quiet zone is machine-readable image content, not an alternative UI palette.
This transient credential image is not a proprietary/build asset or remote QR
service. QR/key/codes carry data-sensitive markers and are masked in captures.
Copy codes is an explicit user action; there is no automatic clipboard write,
download, storage or repeated disclosure. Hide/navigation clears the transient
display; a lost one-time handoff gives the actual support/sign-in path.
Place the authenticator/recovery switch and cancel action before the field: an
empty field's blur validation must not move either action during pointer activation.
Only uncertain sessions show a manual recheck; routine checks are automatic.
Render the TopNavEnd action slot only when it contains an action. Its native
mobile overflow button must not expose an empty menu on signed-out access tasks.
The documented slot contract is in the current
[layout API](https://atlassian.design/components/navigation-system/layout/code).

Review normal, failure/retry, setup, enrollment/recovery, help and workspace
scenes. Check laptop fit, narrow mobile, keyboard, skip navigation, select
behavior and 200% text. Natural scrolling remains available. Technical checks
do not establish human/device/assistive acceptance or production readiness.

During QR enrollment only, a 900px content bound places the credential image
beside the single-column form at ADS md; mobile stacks. This uses the existing
Grid pattern and avoids unnecessary laptop scrolling. Anonymous setup Cancel
clears local proof while preserving verified server progress, with a contextual
Continue account setup action. It does not discard the bound mailbox proof.

Use Box for live-region/alert semantics around Text content. The pinned compiled
Text implementation does not forward role despite its broad TypeScript props;
DOM role checks must verify announcements. Applied references:
https://atlassian.design/components/primitives/box/usage and
https://atlassian.design/components/primitives/text/code .

## Closed Complaints workspace (P2a / ADR 0070)

The separately built `complaints.html` entry composes the same native sign-in
with the first authorized read workspace. Current official guidance consulted
20 October 2026: [Select usage](https://atlassian.design/components/select/usage),
[SectionMessage usage](https://atlassian.design/components/section-message/usage),
[Navigation System layout](https://atlassian.design/components/navigation-system/layout/code),
[Grid](https://atlassian.design/components/primitives/grid) and
[applying the grid](https://atlassian.design/foundations/grid-beta/applying-grid).
The Grid and Navigation System code pages were also consulted after the
overview pages returned incomplete text; installed versioned APIs were inspected.
Form references: https://atlassian.design/components/form/usage and
https://atlassian.design/components/form/code . Applied filters are restored
when Refresh remounts the form, so its visible query matches the result set.

Intentional composition exception to the long-form single-column guidance:
this compact queue filter toolbar places search, immediate status and submit
beside each other on desktop. Each has a visible label; mobile stacks them.
It has no required fields or setup task. This application-specific candidate
remains subject to human review and is recorded in the source ratchet.

Use the fixed-wide 1296px grid, 32px desktop/16px mobile margins, a flat queue
beside detail at 64rem and labelled ADS search/status controls. Five cases per
page keep the ordinary laptop queue visible. Mobile stacks; long names,
descriptions, history and enlarged-text reflow retain natural scrolling.
The installed Button selected state identifies the case being reviewed.
Previous/Next are real actions, with disabled boundaries. No unimplemented
navigation, sunken-on-raised surface, custom selection widget or new asset.

This is a new source-bound candidate, not approval of a Telegram standard.
Read requests clear superseded detail, cancel on replacement/unmount and never
replay credentials. A 401 returns to native session checking; a workflow denial
does not claim that company sign-in supplies Complaint authority. Persistent
section feedback offers Refresh without extra authentication steps.

Keep the local single-column Grid declaration as `repeat(1, minmax(0, 1fr))`,
as in the existing preview. Reusing Root's exact `minmax(0, 1fr)` base atomic
class can inject that base rule after its desktop media rule in development,
leaving four named areas with only one explicit column and narrowing Main.
Both build modes must verify the actual main width after sign-in and reload.

## Closed Complaints UI correction (22 October 2026)

The current operations entry supersedes the earlier read-only candidate's layout
described above. `ui.txt` is the review brief, not a production data source.
The recovery slice below resumes the work paused for this correction.

Applied official references, consulted 22 October 2026:

- [Tabs](https://atlassian.design/components/tabs/usage): mutually exclusive
  Complaints/Reports destinations and report views, real tab/panel semantics.
- [Form](https://atlassian.design/components/form/usage): visible labels,
  bounded input widths, field errors and retained entries; account settings
  have a 480px maximum, creation a 672px maximum.
- [Button](https://atlassian.design/components/button/usage) and
  [Lozenge](https://atlassian.design/components/lozenge/usage): one primary Create,
  subtle Settings/Refresh icons, explicit context actions, readable Open,
  Reopened and Closed states with more than colour alone.
- [Pressable](https://atlassian.design/components/primitives/pressable/usage)
  and [MetricText](https://atlassian.design/components/primitives/metric-text/usage):
  the complete KPI card is one labelled, keyboard-operable filter action, not
  three repeated View complaints buttons. Existing Button cannot express this
  stacked statistic layout; Pressable provides the native button/focus contract.
  Zero-count filters are disabled. MetricText uses the supplied metric token.
- [Modal dialog](https://atlassian.design/components/modal-dialog/usage):
  contextual creation/update/export tasks with focus containment, Escape,
  heading, close action and return focus. The pinned Modal Dialog dependency
  cannot satisfy the existing React peer contract, so it was not installed.
  Intentional narrow exception: native `dialog.showModal()` supplies these
  browser semantics around existing ADS Form/Button/Heading content. No peer
  override, forced installation or replacement component library was added.
- [Section message](https://atlassian.design/components/section-message/usage):
  actionable read errors remain with their task; routine pending publication is
  one compact summary, not eleven competing warning cards.
- AG Grid official [installation](https://www.ag-grid.com/javascript-data-grid/installation/),
  [theme](https://www.ag-grid.com/javascript-data-grid/theming/),
  [grid interface](https://www.ag-grid.com/javascript-data-grid/grid-interface/)
  and [accessibility](https://www.ag-grid.com/javascript-data-grid/accessibility/):
  Community 36.1.0 matches the existing Mini App dependency. Current web docs
  describe a later minor; the exact installed APIs/types were checked as well.

The staff shell is bounded to 1280px, with a 384px queue and the remaining
width for detail above 1024px. Below that, selection opens detail with Back to
complaints. Desktop filters remain available while detail is open. ADS Tabs
panels use flex layout: their immediate content explicitly fills available
width, so an intrinsic-width Stack cannot leave half the page empty. Spacing
uses ADS tokens rather than the Design Lab's unapproved candidate scale.
Use the system typography without custom fonts or shrinking dense content.
The action cluster wraps at enlarged text sizes. A scrollable wrapper preserves
the unmodified ADS report tab labels at 200% text rather than truncating them;
keyboard focus can scroll within it. Dialog launch controls stay mounted so
Escape/Close can restore focus to the actual opener.

Settings is its own route, not a card stacked over Reports. Creation and saved
complaint actions are modal tasks. Description, activity and the single saved
attachment list precede actions. A legacy complaint with no saved creation
event may show its actual reported time; never invent its creator. Cameras
appear in narrow-screen capture layouts; file selection remains available.
This viewport rule is not a claim of physical-camera detection.

Reports default to Last 30 days. Date/Group by/Count by are bounded controls;
custom dates appear only when selected. Extra facets and help are disclosed.
Human-readable dates are display values only; canonical requests use ISO dates.
The three KPI comparisons use equal preceding calendar ranges, with no invented
good/bad target. The redundant outcomes chart is removed; a single category is
a text total. Temporal and categorical charts retain distinct chart choices,
real time spacing, headroom, legends above and subdued non-zero labels.

The table is actual AG Grid, not an HTML imitation. Its seven resizable columns
sort the full canonical report query before paging. It uses ADS colour/font
tokens, keyboard cell navigation and Enter/click opening. Narrow screens scroll
inside the grid, not the workspace. A reference becomes a workspace link only
when its complaint belongs to the currently authorized group; existing global
report scope does not grant access to another group's detail. The native Grid
adapter and SVG chart styling are documented application-specific exceptions.
No Enterprise code, chart engine, remote font or new proprietary asset is used.

Intentional differences from the brief: staff-authorized National IDs stay
visible as previously requested; safe existing History URLs are retained
instead of adding a competing hash router; no unavailable app switcher,
fabricated reporter, placeholder account/avatar, target colour or live-data
claim is added. Fixture data and review credentials belong only to loopback.
These are source-bound candidates, not human approval of a shared standard,
Phase 6 permission, real-device certification or production activation.

## Closed Complaints form recovery (22 October 2026)

Current official [Form](https://atlassian.design/components/form/usage),
[Section message](https://atlassian.design/components/section-message/usage) and
[Button](https://atlassian.design/components/button/usage) guidance was consulted
again on 22 October. Retain entered values and field errors; put an actionable,
persistent connection/session/uncertain-save message inside the affected task.
Do not turn normal editing into a warning wall or silently retry a write.
The revised tabs, dialogs, AG Grid, typography and spacing are preserved.

Creation and case-action forms resume only after current native sign-in and
owning-workflow bootstrap. One bounded task (including at most 30 MB of chosen
files) lives in tab memory outside the authentication component. An opaque
server-owned account/security-generation binding gates reuse. Other accounts,
security-generation changes, explicit sign-out, confirmed discard/navigation
and successful canonical saves invalidate old callbacks and retained entries.
Reload/tab closure loses unsaved memory; an explicitly saved server draft
remains available. There is no customer/credential browser storage or URL state.
This is not an approved offline-data retention/privacy policy for real staff.

A timed-out/disconnected write keeps its exact request key, values, expected
revision and File objects. Retry is explicit, not triggered by reconnect or MFA.
Intentional, narrow ADS exception: submitted inputs are temporarily read-only
while saving or confirming an uncertain result. The visible explanation and
Retry previous save action explain why; ordinary editing is interactive. A
confirmed Leave without checking escape explains that a save may already have
completed, so access loss cannot trap the user inside a modal. No success is
claimed until the server confirms it. Revision conflicts require reviewing the
latest case, not silently upgrading the submitted revision.

Offline editing is allowed. Quiet session-check network failure may retain
the already-visible operations workspace, but an actual 401/revocation never
does; hidden-page checks still remove sensitive content until reauthorized.
The option defaults off for every other StaffAccess entry. Draft save/discard
uses a bounded request and reads the current draft before another write, so a
lost response is reconciled without overwriting a newer device's revision.
Back/Forward cancellation restores the real same-document history position;
history stores only a numeric cursor and existing safe route controls.

Scope: complaint creation and case updates, not unsaved preferences, scheduled
email editors or report-email tasks. Those and real-provider/network/device
acceptance remain explicit release gates. Sources/screenshots are candidates,
not human design approval, a Telegram migration or production activation.

## Specification 18: closed Complaints composition (23 October 2026)

The current native operations candidate implements
[Specification 18](https://github.com/bedanavrvm/HB-Biogas-Telegram-Bot/issues/18).
It supersedes the earlier three-card/report-grid and confirmation descriptions
above. The existing reviewed package graph is retained; no dependency was added.

Official usage/design guidance rechecked on 23 October:

- [Elevation](https://atlassian.design/foundations/elevation/) and
  [typography](https://atlassian.design/foundations/typography/): distinct canvas,
  ordinary panels and overlays; token typography, readable metadata, and one
  six-card metric composition. No proprietary fonts or brand assets are added.
- [Modal dialog](https://atlassian.design/components/modal-dialog/usage/): named
  immediate tasks, consistent header/body/footer, inert background, body scroll
  locking, Escape/scrim dismissal and focus return. Dirty/uncertain forms retain
  their existing protection. A scrim dismissal requires both pointer endpoints
  outside; text selection ending outside does not close the task.
- [Icon button](https://atlassian.design/components/button/icon-button/usage/)
  and [tooltip](https://atlassian.design/components/tooltip/usage/): direct theme
  switching uses the installed IconButton's actual tooltip API. Recognizable
  icons retain meaningful labels; account actions use the existing action menu.
- [Select](https://atlassian.design/components/select/usage/): searchable choices
  stay in the active modal layer with bounded internal menu scrolling.
- [Flag](https://atlassian.design/components/flag/usage/): concise semantic icon,
  title and message, useful recovery and bottom-left placement. The user's
  explicit contract differs from ADS bold-flag dismissal: warnings/errors remain
  dismissible and persistent; success/information expire after five seconds,
  paused on hover/focus. At most three appear, with FIFO queuing and deduplication.
- [AG Grid layout](https://www.ag-grid.com/javascript-data-grid/grid-size/):
  auto-height rows within one report scroll, with 25 server rows per page.
  Whole-query sorting remains server-owned; unsupported timing/target sorts
  are not advertised. The moving row index is optional; Reference is primary.

Intentional bounded compositions: the existing native `dialog` wraps pinned
ADS Form/Button/Heading content instead of adding the incompatible modal
package. It retains the existing h2 task heading and explicit aria-labelledby.
The calendar composes existing ADS Pressable/textfields/selects; the notification
host composes existing primitives/icons; native popovers supply top-layer menus.
No native alert/confirm/prompt or browser date picker supplies an application
decision. OS file/camera pickers and beforeunload remain necessary exceptions.
Live geometry adjusts mobile input size, available pane height, text enlargement,
three/two/one metric columns and the AG Grid header's scroll position.
These adjustments use the installed controls and tokens, not a second palette.
Charts retain first-party SVG geometry with keyboard marks and visible textual
details; chart choices and help use product controls.

Protected, lazy image/PDF thumbnails use the owning evidence endpoint. Upload
state, unsupported/unavailable previews, saved uploader/size/date, attachment
navigation, PDF pages and original download remain separate concerns. Data URLs
are transient and requests abort on unmount; originals are downloaded only on
explicit request. Uploads still belong only to Create and Resolve.

Full authorized IDs stay visible/copyable. Queue ordering/navigation is stable
across server pages and a successful resolve rechecks the next item's current
membership. Report-only search combines with selection for Excel/email without
changing KPI/chart populations. Timing comparisons and coverage come from the
canonical cohort projection; incomplete response coverage is explained inline.
Small positive chart durations that round below the displayed precision use
`<0.1`; a recorded zero remains `0`, including when the shared axis uses days.
This preserves readable labels and visible timing context under the typography
and tooltip guidance above; it adds no new control or visual exception.

Builds, screenshots and code reviews are candidates, not approved baselines.
The current runbook records executed checks, limitations and rollback. No
Telegram restyling, workflow grant, production mount or human/device/privacy
acceptance follows from this change.

## Persistent local Complaints demo (P2a.1 / ADR 0071)

The separate `complaints-demo.html` entry reuses that same workspace with an
injected synthetic reader, explicit "Local demo · Synthetic cases" page context
and an Exit demo action. It opens directly into review. Exit shows a short ADS
task with a working Open demo button; it never presents credential fields or
claims company authentication. Default staff composition/transport is unchanged.

Current sources consulted 20 October 2026:
- https://atlassian.design/components/navigation-system/layout/code
- https://atlassian.design/components/section-message/usage
- https://atlassian.design/components/primitives/text/code

Root owns immediate TopNav/Main slots. Text supplies ordinary persistent page
context; no error/warning SectionMessage is added for the normal demo state.
Existing SectionMessage continues to handle actual read failure/retry. ADS
Button/Heading/Box/Stack compose the exit task. No new asset, palette, component
library or layout exception is introduced. The existing compact filter toolbar
exception remains documented above. Synthetic captures/technical checks do not
approve a Telegram standard, certify design quality or open an operational gate.

## Complaints manual-audit corrections, 23 October 2026

The repair candidate is tracked in
`docs/ui-standard/reviews/2026-10-23-complaints-ui-repair.md`, against F01-F39
of the manual audit. Source bindings remain candidates; the original audit,
approved baselines and Telegram migration hold remain unchanged.

Official guidance consulted for these corrections:

- [Navigation layout](https://atlassian.design/components/navigation-system/layout/code):
  omit an unused middle slot so branding and real actions retain their space.
- [Form usage](https://atlassian.design/components/form/usage): required markers,
  field-linked errors, first-error focus and dependent location choices.
- [Calendar usage](https://atlassian.design/components/calendar/usage) and
  [Pressable](https://atlassian.design/components/primitives/pressable/code):
  complete numeric dates, editable year text, visible selected days and labels.
- [Modal dialog usage](https://atlassian.design/components/modal-dialog/usage):
  focused tasks, case identity, a bounded body and readable action footer.
- [Checkbox usage](https://atlassian.design/components/checkbox/usage):
  the existing Open next checkbox semantics now have a checked/unchecked icon.
- [Section message usage](https://atlassian.design/components/section-message/usage):
  one persistent queue error with Retry; offline guidance inside active forms.
- [Data visualization color](https://atlassian.design/foundations/color/data-visualization-color):
  token-backed radial legend swatches identify their matching chart series.

Existing bounded exceptions continue: native dialog/popover semantics compose
installed ADS controls; no additional package is installed. Calendar day cells
use the installed Pressable with token typography, surfaces and visible focus,
without Button's truncating text wrapper. Custom SVG charts and AG Grid remain.
Mobile register rows use ADS text, buttons, status and selection controls rather
than a horizontally clipped grid. Only long narrative desktop columns wrap;
short fields retain compact rows and the reference stays pinned.

The queue/detail split uses the supported 90rem breakpoint; narrower screens
show one working pane with Back navigation. Auto-fit grids use available width
for facts, fields and attachment cards. Runtime geometry keeps existing dialog
footers readable and fits the evidence viewport around its actual controls;
Fit page preserves image aspect ratio, while Fit width/zoom retain scrolling.
This is application layout, not a new palette, type scale or component library.

Report filters edit a local draft until Apply; invalid dates cannot apply.
Each report tab shows its own metrics and timing coverage. Single-point charts
use complete text; radial legends include swatches. Account names and safe sync
timestamps come from the existing authorized actor/record projections. No raw
provider diagnostics, broader access or new workflow state is introduced.

## Complaints detail: Stitch candidate, 28 October 2026

The user-approved detail-first layout supersedes the desktop split for the
selected native operational complaint. It keeps one vertical stack at every
width, a compact action toolbar, two-column metadata, read-only description,
recorded Portal-style map, protected attachments, and Conversation/History tabs.
The queue remains its own destination with retained in-memory filters.

Current official ADS Comment, Tabs, Form, Button and Modal guidance, applied
behaviour, deliberate native-input/thread compositions and Playwright evidence
are recorded in [the source-bound review](../docs/ui-standard/reviews/2026-10-28-complaints-stitch-detail.md).
This introduces no new design-system dependency or approved baseline.

## Additional Stitch components, 28 October 2026

The later user-directed [detail corrections](../docs/ui-standard/reviews/2026-10-28-complaints-ui-corrections.md)
replace the large publication panel with contextual file progress and a compact
register status, and revise threads, actions, fields, maps, tabs and notifications.
For ongoing UI iterations, use browser interaction/screenshots only: no test
suites, assertion scripts or test files. Builds are only for previewing changes.

The [decision record](STITCH-DESIGN-DECISIONS.md) maps all new supplied references
to adopted behavior and the user's explicit exclusions. Real skeletons, semantic
feedback, clipboard confirmation, drop selection, SLA/help and two whole-queue
sorts compose the existing single-column browser. Validated browser file receipts
and canonical saves queue independent Drive/Sheet publication with measured
progress, retained originals and scoped IT recovery. Telegram publication remains
unchanged. [Evidence and limits](../docs/ui-standard/reviews/2026-10-28-complaints-stitch-components.md)
and the [worker runbook](../docs/runbooks/complaints-browser-publications.md)
describe deployment requirements; no worker or production release is activated.
