# Component index and migration hold

The 27 October Origination header removal action and document-specific setup
diagnostics reuse existing header icons, confirmation sheets, Admin task links
and autosave. Source and synthetic behaviour evidence are recorded in
`reviews/2026-10-27-origination-header-and-setup-errors.md`; approved baselines and
the Phase 6 hold remain unchanged.

The 26 October Portal corrections reuse the existing settings summaries, HB
forms/history, shared chart icons/help, scoped recovery controls and secure
media viewer. Compact reports, launch-bound non-customer preferences, preview
rotation and deposit-date display are recorded in
`reviews/2026-10-26-portal-improvements.md`. This is a bounded user-requested
correction; original baselines and Phase 6 approval remain unchanged.

Specification 18 (23 October) completes the native Complaints candidate's queue,
detail, protected evidence and reporting composition. Shared product dialogs,
calendar, notifications, thumbnail gallery and report metrics reuse the pinned
ADS graph. Current official references and deliberate compositions are in
browser/DESIGN.md; source-bound verification and rollback are in the browser
channel runbook. The source ratchet records candidates only: no approved
baseline, Telegram migration, workflow authority or production activation.

The 23 October settings/schedule/email recovery extension reuses tab-local
`workspace-recovery.ts` through `workspace-task.tsx`, with the existing ADS
SectionMessage/Button task feedback. Exact pending requests and confirmations
survive same-owner reauthentication; no persistent browser data or new visual
standard is introduced. Evidence: browser/DESIGN.md and browser-channel-parity
runbook. Telegram candidates/baselines and the Phase 6 hold are unchanged.

The 23 October browser Complaints composition correction extends the existing
shared `complaints-ui.tsx`: fixed dialog header/body/footer, named status/action
slots, adaptive menu placement and the explicitly requested green-positive
ActionButton adapter. It reuses the pinned ADS controls and tokens. Direct theme
switching, grouped workspace/attachment actions and mobile metric layout are
candidate-only; current references and narrow exceptions are in
browser/DESIGN.md. No approved baseline, Telegram UI or Phase 6 hold is changed.

The responsive browser Complaints correction adds `browser-interactions.tsx`
(provider-owned theme, event toasts and measured viewport panes) and
`complaints-report-filters.tsx` (collapsed fine-grained report filters). Existing
ADS forms/dialogs, AG Grid and SVG charts remain the source patterns. The native
browser evidence adapter adds bounded PDF page previews. Current references,
storage/geometry/native-popover exceptions and evidence are in browser/DESIGN.md
and docs/runbooks/browser-channel-parity.md. Candidate only: no baseline approval,
Telegram migration, permission expansion or production activation.

The 22 October recovery slice adds `browser/src/workspace-recovery.ts` for one
owner-bound, tab-local unfinished task and extends the existing operations
forms with connection/session feedback and explicit same-request retry. It
preserves the revised UI and AG Grid. Current references, the temporary
read-only-input exception, scope and evidence are in `browser/DESIGN.md` and
`docs/runbooks/browser-channel-parity.md`; no approved baseline changes.

The 22 October `ui.txt` correction adds `browser/src/complaints-ui.tsx` (actual
ADS Lozenge, human dates and the documented native-dialog composition) and
`complaints-report-table.tsx` (actual AG Grid Community, token theme, full-query
sorting and keyboard row opening). Operations tabs, master/detail, contextual
actions, bounded preferences and compact reports reuse the native shell.
Official references, intentional differences, source-bound review evidence and
the subsequently resumed reliability slice are recorded in browser/DESIGN.md and
docs/runbooks/browser-channel-parity.md. This does not approve candidates,
replace legacy baselines, migrate Telegram or enable production browser access.

ADR 0073's navigation/preferences/activity slice adds
`browser/src/complaints-operations-history.tsx` and extends the settings/report
composition: labelled saved queue/branch defaults, safe URL state restoration,
and bounded older-activity/retry/refresh over current owning-workflow access.
It reuses ADS controls and tokens; the local review launcher is documented in
`browser/README.md`. These are source-bound candidates, not approved baselines.

