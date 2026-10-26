# ADR 0066: bounded React/ADS browser build and local preview

## Context

The user explicitly selected React/Atlassian Design System, required dependency
review, rejected treating a custom wireframe as ADS, and now instructed
"resolve it and proceed". This authorizes resolving and installing the bounded
frontend tooling/components locally. It does not authorize production admission,
deployment, grant changes or Telegram migration. Existing uncommitted source-only
preview work is retained as historical review evidence.

D13a records exact artifact evidence but uses broad forensic React overrides.
One original peer is incompatible: analytics-next-stable-react-context 1.0.1
declares React ^16.8.0 although its tiny context module uses createContext and
the consuming analytics-next 12.6.0 declares React ^18.2.0. React 19 is unsuitable
because other current Atlaskit packages require React 18. Local system Node 26
is outside the chosen build range. Missing licence-file indicators, branding
assets and runtime feature-gate behavior require concrete handling.

## Decision

Create an isolated `browser/` workspace for the exact reviewed React 18.3.1,
ADS login/form/provider/token components, TypeScript, ESLint and supported
Parcel/Compiled build. React/ADS components replace the custom wireframe in the
new preview. Native HTML wireframes are insufficient to demonstrate the user's
chosen component library. Parcel is preferred to experimental Vite integration;
the root Telegram dependency/build pipeline is retained.

Resolve a fresh scripts-disabled review lock with only the exact legacy-context
React override, not a global React/ReactDOM override or force/legacy-peer flag.
Accept that narrow local compatibility exception only with shipped-source hashes,
one React renderer, original-peer accounting and actual strict-mode context/
component browser tests. Do not describe it as upstream declared support.
If the actual resolution needs further exceptions, record and resolve them
explicitly rather than broadening overrides silently.

Use Node 22.23.3, downloaded from the official distribution with SHA-256
verification into ignored local tooling, without replacing system Node. Add
neither a runtime downloader nor an automatic package install to application
startup. Keep npm lifecycle scripts disabled; inspect any native tool needed
before explicitly executing the build. The initial audit found the dev-only
selector-parser CPU-exhaustion advisory GHSA-rj75-hqrm-r3gf. Resolve that edge
explicitly to fixed 7.1.6, with selector parsing and actual Compiled production
build checks. This is a separate security override, not another accepted React
peer mismatch. Use supported ESLint 10.13.0 instead of the now-deprecated
original 9.39.4. Reinspect changed exact artifacts and rerun the audit; no audit
finding is hidden by an exception or ignore flag.

Resolve notices for the exact runtime code, retaining package licence/NOTICE
texts and official upstream terms where omitted. Use only identified OSS code,
company text/system fonts and generic component-generated UI glyphs. Exclude
Atlassian logos, proprietary fonts, illustrations and brand glyph modules/assets.
Inspect the emitted module graph and browser network rather than assuming
tree-shaking or package licence metadata clears every design asset. Local dev
tools/native binaries are not distributed as application assets; production
distribution and operational maintenance acceptance remain release obligations.

Serve the built React demo on loopback independently of Django. Demonstrate
password/setup/MFA/enrollment/recovery states with a deterministic in-memory
transport and clearly labelled demo credentials. No real account provisioning,
proof delivery, backend auth mount, business data or grants. Build outputs,
node_modules and screenshots are ignored. Record component/source versions,
keyboard/mobile/failure evidence, notices and a reproducible build manifest.

## Consequences

### Browser-wide ADS adoption follow-up — 20 October 2026

The user's explicit request for full design adoption applies to all existing and
future pages in the standalone browser frontend. Replace P1c.1's custom layout,
native review selectors, hand-styled introduction and visual CSS overrides with
ADS Box/Grid/Inline/Stack/Anchor, Heading/Text, Button/LinkButton, form and status
components. Use the supported `@atlaskit/css` cssMap/xcss API, typed semantic
tokens and ADS responsive breakpoints. Enforce both lint plugins' complete
recommended rule sets, including advisory rules, as errors. Remove the native
class/global stylesheet exemptions rather than carrying them forward.

