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
typing or flash the page. Setup/enrollment UI remains a separate increment;
its support handoff must not be mistaken for completed onboarding.
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
