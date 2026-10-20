# New browser frontend: React / Atlassian review gate

Decision date: 19 October 2026; D13a evidence follow-up on the same date. Governing decision: ADR 0062,
`docs/adr/0062-browser-react-ads-and-headless-auth-boundary.md`.

Current P1c.6 / plan revision 16: section 12 records guided native initial-password,
QR enrollment and one-time recovery handoff under ADR 0068. Section 11 retains
P1c.5 sign-in evidence. Production auth stays disabled/unmounted; readiness and
M0/M1 acceptance remain open before the Complaints read pilot.

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

**Current finding, 20 October 2026:** the user's “resolve it and proceed”
instruction authorizes the bounded local React/ADS workspace in section 7.
Its exact graph, exceptions, notices and asset exclusions replace the install
hold for this local scope only. Sections 1–6 retain earlier review evidence;
the historical forensic graph is not relabelled as an approved client lock.
Production distribution, real authentication and M1 remain separately gated.
**Open questions:** production distribution/maintainers and native transport/M1.
**Current design follow-up:** the user's subsequent request for full browser
design adoption governs P1c.2 in section 8. It supersedes section 7's custom
layout/style exceptions for the standalone browser frontend. The Telegram UI
hold and operational gates remain in force.
**Next steps:** section 11 implements the closed native sign-in boundary; complete
short guided setup/enrollment/recovery handoff and remaining identity/M1 gates.

The user-approved viewport-layout refinement is P1c.3 in section 9. It replaces
P1c.2's narrow/stacked page geometry while preserving ADS adoption and all
operational boundaries. That layout is now historical. The user's subsequent
"fix the issues ... always refer to the atlassian docs" instruction governs
P1c.4 in section 10 and plan revision 14. Use those and the current release
checklist for that source-bound design evidence. The user's acceptance and
subsequent proceed/usability instruction govern P1c.5 in section 11, with a
separate dormant native transport build. No operational gate is relaxed.

## 2. Licence findings and exact-package shortlist

The shortlist below retains the initial P1b.2a inspection. Section 5 records the
later D13a exact-graph evidence and unresolved acceptance gates; use that section
for the current review status, not the original five-package scope alone.

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
At the initial five-package inspection there was no resolved browser lockfile or
transitive report. The later review-only snapshot is described in section 5;
it is not an installed application lockfile or complete legal/source audit.
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

### STATE BLOCK — initial P1b.2a snapshot

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

## 5. D13a: reproducible exact dependency evidence

This bounded follow-up starts from clean branch commit `f7b23a51`. Deployed
commit, production configuration and applied migrations remain unknown. It does
not change Django, staff records, Telegram, workflow APIs or business authority.

### Scope, candidate and reproducibility

`codebase-analysis-docs/assets/BROWSER_DEPENDENCY_CANDIDATE.json` is a **review
input**, not the repository's application manifest. Its runtime proposal covers
React/ReactDOM, provider, tokens/reset/primitives and login form/input/button/
heading/message components. Development scope covers Parcel, Compiled's Parcel
integration, TypeScript/types and the ADS/stylesheet lint tools with ESLint.
It deliberately excludes routers, a second backend, Forge/Connect, customer
workflows, charts, uploads and a new UI test framework. Later additions require
their own graph review; root Playwright is existing tooling, not proof a future
browser workspace has its own tests.

Resolution takes place in an OS temporary directory with a copied candidate
manifest and these npm options:

```text
npm install --package-lock-only --ignore-scripts --audit=false --fund=false --strict-peer-deps --prefer-offline --registry=https://registry.npmjs.org/
```

