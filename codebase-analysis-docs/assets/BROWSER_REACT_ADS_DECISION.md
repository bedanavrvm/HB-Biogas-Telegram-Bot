# New browser frontend: React / Atlassian review gate

Decision date: 19 October 2026. Governing decision: ADR 0062,
`docs/adr/0062-browser-react-ads-and-headless-auth-boundary.md`.

## 1. Approved direction versus permission still needed

The user chose React and Atlassian Design System (ADS) for the **new standalone
browser client**, then explicitly chose **exact package/licence review first**.
Keep existing Telegram Mini Apps on their current Django/template/JavaScript
stack. Neither Telegram restyling nor forced company MFA inside Telegram is
approved. Pilot order stays Complaints → TAT → Origination → Portal.

No React/ADS package, font, icon, copied design asset or browser workspace is
installed/created by P1b.2a. `package.json`, its existing lockfile and the existing
Mini App asset build remain unchanged. The installed Python allauth distribution
can supply the dormant JSON authentication contract independently of this review.
This direction does not authorize Forge/Connect, Atlassian accounts/SSO, Jira,
Confluence, cloud hosting, analytics disclosure or an Atlassian subscription.

Do not treat a design-system selection as legal clearance or as acceptance of a
finished frontend. This is an engineering review record, not legal advice.

**Findings:** frontend direction is selected; installation is held.
**Open questions:** exact resolved dependency/asset scope and review acceptance.
**Next steps:** finish the review below before scaffolding or installation.

## 2. Licence findings and exact-package shortlist

