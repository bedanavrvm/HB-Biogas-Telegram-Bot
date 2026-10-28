# Browser dependency and asset decision

Decision: 20 October 2026, under the user's instruction **"resolve it and
proceed"**. Local installation/build of this bounded React/ADS workspace is
authorized. This is an engineering dependency decision, not legal advice,
production deployment authority or approval of every ADS material.

## Exact scope and why it is needed

P1c.5's separate closed-authentication build (ADR 0067) reuses this exact graph,
review/lock and asset exclusions. It introduces no package, archive or override.
The synthetic preview and closed native-transport bundles are separately
inventoried; notices and the same graph/brand/font/image guards apply to both.
Decision section 11 and browser/README.md record its isolated testing boundary.

### Current composition correction — P1c.4

The user instructed "fix the issues ... always refer to the atlassian docs"
after the documented design critique. ADR 0066 records this authorization and
why the existing primitive-only frame, popup message and button collections
could not fix the identified patterns. Exact direct additions:
navigation-system 11.3.1, side-nav-items 2.5.8, section-message 10.2.6 and select
23.1.3. The unused direct inline-message package is removed. See DESIGN.md for
official guidance and application-specific decisions.

The current graph contains **592 lock entries / 554 unique archives**: 504
inspections reused from the forensic base and 50 separate current inspections,
including 27 newly inspected archives for this correction. Lock-only resolution
preceded installation; SRI/identity/licence/asset/native/script inspection ran
before the scripts-disabled install. All 27 new archives declare Apache-2.0 or
MIT with complete licence files and no lifecycle scripts/native binaries.
Nested metadata consists of entrypoint/module declarations (including
description/private/jsnext:main), not an extra executable install step.

Navigation System's 24 documentation PNGs and the hitbox package's example JPEG
are excluded from emitted assets. Its transitive logo package contains brand
code; importing any @atlaskit/logo module is explicitly rejected by the build,
in addition to the existing font/image/native/brand-glyph exclusions. Only
generic component UI glyphs and company text are used. No proprietary asset
permission is inferred from package metadata.

The original-peer checker now verifies 171 installed peer declarations with
exactly the previous context exception, 75 absent optional platform packages
and one React renderer. The exact overrides and engine remain unchanged. The
post-install point-in-time npm audit reports zero findings across 592 entries.
Production/development notice and source-bound browser results are recorded in
BROWSER_REACT_ADS_DECISION.md section 10. None accepts production distribution,
real identity/provider transport or operational M1.

### Historical initial component workspace

`package.json` and `package-lock.json` are the authoritative exact versions.
React/ReactDOM 18.3.1, provider 8.1.0, button 25.5.0, reset 8.4.6, form 18.2.0,
heading 8.0.0, inline-message 16.4.8, primitives 22.6.0, textfield 10.2.6 and
tokens 20.6.1 implement the chosen access UI. A custom wireframe does not satisfy
the requested ADS implementation. No router or additional backend is needed.

Parcel/its core/default config 2.16.4 plus Compiled config 0.5.7 provide the
documented supported atomic-style pipeline. Compiled Babel 3.0.2, strip-runtime
3.0.3 and build-time Compiled React 2.0.0 are explicit development dependencies:
the Parcel transform resolves plugins from the application root. ADS keeps
its required nested Compiled React 1.0.2 runtime; this is not another React
renderer. These exact Compiled artifacts were already inspected in D13a.
TypeScript 5.9.3 and React 18 types
validate component contracts. ESLint 10.13.0 and the two ADS lint plugins check
design-system use. The MIT TypeScript parser 8.72.0 is necessary to lint TSX;
ESLint's default parser cannot parse TypeScript. Semver 7.8.5 validates original
installed peer declarations. New/changed archives for the supported linter and
selector-parser fix are separately SRI/identity/licence inspected.

P1c.2's full browser ADS adoption promotes `@atlaskit/css@1.1.7` and
`@atlaskit/visually-hidden@4.4.0` from already installed, inspected runtime
transitives to exact direct dependencies. The former supplies the supported
typed cssMap/xcss API for all layouts; the latter replaces custom hidden CSS.
No new archive/version/integrity, renderer or override is introduced. The lock's
root declarations and review digest change together. The user explicitly
requested full browser design adoption; ADR 0066 records this follow-up decision.

The initial P1c.1/P1c.2 graph had 555 lock entries / 528 unique archives. `dependency-review.json`
binds the exact lock to 505 prior integrity-inspected archives and 23 new
inspections. It does not relabel the historical forensic graph as installable.
Only the separate exact workspace and documented exception below are accepted.

Use Node **22.23.3** (`.nvmrc`, engines), not the system's Node 26. The local
official Windows distribution was SHA-256 verified before use. No system runtime
was replaced. `.npmrc` requires strict peers/engines and suppresses all dependency
lifecycle scripts. Installation does not run arbitrary postinstall commands.

