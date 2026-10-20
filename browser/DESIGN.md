# Browser design references and application decisions

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