This operation creates a review lock only: no `node_modules`, package lifecycle
script, React build, browser page or deployment. npm documentation distinguishes
lockfile-only resolution and script suppression from package installation.
[npm install options](https://docs.npmjs.com/cli/v11/commands/npm-install/)

The standard-library inspector is
`codebase-analysis-docs/assets/review_browser_dependencies.py`. It accepts only
public credential-free HTTPS registry artifact URLs, refuses redirects, checks
SHA-256-or-stronger SRI, reads bounded archives without extracting/executing code,
and inventories shipped package metadata, licence/NOTICE files, asset names,
nested package manifests and lifecycle commands. Archives remain outside the
repository. Reports contain hashes/metadata, not copied package code, fonts,
images, credentials or customer data. Downloading an artifact for inspection is
not installing it in the application.

Evidence files under analysis assets:

| File | Purpose |
|---|---|
| `codebase-analysis-docs/assets/BROWSER_DEPENDENCY_CANDIDATE.json` | Proposed exact direct versions; no installation approval |
| `codebase-analysis-docs/assets/BROWSER_DEPENDENCY_REVIEW_LOCK.json` | Exact review-only dependency resolution, including development/platform options |
| `codebase-analysis-docs/assets/BROWSER_DEPENDENCY_REVIEW.json` | Machine-readable archive identity/integrity, licence hashes, asset/peer/script evidence |
| `codebase-analysis-docs/assets/BROWSER_DEPENDENCY_REVIEW.md` | Generated inventory; held status, not legal or security clearance |
| `scripts/tests/test_browser_dependency_review.py` | Synthetic offline safety/evidence tests; no package installation/network |

Offline binding check, without downloads or cache:

```text
python codebase-analysis-docs/assets/review_browser_dependencies.py --check
```

To reproduce archive inspection, use the committed review lock and an explicitly
chosen OS-temporary cache directory; replace `TEMPORARY_REVIEW_CACHE` with that
path. The command writes only the generated evidence files above and temporary
cache artifacts. It never writes the actual root package manifest/lock.

```text
python codebase-analysis-docs/assets/review_browser_dependencies.py --lock-file codebase-analysis-docs/assets/BROWSER_DEPENDENCY_REVIEW_LOCK.json --cache-dir TEMPORARY_REVIEW_CACHE --fetch
```

Without `--fetch`, inspection requires already-cached archives. Canonical-JSON
hashes bind candidate/lock contents independently of checkout line endings;
archive and licence-file hashes describe exact downloaded bytes. Re-resolving
later without this lock can change transitive versions even when direct versions
stay pinned. Regenerate evidence and review differences; never relabel an old
review as approval for a new graph.
The offline check verifies recorded binding/coverage and generated report
consistency, not cryptographic authenticity of a human-edited report or fresh
registry downloads. Re-running archive inspection rechecks the downloaded bytes
against locked SRI. Git review protects the checked-in evidence itself.

### Executed inventory results

Final inspection covered **546 locked package entries / 529 unique archives**,
all identity/SRI-verified with **zero remaining inspection errors**. Of those
unique artifacts, 119 belong to the runtime dependency graph and 410 are labelled
development-only by npm. Optional platform variants are included: these are
dependency/archive counts, not shipped browser module counts or bundle sizes.
The archives total 423,215,941 compressed bytes and remain in an OS-temporary
review cache outside the repository; no archive or third-party asset is added to
Git. The retained metadata/lock/Markdown evidence is approximately 1.24 MB.

| Review indicator | Unique artifacts | Meaning and action |
|---|---|---|
| No matched shipped licence/NOTICE file | 63 | Declaration alone is not complete notice evidence; retrieve/confirm exact-version terms and attribution before distributing |
| Nested package manifests | 53 | Some are secondary entry points, some may describe vendor/test code; inspect relevant boundaries rather than assuming independent dependencies or complete coverage |
| Shipped image/SVG assets | 6 | Whole-archive inventory only; review permitted assets and actual future distribution |
| MPL-2.0 declarations | 13, all development-only | Review file-level/distribution obligations for the tools/native variants; not evidence JBL must open-source its application |
| Different lock versus shipped declaration | 0 | Consistency check only, not a legal clearance |

Indicators overlap and must not be summed as distinct failures. All shipped
package manifests had a licence declaration; the 63 missing-file flags refer
to missing matched **licence text files**, not 63 proven unlicensed packages.

The four runtime-graph artifacts without a matched shipped licence/NOTICE file
are `@atlaskit/platform-feature-flags@2.2.1`, `@atlaskit/top-layer@6.3.0`,
`@compiled/react@1.0.2` and `@statsig/client-core@3.30.2`. The other 59 are
development-only. Keep this distinction in the acceptance record; do not use
metadata alone to invent missing notice text.

The MPL set is `lightningcss@1.33.0`, its 11 locked platform binaries, and
`postcss-values-parser@6.0.2`. Tool use and distribution of covered source/binaries
are different questions. Review actual build images, modifications and shipped
outputs; do not assume automatic prohibition or a blanket duty to disclose JBL
application code. [Mozilla MPL FAQ](https://www.mozilla.org/en-US/MPL/2.0/FAQ/)

The runtime graph includes `@statsig/client-core@3.30.2` through platform feature
gating. Its presence is **not proof of a network request or staff/customer data
disclosure**. It makes runtime network/configuration inspection and D11's actual
data-flow review necessary before using real records. No React app was executed,
no third-party analytics account was configured and no customer data was sent.

### Verification performed in this phase

- Final **44 governance/tool tests passed**, including 16 new offline inspector/
  snapshot tests. No claim is made that this is the full Django application suite.
- The inspector's `--check` passed without network/cache access; a final complete
  archive inspection also passed using the temporary cache without `--fetch`.
- Django system check, dependency parity (28 existing direct Python packages),
  Mini App route inventory (202 routes), architecture boundaries, UI source ratchet,
  Python compilation and `git diff --check` passed.
- Existing high-confidence secret/artifact rules were also applied explicitly to
  changed **and untracked** files; no findings. This narrow check is not a claim
  that the repository-wide artifact audit or all other CI gates are green.
- No application model/config/route/dependency/asset change occurred; no new
  migration, environment variable or schema reversal is needed. Full application,
  PostgreSQL, real-device, production and frontend/build tests were not rerun for
  this evidence/tooling-only slice. Earlier known CI/environment/artifact issues
  remain documented and were not waived or repaired here.

Intermediate archive inspection errors were not treated as passes. Temporary
download failures were retried explicitly; the inspector was corrected to accept
DefinitelyTyped's single safe version-labelled tar root (for example
`react v18.3`) without extraction, while still denying traversal, multiple roots,
duplicates and identity mismatches. Synthetic regression coverage proves that
boundary. Final zero-error/offline results supersede those diagnostic runs.

### Original peer verification

The initial broad component React peers were not enough to choose React 19:
transitive `@atlaskit/browser-apis@1.2.0` declares React `^18.2.0` only. A React
19.3.1 resolution was rejected. Keep that finding visible even though several
direct packages advertise React 18 or 19. It confirms why exact transitive review
must precede a scaffold.

npm 11.19.0 also rejected an initial React 18 graph while selecting peer versions,
and a `$react`-reference override attempt failed. The forensic inventory uses
literal React/ReactDOM 18.3.1 overrides in its review manifest. **This masks
incompatible original peer declarations; the graph is not approved for
installation as-is.** Removing those overrides and rerunning strict resolution
against the existing review lock failed on
`@atlaskit/analytics-next-stable-react-context@1.0.1`, whose registry peer is React
`^16.8.0`. The registry's latest version was still 1.0.1 at inspection. It is
pulled by `@atlaskit/analytics-next@12.6.0`, which several proposed components use.
Do not call override-assisted resolution proof of compatible peers. No `--force`
or `--legacy-peer-deps` was used, and nothing was installed.

Before building, choose a genuinely compatible maintained dependency set or
obtain an explicit, narrowly justified compatibility exception with actual
source/runtime evidence and tests. Do not silently rewrite dependency manifests,
ship multiple incompatible React renderers or substitute another design system.
That decision is separate from the licence evidence collected here.

A read-only comparison using npm 11.19.0's already-installed semver utility
checked 56 shipped peer declarations whose provider is a direct candidate pin.
It confirmed one incompatible declaration: the runtime analytics context above.
This did not install a semver dependency or execute any candidate package code;
other transitive peer/build/runtime contracts still need their own acceptance.

Parcel/Compiled remains the build proposal, not a tested production integration.
No TypeScript compilation, ADS lint execution, actual style pipeline, bundle-size
measurement, browser network inspection, accessibility acceptance or cached-bundle
rollback has occurred. Those belong to the separately approved P1c build.

### Licence interpretation and remaining decision

Focused shipped-artifact findings, in addition to the generated full inventory:

| Exact artifact | Confirmed evidence | Required handling |
|---|---|---|
| `@atlaskit/icon@38.0.2` | Apache declaration and shipped LICENSE; 733 image/SVG assets. Paths include `package/svgs/core/atlassian-intelligence.svg` and `package/svgs/emoji/atlassian.svg` | This package is in the runtime graph. Exclude branding and unreviewed glyphs; review file-level terms and eventual bundle contents. Do not copy the entire asset directory |
| `@atlaskit/icon-lab@7.11.0` | Apache declaration but no matched shipped licence/NOTICE file; 515 assets, including `package/svgs/core/atlassian.svg` and `package/svgs/core/jira.svg` | It enters through development tooling. Do not ship these icons; retain the missing-file/asset review rather than inferring blanket permission from metadata |
| `@atlaskit/analytics-next-stable-react-context@1.0.1` | Shipped Apache licence and React peer `^16.8.0` | Licence evidence does not cure the incompatible declared peer; installation remains held |
| `@atlaskit/browser-apis@1.2.0` | Shipped Apache licence and React peer `^18.2.0` | Do not propose React 19 merely because direct component peers allow it |

The asset counts describe whole archives, not assets proven to be used or shipped
by JBL. Brand-like paths are review indicators, not legal conclusions about each
glyph. No third-party icon/font/image bytes are copied into the repository.

Treat the generated inventory as **evidence collected / human acceptance open**.
The inspector lists broad declared terms and hashes; it does not prove every
embedded file has those terms. Its flags identify review work, not necessarily a
licence violation. Missing files, legacy declarations, nested/vendor code,
generated inline icons and asset-specific terms need focused review. A package
without a `.woff` file may still contain remote font references; a package without
an `.svg` file may contain inline SVG code. No runtime privacy conclusion follows
from an archive filename scan.

For identified Apache-2.0 code, prepare the applicable licence/attribution and
NOTICE material and mark modifications when required; do not infer trademark
rights. For MIT code, preserve the applicable copyright and permission notices.
These are engineering preparation points, not a legal determination about the
complete standalone product. [Apache 2.0 terms](https://www.apache.org/licenses/LICENSE-2.0),
[MIT terms](https://opensource.org/license/mit)

Continue to exclude proprietary fonts, Atlassian branding, sticker sheets,
illustrations and unreviewed assets. The general ADS licence and identified OSS
code rights remain separate questions. Obtain qualified clarification for any
remaining conflict; a model-generated inventory is not a substitute for it.
[ADS licence](https://atlassian.design/license/)

Before installation, accept the exact candidate/lock, resolve remaining licence
and asset questions, define shipped notice files, approve build/dependency scope
and assign its maintainer. No approval is inferred from passing checker tests.
Pending backend P1b.2b work remains separately gated and need not install ADS.

### Change-specific merge / deployment checklist

- [ ] Review only analysis assets, the offline inspector/tests, ADR/plan/docs and
  exact JSON allowlist exceptions in `.gitignore`; no runtime/build change.
- [ ] Keep root `package.json`/`package-lock.json`, requirements, Django settings,
  URLs, browser flag, migrations and Telegram assets unchanged.
- [ ] Keep browser disabled and auth/business routes unmounted; no real staff
  provisioning, MFA reset, external messaging or customer changes.
- [ ] Re-run the inspector's offline snapshot binding and synthetic unit tests;
  treat graph/licence/asset changes as new review, not automatic acceptance.
- [ ] Do not install/execute the candidate, its scripts or optional native
  binaries until the exact dependency/licence/build proposal is accepted.
- [ ] No production monitoring change is needed for this evidence-only slice.
  If merged, inspect CI and generated evidence consistency; any unexpected
  dependency install, browser exposure or Telegram change is outside this phase.
- [ ] Rollback removes/reverts this slice's review tooling/evidence/docs only;
  there is no schema reversal or business-data rollback. Do not delete shared
  staff/session/audit data or use a database restore.

**Findings:** the review is now a reproducible bounded deliverable rather than a
five-package metadata guess. **Open questions:** named acceptance, remaining
licence/asset findings and proven build compatibility. **Next steps:** accept the
exact reviewed scope before P1c installation; retain M1 and pilot-order gates.

### STATE BLOCK — D13a evidence follow-up

- INDEX_VERSION: browser-react-ads-decision-2 / D13a / 19 October 2026.
- FILE_MAP_SUMMARY: exact BROWSER_DEPENDENCY_CANDIDATE/REVIEW_LOCK/REVIEW JSON,
  generated review Markdown, review_browser_dependencies.py, offline safety tests,
  ADR 0062, implementation plan revision 6 and release checklist.
- OPEN_QUESTIONS: compatible peer strategy, missing notice/asset acceptance,
  distribution-specific MPL review, accepted build scope, named reviewer/maintainer
  and later M1 operational controls. Deployed release/migrations remain unknown.
- KNOWN_RISKS: override-masked React-16 peer, React-18-only transitive dependency,
  brand glyphs, missing shipped notice files, nested/vendor metadata, unmeasured
  runtime feature-gate traffic and two-frontend maintenance.
- GLOSSARY_DELTA: forensic review graph is evidence, never installation approval;
  no matched licence file is not proof of no licence; dev graph is not client bundle.
- NEXT_READ_QUEUE: resolve/accept exact peer/licence/asset/build findings before
  P1c installation; separately bounded P1b.2b backend work remains possible.
- VERIFICATION: 529 unique archives / 546 entries inspected, zero remaining
  errors; final 44 governance/tool tests and offline binding passed. No installation,
  production inspection, staff/customer/provider changes, commit, merge or deployment.

## 6. Source-only access preview — 20 October 2026

The user asked whether pages were accessible and agreed to proceed toward a
preview. This bounded **P1c preparation** makes the proposed access journeys
reviewable while preserving the previously chosen exact dependency review.
It does not complete D13, create the React workspace or implement authentication.
Starting source commit: `1b07b549`; production release/migrations remain unknown.

### Open the preview

From the repository root:

```powershell
.venv/Scripts/python.exe scripts/serve_browser_access_preview.py
```

Open **http://127.0.0.1:8765/** on the same computer. The Page selector opens
sign-in, setup-link verification, first password, MFA, authenticator enrollment,
recovery-code handoff, fresh sign-in, workspace and help. The scenario selector
simulates invalid details, temporary unavailability, throttling, expiry or an
account needing enrollment. Switch Light/Dark/System to review appearance.
Use Reset demo to restart. Ctrl+C stops the local server. A port conflict can
be handled with `--port 8766` and the corresponding local address.

The server always binds IPv4 loopback. It has no public/LAN mode, Django imports,
database, credentials, environment loading, CORS, authentication APIs or directory
listing. It serves only `/`, `/index.html`, `/preview.css` and `/preview.js`.
Other paths and query strings return 404; foreign Host headers return 403 and
POST returns 405 without reading or echoing the body. Python's HTTP parser may
normalize a leading double slash to the same allowlisted path. CSP forbids
connections, form submissions, remote assets, fonts and framing. Access logging
is disabled to avoid retaining supplied paths/headers.

The three sources live under
`codebase-analysis-docs/assets/browser-access-preview/`. They are first-party
HTML/CSS/JavaScript review artifacts with system fonts and no copied ADS styles,
tokens, icons, fonts, logos or packages. This wireframe does **not** substitute a
different library for the selected React/ADS client. The existing application
build and root dependency lock remain unchanged. Review values are not approved
tokens or permission to restyle Telegram.

### Page and interaction contract

The source/component candidate inventory is in
`docs/ui-standard/component-index.md`; exact hashes and the candidate-only reason
are in the existing UI source ratchet. The artifact's own real browser shell is
captured; there is no React or operational business shell to capture yet.

- Sign-in offers only fixed read-only demo values, with a simulated loading
  response. Error/retry remains on the same page. A fresh login resets the
  authenticator/recovery-code choice.
- Setup simulates a valid mailbox proof followed by a first password. It claims
  no email dispatch. Completion returns to sign-in, not business access. Real
  delivery and interrupted verified-mailbox setup remain backend support gaps.
- Enrollment simulates a fresh password check, an explicitly labelled setup
  placeholder, native-code confirmation and a separate one-time recovery-code
  handoff. All code labels are deliberately invalid. After viewing, Back/direct
  navigation does not re-show the labels within that page session. Refresh and
  Reset demo restart the in-memory simulation; this is not a durable security
  control. No QR secret, credential or recovery-code download/copy is provided.
- Enrollment ends at fresh password/MFA sign-in. The demo workspace disables all
  business tiles. It illustrates the ordered Complaints → TAT → Origination →
  Portal backlog, not a claim that a viewer has those grants or usable tools.
- Help gives an existing internal administrator handoff. No invented email,
  ticket submission, signup, password reset or factor replacement is connected.
- Navigation cancels an in-flight simulated response. Keyboard skip/focus,
  labelled fields, loading and live errors are present. No localStorage,
  sessionStorage, cookie, SDK, analytics or API is used.

### Executed evidence and limits

The existing root Playwright installation exercises the source directly:

```powershell
node scripts/test_browser_access_preview.js
.venv/Scripts/python.exe -m unittest discover -s scripts/tests -p 'test_*.py'
.venv/Scripts/python.exe scripts/check_ui_standard.py
.venv/Scripts/python.exe codebase-analysis-docs/assets/review_browser_dependencies.py --check
```

The browser script requires the default loopback server above. It records
source hashes, captures, request methods/URLs and absence of storage/cookies in
ignored `test-results/browser-access-preview/report.json`. Synthetic screenshots
stay beside that report; no screenshot or visual baseline enters Git.
Final executed counts are recorded in the plan/release handoff after validation.
The final run passed **78 browser checks**, captured **70 synthetic screenshots**
and recorded no unexpected requests, browser errors, cookies or web storage.
All three report source hashes match the current files and UI candidate registry.
**All 50 tooling/governance tests passed**, including six new loopback-boundary
tests. The governance run used process-only synthetic Django settings and a
loopback-only socket guard; the initial unconfigured invocation stopped at the
existing DEBUG/secret-key settings guard, which was not weakened. These commands
must run with isolated synthetic Django settings as in CI, not production secrets.

Narrow Ruff/compilation, UI ratchet, offline D13a binding, Django system check,
migration graph (290 nodes/19 leaves), database governance/catalogue (215 tables),
architecture boundaries, route inventory (202), dependency parity (28), explicit
preview JavaScript syntax and diff whitespace checks passed. First-party syntax
discovery now includes the preview directory. No authentication/domain suites,
PostgreSQL, native provider or operational browser acceptance were rerun for this
presentation-only artifact. Prior environment-template, artifact-hash and expired
dependency-audit findings remain open; no exception/baseline was relaxed.

Headless evidence does not approve the design, establish WCAG conformance, test
a real phone/Telegram client, or prove React/ADS, CSRF, native MFA or live mail.

Diagnostic browser runs found retained recovery-input mode across fresh logins
and hash navigation overriding the keyboard skip link; both were fixed before
the final run. An initial server-test assertion expected Python to preserve
double-leading slashes; the test now checks encoded traversal instead. No parser
or operational URL policy was weakened to pass that test.

Read-only registry queries reconfirmed
`analytics-next-stable-react-context@1.0.1` is still latest and declares React
`^16.8.0`; `analytics-next@12.6.0` still depends on it. Section 5's peer hold is
unchanged. The context source uses `createContext`, which is a reason to
investigate a narrowly reviewed compatibility exception, not runtime proof or
permission to install. No exception is accepted here. The local Node is 26.7.0,
outside the review candidate's `>=22 <25` range; future React builds need the
reviewed supported runtime. Existing-tool preview checks do not accept Node 26
for the future frontend.

### Change-specific handoff checklist

- [x] Add only the three first-party review sources, loopback server, focused
  server/browser verification, syntax discovery and source-bound UI/documentation records.
- [x] Affected workflow: company-browser presentation review only. No operational
  workflow, auth handler, permissions, state, Telegram source or asset changes.
- [x] New dependency/configuration/environment/schema changes: none. No migration
  or database reversal applies. Existing root Playwright is reused.
- [x] Keep browser off, E006 blocking, production URLs unmounted, D13/M1 open and
  all Design Lab decisions/baselines unapproved. No merge/deployment performed.
- [ ] Human review of wording/layout, real-device/assistive checks and final
  source/version mapping to the accepted React/ADS components.
- [ ] Resolve and accept exact peer/licence/notice/asset/build/runtime scope
  before installing React. Then implement and test the real CSRF/session client.
- [ ] Before operational access: accepted delivery/recovery, native shared cache
  and log privacy, PostgreSQL races, support/backup ownership and M0/M1 evidence.
- [x] Monitoring: expect only local fixed-asset GET/HEAD traffic and no writes.
  Unexpected external requests, writable credential fields or exposed repository
  paths require stopping the preview and fixing its boundary.
- [x] Rollback: stop the loopback process and revert this review artifact/tooling/
  source-ratchet documentation change. No staff, credentials, sessions, audit or
  workflow records need modification. Nothing is published or deployed.

### STATE BLOCK — source-only access preview

- INDEX_VERSION: browser-react-ads-decision-3 / 20 October 2026.
- FILE_MAP_SUMMARY: browser-access-preview/{index.html,preview.css,preview.js};
  scripts/serve_browser_access_preview.py; scripts/test_browser_access_preview.js;
  focused server tests; existing UI source registry/index; ADR 0062 clarification;
  platform plan revision 10 and release checklist.
- OPEN_QUESTIONS: exact dependency/asset/licence/build acceptance and peer strategy,
  supported Node runtime, real React implementation and remaining backend/M1 gates.
- KNOWN_RISKS: confusing synthetic navigation with authentication or interpreting
  screenshots as design/production approval. Production state remains unknown.
- GLOSSARY_DELTA: access preview means a first-party synthetic analysis artifact,
  not the installed browser client or an operational account/session.
- NEXT_READ_QUEUE: review the preview; resolve and accept D13; implement bounded
  React/ADS auth pages; finish operational backend/support and M1 before Complaints.

## 7. P1c.1 — actual React/ADS local access client

The user clarified that the preview must use Atlassian and instructed **“resolve
it and proceed”**. ADR 0066 records that local dependency/build decision before
implementation. `browser/` now contains actual React 18.3.1 and ADS components,
separate from the root Telegram package/build. This delivers a usable **local
demo**, not operational company login, business APIs or M1. Source start remains
`1b07b549`; prior wireframe changes were already uncommitted and are retained.
Production release/migration state remains unknown. No commit, merge or deploy
is performed by this phase.

### Dependency resolution and exact licence scope

`browser/DEPENDENCIES.md` is the canonical dependency/notice decision. Exact pins
are in its package manifest/lock; `dependency-review.json` binds the current lock
to D13a's archive evidence plus integrity/identity/licence inspection for changed
artifacts. Final graph: **555 entries / 528 unique archives**, comprising **505
reused inspections and 23 new inspections**. No broad global React override,
force or legacy-peer flag is used.

Two explicit selections resolve the concrete blockers:

1. A React-edge override scoped only to
   `analytics-next-stable-react-context@1.0.1` selects React 18.3.1. Its original
   ^16.8.0 declaration remains an **engineering compatibility exception**, not
   upstream support. The shipped tiny createContext module, compatible parent,
   singleton/provider/consumer tests and actual component journeys justify this
   local scope. The original-peer checker requires exactly that exception and
   one React renderer; any additional incompatible/missing required peer fails.
2. The initial npm audit found development-only selector-parser advisory
   GHSA-rj75-hqrm-r3gf. Pinning the fixed parser 7.1.6 is a deliberate toolchain
   override across old 6.x ranges, verified with selector/API and real Compiled
   build checks. Supported ESLint 10.13.0 replaces the EOL proposed 9.39.4.
   The final point-in-time audit reports **zero vulnerabilities**; this is not
   a general security certification. See the
   [upstream advisory](https://github.com/advisories/GHSA-rj75-hqrm-r3gf) and
   [ESLint support record](https://eslint.org/version-support/).

Node **22.23.3** was downloaded from the official distribution to ignored local
tooling and SHA-256 verified (`2b0ff57b049cda1bbcea2240eec20467018713c1efe1f7360c2681859b90ed71`
for the Windows x64 zip). System Node 26 is not changed or accepted as the build
runtime. npm 11.19.0 strictly resolves/installs with lifecycle scripts disabled.
Parcel automatic installs are disabled. Explicit Compiled Babel/strip/build
runtime dependencies fix root plugin resolution without patching vendor files.

The accepted licence scope is identified OSS npm code, company text/system fonts
and generic OSS component glyphs. The general ADS licence is not treated as a
blanket standalone asset grant. Applicable shipped full licences/notices and
publisher/provenance are generated into readable THIRD_PARTY_NOTICES.txt.
Runtime archives missing separate licence files use their explicit declarations
plus full retained terms/official upstream notices, with attribution/source
hashes disclosed. No missing-file flag is misrepresented as a shipped notice.
Development tool/native/MPL redistribution is excluded from this local build
decision and needs a distribution-specific notice/source package if commissioned.

The build inspects the emitted module graph: no proprietary font, image/native
asset or brand-glyph module is allowed. No logos, illustrations, copied asset
directory, Atlassian account, analytics account or third-party hosting is used.
Theme chunk names containing “atlassian” are OSS theme code identifiers. The
module scan plus network checks are scoped evidence, not proof for unbuilt
future imports. Deprecated vendor transitives stable 0.1.8 and theme 28.2.5 remain
documented maintenance concerns; the app does not directly use deprecated theme APIs.

### Open and reproduce the real ADS preview

With Node 22.23.3 on PATH, run from the repository root:

```powershell
npm --prefix browser ci
npm --prefix browser run check:dependencies
node browser/scripts/check-context.cjs
npm --prefix browser run typecheck
npm --prefix browser run lint
npm --prefix browser run build
.venv/Scripts/python.exe scripts/serve_ads_browser_preview.py
```

Open **http://127.0.0.1:8766/** on this computer. Commands and exact local-runtime
notes are in `browser/README.md`. Stop with Ctrl+C. The former custom wireframe
on 8765 is historical evidence and is not the actual ADS preview.

Login, setup proof/first password, MFA/recovery, enrollment, one-view invalid
recovery labels, fresh login, workspace and help now render real ADS controls.
Page/scenario/theme selectors support review. All credential values are fixed
and read-only. Navigation cancels simulated pending responses; setup never
issues authentication and workflow tiles remain disabled. Refresh/Reset restarts
the demo memory; one-view labels are not a durable security control. No API,
secret, proof transport, credential mutation or workflow grants are connected.

The loopback server verifies manifest hashes before serving and exposes only
listed flat HTML/JS/CSS/notices. It refuses repository/source maps/node_modules,
query strings, foreign Host and POST. Runtime theme styles use a local-only
inline-style allowance. Parcel's static import map has an exact CSP hash and
may reference only reviewed local assets; arbitrary inline scripts stay denied.
Connections, remote assets, fonts, forms and framing remain blocked. Production
CSP/nonces/static/cache integration must be designed separately.

### Actual components, evidence and diagnostics

The UI component index maps exact package/entry paths; `registry.json` freezes
the four new source candidates. TypeScript/TSX now participate in the existing
source ratchet. Existing legacy baselines and migration_authorized=false remain.
First-party layout CSS and native review/navigation controls are documented
exceptions. A local lint rule prohibits attaching layout classes to ADS/custom
components. Both ADS plugins' recommended error-level rule sets run; advisory
migration warnings are not claimed as completed conformance.

Run `node scripts/test_ads_browser_preview.js` with the default server running.
The production-browser run passed **79 checks** and produced **71 synthetic
screenshots** at 320/390/1440 widths in light/dark, with errors/retry, labels,
enrollment/recovery, keyboard skip/focus, no horizontal overflow and 200% text.
Ignored `test-results/ads-browser-preview/report.json` records current source
hashes, exact dependency lock, actual ADS packages, requests and captures.
No unexpected network/console errors, cookies or local/session storage appeared.
A native feature-gate warning reports an uninitialized client; no analytics
client/key is initialized merely to silence it. No real data-flow conclusion
follows for future authenticated traffic.

The explicit browser production build has **25 assets / 52 noticed packages /
1,193,784 uncompressed bytes**, including notices and all emitted theme chunks.
This measurement is not an initial-download or performance objective. The
dependency checker passes **134 original peer declarations**, exactly the
documented context exception, 75 absent optional platform packages and one React
renderer. Context singleton/default/provider/consumer in StrictMode, fixed-parser
syntax, TypeScript and ADS lint checks passed. Final governance/static counts
are maintained in the release handoff. All **56 tooling/governance tests** pass,
including five new hashed-server/import-map checks and the TSX-ratchet regression.
Narrow Ruff, JavaScript syntax, UI source ratchet, historical D13a offline binding,
Django system check, architecture boundaries, 202-route inventory, 28-package
Python parity and the 215-table database governance/catalogue checks pass.
These use process-only synthetic Django settings and no external credentials.
The final clean offline scripts-disabled npm ci succeeds for the exact lock.
The separate development/StrictMode build also passes the same **79 browser
checks / 71 captures**, retained under ads-browser-preview-development rather
than mixed with production evidence. Both modes have no unexpected network,
console errors, cookies or local/session storage; the warning limitation above
still applies. Actual GitHub/Linux CI remains unexecuted locally.

Diagnostics were resolved, not counted as passes: initial strict solve picked
ReactDOM 19; seeding exact previously inspected provider choices let npm validate
the scoped override. Compiled plugins required explicit root build declarations.
An initial implicit Parcel target externalized packages; the build now fixes a
browser target and requires actual React/ADS modules before it can pass. CSP
initially blocked Parcel's import map; an exact static-map hash/local-target
check fixes it without allowing arbitrary inline JS. ADS Textfield needs
isReadOnly rather than readOnly; the fixed-value check caught and fixed that.
One post-clean-install production rebuild process returned exit 1 without
diagnostic output; the isolated logged rerun passed and emitted the same
verified build. Its cause is unverified. The environment rejected a detached
background server launch; the final preview runs through the normal local
session. Restart using the documented command if that session ends. All 25
served asset hashes were verified against the final production manifest.

No native-auth/domain suite, PostgreSQL race, real device/assistive technology,
actual mail/provider, deployment/static rollback, full CI or production operation
is certified by these synthetic checks. Prior wider environment/artifact/Python
dependency-audit findings remain open. No baseline/exception was relaxed.

### Change-specific handoff checklist

- [x] Add one isolated browser manifest/lock/review, React sources, supported
  build/style/lint pipeline, notices, hashed loopback server and focused checks.
- [x] Local external dependency addition authorized by the explicit user request;
  reason/alternative/exceptions and exact graph documented before installation.
- [x] Company-browser presentation only. No Telegram asset/build, Django auth
  handler, permission/grant, business workflow, environment secret or schema
  change. No migration or reversal command applies to this phase.
- [x] Browser off, E006 blocking, production routes unmounted. No real staff
  provisioning, credential mutation, mail, merge or deployment.
- [x] Expect only manifest-listed loopback asset reads and demo memory. Unexpected
  outbound traffic, changed hashes, real credential entry or repository exposure
  requires stopping the preview and fixing the boundary.
- [ ] Human design/component acceptance, real devices/assistive checks, actual
  React→CSRF/session/native auth integration and production static/CSP/cache plan.
- [ ] Operational support/backup owners, proof delivery/interrupted setup/recovery,
  native shared cache/log privacy, PostgreSQL and M0/M1 acceptance before Complaints.
- [x] Rollback stops the loopback process and reverts this bounded workspace,
  tooling/source-review/docs change. Keep backend staff, credentials, sessions,
  audit and operational records. No database restore or data reversal.

### STATE BLOCK — P1c.1 actual React/ADS local client

- INDEX_VERSION: browser-react-ads-decision-4 / 20 October 2026; ADR 0066;
  platform plan revision 11. This supersedes the local installation hold only
  for the exact browser workspace, not the historical forensic manifest.
- FILE_MAP_SUMMARY: browser/{src,scripts,notice-sources,package/lock/review,
  configuration,README,DEPENDENCIES}; hashed loopback server; actual browser and
  server tests; TSX UI ratchet; component index; release checklist.
- OPEN_QUESTIONS: real backend transport/static delivery, production distribution,
  final human design, device/assistive testing, support/backup and remaining M1.
- KNOWN_RISKS: original context peer exception, selector override/tool updates,
  deprecated vendor transitives, synthetic success mistaken for authenticated
  workflow authority, local CSP unsuitable for unreviewed production reuse.
- GLOSSARY_DELTA: installed React/ADS client means an actual component build;
  current demo remains disconnected and supplies no real session/grants.
- NEXT_READ_QUEUE: bounded real CSRF/session client integration and remaining
  operational prerequisites; M1 before Complaints; retain later pilot order/M3.

## 8. P1c.2 — browser-wide ADS design adoption

### Authorization and implemented scope

On 20 October 2026 the user explicitly requested **full design adoption for the
browser frontend** after the source review identified P1c.1's custom layout and
partial token use. This authorizes browser-wide implementation of ADS. It does
not approve generated screenshots, activate operational auth, migrate Telegram,
accept all Atlassian assets or authorize deployment. ADR 0066 was updated before
this implementation. Plan revision 12 retains the existing workflow pilot order.

All eleven current pages/states share the ADS shell: sign-in, setup verification,
first password, MFA/recovery-code sign-in, authenticator password recheck, setup
placeholder, recovery handoff/reveal, fresh sign-in, workspace and help. The old
split introduction and `browser/src/layout.css` are removed.

| Area | Current implementation |
|---|---|
| Header, main, cards and help | ADS Box/Stack; semantic landmarks retained |
| Responsive workflow tiles | ADS Grid; one column below ADS sm, two from 48rem |
| Wrapping actions/review controls | ADS Inline/Button, labelled pressed-state groups and disclosure |
| Typography | ADS Heading/Text and unchanged typography tokens |
| Links and skip navigation | ADS Anchor/LinkButton; focus restored after closing review controls |
| Forms and feedback | ADS Form direct children, Field, Textfield, FormFooter, MessageWrapper/HelperMessage, InlineMessage |
| Screen-reader announcements | ADS VisuallyHidden |
| Visual styles | Typed @atlaskit/css cssMap/cx/xcss and @atlaskit/tokens token() |

The entire standalone browser source uses both lint plugins' complete recommended
rule sets as errors, including advisory migration rules. The native class/global
stylesheet exceptions and custom native-class rule are removed. There is one
line-scoped exception: synthetic credential fields must remain read-only. This
does not endorse read-only login fields for the future operational client.

The typed styling API accepts the literal ADS sm media query. No custom breakpoint,
palette, type scale, global font/focus override, raw visual fallback, native select
or vendor CSS selector remains. Widths, minimum sizes and grid tracks are normal
application geometry; ADS has no token for a 28rem access card or 52rem workspace.
These declarations stay inside typed cssMap; layout composition stays in ADS
primitives. Future browser pages must follow the same lint/component contracts.

ADS typography tokens retain their supplied system-font fallback stack. No font
files, Atlassian logos, brand glyphs or illustrations are added. Full component/
layout/token adoption is not a claim to distribute proprietary fonts or reproduce
the Jira/Confluence product shell. Official references:
[tokens](https://atlassian.design/foundations/design-tokens),
[spacing](https://atlassian.design/foundations/spacing),
[typography](https://atlassian.design/foundations/typography) and
[primitives](https://atlassian.design/components/primitives/overview).

### Dependency and build binding

Only already installed/reviewed `@atlaskit/css@1.1.7` and
`@atlaskit/visually-hidden@4.4.0` are promoted to direct dependencies. Their
existing archive versions, URLs and integrity values remain unchanged. The
workspace manifest/root lock declarations and review digest were updated
together; no package resolution, download, new override or upstream-support
claim is introduced. The graph stays **555 entries / 528 unique archives**;
134 installed original-peer declarations still have precisely the documented
context exception, one React renderer and 75 absent optional platform packages.

Compiled explicitly recognizes the supported @atlaskit/css import source.
Build manifests now bind all three first-party source hashes as well as output,
dependency and module hashes. Browser checks reject a stale build before running.
Production: **25 assets / 52 noticed packages / 1,211,086 uncompressed bytes**.
Development: **25 assets / 52 noticed packages / 3,579,839 bytes**. Outputs include
readable notices and emitted theme chunks; these are measurements, not budgets.
The graph/asset/notice checks pass; the local npm audit reports zero findings.

### Executed evidence and practical limits

- Production and separate development/StrictMode runs **each pass 88 browser
  checks and produce 73 synthetic captures**. These repeat the same journeys;
  do not count them as 176 distinct business scenarios.
- All eleven pages/states render at 320/390/1440 in both themes. Error/retry,
  busy-navigation cancellation, first-password/fresh-sign-in boundaries,
  one-view invalid recovery labels and disconnected tools remain covered.
- Six viewport/theme comparisons prove actual rendered card spacing, radius,
  surface, shadow, Heading and Text match defined loaded ADS tokens. Exact
  767/768 grid behavior, system theme changes, wrapped review controls, keyboard
  activation/focus return, skip navigation and 200% text overflow checks pass.
- Zero unexpected network requests, browser/console errors, cookies or local/
  session storage. Fixed values remain read-only. No customer/staff data or
  actual credentials are used. Captures were visually inspected for light
  desktop, dark mobile, narrow workspace and expanded review controls.
- TypeScript, the complete recommended ADS lint rules, exact graph/original
  peers, React context and selector-parser checks pass. All **56 tooling tests**
  pass with synthetic DEBUG/secret configuration and an in-memory database.
  Initial bare discovery correctly failed the production secret configuration
  guard; the rerun used explicit nonoperational settings, without changing it.
- UI source ratchet, first-party JavaScript syntax, source/build/report/registry
  hashes and changed-file/privacy/diff checks pass. Legacy source baselines and
  `migration_authorized: false` remain unchanged. Full CI, real devices,
  assistive technology and native authentication were not certified here.

Reproduce with `browser/README.md`, the source-bound browser scripts and the
dedicated CI job. Reports/captures are ignored under
`test-results/ads-browser-preview{,-development}/`. They are review evidence,
not approved visual baselines. The old P1c.1 measurements remain in section 7.

### Change-specific handoff checklist

- [x] Additions/affected workflow: browser presentation only; all current access
  pages and future browser styling rules. No Complaints/TAT/Origination/Portal
  business endpoints, workflow semantics or grants changed.
- [x] Dependencies/configuration: two already-reviewed packages promoted;
  archive graph/overrides unchanged; typed styling build/lint updated. No root
  Telegram package, environment secret, schema or migration change.
- [x] Verification: local production/development builds and browser checks,
  type/lint/peer/context/parser/audit, tooling and source binding as above.
  GitHub CI is configured, not claimed executed in this session.
- [x] Telegram compatibility: no Telegram source, dependency, identity or role
  change; its UI migration hold remains. Browser stays off/E006/routes unmounted.
- [x] Monitor: loopback asset reads only; stop on unexpected network, editable
  credentials, stale source/build hashes or repository exposure.
- [x] Rollback: stop the preview process and revert this browser design/tooling/
  candidate-doc slice to P1c.1. No DB reversal or data/session/audit restoration.
- [ ] Human design/device/assistive acceptance; no approval inferred from PNGs.
- [ ] Real CSRF/session transport, production static/CSP delivery, proof delivery,
  interrupted setup/recovery, native shared cache/privacy, PostgreSQL, primary/
  backup support owners and operational M0/M1 before the Complaints pilot.

### STATE BLOCK — P1c.2 browser-wide ADS adoption

- INDEX_VERSION: browser-react-ads-decision-5 / 20 October 2026; ADR 0066;
  platform plan revision 12. Supersedes P1c.1 custom styling exceptions.
- FILE_MAP_SUMMARY: three browser source files; typed styling configuration,
  lint/build/source binding; direct-use metadata; browser checks; UI source
  inventory/ratchet; existing canonical decision/plan/checklist/docs.
- OPEN_QUESTIONS: human/device review and actual transport/operational M1.
- KNOWN_RISKS: existing dependency exceptions and production-distribution
  obligations; synthetic success must not be treated as authenticated authority.
- GLOSSARY_DELTA: browser design adoption means ADS components, layout,
  typography, responsive rules and typed tokens across this browser workspace.
- NEXT_READ_QUEUE: real native CSRF/session integration and remaining M1 gates;
  Complaints before TAT, Origination and Portal, retaining M3 investment review.

## 9. P1c.3 — browser viewport layout

### Problem and authorized change

The user rejected scrolling while horizontal space was unused, then explicitly
approved the proposed responsive layout plan. Read-only measurements at 1366x768
showed the P1c.2 sign-in card fixed at 448px with 26px vertical overflow; opening
Preview controls increased overflow to 480px. Its 64px desktop top/bottom spacing,
narrow footer and vertically stacked controls caused avoidable document height.
The earlier browser checks used a 1000px desktop height and checked horizontal
overflow only; they did not establish short-laptop viewport fit.

P1c.3 keeps the approved ADS components/tokens and changes application geometry:

- A fluid desktop frame uses the available width, up to a readable 90rem.
  Individual form fields retain a 28rem maximum; the page is no longer constrained
  to that input width. At ADS md (64rem), guidance/status sits beside actions.
- Compact, labelled ADS control buttons open in an adjacent 22rem column from
  md, without moving the page down. All Page/Theme/Response controls remain
  visible together. Accessible names retain the full meanings of compact labels.
- Workspace tools use four columns from md, two at sm and one on phones. Help
  guidance uses three columns from sm; recovery labels use two. Overlapping
  breakpoint declarations for the same grid tracks are avoided.
- Token spacing reduces desktop main padding from 64px to 24px each side of
  the block axis, header padding from 16px to 8px, and compacts the footer into
  a wrapping horizontal row. Body/heading typography remains unchanged.
- Below md, guidance precedes actions and controls follow the content in natural
  document flow. Phone/short-window/enlarged text remains scrollable. No fixed
  page height, overflow clipping, hidden explanation or font shrinking is used.

All forms/actions, error text, help, demo warnings, recovery behavior and current
authentication boundaries remain. There is no dependency, config secret, backend,
grant, schema/migration, Telegram, real account/provider or deployment change.
ADR 0066 records the follow-up; plan revision 13 retains the pilot/M1 gates.

### Verification contract and evidence

`scripts/test_ads_browser_preview.js` adds an explicit desktop matrix:
1280x720, 1366x768 and 1440x900; light/dark; eleven pages; controls closed/open.
For each of the seven forms, all four simulated errors are tested at each
viewport/theme/control state. The checks assert document height/width fit,
onscreen actions, no clipped/inner-scroll workaround, and an adjacent panel with
the same top position as the card. Source/build/report/registry hashes bind the
evidence to this implementation. Mobile/200% text, keyboard/focus, token and
functional journeys remain in the same runner.

The first rerun exposed a test synchronization issue in automatic theme checks:
controls detaching does not prove AppProvider has committed auto mode. The test
now waits for the existing light system preference before emulating dark, then
checks both OS preference changes. A separate direct browser probe confirmed the
provider follows the system preference; no product theme workaround was added.

### Executed results

Production and separate development/StrictMode builds each pass **556 browser
checks with 125 synthetic captures**. Each includes **468 viewport-fit cases**:
eleven normal pages plus four errors on seven forms, across three desktop sizes,
two themes and controls open/closed. All fit without document scrolling or
offscreen actions. Normal/error guidance and the entire compact panel stay
visible together. The two builds repeat the same cases; they are not 1,112
distinct operational journeys. Mobile/large-text scrolling, token comparisons,
keyboard/focus and the earlier functional boundaries also pass.

TypeScript, complete recommended ADS lint, both graph/notice/asset builds,
11 focused UI-ratchet/static-server tests and 153 first-party JavaScript syntax
checks pass. Both build/report/source/registry bindings, unchanged legacy
baselines, privacy/scope/diff and served-output hashes were checked. There was no
dependency change, install or new registry audit; earlier audit results remain
historical. Production: 25 assets / 52 noticed packages / 1,212,635 uncompressed
bytes. Development: 25 assets / 52 noticed packages / 3,607,470 bytes.

Source-faithful 1280x720 screenshots were visually inspected for normal/error
sign-in, first password, help and controls; the mobile captures retain natural
flow. The current release checklist records the phase handoff.
Ignored reports and source-faithful captures remain under
`test-results/ads-browser-preview{,-development}/`; they are not approved visual
baselines, native authentication, real-device or assistive-technology acceptance.

### Change-specific handoff checklist

- Additions/affected workflow: standalone browser presentation and viewport
  regression checks only; no business workflow endpoints/decisions/grants.
- Dependencies/configuration/migrations: none. Existing exact graph, review
  binding and peer/security/asset decisions remain. No reversal command applies.
- Verification: current results recorded at handoff; GitHub CI is configured,
  not claimed executed locally. Prior section 8 measurements are historical.
- Telegram compatibility: no source/identity/role/dependency changes; UI migration
  hold remains. Browser off/E006/routes and operational M0/M1 remain open.
- Monitor: reviewed loopback asset reads only; unexpected network, editable
  credentials, stale hashes or repository exposure require stopping the preview.
- Rollback: stop the loopback process and revert this source/test/candidate-doc
  layout slice to P1c.2; rebuild/restart if previewing that version. Preserve all
  backend records, sessions and audits; no data restoration is required.
- Unresolved: human design/device/assistive review, real auth transport/static
  delivery, proof/recovery/cache/privacy/PostgreSQL/support and M0/M1 acceptance.

### STATE BLOCK — P1c.3 browser viewport layout

- INDEX_VERSION: browser-react-ads-decision-6 / 20 October 2026; ADR 0066;
  platform plan revision 13. Supersedes P1c.2 narrow/stacked page geometry.
- FILE_MAP_SUMMARY: browser/src/preview.tsx; browser test viewport matrix;
  candidate source hashes/component index; existing ADR/decision/plan/checklist.
- OPEN_QUESTIONS: human/device review and operational native transport/M1.
- KNOWN_RISKS: viewport fit is for the declared desktop sizes and normal text;
  small windows/large text remain naturally scrollable. Synthetic UI supplies
  no operational authentication or workflow authority.
- GLOSSARY_DELTA: none; geometry changes existing browser presentation only.
- NEXT_READ_QUEUE: human layout review and real native CSRF/session/M1 work;
  existing Complaints-first pilot order and M3 gate remain.

## 10. P1c.4 — documentation-led browser composition

### Problem, authorization and official references

The prior implementation used actual ADS packages and tokens but composed them
poorly: an oversized raised access frame, sunken groups on that frame, essential
guidance remote from the form, popup feedback duplicated as paragraphs, and
review button collections mixed into the staff presentation. Package imports,
lint success and viewport fit did not establish design adoption. The user's
"fix the issues. use common sense. always refer to the atlassian docs" instruction
authorizes these corrections and the exact ADS components needed for them.

The current reference map is `browser/DESIGN.md`; `browser/AGENTS.md` makes
checking relevant current official guidance mandatory for future browser work.
References consulted for this correction include:

- [Form usage](https://atlassian.design/components/form/usage) and
  [Text field usage](https://atlassian.design/components/textfield/usage): coherent
  title/description, one form column, visible labels and purposeful field widths.
- [Section Message usage](https://atlassian.design/components/section-message/usage)
  and [Inline Message usage](https://atlassian.design/components/inline-message/usage):
  persistent form-wide failures belong in visible section feedback.
- [Elevation](https://atlassian.design/foundations/elevation) and
  [Grid](https://atlassian.design/foundations/grid-beta/applying-grid): meaningful
  surfaces and a fixed-wide 1296px workspace grid including margins.
- [Navigation layout](https://atlassian.design/components/navigation-system/layout),
  [migration guide](https://atlassian.design/components/navigation-system/migration-guide)
  and [Select usage](https://atlassian.design/components/select/usage): actual
  navigation frame/items and labelled option selection for the review harness.
- [Typography](https://atlassian.design/foundations/typography),
  [Button usage](https://atlassian.design/components/button/usage),
  [Token setup](https://atlassian.design/foundations/tokens/use-tokens-in-code/)
  and [App provider](https://atlassian.design/components/app-provider/examples):
  semantic type/actions and initialized themes. Installed exact types/source
  supplied the APIs; old snippets were not assumed compatible.

The 500px access maximum and separate review route are application decisions,
not universal ADS mandates. The synthetic read-only input exception remains
line-scoped; it must not become an operational form rule.

### Resulting behavior and exact dependency decision

`/` is the staff presentation: one compact fixed-value notice, focused access
forms, description and any SectionMessage before the fields, one primary
action and relevant help links. Fields/feedback remain in one reading sequence.
Default surfaces and neutral/bordered groups replace decorative raised/sunken
nesting. No Details popup or repeated per-field warning remains.

The workspace uses actual Root/TopNav/Main/SideNav, responsive navigation toggle
and current side-nav-items. Its four disconnected tools use a two-column grid
where space allows; they contain no dead disabled buttons or fabricated grants.
The content grid includes 32px desktop/16px mobile margins. Small windows and
enlarged text retain natural scrolling and the vendor's main scroll region.

`/review.html` renders the same task components with separate, labelled ADS
Page/Theme/Response Selects. At desktop size the review column sits beside the
task; it follows naturally on mobile. The hash/state/reveal guards remain
in-memory only. Both HTML entries receive the same manifest/CSP validation.

ADR 0066 and `browser/DEPENDENCIES.md` record the exact pre-install review:
navigation-system 11.3.1, side-nav-items 2.5.8, section-message 10.2.6 and select
23.1.3 added; unused direct inline-message removed. Lock-only resolution and
archive inspection preceded scripts-disabled installation. The graph is 592 lock
entries / 554 unique archives, with 27 newly inspected archives (50 current
separate records plus 504 reused base inspections). The 27 additions declare
Apache-2.0/MIT with licence files and no lifecycle scripts/native binaries.
Documentation/example images are excluded. Any emitted @atlaskit/logo module
now fails the build, in addition to existing font/image/native/brand exclusions.

The one original React peer exception and selector-parser 7.1.6 override remain
explicit. The checker passes 171 original installed peers, 75 absent optional
platform packages and one React renderer. The point-in-time post-install npm
audit reports zero findings. None accepts production distribution or all ADS assets.

### Diagnostics resolved during verification

The development build exposed an atomic-style insertion collision: our redundant
single-column value shared Root's base class and could be inserted after its
responsive declaration, collapsing the navigation frame. An equivalent distinct
`repeat(1, minmax(0, 1fr))` value on our content grids avoids that collision.
Both builds now retain Root's responsive columns without vendor edits, feature
gate changes or style/lint suppressions. A visually hidden live region was moved
inside Main to remove a one-pixel body overflow.

Visual review also caught initially light input backgrounds transitioning under
dark text while provider theme CSS loaded. Startup now awaits the supported
default theme initializer before mounting controls, releases its system listener,
and lets AppProvider own subsequent themes. First-frame field checks compare
foreground/background with loaded tokens; screenshots await finite transitions.
This fixes the rendered startup defect rather than hiding it with a screenshot delay.

### Verification and practical limits

Production and separate development/StrictMode runs each pass **362 checks**,
including **300 desktop-fit cases**, with **97 synthetic captures**. They repeat
the same cases and are not separate operational journeys. Normal states cover
all eleven pages on staff/review entries at 1280x720, 1366x768 and 1440x900 in
both themes (132 cases). Four failures for each of seven shared forms at those
sizes/themes add 168 cases. Body/Main bounds, visible actions, flat task surfaces,
one notice, bounded access width and feedback-before-form checks pass.

Functional setup/sign-in/MFA/recovery journeys, one-view invalid recovery labels,
320/390 mobile captures, mobile navigation, native skip links, select keyboard
interaction, system theme changes, heading/input focus and 200% text reachability
pass. Four first-frame/typography comparisons use actual loaded tokens.
No unexpected network, page/console errors, cookies or persistent storage occur.
Screenshots remain source-faithful candidates; representative normal/error,
workspace, help/recovery and dark-mobile scenes receive visual inspection.

TypeScript, complete recommended ADS lint, both graph/asset/notice builds,
12 focused UI/server tooling tests, UI source ratchet and 153 first-party
JavaScript syntax checks pass. Production output: 26 assets / 67 noticed packages /
1,752,528 uncompressed bytes. Development: 26 assets / 69 noticed packages /
4,859,188 bytes. Reports/captures stay ignored under the existing test-results
directories. Build/report/registry bindings and served asset hashes are checked
at handoff; legacy baselines and `migration_authorized: false` remain unchanged.
GitHub CI/full Django/PostgreSQL, real-device, assistive and native-auth acceptance
are not claimed by this UI slice. Technical checks do not certify full ADS
conformance or replace the user's visual acceptance.

### Change-specific handoff and rollback

- Affected workflow: standalone synthetic browser presentation/tooling only;
  no business endpoint, data/state transition, permission or workflow grant change.
- Dependencies/configuration: exact additions/review above, two HTML build entries
  and same-boundary CSP validation; no secret, root Telegram dependency or schema
  migration. No migration/reversal command applies.
- Telegram compatibility: source, roles, identity and assets unchanged. Browser
  stays disabled, E006 blocking and production routes unmounted. No live account,
  provider message, Sheets/Drive, merge or deployment action occurred.
- Monitor: loopback manifest asset reads only. Stop on unexpected network,
  editable credential collection, stale bindings or repository exposure.
- Rollback: stop the local server and revert this composition/dependency/tooling/
  candidate-doc slice to P1c.3, then rebuild/restart if reviewing that historical
  version. Retain backend identities, credentials, sessions, audits and workflow
  records; no database restore is required.
- Open: human design/device/assistive acceptance; real native transport/static
  delivery, proof/recovery/shared cache/privacy/PostgreSQL/support and M0/M1.

### STATE BLOCK — P1c.4 browser composition

- INDEX_VERSION: browser-react-ads-decision-7 / 20 October 2026; ADR 0066;
  platform plan revision 14. Supersedes section 9's page composition.
- FILE_MAP_SUMMARY: browser/{AGENTS,DESIGN,DEPENDENCIES,README}; exact graph/review;
  four src entries, build/logo guard; loopback HTML validation; browser/server
  checks; candidate source registry and existing current plan/checklist/docs.
- OPEN_QUESTIONS: human/device review and operational native transport/M1.
- KNOWN_RISKS: declared laptop fits do not guarantee arbitrary viewport fit;
  mobile/enlarged text scrolls naturally. System fonts and peer exception remain.
- GLOSSARY_DELTA: existing React browser client entry updated; no new domain term.
- NEXT_READ_QUEUE: user's visual review and closed native transport/M1 work;
  Complaints-first pilot order and M3 gate remain unchanged.

## 11. P1c.5 — closed native session integration

### Authorized scope and usability

After accepting P1c.4, the user instructed proceeding with the independence plan
and keeping onboarding/authentication easy and seamless. ADR 0067 records the
next bounded prerequisite: a separately built React client against the existing
native session/password/MFA/logout boundary. It does not start P2, admit staff,
mount production URLs or accept M1. Guided initial-password/enrollment/recovery
handoff and delivery/support remain the next increment, not completed onboarding.

Routine sign-in uses username/password and then one authenticator/recovery code.
Standard autofill, automatic server-stage resume, username retention after errors,
inline recovery, field-specific validation and visible section feedback reduce
friction. Secrets are cleared after submission/navigation; never stored or logged.
Background session checks do not interrupt typing or repeatedly flash the page.
No additional routine confirmation or remembered-device bypass is introduced.
The recovery and cancel actions precede the code field: verification caught blur
validation messages shifting below-field actions during pointer activation.
Moving these actions prevents lost clicks rather than requiring a second click
or keyboard-only workaround. Routine checks remain automatic, and explicit
logout can preempt a background session read.
The signed-out task omits the empty TopNavEnd slot, whose native mobile overflow
would otherwise show an empty menu. This is local composition using the documented
layout API, not a vendor style override or a substitute action.
Form/feedback/type/navigation references in `browser/DESIGN.md` remain applicable;
the exact installed Field/MessageWrapper contracts are used without lint exemptions.

### Implementation and trust boundary

`browser/src/{access.html,auth-index.tsx,auth-transport.ts,staff-access.tsx}` is a
distinct dormant entry. `--authentication` builds into ignored
dist-authentication (or dist-authentication-development), with `demoOnly: false`
and `closedAuthentication: true`. The fixed-value demo entry/graph and its
zero-connect CSP remain separate. The demo server rejects this manifest kind.
No new package, archive, override or proprietary asset is introduced.

The transport accepts only fixed same-origin `/api/staff/auth/v1/` paths, server
cookies and strict JSON states. It reads masked CSRF immediately before each
mutation and reads the session after responses, including login CSRF rotation.
Authenticated UI comes only from the fresh session read. Network/CSRF/protocol
failures hide unconfirmed access and offer a session check; credentials are never
automatically replayed. A request timeout and abort/generation handling prevent
late responses from restoring discarded UI. Reload/visibility restores the server
stage, and signed-in sessions recheck quietly every 30 seconds. Future business
APIs must independently recheck identity and owning workflow policy on every call.

Source review/regression exposed a stale-cookie trap: an expired/revoked browser
session could report signed_out while the existing Django cookie made password
login return 409 indefinitely. Password login now clears only a stale context
owned by that exact cookie user, then performs a fresh native password/MFA login.
Ordinary Admin/other-channel or mismatched cookies remain protected and cannot
be converted. There is no new authority, factor bypass or admission change.

`staff_auth.transport_test_urls` is guarded by test-runner and explicit test
settings. Only it mounts the native handlers and manifest/hash-checked assets.
Its identity and Complaints probes exercise existing guards with synthetic data;
they are not production endpoints or a Complaints pilot. The opt-in full-schema
SQLite settings never open db.sqlite3 or a deployment DATABASE_URL. Proof travels
to the Playwright child only over stdin. Parent-driven fixture controls use that
pipe, not unauthenticated HTTP mutation helpers. Python external connections are
rejected; browser requests stay on loopback; email uses locmem. Reports retain
paths/methods/source hashes/bounds and proof-free synthetic captures only.

### Verification record

The full affected `staff_auth` suite ran 148 tests: 139 passed and nine
PostgreSQL-only cases were skipped on SQLite. After the final empty-mobile-menu
markup change, the focused transport suite passed all five tests against the
rebuilt production and development/StrictMode entries. Each native browser run
passed 25 checks and retained 10 proof-free synthetic captures. The two builds
repeat the same scenarios; they are not 50 distinct operational journeys.
The native end-to-end path is real React -> HTTP middleware/CSRF -> DB session ->
password -> allauth TOTP/recovery -> durable login audit. It uses neither
force_login nor a mocked successful authentication response. Fault injection
is confined to lost/invalid response bodies, CSRF corruption and network failure;
successful identity remains native. Tests include missing proof, password-only
denial, session resume, logout, rotation, expiry/revocation and existing workflow
denial with no grants. Production/development runs repeat the same scenarios.

TypeScript and full recommended ADS lint pass. Each auth build contains 25 assets
and 56 noticed packages: production 1,328,516 bytes; development 3,814,736 bytes.
Eighteen focused UI/server/ratchet tooling tests, Ruff on changed Python, 154
first-party JavaScript syntax checks, architecture boundaries and the UI source
ratchet pass. Current source/report/registry/asset hashes match in both modes;
the eight browser source candidates leave legacy baselines and migration holds
unchanged. Default Django checks and migration-drift checks pass with no new
migration. CI YAML parses; no remote run is claimed. Inspected proof-free
normal/error/recovery/setup/mobile and enlarged-text captures remain review
evidence, not human/device/assistive acceptance.
The demo rebuild remains 26 assets / 67 noticed packages / 1,752,528 bytes, with
no auth-entry modules. Source/build/report/registry bindings remain candidate
evidence, not human design or operational acceptance. SQLite does not exercise
PostgreSQL locking or catalogue comments; platform comment warnings are expected.
No remote GitHub CI, full repository suite, real-device/assistive or M1 acceptance
is claimed. Native shared cache, deployment origin/static/CSP, proof delivery,
guided setup/recovery/helpdesk, backup owners and M0/M1 remain open.
The broader environment-example parity check fails on 119 pre-existing missing
declarations; all three checker inputs match HEAD. No deployment setting is
introduced here. The preview's root/review entries return 200 with zero-connect
CSP; the auth entry and native session route both return 404 on that server.

### Handoff, rollback and state

Affected workflow: closed company-browser authentication/presentation and test
tooling only. No schema/migration, environment secret, root Telegram dependency,
effective workflow policy or grant change. Production auth stays disabled,
E006 blocking and routes unmounted. No real account/provider/Sheets/Drive write,
commit, merge or deployment occurred. CI adds isolated native transport runs;
configuration is not a claim of a completed remote execution.

Monitor only test-loopback traffic and proof-free evidence. Stop if tests touch
non-test data, collect external destinations or retain proof. Rollback removes
this dormant entry/transport/owned-session restart/test/doc slice and stops test
processes; preserve backend identities, factors, sessions, audits and workflow
records. No schema reversal or operational data restore is required.

- INDEX_VERSION: browser-react-ads-decision-8 / P1c.5 / 20 October 2026; ADR 0067;
  platform plan revision 15. P1c.4 remains the accepted synthetic composition.
- FILE_MAP_SUMMARY: four auth source files; separate build kind; owned-session
  restart/regression; test-only URLconf/settings/native browser runner; CI;
  candidate source registry and existing plan/checklist/docs.
- OPEN_QUESTIONS: guided setup/enrollment/recovery UI and actual delivery/support;
  shared native cache/privacy/PostgreSQL/device/static/origin and M0/M1.
- KNOWN_RISKS: local native authentication is not production acceptance or
  workflow authority; setup support handoff is not completed onboarding.
- GLOSSARY_DELTA: existing React client definition extended for the closed build.
- NEXT_READ_QUEUE: short guided setup/enrollment/recovery handoff and remaining
  identity/support prerequisites; M1 before Complaints, M3 before later apps.

## 12. P1c.6 - guided closed onboarding

### Scope and user journey

The user instructed proceeding and avoiding further authentication delay.
ADR 0068 connects the existing native contracts in the same dormant auth build:
prepared existing-account invitation -> native first password -> QR/manual-key
TOTP enrollment -> one-time recovery codes -> fresh password/MFA sign-in.
Password-manager autofill, inline errors and bound-session resume apply. A
create-password submission proceeds through native login/recheck into enrollment
without another password prompt. Ordinary unenrolled login also proceeds directly
into setup. This is one explicit action sequence, never credential replay.

Invitation proof is accepted only from a fragment, erased before authentication requests/render,
and submitted by explicit Continue. It is not put in a query, form, storage,
report or screenshot. The browser creates no user, grant, admission or delivery.
Existing-password reset/address verification and lost-cookie setup remain verified
support procedures, not signup or identity-merging shortcuts.

QR images use the already-installed allauth MFA adapter/qrcode dependency, entirely
locally. The SVG image's white quiet zone is machine-readable content; Box renders
it without HTML injection, external images or a new package. A setup key supports
same-phone use. Desktop places the QR beside the single-column code form using
ADS Grid; mobile stacks naturally. Other focused tasks retain the 500px bound.
Guidance follows current official Form, Section Message and Button docs in
browser/DESIGN.md; actual installed Box/Grid APIs are checked. No new lint exception,
custom palette or vendor CSS override is introduced. Code/key text uses the ADS
font.code token. Authenticator fields use the numeric mobile keyboard, while
recovery fields retain general text entry. Enrollment errors ask for the newly
added authenticator code, not recovery codes that do not exist yet. Anonymous Cancel preserves verified bound first-password progress
and offers Continue account setup, rather than stranding a verified invitation.
A stale owned Django cookie cannot force native signed-out users through anonymous
setup resume; its expected 409 preserves the ordinary sign-in screen.

### Progress, disclosure and failure boundary

GET setup/session now reports password-required/completed progress and username
only for the exact verified bound session with fresh native grant/admission/audit
checks. Cross-session, expired or revoked state exposes no account detail.
GET enrollment/session reads only a fresh same-channel enrollment draft under the
existing locks, retaining its own username for sign-in after refresh; it cannot generate a seed, activate a factor, repeat recovery-code
disclosure or issue assurance. Both remain private/no-store, test-only/unmounted.

Native begin additionally returns a bounded data-image QR of its existing URI.
After explicit code confirmation, native one-time recovery disclosure follows in
that action. Copy is explicit and failure offers manual selection. A saved-codes
action signs out into the fresh native login required by ADR 0063; setup never
grants identity/workflow access. Lost confirmation is reconciled by progress;
lost recovery disclosure is not replayed or silently regenerated. Hide/navigation/
errors clear transient proof; resumed drafts require the same fresh server context.

Native setup callbacks must not queue unused Django flash-message cookies.
The JSON endpoint marks its request for explicit JSON feedback; StaffAccountAdapter
suppresses only new flashes on that request, including on-commit callbacks.
Other requests retain ordinary native messages, and notification/audit/credential
behavior is unchanged. This avoids retaining staff email in an unused cookie.

The synthetic preview and its zero-connect CSP remain unchanged. Only the guarded
test URLconf adds setup/enrollment routes and data-image permission. Test captures
mask QR/key/codes, request reports omit data URLs, and synthetic invitation proof
travels over stdin. No mail is dispatched, and identity-only tests still fail
existing Complaints authorization without grants.

### Verification and handoff

The affected backend progress/enrollment/setup suite ran 59 tests: 54 passed,
five PostgreSQL-only cases skipped. After the final response metadata and native
flash boundary fixes, all 10 focused progress/transport tests passed, including
same-session resume, anonymous/cross-session/revoked denial, normal-message
preservation and production-route closure. Both production and development/
StrictMode browser journeys passed 39 checks with 17 masked captures each.
These repeat the same scenarios; do not count them as 78 distinct journeys. Browser TOTP submissions wait for a fresh native time
window when necessary; no clock/tolerance or MFA-validation bypass is used. The
clipboard UI success branch uses an in-memory count-only test sink to avoid
overwriting the host clipboard with proof. It does not establish real OS
clipboard behavior; authentication and recovery disclosure remain native.
TypeScript, full recommended ADS lint and both builds pass. Each auth build has
25 assets / 56 noticed packages: production 1,339,987 bytes; development 3,871,969.
Current source/report/asset/registry bindings pass. Legacy baselines/inventory and
migration hold remain unchanged. Eighteen focused UI/server/ratchet tooling tests,
changed-Python Ruff, the 154-file JavaScript check and final runner syntax check,
architecture boundaries and default Django/migration-drift checks pass. No new
migration exists. Inspected normal/error/QR/recovery/mobile/enlarged-text masked
captures remain candidate evidence; real devices/assistive and OS clipboard are
not accepted here. The unchanged preview returns root/review 200 with zero-connect
CSP and auth/setup URLs 404. No remote CI or full repository suite is claimed.

No new external package/archive/override, environment secret, schema/migration,
permission matrix/grant, Telegram source/asset or production setting/URL change.
No real account/factor/provider/Sheets/Drive write, commit, merge or deployment.
CI's existing native transport job includes the extended journeys; configured CI
is not an executed remote run. The pre-existing 119 environment-example parity
omissions remain documented, and full repository/production readiness is not claimed.

Actual canonical-address invitation delivery, verified support/factor replacement,
PostgreSQL/native shared cache/privacy, origin/static/CSP, real-device/assistive,
backup/support/staging and M0/M1 acceptance remain release prerequisites. The next
work package is readiness and M1 acceptance, then Complaints read; do not restart
local authentication layout work without a concrete defect. M3 remains mandatory
before TAT/Origination/Portal investment.

Monitor isolated loopback traffic only; stop on non-test data, external requests,
retained proof or stale source bindings. Rollback removes this guided-client,
progress/QR and test/doc slice and rebuilds the P1c.5 auth entry. Preserve accepted
native passwords, factors, admissions, sessions, audit and workflow records; no
schema reversal or operational data restore applies.

- INDEX_VERSION: browser-react-ads-decision-9 / P1c.6 / 20 October 2026; ADR 0068;
  plan revision 16. Earlier sections retain their historical counts/scope.
- FILE_MAP_SUMMARY: existing auth client; enrollment/setup progress and native QR; JSON-only native
  flash handling;
  native/regression test extension; candidate bindings and canonical handoff docs.
- OPEN_QUESTIONS: delivery/support, PostgreSQL/cache/privacy, production static/
  origin/CSP, device/assistive/backup and M0/M1 acceptance.
- KNOWN_RISKS: local guided integration is not operational provisioning or workflow
  authority; lost one-time codes/session need the verified support procedure.
- GLOSSARY_DELTA: existing React browser client definition extended.
- NEXT_READ_QUEUE: readiness/staging acceptance for M1, then Complaints read.