ADR 0073's next reporting slice adds `browser/src/complaints-report-charts.tsx`
and extends `complaints-operations-reports.tsx`: outcome/cohort, resolution,
target, first-response, age and reopening views over canonical Complaint facts.
ADS selectors, adaptive charts and selection-to-table/Excel behavior are new
source-bound candidates. Current evidence, exception and handoff are in
`browser/DESIGN.md` and `docs/runbooks/browser-channel-parity.md`.

ADR 0073 adds the source-bound native operations candidate in
`browser/src/complaints-operations*` and `workspace-navigation.ts`: actual ADS
shell/forms/selection/feedback, fluid queue/detail, private media and reporting.
Native camera/textarea and interactive SVG exceptions are explicit in
`browser/DESIGN.md`. Evidence/remaining acceptance:
`docs/runbooks/browser-channel-parity.md`. No approved baseline or Telegram
appearance is changed; production stays disabled/unmounted.

P2a.2 / ADR 0072 adds `browser/src/{complaints-demo-api.ts,complaints-demo-forms.tsx}`
and extends the demo entry/shared workspace with explicit role/action slots.
Actual ADS Form/Field/MessageWrapper/Textfield/Select/Button/SectionMessage and
Grid compose intake, action feedback and evidence. The hidden native file input
is a bounded exception documented in DESIGN.md. Synthetic source/evidence are
recorded in decision section 15; approved patterns and migration hold stay.

P2a.1 / ADR 0071 adds `browser/src/{complaints-demo.html,complaints-demo-index.tsx}`
and the shared workspace's explicit synthetic-reader/context options. Actual ADS
Root/TopNav/Main/Text and Button/Heading/Box/Stack compose the no-account review
and Exit/Open task. Current sources/evidence are in decision section 14. This is
local synthetic availability, not an operational auth bypass or Telegram change.

P2a / ADR 0070 adds the separate closed Complaints candidate in
`browser/src/{complaints.html,complaints-index.tsx,complaints-transport.ts,complaints-workspace.tsx}`.
It composes native StaffAccess with actual ADS navigation, a responsive
queue/detail Grid, labelled search/status controls and persistent feedback.
Its source-bound isolated browser evidence is recorded in decision section 13.
This is no operational mount, human design approval or Telegram migration.

The executable inventory is `ui_review.catalog.PATTERNS`; the lab projects it
without a second editable component dictionary. It groups 31 patterns into
Foundations, Navigation, Queues, Forms, Actions, States, Evidence, Reports and
Details. The source manifest shows exact paths and hashes for each alternative.

The new standalone browser workspace now installs/builds the exact locally
reviewed React/ADS graph (ADR 0066). The current entry is a synthetic demo, not
operational authentication. The 31-pattern Telegram inventory does not approve
the React design or authorize Telegram migration. P1b.2a itself added no client.

Existing reusable implementations include MiniAppUtils (feedback, form/draft,
theme, main-action and request behaviour), MiniAppComponents (search, filters,
pagination and action primitives), SecureMediaViewer, report controls and the
Portal confirmation dialog. Audit actual callers before extracting/reusing one.

## Standalone browser composition — P1c.4

P1c.5 adds a separately built dormant transport candidate at
`browser/src/{access.html,auth-index.tsx,auth-transport.ts,staff-access.tsx}`.
It reuses the documented ADS form/feedback/navigation composition with real
editable fields, required legend, MessageWrapper and standard autofill.
Routine password/code sign-in, inline recovery and automatic stage resume
avoid extra confirmations. Source-bound native Django tests remain synthetic
and do not authorize operational mounting, completed onboarding, workflow
access or Telegram migration. ADR 0067 and decision section 11 govern it.
The following fixed-value preview and its four source bindings remain separate.

P1c.6 / ADR 0068 extends those same dormant source candidates with guided native
first-password, QR/manual-key enrollment and one-time recovery-code handoff.
Box renders the locally generated credential QR; Grid arranges recovery codes.
Transient credential content is masked in captures. Current evidence/limits are
in decision section 12; no Telegram candidate or migration hold is changed.

