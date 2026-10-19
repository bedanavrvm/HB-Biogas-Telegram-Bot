# New browser frontend: React / Atlassian review gate

Decision date: 19 October 2026; D13a evidence follow-up on the same date. Governing decision: ADR 0062,
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