## Exact compatibility exception

The React override is scoped to
`@atlaskit/analytics-next-stable-react-context@1.0.1`'s React edge, selecting
18.3.1. Its original published peer **^16.8.0 remains incompatible**; this is a
local engineering exception, never an upstream-support claim. The archive
SHA-256 is `a058cb454aa942577a4827c00f0763ee631fd84766e493d8c0a3912529efc1e2`.
The shipped context module creates a default context using `createContext`;
the consuming analytics-next 12.6.0 explicitly supports React ^18.2.0.
React documents that API; React 19 is excluded because other ADS peers require 18.

A fresh npm solve tried ReactDOM 19 for tooltip despite the direct ReactDOM 18
pin. Reusing the existing exact, integrity-pinned provider choices let npm
strictly revalidate the graph with only the scoped context override. No global
React override, force or legacy-peer flag is used. The installed original-peer
checker must report exactly this exception, no second React renderer or hidden
incompatible/missing required peer. Actual context identity, provider/consumer,
StrictMode, form/button/input and failure/retry interactions are release checks
for this local build. Any additional mismatch blocks the build rather than being
automatically accepted. Re-review the exception on package/React upgrades.

The second override pins development-only `postcss-selector-parser` to fixed
7.1.6. The initial audit reported GHSA-rj75-hqrm-r3gf through Compiled/lint tools.
Their original 6.x dependency ranges have no patched release, so this deliberate
major-version selection requires parsing/API and actual Compiled build checks.
No parser executes on customer input or ships in the browser. The
[upstream advisory](https://github.com/advisories/GHSA-rj75-hqrm-r3gf) identifies
7.1.6 as fixed and distinguishes trusted build-time use from exposed parsers.
No advisory is ignored; retain the explicit final audit result in the handoff.

## Licence and notice handling

The [general ADS licence](https://atlassian.design/license/) distinguishes
identified OSS code in section 8. This workspace uses only exact npm packages
identified as OSS by their published declarations and shipped/source licences.
It does not rely on the general integrated-product grant to copy proprietary
ADS assets. Apache/MIT/ISC/BSD obligations are retained in generated readable
notices. No trademark right is inferred from a code licence.

The build copies the applicable shipped full licence/NOTICE texts and provenance
for runtime/actually bundled package code into `THIRD_PARTY_NOTICES.txt`. For the
four runtime archives missing a separate licence file, explicit declarations
are retained and paired with full standard terms and attribution:

| Exact package | Published declaration and notice source |
|---|---|
| platform-feature-flags 2.2.1 | Apache-2.0, Atlassian Pty Ltd; full terms retained from the same vendor's inspected button archive |
| top-layer 6.3.0 | Apache-2.0, Atlassian Pty Ltd; same full Apache terms and publisher attribution |
| @compiled/react 1.0.2 | Apache-2.0; official Compiled repository full licence and attribution retained in `notice-sources/` |
| @statsig/client-core 3.30.2 | ISC; official repository LICENSE at its published gitHead `45d4ad73f29c7ee37a3f664c40c37c5551301d8b`, retained in `notice-sources/` |

This resolves the local runtime notice-file omissions without pretending the
files were shipped in those tarballs. The 59 historical development-only
missing-file flags remain recorded in D13a; local tool execution is the accepted
scope. Tool/native-binary redistribution is excluded. Build tools, icon-lab,
Parcel/SWC/esbuild executables, MPL LightningCSS/parser tools and their sources
are not application assets. Any small emitted bundler/helper JavaScript is
included in the actual module inventory and receives its package's notices.
Distributing a build image/toolchain or modified covered
source requires that distribution's complete notice/source package and review.

Only company text/system fonts and generic OSS component glyphs are permitted.
No Atlassian logo, brand glyph, proprietary font, illustration, sticker sheet,
copied asset directory, Forge/Connect, Atlassian account or analytics account is
used. The emitted module graph and static files are checked for excluded assets
and brand-glyph modules. Theme identifiers such as `atlassian-light` are code
identifiers, not copied branding. Notices remain readable in the built preview.

Feature-gating/analytics code can be transitive component code; its presence is
not evidence of outbound traffic. The local preview permits no connections and
browser tests record/block unexpected network requests. Real staff data and
operational analytics/provider configuration remain excluded from this phase.

## Bounded Complaints UI additions (22 October 2026)

The user's UI correction and explicit AG Grid requirement add exact direct pins:
`@atlaskit/tabs@21.3.0`, `@atlaskit/icon@38.0.2`,
`@atlaskit/lozenge@17.0.6` and `ag-grid-community@36.1.0`.
Icon and Lozenge were already inspected transitive dependencies. The lock adds
five entries: Tabs, its nested Compiled runtime, AG Grid Community, ag-stack and
ag-charts-types. No existing dependency version is upgraded, and the root Mini
App package/lock is unchanged. ag-charts-types is a type dependency, not an
installed charts renderer. AG Grid and its dependencies declare MIT; Tabs and
Compiled declare Apache-2.0. No new lifecycle script is accepted.

`scripts/review_complaints_ui_dependencies.py` reuses the standard-library
archive inspector, validates exact registry integrities and emits a review
patch. Archives are inspected in a temporary directory, never executed.
The resulting manifest binds this local build, not production distribution.
Build notices attribute nested package roots rather than misleading nested
export descriptors; exact inspected licence hashes remain checked.

The original-peer check now checks 173 installed declarations, still exactly
one previously documented context exception, 75 absent platform options and
one React renderer. Modal Dialog was investigated but not installed: its
transitive React-scrolllock peer does not support this React version. No
force/legacy-peer installation or new exception is used. The native dialog
composition exception is described in DESIGN.md. No fonts, logos or images
are introduced. Human acceptance and operational release gates remain open.

## Maintenance and release boundary

The repository maintainer owns this isolated workspace's pinned build and
dependency review; an operational primary/backup assignment remains required
before M1. Exact graph/source/licence changes invalidate the review binding.
Production distribution, real-browser authentication, cookie/CSRF integration,
mail/recovery/cache/privacy/support and staging acceptance remain separate gates.
Neither local installation nor this document approves production activation.

## Historical P1c.1 local acceptance

- Clean offline `npm ci` with scripts disabled and the original-peer checker pass:
  134 installed peer declarations, exactly the recorded context exception,
  one React/ReactDOM 18.3.1 renderer and 75 absent optional platform packages.
- React context singleton/default/provider/consumer in StrictMode and selector
  API regression checks pass. TypeScript and both ADS lint plugins' recommended
  error-level rules pass with the explicit native-layout exception.
- The explicit browser production target bundles the actual dependencies:
  25 output assets, 52 attributed/noticed packages, 1,193,784 uncompressed bytes
  including notices/all emitted theme chunks. This is a review measurement,
  not a performance target or proof all chunks are requested initially.
- Production and development StrictMode browser runs each passed 79 checks and
  produced 71 synthetic captures in separate ignored directories. No
  external requests, console errors, cookies or local/session storage were
  observed. A native feature-gate warning says its client is uninitialized;
  no feature/analytics client or key is initialized to silence it. This is not
  proof of all future operational data flows or upstream compatibility.
- `npm audit` after the supported-linter/parser fix reports zero vulnerabilities
  for this exact graph. It is a point-in-time registry result, not a security
  certification. Deprecated transitive `stable@0.1.8` and
  `@atlaskit/theme@28.2.5` remain vendor component dependencies; no direct use of
  deprecated theme APIs is introduced. Revisit these during dependency upgrades.

The phase handoff in BROWSER_REACT_ADS_DECISION.md section 7 records commands,
diagnostic failures/corrections and unverified release work.

Current P1c.2 acceptance and measurements are in that document's section 8.
It replaces the native-layout/style exceptions above with all recommended ADS
lint rules enforced as errors, typed token styling and source-bound runtime
comparisons. The sole synthetic read-only field exception is line-scoped.
ADS typography tokens use their system-font fallbacks unchanged; font/image/
brand files remain excluded. Production and native-auth gates are unchanged.

References: [Atlassian setup](https://atlassian.design/get-started/develop/atlassians),
[React context](https://react.dev/reference/react/createContext), ADR 0066 and
`codebase-analysis-docs/assets/BROWSER_REACT_ADS_DECISION.md`.

The 28 October Complaints detail candidate also copies the Portal's existing
Leaflet 1.9.4 JavaScript, CSS and BSD licence into native operations builds.
`vendorSources` binds those exact source bytes to the served artifact hashes.
This adds no npm dependency or external script and does not enter synthetic
preview/demo graphs. See the [detail review](../docs/ui-standard/reviews/2026-10-28-complaints-stitch-detail.md).

## Reference typography (28 October 2026)

`vendor/inter/InterVariable.woff2` is the unmodified Inter 4.1 upright variable
font from the [official source](https://github.com/rsms/inter/tree/v4.1).
Its SIL Open Font License 1.1 is retained as `Inter-LICENSE.txt`; provenance and
upstream revision are in `vendor/inter/README.md`. This bounded font exception
to the earlier font exclusion implements the user's Stitch reference. Native
operations builds copy both files, bind source/output hashes in vendorSources,
and allow only same-origin fonts. Existing dependency locks and exclusions for
Atlassian brand/image/font assets remain.