Current source: `browser/src/{index.html,index.tsx,preview.tsx,review.html}`.
The user's documentation-led correction supersedes earlier geometry and
overbroad design-adoption claims. Component/token coverage, lint and viewport
fit do not establish design quality. Follow browser/AGENTS.md and DESIGN.md,
consulting the current official guidance before every browser UI change.
Open http://127.0.0.1:8766/ after the bounded build/server commands in
`browser/README.md`. Package versions, licence/asset decision and exact review
binding are in `browser/DEPENDENCIES.md`, package/lock and dependency-review JSON.
This is actual compiled React/ADS code; the business/auth transport remains a
fixed-value in-memory demo. Source hashes remain candidate-only in the ratchet.

| Source-bound component | Exact package/version and entry | Use |
|---|---|---|
| Root provider/theme | app-provider 8.1.0, `app-provider` / `use-set-color-mode` | Supported light/dark/auto theme context |
| Reset/tokens | css-reset 8.4.6, tokens 20.6.1 | Official reset and typed token() calls; no authored raw visual values/token fallbacks |
| Typed styling | css 1.1.7, cssMap/cx | Compiled xcss; checked ADS 48rem breakpoint and app-specific content geometry |
| Button / LinkButton | button 25.5.0, `default/button` / `link` | Primary/loading, review toggles, navigation and disabled workflow actions |
| Staff forms | form 18.2.0, Form/Field/FormFooter/HelperMessage | Provider-owned labels/IDs and fixed demo credential fields |
| Text field | textfield 10.2.6 | Password, staff username, MFA and confirmation values |
| Heading | heading 8.0.0 | Access-page and workflow-card semantic headings |
| Box/Grid/Inline/Stack | primitives 22.6.0, individual `compiled/*` entries | Coherent single-column tasks, flat groups and responsive content grids |
| Text/Anchor | primitives 22.6.0, individual `compiled/*` entries | Token typography, navigation and keyboard skip link |
| VisuallyHidden | visually-hidden 4.4.0 | Screen-reader response announcements |
| Navigation frame | navigation-system 11.3.1, Root/TopNav slots/Main/SideNav | Distinct access tasks and workspace shell; built-in skip links/collapsible navigation |
| Side-nav items | side-nav-items 2.5.8, LinkMenuItem/MenuList/MenuSection | Actual navigation semantics and selected overview |
| Persistent feedback | section-message 10.2.6 | Form-wide errors directly before fields; one message, no popup/duplicate paragraph |
| Review selection | select 23.1.3 | Labelled Page/Theme/Response controls only on /review.html |

The flow meanings remain those in the table below: setup/enrollment never grant
assurance; fresh login follows; tools remain disconnected. Runtime/graph/notice checks
prove the components are bundled. Headless screenshots and simulated errors are
review evidence, not human approval or native backend/device/accessibility proof.

P1c.2 removes the custom stylesheet, native select controls, layout classes,
hand-styled introduction, global typography/focus overrides and blanket lint
exemptions. Both ADS plugins' complete recommended rule sets, including advisory
rules, are enforced as errors for all browser source. One line-scoped exception
keeps synthetic credential fields read-only; it does not govern real forms.
ADS typography tokens remain unchanged and use their supplied system-font
fallbacks. No proprietary font, logo, brand glyph or illustration is shipped.
Content widths/grid geometry use typed cssMap because ADS has no corresponding
visual tokens. This is normal application composition using ADS primitives,
not an alternative palette, type scale, component skin or breakpoint system.
The exact graph, peer/security exceptions and asset decision remain binding.
Source-bound runtime evidence and remaining human/device gates are in decision
section 8. Browser-wide implementation permission is not screenshot approval.

Historical P1c.3 implemented the user-approved viewport plan (decision section 9). Normal
desktop layouts use the available width, keeping only fields constrained.
At ADS md (64rem), guidance/status and compact controls use adjacent columns;
workspace tiles use four columns. Below md, guidance precedes form actions and
controls follow the page in natural document flow. Help/recovery grids use ADS
sm. All eleven pages and form errors must fit the three declared desktop sizes
with controls open/closed, without clipping, hidden content, fixed heights or
smaller typography. Mobile/enlarged text keeps natural vertical scrolling.