The general ADS licence describes Atlassian-integrated uses and separately
recognizes identified open-source components. Individual packages therefore need
their own review; the general licence and an npm licence field are not
interchangeable permission statements. Font, icon and branding rights must not
be inferred from component code. [Atlassian Design System licence](https://atlassian.design/license/)

Read-only registry queries on 19 October 2026 returned this **preliminary
shortlist**, not an approved installation manifest:

| Exact package inspected | npm-declared licence | Role to evaluate |
|---|---|---|
| `@atlaskit/button@25.5.0` | Apache-2.0 | Button interactions; includes dependencies beyond a single primitive |
| `@atlaskit/tokens@20.6.1` | Apache-2.0 | Semantic tokens and theme support |
| `@atlaskit/primitives@22.6.0` | Apache-2.0 | Layout and primitive building blocks |
| `@atlaskit/css-reset@8.4.6` | Apache-2.0 | Browser styling normalization |
| `@atlaskit/app-provider@8.1.0` | Apache-2.0 | Provider/theme initialization, subject to chosen setup |

Sources: exact npm registry records available through
`npm view PACKAGE@VERSION --json`. Published component records for button,
primitives and app-provider advertise React peers `^18.2.0 || ^19.0.0`; the
current Atlassian setup guide describes a React 18 environment. This is not a
reason to pick React 19 automatically. Choose a compatible exact React/ReactDOM,
TypeScript and build tool set only after reviewing all proposed components.
[Atlassian developer setup](https://atlassian.design/get-started/develop/atlassians)

The five direct-package tarballs were downloaded to an OS temporary review
directory, not the repository or an installation. SHA-512 was checked against
each registry `dist.integrity`; each archive contains `package/LICENSE` with an
Apache-2.0 declaration. This establishes evidence for those direct artifacts,
**not** an entire dependency tree or permission for unrelated ADS assets.

Direct artifact SHA-256 records (the registry integrity comparison used SHA-512):

| Artifact | SHA-256 |
|---|---|
| `@atlaskit/button@25.5.0` | `0c068ab0b2137a6f0cb977ade5429c3f8af51617eb9a8e7c1307e68d7b95cd2d` |
| `@atlaskit/tokens@20.6.1` | `ce14020bc202d74dfa5852140f864723e9df8b40b2bde15f559677047df67e5b` |
| `@atlaskit/primitives@22.6.0` | `14d34d97ce4b9110d09543ee44ca275425744d14b3f53f994bd9573f97fcf7b4` |
| `@atlaskit/css-reset@8.4.6` | `842e9b2cb1c8521c951a9591b7190c7182ce7a44ec7ace2eed3fa20afb23b9bb` |
| `@atlaskit/app-provider@8.1.0` | `6d7c08dcb60fb9ef0a496286e15b2cabae649936371a254ce89c317e76cda7e9` |

For example, button 25.5.0 directly depends on `@atlaskit/icon` (`^38.0.0`),
`@atlaskit/theme` (`^28.2.0`), tooltip, spinner, analytics-next, Compiled, Emotion
and other packages. Top-level Apache declarations do not resolve their exact
versions or embedded asset terms. Tree-shaking is not a licence-review substitute.
There is no resolved browser lockfile or complete transitive report yet.
Additional metadata checks found Apache-2.0 declarations for
`@atlaskit/icon@38.0.0` and `@atlaskit/theme@28.2.0`; those are two dependency-range
minimums, not a resolved tree or a completed shipped-asset review.

### Installation gate

- [ ] Define the minimum login/shell component set and optional assets. Do not
  audit an imaginary complete enterprise frontend or install everything by default.
- [ ] Resolve exact React/ReactDOM, TypeScript, build/style/lint/test packages and
  all transitive versions in a review process that does not alter the production
  dependency manifests. Record registry provenance and integrity evidence.
- [ ] Inspect full shipped licence/NOTICE files, SPDX declarations, exceptions,
  embedded code/assets and distribution obligations for the resolved set.
- [ ] Review icon/font/theme assets separately, including dependencies that bring
  them indirectly. Do not import Atlassian logos, illustrations, proprietary fonts
  or brand identifiers without permission covering this standalone use.
- [ ] Record the intended deployment/distribution model, required notices and
  allowed packages/assets. Obtain qualified clarification for any conflict.
- [ ] Named reviewer records accepted/held/rejected scope and conditions. No
  assumption that an npm metadata field clears the whole design system.
- [ ] Obtain repository-required approval for the exact dependency/build addition.
  If permission cannot be established, return to the user with the evidence and
  options; do not silently switch design systems.

**Findings:** direct artifacts provide promising open-source evidence; the full
stack remains unreviewed. **Open questions:** resolved transitive licences and
asset permissions. **Next steps:** complete and accept the installation gate.

## 3. Technical frontend direction after clearance

Use one logically separate React workspace (proposed `browser/`) with a pinned
lockfile, source manifest and build outputs separate from
`core/static/miniapp/` and `origination/static/miniapp/`. The workspace is a plan,
not an existing folder or a new production service.

The current official setup recommends Parcel, documents Webpack support and
labels its Vite integration experimental. Select a supported style pipeline
with Compiled and token transforms rather than assuming a Vite scaffold will
work. A final build-tool dependency decision is still outstanding.
[Atlassian developer setup](https://atlassian.design/get-started/develop/atlassians)

Initialize tokens/themes deliberately with the supported provider or theme
function. Installing token code alone does not initialize a theme. Do not copy
the current Telegram Design Lab's candidate tokens into the browser app.
[Using tokens in code](https://atlassian.design/foundations/tokens/use-tokens-in-code)

Prefer same-origin Django delivery of the built shell and CSRF-protected API.
React owns rendering, navigation, form state and accessibility; Django remains
the only authority for staff identity, grants, validation, workflows and audit.
Do not store credentials, bearer tokens, customer drafts or MFA recovery codes
in localStorage. Company branding/system fonts are the starting design proposal;
do not misrepresent this JBL application as an Atlassian product.

Early component conformance must be demonstrated, not assumed: map each approved
component to its exact source/version, use semantic tokens and the supported lint
rules, and review keyboard focus, labels, validation, empty/loading/error states,
mobile layouts and assistive behavior. Extend the browser UI review inventory
before the first visual implementation. The existing Telegram UI source ratchet
still applies and is not a ready-made React compliance checker.
Prove the selected components work outside an Atlassian host and inspect runtime
network requests for unexpected remote fonts/assets/telemetry. Do not assume
that an open-source licence proves standalone compatibility or acceptable data
flows. No claim that the inspected packages send such data is made here.

**Findings:** a separate frontend need not introduce another backend or hosting
service. **Open questions:** approved versions/build and browser-review inventory.
**Next steps:** a small login/shell build only, after licence acceptance.

## 4. Milestones, costs and non-disruption checklist

| Gate | Deliverable | Must remain true |
|---|---|---|
| D13 review | Accepted exact dependency/asset/licence record | No unreviewed package/assets installation |
| P1b.2a, current | Dormant JSON auth contract and protected pending-secret storage | No production routes or Telegram credential changes |
| P1b.2b | Governed provisioning, enrollment/recovery, shared replay cache and support | No password-only business access or implicit grants |
| P1c | Reviewed React/ADS login and shell, build/notice/asset-isolation evidence | Root Telegram pipeline and cached WebViews retain compatibility |
| M1 | Real staging authentication, security, support and both-channel acceptance | Production admission still needs its own go decision |
| M2/M3 | Narrow Complaints read, then justified write and business review | TAT, Origination and Portal are not commissioned automatically |

The earlier P1 window must be re-estimated for a separate frontend, licence
review, build integration, component conformance, accessibility, testing and
handover. No new delivery dates or tiny-cohort percentage targets are invented.
Assign a maintainer and backup for React/ADS dependency updates in addition to
Django/allauth and the legacy Mini App frontend.

For each merge/deploy proposal, report dependency/notice changes, browser static
build and cached-bundle compatibility, CSRF/session behavior, ordinary-role
denials, Telegram regression, support observations and a compatible rollback.
Never overwrite existing Mini App URLs/assets to introduce the browser shell.

### STATE BLOCK

- INDEX_VERSION: browser-react-ads-decision-1 / 19 October 2026.
- FILE_MAP_SUMMARY: ADR 0062; implementation plan revision 5; config/settings.py;
  staff_auth/browser_api.py; staff_auth/session_protection.py; existing package.json;
  docs/ui-standard/README.md; docs/ui-standard/component-index.md.
- OPEN_QUESTIONS: exact transitive/asset licences, build/version selection,
  maintenance owners and M1 operational acceptance.
- KNOWN_RISKS: licence assumptions, unreviewed transitive assets, style/build
  incompatibility, two-frontend maintenance, cached bundles and CSRF confusion.
- GLOSSARY_DELTA: React browser client is a new presentation channel; ADS selection
  is not a Telegram migration, permission grant or compliance determination.

**Findings:** the next frontend action is review, not installation.
**Open questions:** owners/clearance and accepted build scope.
**Next steps:** finish D13 while completing separately gated backend controls.