Promote only the already installed, archive-reviewed `@atlaskit/css@1.1.7` and
`@atlaskit/visually-hidden@4.4.0` to direct dependencies; do not resolve new
archives or relax peers. The existing font/image/brand-asset exclusion remains:
use ADS typography tokens unchanged with their supplied system-font fallbacks,
without shipping font files or injecting first-party font overrides. Layout
geometry such as content width has no corresponding visual token; keep it in
typed cssMap declarations, with no custom palette, type scale or breakpoint.
Read-only credentials are an explicit synthetic-demo exception, never a pattern
for operational forms. These decisions do not authorize Telegram migration,
production distribution or operational authentication.

The preview can honestly demonstrate actual ADS components. Exact dependencies,
the one documented peer exception, build/notice generation and source inventory
become maintained browser-workspace concerns. Build tooling is additional work;
it is not permission to change existing Mini Apps. Browser authentication stays
off, E006 blocking and production routes unmounted. M1 remains open for actual
mail/recovery/cache/privacy/support/staging and PostgreSQL acceptance.

Normal rollback stops the loopback preview and reverts this bounded workspace,
tooling/docs only. No migration/schema reversal, environment secret, staff,
credential, session, audit or workflow-data change is required. Production
static delivery and cache compatibility need a later reviewed integration.

### Viewport-layout follow-up — 20 October 2026

Viewport-layout follow-up (user-approved plan, 20 October 2026): compose the
browser access surface as a responsive ADS Grid using the available width.
Keep fields readable while placing guidance/status alongside them, use wider
workspace/help/recovery grids, reduce outer spacing through existing tokens,
and place compact preview controls beside content on desktop. Verify all pages,
errors and expanded controls at 1280x720, 1366x768 and 1440x900. Keep natural
scrolling for mobile/enlarged text; never clip content, shrink typography or
force a fixed-height viewport. No dependency or operational boundary changes.

## Alternatives considered

### Documentation-led composition correction — 20 October 2026

The user's "fix the issues ... always refer to the atlassian docs" instruction
authorizes correcting the researched browser design issues, including the
specific ADS components necessary for those corrections. Before installation,
resolve and inspect the exact graph for navigation-system 11.3.1, side-nav-items
2.5.8, section-message 10.2.6 and select 23.1.3. The existing primitives remain
appropriate for content but do not supply the supported responsive application
frame, persistent section feedback or accessible option-list behavior. Reusing
the prior popup-plus-duplicated-error and button collections would retain the
identified problems. Keep the one original peer exception, strict checks,
scripts-disabled installation, notices and proprietary-asset exclusion.

Use separate focused, single-column access tasks and a Navigation System
workspace. Keep description, persistent form feedback and inputs in reading
order; use default surfaces with borders and neutral grouping instead of sunken
boxes nested on raised surfaces. Use the documented fixed-wide content grid
(1296px including margins) for the workspace. Move Page/Theme/Response controls
to a separate review entry with labelled ADS selects. Normal access pages retain
one clear demo notice and read-only fixed values, without repeated field warnings.
No authentication, grant, workflow or production activation is introduced.

Implement against the official Form usage, Section Message usage, Elevation,
Grid and Navigation System layout/migration documentation. Record sources and
the distinction between technical checks and visual acceptance in the existing
decision record. Future browser UI work must recheck relevant official docs.

References: https://atlassian.design/components/form/usage ;
https://atlassian.design/components/section-message/usage ;
https://atlassian.design/foundations/elevation ;
https://atlassian.design/foundations/grid-beta/applying-grid ;
https://atlassian.design/components/navigation-system/layout ;
https://atlassian.design/components/navigation-system/migration-guide .

- Ship the custom wireframe as the selected client: does not meet the user's
  requirement to use ADS.
- Force/legacy-peer or global React overrides: conceal incompatible contracts.
- Downgrade to React 16 or switch to React 19: conflicts with current ADS peers.
- Replace ADS with a different design system: not requested or authorized.
- Publicly deploy or mount dormant auth handlers for the preview: unnecessary
  and fails the remaining operational gates.

## References

- https://atlassian.design/license/
- https://atlassian.design/get-started/develop/atlassians
- https://react.dev/reference/react/createContext
- `codebase-analysis-docs/assets/BROWSER_REACT_ADS_DECISION.md`