P1c.4 corrects the composition using official Form, Section Message, Elevation,
Grid and Navigation System usage/migration documentation (browser/DESIGN.md).
Access descriptions/feedback remain with the form; default surfaces and neutral
groups replace the raised-page/sunken nesting. Workspace content uses the
fixed-wide grid including margins. The independent review entry avoids mixing
scenario controls into the staff presentation. Exact graph, notice/asset review,
source-bound evidence and remaining gates are in decision section 10.

Live Django/Telegram UI, source baselines and Phase 6 hold remain unchanged.
Production CSP/nonces, native auth/CSRF, real devices, support and M1 remain open.

## Historical standalone access wireframe candidates

The first-party review sources are
`codebase-analysis-docs/assets/browser-access-preview/{index.html,preview.css,preview.js}`.
They form a synthetic analysis artifact, **not** a React/ADS implementation or
an operational authentication surface. No third-party assets/tokens are used.
Exact source hashes and candidate-only review references are in `registry.json`.
The browser component mapping below is proposed meaning only; an accepted
React/ADS version/component inventory still precedes the actual client.

| Candidate | Owning backend meaning | Review coverage |
|---|---|---|
| Staff sign-in | `staff_auth.browser_api.password_login` | Fixed demo fields, busy, generic error, retry and enrollment-required |
| Mailbox proof / first password | `staff_auth.setup_api` | No dispatch claim; setup completes at fresh login; expiry/support handoff |
| Authenticator / recovery sign-in | `staff_auth.browser_api.authenticate_mfa` | Mode switch, same-page failure and demo shell transition |
| Authenticator enrollment | `staff_auth.enrollment` | Fresh password, secret-free placeholder and activation step |
| Recovery handoff | `enrollment_recovery_codes` | Separate reveal, invalid labels, no repeated viewing in the same page session |
| Reauthentication | Backend `reauthentication_required` state | Setup alone supplies no assurance; explicit new password/MFA login |
| Workspace / help | Future workflow authorization / existing administrator | Disabled business tiles, ordered pilots and no fabricated support submission |

All are **unapproved candidates**. The real wireframe shell has source-faithful
light/dark captures at 320/390/1440 pixels, synthetic failure/retry journeys,
keyboard skip/focus and a 200% text-size check. This is not real-device,
assistive-technology, ADS, native MFA, CSRF or design approval. Screenshot/report
commands and limits: `BROWSER_REACT_ADS_DECISION.md` section 6. The live Mini App
catalogue, source baselines and Phase 6 migration hold are unchanged.

Candidate foundations are isolated in the lab's tokens/theme files. A user may
preview Telegram or JBL plus Automatic/Light/Dark and three density choices.
No app consumes these files. An approved standard will identify the winner,
allowed variants and governed consumer modules after human review.

## Migration package required after approval

For each selected pattern, record the exact approved revision and decision,
existing consumers, target shared implementation, intentional variants, covered
states, before/after screenshots, affected workflow tests and rollback. Pilot
one pattern in one app before extending it to others. Remove old CSS only after
its final consumer has moved. Role grants and workflow semantics remain local.

**STOP:** this is preparation, not permission to start Phase 6. The user's
explicit migration approval must be obtained after reviewing that package.

## Complaints browser manual-audit repair candidate, 23 October 2026

The closed operations workspace now binds the existing ADS shell, Pressable,
Form/Label/Textfield/Select, checkbox semantics, task footer, status, feedback,
and report compositions to the F01-F39 corrections. The shared access shell also
removes its unused middle navigation slot. Relevant usage references and bounded
calendar/viewer/mobile-register compositions are recorded in `browser/DESIGN.md`.

Review: [repair record](reviews/2026-10-23-complaints-ui-repair.md).
Original audit evidence remains in `reviews/complaints-manual-audit-assets/`,
with separately prefixed repair captures. The source ratchet records the new
candidate hashes only; it does not authorize Phase 6, production browser access,
Telegram appearance changes or screenshot-baseline replacement.
